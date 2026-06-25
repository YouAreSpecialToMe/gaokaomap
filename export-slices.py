#!/usr/bin/env python3
"""导出分省客户端切片(列存 + 字典,近 3 年)——冲稳保引擎所需的最小数据。
gaokao.db → slices/{省}.json:客户端 gk-engine.js 直接跑,免跨境 API。
列存(校名/专业名/选科 intern 成索引 + 各列数字)→ 体积/内存对移动端友好。
slices/ 走 .gitignore(盒子/dev 生成),与 DEM 瓦片同思路。
用法: [GK_DB=路径] python3 export-slices.py [省名,缺省=全部]
"""
import sqlite3, json, os, sys, gzip, re

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from recommend import benke_line_score   # 本科线分数(与服务端同源)→ 切片预算成位次,保证客户端==服务端
DB = os.environ.get("GK_DB") or next((p for p in [
    os.path.join(HERE, "gaokao-data", "gaokao.db"),
    "/Users/zhangxiansheng/projects/agentfeed/demos/gaokao-data/gaokao.db",
    os.path.join(HERE, "gaokao.db")] if os.path.exists(p)), None)
OUT = os.path.join(HERE, "slices")
YEARS = 3   # 引擎用 year/y-1/y-2;与服务端一致
NORM = {"物理类": "物理", "历史类": "历史"}   # 一分一段表用「物理类/历史类」,投档线/前端用「物理/历史」→ 统一到后者(否则改革省对不上)

con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
_strip = lambda s: re.sub(r"[(（][^)）]*[)）]", "", s or "").strip()
def _tier(r): return "985" if r["is_985"] else "211" if r["is_211"] else "dfc" if r["is_dfc"] else "ben"
UNI_ALL = {r["name"]: r for r in con.execute("SELECT name,lng,lat,is_985,is_211,is_dfc,city,rank,province FROM universities")}
try:   # 软科专业评级(校,专业)→ 等级;ruanke_match 不存在(未导入排名)则空,切片不带 mg
    RKG = {(r[0], r[1]): r[2] for r in con.execute("SELECT uni_name,major,grade FROM ruanke_match")}
except Exception:
    RKG = {}


