$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$ScriptDir = Split-Path -Parent $PSCommandPath
$ProjectDir = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectDir "logs"
$LogPath = Join-Path $LogDir "usb_attach_last.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Host "Mini2 USB attach helper needs Administrator rights. Relaunching..."
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-NoExit",
        "-File", "`"$PSCommandPath`""
    )
    Write-Host "An Administrator PowerShell window should open. This window can be closed."
    exit 0
}

$exitCode = 0
$transcriptStarted = $false

try {
    Start-Transcript -Path $LogPath -Force | Out-Null
    $transcriptStarted = $true

    Write-Host "Mini2 -> WSL USB attach helper"
    Write-Host "This window will stay open even if an error happens."
    Write-Host "Log file: $LogPath"
    Write-Host "Close HIKMICRO Viewer/Analyzer and OpenCV preview before attaching."
    Write-Host ""

    $usbipd = Get-Command usbipd -ErrorAction SilentlyContinue
    if (-not $usbipd) {
        Write-Host "usbipd is not installed. Installing usbipd-win with winget..."
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw "winget was not found. Install usbipd-win manually: https://github.com/dorssel/usbipd-win/releases"
        }
        winget install --interactive --exact dorssel.usbipd-win
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        $usbipd = Get-Command usbipd -ErrorAction SilentlyContinue
        if (-not $usbipd) {
            throw "usbipd was installed, but this terminal cannot see it yet. Close this window and rerun this PowerShell helper."
        }
    }

    Write-Host ""
    Write-Host "Current USB devices:"
    $usbList = usbipd list | Out-String
    Write-Host $usbList
    Write-Host ""
    Write-Host "Find the Mini2 row. It may be named Mini2, HIKMICRO, Hikvision, UVC Camera, USB Camera, or vendor-specific USB device."
    Write-Host "Known Mini2 USB vendor usually appears as 2bdf:xxxx. Example: 2bdf:0102"
    Write-Host "Shared means bind is done; it still needs attach to WSL."
    Write-Host ""

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

    $selectedState = ""
    if ($mini2Candidates.Count -eq 1) {
        $busid = $mini2Candidates[0].BusId
        $selectedState = $mini2Candidates[0].State
        Write-Host "Auto-detected HIK/Mini2 BUSID: $busid state=$selectedState"
    } else {
        if ($mini2Candidates.Count -gt 1) {
            Write-Host "Multiple 2bdf: candidates found: $($mini2Candidates.BusId -join ', ')"
        } else {
            Write-Host "No 2bdf: Mini2 candidate was auto-detected."
        }
        $busid = Read-Host "Enter Mini2 BUSID from usbipd list, for example 2-1"
        foreach ($candidate in $mini2Candidates) {
            if ($candidate.BusId -eq $busid) {
                $selectedState = $candidate.State
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($busid)) {
        throw "No BUSID entered."
    }

    Write-Host ""
    if ($selectedState -match "Shared|Attached") {
        Write-Host "Already shared: BUSID $busid state=$selectedState. Skipping bind and attaching to WSL."
    } else {
        Write-Host "Binding BUSID $busid for sharing..."
        usbipd bind --busid $busid
        if ($LASTEXITCODE -ne 0) {
            throw "usbipd bind failed with exit code $LASTEXITCODE. Check BUSID and Administrator rights."
        }
    }

    Write-Host ""
    Write-Host "Attaching BUSID $busid to WSL..."
    usbipd attach --wsl --busid $busid
    if ($LASTEXITCODE -ne 0) {
        throw "usbipd attach failed with exit code $LASTEXITCODE. If another app owns Mini2, close it and retry."
    }

    Write-Host ""
    Write-Host "Checking WSL USB visibility (/dev/bus/usb, HIK sysfs, and /dev/video if available)..."
    wsl bash -lc "echo /dev/bus/usb:; find /dev/bus/usb -maxdepth 2 -type c 2>/dev/null | head -20; echo; echo HIK sysfs:; found=0; for d in /sys/bus/usb/devices/*; do if [ -f \"\$d/idVendor\" ] && [ \"\$(cat \"\$d/idVendor\")\" = \"2bdf\" ]; then found=1; echo \"\$(basename \"\$d\") idVendor=\$(cat \"\$d/idVendor\") idProduct=\$(cat \"\$d/idProduct\" 2>/dev/null) product=\$(cat \"\$d/product\" 2>/dev/null)\"; fi; done; [ \"\$found\" = 1 ] || echo 'No HIK sysfs device'; echo; echo /dev/video:; ls -l /dev/video* 2>/dev/null || echo 'No /dev/video nodes yet'; echo; command -v lsusb >/dev/null && lsusb || true"

    Write-Host ""
    Write-Host "OK. Now rerun the WSL V4L2 probe shell script if you are using the legacy WSL path."
} catch {
    $exitCode = 1
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)"
    Write-Host "Log file: $LogPath"
} finally {
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch { }
    }
    Write-Host ""
    Read-Host "Press Enter to close"
}

exit $exitCode
