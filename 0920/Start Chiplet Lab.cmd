@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0simplified_rapidchiplet\scripts\bootstrap_windows.ps1" %*
if errorlevel 1 pause
