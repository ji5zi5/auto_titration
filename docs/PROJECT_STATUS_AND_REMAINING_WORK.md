# 자동 적정 프로젝트 진행 현황 및 남은 수정점

작성 기준: 2026-07-13
목적: Windows 쪽 Codex 또는 다른 개발자가 이 repo를 바로 이어받아, 현재까지 구현된 내용과 앞으로 수정해야 할 일을 헷갈리지 않도록 정리한다.
범위: Windows 수집 앱, Mini2 열화상 처리, Arduino 시린지 펌프, 화학 계산, 머신러닝, Android 포팅, 문서/포스터 작업을 모두 포함한다.

## 1. 프로젝트 목표 요약

이 프로젝트는 고등학교 과학전람회/발명품 프로젝트로, 산·염기 중화적정에서 사람이 뷰렛 콕을 직접 조절하고 지시약 색 변화를 눈으로 판단할 때 생기는 인적 오류를 줄이기 위한 자동 적정 보조 시스템이다.

핵심 아이디어는 다음과 같다.

- 뷰렛 대신 Arduino 기반 시린지 펌프가 적정액을 일정한 속도로 밀어 넣는다.
- 일반 카메라는 지시약 색 변화를 RGB/HSV 값으로 기록한다.
- HIKMICRO Mini2 V2 열화상 카메라는 용액 영역의 온도 변화를 기록한다.
- 펌프 작동 시간과 보정 유량으로 현재 주입량을 계산한다.
- 모든 값을 같은 실험 CSV에 저장한다.
- 녹화 종료 후 머신러닝 모델이 당량점에 가까운 주입 부피를 예측한다.
- 예측 당량점 부피를 이용해 미지 시료 농도, 예측 pH, 이론 pH 곡선 해석으로 이어지게 한다.

중요한 범위는 다음과 같다.

- 완전 자동 적정기가 아니라 자동 적정 보조장치다.
- 모델이 당량점이라고 판단해도 펌프를 자동 정지하지 않는다.
- 현재 안전 설계는 사람이 녹화 시작/종료와 펌프 정지를 최종 판단하는 방식이다.
- 과장하면 안 되는 부분은 Android 단독 Mini2 섭씨 변환과 머신러닝 성능이다. Windows 쪽 공식 DLL 기반 온도 변환과 개발셋 머신러닝 결과는 구분해야 한다.

## 2. 현재 repo와 실행 상태

### 2.1 저장소

- GitHub repo: `https://github.com/ji5zi5/auto_titration`
- Windows 실행본 release: `v0.1.3 Windows 실행본`
- release URL: `https://github.com/ji5zi5/auto_titration/releases/tag/v0.1.3`

### 2.2 사용자가 실제로 실행하는 Windows 경로

Windows에는 프로젝트 폴더를 하나만 둔다.

```text
C:\Users\Jio\Downloads\auto_titration
```

WSL에서는 다음 경로로 접근한다.

```text
/mnt/c/Users/Jio/Downloads/auto_titration
```

예전에 쓰던 `auto_titration_20260513-170048`, `auto_titration_windows` 같은 중복 폴더는 삭제 대상이다. 새 Codex가 작업할 때도 복사본을 새로 만들지 말고 위 폴더 하나만 사용한다.

### 2.3 일반 실행법

일반 사용자는 Windows에서 아래 파일을 더블클릭한다.

```text
launchers\windows\21_open_dashboard_server.bat
```

이 BAT가 하는 일은 다음과 같다.

- Python 실행기 탐색
- requirements 설치 확인
- YOLO 사용 시 requirements-yolo 설치 확인
- 기존 collector/server 프로세스 정리
- 대시보드 서버 실행
- live collector 실행
- 웹 UI 열기
- 같은 Wi-Fi에서 폰으로 접속할 수 있는 LAN 주소 출력

수집기만 따로 확인할 때는 다음을 실행한다.

```text
launchers\windows\20_windows_live_collect.bat
```

### 2.4 현재 실사용 기준

현재 실험 수집의 본경로는 Windows 노트북 앱이다. Android 앱은 상당히 많은 파일과 native library, bridge 코드가 있지만 아직 Windows와 같은 수준의 완전한 실사용 본경로라고 보면 안 된다. Android는 이어서 수정해야 할 대상이다.

## 3. 지금까지 구현한 것

## 3.1 Windows 대시보드와 live collector

구현된 핵심 파일은 다음과 같다.

```text
tools/dashboard_server.py
tools/windows_live_collect.py
website/index.html
website/app.js
website/style.css
```

구현된 기능은 다음과 같다.

- 브라우저 기반 실험 UI 제공
- 일반 카메라 프레임 표시
- Mini2 열화상 프레임 표시
- 카메라 ROI 설정
- 열화상 ROI 설정
- 녹화 시작/종료
- CSV 저장
- Arduino 펌프 명령 전송
- 실험 조건 입력
- 현재 주입량 표시
- 당량점 차이 표시
- RGB/HSV 변화 표시
- ROI 온도 변화 표시
- IUPAC 상수 기반 pKa/pKb 선택
- 지시약 변색 범위 기록
- pH 계산 및 예측 pH 표시 흐름
- 녹화 종료 후 머신러닝 예측값을 CSV와 UI에 반영

