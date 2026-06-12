#!/usr/bin/env python3
"""ETL: 院校基础信息 Excel (3236 行全口径) -> SQLite universities + subject_eval.

评估结果列为第四轮学科评估的 JSON 片段({"name":"0101 哲学","value":"B+"},...),
'-' 表示未参评。重名行(军校更名/多校区)按非空字段数保留最完整一行。
"""
import json, os, re, sqlite3, sys
import pandas as pd

SRC = sys.argv[1] if len(sys.argv) > 1 else \
    "/Users/zhangxiansheng/Downloads/辅助表格-院校基础信息0601(2).xlsx"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gaokao-data", "gaokao.db")

df = pd.read_excel(SRC)
print(f"读入 {len(df)} 行")

# 重名去重:保留非空字段最多的一行
df["_filled"] = df.notna().sum(axis=1)
df = df.sort_values("_filled", ascending=False).drop_duplicates("学校名称").drop(columns="_filled")
print(f"按校名去重后 {len(df)} 行")

def pct(v):
    if pd.isna(v): return None
    m = re.search(r"[\d.]+", str(v))
    return float(m.group()) if m else None

def flag(v, truthy):
    if pd.isna(v): return 0
    return 1 if str(v).strip() in truthy else 0

con = sqlite3.connect(DB)
con.executescript("""
DROP TABLE IF EXISTS universities;
DROP TABLE IF EXISTS subject_eval;
CREATE TABLE universities(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, alias TEXT,
  rank INTEGER, province TEXT, city TEXT, type TEXT, affiliation TEXT,
  is_985 INTEGER DEFAULT 0, is_211 INTEGER DEFAULT 0, is_dfc INTEGER DEFAULT 0,
  is_art INTEGER DEFAULT 0, ownership TEXT, level TEXT,
  baoyan_rate REAL, master_pts INTEGER, doctor_pts INTEGER,
  founded TEXT, female_ratio REAL,
  phone TEXT, email TEXT, address TEXT, website TEXT, intro TEXT,
  national_majors TEXT, prov_majors TEXT,
  lng REAL, lat REAL,
  source TEXT DEFAULT 'taobao-0601'
);
CREATE TABLE subject_eval(
  uni_id INTEGER NOT NULL REFERENCES universities(id),
  code TEXT, discipline TEXT NOT NULL, grade TEXT NOT NULL
);
""")

evals, eval_fail = [], 0
rows = []
for _, r in df.iterrows():
    rows.append((
        r["学校名称"],
        r["新院校名称"] if pd.notna(r["新院校名称"]) and r["新院校名称"] != r["学校名称"] else None,
        int(r["排名"]) if pd.notna(r["排名"]) else None,
        r["所在省"], r.get("城市"), r.get("类型"), r.get("隶属单位"),
        flag(r["是否985"], {"985", "985.0"}),
        flag(r["是否211"], {"211", "211.0"}),
        flag(r["是否双一流"], {"双一流", "1"}),
        flag(r["是否艺术"], {"1", "是", "艺术"}),
        r.get("公私性质"), r.get("本科/专科"),
        pct(r.get("保研率")),
        int(r["硕士点（个）"]) if pd.notna(r.get("硕士点（个）")) else None,
        int(r["博士点（个）"]) if pd.notna(r.get("博士点（个）")) else None,
        str(r["成立时间"]) if pd.notna(r.get("成立时间")) else None,
        pct(r.get("女生比例")),
        r.get("招办电话"), r.get("电子邮箱"), r.get("通讯地址"),
        r.get("官网"), r.get("大学简介"),
        r.get("国家特色专业"), r.get("省特色专业"),
    ))
cols = ("name,alias,rank,province,city,type,affiliation,is_985,is_211,is_dfc,"
        "is_art,ownership,level,baoyan_rate,master_pts,doctor_pts,founded,"
        "female_ratio,phone,email,address,website,intro,national_majors,prov_majors")
con.executemany(
    f"INSERT INTO universities({cols}) VALUES({','.join('?'*25)})", rows)

ids = {n: i for i, n in con.execute("SELECT id,name FROM universities").fetchall()}
for _, r in df.iterrows():
    raw = r.get("评估结果")
    if pd.isna(raw) or str(raw).strip() in ("-", ""):
        continue
    try:
        items = json.loads("[" + str(raw) + "]")
        uid = ids[r["学校名称"]]
        for it in items:
            nm = str(it.get("name", "")).strip()
            m = re.match(r"(\d{4})\s*(.+)", nm)
            code, disc = (m.group(1), m.group(2)) if m else (None, nm)
            evals.append((uid, code, disc, str(it.get("value", "")).strip()))
    except Exception:
        eval_fail += 1
con.executemany("INSERT INTO subject_eval VALUES(?,?,?,?)", evals)
con.executescript("""
CREATE INDEX idx_uni_prov ON universities(province, level);
CREATE INDEX idx_eval_uni ON subject_eval(uni_id);
CREATE INDEX idx_eval_grade ON subject_eval(grade);
""")
con.commit()

print(f"universities: {con.execute('SELECT COUNT(*) FROM universities').fetchone()[0]} 行")
print(f"  985: {con.execute('SELECT COUNT(*) FROM universities WHERE is_985=1').fetchone()[0]}"
      f" / 211: {con.execute('SELECT COUNT(*) FROM universities WHERE is_211=1').fetchone()[0]}"
      f" / 双一流: {con.execute('SELECT COUNT(*) FROM universities WHERE is_dfc=1').fetchone()[0]}")
print(f"subject_eval: {len(evals)} 行(解析失败 {eval_fail} 行)")
print(f"  参评院校数: {con.execute('SELECT COUNT(DISTINCT uni_id) FROM subject_eval').fetchone()[0]}")
print(f"  A+ 学科数: {con.execute(chr(39).join(['SELECT COUNT(*) FROM subject_eval WHERE grade=','A+',''])).fetchone()[0]}")
q = con.execute("""SELECT u.name, COUNT(*) FROM subject_eval e
  JOIN universities u ON u.id=e.uni_id WHERE e.grade='A+'
  GROUP BY u.id ORDER BY 2 DESC LIMIT 5""").fetchall()
print("  A+ 最多:", q)
con.close()
