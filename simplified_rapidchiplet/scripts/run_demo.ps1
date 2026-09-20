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
    & $Python.Source -3 .\run.py --preference balanced --out .\results\demo
} else {
    & $Python.Source .\run.py --preference balanced --out .\results\demo
}

Write-Host ""
if ($LASTEXITCODE -ne 0) { throw "DSE 執行失敗，請查看上方錯誤。" }
Write-Host "完成。請打開 results\demo\preference_search_summary.csv 與 preference_search_results.json。"