현재 구조상 `dashboard_server.py`는 웹 화면을 띄우고, 실제 카메라/펌프/CSV 처리는 `windows_live_collect.py`가 담당한다. 웹 UI는 collector API를 통해 최신 프레임과 상태를 받아온다.

## 3.2 Mini2 열화상 처리

구현된 핵심 파일은 다음과 같다.

```text
auto_titrator/mini2_live.py
auto_titrator/official_hikmicro.py
vendor/hikmicro_analyzer/
tools/windows_live_collect.py
```

지금까지 확인한 Mini2 관련 사실은 다음과 같다.

- Mini2 V2는 UVC 장치로 raw frame을 제공한다.
- raw frame에서 `256x344` 형태가 잡힌다.
- 위쪽 `256x192` 영역이 thermal raw matrix로 쓰인다.
- Windows에서는 HIKMICRO 공식 Analyzer DLL을 이용해 raw frame을 처리한다.
- 공식 처리 결과의 int32 온도값은 다음 식으로 섭씨 변환한다.

```text
temperature_c = point_i32_at_0x10 / 64.0
```

중요한 구분은 다음과 같다.

- `/64`는 공식 DLL 또는 공식 처리 결과가 반환한 int 값을 섭씨로 해석하는 방식이다.
- 예전에 실험했던 affine 변환식, lookup 근사식, fake color 기반 변환식은 현재 공식 주장 경로가 아니다.
- Windows 앱은 공식 DLL 경로를 사용하는 것이 핵심이다.
- Android 단독 Mini2 변환은 아직 Windows만큼 검증된 상태가 아니다.

공식 프로그램 참고 위치는 다음과 같다.

```text
C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer
C:\Users\Public\AnalyzerTool\RunAnalyzerExe
vendor/hikmicro_analyzer/
```

WSL에서는 다음 경로로 확인한다.

```text
/mnt/c/Program Files/HIKMICRO Analyzer/HIKMICRO Analyzer
/mnt/c/Users/Public/AnalyzerTool/RunAnalyzerExe
```

중요 DLL 예시는 다음과 같다.

```text
HCUSBSDK.dll
MTlib_OL.dll
FormatConversion.dll
MicroJITA_Release_x64.dll
MicroJPEG_Release_x64.dll
MicroRVP_Release_x64.dll
MicroRVR_Release_x64.dll
MicroTA_Release_x64.dll
libusb-1.0.dll
```

## 3.3 일반 카메라와 ROI

구현된 기능은 다음과 같다.

- 일반 카메라 화면 표시
- 사각형 ROI 지정
- 열화상 ROI 지정
- ROI 내부 RGB 평균 계산
- ROI 내부 HSV 평균 계산
- 색 변화량과 변화율 계산
- ROI 면적, 준비 상태, 품질 정보 기록
- YOLO 기반 후보 탐색 시도
- 자동 ROI 추적 시도
- lasso ROI 시도 후 다시 단순 사각형 ROI 중심으로 정리

현재 판단은 다음과 같다.

- 투명 비커는 YOLO가 항상 안정적으로 잡지 못한다.
- 실험에서는 자동 인식보다 시작 전 ROI를 수동으로 잡고 고정하는 방식이 더 안정적이다.
- 자동 후보는 보조 기능으로 남길 수 있지만, 최종 실험 흐름은 수동 ROI lock을 중심으로 두는 것이 좋다.
- 일반 카메라와 열화상 ROI는 같은 픽셀 좌표를 쓰면 안 된다. 두 장치의 화각과 좌표계가 다르므로 각각 따로 잡아야 한다.

## 3.4 Arduino 시린지 펌프

구현된 핵심 파일은 다음과 같다.

```text
auto_titrator/arduino_stepper/arduino_stepper.ino
auto_titrator/arduino_stepper_original_working/arduino_stepper_original_working.ino
auto_titrator/pump_controller.py
tools/windows_live_collect.py
```

현재 펌웨어는 단순 문자 명령 방식이다.

```text
a = 역방향, 시린지 당기기
b = 정방향, 적정액 밀기
c = 정지
```

핀 설정은 다음과 같다.

```text
STEP_PIN = 2
DIR_PIN = 3
ENABLE_PIN = 4
Serial = 9600 baud
```

현재 웹/collector 기본 명령은 다음과 맞춰져 있다.

```text
PUMP_START_COMMAND=b
PUMP_RETRACT_COMMAND=a
PUMP_STOP_COMMAND=c
```

실험 흐름은 다음과 같다.

- 녹화 시작 버튼을 누르면 CSV 기록이 시작되고 `b` 명령으로 펌프가 밀기 시작한다.
- 녹화 종료 버튼을 누르면 CSV 기록이 끝나고 `c` 명령으로 펌프가 멈춘다.
- 별도 후퇴 버튼은 `a` 명령을 보낸다.

펌프 유량 계산은 다음 기준으로 정리되어 있다.

- 주사기 내경: 약 35 mm
- 반지름: 17.5 mm
- 단면적: 약 962 mm2
- 스텝모터: 1.8도, 200 step/rev 기준
- 펌웨어 step 주기: HIGH 5000 us + LOW 5000 us = 약 100 step/s
- 회전 속도: 약 0.5 rev/s
- 리드스크류 이동: 2 mm/rev
- 피스톤 속도: 약 1 mm/s
- 이론 유량: 약 0.962 mL/s
- 물 주입 실측 보정: 약 0.99 mL/s 근처로 사용

