@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0..\.."

set "PYTHON_CMD="
set "PYTHON_ARGS="
where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py"
  set "PYTHON_ARGS=-3"
) else (
  where python >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=python"
    set "PYTHON_ARGS="
  ) else (
    echo Python command not found.
    pause
    exit /b 1
  )
)

if "%FRAMES%"=="" set "FRAMES=999999"
if "%MINI2_INDEX%"=="" set "MINI2_INDEX=auto"
if "%MINI2_BACKEND%"=="" set "MINI2_BACKEND=AUTO"
if "%ALLOW_MINI2_MISSING%"=="" set "ALLOW_MINI2_MISSING=1"
if "%MINI2_RETRY_INTERVAL_S%"=="" set "MINI2_RETRY_INTERVAL_S=3"
if "%VISIBLE_INDEX%"=="" set "VISIBLE_INDEX=auto"
if "%VISIBLE_BACKEND%"=="" set "VISIBLE_BACKEND=DSHOW"
if "%VISIBLE_WIDTH%"=="" set "VISIBLE_WIDTH=320"
if "%VISIBLE_HEIGHT%"=="" set "VISIBLE_HEIGHT=240"
if "%THERMAL_ROI%"=="" set "THERMAL_ROI=96,72,64,48"
if "%THERMAL_PROCESSING%"=="" set "THERMAL_PROCESSING=roi"
if "%THERMAL_ROTATION_DEGREES%"=="" set "THERMAL_ROTATION_DEGREES=180"
if "%VISIBLE_ROI%"=="" set "VISIBLE_ROI=auto"
if "%OUTPUT%"=="" set "OUTPUT=data\raw\windows-live-mini2-visible.csv"
if "%STREAM_EVERY%"=="" set "STREAM_EVERY=0"
if "%PREVIEW_DIR%"=="" set "PREVIEW_DIR=website\live"
if "%PREVIEW_EVERY%"=="" set "PREVIEW_EVERY=0"
if "%LIVE_STREAM_HOST%"=="" set "LIVE_STREAM_HOST=127.0.0.1"
if "%LIVE_STREAM_PORT%"=="" set "LIVE_STREAM_PORT=8766"
if "%LIVE_STREAM_JPEG_QUALITY%"=="" set "LIVE_STREAM_JPEG_QUALITY=60"
if "%ROI_CLICK_ENABLED%"=="" set "ROI_CLICK_ENABLED=1"
if "%ROI_LINK_MODE%"=="" set "ROI_LINK_MODE=anchor"
if "%ROI_AUTO_DETECT%"=="" set "ROI_AUTO_DETECT=off"
if "%VISIBLE_ROI_DETECTOR%"=="" set "VISIBLE_ROI_DETECTOR=yolo"
if "%YOLO_MODEL%"=="" set "YOLO_MODEL=yolo11n-seg.pt"
if "%YOLO_CLASSES%"=="" set "YOLO_CLASSES=cup,bottle,wine glass,bowl,vase,beaker,flask,glass,container"
if "%YOLO_MIN_CONFIDENCE%"=="" set "YOLO_MIN_CONFIDENCE=0.25"
if "%YOLO_MAX_AREA_FRACTION%"=="" set "YOLO_MAX_AREA_FRACTION=0.45"
if "%YOLO_MIN_INTERVAL_MS%"=="" set "YOLO_MIN_INTERVAL_MS=200"
if "%YOLO_SUCCESS_INTERVAL_MS%"=="" set "YOLO_SUCCESS_INTERVAL_MS=200"
if "%YOLO_INPUT_SIZE%"=="" set "YOLO_INPUT_SIZE=256"
if "%AUTO_INSTALL_YOLO%"=="" set "AUTO_INSTALL_YOLO=0"
if "%ROI_AUTO_MIN_CONFIDENCE%"=="" set "ROI_AUTO_MIN_CONFIDENCE=0.25"
if "%ROI_AUTO_EVERY%"=="" set "ROI_AUTO_EVERY=5"
if "%AUTO_ROI_WORKER%"=="" set "AUTO_ROI_WORKER=0"
if "%AUTO_ROI_RESULT_MAX_AGE_MS%"=="" set "AUTO_ROI_RESULT_MAX_AGE_MS=2000"
if "%MAX_SYNC_OFFSET_MS%"=="" set "MAX_SYNC_OFFSET_MS=40"
if "%VISIBLE_SYNC_MAX_AGE_MS%"=="" set "VISIBLE_SYNC_MAX_AGE_MS=1000"
if "%PUMP_SERIAL_PORT%"=="" set "PUMP_SERIAL_PORT=auto"
if "%PUMP_SERIAL_BAUD%"=="" set "PUMP_SERIAL_BAUD=9600"
if "%PUMP_SERIAL_RETRY_INTERVAL_S%"=="" set "PUMP_SERIAL_RETRY_INTERVAL_S=2"
if "%PUMP_START_COMMAND%"=="" set "PUMP_START_COMMAND=b"
if "%PUMP_RETRACT_COMMAND%"=="" set "PUMP_RETRACT_COMMAND=a"
if "%PUMP_STOP_COMMAND%"=="" set "PUMP_STOP_COMMAND=c"
if "%METADATA_JPEG%"=="" set "METADATA_JPEG=data\fixtures\mini2\IR_00001.jpeg"
if "%DLL_DIR%"=="" set "DLL_DIR=vendor\hikmicro_analyzer"

