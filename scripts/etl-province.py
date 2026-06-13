#!/usr/bin/env python3
"""通用省份 ETL(卖家"22-25 三件套"格式)。

用法: python3 etl-province.py <省份名> <文件夹路径>
吃:一分一段/{省}2025年的一分一段表.xlsx -> rank_tables
   22-25年全国高校在{省}的专业录取分数.xlsx -> admission_lines
   22-25年全国高校在{省}的招生计划.xlsx -> enrollment_plans
按省份 DELETE 后插入,幂等可重跑;college_data 赠品不在此处理。
"""
import os, re, sqlite3, sys
from bisect import bisect_right
import pandas as pd

PROV, ROOT = sys.argv[1], sys.argv[2]
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gaokao-data", "gaokao.db")
con = sqlite3.connect(DB)
num = lambda v: pd.to_numeric(v, errors="coerce")
def I(x):
    v = num(x); return None if pd.isna(v) else int(v)
def V(x):
    v = num(x); return None if pd.isna(v) else float(v)
S = lambda r, c: str(r[c]).strip() if c in r.index and pd.notna(r[c]) else None
strip_paren = lambda s: re.sub(r"[(（][^)）]*[)）]", "", str(s)).strip()
names = {n: i for i, n in con.execute("SELECT id,name FROM universities")}
def uid(name):
    if name is None: return None
    return names.get(name) or names.get(strip_paren(name))

# ① 一分一段 2025
f = os.path.join(ROOT, "一分一段", f"{PROV}2025年的一分一段表.xlsx")
if os.path.exists(f):
    con.execute("DELETE FROM rank_tables WHERE province=? AND year=2025", (PROV,))
    df = pd.read_excel(f)
    rows = []
    for _, r in df.iterrows():
        sc = str(r["分数(分)"]).strip()
        m = re.match(r"(\d+)\s*[-~—]\s*(\d+)", sc)
        if m: lo, hi = sorted((int(m.group(1)), int(m.group(2))))
        elif sc.replace(".", "").isdigit(): lo = hi = int(float(sc))
        else: continue
        cum = I(r["累计人数(人)"])
        if cum is None: continue
        m2 = re.match(r"(\d+)", str(r.get("排名区间", "")).strip())
        rows.append((PROV, 2025, str(r["科类"]).strip(), None,
                     int(m2.group(1)) if m2 else None, cum, hi, lo, I(r["本段人数(人)"])))
    con.executemany("""INSERT INTO rank_tables
      (province,year,subject,level,rank_from,cum_rank,score_max,score_min,count_same)
      VALUES(?,?,?,?,?,?,?,?,?)""", rows)
    print(f"rank_tables {PROV}2025: +{len(rows)}")

lookup = {}
for yr, subj, smin, cum in con.execute(
        "SELECT year,subject,score_min,cum_rank FROM rank_tables WHERE province=? "
        "ORDER BY year,subject,score_min", (PROV,)):
    lookup.setdefault((yr, str(subj).strip()), []).append((smin, cum))
ALIAS = {"物理类": ["物理类", "物理", "理科"], "历史类": ["历史类", "历史", "文科"],
         "物理": ["物理类", "物理", "理科"], "历史": ["历史类", "历史", "文科"]}
def derive(yr, subj, score):
    if score is None or subj is None: return None
    if any(k in subj for k in ("艺术", "体育", "音乐", "美术")): return None
    for cand in ALIAS.get(subj, [subj]):
        tbl = lookup.get((yr, cand))
        if tbl:
            ss = [t[0] for t in tbl]
            i = bisect_right(ss, score) - 1
            return tbl[i][1] if i >= 0 else None
    return None

# ② 专业录取分数
f = os.path.join(ROOT, f"22-25年全国高校在{PROV}的专业录取分数.xlsx")
if os.path.exists(f):
    con.execute("DELETE FROM admission_lines WHERE province=? AND granularity='major'", (PROV,))
    df = pd.read_excel(f)
    rows, derived = [], 0
    for _, r in df.iterrows():
        un = S(r, "院校名称")
        if not un: continue
        yr, subj, mn = I(r["年份"]), S(r, "科类"), V(r["最低分数"])
        rk = I(r["最低位次"]) if "最低位次" in df.columns else None
        if rk is None and mn is not None:
            rk = derive(yr, subj, mn)
            if rk is not None: derived += 1
        rows.append((uid(un), un, S(r, "院校代码"), PROV, yr, S(r, "批次"), subj, "major",
                     S(r, "专业代码"), S(r, "专业"), S(r, "专业备注"), S(r, "选科要求"),
                     mn, rk, None, None, None, I(r["录取人数"]), None,
                     f"{PROV}-22-25"))
    con.executemany("""INSERT INTO admission_lines
      (uni_id,uni_name,uni_code,province,year,batch,subject,granularity,major_code,
       major,major_note,sel_req,min_score,min_rank,avg_score,avg_rank,max_score,
       enroll_n,line_diff,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    print(f"admission_lines {PROV}: +{len(rows):,}(反推 {derived})")

# ③ 招生计划
f = os.path.join(ROOT, f"22-25年全国高校在{PROV}的招生计划.xlsx")
if os.path.exists(f):
    con.execute("DELETE FROM enrollment_plans WHERE province=?", (PROV,))
    df = pd.read_excel(f)
    rows = [(uid(S(r, "院校名称")), S(r, "院校名称"), S(r, "院校代码"), PROV,
             I(r["年份"]), S(r, "科类"), S(r, "批次"), S(r, "招生类型"),
             S(r, "专业名称"), S(r, "专业代码"), S(r, "所属专业组"), S(r, "专业备注"),
             S(r, "选科要求"), I(r["招生人数"]), S(r, "学制(年)"), V(r["学费(元)"]),
             f"{PROV}-22-25") for _, r in df.iterrows() if S(r, "院校名称")]
    con.executemany(f"""INSERT INTO enrollment_plans
      (uni_id,uni_name,uni_code,province,year,subject,batch,enroll_type,major,major_code,
       major_group,major_note,sel_req,plan_n,years,tuition,source)
      VALUES({','.join('?'*17)})""", rows)
    print(f"enrollment_plans {PROV}: +{len(rows):,}")

con.commit()
print("admission_lines 总量:", con.execute("SELECT COUNT(*) FROM admission_lines").fetchone()[0])
con.close()
