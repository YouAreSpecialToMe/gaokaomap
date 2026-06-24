#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校友会 2025 中国大学排名(总榜)→ universities.rank(prestige 排序用)。清洗 + 可在盒子重跑。

源:`校友会2025中国大学排行榜（完整版）.xlsx`(单 sheet 总榜;表头在第 5 行:
名次/学校名称/总分/星级/办学层次)。867 校、名次 1-536,**名次带 `*` 是校友会并列**
(同总分→同名次,合法),解析时取数字部分,并列即同 rank。

为何重写:之前是临时 Bash 入库、无脚本、名匹配乱(分校区/院系错配,出现「浙大医学院=3 压过浙大=5」、
军校多名同号等)。本脚本三级匹配,母体只认总榜精确名:
  ① 精确校名 → 校友会名次
  ② 分校区/院系/名变体 → 继承**母体**名次:去括号(苏州校区/威海)、去「中国人民解放军」前缀、
     去院系后缀(医学院/医学部/上海医学院/美术学院);因①先行,北京协和医学院等独立医学院已精确命中、不会被误拆
  ③ 不在 867 校总榜(民办/职业/独立学院/部分军校)→ rank=NULL(引擎按 985/211/双一流 层次兜底,最低 prestige)

需 pandas+openpyxl。用法:python3 ingest-alumni-rank-2025.py [--xlsx ...] [--db ...] [--commit]
"""
import pandas as pd, sqlite3, re, argparse

def parse_rank(v):
    m = re.search(r"\d+", str(v)); return int(m.group()) if m else None

SUFFIX = ["上海医学院", "医学院", "医学部", "美术学院"]   # 长的在前(复旦大学上海医学院 先剥「上海医学院」)

def parents(name):
    """从分校区/院系/名变体回退,产出候选母体名(在总榜里命中即继承其名次)。"""
    n = name.strip(); out = []
    np = re.sub(r"[(（][^)）]*[)）]", "", n).strip()        # 去括号:中国人民大学(苏州校区)→中国人民大学
    if np != n: out.append(np)
    for base in (n, np):                                    # 去「中国人民解放军」前缀
        if base.startswith("中国人民解放军"): out.append(base.replace("中国人民解放军", "", 1))
    for base in (n, np):                                    # 去院系后缀:浙江大学医学院→浙江大学
        for suf in SUFFIX:
            if base.endswith(suf) and len(base) > len(suf) + 2: out.append(base[:-len(suf)].strip())
    seen = set(); return [x for x in out if x and not (x in seen or seen.add(x))]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default="/tmp/alumni2025.xlsx")
    ap.add_argument("--db", default="gaokao-data/gaokao.db")
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()

    df = pd.read_excel(a.xlsx, header=4).dropna(subset=["名次", "学校名称"])
    df["rk"] = df["名次"].map(parse_rank); df = df.dropna(subset=["rk"])
    RANK = {}
    for _, r in df.iterrows():                              # 同名取最优(最小)名次,防异常重复行
        nm = str(r["学校名称"]).strip(); rk = int(r["rk"])
        if nm not in RANK or rk < RANK[nm]: RANK[nm] = rk
    print(f"校友会总榜 {len(RANK)} 校,名次 1-{max(RANK.values())}(含并列)")

    c = sqlite3.connect(a.db)
    unis = [r[0] for r in c.execute("SELECT name FROM universities")]
    out = {}; via = {"exact": 0, "derive": 0, "none": 0}; unmatched = []
    for u in unis:
        if u in RANK:
            out[u] = RANK[u]; via["exact"] += 1; continue
        hit = next((RANK[c2] for c2 in parents(u) if c2 in RANK), None)
        if hit is not None: out[u] = hit; via["derive"] += 1
        else: out[u] = None; via["none"] += 1; unmatched.append(u)
    print("匹配:", via, f"/ 共 {len(unis)} 校")

    # 现状里有 rank 的、却将被置 NULL 的(看会不会丢掉知名校)
    cur_rank = {r[0]: r[1] for r in c.execute("SELECT name,rank FROM universities WHERE rank IS NOT NULL")}
    lose = [u for u in unmatched if u in cur_rank]
    print(f"未匹配 {len(unmatched)} 校 → NULL;其中原本有 rank 的 {len(lose)} 校丢 rank,示例:", lose[:15])

    print("\n抽查(应:浙大不被医学院压、军校名变体同号、原 38 并列复核):")
    for u in ["北京大学", "清华大学", "浙江大学", "浙江大学医学院", "复旦大学", "复旦大学上海医学院",
              "上海交通大学", "中国人民大学", "中国人民大学(苏州校区)", "国防科技大学",
              "中国人民解放军国防科技大学", "华中科技大学", "武汉大学", "苏州大学", "南京理工大学",
              "中国矿业大学", "中国矿业大学(北京)", "哈尔滨工业大学", "哈尔滨工业大学(威海)"]:
        if u in out: print(f"  {u}: {out[u]}")

    if not a.commit:
        print("\n=== DRY-RUN(未写库)。确认后加 --commit ==="); return
    c.executemany("UPDATE universities SET rank=? WHERE name=?", [(v, k) for k, v in out.items()])
    c.commit()
    print(f"已写库:{len(out)} 校 rank 更新(校友会精确 {via['exact']} + 继承 {via['derive']} + NULL {via['none']})")

if __name__ == "__main__":
    main()