echo Running Windows-native Mini2 + visible-camera live collector...
echo   Mini2: index=%MINI2_INDEX% backend=%MINI2_BACKEND% 256x344 YUY2 @25fps
echo   Mini2 missing behavior: allow_visible_only=%ALLOW_MINI2_MISSING%
echo   Mini2 reconnect: retry_interval=%MINI2_RETRY_INTERVAL_S%s
echo   Visible: index=%VISIBLE_INDEX% backend=%VISIBLE_BACKEND% %VISIBLE_WIDTH%x%VISIBLE_HEIGHT%
echo   Thermal ROI: %THERMAL_ROI%
echo   Thermal processing: %THERMAL_PROCESSING%
echo   Thermal rotation: %THERMAL_ROTATION_DEGREES% degrees
echo   Visible ROI: %VISIBLE_ROI%
echo   Output: %OUTPUT%
echo   MJPEG/SSE stream: http://%LIVE_STREAM_HOST%:%LIVE_STREAM_PORT%/
echo   ROI setup/lock: click=%ROI_CLICK_ENABLED% link=%ROI_LINK_MODE% continuous_auto=%ROI_AUTO_DETECT%
echo   Visible ROI detector: %VISIBLE_ROI_DETECTOR% model=%YOLO_MODEL%
echo   Auto ROI worker: %AUTO_ROI_WORKER% every=%ROI_AUTO_EVERY% max_age=%AUTO_ROI_RESULT_MAX_AGE_MS%ms
echo   YOLO throttle: min=%YOLO_MIN_INTERVAL_MS%ms success=%YOLO_SUCCESS_INTERVAL_MS%ms imgsz=%YOLO_INPUT_SIZE%
echo   Legacy file preview every rows: %PREVIEW_EVERY%
echo   Stream every rows: %STREAM_EVERY%
echo   Max sync offset warning: %MAX_SYNC_OFFSET_MS% ms
echo   Pump serial: port=%PUMP_SERIAL_PORT% baud=%PUMP_SERIAL_BAUD% retry=%PUMP_SERIAL_RETRY_INTERVAL_S%s start=%PUMP_START_COMMAND% retract=%PUMP_RETRACT_COMMAND% stop=%PUMP_STOP_COMMAND%
echo.

