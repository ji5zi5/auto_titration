$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$ScriptDir = Split-Path -Parent $PSCommandPath
$ProjectDir = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectDir "logs"
$LogPath = Join-Path $LogDir "wsl_usb_auto_attach_last.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

try { Start-Transcript -Path $LogPath -Force | Out-Null } catch { }

try {
    Write-Host "Auto-attaching Mini2 to WSL before V4L2 probe..."
    $usbipd = Get-Command usbipd -ErrorAction SilentlyContinue
    if (-not $usbipd) {
        Write-Host "usbipd not found. Install usbipd-win and attach Mini2 to WSL before using the legacy WSL path."
        exit 0
    }

    $usbList = usbipd list | Out-String
    Write-Host $usbList

    $mini2Candidates = @()
    foreach ($line in ($usbList -split "`r?`n")) {
        $columns = $line.Trim() -split "\s{2,}"
        if ($columns.Count -ge 4 -and $columns[1] -match "^2bdf:[0-9a-fA-F]{4}$") {
            $mini2Candidates += [pscustomobject]@{
                BusId = $columns[0]
                VidPid = $columns[1]
                Device = $columns[2]
                State = $columns[$columns.Count - 1]
            }
        }
    }

    if ($mini2Candidates.Count -lt 1) {
        Write-Host "No 2bdf: Mini2 candidate found in Windows usbipd list."
        exit 0
    }

    $mini2 = $mini2Candidates[0]
    Write-Host "Mini2 candidate: BUSID=$($mini2.BusId) VIDPID=$($mini2.VidPid) state=$($mini2.State) device=$($mini2.Device)"

    if ($mini2.State -match "Not shared") {
        Write-Host "Mini2 is Not shared. Run usbipd bind/attach as Administrator, then rerun the legacy WSL probe."
        exit 0
    }

    if ($mini2.State -match "Attached") {
        Write-Host "Already attached to WSL."
        exit 0
    }

    Write-Host "Running: usbipd attach --wsl --busid $($mini2.BusId)"
    usbipd attach --wsl --busid $mini2.BusId
    if ($LASTEXITCODE -ne 0) {
        Write-Host "usbipd attach returned exit code $LASTEXITCODE. Continuing so WSL probe can print diagnostics."
    } else {
        Write-Host "usbipd attach completed."
    }
} catch {
    Write-Host "Auto-attach error: $($_.Exception.Message)"
} finally {
    try { Stop-Transcript | Out-Null } catch { }
}

exit 0
