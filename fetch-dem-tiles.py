#!/usr/bin/env python3
"""预下载「中国范围」的地形 DEM 瓦片(terrarium)到本地,自托管 —— 免外网(AWS s3)慢/不可达,
访客打开即用本地瓦片,告别"加载方块"。地形是柔和水墨底,默认 z2–6(约 10MB)即够区域级观感,
放大靠过采样(柔和但即时、无方块);要更清晰可调大 maxzoom。

  python3 fetch-dem-tiles.py                  # z2–6 中国 → tiles/terrarium (~10MB)
  python3 fetch-dem-tiles.py --maxzoom 7      # 更清晰到城市级 (~45MB)
  python3 fetch-dem-tiles.py --maxzoom 8      # 最清晰 (~170MB,慎用)

幂等:已存在的瓦片跳过,失败可重跑补齐。完成后写 tiles/terrarium/ready(内含 maxzoom)。
前端(index.html)启动时探测该 ready:存在则改用本地源(maxzoom 取其值),否则回退 AWS——
所以"没下也能跑、下了自动加速",零改码切换。部署:在自托管机的服务目录里跑一次即可。
"""
import math, os, argparse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

SRC = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

def deg2tile(lng, lat, z):
    n = 2 ** z
    x = int((lng + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y

def tiles_for(bbox, zmin, zmax):
    w, s, e, nn = bbox
    out = []
    for z in range(zmin, zmax + 1):
        x0, y0 = deg2tile(w, nn, z)        # 西北角(y 较小)
        x1, y1 = deg2tile(e, s, z)         # 东南角(y 较大)
        n = 2 ** z
        for x in range(max(0, x0), min(n - 1, x1) + 1):
            for y in range(max(0, y0), min(n - 1, y1) + 1):
                out.append((z, x, y))
    return out

def fetch(t, outdir):
    z, x, y = t
    p = os.path.join(outdir, str(z), str(x), f"{y}.png")
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return "skip"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    url = SRC.format(z=z, x=x, y=y)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gaokaomap-dem/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = r.read()
            with open(p, "wb") as f:
                f.write(data)
            return "ok"
        except Exception as e:
            if attempt == 2:
                return f"err {e}"
    return "err"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minzoom", type=int, default=2)
    ap.add_argument("--maxzoom", type=int, default=6)
    ap.add_argument("--bbox", default="73,17,135,54", help="W,S,E,N(默认中国大陆+海南)")
    ap.add_argument("--out", default="tiles/terrarium")
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()
    bbox = tuple(float(v) for v in a.bbox.split(","))
    ts = tiles_for(bbox, a.minzoom, a.maxzoom)
    print(f"目标 {len(ts)} 块瓦片 (z{a.minzoom}–{a.maxzoom}, bbox {a.bbox}) → {a.out}/")
    ok = skip = err = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(fetch, t, a.out): t for t in ts}
        for i, f in enumerate(as_completed(futs)):
            r = f.result()
            if r == "ok": ok += 1
            elif r == "skip": skip += 1
            else: err += 1
            if (i + 1) % 200 == 0 or i + 1 == len(ts):
                print(f"  {i+1}/{len(ts)}  ok={ok} skip={skip} err={err}")
    with open(os.path.join(a.out, "ready"), "w") as f:   # 标记:内含 maxzoom,供前端取本地源 maxzoom
        f.write(str(a.maxzoom))
    sz = sum(os.path.getsize(os.path.join(dp, fn))
             for dp, _, fns in os.walk(a.out) for fn in fns)
    print(f"完成: ok={ok} skip={skip} err={err} · 总大小 {sz/1e6:.1f}MB · 标记 {a.out}/ready={a.maxzoom}")
    if err:
        print(f"⚠ {err} 块失败(网络抖动?可重跑补齐,幂等)")

if __name__ == "__main__":
    main()