실험 중 확인한 사항은 다음과 같다.

- 펌프가 수직 아래 방향으로 누를 때 내부 공기 압축과 기포 영향이 컸다.
- 방향을 바꾸고 공기를 줄이니 토출이 안정화되었다.
- 10 mL가 약 10초 전후에 나와 이론값과 크게 다르지 않았다.
- 정확한 표준화보다는 현재 프로젝트에서는 보정 유량으로 프레임별 주입량을 환산하는 것이 목적이다.

## 3.5 CSV 저장과 동기화

현재 CSV는 머신러닝 학습용 원자료다. 단순 결과표가 아니라 실험 전체를 재분석하기 위한 로그다.

저장되는 정보의 큰 묶음은 다음과 같다.

- 실험 조건
- 적정 종류
- 시료/표준용액 종류
- 농도/부피
- 지시약
- 이론 당량점
- pH 계산 관련 값
- 펌프 상태
- 경과 시간
- 현재 주입량
- 일반 카메라 RGB/HSV 특징
- 열화상 ROI 온도 특징
- 열화상 전체/ROI 통계 특징
- ROI 준비 상태와 품질
- 일반 카메라와 열화상 프레임 시간 차이
- 머신러닝 예측값
- 예측 source

동기화 방식은 PC clock을 기준으로 한다. 일반 카메라와 Mini2 프레임이 완전히 같은 순간에 들어오지는 않으므로, 두 장치 프레임 시간과 차이를 기록한다. 이 차이를 없애는 것이 아니라 기록해서 분석에서 판단할 수 있게 하는 방식이다.

과거 문제가 있었던 부분은 다음과 같다.

- 특정 실험에서 CSV 행 수가 너무 적게 저장되었다.
- 이후 후처리/보간 이야기가 나왔지만, 본질적으로는 수집기가 녹화 중 row를 안정적으로 남겨야 한다.
- 지금도 실제 실험 직전에는 행 수, FPS, CSV 열이 정상인지 반드시 짧은 물 테스트로 확인해야 한다.

## 3.6 화학 계산

구현된 핵심 파일은 다음과 같다.

```text
auto_titrator/chemistry.py
auto_titrator/chemical_constants.py
auto_titrator/indicator_models.py
data/chemistry_constants/iupac/iupac_high-confidence_v2_3.csv
```

현재 앱이 다루는 기본 물질은 다음 네 가지다.

```text
HCl
Acetic acid
NaOH
Ammonia
```

기본 적정 종류는 다음 네 가지다.

```text
strong_acid_strong_base
strong_acid_weak_base
weak_acid_strong_base
weak_acid_weak_base
```

구현된 화학 기능은 다음과 같다.

- 당량 관계식 기반 이론 당량점 계산
- 예측 당량점 부피 기반 미지 시료 농도 계산
- 표준용액 농도 역산 흐름
- 약산/약염기 pKa/pKb 적용
- IUPAC 해리상수 CSV lookup
- 지시약 변색 범위 저장
- 이론 pH 곡선 계산
- Davies 식 기반 활동도 보정 정보 반영
- 이온 세기 범위에 따른 해석 주의 표시

중요한 해석은 다음과 같다.

- 당량점 부피 계산 자체는 반응 가수와 몰수 관계가 중심이다.
- 강산/약산, 강염기/약염기 차이는 당량점 pH, pH 곡선, 지시약 적합성에 영향을 준다.
- 농도 계산 결과는 예측 당량점 부피에 직접 비례하므로, 당량점 부피 오차는 농도 오차로 이어진다.

## 3.7 머신러닝

구현된 핵심 파일은 다음과 같다.

```text
auto_titrator/typewise_live_model.py
tools/export_live_typewise_model.py
tools/train_equivalence_current_volume.py
data/labeled/typewise-current-volume-classifier.pkl
docs/ml_current_volume_no_progress.md
docs/포스터_머신러닝_모델선정.txt
docs/포스터_적정종류별_성능표.csv
```

현재 live 앱이 먼저 사용하는 모델은 다음이다.

```text
data/labeled/typewise-current-volume-classifier.pkl
```

`tools/windows_live_collect.py`에는 다음 기본값이 들어 있다.

```text
DEFAULT_LIVE_ML_MODEL = ""
DEFAULT_TYPEWISE_LIVE_ML_MODEL = ROOT / "data" / "labeled" / "typewise-current-volume-classifier.pkl"
```

즉, 과거 JSON regression 모델보다 typewise classifier pickle이 우선된다.

현재 live 예측 source는 다음으로 표시된다.

```text
predicted_equivalence_source = typewise_frame_zone_classifier
```

웹에서는 이를 다음처럼 표시한다.

```text
적정 종류별 분류 모델
```

현재 머신러닝 정리는 다음과 같다.

