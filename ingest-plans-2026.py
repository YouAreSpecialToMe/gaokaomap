#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026 招生计划 → enrollment_plans(增量,按省·年 DELETE+INSERT;引擎 plan_factor 扩缩招修正用)。

卖家 xlsx(每省一文件):首行常是标题、第2行才是表头(自动探测含「院校名称」的行)。列:
年份/生源地/科类/计划类别/批次/选科/院校代码/院校名称/专业代码/专业名称/专业备注/计划人数/学制/学费。
院校名称去 [公办]/[民办] 等办学性质后缀(对齐 universities/admission_lines 命名,否则 plan_factor 跨年匹配不上)。

幂等:按出现的 (省,年) 先 DELETE 再 INSERT,不动其它年/省。需 pandas+openpyxl。
用法:python3 ingest-plans-2026.py <xlsx...> [--db ...] [--year 2026] [--source maijia-2026-plan] [--commit]
"""
import pandas as pd, sqlite3, re, argparse, os

MAP = {'年份': 'year', '生源地': 'province', '科类': 'subject', '计划类别': 'enroll_type', '批次': 'batch',
       '选科': 'sel_req', '院校代码': 'uni_code', '院校名称': 'uni_name', '专业代码': 'major_code',
       '专业名称': 'major', '专业备注': 'major_note', '计划人数': 'plan_n', '学制': 'years', '学费': 'tuition'}
OWNER = re.compile(r'[\[【（(](公办|民办|中外合作办学|内地与港澳台合作办学|境外合作办学|独立学院|军事)[\]】）)]')
def strip_owner(n): return OWNER.sub('', str(n)).strip()
def _i(v):
    try: return int(float(v))
    except (TypeError, ValueError): return None

def read_one(path):
    raw = pd.read_excel(path, header=None)
    hi = next((i for i in range(min(5, len(raw))) if any('院校名称' in str(v) for v in raw.iloc[i].tolist())), 0)
    return pd.read_excel(path, header=hi).rename(columns={c: MAP[c] for c in pd.read_excel(path, header=hi).columns if c in MAP})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('xlsx', nargs='+'); ap.add_argument('--db', default='gaokao-data/gaokao.db')
    ap.add_argument('--year', type=int, default=2026); ap.add_argument('--source', default='maijia-2026-plan')
    ap.add_argument('--commit', action='store_true')
    a = ap.parse_args()
    rows = []; combos = set()
    for path in a.xlsx:
        df = read_one(path)
        miss = [c for c in ('province', 'uni_name', 'major', 'plan_n') if c not in df.columns]
        if miss: print(f"  ✗ {os.path.basename(path)}: 缺列 {miss},跳过"); continue
        prov = str(df['province'].dropna().iloc[0]).strip()
        cnt = 0
        for _, r in df.iterrows():
            pn = _i(r['plan_n']); un = str(r.get('uni_name') or '').strip()
            if pn is None or not un: continue
            rows.append((strip_owner(un), str(r.get('uni_code') or ''), prov, a.year, str(r.get('subject') or ''),
                         str(r.get('batch') or ''), str(r.get('enroll_type') or ''), str(r.get('major') or ''),
                         str(r.get('major_code') or ''), str(r.get('major_note') or ''), str(r.get('sel_req') or ''),
                         pn, str(r.get('years') or ''), str(r.get('tuition') or ''), a.source))
            cnt += 1
        combos.add((prov, a.year)); print(f"  {prov}: {cnt} 行,{df['uni_name'].nunique()} 校")
    print(f"\n共 {len(rows)} 行,{len(combos)} 个 (省,年): {sorted(combos)}")
    if not a.commit:
        print("=== DRY-RUN(未写库)。加 --commit ==="); return
    c = sqlite3.connect(a.db)
    c.execute("BEGIN")
    for prov, yr in combos: c.execute("DELETE FROM enrollment_plans WHERE province=? AND year=?", (prov, yr))
    c.executemany("""INSERT INTO enrollment_plans
        (uni_name,uni_code,province,year,subject,batch,enroll_type,major,major_code,major_note,sel_req,plan_n,years,tuition,source)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    c.commit()
    print(f"✅ 入库 {len(rows)} 行 → {a.db}")

if __name__ == '__main__':
    main()
