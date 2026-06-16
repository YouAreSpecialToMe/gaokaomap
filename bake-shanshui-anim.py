#!/usr/bin/env python3
"""烤一段"山水"进场动效(动画 webp):把自托管 z5 DEM 拼起来、按 App 色带着色,
让掠光(山体阴影的光向)正弦来回扫过山体 —— 起伏被动态揭示出 3D 立体感,而 60fps 全靠
浏览器解码、零现算,故可面对多人同时观看(同一静态文件,Cloudflare 边缘缓存)。
首屏当进场播放,放大即淡入可交互 2D 地图。与 relief-cn.webp 占位图同色带,过渡近无缝。
依赖 Pillow numpy。瓦片读本地 tiles/terrarium/5,境外透明裁到中国版图。"""
import os, math, json, numpy as np
from PIL import Image, ImageDraw

Z = 5
REPO = r"D:\Desktop\repos\gaokaomap"
TILES = os.path.join(REPO, "tiles", "terrarium", "5")
OUT = os.path.join(REPO, "assets", "shanshui-3d.webp")
GJ = os.path.join(REPO, "geo", "100000_full.json")

# 与 relief-cn.webp 占位图同一 wc 色带(elevation→RGB),进场→揭开过渡无缝
RAMP = [(-11000,(238,231,211)),(-1,(238,231,211)),(0,(169,191,142)),(250,(188,200,142)),
        (700,(214,201,143)),(1300,(221,190,126)),(2100,(211,163,104)),(3000,(185,142,99)),
        (4000,(168,146,126)),(4700,(179,167,168)),(5300,(233,227,220)),(5800,(251,249,244))]

# --- 拼高程 ---
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

# --- 着色(固定)+ 法线(固定),逐帧只换光向 ---
es = np.array([s[0] for s in RAMP], np.float32)
cols = np.array([s[1] for s in RAMP], np.float32)
base = np.stack([np.interp(elev, es, cols[:, c]) for c in range(3)], axis=-1)
lat_mid = 36.0
cell = 40075016.0 / (2 ** Z * 256) * math.cos(math.radians(lat_mid))
gy, gx = np.gradient(elev)
ex = 2.4
nx, ny, nz = -gx / cell * ex, -gy / cell * ex, 1.0
nl = np.sqrt(nx * nx + ny * ny + 1)

# --- 中国版图 alpha(境外透明)---
OW = 920
OH = round(OW * H / W)
def latd(yt): return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yt / 2 ** Z))))
west, east = x0 / 2 ** Z * 360 - 180, (x1 + 1) / 2 ** Z * 360 - 180
north, south = latd(y0), latd(y1 + 1)
def mercY(d): r = math.radians(d); return math.log(math.tan(math.pi / 4 + r / 2))
mt, mb = mercY(north), mercY(south)
gj = json.load(open(GJ, encoding="utf-8"))
alpha = Image.new("L", (OW, OH), 0)
dr = ImageDraw.Draw(alpha)
for ft in gj.get("features", []):
    g = ft.get("geometry") or {}
    polys = g.get("coordinates", []) if g.get("type") == "MultiPolygon" else [g.get("coordinates", [])]
    for poly in polys:
        if not poly: continue
        pts = [((c[0] - west) / (east - west) * OW, (mercY(c[1]) - mt) / (mb - mt) * OH) for c in poly[0]]
        if len(pts) >= 3: dr.polygon(pts, fill=255)

# --- 逐帧:掠光方位角正弦来回扫(f=0 与 f=N 同相 → 无缝循环)---
N = 28
alt = math.radians(40)
az0, amp = 315.0, 45.0
frames = []
for f in range(N):
    az = math.radians(az0 + amp * math.sin(2 * math.pi * f / N))
    lx, ly, lz = math.cos(alt) * math.sin(az), math.cos(alt) * math.cos(az), math.sin(alt)
    shade = np.clip(0.72 + 0.58 * ((nx * lx + ny * ly + nz * lz) / nl), 0.52, 1.28)
    rgb = np.clip(base * shade[:, :, None], 0, 255).astype(np.uint8)
    img = Image.fromarray(rgb).resize((OW, OH), Image.LANCZOS).convert("RGBA")
    img.putalpha(alpha)
    frames.append(img)

frames[0].save(OUT, "WEBP", save_all=True, append_images=frames[1:],
               duration=64, loop=0, quality=66, method=4)
print("frames %d  size %dx%d  %dKB  -> %s" % (N, OW, OH, os.path.getsize(OUT) // 1024, OUT))
print("COORDS west=%.4f east=%.4f north=%.4f south=%.4f" % (west, east, north, south))
