#!/usr/bin/env python3
"""烤一张【高清】中国地形图当"精致地形"占位:z6 DEM(比 z5 占位图细一倍)+ App 默认 sym 色带
着色 + 山体阴影,境外透明裁中国版图。前端把它当 relief-cn-img 即时铺上 —— 精致地形一进门就出,
不必等几十块真实瓦片在慢网下慢慢加载(治"best pic 不出来")。真实瓦片仍在其上按需精修。
依赖 Pillow numpy。瓦片读本地 tiles/terrarium/6,图写 assets/relief-cn2.webp。"""
import os, math, json, numpy as np
from PIL import Image, ImageDraw

Z = 6
REPO = os.path.dirname(os.path.abspath(__file__))   # 脚本所在仓(原硬编码 D:\… 只限那台盒子;改用脚本目录,跨机可跑)
TILES = os.path.join(REPO, "tiles", "terrarium", str(Z))
OUT = os.path.join(REPO, "assets", "relief-cn2.webp")
GJ = os.path.join(REPO, "geo", "100000_full.json")
# App 默认 sym 色带(山形符号)elevation→RGB,与放大后的"精致地形"同色
RAMP = [(-11000,(239,231,210)),(-1,(239,231,210)),(0,(159,184,126)),(250,(179,188,126)),
        (700,(210,189,114)),(1200,(227,185,92)),(2000,(223,166,78)),(3000,(188,138,82)),
        (4000,(168,127,84)),(5000,(203,183,143)),(5600,(246,240,225))]

xs = sorted(int(d) for d in os.listdir(TILES) if d.isdigit())
ys = set()
for x in xs:
    for f in os.listdir(os.path.join(TILES, str(x))):
        if f.endswith(".webp"): ys.add(int(f[:-5]))
x0, x1, y0, y1 = xs[0], xs[-1], min(ys), max(ys)
W, H = (x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256
elev = np.zeros((H, W), np.float32)
for x in xs:
    for f in os.listdir(os.path.join(TILES, str(x))):
        if not f.endswith(".webp"): continue
        y = int(f[:-5])
        im = np.asarray(Image.open(os.path.join(TILES, str(x), f)).convert("RGB")).astype(np.float32)
        e = im[:, :, 0] * 256 + im[:, :, 1] + im[:, :, 2] / 256 - 32768
        elev[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = e

es = np.array([s[0] for s in RAMP], np.float32); cols = np.array([s[1] for s in RAMP], np.float32)
rgb = np.stack([np.interp(elev, es, cols[:, c]) for c in range(3)], axis=-1)
# 山体阴影(西北光),z6 更细 → 山脊清晰
cell = 40075016.0 / (2 ** Z * 256) * math.cos(math.radians(36))
gy, gx = np.gradient(elev); ex = 2.2
nx, ny, nz = -gx / cell * ex, -gy / cell * ex, 1.0; nl = np.sqrt(nx * nx + ny * ny + 1)
az, alt = math.radians(315), math.radians(45)
lx, ly, lz = math.cos(alt) * math.sin(az), math.cos(alt) * math.cos(az), math.sin(alt)
shade = np.clip(0.78 + 0.5 * ((nx * lx + ny * ly + nz * lz) / nl), 0.6, 1.2)
rgb = np.clip(rgb * shade[:, :, None], 0, 255).astype(np.uint8)

OW = 2000; OH = round(OW * H / W)
img = Image.fromarray(rgb).resize((OW, OH), Image.LANCZOS)
def latd(yt): return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yt / 2 ** Z))))
west, east = x0 / 2 ** Z * 360 - 180, (x1 + 1) / 2 ** Z * 360 - 180
north, south = latd(y0), latd(y1 + 1)
def mercY(d): r = math.radians(d); return math.log(math.tan(math.pi / 4 + r / 2))
mt, mb = mercY(north), mercY(south)
gj = json.load(open(GJ, encoding="utf-8"))
alpha = Image.new("L", (OW, OH), 0); dr = ImageDraw.Draw(alpha)
for ft in gj.get("features", []):
    g = ft.get("geometry") or {}
    polys = g.get("coordinates", []) if g.get("type") == "MultiPolygon" else [g.get("coordinates", [])]
    for poly in polys:
        if not poly: continue
        pts = [((c[0] - west) / (east - west) * OW, (mercY(c[1]) - mt) / (mb - mt) * OH) for c in poly[0]]
        if len(pts) >= 3: dr.polygon(pts, fill=255)
img = img.convert("RGBA"); img.putalpha(alpha)
img.save(OUT, "WEBP", quality=68, method=6)   # q68:平滑地形+山影降质几乎无损,体积 ~156K→~66K(占位图,真 DEM 随后覆盖)
print("z%d tiles %d-%d  out %dx%d  %dKB" % (Z, xs[0], xs[-1], OW, OH, os.path.getsize(OUT) // 1024))
print("COORDS [[%.5f,%.5f],[%.5f,%.5f],[%.5f,%.5f],[%.5f,%.5f]]" % (
    west, north, east, north, east, south, west, south))
