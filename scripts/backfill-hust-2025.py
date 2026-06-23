#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补华中科技大学 2025 专业级录取线(官方招生网,合规)。

数据源:https://zsb.hust.edu.cn/bkzn/fsfzyfsx.htm 内嵌 `var year_listObject={...}`。
官方只给最低分(zdf),无位次 → 用本省 2025 一分一段(rank_tables)把分→位次换算,
与推荐引擎给考生算位次的口径一致(自洽)。

范围:仅 lx='普通类' 的专业级行;只补「库里还没有华科 2025 专业级」的省(不动已有的 11 省)。
幂等:source='hust-2025-official',按 (省) 先 DELETE 该源再 INSERT,可反复重跑。

用法:
  python3 backfill-hust-2025.py            # dry-run:解析+校验+列出将插入什么,不写库
  python3 backfill-hust-2025.py --commit   # 真正写库
  python3 backfill-hust-2025.py --html /tmp/huake.html --db gaokao-data/gaokao.db
"""
import re, json, sqlite3, argparse, os, statistics
from collections import Counter, defaultdict

UNI = "华中科技大学"; YEAR = 2025; SRC = "hust-2025-official"; UNI_ID = 259

def parse_year_object(path, year="2025"):
    html = open(path, "rb").read().decode("utf-8", "replace")
    i = html.find("year_listObject"); i = html.find("{", i)
    depth = 0
    for k in range(i, len(html)):
        depth += (html[k] == "{") - (html[k] == "}")
        if depth == 0:
            j = k; break
    return json.loads(html[i:j+1])[year]

def prov_subjects(c, prov):
    return set(r[0] for r in c.execute(
        "SELECT DISTINCT subject FROM rank_tables WHERE province=? AND year=?", (prov, YEAR)))

def std_to_rank_subject(subs, ss):
    """admission_lines.subject_std(物理/历史/理科/文科/综合)→ 该省 rank_tables 的科类标签。"""
    if ss in subs: return ss
    alt = {"物理": "物理类", "历史": "历史类", "理科": "理科", "文科": "文科", "综合": "综合"}
    if ss in alt and alt[ss] in subs: return alt[ss]
    if len(subs) == 1: return next(iter(subs))
    return None

def map_subject(subs, kl):
    """华科 kl(理工/物理类 | 文史/历史类 | 综合改革)→ (rank_tables科类, al.subject, al.subject_std)"""
    if "综合" in subs:
        return "综合", "综合", "综合"
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

def rank_of(c, prov, subj, score):
    """某省某科 2025 一分一段:分数→位次(cum_rank)。精确分档优先,空档取最近的上一档。"""
    for sql, a in (
        ("SELECT cum_rank FROM rank_tables WHERE province=? AND year=? AND subject=? AND score_min<=? AND score_max>=? ORDER BY cum_rank LIMIT 1", (prov, YEAR, subj, score, score)),
        ("SELECT cum_rank FROM rank_tables WHERE province=? AND year=? AND subject=? AND score_max>=? ORDER BY score_max ASC LIMIT 1", (prov, YEAR, subj, score)),
        ("SELECT MIN(cum_rank) FROM rank_tables WHERE province=? AND year=? AND subject=?", (prov, YEAR, subj)),
    ):
        r = c.execute(sql, a).fetchone()
        if r and r[0] is not None:
            return int(r[0])
    return None

def batch_for(c, prov, subject_std):
    r = c.execute("""SELECT batch FROM admission_lines WHERE province=? AND year=? AND granularity='major'
                     AND subject_std=? AND batch IS NOT NULL
                     GROUP BY batch ORDER BY COUNT(*) DESC LIMIT 1""", (prov, YEAR, subject_std)).fetchone()
    return r[0] if r else "本科批"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default="/tmp/huake.html")
    ap.add_argument("--db", default="gaokao-data/gaokao.db")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    c = sqlite3.connect(args.db)

    rows = [r for r in parse_year_object(args.html) if r.get("lx") == "普通类"]
    print(f"解析:华科官网 2025 普通类专业级 {len(rows)} 条,{len(set(r['sf'] for r in rows))} 省")

    have = set(p for (p,) in c.execute(
        "SELECT DISTINCT province FROM admission_lines WHERE uni_name=? AND year=? AND granularity='major'",
        (UNI, YEAR)))
    print(f"库里已有华科 2025 专业级的省({len(have)},跳过): {'、'.join(sorted(have))}")

    # ── 校验闸门:用库里已有省的真实 (min_score,min_rank) 验转换器口径 ──
    print("\n[校验] 转换器在『已有省』上:官方分算位次 vs 库里真实位次")
    by_kind = defaultdict(list)
    for prov in sorted(have):
        subs = prov_subjects(c, prov)
        kind = "综合" if "综合" in subs else ("老高考" if ("理科" in subs or "文科" in subs) else "3+1+2")
        db = c.execute("""SELECT min_score,min_rank,subject_std FROM admission_lines
                          WHERE uni_name=? AND year=? AND province=? AND granularity='major'
                          AND min_score IS NOT NULL AND min_rank IS NOT NULL""", (UNI, YEAR, prov)).fetchall()
        for sc, rk, ss in db:
            sj = std_to_rank_subject(subs, ss)
            if sj is None:
                continue
            got = rank_of(c, prov, sj, sc)
            if got is not None:
                by_kind[kind].append(abs(got - rk))
    for kind, errs in sorted(by_kind.items()):
        if errs:
            med = int(statistics.median(errs)); within = sum(1 for e in errs if e <= 20)
            print(f"   {kind:6} {len(errs):3}例  中位误差 {med:4}  ≤20名占 {within*100//len(errs)}%")
    print("   (3+1+2/老高考 应≈0;综合省口径差属定义性,见脚本头注)")

    # ── 组装待插入(只新省)──
    todo = [r for r in rows if r["sf"] not in have]
    out, skipped = [], Counter()
    for r in todo:
        prov, kl, zdf = r["sf"], r["kl"], r.get("zdf")
        subs = prov_subjects(c, prov)
        if not subs:
            skipped["该省无2025一分一段"] += 1; continue
        rsub, asub, astd = map_subject(subs, kl)
        if rsub is None:
            skipped[f"{prov}:科类映射失败({kl}/{subs})"] += 1; continue
        try:
            sc = float(zdf)
        except (TypeError, ValueError):
            skipped["最低分缺失"] += 1; continue
        rk = rank_of(c, prov, rsub, sc)
        if rk is None:
            skipped[f"{prov}:位次换算失败"] += 1; continue
        out.append((prov, asub, astd, r.get("zydm"), r.get("zymc"), r.get("bz") or None,
                    sc, rk, batch_for(c, prov, astd)))

    new_provs = sorted(set(o[0] for o in out))
    print(f"\n待插入:{len(out)} 条 / {len(new_provs)} 个新省")
    print("   新省:", "、".join(new_provs))
    if skipped:
        print("   跳过:", dict(skipped))

    # 单调性自检:每省·每科(跨科混排不可比 → 必须按科分组)分降序应位次升序
    print("\n[单调性自检] 每省·每科(分降序→位次升序)")
    perps = defaultdict(list)
    for o in out: perps[(o[0], o[1])].append(o)  # (prov, al.subject)
    bad = []
    for prov in new_provs:
        segs = []
        for (p, asub) in sorted(k for k in perps if k[0] == prov):
            items = sorted(perps[(p, asub)], key=lambda x: -x[6])
            ranks = [x[7] for x in items]
            mono = all(ranks[i] <= ranks[i+1] for i in range(len(ranks) - 1))
            if not mono: bad.append((prov, asub))
            segs.append(f"{asub}{len(items)}条 位{min(ranks)}-{max(ranks)} {'✓' if mono else '✗'}")
        print(f"   {prov:5} {'  '.join(segs)}")
    print("   " + ("⚠ 非单调:" + str(bad) if bad else "✓ 各省各科均单调,换算自洽"))

    if not args.commit:
        print(f"\n=== DRY-RUN(未写库)。确认无误后加 --commit ===")
        return

    cur = c.cursor()
    cur.execute("DELETE FROM admission_lines WHERE uni_name=? AND year=? AND source=?", (UNI, YEAR, SRC))
    deleted = cur.rowcount
    cur.executemany("""INSERT INTO admission_lines
        (uni_id,uni_name,uni_code,province,year,batch,subject,granularity,major_code,major,major_note,
         sel_req,min_score,min_rank,avg_score,avg_rank,max_score,enroll_n,line_diff,source,subject_std)
        VALUES (?,?,?,?,?,?,?,'major',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(UNI_ID, UNI, None, prov, YEAR, batch, asub, zydm, zymc, bz,
          None, sc, rk, None, None, None, None, None, SRC, astd)
         for (prov, asub, astd, zydm, zymc, bz, sc, rk, batch) in out])
    c.commit()
    after = c.execute("SELECT COUNT(DISTINCT province) FROM admission_lines WHERE uni_name=? AND year=? AND granularity='major'", (UNI, YEAR)).fetchone()[0]
    print(f"\n=== 已写库:删旧 {deleted}、插新 {len(out)}。华科 2025 专业级现覆盖 {after} 省 ===")

if __name__ == "__main__":
    main()
