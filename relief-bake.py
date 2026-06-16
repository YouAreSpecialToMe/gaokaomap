#!/usr/bin/env python3
"""烤一张中国地形静态占位图:把自托管 z5 DEM(terrarium)瓦片拼起来、按 App 的
color-relief 色带着色 + 轻山体阴影,存成一张小 webp。首屏先铺它(地形模样,不是平绿),
真 DEM 瓦片到了再覆盖精细化。输出 image source 用的经纬度四角。
依赖:Pillow numpy。瓦片读 demos/tiles,图写 assets/relief-cn.webp(两份)。"""
import os, math, numpy as np
from PIL import Image

Z = 5
TILES = "/Users/zhangxiansheng/projects/agentfeed/demos/tiles/terrarium/%d" % Z
OUTS = ["/Users/zhangxiansheng/projects/gaokaomap/assets/relief-cn.webp",
        "/Users/zhangxiansheng/projects/agentfeed/demos/assets/relief-cn.webp"]

# App 默认色带 wc.ramp(elevation→RGB)
RAMP = [(-11000,(238,231,211)),(-1,(238,231,211)),(0,(169,191,142)),(250,(188,200,142)),
        (700,(214,201,143)),(1300,(221,190,126)),(2100,(211,163,104)),(3000,(185,142,99)),
        (4000,(168,146,126)),(4700,(179,167,168)),(5300,(233,227,220)),(5800,(251,249,244))]

xs = sorted(int(d) for d in os.listdir(TILES) if d.isdigit())
ys = set()
for x in xs:
    for f in os.listdir("%s/%d" % (TILES, x)):
        if f.endswith(".png"):
            ys.add(int(f[:-4]))
x0, x1, y0, y1 = xs[0], xs[-1], min(ys), max(ys)
W, H = (x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256
elev = np.zeros((H, W), np.float32)
n_have = 0
for x in xs:
    for f in os.listdir("%s/%d" % (TILES, x)):
        if not f.endswith(".png"):
            continue
        y = int(f[:-4])
        im = np.asarray(Image.open("%s/%d/%s" % (TILES, x, f)).convert("RGB")).astype(np.float32)
        e = im[:, :, 0] * 256 + im[:, :, 1] + im[:, :, 2] / 256 - 32768
        elev[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = e
        n_have += 1

# 着色(逐通道线性插值)
es = np.array([s[0] for s in RAMP], np.float32)
cols = np.array([s[1] for s in RAMP], np.float32)
rgb = np.stack([np.interp(elev, es, cols[:, c]) for c in range(3)], axis=-1)

# 轻山体阴影(西北光),用高程梯度;像素米数按纬度修正
lat_mid = 36.0
cell = 40075016.0 / (2 ** Z * 256) * math.cos(math.radians(lat_mid))   # ~米/像素
gy, gx = np.gradient(elev)
ex = 2.2                                                               # 夸张系数,让起伏看得见
nx, ny, nz = -gx / cell * ex, -gy / cell * ex, 1.0
nl = np.sqrt(nx * nx + ny * ny + 1)
az, alt = math.radians(315), math.radians(45)
lx, ly, lz = math.cos(alt) * math.sin(az), math.cos(alt) * math.cos(az), math.sin(alt)
shade = np.clip(0.78 + 0.5 * ((nx * lx + ny * ly + nz * lz) / nl), 0.62, 1.18)
rgb = np.clip(rgb * shade[:, :, None], 0, 255).astype(np.uint8)

ow = 1400
img = Image.fromarray(rgb).resize((ow, round(ow * H / W)), Image.LANCZOS)
oh = img.size[1]

# 裁到中国版图:把边界 geojson 栅格化成 alpha(境外透明),免在 0.5 纸色蒙版下露出日本/印度地形
import json
from PIL import ImageDraw
def latd(yt): return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yt / 2 ** Z))))
west, east = x0 / 2 ** Z * 360 - 180, (x1 + 1) / 2 ** Z * 360 - 180
north, south = latd(y0), latd(y1 + 1)
def mercY(d): r = math.radians(d); return math.log(math.tan(math.pi / 4 + r / 2))
mt, mb = mercY(north), mercY(south)
gj = json.load(open("/Users/zhangxiansheng/projects/agentfeed/demos/geo/100000_full.json"))
alpha = Image.new("L", (ow, oh), 0)
dr = ImageDraw.Draw(alpha)
for ft in gj.get("features", []):
    g = ft.get("geometry") or {}
    polys = g.get("coordinates", []) if g.get("type") == "MultiPolygon" else [g.get("coordinates", [])]
    for poly in polys:
        if not poly:
            continue
        pts = [((c[0] - west) / (east - west) * ow, (mercY(c[1]) - mt) / (mb - mt) * oh) for c in poly[0]]
        if len(pts) >= 3:
            dr.polygon(pts, fill=255)
img = img.convert("RGBA")
img.putalpha(alpha)
for o in OUTS:
    os.makedirs(os.path.dirname(o), exist_ok=True)
    img.save(o, "WEBP", quality=82, method=6)

kb = os.path.getsize(OUTS[0]) // 1024
print("tiles %d  out %s  %dKB  (已裁到中国版图)" % (n_have, img.size, kb))
print("COORDS [[%.5f,%.5f],[%.5f,%.5f],[%.5f,%.5f],[%.5f,%.5f]]" % (
    west, north, east, north, east, south, west, south))
