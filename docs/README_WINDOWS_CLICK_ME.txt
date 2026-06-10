자동 적정 프로젝트 실행 안내

지금 윈도우에서 더블클릭할 BAT는 2개만 유지합니다.

1) 전람회 시연/실사용
- launchers/windows/21_open_dashboard_server.bat
- 웹 서버와 Mini2+일반 카메라 수집기를 같이 시작합니다.
- 브라우저 주소: http://127.0.0.1:8765/
- 폰 주소: 21번 창의 LAN URL, 예: http://192.168.0.15:8765/
- 폰과 노트북은 같은 Wi-Fi에 있어야 합니다.
- 폰 접속이 안 되면 Windows Defender Firewall에서 Python 또는 8765 포트를 허용합니다.
- 웹 화면의 백엔드 주소는 보통 `현재 웹사이트 주소`로 자동 설정됩니다.
- 화면 상단에서 `CSV 수집 모드`와 `농도계산 모드`를 전환할 수 있습니다.
- CSV 수집 모드는 녹화 시작 → 녹화 종료 → CSV 다운로드로 ML 학습용 CSV를 받습니다.
- 농도계산 모드는 녹화 종료 후 마지막 예측 당량점을 자동으로 받아 미지 시료 농도와 당량점 pH를 결과 카드로 표시합니다.
- 폰 자체 카메라/Mini2로 보내는 Android companion은 별도 Android 앱입니다.
  웹 대시보드의 `Android 연결`에서 토큰을 만들고, 앱이
  mobile_feature_frame.v1 데이터를 /api/mobile/ingest로 보냅니다.
  이때도 노트북 서버가 CSV/ML 기록 주체입니다.

2) 수집기만 따로 확인
- launchers/windows/20_windows_live_collect.bat
- Mini2 UVC raw frame, 일반 카메라, ROI, 공식 DLL 온도 변환, CSV 기록을 직접 실행합니다.

실제 실험 전 순서:
- 물로 먼저 실행해서 주사기/호스 기포와 누수를 확인합니다.
- 아두이노 Serial Monitor에서 a=왼쪽, b=오른쪽, c=정지가 되는지 확인합니다.
- 물 토출량으로 ml_per_step 또는 steps_per_ml을 보정합니다.
- 21번을 실행한 뒤 일반 카메라 ROI와 Mini2 ROI를 잠그고 녹화를 시작합니다.
- CSV 다운로드 후 reference_equivalence_volume_ml은 이론값/UV-vis/기준값으로 나중에 채웁니다.
- 이 앱은 수동 상태 라벨을 쓰지 않고, 펌프를 자동 정지하지 않습니다.

Mini2 온도 경로:
- Mini2 UVC raw frame은 256x344이고, 위쪽 256x192 영역을 IR 원본 행렬로 사용합니다.
- 전람회 본 경로는 공식 HIKMICRO Analyzer/MTlib DLL worker를 사용합니다.
- 공식 DLL이 반환하는 point_i32_at_0x10 값을 /64 해서 ℃로 해석합니다.
- AFFINE_JSON/LOOKUP_CSV 같은 근사식은 과거 검증용이며 공식 온도 변환이라고 주장하지 않습니다.
- 전체 25fps matrix CSV는 기본으로 저장하지 않고 ROI/전체행렬 scalar feature만 저장합니다.

Android companion 주의:
- Android 앱은 CameraX ImageAnalysis와 Android USB host/Mini2 권한 확인 뼈대입니다.
- Android에서 Mini2 공식 변환기가 검증되기 전까지는 thermal_calibrated=false,
  raw_unverified 또는 blocked 상태만 기록합니다.
- 온도 보정이 필요한 실제 전람회 본 촬영은 현재 Windows-native collector를 우선 사용합니다.

화면이 안 뜰 때:
- 21번 실행 후 Auto Titration Collector 창이 살아 있는지 확인합니다.
- 웹 상단 백엔드 주소가 http://127.0.0.1:8766 인지 확인하고 연결을 누릅니다.
- HTTPS 웹에 배포한 경우 백엔드도 HTTPS 주소가 필요합니다.
- Mini2/카메라가 다른 앱에서 사용 중이면 닫고 다시 실행합니다.

남긴 BAT:
- launchers/windows/20_windows_live_collect.bat
- launchers/windows/21_open_dashboard_server.bat
