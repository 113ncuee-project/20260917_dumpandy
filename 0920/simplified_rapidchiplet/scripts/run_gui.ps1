param([int]$Port = 0, [switch]$NoBrowser, [switch]$Offline)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'bootstrap_windows.ps1') -Port $Port -NoBrowser:$NoBrowser -Offline:$Offline
exit $LASTEXITCODE
