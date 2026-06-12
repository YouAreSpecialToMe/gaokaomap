#!/usr/bin/env python3
"""把 pg7go 大学坐标(BD09)模糊匹配到 universities 表并转 WGS84。

匹配优先级:同省精确名 > 全国唯一精确名 > 别名 > 归一化名 > 同省模糊(>=0.88)。
坐标转换:BD09 -> GCJ02 -> WGS84(标准算法)。
"""
import json, math, os, re, sqlite3
from difflib import SequenceMatcher

SRC = "/tmp/schoolloc/大学-8084.json"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gaokao-data", "gaokao.db")

# ---- 坐标转换 ----
PI = math.pi
A, EE = 6378245.0, 0.00669342162296594323

def bd09_to_gcj02(lng, lat):
    x, y = lng - 0.0065, lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * PI * 3000 / 180)
    t = math.atan2(y, x) - 0.000003 * math.cos(x * PI * 3000 / 180)
    return z * math.cos(t), z * math.sin(t)

def _t_lat(x, y):
    r = -100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    r += (20*math.sin(6*x*PI) + 20*math.sin(2*x*PI)) * 2/3
    r += (20*math.sin(y*PI) + 40*math.sin(y/3*PI)) * 2/3
    r += (160*math.sin(y/12*PI) + 320*math.sin(y*PI/30)) * 2/3
    return r

def _t_lng(x, y):
    r = 300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    r += (20*math.sin(6*x*PI) + 20*math.sin(2*x*PI)) * 2/3
    r += (20*math.sin(x*PI) + 40*math.sin(x/3*PI)) * 2/3
    r += (150*math.sin(x/12*PI) + 300*math.sin(x/30*PI)) * 2/3
    return r

def gcj02_to_wgs84(lng, lat):
    dlat, dlng = _t_lat(lng-105, lat-35), _t_lng(lng-105, lat-35)
    radlat = lat / 180 * PI
    magic = 1 - EE * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = dlat * 180 / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlng = dlng * 180 / (A / sqrtmagic * math.cos(radlat) * PI)
    return lng - dlng, lat - dlat

def bd09_to_wgs84(lng, lat):
    return gcj02_to_wgs84(*bd09_to_gcj02(lng, lat))

# ---- 数据 ----
norm = lambda s: re.sub(r"[\s()()·]", "", str(s))
prov_short = lambda p: re.sub(r"(省|市|自治区|维吾尔|壮族|回族|特别行政区)", "", str(p))

src = json.load(open(SRC))
strip_paren = lambda s: re.sub(r"[(（][^)）]*[)）]", "", str(s))
by_name, by_base, by_prov = {}, {}, {}
for e in src:
    e["pshort"] = prov_short(e["province"])
    e["base"] = norm(strip_paren(e["name"]))
    by_name.setdefault(norm(e["name"]), []).append(e)
    by_base.setdefault(e["base"], []).append(e)
    by_prov.setdefault(e["pshort"], []).append(e)

con = sqlite3.connect(DB)
try:
    con.execute("ALTER TABLE universities ADD COLUMN geo_src TEXT")
except sqlite3.OperationalError:
    pass
unis = con.execute("SELECT id,name,alias,province,city,address FROM universities").fetchall()

def pick(cands, prov, city=None, addr=None):
    pool = [c for c in cands if c["pshort"] == prov_short(prov)] \
        or (cands if len(cands) == 1 else [])
    if not pool:
        return None
    if city:  # 多校区:优先同城
        sc = [c for c in pool if str(city).rstrip("市") in c["city"]]
        pool = sc or pool
    if len(pool) > 1 and addr:  # 再用通讯地址相似度挑校区(主校区=招办地址)
        pool = sorted(pool, key=lambda c: -SequenceMatcher(
            None, norm(addr), norm(c.get("address", ""))).ratio())
        return pool[0]
    nosuf = [c for c in pool if norm(c["name"]) == c["base"]]  # 无括号后缀=主条目
    return (nosuf or pool)[0]

stats = {"exact": 0, "base": 0, "alias": 0, "fuzzy": 0, "citymean": 0, "miss": 0}
updates = []
for uid, name, alias, prov, city, addr in unis:
    hit, how = None, None
    for key, tag in [(norm(name), "exact"), (None, None)]:
        cands = by_name.get(key) if key else None
        if cands:
            hit, how = pick(cands, prov, city, addr), tag
            if hit: break
    if not hit:
        cands = by_base.get(norm(name))
        if cands:
            hit, how = pick(cands, prov, city, addr), "base"
    if not hit and alias:
        cands = by_base.get(norm(strip_paren(alias)))
        if cands:
            hit, how = pick(cands, prov, city, addr), "alias"
    if not hit:
        best, bs = None, 0.9
        for e in by_prov.get(prov_short(prov), []):
            r = SequenceMatcher(None, norm(name), e["base"]).ratio()
            if r > bs:
                best, bs = e, r
        if best:
            hit, how = best, "fuzzy"
    if hit:
        lng, lat = bd09_to_wgs84(hit["location"]["lng"], hit["location"]["lat"])
        updates.append((round(lng, 6), round(lat, 6), f"bd09-{how}", uid))
        stats[how] += 1
    else:
        stats["miss"] += 1
        updates.append((None, None, None, uid))
con.executemany("UPDATE universities SET lng=?,lat=?,geo_src=? WHERE id=?", updates)

# 未匹配兜底:同城已匹配院校的均值坐标(精度=城市级,加微抖动防重叠)
import random
random.seed(7)
rows = con.execute("""SELECT province,city,AVG(lng),AVG(lat) FROM universities
  WHERE lng IS NOT NULL GROUP BY province,city""").fetchall()
citymean = {(p, c): (x, y) for p, c, x, y in rows}
for uid, name, alias, prov, city, addr in unis:
    if con.execute("SELECT lng FROM universities WHERE id=?", (uid,)).fetchone()[0]:
        continue
    m = citymean.get((prov, city))
    if m:
        con.execute("UPDATE universities SET lng=?,lat=?,geo_src='city-mean' WHERE id=?",
                    (round(m[0]+random.uniform(-.01,.01), 6),
                     round(m[1]+random.uniform(-.008,.008), 6), uid))
        stats["citymean"] += 1
        stats["miss"] -= 1
con.commit()

total = len(unis)
print(f"匹配:精确 {stats['exact']} + 基名 {stats['base']} + 别名 {stats['alias']}"
      f" + 模糊 {stats['fuzzy']} + 城市均值兜底 {stats['citymean']}"
      f" = {total-stats['miss']}/{total} ({(total-stats['miss'])*100//total}%),无坐标 {stats['miss']}")
for lv, in [("本科",), ("专科",)]:
    n, m = con.execute(
        "SELECT COUNT(*),SUM(lng IS NOT NULL) FROM universities WHERE level=?", (lv,)).fetchone()
    print(f"  {lv}: {m}/{n}")
print("\n抽查(WGS84):")
for nm in ["清华大学", "浙江大学", "武汉大学", "兰州大学"]:
    r = con.execute("SELECT lng,lat,geo_src FROM universities WHERE name=?", (nm,)).fetchone()
    print(f"  {nm}: {r}")
miss = con.execute("""SELECT name,province FROM universities
  WHERE lng IS NULL AND level='本科' LIMIT 10""").fetchall()
print("\n未匹配本科样例:", miss)
con.close()
