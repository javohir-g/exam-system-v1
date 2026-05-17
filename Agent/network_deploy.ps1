# Network Deployment Script
# This script copies the settings.exe to multiple computers on a local network.
# REQUIRES: Administrative access to target machines.

# List of target computer names or IP addresses
$computerNames = @(
    "Computer-01",
    "Computer-02"
    # Add more computers here
)

$exeName = "settings.exe"
$sourcePath = Join-Path $PSScriptRoot $exeName
$remotePathSuffix = "C$\pythonProject001v" # Target folder via Administrative share

# Check if source file exists
if (!(Test-Path $sourcePath)) {
    Write-Error "Source file not found: $sourcePath"
    exit
}

foreach ($computer in $computerNames) {
    Write-Host "`nProcessing $computer..." -ForegroundColor Cyan
    
    # 1. Test connectivity
    if (Test-Connection -ComputerName $computer -Count 1 -Quiet) {
        $targetNetworkPath = "\\$computer\$remotePathSuffix"
        
        try {
            # 2. Create remote directory if needed
            if (!(Test-Path $targetNetworkPath)) {
                Write-Host "Creating directory on $computer..." -ForegroundColor Gray
                New-Item -ItemType Directory -Path $targetNetworkPath -Force | Out-Null
            }
            
            # 3. Copy file
            Write-Host "Copying $exeName to $computer..." -ForegroundColor Gray
            Copy-Item -Path $sourcePath -Destination "$targetNetworkPath\$exeName" -Force
            Write-Host "Successfully deployed to $computer" -ForegroundColor Green
        }
        catch {
            Write-Warning "Failed to deploy to $computer. Check permissions or network path accessibility."
            $_.Exception.Message | Write-Host -ForegroundColor Red
        }
    }
    else {
        Write-Warning "Could not reach $computer. Skipping."
    }
}

Write-Host "`nNetwork deployment finished." -ForegroundColor Cyan