- 회귀만 고집하지 않고 분류 기반 접근도 실험했다.
- 최종 live용은 적정 종류별로 나누어 현재 프레임/구간이 당량점 근처인지 판단하는 분류 모델 구조다.
- 프레임별 후보를 기반으로 실험 단위 당량점 부피를 고르는 방식이다.
- 입력에는 실제 실험 중 알 수 있는 센서값과 현재 주입량을 포함할 수 있다.
- 진행률, 이론 당량점, 당량점까지의 거리, 정답 라벨 같은 누수 feature는 제거해야 한다.

현재 문서화된 개발셋 결과는 다음과 같다.

```text
12개 run 기준 개발셋
MAE 0.392472 mL
RMSE 0.685276 mL
MAPE 1.271147%
```

적정 종류별 MAPE는 다음으로 정리되어 있다.

```text
강산-강염기: 0.470296%
강산-약염기: 0.674847%
약산-강염기: 3.486481%
약산-약염기: 0.452964%
```

이 결과는 포스터에 쓸 수 있지만, 반드시 개발셋 결과라고 표현해야 한다. 독립적인 새 실험에서 검증된 최종 성능이라고 과장하면 안 된다.

## 3.8 Android 앱

Android 프로젝트 위치는 다음과 같다.

```text
mobile/android/
```

주요 파일은 다음과 같다.

```text
mobile/android/settings.gradle.kts
mobile/android/build.gradle.kts
mobile/android/app/build.gradle.kts
mobile/android/app/src/main/AndroidManifest.xml
mobile/android/README.md
```

주요 Kotlin 코드 위치는 다음과 같다.

```text
mobile/android/app/src/main/java/kr/auto/titration/mobile/
```

구현 또는 scaffold가 있는 영역은 다음과 같다.

- `MainActivity.kt`: 앱 진입점
- `AndroidBridge.kt`: WebView와 native bridge
- `MobileFeatureClient.kt`: 노트북 서버로 feature frame 전송
- `Mini2UsbProbe.kt`: USB Mini2 권한/연결 probe
- `session/PhoneRunSession.kt`: 폰 단독 session 구조
- `data/LocalCsvWriter.kt`: Android 로컬 CSV 저장
- `data/CsvFeatureRow.kt`, `data/CsvSchema.kt`: Android CSV schema
- `chemistry/EquivalenceCalculator.kt`: Android 농도/당량 계산
- `pump/BluetoothPumpTransport.kt`: Bluetooth Classic SPP 펌프 통신
- `pump/PumpCommandContract.kt`: `a`, `b`, `c` 명령 계약
- `vision/VisibleFeatureExtractor.kt`: 스마트폰 카메라 RGB/HSV feature
- `vision/YoloSegmentationDetector.kt`: YOLO segmentation ROI 후보
- `ml/LiteRtYoloSegmenter.kt`: TFLite YOLO 실행
- `thermal/HikmicroF1Mini2Stream.kt`: HIKMICRO F1/Mini2 stream 시도
- `thermal/HikmicroJnaMini2Stream.kt`: HIKMICRO JNA stream 시도
- `thermal/Mini2ValidationGate.kt`: calibrated/raw_unverified gate

Android asset은 다음과 같다.

```text
mobile/android/app/src/main/assets/models/yolo11n-seg-256-fp32.tflite
mobile/android/app/src/main/assets/models/yolo11n-seg-256-fp32.metadata.json
```

Android native library는 다음 위치에 있다.

```text
mobile/android/app/src/main/jniLibs/arm64-v8a/
```

중요 `.so`는 다음과 같다.

```text
libHCUSBSDK.so
libMTlib.so
libAnalyzeData.so
lib_thermal_module.so
libMicroJITA_Release_v8a.so
libMicroJPEG_Release_v8a.so
libusbCam_host.so
libuvc.so
libusb-1.0.so
```

공식 APK/XAPK 분석 요약은 다음 문서에 있다.

```text
docs/hikmicro_apk_androguard_summary.txt
```

공식 앱 구조를 맞추기 위한 namespace도 repo에 들어 있다.

```text
mobile/android/app/src/main/java/com/hcusbsdk/
mobile/android/app/src/main/java/com/hik/f2module/
mobile/android/app/src/main/java/com/hik/viewer/
mobile/android/app/src/main/java/com/hik/viewercommon/
```

현재 Android에 대한 정확한 판단은 다음과 같다.

- Android 파일은 많이 만들어져 있다.
- 공식 APK 분석 흔적과 `.so` 복사본도 있다.
- 하지만 Windows 본경로처럼 실제 실험에서 안정적으로 작동 검증된 상태는 아니다.
- 특히 Mini2 단독 섭씨 변환, 25fps 안정 수집, Bluetooth 펌프 연동, 로컬 CSV export, ML 모델 적용은 Windows와 같은 수준으로 검증해야 한다.

## 3.9 문서, 보고서, 포스터 자료

이미 작성된 문서가 많다. 주요 파일은 다음과 같다.

```text
docs/WINDOWS_CODEX_HANDOFF.md
docs/README_WINDOWS_CLICK_ME.txt
docs/mobile_companion_runbook.md
docs/hikmicro_apk_androguard_summary.txt
docs/ml_current_volume_no_progress.md
docs/report_laptop_app_development_draft.md
docs/science_fair_report_final_draft.md
docs/보고서.txt
docs/포스터_문장_정리.txt
docs/포스터_연구요약_앱개발_간략문장.txt
docs/포스터_windows_android앱개발_문장.txt
docs/포스터_머신러닝_모델선정.txt
docs/포스터_적정종류별_성능표.csv
docs/포스터_적정종류별_성능표.txt
docs/포스터_그래프1_데이터수집_설명.txt
docs/포스터_결론_기대효과.txt
```

