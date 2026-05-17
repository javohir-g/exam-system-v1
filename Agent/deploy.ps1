# Deployment and Setup Script
# This script handles the relocation of the Agent executable to a dedicated directory.

$targetDir = Join-Path $env:LOCALAPPDATA "pythonProject001v"
$exeName = "settings.exe"
$sourcePath = Join-Path $PSScriptRoot $exeName
$targetPath = Join-Path $targetDir $exeName

# 1. Create target directory if it doesn't exist
if (!(Test-Path $targetDir)) {
    Write-Host "Creating directory: $targetDir" -ForegroundColor Cyan
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

# 2. Check if source EXE exists in the current script directory
if (Test-Path $sourcePath) {
    Write-Host "Copying $exeName to $targetDir..." -ForegroundColor Cyan
    Copy-Item -Path $sourcePath -Destination $targetPath -Force
    Write-Host "Success! File copied to $targetPath" -ForegroundColor Green
    
    # 3. Launch the program immediately
    Write-Host "Starting $exeName..." -ForegroundColor Cyan
    Start-Process -FilePath $targetPath

    # 4. Add to Startup (User-Level)
    $startupFolder = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
    $shortcutPath = Join-Path $startupFolder "$exeName.lnk"
    
    if (!(Test-Path $shortcutPath)) {
        Write-Host "Adding Shortcut to Startup folder..." -ForegroundColor Cyan
        $wshShell = New-Object -ComObject WScript.Shell
        $shortcut = $wshShell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $targetPath
        $shortcut.WorkingDirectory = $targetDir
        $shortcut.Save()
        Write-Host "Startup shortcut created successfully." -ForegroundColor Green
    } else {
        Write-Host "Startup shortcut already exists." -ForegroundColor Gray
    }
} else {
    Write-Warning "Source file not found: $sourcePath"
    Write-Host "Please ensure $exeName is in the same folder as this script (after extraction)." -ForegroundColor Yellow
}

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Note: To enable automatic startup, you can manually add a shortcut of the EXE to your Startup folder:" -ForegroundColor Gray
Write-Host "1. Press Win+R, type 'shell:startup', and hit Enter." -ForegroundColor Gray
Write-Host "2. Right-click your EXE in $targetDir and select 'Create Shortcut'." -ForegroundColor Gray
Write-Host "3. Move the shortcut to the Startup folder." -ForegroundColor Gray
