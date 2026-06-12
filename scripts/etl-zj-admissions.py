#!/usr/bin/env python3
"""ETL: 浙江三份投档线 Excel -> admission_lines 表。

① 院校分数 2020-2024(校级,5 sheet)
② 2025 专业分(专业级,含提前批/一段/二段)
③ 2024 专业分(专业级)
'-' 一律转 NULL;院校名匹配 universities.id(剥校区括号辅助)。
"""
import os, re, sqlite3
import pandas as pd

DL = "/Users/zhangxiansheng/Downloads"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gaokao-data", "gaokao.db")
con = sqlite3.connect(DB)
con.executescript("""
DROP TABLE IF EXISTS admission_lines;
CREATE TABLE admission_lines(
  id INTEGER PRIMARY KEY,
  uni_id INTEGER REFERENCES universities(id),
  uni_name TEXT NOT NULL, uni_code TEXT,
  province TEXT NOT NULL DEFAULT '浙江', year INTEGER NOT NULL,
  batch TEXT, subject TEXT,
  granularity TEXT NOT NULL,             -- school | major
  major_code TEXT, major TEXT, major_note TEXT, sel_req TEXT,
  min_score REAL, min_rank INTEGER, avg_score REAL, avg_rank INTEGER,
  max_score REAL, enroll_n INTEGER, line_diff REAL,
  source TEXT
);
""")

num = lambda v: pd.to_numeric(v, errors="coerce")
strip_paren = lambda s: re.sub(r"[(（][^)）]*[)）]", "", str(s)).strip()
names = {n: i for i, n in con.execute("SELECT id,name FROM universities")}
def uid(name):
    if pd.isna(name): return None
    n = str(name).strip()
    return names.get(n) or names.get(strip_paren(n))

def ins(rows):
    con.executemany("""INSERT INTO admission_lines
      (uni_id,uni_name,uni_code,year,batch,subject,granularity,major_code,major,
       major_note,sel_req,min_score,min_rank,avg_score,avg_rank,max_score,
       enroll_n,line_diff,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)

def V(x):
    v = num(x)
    return None if pd.isna(v) else float(v)
def I(x):
    v = num(x)
    return None if pd.isna(v) else int(v)

# ① 校级 2020-2024
xl = pd.ExcelFile(os.path.join(DL, "Z浙江-2020-2024院校分数.xlsx"))
n1 = 0
for sh in xl.sheet_names:
    df = pd.read_excel(xl, sheet_name=sh)
    rows = []
    for r in df.itertuples():
        note = None if str(r.学校方向) == str(r.学校) else str(r.学校方向)
        rows.append((uid(r.学校), str(r.学校).strip(), str(r.招生代码), int(r.年份),
                     str(r.批次), str(r.科目), "school", None, None, note, None,
                     V(r.最低分), I(r.最低分位次), V(r.平均分), None, V(r.最高分),
                     I(r.录取人数), V(r.最低分线差), "zj-school-20-24"))
    ins(rows); n1 += len(rows)

# ③ 2024 专业级
df = pd.read_excel(os.path.join(DL, "Z浙江-专业分数-2024.xlsx"))
rows = []
for r in df.itertuples():
    rows.append((uid(r.学校), str(r.学校).strip(), str(r.招生代码), 2024,
                 str(r.批次), str(r.科目), "major", str(r.专业代码), str(r.专业).strip(),
                 None, str(r.选科要求) if pd.notna(r.选科要求) else None,
                 V(r.最低分), I(r.最低分位次), V(r.平均分), None, V(r.最高分),
                 I(r.录取人数), V(r.最低分线差), "zj-major-2024"))
ins(rows); n3 = len(rows)

# ② 2025 专业级
df = pd.read_excel(os.path.join(DL, "Z浙江-2025-专业分.xlsx"))
rows = []
for r in df.itertuples():
    rows.append((uid(r.院校名称), str(r.院校名称).strip(), str(r.院校代码), 2025,
                 str(r.批次), str(r.科类), "major", str(r.专业代码), str(r.专业名称).strip(),
                 str(r.专业备注) if pd.notna(r.专业备注) else None,
                 str(r.选科要求) if pd.notna(r.选科要求) else None,
                 V(r.最低分), I(r.最低位次), V(r.平均分), I(r.平均位次), None,
                 I(r.录取人数), None, "zj-major-2025"))
ins(rows); n2 = len(rows)

con.executescript("""
CREATE INDEX idx_adm_uni ON admission_lines(uni_id,year);
CREATE INDEX idx_adm_rank ON admission_lines(province,year,granularity,min_rank);
""")
con.commit()

print(f"校级 20-24: {n1} 行 / 专业级 2024: {n3} 行 / 专业级 2025: {n2} 行")
t, m = con.execute("SELECT COUNT(*),SUM(uni_id IS NOT NULL) FROM admission_lines").fetchone()
print(f"合计 {t:,} 行,院校匹配率 {m*100//t}%")
print(f"带最低位次: {con.execute('SELECT COUNT(*) FROM admission_lines WHERE min_rank IS NOT NULL').fetchone()[0]:,}")

# ===== 闭环演示:2024 浙江 650 分 -> 冲稳保 =====
rank = con.execute("""SELECT cum_rank FROM rank_tables
  WHERE province='浙江' AND year=2024 AND score_min<=650
  ORDER BY score_min DESC LIMIT 1""").fetchone()[0]
print(f"\n===== 演示:2024 浙江 650 分 → 位次 {rank:,} =====")
for label, lo, hi in [("冲", int(rank*0.82), rank),
                      ("稳", rank, int(rank*1.25)),
                      ("保", int(rank*1.25), int(rank*1.6))]:
    q = con.execute("""SELECT uni_name, major, min_score, min_rank
      FROM admission_lines
      WHERE province='浙江' AND year=2024 AND granularity='major'
        AND min_rank BETWEEN ? AND ? ORDER BY min_rank LIMIT 4""", (lo, hi)).fetchall()
    print(f"--{label}({lo:,}~{hi:,})")
    for u, mj, s, rk in q:
        print(f"   {u} · {mj} · {int(s)}分/位次{rk:,}")
con.close()
