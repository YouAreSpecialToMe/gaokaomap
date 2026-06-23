#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兜底:把清北复交浙交的官方院校级投档线"提升"为可推荐条目,让它们在更多省的「我的推荐」出现。

背景:这 5 校按大类招生,真·大类线只在卖家专业分数线 xlsx(现有 11 省),官方招生网只发到院校/
批次级投档线、抓不到大类(故不能像华科那样自动抓)。本脚本**不抓外部数据,纯库内变换**:对这 5 校、
在「库里还没有 2025 大类(major)数据」的省,取其官方院校级(school)**普通本科批**投档线
(排除提前批/国家专项/特殊类型/高校专项等;每省每科类取最低分=门槛),提升成 granularity='major'
的可推荐条目,major='院校投档线'(明确标注非分大类)。

⚠ 代价:投档线级、科类标签、和现有大类省粒度不一致,且投档线是最低档偏乐观——**仅兜底**;
等卖家更全的 2025 专业分数线到位后,应删掉本源、用真大类替换。
幂等 source='toudang-promote-2025'。用法: python3 promote-toudang-2025.py [--commit] [--db ...]
"""
import sqlite3, argparse
from collections import Counter

SCHOOLS = ['清华大学', '北京大学', '复旦大学', '上海交通大学', '浙江大学']
YEAR = 2025; SRC = 'toudang-promote-2025'
SPECIAL = ('提前', '专项', '特殊', '强基', '零志愿', '农村', '南疆', '援疆', '艺术', '体育', '民族', '中外', '对口', '定向')

def is_main(batch):
    b = batch or ''
    return bool(b) and not any(s in b for s in SPECIAL)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="gaokao-data/gaokao.db")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    c = sqlite3.connect(args.db)
    out = []
    batches_used = Counter()
    for uni in SCHOOLS:
        uid = c.execute("SELECT uni_id FROM admission_lines WHERE uni_name=? LIMIT 1", (uni,)).fetchone()
        uid = uid[0] if uid else None
        have = set(p for (p,) in c.execute(
            "SELECT DISTINCT province FROM admission_lines WHERE uni_name=? AND year=? AND granularity='major'", (uni, YEAR)))
        best = {}  # (prov,subj) -> 最低分那行
        for prov, subj, sstd, batch, ms, mr in c.execute(
                """SELECT province, subject, subject_std, batch, min_score, min_rank
                   FROM admission_lines WHERE uni_name=? AND year=? AND granularity='school'
                     AND min_score IS NOT NULL AND min_rank IS NOT NULL""", (uni, YEAR)):
            if prov in have or not is_main(batch):
                continue
            k = (prov, subj)
            if k not in best or ms < best[k][3]:
                best[k] = (prov, subj, sstd or subj, ms, mr, batch)
        for v in best.values():
            batches_used[v[5]] += 1
            out.append((uid, uni, *v))

    print("提升计划(各校在『大类缺、院校级有』的省补投档线条目):")
    for uni in SCHOOLS:
        rows = [o for o in out if o[1] == uni]
        provs = sorted(set(o[2] for o in rows))
        print(f"  {uni}: +{len(rows)} 条 / {len(provs)} 省")
    print(f"\n合计 {len(out)} 条;用到的批次:", dict(batches_used))
    print("抽样:")
    for o in out[:10]:
        print(f"  {o[1]} {o[2]} {o[3]}  {o[5]}分/{o[6]}位  [{o[7]}]")

    if not args.commit:
        print("\n=== DRY-RUN(未写库)。确认后加 --commit ==="); return
    cur = c.cursor()
    cur.execute("DELETE FROM admission_lines WHERE source=?", (SRC,))
    deleted = cur.rowcount
    cur.executemany("""INSERT INTO admission_lines
        (uni_id,uni_name,uni_code,province,year,batch,subject,granularity,major_code,major,major_note,
         sel_req,min_score,min_rank,avg_score,avg_rank,max_score,enroll_n,line_diff,source,subject_std)
        VALUES (?,?,?,?,?,?,?,'major',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(uid, uni, None, prov, YEAR, batch, subj, None, '院校投档线', '按院校投档线提升(非分大类,门槛参考)',
          None, ms, mr, None, None, None, None, None, SRC, sstd)
         for (uid, uni, prov, subj, sstd, ms, mr, batch) in out])
    c.commit()
    print(f"\n=== 已写库:删旧 {deleted}、插新 {len(out)} ===")

if __name__ == "__main__":
    main()
