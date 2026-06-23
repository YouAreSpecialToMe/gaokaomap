#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补中国人民大学 2025 专业级录取线(官方招生网,合规)。

数据源:rdzs.ruc.edu.cn 的 POST /f/ajax_lnfs(CSRF + 时间头,与中科大同机制;一次返回全部省)。
官方只给最高/平均/最低分,**无位次** → min_rank 用本省 2025 一分一段按最低分换算(与华科/哈工大同法、
与引擎给考生算位次同口径;换算精度已由中科大官方位次交叉校验 0 误差证明)。
抓取 agent 已只留 本科一批 普通类(剔除 国家专项/中外合作/人大苏州/艺术/提前批)。

仅补「库里还没有人大 2025 专业级」的省(不动已有 11 省);幂等 source='ruc-2025-official'。
用法: python3 backfill-ruc-2025.py [--commit] [--json /tmp/ruc_2025.json] [--db ...]
"""
import json, sqlite3, argparse, statistics
from collections import Counter, defaultdict

UNI = "中国人民大学"; YEAR = 2025; SRC = "ruc-2025-official"; UNI_ID = 30

def std_to_rank_subject(subs, ss):
    if ss in subs: return ss
    alt = {"物理": "物理类", "历史": "历史类", "理科": "理科", "文科": "文科", "综合": "综合"}
    if ss in alt and alt[ss] in subs: return alt[ss]
    if len(subs) == 1: return next(iter(subs))
    return None

def map_subject(subs, kl):
    """人大科类(综合改革 | 物理类 | 历史类 | 理工 | 文史)→ (rank科类, al.subject, al.subject_std)。"""
    if "综合" in subs: return "综合", "综合", "综合"
    li = ("理" in kl) or ("物理" in kl)
    if li:
        if "物理类" in subs: return "物理类", "物理类", "物理"
        if "物理"   in subs: return "物理", "物理", "物理"
        if "理科"   in subs: return "理科", "理科", "理科"
    else:
        if "历史类" in subs: return "历史类", "历史类", "历史"
        if "历史"   in subs: return "历史", "历史", "历史"
        if "文科"   in subs: return "文科", "文科", "文科"
    return None, None, None

def is_clean(major):
    m = (major or "").strip()
    if not m or m.startswith("录取分数"): return False
    return not any(k in m for k in ("中外", "合作办学", "艺术"))

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
    ap.add_argument("--json", default="/tmp/ruc_2025.json")
    ap.add_argument("--db", default="gaokao-data/gaokao.db")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    c = sqlite3.connect(args.db)
    recs = [r for r in json.load(open(args.json, encoding="utf-8")) if int(r.get("year", YEAR)) == YEAR]
    print(f"解析:人大官方 2025 专业级 {len(recs)} 条,{len(set(r['province'] for r in recs))} 省")

    have = set(p for (p,) in c.execute(
        "SELECT DISTINCT province FROM admission_lines WHERE uni_name=? AND year=? AND granularity='major'", (UNI, YEAR)))
    print(f"库里已有人大 2025 专业级省({len(have)},跳过): {'、'.join(sorted(have))}")

    # ── 校验:用库里已有省真实 (min_score,min_rank) 验转换器(人大源无位次)──
    errs = defaultdict(list)
    for prov in sorted(have):
        subs = prov_subjects(c, prov)
        for sc, rk, ss in c.execute("""SELECT min_score,min_rank,subject_std FROM admission_lines
                WHERE uni_name=? AND year=? AND province=? AND granularity='major'
                AND min_score IS NOT NULL AND min_rank IS NOT NULL""", (UNI, YEAR, prov)):
            sj = std_to_rank_subject(subs, ss)
            if not sj: continue
            got = rank_of(c, prov, sj, sc)
            if got is not None:
                kind = "综合" if "综合" in subs else ("老高考" if ("理科" in subs or "文科" in subs) else "3+1+2")
                errs[kind].append(abs(got - rk))
    print("\n[校验] 转换器 vs 库里人大真实位次")
    for k, e in sorted(errs.items()):
        print(f"   {k:6} {len(e):3}例 中位|差| {int(statistics.median(e)):4} ≤20名 {sum(1 for x in e if x<=20)*100//len(e)}%")

    out, skip = [], Counter()
    for r in recs:
        prov = r["province"]
        if prov in have: continue
        if not is_clean(r["major"]): skip["非普通类(中外/艺术/汇总行)"] += 1; continue
        subs = prov_subjects(c, prov)
        if not subs: skip["无2025一分一段"] += 1; continue
        rsub, asub, astd = map_subject(subs, r["subject"])
        if not rsub: skip[f"科类跳过({r['subject']})"] += 1; continue
        mr = rank_of(c, prov, rsub, r["min_score"])
        if mr is None: skip[f"{prov}位次换算失败"] += 1; continue
        out.append({"prov": prov, "asub": asub, "astd": astd, "major": r["major"],
                    "ms": r["min_score"], "mr": mr, "avs": r.get("avg_score"),
                    "avr": rank_of(c, prov, rsub, r.get("avg_score")), "mxs": r.get("max_score"),
                    "en": r.get("enroll"), "batch": batch_for(c, prov, astd)})
    new = sorted(set(o["prov"] for o in out))
    print(f"\n待插入:{len(out)} 条 / {len(new)} 新省")
    print("   新省:", "、".join(new))
    if skip: print("   跳过:", dict(skip))

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
        [(UNI_ID, UNI, None, o["prov"], YEAR, o["batch"], o["asub"], None, o["major"], None,
          None, o["ms"], o["mr"], o["avs"], o["avr"], o["mxs"], o["en"], None, SRC, o["astd"]) for o in out])
    c.commit()
    after = c.execute("SELECT COUNT(*),COUNT(DISTINCT province) FROM admission_lines WHERE uni_name=? AND year=? AND granularity='major'", (UNI, YEAR)).fetchone()
    print(f"\n=== 已写库:删旧 {deleted}、插新 {len(out)}。人大 2025 专业级现 {after[0]} 条 / {after[1]} 省 ===")

if __name__ == "__main__":
    main()
