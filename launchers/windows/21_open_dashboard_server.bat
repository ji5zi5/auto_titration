@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0..\.."

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py -3"
) else (
  where python >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=python"
  ) else (
    echo Python command not found.
    pause
    exit /b 1
  )
)

if "%PORT%"=="" set "PORT=8765"
if "%DASHBOARD_HOST%"=="" set "DASHBOARD_HOST=0.0.0.0"
if "%LIVE_STREAM_PORT%"=="" set "LIVE_STREAM_PORT=8766"
if "%LIVE_CSV%"=="" set "LIVE_CSV=data\raw\windows-live-mini2-visible.csv"
if "%PREVIEW_DIR%"=="" set "PREVIEW_DIR=website\live"
if "%AUTO_COLLECT%"=="" set "AUTO_COLLECT=1"
if "%AUTO_FRAMES%"=="" set "AUTO_FRAMES=999999"
if "%CLEAN_OLD%"=="" set "CLEAN_OLD=1"
if "%VISIBLE_ROI_DETECTOR%"=="" set "VISIBLE_ROI_DETECTOR=yolo"
if "%AUTO_INSTALL_YOLO%"=="" set "AUTO_INSTALL_YOLO=1"
if "%AUTO_INSTALL_REQUIREMENTS%"=="" set "AUTO_INSTALL_REQUIREMENTS=1"

if /I not "%AUTO_INSTALL_REQUIREMENTS%"=="0" (
  echo Checking Python dependencies...
  %PYTHON_CMD% -c "import cv2, numpy, serial, sklearn, yaml" >nul 2>nul
  if errorlevel 1 (
    echo Installing required Python packages. First run can take several minutes...
    %PYTHON_CMD% -m pip install -r requirements.txt
    if errorlevel 1 (
      echo Python package install failed. Check internet connection and Python/pip installation.
      pause
      exit /b 1
    )
  )
)

if /I "%VISIBLE_ROI_DETECTOR%"=="yolo" if not "%AUTO_INSTALL_YOLO%"=="0" (
  echo Checking optional YOLO dependency...
  %PYTHON_CMD% -c "import ultralytics" >nul 2>nul
  if errorlevel 1 (
    echo Installing optional YOLO package. This can take several minutes...
    %PYTHON_CMD% -m pip install -r requirements-yolo.txt
    if errorlevel 1 (
      echo YOLO install failed. The app can still run if VISIBLE_ROI_DETECTOR is changed from yolo.
      pause
      exit /b 1
    )
  )
)

if /I not "%CLEAN_OLD%"=="0" (
  echo Closing old Auto Titration server/collector processes for this folder...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and ($_.CommandLine -match 'tools\\dashboard_server.py|tools\\windows_live_collect.py|20_windows_live_collect.bat') } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch { } }"
  timeout /t 1 >nul
)

set "LAN_IP="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ips=Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254*' -and $_.InterfaceAlias -notmatch 'vEthernet|Loopback|WSL|VMware|VirtualBox|Bluetooth' }; $ip=($ips | Sort-Object @{Expression={if($_.IPAddress -like '192.168.*'){0}elseif($_.IPAddress -like '10.*'){1}elseif($_.IPAddress -like '172.*'){2}else{3}}} | Select-Object -First 1 -ExpandProperty IPAddress); if($ip){$ip}"`) do set "LAN_IP=%%I"

echo Starting Auto Titration app server...
echo   Local URL: http://127.0.0.1:%PORT%/
if not "%LAN_IP%"=="" echo   LAN URL: http://%LAN_IP%:%PORT%/
echo   If the phone cannot open the LAN URL, allow Python or port %PORT% in Windows Defender Firewall.
echo   Live CSV: %LIVE_CSV%
echo   Camera stream: http://127.0.0.1:%LIVE_STREAM_PORT%/stream/visible.mjpg
echo   Thermal stream: http://127.0.0.1:%LIVE_STREAM_PORT%/stream/thermal.mjpg
echo.
start "Auto Titration App Server" cmd /k %PYTHON_CMD% tools\dashboard_server.py --host %DASHBOARD_HOST% --port %PORT% --csv "%LIVE_CSV%" --live-stream-base "http://127.0.0.1:%LIVE_STREAM_PORT%"

echo Waiting for app server...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$u='http://127.0.0.1:%PORT%/'; for($i=0; $i -lt 30; $i++){ try { $r=Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 1; if($r.StatusCode -eq 200){ exit 0 } } catch { } Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
  echo App server did not respond. Check the "Auto Titration App Server" window.
  pause
  exit /b 1
)

if /I not "%AUTO_COLLECT%"=="0" (
  if "%FRAMES%"=="" set "FRAMES=%AUTO_FRAMES%"
  set "OUTPUT=%LIVE_CSV%"
  echo Starting Mini2 + visible-camera collector...
  echo   Output: %LIVE_CSV%
  echo   Stream port: %LIVE_STREAM_PORT%
  echo   Frames: %FRAMES%
  echo   Visible ROI detector: %VISIBLE_ROI_DETECTOR%
  start "Auto Titration Collector" cmd /k call "launchers\windows\20_windows_live_collect.bat"
  echo Waiting for collector stream...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$u='http://127.0.0.1:%LIVE_STREAM_PORT%/api/collector-health'; for($i=0; $i -lt 60; $i++){ try { $r=Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 1; if($r.StatusCode -eq 200){ exit 0 } } catch { } Start-Sleep -Milliseconds 500 }; exit 1"
  if errorlevel 1 (
    echo Collector did not respond yet. The web page will show Run check hints.
    echo Check the "Auto Titration Collector" window for Python/camera/DLL errors.
  ) else (
    echo Collector stream is ready.
  )
) else (
  echo Collector auto-start skipped because AUTO_COLLECT=0.
)

start "" "http://127.0.0.1:%PORT%/"
exit /b 0
