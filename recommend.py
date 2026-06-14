#!/usr/bin/env python3
"""冲稳保推荐引擎 v1.5(JSON 输出,供 serve-api.py 调用)。

CLI: python3 recommend.py <省份> <科类> <分数> [年份=2025] [选科如 物,化,生]

算法:
1) 分数->位次(一分一段,科类别名解析,新老高考自动兼容)
2) 跨年等效位次(按考生规模缩放)
3) 选科要求过滤(不限/必选/N选1 三种语义)
4) 近三年专业线加权 ρ=线位次/等效位次 分档,取档位中心
5) 招生计划扩缩招修正(校级计划同比,ρ*factor^0.2)
6) 缺最新年标注 (据YYYY);专业级薄省提示参考院校线
"""
import json, math, os, pathlib, re, sqlite3, sys
from bisect import bisect_right
from collections import defaultdict
from functools import lru_cache

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gaokao-data", "gaokao.db")
DB_URI = pathlib.Path(DB).as_uri() + "?immutable=1"   # static snapshot: skip all locking/change-detection → max read concurrency

def connect():
    """Read-only connection tuned for this ~2.4GB snapshot.
    mmap_size memory-maps the file so index/data pages are served from the shared OS
    page cache across every per-request connection and thread (big win for repeat reads;
    the default 2MB per-connection cache was discarded each request)."""
    con = sqlite3.connect(DB_URI, uri=True, timeout=30)
    con.execute("PRAGMA mmap_size=3000000000")   # ~3GB: map the whole db
    con.execute("PRAGMA temp_store=MEMORY")        # GROUP BY temp b-trees in RAM, not disk
    con.execute("PRAGMA cache_size=-65536")        # 64MB page cache
    return con
ALIAS = {"物理": ["物理类", "物理", "理科"], "历史": ["历史类", "历史", "文科"],
         "理科": ["理科", "物理类", "物理"], "文科": ["文科", "历史类", "历史"],
         "综合": ["综合", "综合改革"]}
BANDS = {"冲": (0.85, 1.05, 0.95), "稳": (1.05, 1.25, 1.15), "保": (1.25, 1.80, 1.45)}
CURRENT_YEAR = 2026   # 出分日预案目标年:换算位次时按省回退到 ≤ 此年的最新可用一分一段;各省 2026 数据入库后自动升级,无需改码(入库后须重启服务清缓存)
SUBJ_EQ = {"物理": ("物理", "理科"), "历史": ("历史", "文科"),
           "理科": ("理科", "物理"), "文科": ("文科", "历史"), "综合": ("综合",)}
TOK = {"物理": "物", "化学": "化", "生物": "生", "历史": "史", "地理": "地", "政治": "政",
       "技术": "技"}

def _norm_tokens(text):
    t = str(text)
    for full, short in TOK.items():
        t = t.replace(full, short)
    return set(re.findall(r"[物化生史地政技]", t))

def sel_ok(req, user_sel):
    """user_sel: 用户选考科目短名集合(含首选),None=不过滤。"""
    if user_sel is None: return True
    if req is None: return True
    r = str(req).strip()
    if not r or "不限" in r or r in ("-", "无"): return True
    toks = _norm_tokens(r)
    if not toks: return True
    if re.search(r"选\s*1|或", r) or "/" in r:      # N 选 1
        return bool(toks & user_sel)
    return toks <= user_sel                            # 必选/捆绑

def band_of(rho):
    for b, (lo, hi, _) in BANDS.items():
        if lo <= rho < hi: return b
    return None

def effective_rank_year(con, prov, subj_std, target=None):
    """出分日预案核心:返回 ≤target 且该省该科有一分一段的最新年(科类别名兼容);全无则 None。
    target 默认 CURRENT_YEAR——即"预置 2026":某省 2026 一分一段入库前自动用其最新可用年(现为 2025),
    入库后(配合服务重启清缓存)同一查询自动升级到 2026,逐省灰度,无需改码。"""
    target = CURRENT_YEAR if target is None else int(target)
    for cand in ALIAS.get(subj_std, [subj_std]):
        row = con.execute("SELECT MAX(year) FROM rank_tables WHERE province=? AND subject=? AND year<=?",
                          (prov, cand, target)).fetchone()
        if row and row[0]:
            return row[0]
    return None

