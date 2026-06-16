#!/usr/bin/env python3
"""烤"视差立体山水"两个图层(2.5D · 纯预渲染,不需实时 3D):
  assets/shanshui-far.webp  = 整片山水(雾化后退的远景背景,境外透明裁中国)
  assets/shanshui-near.webp = 隆起的山体(按高程平滑抠 alpha:平原透明、山地清晰,叠在远景上)
前端把两层叠放,鼠标移动 / 手机倾斜 / 自动飘移时以不同速度位移 → 纸雕立体景深。
与 relief-cn.webp 同投影同范围(west/east/north/south 一致),完美对齐。依赖 Pillow numpy。"""
import os, math, json, numpy as np
from PIL import Image, ImageDraw

Z = 5
REPO = r"D:\Desktop\repos\gaokaomap"
TILES = os.path.join(REPO, "tiles", "terrarium", "5")
GJ = os.path.join(REPO, "geo", "100000_full.json")
FAR = os.path.join(REPO, "assets", "shanshui-far.webp")
NEAR = os.path.join(REPO, "assets", "shanshui-near.webp")
RAMP = [(-11000,(238,231,211)),(-1,(238,231,211)),(0,(169,191,142)),(250,(188,200,142)),
        (700,(214,201,143)),(1300,(221,190,126)),(2100,(211,163,104)),(3000,(185,142,99)),
        (4000,(168,146,126)),(4700,(179,167,168)),(5300,(233,227,220)),(5800,(251,249,244))]

# --- elevation ---
xs = sorted(int(d) for d in os.listdir(TILES) if d.isdigit()); ys = set()
for x in xs:
    for f in os.listdir(os.path.join(TILES, str(x))):
        if f.endswith(".webp"): ys.add(int(f[:-5]))
x0, x1, y0, y1 = xs[0], xs[-1], min(ys), max(ys)
W, H = (x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256
elev = np.zeros((H, W), np.float32)
for x in xs:
    for f in os.listdir(os.path.join(TILES, str(x))):
        if not f.endswith(".webp"): continue
        y = int(f[:-5]); im = np.asarray(Image.open(os.path.join(TILES, str(x), f)).convert("RGB")).astype(np.float32)
        e = im[:, :, 0] * 256 + im[:, :, 1] + im[:, :, 2] / 256 - 32768
        elev[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = e

# --- color + hillshade ---
es = np.array([s[0] for s in RAMP], np.float32); cols = np.array([s[1] for s in RAMP], np.float32)
rgb = np.stack([np.interp(elev, es, cols[:, c]) for c in range(3)], axis=-1)
cell = 40075016.0 / (2 ** Z * 256) * math.cos(math.radians(36)); gy, gx = np.gradient(elev); ex = 2.6
nx, ny, nz = -gx / cell * ex, -gy / cell * ex, 1.0; nl = np.sqrt(nx * nx + ny * ny + 1)
az, alt = math.radians(315), math.radians(45)
lx, ly, lz = math.cos(alt) * math.sin(az), math.cos(alt) * math.cos(az), math.sin(alt)
shade = np.clip(0.74 + 0.55 * ((nx * lx + ny * ly + nz * lz) / nl), 0.55, 1.3)
base = np.clip(rgb * shade[:, :, None], 0, 255)

OW = 1400; OH = round(OW * H / W)
# --- china alpha ---
def latd(yt): return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yt / 2 ** Z))))
west, east = x0 / 2 ** Z * 360 - 180, (x1 + 1) / 2 ** Z * 360 - 180
north, south = latd(y0), latd(y1 + 1)
def mercY(d): r = math.radians(d); return math.log(math.tan(math.pi / 4 + r / 2))
mt, mb = mercY(north), mercY(south)
gj = json.load(open(GJ, encoding="utf-8")); cna = Image.new("L", (OW, OH), 0); dr = ImageDraw.Draw(cna)
for ft in gj.get("features", []):
    g = ft.get("geometry") or {}; polys = g.get("coordinates", []) if g.get("type") == "MultiPolygon" else [g.get("coordinates", [])]
    for poly in polys:
        if not poly: continue
        pts = [((c[0] - west) / (east - west) * OW, (mercY(c[1]) - mt) / (mb - mt) * OH) for c in poly[0]]
        if len(pts) >= 3: dr.polygon(pts, fill=255)
cna_np = np.asarray(cna).astype(np.float32) / 255

base_s = np.asarray(Image.fromarray(base.astype(np.uint8)).resize((OW, OH), Image.LANCZOS)).astype(np.float32)
elev_s = np.asarray(Image.fromarray(elev).resize((OW, OH), Image.BILINEAR)).astype(np.float32)

# FAR: hazed full relief (atmospheric back)
haze = np.array([236, 228, 206], np.float32)
far_rgb = base_s * 0.62 + haze * 0.38
Image.fromarray(np.dstack([far_rgb, cna_np * 255]).astype(np.uint8), "RGBA").save(FAR, "WEBP", quality=80, method=6)

# NEAR: crisp raised terrain; alpha = smoothstep(elev,200,1800) * china
t = np.clip((elev_s - 200) / (1800 - 200), 0, 1); t = t * t * (3 - 2 * t)
Image.fromarray(np.dstack([base_s, t * cna_np * 255]).astype(np.uint8), "RGBA").save(NEAR, "WEBP", quality=84, method=6)

print("FAR %dKB  NEAR %dKB  %dx%d" % (os.path.getsize(FAR)//1024, os.path.getsize(NEAR)//1024, OW, OH))
print("COORDS west=%.4f east=%.4f north=%.4f south=%.4f" % (west, east, north, south))
