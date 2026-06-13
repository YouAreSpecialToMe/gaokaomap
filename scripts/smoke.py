#!/usr/bin/env python3
"""30 省冒烟:每省每科类取 高(前5%)/中(30%)/低(60%) 三个分位分数跑引擎。

断言:无 error;冲稳保合计 ≥10 条视为健康,1-9 条为薄,0 条为失败。
"""
import os, sqlite3
from bisect import bisect_left
from recommend import engine, ALIAS, DB

con = sqlite3.connect(DB, timeout=30)
provs = {}
for p, s in con.execute("SELECT DISTINCT province,subject FROM rank_tables WHERE year=2025"):
    std = next((k for k, v in ALIAS.items() if s in v), None)
    if std: provs.setdefault(p, set()).add(std)

def score_at(prov, subj, pct):
    for cand in ALIAS[subj]:
        t = con.execute("""SELECT score_min,cum_rank FROM rank_tables
            WHERE province=? AND year=2025 AND subject=? ORDER BY cum_rank""",
            (prov, cand)).fetchall()
        if t:
            target = int(max(c for _, c in t) * pct)
            i = bisect_left([c for _, c in t], target)
            return t[min(i, len(t)-1)][0]
    return None

fail, thin, ok = [], [], 0
for prov in sorted(provs):
    for subj in sorted(provs[prov]):
        row = []
        for pct, tag in ((0.05, "高"), (0.30, "中"), (0.60, "低")):
            sc = score_at(prov, subj, pct)
            if sc is None: row.append(f"{tag}:无表"); continue
            r = engine(prov, subj, sc)
            if "error" in r:
                row.append(f"{tag}:ERR"); fail.append(f"{prov}{subj}{tag} {r['error'][:30]}")
                continue
            n = sum(len(v) for v in r["bands"].values())
            row.append(f"{tag}{sc}分:{n}条")
            if n == 0: fail.append(f"{prov}{subj}{tag}{sc}分 0条")
            elif n < 10: thin.append(f"{prov}{subj}{tag}{sc}分 {n}条")
            else: ok += 1
        print(f"{prov:4s}{subj}  " + "  ".join(row))
print(f"\n健康 {ok} | 薄 {len(thin)} | 失败 {len(fail)}")
if thin: print("薄:", "; ".join(thin[:12]))
if fail: print("失败:", "; ".join(fail[:12]))
