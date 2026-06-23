#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补中国科学技术大学 2025 专业级录取线(官方招生网,合规)。

数据源:zsfw.ustc.edu.cn 的 /f/ajax_lnfs(需 Csrf-Token + X-Requested-Time 头;详见抓取脚本)。
中科大官方**自带位次 + 最高/平均分**;但为与华科/引擎口径统一,min_rank 仍用本省 2025 一分一段
按最低分换算(引擎给考生算位次也是这个口径 → 自洽),并把官方位次拿来**交叉校验**(应≈)。
最高/平均分按原值存,avg/max 位次也用一分一段换算。

输入:/tmp/ustc_2025.json(抓取 agent 产出;每条 province/subject/major/min_score/max_score/
avg_score/min_rank/enroll)。范围:仅补「库里还没有中科大 2025 专业级」的省(不动已有 11 省)。
幂等:source='ustc-2025-official',按校+年+源 DELETE+INSERT,可重跑。

用法: python3 backfill-ustc-2025.py [--commit] [--json /tmp/ustc_2025.json] [--db ...]
"""
import json, sqlite3, argparse, statistics
from collections import Counter, defaultdict

UNI = "中国科学技术大学"; YEAR = 2025; SRC = "ustc-2025-official"; UNI_ID = 212

def std_to_rank_subject(subs, ss):
    if ss in subs: return ss
    alt = {"物理": "物理类", "历史": "历史类", "理科": "理科", "文科": "文科", "综合": "综合"}
    if ss in alt and alt[ss] in subs: return alt[ss]
    if len(subs) == 1: return next(iter(subs))
    return None

def map_subject(subs, kl):
    """中科大 kl(物理类 | 综合改革 | 理工)→ (rank科类, al.subject, al.subject_std)。理工=新疆老高考。"""
    if "综合" in subs: return "综合", "综合", "综合"
    li = ("理" in kl) or ("物理" in kl)   # 中科大理工类高校,均为理
    if li:
        if "物理类" in subs: return "物理类", "物理类", "物理"
        if "物理"   in subs: return "物理", "物理", "物理"
        if "理科"   in subs: return "理科", "理科", "理科"
    else:
        if "历史类" in subs: return "历史类", "历史类", "历史"
        if "历史"   in subs: return "历史", "历史", "历史"
        if "文科"   in subs: return "文科", "文科", "文科"
    return None, None, None

def rank_of(c, prov, subj, score):
    if score is None: return None
    for sql, a in (
        ("SELECT cum_rank FROM rank_tables WHERE province=? AND year=? AND subject=? AND score_min<=? AND score_max>=? ORDER BY cum_rank LIMIT 1", (prov, YEAR, subj, score, score)),
        ("SELECT cum_rank FROM rank_tables WHERE province=? AND year=? AND subject=? AND score_max>=? ORDER BY score_max ASC LIMIT 1", (prov, YEAR, subj, score)),
        ("SELECT MIN(cum_rank) FROM rank_tables WHERE province=? AND year=? AND subject=?", (prov, YEAR, subj)),
    ):
        r = c.execute(sql, a).fetchone()
        if r and r[0] is not None: return int(r[0])
    return None

def batch_for(c, prov, subject_std):
    r = c.execute("""SELECT batch FROM admission_lines WHERE province=? AND year=? AND granularity='major'
                     AND subject_std=? AND batch IS NOT NULL GROUP BY batch ORDER BY COUNT(*) DESC LIMIT 1""",
                  (prov, YEAR, subject_std)).fetchone()
    return r[0] if r else "本科批"

def prov_subjects(c, prov):
    return set(r[0] for r in c.execute("SELECT DISTINCT subject FROM rank_tables WHERE province=? AND year=?", (prov, YEAR)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="/tmp/ustc_2025.json")
    ap.add_argument("--db", default="gaokao-data/gaokao.db")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    c = sqlite3.connect(args.db)
    recs = [r for r in json.load(open(args.json, encoding="utf-8")) if int(r.get("year", YEAR)) == YEAR]
    print(f"解析:中科大官方 2025 专业级 {len(recs)} 条,{len(set(r['province'] for r in recs))} 省")

    have = set(p for (p,) in c.execute(
        "SELECT DISTINCT province FROM admission_lines WHERE uni_name=? AND year=? AND granularity='major'", (UNI, YEAR)))
    print(f"库里已有中科大 2025 专业级省({len(have)},跳过): {'、'.join(sorted(have))}")

    # ── 交叉校验:官方位次 vs 一分一段换算(应≈;验证两套口径一致)──
    xc = defaultdict(list)
    for r in recs:
        if r.get("min_rank") is None: continue
        subs = prov_subjects(c, r["province"])
        if not subs: continue
        rsub, _, _ = map_subject(subs, r["subject"])
        if not rsub: continue
        got = rank_of(c, r["province"], rsub, r["min_score"])
        if got is not None:
            kind = "综合" if "综合" in subs else ("老高考" if ("理科" in subs or "文科" in subs) else "3+1+2")
            xc[kind].append(abs(got - r["min_rank"]))
    print("\n[交叉校验] 一分一段换算 vs 官方位次(应≈,证明换算口径对)")
    for k, e in sorted(xc.items()):
        print(f"   {k:6} {len(e):3}例  中位|差| {int(statistics.median(e)):4}  ≤20名 {sum(1 for x in e if x<=20)*100//len(e)}%")

    # ── 组装(只新省)──
    out, skip = [], Counter()
    for r in recs:
        prov = r["province"]
        if prov in have: continue
        subs = prov_subjects(c, prov)
        if not subs: skip["无2025一分一段"] += 1; continue
        rsub, asub, astd = map_subject(subs, r["subject"])
        if not rsub: skip[f"{prov}科类映射失败({r['subject']})"] += 1; continue
        mr = rank_of(c, prov, rsub, r["min_score"])
        if mr is None: skip[f"{prov}位次换算失败"] += 1; continue
        out.append({"prov": prov, "asub": asub, "astd": astd, "rsub": rsub,
                    "code": r.get("major_code"), "major": r["major"],
                    "ms": r["min_score"], "mr": mr,
                    "avs": r.get("avg_score"), "avr": rank_of(c, prov, rsub, r.get("avg_score")),
                    "mxs": r.get("max_score"),
                    "en": r.get("enroll"), "batch": batch_for(c, prov, astd)})
    new = sorted(set(o["prov"] for o in out))
    print(f"\n待插入:{len(out)} 条 / {len(new)} 新省")
    print("   新省:", "、".join(new))
    if skip: print("   跳过:", dict(skip))

    # 单调性自检(每省每科)
    print("\n[单调性自检] 每省·每科")
    perp = defaultdict(list)
    for o in out: perp[(o["prov"], o["asub"])].append(o)
    bad = []
    for prov in new:
        segs = []
        for (p, asub) in sorted(k for k in perp if k[0] == prov):
            items = sorted(perp[(p, asub)], key=lambda x: -x["ms"])
            ranks = [x["mr"] for x in items]
            mono = all(ranks[i] <= ranks[i+1] for i in range(len(ranks)-1))
            if not mono: bad.append((prov, asub))
            segs.append(f"{asub}{len(items)}条 位{min(ranks)}-{max(ranks)} {'✓' if mono else '✗'}")
        print(f"   {prov:5} {'  '.join(segs)}")
    print("   " + ("⚠ 非单调:" + str(bad) if bad else "✓ 各省各科均单调"))

    if not args.commit:
        print("\n=== DRY-RUN(未写库)。确认后加 --commit ==="); return
    cur = c.cursor()
    cur.execute("DELETE FROM admission_lines WHERE uni_name=? AND year=? AND source=?", (UNI, YEAR, SRC))
    deleted = cur.rowcount
    cur.executemany("""INSERT INTO admission_lines
        (uni_id,uni_name,uni_code,province,year,batch,subject,granularity,major_code,major,major_note,
         sel_req,min_score,min_rank,avg_score,avg_rank,max_score,enroll_n,line_diff,source,subject_std)
        VALUES (?,?,?,?,?,?,?,'major',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(UNI_ID, UNI, None, o["prov"], YEAR, o["batch"], o["asub"], o["code"], o["major"], None,
          None, o["ms"], o["mr"], o["avs"], o["avr"], o["mxs"], o["en"], None, SRC, o["astd"]) for o in out])
    c.commit()
    after = c.execute("SELECT COUNT(*),COUNT(DISTINCT province) FROM admission_lines WHERE uni_name=? AND year=? AND granularity='major'", (UNI, YEAR)).fetchone()
    print(f"\n=== 已写库:删旧 {deleted}、插新 {len(out)}。中科大 2025 专业级现 {after[0]} 条 / {after[1]} 省 ===")

if __name__ == "__main__":
    main()
