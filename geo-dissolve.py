#!/usr/bin/env python3
"""把 100000_full.json 的 34 个省级面 dissolve 成单一国界轮廓 → geo/china-outline.json。
纸色蒙版（cover 非中国）原先用「每省外环挖洞」组一个多边形,34 个省洞在共享省界处
earcut 三角化出毛刺/三角伪影(典型:江西-湖北-安徽 三省交界·庐山一带的白色透明三角)。
dissolve 掉省界共边 → 单一国界轮廓(陆地一个大环 + 各岛屿),蒙版改用它当洞 → 无伪影。"""
import json, gzip, sys, os
from shapely.geometry import shape, mapping, MultiPolygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else "geo/100000_full.json"
OUT = sys.argv[2] if len(sys.argv) > 2 else "geo/china-outline.json"

g = json.load(open(SRC, encoding="utf-8"))
# 只并省级面(排除 100000_JD 九段线 dash —— 它本是线标,不该当洞)
geoms = []
for f in g["features"]:
    if (f.get("properties") or {}).get("adcode") == "100000_JD":
        continue
    s = shape(f["geometry"])
    if not s.is_valid:           # 真实边界数据常有自交/坏环 → buffer(0) 修复后再并
        s = s.buffer(0)
    geoms.append(s)
u = unary_union(geoms)
# 省界共边顶点不齐会在 dissolve 后留微缝/微洞 → 微膨胀再微收缩焊掉(~100m)
u = u.buffer(0.001).buffer(-0.001)
# 轻简化(~300m):蒙版是 0.5 半透明纸色、画在 prov-line 之下,边缘略简化看不出,但能压体积
u = u.simplify(0.005, preserve_topology=True)
# 丢极小岛(<~20km²,海面上几像素以下):蒙版盖住即可、不可见;岛多是体积大头,留陆地+海南/台湾/SAR+主要岛
if u.geom_type == "MultiPolygon":
    parts = [p for p in u.geoms if p.area > 0.0005]
    u = MultiPolygon(parts)
    print(f"  岛屿过滤:{len(geoms)}省 → 留 {len(parts)} 子面(陆地+大岛)")

out = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "中国国界·dissolve"}, "geometry": mapping(u)}]}
js = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
open(OUT, "w", encoding="utf-8").write(js)
n = len(u.geoms) if u.geom_type == "MultiPolygon" else 1
print(f"{OUT}: {len(js.encode())//1024}K / gz {len(gzip.compress(js.encode(),9))//1024}K  | {u.geom_type} 子面 {n}")
