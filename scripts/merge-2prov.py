#!/usr/bin/env python3
"""补抓被 429 限流的省份(山西/河北),并入 overpass-cache.json。带 429 退避重试。"""
import json, os, time, urllib.request, urllib.parse
D = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(D, "overpass-cache.json")
EP = "https://overpass-api.de/api/interpreter"
BOX = {'山西': (110.1, 34.5, 114.8, 40.9), '河北': (113.3, 36.0, 119.9, 42.8)}  # (W,S,E,N)
def norm(s): return str(s).replace('（', '(').replace('）', ')').replace(' ', '').strip()
def base(s):
    s = norm(s); i = s.find('('); return s[:i] if i > 0 else s
def fetch(p):
    w, s, e, n = BOX[p]
    q = f'[out:json][timeout:120];nwr["amenity"~"^(university|college)$"]["name"]({s},{w},{n},{e});out tags center;'
    for attempt in range(4):
        try:
            req = urllib.request.Request(EP, data=urllib.parse.urlencode({'data': q}).encode(),
                                         headers={'User-Agent': 'gaokaomap-edu/1.0'})
            d = json.load(urllib.request.urlopen(req, timeout=140))
            return d.get('elements', [])
        except Exception as ex:
            print(f"  {p} try{attempt} err {ex}; backoff 20s", flush=True); time.sleep(20)
    return []
c = json.load(open(CACHE, encoding='utf-8'))
osm = c['osm']; ob = c['base']
for p in BOX:
    els = fetch(p); add = 0
    for el in els:
        nm = el.get('tags', {}).get('name')
        la = el.get('lat') or el.get('center', {}).get('lat')
        lo = el.get('lon') or el.get('center', {}).get('lon')
        if nm and la and lo:
            rec = [round(lo, 5), round(la, 5), el.get('tags', {}).get('amenity')]
            osm.setdefault(norm(nm), []).append(rec)
            ob.setdefault(base(nm), []).append(rec)
            add += 1
    print(f"{p}: +{add}", flush=True); time.sleep(8)
json.dump({'osm': osm, 'base': ob}, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
print(f"cache now names={len(osm)}", flush=True)