포스터/보고서 문장 작업에서 정리된 방향은 다음과 같다.

- 너무 AI 문체처럼 길게 쓰지 않는다.
- 포스터 문장은 한두 문장 또는 짧은 개조식으로 쓴다.
- “구성하였다”보다 실제 만든 기능이 드러나게 쓴다.
- 중화적정에서 뷰렛 콕 조절의 불편함과 인적 오류를 동기로 둔다.
- 종말점과 당량점 차이를 명확히 설명한다.
- 카메라 모델명보다 색 변화, 온도 변화, 주입량, 농도 계산 기능을 중심으로 설명한다.
- 포스터 성능 수치는 개발셋 기준임을 숨기지 않는다.

## 4. 앞으로 수정해야 할 점 전체 목록

아래는 실제로 이어서 수정하거나 확인해야 하는 작업 목록이다.

## 4.1 P0 - Windows 실험 본경로 검증

가장 먼저 해야 한다. Android나 새 기능보다 실제 전람회 실험 데이터 수집이 우선이다.

수정/확인할 점:

1. Windows에서 `21_open_dashboard_server.bat` 실행 확인
   - 서버가 8765 포트로 뜨는지 확인
   - collector가 8766 포트로 뜨는지 확인
   - 수집기 포트 닫힘 메시지가 있으면 collector 프로세스가 죽었는지 확인

2. Arduino 재연결 흐름 확인
   - 서버를 먼저 켠 뒤 Arduino를 나중에 꽂아도 잡히는지 확인
   - Arduino IDE Serial Monitor가 열려 있으면 포트를 못 잡으므로 이 경우 UI에 명확히 표시되게 개선
   - 재시도 로그가 너무 조용하면 “펌프 검색 중” 같은 상태 표시 추가

3. 녹화 시작/펌프 시작 동시성 확인
   - 녹화 시작 시 `b` 명령이 실제로 전송되는지 확인
   - 녹화 종료 시 `c` 명령이 실제로 전송되는지 확인
   - 후퇴 버튼이 `a`를 보내는지 확인
   - 펌프가 연결 안 되어도 CSV 녹화 자체는 막히지 않게 유지

4. CSV row 수 확인
   - 10초 녹화에서 기대 row 수가 너무 적지 않은지 확인
   - 일반 카메라/열화상 FPS와 CSV row 기록 주기가 실제로 맞는지 확인
   - row 수가 적으면 ML 학습용으로 가치가 떨어지므로 먼저 고쳐야 함

5. Mini2와 일반 카메라 동시 표시 확인
   - 일반 카메라가 바로 표시되는지 확인
   - Mini2 raw frame이 바로 표시되는지 확인
   - 열화상 ROI 온도값이 `-`로 남지 않는지 확인
   - Mini2가 없을 때에도 일반 카메라와 CSV 녹화가 동작하는지 확인

6. ROI 실험 흐름 단순화
   - 자동 ROI가 불안정하면 수동 사각형 ROI를 기본값으로 둔다
   - 일반 카메라 ROI와 열화상 ROI를 따로 잡게 한다
   - 실험 직전 ROI lock 상태가 명확히 보이게 한다

## 4.2 P0 - live 머신러닝 예측 연결 확인

현재 이론값이 예측값처럼 보이면 안 된다. live 앱은 typewise classifier 결과를 우선 사용해야 한다.

수정/확인할 점:

1. 녹화 종료 후 CSV에서 다음 열 확인

```text
predicted_equivalence_volume_ml
predicted_equivalence_source
predicted_sample_concentration_M
predicted_ph
```

2. `predicted_equivalence_source`가 다음인지 확인

```text
typewise_frame_zone_classifier
```

3. 웹 UI 표시가 다음으로 나오는지 확인

```text
적정 종류별 분류 모델
```

4. 예측값이 이론 당량점과 항상 같게 고정되는지 확인
   - 항상 같으면 모델 예측이 아니라 이론값 fallback일 가능성이 크다.
   - `data/labeled/typewise-current-volume-classifier.pkl` 로드 실패 여부를 확인한다.

5. 농도 계산창의 기준 정리
   - 미지 시료 농도 입력값은 정답 계산에 쓰면 안 된다.
   - 예측 당량점 부피로 농도를 역산해야 한다.
   - 웹 UI 문구는 “예측 pH”처럼 표시한다.

6. 성능 표현 수정
   - `MAPE 1.27%`는 개발셋 12개 run 기준이다.
   - 새 독립 실험 성능으로 표현하지 않는다.
   - 포스터에는 “개발셋 기준” 또는 “수집 데이터 기준”으로 표현한다.

## 4.3 P0 - Android 앱 수정점

사용자가 Windows 환경에서 이어서 작업하려는 핵심 중 하나다. Android는 “완성본”이 아니라 “수정해야 할 대상”이다. 현재 Android 계획의 1순위는 앱 UI나 CSV가 아니라 공식 HIKMICRO 앱의 Mini2 호출 경로를 찾아 우리 앱에서 최소 재현하는 것이다.

