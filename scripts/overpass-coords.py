#!/usr/bin/env python3
"""坐标精度——权威基准重定位:用 OSM Overpass 批量取全国高校(amenity=university|college)
的 name + 中心坐标(WGS84,实测与底图一致无偏移),按"精确名/规范名"匹配我们的本科,
并以"落在本省 bbox"为安全门替换坐标。覆盖近似 + 精确两类,精确名匹配几无歧义,
故可安全纠正省内错位(替换正确校为同校坐标=无害,替换错误校=修正,无匹配=保留)。
"""
import json, os, time, urllib.request, urllib.parse

D = os.path.dirname(os.path.abspath(__file__))
UNIS = os.path.join(D, "unis.json")
PROG = os.path.join(D, "overpass-progress.txt")
OSMREF = os.path.join(D, "overpass-ref.json")

PBOX = {
 '上海':(120.8,30.6,122.1,31.9),'云南':(97.3,21.0,106.3,29.3),'内蒙古':(97.1,37.3,126.2,53.4),
 '北京':(115.3,39.3,117.6,41.1),'吉林':(121.5,40.8,131.4,46.4),'四川':(97.2,25.9,108.7,34.4),
 '天津':(116.6,38.4,118.1,40.3),'宁夏':(104.1,35.1,107.8,39.5),'安徽':(114.8,29.3,119.8,34.8),
 '山东':(114.7,34.3,122.8,38.5),'山西':(110.1,34.5,114.8,40.9),'广东':(109.5,20.1,117.4,25.6),
 '广西':(104.3,20.8,112.2,26.5),'新疆':(73.3,34.2,96.5,49.3),'江苏':(116.2,30.7,122.0,35.2),
 '江西':(113.4,24.4,118.6,30.2),'河北':(113.3,36.0,119.9,42.8),'河南':(110.2,31.3,116.8,36.5),
 '浙江':(118.0,27.0,123.2,31.3),'海南':(108.5,18.1,111.2,20.3),'湖北':(108.2,29.0,116.2,33.4),
 '湖南':(108.6,24.5,114.4,30.2),'甘肃':(92.2,32.0,108.9,42.9),'福建':(115.8,23.5,120.8,28.5),
 '西藏':(78.2,26.7,99.3,36.6),'贵州':(103.5,24.5,109.7,29.4),'辽宁':(118.8,38.6,125.9,43.6),
 '重庆':(105.2,28.1,110.3,32.3),'陕西':(105.4,31.6,111.4,39.7),'青海':(89.3,31.5,103.2,39.3),
 '黑龙江':(121.0,43.3,135.2,53.7)}
EP = "https://overpass-api.de/api/interpreter"

def norm(s):
    return str(s).replace('（', '(').replace('）', ')').replace(' ', '').strip()
def base(s):  # 去括号校区后缀
    s = norm(s); i = s.find('(')
    return s[:i] if i > 0 else s

def fetch_province(p):
    w, s, e, n = PBOX[p]
    q = f'[out:json][timeout:120];nwr["amenity"~"^(university|college)$"]["name"]({s},{w},{n},{e});out tags center;'
    req = urllib.request.Request(EP, data=urllib.parse.urlencode({'data': q}).encode(),
                                 headers={'User-Agent': 'gaokaomap-edu/1.0'})
    d = json.load(urllib.request.urlopen(req, timeout=140))
    out = []
    for el in d.get('elements', []):
        nm = el.get('tags', {}).get('name')
        la = el.get('lat') or el.get('center', {}).get('lat')
        lo = el.get('lon') or el.get('center', {}).get('lon')
        if nm and la and lo:
            out.append((nm, round(lo, 5), round(la, 5), el.get('tags', {}).get('amenity')))
    return out

# 1) 抓取全国基准(带缓存,避免重复抓 Overpass)
CACHE = os.path.join(D, "overpass-cache.json")
open(PROG, 'w').write("loading/fetching overpass...\n")
osm = {}; osm_base = {}
if os.path.exists(CACHE):
    c = json.load(open(CACHE, encoding='utf-8'))
    osm = {k: [tuple(x) for x in v] for k, v in c['osm'].items()}
    osm_base = {k: [tuple(x) for x in v] for k, v in c['base'].items()}
    open(PROG, 'a').write(f"CACHE loaded names={len(osm)}\n")
