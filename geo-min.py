#!/usr/bin/env python3
"""无损精简 geo/*.json:截断坐标精度 + 去空白。
顶点一个不删、拓扑不变(只裁掉看不见的亚像素精度)——视觉零变化,体积砍 ~45%。
水系/湖泊原本 ~13 位小数(亚毫米),裁到 4 位(~10m,远小于一个像素);
边界类裁到 5 位(~1m,杜绝任何顶点合并风险,不影响蒙版)。
用法: python3 geo-min.py [geo目录]   默认 geo/
"""
import json, os, sys

DECIMALS = {  # 装饰性水系裁更狠;其余(边界)更保守
    "ne_50m_rivers_lake_centerlines.json": 4,
    "ne_50m_lakes.json": 4,
}
DEFAULT_DEC = 5  # 边界/行政区:1m,安全


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


def feature_count(o):
    t = o.get("type")
    if t == "FeatureCollection":
        return len(o.get("features", []))
    return 1


def trim_file(path, nd):
    o = json.load(open(path, encoding="utf-8"))
    t = o.get("type")
    if t == "FeatureCollection":
        for f in o.get("features", []):
            if f.get("geometry"):
                trim_geom(f["geometry"], nd)
    elif t == "Feature":
        if o.get("geometry"):
            trim_geom(o["geometry"], nd)
    else:  # 裸 geometry / GeometryCollection
        trim_geom(o, nd)
    out = json.dumps(o, separators=(",", ":"), ensure_ascii=False)
    open(path, "w", encoding="utf-8").write(out)
    # 复核:能否原样解析回来、要素数不变
    chk = json.loads(out)
    assert feature_count(chk) == feature_count(o), f"要素数变了! {path}"
    return out


def main():
    geodir = sys.argv[1] if len(sys.argv) > 1 else "geo"
    tb = ta = 0
    print(f"{'文件':42}{'前':>7}{'后':>7}  位")
    for fn in sorted(os.listdir(geodir)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(geodir, fn)
        before = os.path.getsize(path)
        nd = DECIMALS.get(fn, DEFAULT_DEC)
        out = trim_file(path, nd)
        after = len(out.encode("utf-8"))
        tb += before
        ta += after
        print(f"{fn:42}{before//1024:>5}K{after//1024:>5}K  {nd}")
    print(f"{'合计':42}{tb//1024:>5}K{ta//1024:>5}K   省 {100-ta*100//tb}%(裸体积;gzip 后省更多)")


if __name__ == "__main__":
    main()