P0 수정 목표:

```text
공식앱이 Mini2를 여는 정확한 순서를 찾는다.
그 순서를 우리 Android 코드에서 최소 구현한다.
실제 Mini2 frame callback이 들어오는지 확인한다.
frame shape와 온도 변환을 공식 앱/Windows DLL 결과와 비교한다.
```

P0 작업 순서:

1. 공식 앱/APK/XAPK 분석부터 다시 한다.
   - `docs/hikmicro_apk_androguard_summary.txt`를 읽는다.
   - JADX, apktool, androguard로 Mini2 관련 class와 method를 다시 찾는다.
   - 공식 앱에서 USB 권한, 장치 enum, register/login, stream start가 어디서 호출되는지 call path를 뽑는다.

2. native `.so` 호출 관계를 확인한다.
   - `libHCUSBSDK.so`
   - `libMTlib.so`
   - `lib_thermal_module.so`
   - `libusbCam_host.so`
   - `libuvc.so`
   - Ghidra/IDA로 export symbol, string, error code, callback 관련 이름을 확인한다.

3. 공식 앱의 실제 실행 흐름을 추적한다.
   - 가능하면 logcat으로 공식 앱 실행 로그를 본다.
   - 가능하면 Frida 같은 동적 추적으로 USB/stream/native 함수 호출 순서를 확인한다.
   - 목표는 앱 전체 복붙이 아니라 Mini2를 여는 최소 call sequence를 얻는 것이다.

4. 우리 Android 코드와 비교한다.
   - `Mini2UsbProbe.kt`
   - `thermal/HikmicroF1Mini2Stream.kt`
   - `thermal/HikmicroJnaMini2Stream.kt`
   - `thermal/HikmicroNativeBackend.kt`
   - `com/hcusbsdk/`
   - `com/hik/f2module/`
   - 공식 앱과 다르게 호출하는 부분을 찾는다.

5. 최소 Mini2 stream 경로만 먼저 구현한다.
   - USB 권한 요청
   - SDK 초기화
   - device enum 또는 register/login
   - F2/Mini2 module type 설정
   - stream parameter 설정
   - `USB_StartStreamCallback` 또는 같은 역할의 함수 호출
   - frame callback 수신

6. frame evidence를 먼저 저장한다.
   - width, height, type, sequence
   - raw byte size
   - fps
   - error code
   - callback count
   - 공식 앱 또는 Windows와 shape 비교

7. 온도 변환은 frame 수신 이후에 한다.
   - 공식 처리 함수가 int temperature matrix를 주는지 확인한다.
   - Windows 공식 DLL의 `/64` 결과와 비교한다.
   - 검증 전에는 `thermal_calibrated=false` 또는 `raw_unverified`로 둔다.

P0에서 후순위로 미룰 것:

- Android 화면 예쁘게 만들기
- YOLO ROI 개선
- CSV export 확장
- Bluetooth 펌프 연결
- Android ML 적용
- WebView UI 세부 정리

이 후순위 작업들은 Mini2 공식 호출 경로가 잡힌 뒤에 진행한다.

## 4.4 P0 - Mini2 Android 공식앱 역분석 계속

공식 앱/APK 분석을 이어가야 할 때 참고할 자료는 다음이다.

```text
docs/hikmicro_apk_androguard_summary.txt
mobile/android/app/src/main/java/com/hcusbsdk/
mobile/android/app/src/main/java/com/hik/f2module/
mobile/android/app/src/main/java/com/hik/viewer/
mobile/android/app/src/main/java/com/hik/viewercommon/
mobile/android/app/src/main/jniLibs/arm64-v8a/
```

수정할 점:

1. 공식 앱의 USB stream callback 호출 순서를 정리한다.
2. 우리 Kotlin/JNI bridge가 그 순서와 얼마나 다른지 비교한다.
3. `USB_StartStreamCallback` 또는 유사 callback에서 frame을 받는지 확인한다.
4. frame metadata에 width, height, type, sequence가 들어오는지 확인한다.
5. Windows의 `256x344` raw frame과 Android frame shape가 일치하는지 확인한다.
6. 온도 행렬을 얻는 공식 함수가 있는지 찾는다.
7. 공식 앱 화면의 min/max 온도와 우리 계산 min/max를 비교한다.

완료 기준:

- Android에서도 실제 Mini2를 꽂았을 때 25fps 근처 frame이 들어온다.
- raw frame shape가 문서화된다.
- 섭씨 변환이 공식 앱 또는 Windows DLL 결과와 비교 검증된다.
- 검증 실패 시 원인을 문서화하고 Android는 raw_unverified로 남긴다.

## 4.5 P1 - 실험 전 체크리스트 추가

실제 전람회 실험 전에는 다음을 한 화면 또는 README에 넣는 것이 좋다.

수정할 점:

1. 카메라 고정
2. Mini2 고정
3. 조명 고정
4. 비커 위치 고정
5. 일반 카메라 ROI lock
6. 열화상 ROI lock
7. 펌프 공기 제거
8. 10초 물 토출로 유량 확인
9. Arduino 포트 연결 확인
10. CSV row 수 확인
11. 예측 source 확인
12. 파일 저장 위치 확인

