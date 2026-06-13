#!/usr/bin/env python3
"""坐标精度回填:对近似/可疑(落在错省)坐标的本科,用 OSM/Nominatim 重定位。
安全原则——只接受"落在本省"的结果(OSM display_name 含省名 + 省 bbox 双校验),
坏匹配/未找到一律保留原值;对明显跨省错位的(如清华美院在福建),回退到"母体高校同省坐标"
(母体=名称前缀命中的高校),并跳过异地校区(威海/苏州…名称含他市标记者),绝不把真分校挪错。
只会让坐标变准,不会更糟。WGS84,与底图(CARTO/OSM)一致。
"""
import json, os, time, urllib.request, urllib.parse

D = os.path.dirname(os.path.abspath(__file__))
UNIS = os.path.join(D, "unis.json")
PROG = os.path.join(D, "geocode-progress.txt")
LOG  = os.path.join(D, "geocode-log.json")

PBOX = {  # 省 -> (lngmin,latmin,lngmax,latmax) 粗略已留余量
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
BRANCH_CITY = ['威海','苏州','深圳','珠海','秦皇岛','克拉玛依','烟台','青岛','无锡','常州','宜兴','张家口','日照']

def in_box(p, ll):
    b = PBOX.get(p)
    if not b or not ll or not ll[0]: return True   # 未知省/无坐标 不判错
    return b[0] <= ll[0] <= b[2] and b[1] <= ll[1] <= b[3]

def geocode(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {'q': q, 'format': 'json', 'limit': 1, 'countrycodes': 'cn', 'accept-language': 'zh'})
    req = urllib.request.Request(url, headers={'User-Agent': 'gaokaomap-edu-backfill/1.0 (educational, contact via github)'})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=25))
        if d: return float(d[0]['lon']), float(d[0]['lat']), d[0].get('display_name', '')
    except Exception:
        return None
    return None

unis = json.load(open(UNIS, encoding='utf-8'))
names = {u['n']: u for u in unis}
def parent_of(u):  # 名称前缀命中的最长高校名(母体)
    n = u['n']; best = None
    for other in names:
        if other != n and n.startswith(other) and (not best or len(other) > len(best)):
            best = other
    return names.get(best) if best else None

targets = [u for u in unis if u.get('approx') or not in_box(u.get('p'), u.get('ll'))]
open(PROG, 'w').write(f"targets={len(targets)}\n")
fix = snap = rej = nf = 0
log = []
for i, u in enumerate(targets):
    p = u.get('p') or ''
    r = geocode(u['n'] + ' ' + p)
    done = False
    if r:
        lon, lat, disp = r
        if p and p in disp and in_box(p, [lon, lat]):
            u['ll'] = [round(lon, 5), round(lat, 5)]; u.pop('approx', None); u['geo'] = 'osm'
            fix += 1; log.append(['FIX', u['n'], u['ll']]); done = True
    if not done and not in_box(p, u.get('ll')):   # 仍跨省错位 -> 母体同省回退(跳过异地校区)
        if not any(c in u['n'] for c in BRANCH_CITY):
            par = parent_of(u)
            if par and par.get('p') == p and in_box(p, par.get('ll')):
                u['ll'] = par['ll'][:]; u.pop('approx', None); u['geo'] = 'parent'
                snap += 1; log.append(['SNAP', u['n'], '<-', par['n']]); done = True
    if not done:
        if r: rej += 1; log.append(['REJ', u['n'], r[2][:38]])
        else: nf += 1; log.append(['NF', u['n'], ''])
    if i % 20 == 0:
        open(PROG, 'a').write(f"{i}/{len(targets)} fix={fix} snap={snap} rej={rej} nf={nf}\n")
    time.sleep(1.1)

json.dump(unis, open(UNIS, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
json.dump(log, open(LOG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
open(PROG, 'a').write(f"DONE fix={fix} snap={snap} rej={rej} nf={nf} total={len(targets)}\n")

# 同步数据库(可选,失败不影响 unis.json 已存)
try:
    import sqlite3
    db = os.path.join(D, "gaokao-data", "gaokao.db")
    con = sqlite3.connect(db, timeout=60)
    upd = [(u['ll'][0], u['ll'][1], u.get('geo', 'osm'), u['n']) for u in unis if u.get('geo')]
    con.executemany("UPDATE universities SET lng=?,lat=?,geo_src=? WHERE name=?", upd)
    con.commit(); con.close()
    open(PROG, 'a').write(f"DB updated rows={len(upd)}\n")
except Exception as e:
    open(PROG, 'a').write(f"DB skip: {e}\n")
print("done")
