#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fix admission_lines.min_rank rows whose stored 位次 is grossly inconsistent with
their min_score (some source xlsx shipped 位次 referencing a ~3-5x-too-large pool, or
too small). The authoritative field is min_score; the correct min_rank is the cumulative
rank that min_score maps to in that (province, year, subject) 一分一段 (rank_tables) —
exactly what the recommend engine uses for the student's own score. A wrong (inflated)
min_rank makes a high-score 本科 fall into a low-achiever's rank band → recommended as
够不到的「稳/保」(the "低于本科线/位次靠后却推荐高分本科" bug).

Targeted + idempotent + reversible:
  - Only rows where stored/implied > THRESH or < 1/THRESH (default 2x) are touched —
    leaves the already-correct majority in the same files untouched. Re-running is a no-op.
  - Skips rows with no min_score, or where the (prov,year,subject) 一分一段 is missing,
    or score below the table floor (can't derive a rank).
  - --commit backs up every (rowid, old min_rank) to <db>.rankfix-backup.json first.
    Rollback: UPDATE admission_lines SET min_rank=:old WHERE rowid=:rowid for each entry.

Usage:  python -X utf8 scripts/fix-rank-consistency.py [--db PATH] [--thresh 2.0] [--commit]
        (no --commit = dry-run: prints scope + examples, writes nothing)
"""
import sqlite3, sys, os, json
from bisect import bisect_right

DB = None
THRESH = 2.0
COMMIT = "--commit" in sys.argv
for i, a in enumerate(sys.argv):
    if a == "--db" and i + 1 < len(sys.argv): DB = sys.argv[i + 1]
    if a == "--thresh" and i + 1 < len(sys.argv): THRESH = float(sys.argv[i + 1])
if not DB:
    DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gaokao-data", "gaokao.db")

# subject_std -> rank_tables.subject aliases, first that has rows for (prov,year) wins
# (matches recommend.py ALIAS + old-regime 文科/理科; validated against the engine).
ALIAS = {
    "历史": ["历史类", "历史", "文科"], "物理": ["物理类", "物理", "理科"],
    "综合": ["综合", "综合改革"],
    "文科": ["文科", "文史", "历史类", "历史"], "理科": ["理科", "理工", "物理类", "物理"],
}

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# rank tables in memory: {(prov,year): {subject: ([scores...asc], [cum_ranks...])}}
print("loading rank_tables ...", flush=True)
RT = {}
for r in con.execute("SELECT province,year,subject,score_min,cum_rank FROM rank_tables ORDER BY province,year,subject,score_min"):
    d = RT.setdefault((r["province"], r["year"]), {}).setdefault(r["subject"], ([], []))
    d[0].append(r["score_min"]); d[1].append(r["cum_rank"])

def implied_rank(prov, year, subj_std, score):
    tbls = RT.get((prov, year))
    if not tbls or score is None: return None
    for cand in ALIAS.get(subj_std, [subj_std]):
        t = tbls.get(cand)
        if t:
            i = bisect_right(t[0], score) - 1
            return t[1][i] if i >= 0 else None   # below floor -> None
    return None

print("scanning admission_lines (granularity=major) ...", flush=True)
fixes = []   # (rowid, old, new, prov, year, subj, score)
nodata = below = nullscore = 0
for r in con.execute("SELECT rowid rid,province p,year y,subject_std s,min_score ms,min_rank mr FROM admission_lines WHERE granularity='major' AND min_rank IS NOT NULL"):
    if r["ms"] is None: nullscore += 1; continue
    ir = implied_rank(r["p"], r["y"], r["s"], r["ms"])
    if ir is None: below += 1; continue
    if ir <= 0 or r["mr"] <= 0: nodata += 1; continue
    ratio = r["mr"] / ir
    if ratio > THRESH or ratio < 1.0 / THRESH:
        fixes.append((r["rid"], r["mr"], ir, r["p"], r["y"], r["s"], r["ms"]))

from collections import Counter
grp = Counter((f[3], f[4]) for f in fixes)
print(f"\n=== inconsistent rows (>{THRESH}x or <{1/THRESH:.2f}x): {len(fixes)} ===")
print(f"(skipped: null min_score={nullscore}, below-floor/no-table={below}, zero-rank={nodata})")
print("top (province, year) groups:")
for (p, y), c in sorted(grp.items(), key=lambda x: -x[1])[:15]:
    print(f"  {p} {y}: {c}")
print("examples:")
for f in fixes[:8]:
    print(f"  {f[3]} {f[4]} {f[5]} | {f[3]}... score={f[6]} stored={f[1]} -> {f[2]} ({f[1]/f[2]:.2f}x)")

if not COMMIT:
    print(f"\nDRY-RUN — nothing written. Re-run with --commit to apply {len(fixes)} fixes.")
else:
    bak = DB + ".rankfix-backup.json"
    json.dump([{"rowid": f[0], "old": f[1]} for f in fixes], open(bak, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\nbacked up {len(fixes)} old min_rank values -> {bak}")
    con.executemany("UPDATE admission_lines SET min_rank=? WHERE rowid=?", [(f[2], f[0]) for f in fixes])
    con.commit()
    print(f"COMMITTED: recomputed min_rank for {len(fixes)} rows.")
con.close()
