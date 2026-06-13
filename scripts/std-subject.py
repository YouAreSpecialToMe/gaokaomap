#!/usr/bin/env python3
"""科类标准化:admission_lines.subject -> subject_std。

标准值:物理 / 历史 / 理科 / 文科 / 综合 / 艺术 / 体育 / 民族语言 / 其他 / 未知。
NULL 科类:按 (省,年) 内非空标准值的众数填充(占比>=90% 才填,否则记"未知")。
理科≠物理(不同选拔体制,等效换算留给查询层)。幂等可重跑。
"""
import os, re, sqlite3

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gaokao-data", "gaokao.db")
con = sqlite3.connect(DB, timeout=120)
try:
    con.execute("ALTER TABLE admission_lines ADD COLUMN subject_std TEXT")
except sqlite3.OperationalError:
    pass

ART = re.compile(r"艺术|美术|音乐|舞蹈|表演|表\(导\)演|表导演|播音|书法|编导|戏剧|影视")
def std(s):
    if s is None: return None
    t = str(s).strip()
    if not t or t.lower() in ("none", "nan", "-"): return None
    if ART.search(t): return "艺术"
    if "体育" in t: return "体育"
    if re.search(r"蒙授|蒙语|藏文|民语|民族班", t): return "民族语言"
    if "物理" in t: return "物理"
    if "历史" in t: return "历史"
    if re.match(r"^理(科|工)?$", t) or t in ("理科综合",): return "理科"
    if re.match(r"^文(科|史)?$", t) or t in ("文科综合",): return "文科"
    if re.search(r"综合|普通类|不限|本科$", t): return "综合"
    return "其他"

vals = [r[0] for r in con.execute(
    "SELECT DISTINCT subject FROM admission_lines WHERE subject IS NOT NULL")]
print(f"非空科类写法 {len(vals)} 种")
other = []
for v in vals:
    s = std(v)
    con.execute("UPDATE admission_lines SET subject_std=? WHERE subject=?", (s, v))
    if s == "其他": other.append(v)
con.commit()
if other:
    print("落入'其他'的写法样例:", other[:15])

# NULL 科类:按 (省,年) 众数填充
rows = con.execute("""SELECT province,year,subject_std,COUNT(*) FROM admission_lines
  WHERE subject_std IS NOT NULL GROUP BY 1,2,3""").fetchall()
agg = {}
for p, y, s, n in rows:
    agg.setdefault((p, y), []).append((n, s))
filled = unknown = 0
for (p, y), lst in agg.items():
    total = sum(n for n, _ in lst)
    n, s = max(lst)
    nl, = con.execute("""SELECT COUNT(*) FROM admission_lines
      WHERE province=? AND year=? AND subject_std IS NULL""", (p, y)).fetchone()
    if nl == 0: continue
    if n / total >= 0.9:
        con.execute("""UPDATE admission_lines SET subject_std=?
          WHERE province=? AND year=? AND subject_std IS NULL""", (s, p, y))
        filled += nl
    else:
        con.execute("""UPDATE admission_lines SET subject_std='未知'
          WHERE province=? AND year=? AND subject_std IS NULL""", (p, y))
        unknown += nl
con.execute("UPDATE admission_lines SET subject_std='未知' WHERE subject_std IS NULL")
con.commit()
print(f"NULL 填充:众数回填 {filled:,} 行,标记未知 {unknown:,} 行")
con.execute("CREATE INDEX IF NOT EXISTS idx_adm_std ON admission_lines(province,year,subject_std,min_rank)")
con.commit()
print("\n=== 标准科类分布 ===")
for s, n in con.execute(
        "SELECT subject_std,COUNT(*) FROM admission_lines GROUP BY 1 ORDER BY 2 DESC"):
    print(f"  {s:6s} {n:>10,}")
con.close()
