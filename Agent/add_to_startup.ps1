$WshShell = New-Object -ComObject WScript.Shell
$StartupPath = [System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup')
$Shortcut = $WshShell.CreateShortcut([System.IO.Path]::Combine($StartupPath, 'ScreenFrogAgent.lnk'))
$Shortcut.TargetPath = 'E:\screen frog\EXAM_SYSTEM\Agent\run_silent.vbs'
$Shortcut.WorkingDirectory = 'E:\screen frog\EXAM_SYSTEM\Agent'
$Shortcut.Save()
write-host "Startup shortcut created successfully."