@lru_cache(maxsize=8)
def get_uinfo():
    con = connect()
    u = {r[0]: (r[1], r[2], r[3], r[4], r[5], r[6]) for r in con.execute(
        "SELECT name,lng,lat,is_985,is_211,is_dfc,city FROM universities")}
    con.close()
    return u

@lru_cache(maxsize=128)
def get_plan_map(prov, year):
    con = connect()
    plan = {}
    for un, yr, n in con.execute("""SELECT uni_name,year,SUM(plan_n) FROM enrollment_plans
        WHERE province=? AND year IN (?,?) GROUP BY uni_name,year""",
        (prov, year, year - 1)):
        plan.setdefault(un, {})[yr] = n or 0
    con.close()
    return plan

@lru_cache(maxsize=4096)
def _cached(prov, subj_std, score, year, sel_key, rank, mcls_key):
    return _engine(prov, subj_std, score, year,
                   set(sel_key.split(",")) if sel_key else None,
                   rank or None,
                   tuple(mcls_key.split("|")) if mcls_key else None)

def engine(prov, subj_std, score, year=None, sel=None, rank=None, mclasses=None):
    """score 与 rank 二选一(rank 优先);mclasses 给定则只在这些专业类内推荐(测评×分数合并)。
    year=None → 取 CURRENT_YEAR(出分日预案),引擎内再按省回退到最新可用一分一段年。"""
    year = CURRENT_YEAR if year is None else int(year)
    sel_key = ",".join(sorted(sel)) if sel else ""
    mcls_key = "|".join(sorted(mclasses)) if mclasses else ""
    return json.loads(json.dumps(_cached(prov, subj_std, int(score or 0), int(year),
                                         sel_key, int(rank) if rank else 0, mcls_key)))

