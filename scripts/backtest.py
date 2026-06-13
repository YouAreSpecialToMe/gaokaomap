#!/usr/bin/env python3
"""ρ 边界回测:用 ≤2023 数据预测,以 2024 实际线检验各 ρ 区间真实录取率。

模拟:8 个代表省 × 各 10 个位次分位点的虚拟考生;
预测:对每个 (校,专业) 用 2023/22/21 线算加权 ρ(同引擎逻辑);
检验:2024 同 (校,专业) 线存在时,考生 2024 等效位次 <= 线位次 即录取。
输出:ρ 分桶录取率曲线 + 推荐边界。
"""
import os, sqlite3
from bisect import bisect_right
from collections import defaultdict

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gaokao-data", "gaokao.db")
ALIAS = {"物理": ["物理类", "物理", "理科"], "历史": ["历史类", "历史", "文科"],
         "综合": ["综合", "综合改革"]}
PROVS = [("浙江", "综合"), ("上海", "综合"), ("河南", "物理"), ("广东", "物理"),
         ("四川", "物理"), ("辽宁", "物理"), ("湖南", "历史"), ("河北", "历史")]
PCTS = [0.01, 0.03, 0.06, 0.10, 0.16, 0.24, 0.34, 0.46, 0.60, 0.75]

con = sqlite3.connect(DB, timeout=30)

def rank_table(prov, subj, yr):
    for cand in ALIAS[subj]:
        t = con.execute("""SELECT score_min,cum_rank FROM rank_tables
            WHERE province=? AND year=? AND subject=? ORDER BY score_min""",
            (prov, yr, cand)).fetchall()
        if t: return t
    return None

def lines(prov, subj, yr):
    eq = {"物理": ("物理", "理科"), "历史": ("历史", "文科"), "综合": ("综合", "综合")}
    a, b = eq.get(subj, (subj, subj))
    return con.execute("""SELECT uni_name,major,min_rank FROM admission_lines
        WHERE province=? AND year=? AND granularity='major'
          AND subject_std IN (?,?) AND min_rank IS NOT NULL""",
        (prov, yr, a, b)).fetchall()

buckets = defaultdict(lambda: [0, 0])   # rho_bucket -> [admit, total]
for prov, subj in PROVS:
    tbls = {y: rank_table(prov, subj, y) for y in (2021, 2022, 2023, 2024)}
    if not tbls[2023] or not tbls[2024]:
        print(f"  跳过 {prov}(缺位次表)"); continue
    cohort = {y: max(c for _, c in t) for y, t in tbls.items() if t}
    L = {y: lines(prov, subj, y) for y in (2021, 2022, 2023)}
    L24 = {(u, m): r for u, m, r in lines(prov, subj, 2024)}
    if not L24:
        print(f"  跳过 {prov}(无2024线)"); continue
    # 多年线索引
    hist = defaultdict(dict)
    for y in (2021, 2022, 2023):
        if L[y]:
            for u, m, r in L[y]: hist[(u, m)][y] = r
    n_students = 0
    for pct in PCTS:
        my23 = max(1, int(cohort[2023] * pct))
        eq = {2023: my23}
        for y in (2022, 2021):
            if y in cohort: eq[y] = max(1, round(my23 * cohort[y] / cohort[2023]))
        eq24 = max(1, round(my23 * cohort[2024] / cohort[2023]))
        n_students += 1
        for (u, m), yr_ranks in hist.items():
            if (u, m) not in L24: continue
            num = den = 0
            for y, r in yr_ranks.items():
                if y not in eq: continue
                w = 3 if y == 2023 else (2 if y == 2022 else 1)
                num += (r / eq[y]) * w; den += w
            if not den: continue
            rho = num / den
            if not (0.5 <= rho <= 2.6): continue
            b = round(rho / 0.1) * 0.1
            admitted = eq24 <= L24[(u, m)]
            buckets[round(b, 1)][0] += admitted
            buckets[round(b, 1)][1] += 1
    print(f"  {prov} ✓({n_students} 个考生点)")

print("\nρ 桶    样本     录取率")
curve = []
for b in sorted(buckets):
    a, t = buckets[b]
    if t < 200: continue
    curve.append((b, a / t, t))
    print(f"{b:.1f}  {t:>8,}   {a/t*100:5.1f}%")

def find_rho(target, side):
    """side='ge': 最小 ρ 使录取率>=target;'le':最大 ρ 使录取率<=target"""
    if side == "ge":
        for b, p, _ in curve:
            if p >= target: return b
    else:
        last = None
        for b, p, _ in curve:
            if p <= target: last = b
        return last
print("\n建议边界:")
print(f"  冲下限(录取率≈15%): ρ≥{find_rho(0.15,'ge')}")
print(f"  冲/稳分界(≈55%):   ρ≈{find_rho(0.55,'ge')}")
print(f"  稳/保分界(≈85%):   ρ≈{find_rho(0.85,'ge')}")
print(f"  保上限(≈97%):      ρ≈{find_rho(0.97,'ge')}")
