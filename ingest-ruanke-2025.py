#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入软科 2025 中国大学专业排名 → ruanke_major,并匹配到 admission_lines 的(校,专业)→ ruanke_match。
ruanke_match 供 export-slices.py(切片 mg 字段)+ 选校助手/我的推荐 显示专业评级徽章。

匹配三级:① 精确(校,专业名)② 去括号后(法学(涉外班)→法学)③ 大类(**规范名以「类」结尾**)
配软科「专业类」取该校该类最佳评级(电子信息类(图灵班)→规范成电子信息类→软科电子信息类best)。
软科只收录头部约 1110 校 → 低分民办/职业校无评级(正常)。

需 pandas+openpyxl 读 xlsx。用法:
  python3 ingest-ruanke-2025.py [--xlsx 软科.xlsx] [--db gaokao.db] [--commit]
"""
import pandas as pd, sqlite3, re, argparse

GORD = {'A+': 4, 'A': 3, 'B+': 2, 'B': 1, 'C': 0}
def norm(m): return re.sub(r'[(（][^)）]*[)）]', '', m or '').strip()
def _i(v):
    try: return int(v)
    except (TypeError, ValueError): return None
def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default="/Users/zhangxiansheng/Downloads/2025软科中国大学专业排名Excel版.xlsx")
    ap.add_argument("--db", default="gaokao-data/gaokao.db")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    c = sqlite3.connect(args.db)

    if args.commit:
        df = pd.read_excel(args.xlsx, sheet_name='上榜名单')
        c.execute("DROP TABLE IF EXISTS ruanke_major")
        c.execute("""CREATE TABLE ruanke_major(uni_name TEXT,major_name TEXT,major_code TEXT,category TEXT,
            major_class TEXT,grade TEXT,rank INTEGER,score REAL,year INTEGER DEFAULT 2025)""")
        c.executemany("""INSERT INTO ruanke_major(uni_name,major_name,major_code,category,major_class,grade,rank,score)
            VALUES(?,?,?,?,?,?,?,?)""",
            [(r['学校名称'], r['专业名称'], str(r['专业代码']), r['门类'], r['专业类'], r['评级'], _i(r['排名']), _f(r['得分']))
             for _, r in df.iterrows()])
        c.execute("CREATE INDEX IF NOT EXISTS idx_ruanke ON ruanke_major(uni_name,major_name)")
        print(f"ruanke_major 入库 {len(df)} 行")

    exact, clsbest = {}, {}
    for u, m, g, rk in c.execute("SELECT uni_name,major_name,grade,rank FROM ruanke_major"):
        exact[(u, m)] = (g, rk)
    for u, cls, g, rk in c.execute("SELECT uni_name,major_class,grade,rank FROM ruanke_major"):
        k = (u, cls)
        if k not in clsbest or GORD.get(g, -1) > GORD.get(clsbest[k][0], -1): clsbest[k] = (g, rk)

    out = []
    for u, m in c.execute("""SELECT DISTINCT uni_name,major FROM admission_lines
                             WHERE granularity='major' AND major IS NOT NULL AND major!='院校投档线'"""):
        nm = norm(m)
        if (u, m) in exact:                                 g, rk = exact[(u, m)];   out.append((u, m, g, rk, 'exact'))
        elif (u, nm) in exact:                              g, rk = exact[(u, nm)];  out.append((u, m, g, rk, 'paren'))
        elif nm.endswith('类') and (u, nm) in clsbest:      g, rk = clsbest[(u, nm)]; out.append((u, m, g, rk, 'class'))
    from collections import Counter
    print(f"软科专业 {len(exact)} 条;匹配 admission(校,专业)→评级 {len(out)} 条;类型 {dict(Counter(o[4] for o in out))}")
    if not args.commit:
        print("=== DRY-RUN(未写库)。加 --commit ==="); return
    c.execute("DROP TABLE IF EXISTS ruanke_match")
    c.execute("CREATE TABLE ruanke_match(uni_name TEXT,major TEXT,grade TEXT,rank INTEGER,match_type TEXT)")
    c.executemany("INSERT INTO ruanke_match VALUES(?,?,?,?,?)", out)
    c.execute("CREATE INDEX idx_rkmatch ON ruanke_match(uni_name,major)")
    c.commit()
    print(f"已写库:ruanke_major + ruanke_match {len(out)} 条")

if __name__ == "__main__":
    main()
