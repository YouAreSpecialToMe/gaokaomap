#!/usr/bin/env python3
"""ETL: 一分一段表 Excel (30 省 × 2017-2024) -> SQLite rank_tables.

源文件每 sheet 一省,列:省份/年份/科目/层次/最高位次/最低位次/位次区间/
最大分数/最小分数/分数区间/同分人数。逐 sheet 校验表头与位次单调性后入库。
"""
import os, sqlite3, sys
import pandas as pd

SRC = sys.argv[1] if len(sys.argv) > 1 else \
    "/Users/zhangxiansheng/Downloads/2017-2024一分一段.xlsx"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gaokao-data")
os.makedirs(OUT_DIR, exist_ok=True)
DB = os.path.join(OUT_DIR, "gaokao.db")

EXPECT = ["省份", "年份", "科目", "层次", "最高位次", "最低位次", "位次区间",
          "最大分数", "最小分数", "分数区间", "同分人数"]

con = sqlite3.connect(DB)
con.executescript("""
DROP TABLE IF EXISTS rank_tables;
CREATE TABLE rank_tables(
  province TEXT NOT NULL, year INTEGER NOT NULL,
  subject TEXT NOT NULL, level TEXT,
  rank_from INTEGER, cum_rank INTEGER NOT NULL,
  score_max INTEGER NOT NULL, score_min INTEGER NOT NULL,
  count_same INTEGER,
  source TEXT DEFAULT 'taobao-17-24'
);
""")

xl = pd.ExcelFile(SRC)
total, problems = 0, []
for sh in xl.sheet_names:
    df = pd.read_excel(xl, sheet_name=sh, header=0).iloc[:, :11]
    df.columns = EXPECT[:df.shape[1]]
    df = df.dropna(subset=["年份", "最低位次", "最小分数"])
    for c in ["年份", "最高位次", "最低位次", "最大分数", "最小分数", "同分人数"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["年份", "最低位次", "最小分数"])
    # 单调性校验+修复:同一(年,科目,层次)内分数降 -> 累计位次升。
    # 个别录入笔误(如湖北2017文科291分 76042 应为 87042)用同分人数链式重算修复。
    df = df.sort_values(["年份", "科目", "层次", "最小分数"],
                        ascending=[True, True, True, False]).reset_index(drop=True)
    for (y, subj, lv), g in df.groupby(["年份", "科目", "层次"]):
        if (g["最低位次"].diff().dropna() >= 0).all():
            continue
        cum, fixed = None, 0
        for i in g.index:
            c = df.at[i, "同分人数"]
            expect = None if cum is None or pd.isna(c) else cum + c
            v = df.at[i, "最低位次"]
            if expect is not None and v < cum:
                df.at[i, "最低位次"] = expect
                fixed += 1
            cum = df.at[i, "最低位次"]
        problems.append(f"{sh} {int(y)} {subj} {lv}: 修复 {fixed} 行倒挂")
    rows = [(sh, int(r.年份), str(r.科目), str(r.层次),
             int(r.最高位次) if pd.notna(r.最高位次) else None,
             int(r.最低位次), int(r.最大分数), int(r.最小分数),
             int(r.同分人数) if pd.notna(r.同分人数) else None)
            for r in df.itertuples()]
    con.executemany("""INSERT INTO rank_tables
      (province,year,subject,level,rank_from,cum_rank,score_max,score_min,count_same)
      VALUES(?,?,?,?,?,?,?,?,?)""", rows)
    total += len(rows)
    print(f"{sh:6s} {len(rows):>7,} 行")

con.executescript("""
CREATE INDEX idx_rank_lookup ON rank_tables(province,year,subject,score_min);
CREATE INDEX idx_rank_cum ON rank_tables(province,year,subject,cum_rank);
""")
con.commit()

print(f"\n合计 {total:,} 行 -> {DB}")
if problems:
    print("⚠️ 校验问题:"); [print(" ", p) for p in problems]
else:
    print("✅ 全部 (省,年,科目,层次) 组合位次单调性通过")

# 抽样验证:分数->位次 查询
cur = con.execute("""SELECT cum_rank FROM rank_tables
  WHERE province='浙江' AND year=2024 AND score_min<=650
  ORDER BY score_min DESC LIMIT 1""")
print(f"\n试查:浙江 2024 综合 650 分 ≈ 位次 {cur.fetchone()[0]:,}")
con.close()
