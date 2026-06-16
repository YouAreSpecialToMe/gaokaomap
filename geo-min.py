#!/usr/bin/env python3
"""无损精简 geo/*.json:
1) 截断坐标精度 + 去空白(顶点不删、拓扑不变 → 视觉零变化);
2) 全球水系(natural-earth rivers/lakes)裁到中国——丢掉境外要素(它们永远在纸色蒙版下、看不见),
   河流 462→88、湖泊 405→60,水系再省 ~80%。
用法: python3 geo-min.py [geo目录]   默认 geo/
"""
import json, os, sys

DECIMALS = {"ne_50m_rivers_lake_centerlines.json": 4, "ne_50m_lakes.json": 4}
DEFAULT_DEC = 5
CROP_CN = {"ne_50m_rivers_lake_centerlines.json", "ne_50m_lakes.json"}
CN_BOX = (70, 14, 138, 57)   # 中国 + ~3° 余量;只要要素有一点落入即保留(跨境河仍完整)


def round_coords(c, nd):
    if isinstance(c, float):
        return round(c, nd)
    if isinstance(c, int):
        return c
    return [round_coords(x, nd) for x in c]


def trim_geom(g, nd):
    if not g:
        return
    if g.get("type") == "GeometryCollection":
        for x in g.get("geometries", []):
            trim_geom(x, nd)
    elif "coordinates" in g:
        g["coordinates"] = round_coords(g["coordinates"], nd)


def _iter_xy(c):
    if c and isinstance(c[0], (int, float)):
        yield c
        return
    for s in c:
        yield from _iter_xy(s)


def in_cn(g):
    if not g or not g.get("coordinates"):
        return False
    for x, y in _iter_xy(g["coordinates"]):
        if CN_BOX[0] <= x <= CN_BOX[2] and CN_BOX[1] <= y <= CN_BOX[3]:
            return True
    return False


def process(path, nd, crop):
    o = json.load(open(path, encoding="utf-8"))
    nfeat = None
    if o.get("type") == "FeatureCollection":
        feats = o.get("features", [])
        if crop:
            feats = [f for f in feats if in_cn(f.get("geometry"))]
            o["features"] = feats
        for f in feats:
            if f.get("geometry"):
                trim_geom(f["geometry"], nd)
        nfeat = len(feats)
    elif o.get("type") == "Feature":
        if o.get("geometry"):
            trim_geom(o["geometry"], nd)
    else:
        trim_geom(o, nd)
    out = json.dumps(o, separators=(",", ":"), ensure_ascii=False)
    open(path, "w", encoding="utf-8").write(out)
    json.loads(out)   # 复核:能原样解析
    return out, nfeat


def main():
    geodir = sys.argv[1] if len(sys.argv) > 1 else "geo"
    tb = ta = 0
    print(f"{'文件':42}{'前':>7}{'后':>7}  位  要素")
    for fn in sorted(os.listdir(geodir)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(geodir, fn)
        before = os.path.getsize(path)
        out, nfeat = process(path, DECIMALS.get(fn, DEFAULT_DEC), fn in CROP_CN)
        after = len(out.encode("utf-8"))
        tb += before
        ta += after
        print(f"{fn:42}{before//1024:>5}K{after//1024:>5}K  {DECIMALS.get(fn, DEFAULT_DEC)}  {nfeat if nfeat is not None else '-'}{'  (裁中国)' if fn in CROP_CN else ''}")
    print(f"{'合计':42}{tb//1024:>5}K{ta//1024:>5}K   省 {100-ta*100//tb}%(裸体积;gzip 后更省)")


if __name__ == "__main__":
    main()
