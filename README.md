# 高考升学地图 gaokaomap

古地图画卷风的高考志愿辅助:全国 1,598 所本科院校浏览 · 分数/位次冲稳保推荐 · RIASEC 专业测评。

**数据底座**(31 省 × 2017-2025):投档线 584 万行(位次 98%)· 招生计划 334 万 · 一分一段 26 万段 · 学科评估 · 开设专业图谱 11 万。

**在线 demo**:[agentsfeed.org/app-demo](https://agentsfeed.org/app-demo)

## 本地运行

```bash
git clone git@github.com:YouAreSpecialToMe/gaokaomap.git && cd gaokaomap
# 数据库(2.1GB,私有仓库,需权限):
git clone --depth 1 git@github.com:YouAreSpecialToMe/gaokao-data.git
cat gaokao-data/gaokao.db.gz.part-* | gunzip > gaokao-data/gaokao.db
# 启动(单进程,前端+API 同端口):
python3 app.py 8000     # → http://127.0.0.1:8000
```

依赖:Python 3.8+,标准库即可(ETL 脚本另需 `pip install python-calamine`)。

## 功能
- **画卷地图**:CC0 明清木刻笔刷(Zuodong)+ 真实 DEM 地形 + 分层设色;城市/景点/街巷层
- **我的推荐**:省/科类/分数 → 一分一段位次换算 → 跨年等效位次 → 冲稳保(边界经 23 万样本回测校准:冲 15-40% / 稳 55-88% / 保 ≥90% 真实录取率)→ 画卷点亮
- **专业测评**:24 题霍兰德 RIASEC → 六维画像 → 专业类匹配 × 位次可达院校
- **院校卡片**:学科评估 / 保研率 / 本省近三年专业位次

## 目录
- `app.py` 单进程服务(静态 + /api/meta /api/recommend /api/uni /api/quiz*)
- `recommend.py` 推荐引擎 · `quiz_data.py` 测评题库与专业映射
- `scripts/` 数据 ETL(通用省份引擎/回测/冒烟)· `docs/` 设计文档

## 声明
数据来自各省教育考试院等公开渠道整理,仅供参考,不构成志愿填报依据。用户输入即算即弃,不收集任何个人信息。
校徽素材整理自 [China-University-Emblems](https://github.com/fenqijun/China-University-Emblems)(覆盖 1294/1598 所,余者以生成印章代替);校徽版权归各校所有,本项目为非商业教育用途,如有异议即撤。

配乐:萨蒂《Gymnopédie No.1》,演奏录音 [Kevin MacLeod](https://incompetech.com)([archive.org](https://archive.org/details/gymnopedie-no-1-by-kevin-macleod)),授权 CC-BY 4.0;乐曲本身为公有领域。
