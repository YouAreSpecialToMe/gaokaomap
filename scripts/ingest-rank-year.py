#!/usr/bin/env python3
"""出分日预案 · 一分一段「增量·幂等」入库 —— 安全追加单年(默认 2026),绝不 DROP 全表。

与 etl-rank-tables.py(一次性重建 2017-2024 全量、开头就 DROP TABLE)不同:本脚本只对
"输入文件中出现的 (省份, 年份) 组合"先 DELETE 再 INSERT,故可对单年(如 2026)逐省、反复
重跑而绝不动其它年份——出分日各省一分一段陆续到货即陆续入库,失败可安全重试。复用同样的
列约定与位次单调性校验/修复。

输入两种格式:
  ① .xlsx —— 每个 sheet 一省(sheet 名=省份),列顺序同 etl-rank-tables.py 的 EXPECT;
  ② .csv  —— 单表,含「省份」列(其余列名同 EXPECT 子集)。考试院当日抓取常落 CSV。
若文件/表含「年份」列以其为准;--year 可强制覆盖(适用无年份列的当日单年文件)。

用法:
  python3 ingest-rank-year.py 2026一分一段.xlsx --year 2026 --source kaoshiyuan-2026
  python3 ingest-rank-year.py zhejiang_2026.csv --year 2026 --provinces 浙江 --dry-run

入库后务必:① 重启 API 服务(immutable 连接 + lru 缓存,须重启才见新数据);
           ② 等待/清除 Cloudflare 边缘缓存(s-maxage)。详见 出分日预案.md。
"""
import argparse, os, sys
import sqlite3
import pandas as pd

EXPECT = ["省份", "年份", "科目", "层次", "最高位次", "最低位次", "位次区间",
          "最大分数", "最小分数", "分数区间", "同分人数"]
NEED = ["年份", "最低位次", "最小分数"]          # 缺这些的行无法换算位次,丢弃
NUMCOLS = ["年份", "最高位次", "最低位次", "最大分数", "最小分数", "同分人数"]


def fix_monotonic(df):
    """同一 (年,科目,层次) 内分数降→累计位次升;个别录入笔误用同分人数链式重算修复。"""
    problems = []
    df = df.sort_values(["年份", "科目", "层次", "最小分数"],
                        ascending=[True, True, True, False]).reset_index(drop=True)
    for (y, subj, lv), g in df.groupby(["年份", "科目", "层次"]):
        if (g["最低位次"].diff().dropna() >= 0).all():
            continue
        cum, fixed = None, 0
        for i in g.index:
            c = df.at[i, "同分人数"]
            v = df.at[i, "最低位次"]
            expect = None if cum is None or pd.isna(c) else cum + c
            if expect is not None and v < cum:
                df.at[i, "最低位次"] = expect
                fixed += 1
            cum = df.at[i, "最低位次"]
        if fixed:
            problems.append(f"{subj}/{lv} {int(y)}: 修复 {fixed} 行倒挂")
    return df, problems


def normalize(df, prov, force_year):
    df = df.iloc[:, :11].copy()
    df.columns = EXPECT[:df.shape[1]]
    df["省份"] = prov
    if force_year is not None:
        df["年份"] = force_year
    df = df.dropna(subset=NEED)
    for c in NUMCOLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=NEED)


def load_frames(src, force_year, only):
    """→ 列表[DataFrame]。xlsx 逐 sheet(sheet=省);csv 单表按「省份」列分组。"""
    frames = []
    if str(src).lower().endswith(".csv"):
        raw = pd.read_csv(src)
        if "省份" not in raw.columns:
            sys.exit("❌ CSV 缺「省份」列,无法分省入库")
        for prov, g in raw.groupby("省份"):
            prov = str(prov).strip()
            if only and prov not in only:
                continue
            cols = [c for c in EXPECT if c in g.columns]
            df = normalize(g[cols], prov, force_year)
            if not df.empty:
                frames.append(df)
            else:
                print(f"⚠️ {prov}: 无有效行,跳过")
    else:
        xl = pd.ExcelFile(src)
        for sh in xl.sheet_names:
            prov = str(sh).strip()
            if only and prov not in only:
                continue
            df = normalize(pd.read_excel(xl, sheet_name=sh, header=0), prov, force_year)
            if not df.empty:
                frames.append(df)
            else:
                print(f"⚠️ {prov}: 无有效行,跳过")
    return frames