if /I "%VISIBLE_ROI_DETECTOR%"=="yolo" if not "%AUTO_INSTALL_YOLO%"=="0" (
  echo Checking optional YOLO dependency...
  %PYTHON_CMD% %PYTHON_ARGS% -c "import ultralytics" >nul 2>nul
  if errorlevel 1 (
    echo Installing optional YOLO dependency: ultralytics
    %PYTHON_CMD% %PYTHON_ARGS% -m pip install -r requirements-yolo.txt
    if errorlevel 1 (
      echo YOLO install failed. Install requirements-yolo.txt, then run again.
      pause
      exit /b 1
    )
  )
)

%PYTHON_CMD% %PYTHON_ARGS% tools\windows_live_collect.py ^
  --frames %FRAMES% ^
  --mini2-index %MINI2_INDEX% ^
  --mini2-backend %MINI2_BACKEND% ^
  --allow-mini2-missing %ALLOW_MINI2_MISSING% ^
  --mini2-retry-interval-s %MINI2_RETRY_INTERVAL_S% ^
  --visible-index %VISIBLE_INDEX% ^
  --visible-backend %VISIBLE_BACKEND% ^
  --visible-width %VISIBLE_WIDTH% ^
  --visible-height %VISIBLE_HEIGHT% ^
  --thermal-roi %THERMAL_ROI% ^
  --thermal-processing %THERMAL_PROCESSING% ^
  --thermal-rotation-degrees %THERMAL_ROTATION_DEGREES% ^
  --visible-roi %VISIBLE_ROI% ^
  --metadata-jpeg "%METADATA_JPEG%" ^
  --dll-dir "%DLL_DIR%" ^
  --output "%OUTPUT%" ^
  --stream-every %STREAM_EVERY% ^
  --preview-dir "%PREVIEW_DIR%" ^
  --preview-every %PREVIEW_EVERY% ^
  --live-stream-host %LIVE_STREAM_HOST% ^
  --live-stream-port %LIVE_STREAM_PORT% ^
  --live-stream-jpeg-quality %LIVE_STREAM_JPEG_QUALITY% ^
  --roi-click-enabled %ROI_CLICK_ENABLED% ^
  --roi-link-mode %ROI_LINK_MODE% ^
  --roi-auto-detect %ROI_AUTO_DETECT% ^
  --visible-roi-detector %VISIBLE_ROI_DETECTOR% ^
  --yolo-model "%YOLO_MODEL%" ^
  --yolo-classes "%YOLO_CLASSES%" ^
  --yolo-min-confidence %YOLO_MIN_CONFIDENCE% ^
  --yolo-max-area-fraction %YOLO_MAX_AREA_FRACTION% ^
  --yolo-min-interval-ms %YOLO_MIN_INTERVAL_MS% ^
  --yolo-success-interval-ms %YOLO_SUCCESS_INTERVAL_MS% ^
  --yolo-input-size %YOLO_INPUT_SIZE% ^
  --roi-auto-min-confidence %ROI_AUTO_MIN_CONFIDENCE% ^
  --roi-auto-every %ROI_AUTO_EVERY% ^
  --auto-roi-worker %AUTO_ROI_WORKER% ^
  --auto-roi-result-max-age-ms %AUTO_ROI_RESULT_MAX_AGE_MS% ^
  --max-sync-offset-ms %MAX_SYNC_OFFSET_MS% ^
  --visible-sync-max-age-ms %VISIBLE_SYNC_MAX_AGE_MS% ^
  --pump-serial-port "%PUMP_SERIAL_PORT%" ^
  --pump-serial-baud %PUMP_SERIAL_BAUD% ^
  --pump-serial-retry-interval-s %PUMP_SERIAL_RETRY_INTERVAL_S% ^
  --pump-start-command %PUMP_START_COMMAND% ^
  --pump-retract-command %PUMP_RETRACT_COMMAND% ^
  --pump-stop-command %PUMP_STOP_COMMAND%

pause
exit /b %errorlevel%
