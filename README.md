# 高考升学地图 · GaokaoMap

古地图画卷风格的中国高考志愿交互地图。真实数据驱动:全国 **1,598 所本科院校**
(双一流 147 所立旗 + 普通本科点阵)、第四轮学科评估、保研率/硕博点画像,
配合 30 省 × 2017-2024 一分一段表与浙江 6.5 万行投档线,支撑"分数 → 位次 → 冲稳保"推荐闭环。

## 快速开始

```bash
python3 -m http.server 8765
# 打开 http://localhost:8765/
```

需要联网加载:MapLibre GL JS(unpkg)、省界 GeoJSON(DataV)、
地形瓦片(AWS terrarium)、水系(Natural Earth)、街道瓦片(CARTO,城市级缩放才加载)。

## 视觉方案

- **MapLibre GL JS v5**:真实 DEM 地形(可调夸张)+ color-relief 海拔分层设色 + hillshade
- **双画风一键切换**:山形符号(明清木刻舆图风)/ 水彩浮雕(Imhof 学派配色)
- **木刻笔刷**:山/丘/林/浪/城池/宝塔符号取自 [Zuodong 笔刷集](https://kmalexander.com/2023/01/19/zuodong-a-free-17th-century-brush-set-for-fantasy-maps/)
  (17 世纪中国木刻地图提取,**CC0**),离线按真实 DEM 高程+起伏度自动布点(915 → 抽稀 396 点)
- 飘带双描边河流、花瓣粒子、开场运镜、城市级街巷渐显 + 区县结构

## 数据管线(scripts/)

| 脚本 | 作用 |
|---|---|
| `etl-universities.py` | 院校基础信息 Excel → universities(3,218 校)+ subject_eval(学科评估 4,902 行) |
| `etl-coords.py` | pg7go 坐标(BD09)模糊匹配 + BD09→GCJ02→WGS84 转换,97% 覆盖 |
| `etl-rank-tables.py` | 30 省一分一段 Excel → rank_tables(23 万行) |
| `etl-zj-admissions.py` | 浙江校级 5 年 + 专业级 2 年投档线 → admission_lines(6.5 万行) |
| `export-map-data.py` | gaokao.db → unis.json(地图用,学科评估驱动筛选标签) |
| `gen-terrain-symbols.py` | DEM 分析 → terrain-symbols.json(山形符号点位) |
| `prep-zuodong.py` | Zuodong 笔刷染色/缩放 → assets/zuodong/ |

**注意**:`gaokao.db` 与原始数据集(购买所得)不随仓库分发;
按 `docs/data-plan.md` 获取数据源后运行上述脚本可完整重建。

## 数据源与许可

- 代码:MIT
- 木刻笔刷:CC0(K.M. Alexander #NoBadMaps / Zuodong)
- 院校坐标:[pg7go/The-Location-Data-of-Schools-in-China](https://github.com/pg7go/The-Location-Data-of-Schools-in-China)(BD09,已转 WGS84)
- 一分一段/投档线:各省教育考试院公开信息(经第三方整理购入,不在本仓库分发)
- 省界:阿里 DataV Atlas;地形:AWS Terrain Tiles;水系:Natural Earth;街道:CARTO(注意其商用条款)

> 免责声明:demo 阶段数据未经考试院逐条核验,不构成志愿填报建议。