이 체크리스트는 사용자가 당일 급하게 실험할 때 매우 중요하다.

## 4.6 P1 - CSV 품질 진단 기능

CSV가 저장되더라도 row 수가 부족하거나 센서값이 비어 있으면 머신러닝에 쓰기 어렵다. 따라서 녹화 종료 후 자동 진단을 추가하는 것이 좋다.

수정할 점:

1. row 수 표시
2. duration 표시
3. 평균 FPS 표시
4. 일반 카메라 frame 누락률 표시
5. 열화상 frame 누락률 표시
6. ROI 준비 안 된 row 비율 표시
7. thermal 값이 `-`인 row 비율 표시
8. predicted source 표시
9. CSV 저장 경로 표시
10. “이 파일은 학습용으로 충분/부족” 간단 판정 표시

## 4.7 P1 - 머신러닝 검증 보강

현재 모델 결과가 좋아졌지만, 데이터가 12개 run으로 매우 적다. 따라서 다음을 추가해야 한다.

수정할 점:

1. 새 실험 CSV 1개 이상으로 blind 검증
2. 같은 조건 반복 실험으로 재현성 확인
3. 모델이 이론값을 베끼지 않는지 feature leakage 재검사
4. 적정 종류별 모델이 올바르게 선택되는지 확인
5. 약산-강염기에서 오차가 큰 원인 재분석
6. 포스터 수치와 실제 모델 artifact가 같은 결과에서 나온 것인지 확인
7. 모델 artifact 재생성 절차 문서화

현재 문서상 누수로 보면 안 되는 값:

- 현재 주입량
- 펌프 작동 시간
- 센서값
- 물질 종류
- 표준용액 정보

현재 넣으면 안 되는 값:

- 이론 당량점 부피
- 당량점까지 남은 거리
- 정답 zone label
- 최종 총 주입량
- 전체 진행률
- run duration을 알 때만 계산되는 progress fraction
- row index 기반으로 정답 위치를 추측할 수 있는 값

## 4.8 P1 - 농도 계산 UI 정리

최근 사용자가 지적한 부분이다. 농도 계산창이 이론값을 그대로 보여주면 안 되고, 예측값 기반 계산인지 분명해야 한다.

수정할 점:

1. “이론 pH”와 “예측 pH”를 구분한다.
2. 사용자가 입력한 미지 농도는 모델 예측 농도 계산의 정답처럼 쓰지 않는다.
3. 예측 당량점 부피로 미지 농도를 역산한다.
4. 표준용액 농도, 시료 부피, 반응 가수, 예측 당량점 부피가 계산에 쓰인다는 것을 UI에 짧게 표시한다.
5. 계산 실패 시 `-`만 띄우지 말고 이유를 표시한다.
   - 예: 예측값 없음
   - 예: 농도/부피 입력 부족
   - 예: 모델 로드 실패

## 4.9 P1 - Windows release ZIP 정리

GitHub에 EXE 하나만 올리면 전체가 동작하는 구조가 아니다. 현재는 ZIP 안의 파일들이 같이 있어야 한다.

수정할 점:

1. release ZIP에 다음이 포함되는지 확인
   - `AutoTitration.exe`
   - `launchers/windows/21_open_dashboard_server.bat`
   - `tools/`
   - `auto_titrator/`
   - `website/`
   - `vendor/hikmicro_analyzer/`
   - `data/labeled/typewise-current-volume-classifier.pkl`
   - `requirements.txt`
   - `requirements-yolo.txt`
2. 새로 수정하면 `v0.1.4` 같은 버전으로 release 후보 생성
3. README에 “ZIP 압축을 풀고 BAT 또는 EXE 실행”이라고 명확히 적기
4. DLL 라이선스/배포 가능성은 공개 release 전에 확인

## 4.10 P2 - 문서 정리

문서가 많아졌으므로 안내 문서를 계층화할 필요가 있다.

수정할 점:

1. 사용자가 보는 문서
   - `README.md`
   - `docs/README_WINDOWS_CLICK_ME.txt`
2. 개발자가 보는 문서
   - `docs/WINDOWS_CODEX_HANDOFF.md`
   - `docs/PROJECT_STATUS_AND_REMAINING_WORK.md`
3. 포스터/보고서 문서
   - `docs/포스터_*.txt`
   - `docs/science_fair_report_*.md`
4. 연구 기록 문서
   - `docs/ml_*.md`
   - `docs/hikmicro_apk_androguard_summary.txt`
5. 오래된 가설/실패 파일은 지우기보다 archive 또는 “not current” 표시

## 4.11 P2 - 불필요 파일/캐시 정리

이미 일부 정리를 했지만, 용량 문제가 다시 생기면 다음을 우선 확인한다.

수정할 점:

1. pip cache
2. `__pycache__`
3. 오래된 raw probe dump
4. 중복 ZIP
5. 오래된 dist build
6. 실패한 Mini2 연구 dump 중 현재 재현에 필요 없는 파일

삭제 제외 대상은 “현재 실험 CSV, 공식 DLL, Android native libs, 모델 pkl”이다. 삭제 전에는 문서에서 현재 쓰는 파일인지 확인한다.

## 5. Windows에서 다음 Codex가 바로 할 작업 순서

