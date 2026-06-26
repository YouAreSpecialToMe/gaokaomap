#!/bin/bash
# 盒子上重建2026招生计划(官方考试院xlsx,16省)。先 pull gaokao-data(plans-2026/)。
# 用法: bash deploy-plans-official-2026.sh [db路径] [plans目录]
set -e
DB="${1:-gaokao-data/gaokao.db}"; P="${2:-../gaokao-data/plans-2026}"
ING="python3 ingest-plans-official-2026.py --db $DB --year 2026"
# 带科类列(物理类/历史类)或综合类的省:glob 该省全部官方计划文件,脚本自动滤艺体/归并项目后缀
for prov in 辽宁 四川 江苏 陕西 安徽 河南 福建 重庆 青海 山西 广西 云南 广东 北京 山东; do
  $ING --province "$prov" --source "${prov}考试院官方-2026" $P/*"$prov"*招生计划*.xlsx
done
# 天津:无科类列(综合省)+ 每校带(省)后缀 → 需 default-subject + strip-province
$ING --province 天津 --default-subject 综合 --strip-province --source "天津考试院官方-2026" "$P/天津2026招生计划.xlsx"
echo "✅ 16省官方招生计划入库完成,记得 export-slices.py + 重启"
