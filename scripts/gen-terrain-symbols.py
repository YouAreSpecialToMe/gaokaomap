#!/usr/bin/env python3
"""Analyze terrarium DEM tiles, emit painted-map symbol points for China.

Downloads z5 elevation tiles, classifies sample points into mountain/hill/
dune/tree symbols by elevation + local relief, keeps only points inside the
China boundary, thins by per-type min distance, writes terrain-symbols.json.
"""
import io, json, math, random, urllib.request
from PIL import Image

Z = 5
XS = range(22, 29)   # lon ~67..146
YS = range(9, 14)    # lat ~21..56 -> covers 18 via y13 (down to ~17.3? check)
TILE = 256

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "terrain-symbols/1.0"})
    return urllib.request.urlopen(req, timeout=30).read()

# --- mosaic of elevation values ---
W = len(list(XS)) * TILE
H = len(list(YS)) * TILE
print(f"mosaic {W}x{H}, downloading {len(list(XS))*len(list(YS))} tiles ...")
mosaic = Image.new("RGB", (W, H))
for xi, x in enumerate(XS):
    for yi, y in enumerate(YS):
        data = fetch(f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{x}/{y}.png")
        mosaic.paste(Image.open(io.BytesIO(data)).convert("RGB"), (xi * TILE, yi * TILE))
px = mosaic.load()
X0, Y0 = min(XS), min(YS)

def elev(i, j):
    r, g, b = px[max(0, min(W - 1, i)), max(0, min(H - 1, j))]
    return r * 256 + g + b / 256 - 32768

def to_lnglat(i, j):
    xt = (X0 + i / TILE) / (2 ** Z)
    yt = (Y0 + j / TILE) / (2 ** Z)
    lng = xt * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yt))))
    return lng, lat

# --- China boundary (all outer rings) for point-in-polygon ---
print("downloading China outline ...")
cn = json.loads(fetch("https://geo.datav.aliyun.com/areas_v3/bound/100000.json"))
rings = [poly[0] for poly in cn["features"][0]["geometry"]["coordinates"]]
def in_china(lng, lat):
    for ring in rings:
        inside = False
        n = len(ring)
        for k in range(n):
            x1, y1 = ring[k]; x2, y2 = ring[(k + 1) % n]
            if (y1 > lat) != (y2 > lat):
                xint = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
                if lng < xint:
                    inside = not inside
        if inside:
            return True
    return False

DESERTS = [(75, 36.5, 90, 41.5), (94, 39.5, 110, 43.0), (106.5, 39.3, 111, 40.8)]
FORESTS = [(119, 46, 127, 53.3), (125.5, 41.5, 131, 49), (97, 24, 103, 30),
           (109, 24, 119, 28), (105, 31.5, 111, 34.2)]
def in_box(lng, lat, boxes):
    return any(a <= lng <= c and b <= lat <= d for a, b, c, d in boxes)

random.seed(42)
cands = []
STRIDE, WIN = 8, 6
for j in range(WIN, H - WIN, STRIDE):
    for i in range(WIN, W - WIN, STRIDE):
        e = elev(i, j)
        if e < -50:
            continue
        win = [elev(i + di, j + dj) for di in (-WIN, 0, WIN) for dj in (-WIN, 0, WIN)]
        relief = max(win) - min(win)
        lng, lat = to_lnglat(i, j)
        lng += random.uniform(-0.14, 0.14)
        lat += random.uniform(-0.12, 0.12)
        t = None
        if e > 4200 and relief > 600: t = "m3"
        elif e > 2200 and relief > 500: t = "m2"
        elif e > 550 and relief > 380: t = "m1"
        elif in_box(lng, lat, DESERTS) and relief < 320: t = "dune"
        elif in_box(lng, lat, FORESTS) and e < 1900: t = "tree"
        if t:
            cands.append((lng, lat, t, e, relief))

print(f"candidates: {len(cands)}")
# strongest ridges claim their spot first -> symbols chain along real ranges
cands.sort(key=lambda c: -c[4])
MIN_D = {"m3": 1.5, "m2": 1.6, "m1": 1.7, "dune": 1.1, "tree": 1.3}
CAP = {"m3": 110, "m2": 100, "m1": 120, "dune": 50, "tree": 65}
from collections import Counter
counts = Counter()
kept = []
for lng, lat, t, e, relief in cands:
    if counts[t] >= CAP[t]:
        continue
    d = MIN_D[t]
    ok = True
    for lng2, lat2, t2, _ in kept:
        if t2 == t and abs(lng - lng2) < d and abs(lat - lat2) < d * 0.8:
            ok = False; break
    if ok and in_china(lng, lat):
        kept.append((lng, lat, t, e))
        counts[t] += 1

print("kept:", counts)
# per-type size 0.8..1.3 by elevation rank, so high peaks paint bigger
by_type = {}
for lng, lat, t, e in kept:
    by_type.setdefault(t, []).append(e)
rng = {t: (min(v), max(v)) for t, v in by_type.items()}
out = []
for lng, lat, t, e in kept:
    lo, hi = rng[t]
    s = 0.8 + 0.5 * ((e - lo) / (hi - lo) if hi > lo else 0.5)
    out.append([round(lng, 2), round(lat, 2), t, round(s, 2)])
with open("terrain-symbols.json", "w") as f:
    json.dump({"symbols": out}, f, ensure_ascii=False)
print(f"wrote terrain-symbols.json with {len(out)} symbols")