추천 순서는 다음이다.

1. GitHub repo clone 또는 기존 폴더 pull
2. `docs/WINDOWS_CODEX_HANDOFF.md` 읽기
3. 이 문서 읽기
4. Windows에서 `21_open_dashboard_server.bat` 실행
5. Arduino 없이도 웹/카메라/CSV가 되는지 확인
6. Arduino를 꽂고 재연결 상태 확인
7. Mini2를 꽂고 열화상 frame 확인
8. 10초 물 테스트로 CSV row 수와 주입량 확인
9. 녹화 종료 후 typewise model 예측 source 확인
10. 문제가 없으면 release ZIP 재생성
11. Android Studio에서 `mobile/android` build 시작
12. Android 카메라 preview부터 고침
13. Android Mini2 USB permission/stream 확인
14. Android CSV schema를 Windows와 맞춤
15. Bluetooth 펌프 연결 확인

## 6. Android 담당 Codex가 반드시 먼저 읽을 파일

Android를 이어서 만들 Codex는 아래 순서로 읽으면 된다.

```text
docs/PROJECT_STATUS_AND_REMAINING_WORK.md
docs/WINDOWS_CODEX_HANDOFF.md
docs/mobile_companion_runbook.md
docs/hikmicro_apk_androguard_summary.txt
mobile/android/README.md
mobile/android/app/src/main/AndroidManifest.xml
mobile/android/app/build.gradle.kts
mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/AndroidBridge.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/Mini2ValidationGate.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroF1Mini2Stream.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/pump/BluetoothPumpTransport.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/data/CsvSchema.kt
```

## 7. 현재 가장 중요한 수정점 10개

1. Windows에서 실제 실험 10초 테스트로 CSV row 수와 예측 source 확인
2. Arduino를 나중에 꽂아도 collector가 자동 재연결하는지 확인
3. 펌프 미연결 상태에서도 녹화가 막히지 않게 유지
4. 농도 계산창이 이론값이 아니라 예측 당량점 기반 계산을 표시하는지 확인
5. 예측 pH가 `-`로만 뜨는 원인 수정
6. Android Studio에서 mobile/android build 성공시키기
7. Android 카메라 preview와 ROI 좌표 오류 수정
8. Android Mini2 USB 권한과 native stream 실제 연결 확인
9. Android Mini2 섭씨 변환은 공식 `.so` 경로로만 검증
10. 포스터/보고서에서 머신러닝 성능을 개발셋 기준으로 표현

## 8. 현재 주장해도 되는 것과 아직 주장하면 안 되는 것

주장해도 되는 것:

- Windows 앱에서 일반 카메라, Mini2, 펌프, CSV, 화학 계산, ML 예측을 통합하려는 구조를 구현했다.
- Windows Mini2 온도는 공식 DLL 처리 결과를 `/64`로 해석하는 경로를 사용한다.
- Arduino 시린지 펌프는 `a`, `b`, `c` 명령으로 후퇴, 주입, 정지한다.
- 물 주입 실험에서 약 1 mL/s 수준의 보정 유량을 사용했다.
- 수집 데이터 기준 머신러닝 개발셋 MAPE는 약 1.27%로 정리되어 있다.
- 약산-강염기 조건이 상대적으로 어려운 조건으로 나타났다.

아직 조심해야 하는 것:

- Android 단독 Mini2 섭씨 변환이 Windows처럼 완전히 검증되었다고 말하면 안 된다.
- 머신러닝 MAPE 1.27%를 모든 새 실험에서 보장되는 성능처럼 말하면 안 된다.
- EXE 하나만 있으면 모든 PC에서 동작한다고 말하면 안 된다. ZIP 내부 파일과 DLL이 필요하다.
- 자동으로 펌프가 당량점에서 멈춘다고 말하면 안 된다. 현재 설계는 자동 정지가 아니다.
- 이론 당량점이 실제 실험의 참값이라고 단정하면 안 된다. 용액 조제 오차가 있을 수 있다.

## 9. 마지막 정리

현재 프로젝트는 Windows 노트북 기준으로는 전람회 시연과 데이터 수집이 가능한 수준까지 많이 진행되어 있다. 핵심은 Windows 앱에서 카메라 색 변화, Mini2 열화상 온도, 펌프 주입량, 화학 계산, 머신러닝 예측을 하나의 CSV와 UI로 묶은 것이다.

앞으로의 핵심 수정 방향은 두 가지다.

첫째, Windows 본경로를 실제 실험에서 더 안정적으로 만드는 것이다. 특히 CSV row 수, Arduino 재연결, 예측 source, 농도 계산 UI, Mini2 표시를 확인해야 한다.

둘째, Android 앱을 Windows 기능과 맞게 실사용 가능하게 만드는 것이다. Android에는 이미 코드와 공식 앱 분석 자료, native library가 들어 있지만, 빌드와 실제 USB Mini2 stream, Bluetooth 펌프, CSV 저장, ML 적용을 다시 검증해야 한다.

따라서 다음 개발자는 새 기능을 크게 추가하기보다, 먼저 “현재 구현된 기능이 실제 실험에서 끝까지 끊기지 않고 기록되는가”를 검증하고, 그 다음 Android 단독/companion 기능을 완성하는 순서로 가야 한다.
