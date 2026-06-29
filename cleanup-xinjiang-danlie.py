#!/usr/bin/env python3
"""清理新疆「单列类」一分一段(幂等)。

背景:新疆「单列类」= 民族语文/外语 单列招生考生群体,**非普通类(汉语言)**。
本产品的冲稳保引擎只建模普通类考生;但早期 'taobao-17-24' bulk 把单列类的
一分一段表也塞进了 rank_tables(2022 / 2024 各科),与同年普通类(level='本专')
**同分数重叠** → export-slices.py 建 score→rank 的 pts 时出现重复 score_min,
污染「等效年位次」显示(2024 在切片的 3 年窗口内,理科等效 2024 被虚高到 8259,
清理后回到正确的 7690)。

修复:删掉新疆所有 level LIKE '单列类%' 的行,使每个 (年, 科目) 恰好剩 1 个
普通类 level(2026='nan' / 2025=NULL / 2024 及更早='本专' 或 '本科')。

⚠ 幂等:删完即 0 行,可反复跑。**建议每次重建库/部署后跑一次**——因为单列类来自
一次性 bulk 源(不在 yifen-2026 CSV 里),若整库重建可能被重新带回。

用法:
  python3 cleanup-xinjiang-danlie.py --db <生产库gaokao.db>
  python3 cleanup-xinjiang-danlie.py --dry-run     # 只看不删
"""
import argparse, os, sqlite3

ap = argparse.ArgumentParser(description="清理新疆单列类一分一段(幂等)")
ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "gaokao-data", "gaokao.db"))
ap.add_argument("--dry-run", action="store_true", help="只统计不删除")
a = ap.parse_args()

con = sqlite3.connect(a.db)
cur = con.cursor()
WHERE = "province='新疆' AND level LIKE '单列类%'"
n = cur.execute(f"SELECT COUNT(*) FROM rank_tables WHERE {WHERE}").fetchone()[0]
brk = cur.execute(f"SELECT DISTINCT year,subject,level FROM rank_tables WHERE {WHERE} ORDER BY year,subject").fetchall()
print(f"新疆 单列类 待清: {n} 行 {[f'{y}{s}{l}' for y,s,l in brk]}")

if a.dry_run:
    print("[dry-run] 未删")
elif n:
    cur.execute(f"DELETE FROM rank_tables WHERE {WHERE}")
    con.commit()
    bad = cur.execute("""SELECT year,subject,COUNT(DISTINCT level) FROM rank_tables
        WHERE province='新疆' GROUP BY year,subject HAVING COUNT(DISTINCT level)>1""").fetchall()
    print(f"✅ 已删 {cur.rowcount} 行  |  每(年,科目)恰剩1 level: {'是 ✓' if not bad else f'否 ⚠ {bad}'}")
else:
    print("已干净,无需清理")
con.close()
