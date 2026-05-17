@echo off
:: This batch file runs the deploy.ps1 script without requiring manual PowerShell launch
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1"
pause
