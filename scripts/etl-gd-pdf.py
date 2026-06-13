#!/usr/bin/env python3
"""广东 2025 官方分数段统计表 PDF -> 核验普通类 + 入库艺体类。

表式:文化总分 | 本科段人数 | 本科累计 | 专科段人数 | 专科累计(取本科口径)。
"""
import glob, os, re, sqlite3
import warnings; warnings.filterwarnings("ignore")
import pdfplumber

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gaokao-data", "gaokao.db")
con = sqlite3.connect(DB, timeout=60)

def extract(path):
    rows = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for tbl in page.extract_tables():
                for r in tbl:
                    if not r or r[0] is None: continue
                    c0 = str(r[0]).strip()
                    m = re.match(r"^(\d+)(?:\s*[((]含以上[))])?$", c0)
                    if not m: continue
                    sc = int(m.group(1))
                    try:
                        seg = int(str(r[1]).replace(",", ""))
                        cum = int(str(r[2]).replace(",", ""))
                    except (ValueError, TypeError):
                        continue
                    top = "含以上" in c0
                    rows.append((sc, 750 if top else sc, seg, cum))
    return rows

SUBJ = {
    "1.": "历史类", "2.": "物理类", "3.": "体育类", "4.": "美术与设计类",
    "5.": "音乐教育类", "6.": "音乐教育(声乐主项)", "7.": "音乐教育(器乐主项)",
    "8.": "音乐表演(声乐)", "9.": "音乐表演(器乐)", "10.": "舞蹈类",
    "11.": "表导演(戏剧影视表演)", "12.": "表导演(戏剧影视导演)",
    "13.": "表导演(服装表演)", "14.": "播音与主持(普通话)",
    "15.": "播音与主持(粤语)", "16.": "书法类"}

files = sorted(glob.glob("/Users/zhangxiansheng/Downloads/广东/*.pdf"))
print("== 第一步:核验普通类(官方 PDF vs 库内卖家版)")
for f in files:
    base = os.path.basename(f)
    pref = base.split("广东省")[0]
    subj = SUBJ.get(pref)
    if subj not in ("历史类", "物理类"): continue
    rows = extract(f)
    diffs, checked = [], 0
    for sc, _, seg, cum in rows:
        db = con.execute("""SELECT cum_rank FROM rank_tables WHERE province='广东'
            AND year=2025 AND subject=? AND score_min=?""", (subj, sc)).fetchone()
        if db:
            checked += 1
            if abs(db[0] - cum) > 0: diffs.append((sc, db[0], cum))
    print(f"  {subj}: PDF {len(rows)} 段,库内可比 {checked} 段,不一致 {len(diffs)} 段")
    if diffs[:3]: print("    样例差异(分,库内,官方):", diffs[:3])
    # 官方为准:整段替换
    con.execute("DELETE FROM rank_tables WHERE province='广东' AND year=2025 AND subject=?", (subj,))
    con.executemany("""INSERT INTO rank_tables
      (province,year,subject,level,rank_from,cum_rank,score_max,score_min,count_same)
      VALUES('广东',2025,?,?,NULL,?,?,?,?)""",
      [(subj, "本科口径", cum, mx, mn, seg) for mn, mx, seg, cum in rows])
    print(f"    已用官方版替换({len(rows)} 段)")

print("== 第二步:艺体类 14 品类入库")
n_art = 0
for f in files:
    base = os.path.basename(f)
    pref = base.split("广东省")[0]
    subj = SUBJ.get(pref)
    if subj is None or subj in ("历史类", "物理类"): continue
    rows = extract(f)
    con.execute("DELETE FROM rank_tables WHERE province='广东' AND year=2025 AND subject=?", (subj,))
    con.executemany("""INSERT INTO rank_tables
      (province,year,subject,level,rank_from,cum_rank,score_max,score_min,count_same)
      VALUES('广东',2025,?,?,NULL,?,?,?,?)""",
      [(subj, "本科口径", cum, mx, mn, seg) for mn, mx, seg, cum in rows])
    print(f"  {subj}: +{len(rows)} 段")
    n_art += len(rows)
con.commit()
t = con.execute("SELECT COUNT(*) FROM rank_tables WHERE province='广东' AND year=2025").fetchone()[0]
print(f"\n广东 2025 rank_tables 现共 {t:,} 段(艺体新增 {n_art:,})")
con.close()