else:
    total = 0
    for i, p in enumerate(PBOX):
        try:
            rows = fetch_province(p)
        except Exception as ex:
            open(PROG, 'a').write(f"{p} FETCH-ERR {ex}\n"); rows = []
        for nm, lo, la, am in rows:
            osm.setdefault(norm(nm), []).append((lo, la, am))
            osm_base.setdefault(base(nm), []).append((lo, la, am))
        total += len(rows)
        open(PROG, 'a').write(f"{i+1}/31 {p}: +{len(rows)} (total {total})\n")
        time.sleep(2.0)
    json.dump({'osm': {k: list(v) for k, v in osm.items()},
               'base': {k: list(v) for k, v in osm_base.items()}},
              open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
    open(PROG, 'a').write(f"FETCHED total={total} names={len(osm)}\n")

# 2) 匹配并替换(本省 bbox 安全门)
def in_box(p, lo, la):
    b = PBOX.get(p)
    return (not b) or (b[0] <= lo <= b[2] and b[1] <= la <= b[3])
def pick(cands, p):  # 选落在本省的,优先 university
    valid = [(lo, la, am) for lo, la, am in cands if in_box(p, lo, la)]
    if not valid: return None
    valid.sort(key=lambda x: 0 if x[2] == 'university' else 1)
    return valid[0][0], valid[0][1]

unis = json.load(open(UNIS, encoding='utf-8'))
def dist(a, b):
    return ((a[0]-b[0])**2 + (a[1]-b[1])**2) ** 0.5
GATE = 0.2   # 原坐标已好的"精确校"只接受 <~20km 的细修,防止被错配到异地分校/同名校(回归)
acc_bad = acc_refine = rej_far = unmatched = 0
log = []
for u in unis:
    p = u.get('p'); nm = norm(u['n']); bn = base(u['n']); old = u.get('ll')
    was_bad = bool(u.get('approx')) or not (old and old[0] and in_box(p, old[0], old[1]))
    hit = None
    if nm in osm: hit = pick(osm[nm], p)
    if not hit and bn in osm_base: hit = pick(osm_base[bn], p)
    if not hit:
        unmatched += 1
        if len(log) < 600: log.append(['UNMATCHED', u['n']])
        continue
    if was_bad:                                  # 原坐标差 -> 放心采用本省匹配
        u['ll'] = [hit[0], hit[1]]; u.pop('approx', None); u['geo'] = 'overpass'; acc_bad += 1
    elif old and dist(old, hit) <= GATE:         # 原坐标好 -> 仅小幅细修
        u['ll'] = [hit[0], hit[1]]; u['geo'] = 'overpass'; acc_refine += 1
    else:                                        # 原坐标好但匹配点远 -> 不动,防回归(如福建农林大学->漳州)
        rej_far += 1
        if len(log) < 600: log.append(['KEPT-FAR', u['n'], old, [hit[0], hit[1]]])
json.dump(unis, open(UNIS, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
json.dump(log, open(os.path.join(D, 'overpass-log.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
open(PROG, 'a').write(f"MATCH bad-fixed={acc_bad} refined={acc_refine} kept-far={rej_far} unmatched={unmatched} of {len(unis)}\n")

try:
    import sqlite3
    con = sqlite3.connect(os.path.join(D, "gaokao-data", "gaokao.db"), timeout=60)
    upd = [(u['ll'][0], u['ll'][1], 'overpass', u['n']) for u in unis if u.get('geo') == 'overpass']
    con.executemany("UPDATE universities SET lng=?,lat=?,geo_src=? WHERE name=?", upd)
    con.commit(); con.close()
    open(PROG, 'a').write(f"DB updated {len(upd)}\n")
except Exception as e:
    open(PROG, 'a').write(f"DB skip {e}\n")
open(PROG, 'a').write("DONE\n")
print("done")