def export(prov):
    yrs = [r[0] for r in con.execute(
        "SELECT DISTINCT year FROM rank_tables WHERE province=? ORDER BY year DESC LIMIT ?", (prov, YEARS))]
    if not yrs:
        return None
    # 主科目取「最新年」的主导科目(改革省最新年已是 物理/历史/综合,而非历史累计的 理科/文科)
    subj = con.execute("SELECT subject FROM rank_tables WHERE province=? AND year=? GROUP BY subject ORDER BY COUNT(*) DESC LIMIT 1",
                        (prov, yrs[0])).fetchone()
    if not subj:
        return None
    subj = NORM.get(subj[0], subj[0])
    # admission_lines 专业线(近3年)
    rows = con.execute(f"""SELECT uni_name u,major m,min_score ms,min_rank r,enroll_n e,sel_req s,subject_std j,year y,batch bt
        FROM admission_lines WHERE province=? AND granularity='major'
          AND year IN ({','.join('?' * len(yrs))}) AND min_rank IS NOT NULL""", (prov, *yrs)).fetchall()
    unis, majs, sels, subjs = [], [], [], []
    ui, mi, si, ji = {}, {}, {}, {}
    def idx(v, lst, d):
        v = v or ""
        if v not in d:
            d[v] = len(lst); lst.append(v)
        return d[v]
    col = {k: [] for k in "umrescljy"}  # u m r(ank) e(nroll) s(core) c(=sel) l(unused) j y → 见下
    A = {"u": [], "m": [], "r": [], "sc": [], "e": [], "sl": [], "j": [], "y": [], "bt": []}  # bt=1 → 专科批(位次为专科批内排名,与本科一分一段不同基准)
    mg = {}   # "uidx,midx" → 软科评级(只存有评级的,省体积;客户端按 校×专业 查)
    for x in rows:
        uidx = idx(x["u"], unis, ui); A["u"].append(uidx)
        midx = idx(x["m"], majs, mi); A["m"].append(midx)
        _g = RKG.get((x["u"], x["m"]))
        if _g: mg[f"{uidx},{midx}"] = _g
        A["r"].append(x["r"])
        A["sc"].append(round((x["ms"] or 0) * 10))
        A["e"].append(x["e"] or 0)
        A["sl"].append(idx(x["s"], sels, si))
        A["j"].append(idx(x["j"], subjs, ji))
        A["y"].append(x["y"] % 100)
        A["bt"].append(1 if (x["bt"] and ("专科" in x["bt"] or "高职" in x["bt"])) else 0)   # 专科批标记(含"高职高专批"——其无"专科"字样)→ 客户端引擎/选校助手按专科单列,不混入本科冲稳保
    # rank_tables(score→rank):{subjIdx:{year:{smax,pts:[[smin,cr]...]}}}
    rk = {}
    for r in con.execute(f"""SELECT subject sj,year y,score_min smin,score_max smax,cum_rank cr
        FROM rank_tables WHERE province=? AND year IN ({','.join('?' * len(yrs))}) ORDER BY score_min""", (prov, *yrs)):
        rsj = rk.setdefault(NORM.get(r["sj"], r["sj"]), {})
        ry = rsj.setdefault(r["y"], {"smax": 0, "pts": []})
        ry["pts"].append([r["smin"], r["cr"]]); ry["smax"] = max(ry["smax"], r["smax"] or 0)
    # plan(plan_factor):{uniName:{year:n}}
    pl = {}
    for r in con.execute("""SELECT uni_name u,year y,SUM(plan_n) n FROM enrollment_plans
        WHERE province=? AND year IN (?,?) GROUP BY uni_name,year""", (prov, yrs[0], yrs[0] - 1)):
        pl.setdefault(r["u"], {})[r["y"]] = r["n"] or 0
    # major → 招生专业类(测评×分数:与服务端 engine mclasses 过滤同源 uni_majors)。intern 类名 + 平行 majs 的类索引数组
    mcls_names, mci = [], {}
    def mcidx(v):
        if v not in mci:
            mci[v] = len(mcls_names); mcls_names.append(v)
        return mci[v]
    m2mc = {}
    if majs:
        for r in con.execute(f"SELECT major,mclass FROM uni_majors WHERE mclass IS NOT NULL AND major IN ({','.join('?' * len(majs))})", tuple(majs)):
            m2mc.setdefault(r["major"], set()).add(r["mclass"])
    mmc = [sorted(mcidx(c) for c in m2mc.get(m, ())) for m in majs]
    # 院校层次/位次/经纬/城市:取自 universities(与服务端 get_uinfo 同源)→ 切片自带,客户端 prestige 与服务端逐项对齐。
    # (unis.json 是展示用精选子集,缺冷门校 → 之前测评限类把冷门校排序排错;此处补全)
    uinfo = {}
    for un in unis:
        r = UNI_ALL.get(un) or UNI_ALL.get(_strip(un))
        if r:
            uinfo[un] = {"t": _tier(r), "rank": r["rank"], "ll": [r["lng"], r["lat"]] if r["lng"] else None, "c": r["city"], "p": r["province"]}
    # 本科线位次(每科):低于此位次=没上本科线 → 客户端引擎放开专科(与服务端 below_line 同源、同函数算本科线分数)
    bl = {}
    for sj, yd in rk.items():
        py = yrs[0]
        if py not in yd:
            continue
        bls = benke_line_score(con, prov, sj, py)
        if bls is None:
            continue
        br = None
        for smin, cr in yd[py]["pts"]:   # pts 按 score_min 升序;取 ≤本科线分 的最大段位次(= bisect_right-1,与服务端一致)
            if smin <= bls:
                br = cr
            else:
                break
        if br is not None:
            bl[sj] = br
    slice = {"prov": prov, "subj": subj, "years": yrs, "unis": unis, "majs": majs,
             "sels": sels, "subjs": subjs, "adm": A, "rank": rk, "plan": pl,
             "mcls": mcls_names, "mmc": mmc, "uinfo": uinfo, "mg": mg, "bl": bl}
    os.makedirs(OUT, exist_ok=True)
    js = json.dumps(slice, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(OUT, prov + ".json"), "w", encoding="utf-8").write(js)
    return len(rows), len(js.encode()), len(gzip.compress(js.encode(), 9))


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    provs = [target] if target else [r[0] for r in con.execute(
        "SELECT DISTINCT province FROM rank_tables WHERE province IS NOT NULL ORDER BY province")]
    tot_gz = 0
    for p in provs:
        r = export(p)
        if not r:
            print(f"  {p}: 跳过(无一分一段)"); continue
        n, raw, gz = r; tot_gz += gz
        print(f"  {p}: {n} 行 → 裸 {raw//1024}K / gz {gz//1024}K")
    print(f"── 共 {len(provs)} 省,切片 gz 合计 {tot_gz//1024}K(单省单拉,不预载)")


if __name__ == "__main__":
    print(f"DB={DB}")
    main()
