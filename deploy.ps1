#requires -Version 5
<#
  gaokaomap 部署脚本 —— 在自托管盒子(Windows)上跑。
  做的事(带校验、失败即停):拉取 → 校验改动落地 → 30 省服务端冒烟(关键闸门)→
  重启 app.py → 上线自检 → 缓存提示。

  用法:
    .\deploy.ps1                 # 默认端口 8000、python 在 PATH
    .\deploy.ps1 -Port 8000 -Py python3

  关键安全点:冒烟在「重启」之前——冒烟不过就中止,app.py 仍跑旧逻辑、线上不受影响。
  注意:第 5 步「重启 app.py」按你盒子的实际运行方式(直接跑/nssm 服务/计划任务)可能要改,见该段。
#>
param(
  [int]$Port = 8000,
  [string]$Py = 'python'   # 若你的解释器是 python3,传 -Py python3
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Step($n, $m) { Write-Host "`n[$n] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  OK  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  !!  $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "  XX  $m" -ForegroundColor Red; exit 1 }

Write-Host "=== gaokaomap 部署 ===" -ForegroundColor Magenta
Write-Host "本轮含:河流出境截断 / 工具栏+筛选 hover / 默认配乐 / 改名「高考志愿填报模拟器」/ 推荐大类按组分档(引擎)"

# ── 1) 拉取最新(快进;工作区脏则中止,避免覆盖手改)─────────────────────
Step 1 "git pull --ff-only origin main"
if ((git status --porcelain | Measure-Object).Count -gt 0) {
  git status --short
  Die "工作区有未提交改动,先处理(stash/commit)再部署。slices/ __pycache__ 已 gitignore,不该出现在这里"
}
git fetch origin main 2>&1 | Out-Null
git pull --ff-only origin main
Ok ("HEAD = " + (git rev-parse --short HEAD))

# ── 2) 校验本轮关键改动确已落地(防 pull 没生效 / 文件错位)─────────────
Step 2 "校验关键改动已落地"
# 本轮关键改动的标记;下次部署改成你那轮的标记即可,或整组删掉、只靠第 4 步冒烟兜底。
$checks = [ordered]@{
  'gk-engine.js'              = '按组分档'          # 客户端引擎:大类按组分档
  'recommend.py'              = '按组分档'          # 服务端引擎:同构
  'index.html'                = 'gk-engine\.js\?v=3' # 引擎缓存戳已自增(immutable 破缓存)
  'geo/ne_50m_rivers_cn.json' = $null               # 河流裁剪文件存在即可
}
foreach ($f in $checks.Keys) {
  if (-not (Test-Path $f)) { Die "缺文件:$f(pull 未生效?)" }
  if ($checks[$f] -and -not (Select-String -Path $f -Pattern $checks[$f] -Quiet)) {
    Die "$f 未含预期标记『$($checks[$f])』—— 本轮改动没拉到,中止"
  }
  Ok $f
}

# ── 3) 切片:本轮是「引擎逻辑」改动,切片结构未变 → 无需重建 ──────────────
Step 3 "切片无需重建"
Ok "skip export-slices.py(仅当 gaokao.db 数据更新时才需:$Py export-slices.py)"

# ── 4) 服务端引擎冒烟(关键闸门):30 省跑 recommend,断言无 error + 冲稳保健康 ─
Step 4 "$Py scripts/smoke.py(30 省服务端冒烟 —— 按组分档后必须过)"
& $Py scripts/smoke.py
if ($LASTEXITCODE -ne 0) {
  Die "冒烟未通过 → 已中止,app.py 未重启,线上仍跑旧逻辑(安全)。排查 recommend.py 后重试"
}
Ok "30 省冒烟通过"

# ── 5) 重启 app.py(它 import recommend.py:旧进程仍是旧逻辑 + lru_cache,必须重启)──
#    ↓↓↓↓↓ 按你盒子的实际运行方式调整本段 ↓↓↓↓↓
#    下面是「直接跑 python app.py」的通用尝试;若你用 nssm 服务 / 计划任务 / pm2,
#    请改成对应的 restart(例:nssm restart gaokaomap)。
Step 5 "重启 app.py 端口 $Port"
$killed = 0
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match 'app\.py' } |
  ForEach-Object { Write-Host "  停止旧进程 PID $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force; $killed++ }
if ($killed -eq 0) { Warn "没找到在跑的 app.py 进程(可能由服务/计划任务托管)——若是,请改用你的 restart 命令并跳过下面的 Start-Process" }
Start-Sleep -Seconds 1
Start-Process -FilePath $Py -ArgumentList "app.py $Port" -WindowStyle Hidden
Start-Sleep -Seconds 3
Ok "app.py 已尝试重启"
#    ↑↑↑↑↑ 按你盒子的实际运行方式调整本段 ↑↑↑↑↑

# ── 6) 上线自检:本地直连 app.py,确认已起好 + 接口正常 ───────────────────
Step 6 "自检 http://127.0.0.1:$Port/api/meta"
try {
  $meta = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/meta" -TimeoutSec 20
  $n = ($meta.provinces | Measure-Object).Count
  if ($n -gt 0) { Ok "app.py 在跑,/api/meta 返回 $n 省" } else { Warn "/api/meta 省份数为 0,人工查一下" }
  # 按组分档抽检(best-effort,失败不阻断):浙江某分数 → 应有冲稳保
  try {
    $rec = Invoke-RestMethod -Uri ([uri]::EscapeUriString("http://127.0.0.1:$Port/api/recommend?prov=浙江&subj=综合&score=620")) -TimeoutSec 20
    $tot = (@($rec.bands.冲) + @($rec.bands.稳) + @($rec.bands.保) | Measure-Object).Count
    Ok "浙江·综合·620 → 冲稳保共 $tot 条(>0 即引擎在跑)"
  } catch { Warn "推荐抽检跳过:$($_.Exception.Message)" }
} catch { Warn "自检失败:$($_.Exception.Message) —— app.py 是否起好?端口 $Port 对不对?" }

# ── 7) Cloudflare 缓存提示(盒子 token 无 purge 权限)───────────────────────
Step 7 "缓存"
Write-Host "  gk-engine.js?v=3 —— 版本戳已变,immutable 也会取新"
Write-Host "  index.html      —— max-age=300,5 分钟内自动过期(无需 purge;想立刻看就硬刷新 Ctrl+Shift+R)"
Write-Host "  geo/*_cn.json   —— 新文件名,无需 purge"
Write-Host "`n部署完成。" -ForegroundColor Green
Write-Host "提醒:推荐引擎是大改动 —— 建议放量前再人工抽查 2~3 个省的『我的推荐』结果是否合理。" -ForegroundColor Yellow