def _engine(prov, subj_std, score, year, sel, rank=None, mclasses=None):
    con = connect()
    con.row_factory = sqlite3.Row

    def rank_table(yr):
        for cand in ALIAS.get(subj_std, [subj_std]):
            t = con.execute("""SELECT score_min,cum_rank FROM rank_tables
                WHERE province=? AND year=? AND subject=? ORDER BY score_min""",
                (prov, yr, cand)).fetchall()
            if t: return [(r[0], r[1]) for r in t]
        return None

    eff = effective_rank_year(con, prov, subj_std, year)   # 出分日预案:按省回退到最新可用年(2026 入库即自动启用)
    if not eff:
        return {"error": f"{prov} 暂无{subj_std}类一分一段(≤{year}),无法换算位次",
                "degrade": "no_rank"}
    year = eff
    tbl = rank_table(year)
    scores = [t[0] for t in tbl]
    if rank:
        my_rank = int(rank)
    else:
        i = bisect_right(scores, score) - 1
        if i < 0:
            return {"error": "分数低于该省统计下限", "degrade": "below_floor"}
        my_rank = tbl[i][1]
    cohort = {year: max(c for _, c in tbl)}
    eq = {year: my_rank}
    for yr in (year - 1, year - 2):
        t = rank_table(yr)
        if t:
            cohort[yr] = max(c for _, c in t)
            eq[yr] = max(1, round(my_rank * cohort[yr] / cohort[year]))

    uinfo = get_uinfo()
    strip_paren = lambda s: re.sub(r"[(（][^)）]*[)）]", "", str(s)).strip()
    plan = get_plan_map(prov, year)
    def plan_factor(un):
        p = plan.get(un) or plan.get(strip_paren(un))
        if not p or not p.get(year) or not p.get(year - 1): return 1.0
        f = max(0.7, min(1.4, p[year] / p[year - 1]))
        return f ** 0.2

    mcls_clause, mcls_params = "", ()
    if mclasses:
        ph = ",".join("?" * len(mclasses))
        mcls_clause = f" AND major IN (SELECT major FROM uni_majors WHERE mclass IN ({ph}))"
        mcls_params = tuple(mclasses)
    cands = defaultdict(list)
    for yr in eq:
        rows = con.execute(f"""SELECT uni_name,major,min_score,min_rank,enroll_n,sel_req
            FROM admission_lines
            WHERE province=? AND year=? AND granularity='major'
              AND subject_std IN (?,?) AND min_rank IS NOT NULL
              AND min_rank BETWEEN ? AND ?{mcls_clause}""",
            (prov, yr, *(SUBJ_EQ.get(subj_std, (subj_std,)) + (subj_std,))[:2],
             int(eq[yr] * 0.6), int(eq[yr] * 2.4), *mcls_params)).fetchall()
        for r in rows:
            if not sel_ok(r["sel_req"], sel): continue
            cands[(r["uni_name"], r["major"])].append((yr, r["min_rank"] / eq[yr], dict(r)))

    items = []
    for (un, mj), recs in cands.items():
        recs.sort(key=lambda r: r[0], reverse=True)
        w = [3 if r[0] == year else (2 if r[0] == year - 1 else 1) for r in recs]
        rho = sum(r[1] * wi for r, wi in zip(recs, w)) / sum(w)
        rho *= plan_factor(un)
        items.append((rho, recs[0][0], un, mj, recs[0][2]))
    items.sort(key=lambda x: abs(x[0] - BANDS.get(band_of(x[0]) or "稳", (0, 0, 1.18))[2]))

    out = {b: [] for b in BANDS}
    per_uni = defaultdict(int)
    for rho, fresh, un, mj, row in items:
        b = band_of(rho)
        if not b or per_uni[un] >= 2 or len(out[b]) >= 12: continue
        per_uni[un] += 1
        info = uinfo.get(un) or uinfo.get(strip_paren(un))
        out[b].append({
            "uni": un, "major": mj, "minScore": row["min_score"],
            "minRank": row["min_rank"], "rho": round(rho, 3), "year": fresh,
            "note": "" if fresh == year else f"据{fresh}",
            "selReq": row["sel_req"], "enroll": row["enroll_n"],
            "ll": [info[0], info[1]] if info and info[0] else None,
            "tier": ("985" if info and info[2] else "211" if info and info[3]
                     else "dfc" if info and info[4] else "ben") if info else None,
            "city": info[5] if info else None})
    total = sum(len(v) for v in out.values())
    notes = []
    if total < 12:
        notes.append("该省该分段专业级数据较薄,建议同时参考院校投档线")
    con.close()
    return {"province": prov, "subject": subj_std, "score": score, "year": year,
            "rank": my_rank, "eq": {str(k): v for k, v in eq.items()},
            "bands": out, "notes": notes}

def warm(background_provinces=True):
    """Cache-first warmup so the first user request is instant.
    Loads all universities now, then pre-fills each province's enrollment-plan map
    (the formerly ~370ms scan, now indexed) in a daemon thread so server bind isn't delayed.
    Returns the province count."""
    get_uinfo()
    con = connect()
    provs = [r[0] for r in con.execute("SELECT province FROM rank_tables GROUP BY province")]
    con.close()
    def _go():
        for p in provs:
            try: get_plan_map(p, CURRENT_YEAR)
            except Exception: pass
    if background_provinces:
        import threading
        threading.Thread(target=_go, name="warm-plans", daemon=True).start()
    else:
        _go()
    return len(provs)

if __name__ == "__main__":
    prov, subj, score = sys.argv[1], sys.argv[2], int(sys.argv[3])
    yr = int(sys.argv[4]) if len(sys.argv) > 4 else None
    sel = set(sys.argv[5].split(",")) if len(sys.argv) > 5 else None
    r = engine(prov, subj, score, yr, sel)
    if "error" in r: print("⚠️", r["error"]); sys.exit(1)
    print(f"{prov} {subj} {score}分 → 位次 {r['rank']:,}(等效 {r['eq']})")
    for b in ("冲", "稳", "保"):
        print(f"\n【{b}】")
        for it in r["bands"][b][:8]:
            tag = f"({it['note']})" if it["note"] else ""
            print(f"  {it['uni']}·{it['major']}{tag} {int(it['minScore'] or 0)}分/位次{it['minRank']:,} ρ={it['rho']}")