def main():
    ap = argparse.ArgumentParser(description="一分一段 增量·幂等 入库(出分日预案)")
    ap.add_argument("src", help="一分一段 .xlsx(每 sheet 一省)或 .csv(含 省份 列)")
    ap.add_argument("--year", type=int, default=None, help="强制年份(无年份列时必填,如 2026)")
    ap.add_argument("--source", default="kaoshiyuan-2026", help="source 标签,便于溯源/回滚")
    ap.add_argument("--provinces", default=None, help="只入这些省(逗号分隔),默认全部")
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "gaokao-data", "gaokao.db"))
    ap.add_argument("--dry-run", action="store_true", help="只解析+校验,不写库")
    a = ap.parse_args()
    only = set(p.strip() for p in a.provinces.split(",")) if a.provinces else None

    frames = load_frames(a.src, a.year, only)
    if not frames:
        sys.exit("❌ 没有可入库的数据(检查 sheet 名/省份过滤/列布局/--year)")
    fixed = []
    for df in frames:
        prov = df["省份"].iloc[0]
        df, probs = fix_monotonic(df)          # 必须用返回的修复后 df(原 df 不变)
        for p in probs:
            print(f"  {prov} {p}")
        fixed.append(df)
    alldf = pd.concat(fixed, ignore_index=True)

    combos = sorted({(str(r.省份), int(r.年份)) for r in alldf.itertuples()})
    preview = ", ".join(f"{p}{y}" for p, y in combos[:12]) + ("…" if len(combos) > 12 else "")
    print(f"\n将『替换』{len(combos)} 个 (省,年) 组合(先 DELETE 再 INSERT,不动其它年份): {preview}")
    print(f"解析 {len(alldf):,} 行")
    if a.dry_run:
        print("[dry-run] 未写库")
        return

    con = sqlite3.connect(a.db)
    con.execute("""CREATE TABLE IF NOT EXISTS rank_tables(
      province TEXT NOT NULL, year INTEGER NOT NULL, subject TEXT NOT NULL, level TEXT,
      rank_from INTEGER, cum_rank INTEGER NOT NULL, score_max INTEGER NOT NULL,
      score_min INTEGER NOT NULL, count_same INTEGER, source TEXT)""")
    try:
        con.execute("BEGIN")
        for prov, yr in combos:
            con.execute("DELETE FROM rank_tables WHERE province=? AND year=?", (prov, yr))
        rows = [(str(r.省份), int(r.年份), str(r.科目), str(r.层次),
                 int(r.最高位次) if pd.notna(r.最高位次) else None,
                 int(r.最低位次), int(r.最大分数), int(r.最小分数),
                 int(r.同分人数) if pd.notna(r.同分人数) else None, a.source)
                for r in alldf.itertuples()]
        con.executemany("""INSERT INTO rank_tables
          (province,year,subject,level,rank_from,cum_rank,score_max,score_min,count_same,source)
          VALUES(?,?,?,?,?,?,?,?,?,?)""", rows)
        # 表若是新建则补索引(已存在则 no-op);重建过表才会丢索引,增量入库不会
        con.execute("CREATE INDEX IF NOT EXISTS idx_rank_lookup ON rank_tables(province,year,subject,score_min)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_rank_cum ON rank_tables(province,year,subject,cum_rank)")
        con.execute("COMMIT")
    except Exception as e:
        con.execute("ROLLBACK")
        con.close()
        sys.exit(f"❌ 入库失败,已回滚:{type(e).__name__} {e}")

    print(f"✅ 入库 {len(rows):,} 行 → {a.db}")
    for prov, yr in combos[:6]:
        n = con.execute("SELECT COUNT(*) FROM rank_tables WHERE province=? AND year=?",
                        (prov, yr)).fetchone()[0]
        print(f"  {prov} {yr}: {n:,} 行")
    print("\n下一步:重启 API 服务(清缓存)+ 清/等 Cloudflare 边缘缓存。验证见 出分日预案.md。")
    con.close()


if __name__ == "__main__":
    main()
