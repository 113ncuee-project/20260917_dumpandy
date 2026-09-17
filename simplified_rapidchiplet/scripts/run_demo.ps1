$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

$Python = Get-Command python -ErrorAction SilentlyContinue
$UsePyLauncher = $false

if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    $UsePyLauncher = $true
}

if (-not $Python) {
    throw "找不到 Python。請先安裝 Python 3.10 以上，或確認 python/py 已加入 PATH。"
}

if ($UsePyLauncher) {
    & $Python.Source -3 .\run.py --models shufflenet_v2_x1_0 --ppa-goal balanced --workload-search pareto-dp --dp-top-k 12 --out .\results\demo
} else {
    & $Python.Source .\run.py --models shufflenet_v2_x1_0 --ppa-goal balanced --workload-search pareto-dp --dp-top-k 12 --out .\results\demo
}

Write-Host ""
Write-Host "完成。請打開 results\demo\report.html 查看報告。"
