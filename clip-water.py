#!/usr/bin/env python3
# 把自然地球 50m 河流/湖泊裁剪到中国境内 —— 出国境即截断。
# 母版用 geo/china-outline.json(geo-dissolve.py 出的 dissolve 国界轮廓,跟 cream 蒙版同一条边),
# 故河流恰好止于蒙版起始处。输出 geo/ne_50m_rivers_cn.json + geo/ne_50m_lakes_cn.json(体量也大减)。
import json
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

outline = json.load(open("geo/china-outline.json", encoding="utf-8"))
china = unary_union([shape(f["geometry"]) for f in outline["features"]])
if not china.is_valid:
    china = china.buffer(0)

LINE = {"LineString", "MultiLineString"}
POLY = {"Polygon", "MultiPolygon"}


def keep(geom, want):
    # 交集可能掺进点/集合;只保留想要的维度(线给河、面给湖)
    if geom.is_empty:
        return None
    if geom.geom_type in want:
        return geom
    if geom.geom_type == "GeometryCollection":
        parts = [g for g in geom.geoms if g.geom_type in want]
        return unary_union(parts) if parts else None
    return None


def clip(src, dst, want):
    gj = json.load(open(src, encoding="utf-8"))
    out = []
    for f in gj.get("features", []):
        try:
            g = shape(f["geometry"])
            if not g.is_valid:
                g = g.buffer(0)
            inter = keep(g.intersection(china), want)
            if inter is None or inter.is_empty:
                continue
            out.append({"type": "Feature", "properties": f.get("properties", {}),
                        "geometry": mapping(inter)})
        except Exception:
            continue
    json.dump({"type": "FeatureCollection", "features": out},
              open(dst, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    print(f"{dst}: {len(out)} features")


clip("geo/ne_50m_rivers_lake_centerlines.json", "geo/ne_50m_rivers_cn.json", LINE)
clip("geo/ne_50m_lakes.json", "geo/ne_50m_lakes_cn.json", POLY)
