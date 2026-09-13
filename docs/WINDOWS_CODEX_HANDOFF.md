# Windows Codex 인수인계 문서

작성 기준: 2026-07-14
대상: 이 프로젝트를 처음 보는 Windows 쪽 Codex 또는 새 개발자
목적: 프로젝트가 무엇인지, 어떤 파일을 실행해야 하는지, 어디를 수정해야 하는지 한 번에 이해하게 하는 문서

더 긴 전체 현황은 `docs/PROJECT_STATUS_AND_REMAINING_WORK.md`에 있다. 이 문서는 먼저 읽는 빠른 인수인계 문서다.
25 fps 수집 구조와 검증 수치는 `docs/LIVE_PERFORMANCE_VALIDATION.md`에 정리되어 있다.
자동정지 구조와 재생 검증은 `docs/AUTO_STOP_VALIDATION.md`에 정리되어 있다.

### 2026-07-14 자동정지 추가

Windows 웹 앱에는 기본 OFF인 지속 색 변화 자동정지가 추가되었다. 구현은 `auto_titrator/auto_stop.py`, 서버 연결은 `tools/windows_live_collect.py`, UI는 `website/index.html`과 `website/app.js`에 있다. 일반 카메라 ROI의 초기색을 1초간 보정하고, 실시간 구간 분류기 점수와 실제 색 변화가 함께 확인된 뒤 색 변화가 0.4초 유지되면 펌프에 `c`를 보낸다. 감지·정지 시점과 명령 결과는 CSV에 남으며 이론 당량점은 정지 조건으로 사용하지 않는다.

## 0. 가장 먼저 알아야 할 결론

이 프로젝트는 고등학교 과학전람회용 `스마트 자동 적정 보조장치`다.

중화적정에서 사람이 뷰렛 콕을 계속 조절하고, 지시약 색 변화만 보고 종말점을 판단하면 오차가 생긴다. 이 프로젝트는 그 과정을 데이터로 기록하고, 머신러닝으로 당량점에 가까운 주입 부피를 예측해서 미지 용액 농도를 계산하려는 시스템이다.

현재 실사용 중심은 Windows 노트북 앱이다.

- Arduino 시린지 펌프가 적정액을 밀어 넣는다.
- 일반 카메라가 지시약 색 변화를 기록한다.
- HIKMICRO Mini2 V2 열화상 카메라가 용액 온도 변화를 기록한다.
- Windows 웹 대시보드가 카메라, 열화상, 펌프, 실험 조건, CSV 저장을 한 화면에서 다룬다.
- 녹화 종료 후 live 머신러닝 모델이 예측 당량점 부피를 계산한다.
- 예측 당량점 부피로 농도와 예측 pH를 계산한다.

자동정지는 선택 기능이며 기본값은 꺼짐이다. 체크하지 않으면 펌프 시작과 정지는 사람이 버튼으로 수행한다. 체크하면 지속 색 변화가 확인될 때 앱이 정지 명령을 보내지만, 실제 습식 정지 정확도와 PC 장애 시 안전성은 아직 별도 검증 대상이다.

## 1. 현재 작업 폴더

Windows에는 프로젝트 폴더를 하나만 둔다.

```text
C:\Users\Jio\Downloads\auto_titration
```

WSL 원본 repo는 다음이다.

```text
/home/jio/code/auto_titration
```

둘 다 git repo다. Windows 쪽에서 작업할 때는 `C:\Users\Jio\Downloads\auto_titration`만 사용한다. 새 폴더를 또 만들지 않는다.

WSL에서 Windows 폴더를 볼 때는 다음 경로다.

```text
/mnt/c/Users/Jio/Downloads/auto_titration
```

현재 GitHub repo는 다음이다.

```text
https://github.com/ji5zi5/auto_titration
```

최신 commit은 아래 명령으로 확인한다. 이 문서 자체도 repo에 포함되어 있으므로, 작업 전에는 `git pull` 후 최신 상태를 기준으로 본다.

```bash
git log --oneline -1
```

## 2. 처음 실행할 때 할 일

Windows에서 아래 파일을 더블클릭한다.

```text
C:\Users\Jio\Downloads\auto_titration\launchers\windows\21_open_dashboard_server.bat
```

이 파일이 하는 일은 다음과 같다.

- Python 실행기를 찾는다.
- 필요한 Python 패키지를 설치하거나 확인한다.
- 이전에 떠 있던 dashboard/collector 프로세스를 정리한다.
- 웹 대시보드 서버를 연다.
- 실시간 수집기를 실행한다.
- 브라우저에서 실험 화면을 열 수 있게 한다.

정상적으로 켜지면 보통 다음 주소가 쓰인다.

```text
대시보드: http://127.0.0.1:8765/
수집기:   http://127.0.0.1:8766/
```

같은 Wi-Fi의 휴대폰에서 노트북 대시보드에 접속하려면 BAT가 출력하는 LAN 주소를 쓴다.

```text
http://<노트북 IP>:8765
```

수집기만 따로 확인할 때는 다음 파일을 실행한다.

```text
launchers\windows\20_windows_live_collect.bat
```

## 3. 전체 작동 흐름

실험 흐름은 아래 순서로 이해하면 된다.

```text
1. 사용자가 Windows 대시보드 실행
2. 일반 카메라와 Mini2 열화상 카메라 표시
3. 일반 카메라 ROI와 열화상 ROI 지정
4. 실험 조건 입력
5. 녹화 시작 버튼 클릭
6. CSV 기록 시작 + 펌프에 b 명령 전송
7. 실험 중 색 변화, 온도 변화, 주입량 저장
8. 녹화 종료 버튼 클릭
9. CSV 기록 종료 + 펌프에 c 명령 전송
10. 머신러닝 모델이 예측 당량점 부피 계산
11. 앱이 예측 농도와 예측 pH 표시
```

핵심은 모든 데이터가 CSV로 남는다는 점이다. CSV가 제대로 저장되어야 머신러닝과 보고서 분석이 가능하다.

## 4. 하드웨어 구성

## 4.1 시린지 펌프

사용 장치:

- Arduino UNO
- A4988 스테퍼 모터 드라이버
- 스테퍼 모터
- T8 리드스크류
- anti-backlash nut
- 100 mL 주사기
- 실리콘 호스
- 외부 전원

현재 펌웨어 파일은 다음이다.

```text
auto_titrator/arduino_stepper/arduino_stepper.ino
```

백업처럼 같은 단순 펌웨어가 들어 있는 경로도 있다.

```text
auto_titrator/arduino_stepper_original_working/arduino_stepper_original_working.ino
```

현재 펌프 명령은 매우 단순하다.

```text
a = 시린지 뒤로 당기기
b = 적정액 밀기
c = 정지
```

핀 설정은 다음이다.

```text
STEP_PIN   = 2
DIR_PIN    = 3
ENABLE_PIN = 4
Serial     = 9600 baud
```

Windows collector 기본 명령도 이와 맞춰져 있다.

```text
PUMP_START_COMMAND=b
PUMP_RETRACT_COMMAND=a
PUMP_STOP_COMMAND=c
```

실험자가 녹화 시작을 누르면 `b`가 전송되고, 녹화 종료를 누르면 `c`가 전송된다. 후퇴 버튼은 `a`를 전송한다.

Arduino IDE Serial Monitor가 열려 있으면 Python이 같은 포트를 잡지 못할 수 있다. Arduino IDE에서 테스트한 뒤에는 Serial Monitor를 닫고 대시보드를 실행해야 한다.

## 4.2 펌프 유량

현재 계산 기준은 다음이다.

- 주사기 내경: 약 35 mm
- 스테퍼 모터: 200 step/rev 기준
- 리드스크류: 1회전당 약 2 mm 이동
- 펌웨어 step 주기: HIGH 5000 us + LOW 5000 us
- 이론 유량: 약 0.962 mL/s
- 물 토출 실험 보정값: 약 0.99 mL/s 근처

실험에서는 기포와 피스톤 마찰이 실제 유량에 영향을 준다. 그래서 실험 전 물로 10초 정도 토출해 유량이 크게 틀어지지 않는지 확인하는 것이 좋다.

## 4.3 일반 카메라

일반 카메라는 지시약 색 변화를 보는 장치다.

앱은 ROI 안쪽에서 다음 값을 계산한다.

- RGB 평균
- HSV 평균
- 색 변화량
- 색 변화율
- ROI 면적과 준비 상태

투명 비커는 자동 인식이 잘 안 될 수 있다. 실험에서는 수동 사각형 ROI를 잡고 고정하는 방식이 가장 안정적이다.

## 4.4 Mini2 열화상 카메라

Mini2는 HIKMICRO Mini2 V2를 기준으로 작업했다.

Windows에서는 공식 Analyzer DLL을 사용한다.

관련 파일:

```text
auto_titrator/mini2_live.py
auto_titrator/official_hikmicro.py
vendor/hikmicro_analyzer/
```

중요 DLL 예시:

```text
vendor/hikmicro_analyzer/HCUSBSDK.dll
vendor/hikmicro_analyzer/MTlib_OL.dll
vendor/hikmicro_analyzer/FormatConversion.dll
```

현재 Windows 온도 변환 주장은 다음 경로를 기준으로 한다.

```text
temperature_c = 공식 처리 결과 int 값 / 64.0
```

이 말은 “raw 픽셀을 아무렇게나 /64 하면 온도”라는 뜻이 아니다. 공식 DLL 처리 결과로 얻은 int temperature 값을 `/64`로 해석한다는 뜻이다.

Android 쪽 Mini2 섭씨 변환은 아직 Windows처럼 완전히 검증된 본경로가 아니다.


## 4.5 Mini2 온도 분석 인수인계

Mini2 온도 분석은 변환 경로와 분석 feature를 구분해서 이해해야 한다.

현재 Windows에서 인정하는 본경로는 다음이다.

```text
Mini2 UVC 256x344 raw frame
→ 위쪽 256x192 thermal raw matrix 분리
→ addline/metadata block과 함께 HIKMICRO Analyzer MTlib_OL.dll 호출
→ DLL이 point 구조체를 채움
→ point 구조체 offset +0x10의 int32 값을 읽음
→ temperature_c = point_i32_at_0x10 / 64.0
→ 256x192 섭씨 온도 행렬 생성
→ ROI 통계와 전체 행렬 통계를 CSV에 저장
```

핵심 파일:

```text
auto_titrator/official_hikmicro.py
auto_titrator/mini2_live.py
tools/mini2_mtlib_official_matrix_win.py
tools/mini2_official_mtlib_worker_win.py
vendor/hikmicro_analyzer/MTlib_OL.dll
```

중요한 점:

- `MTlib_OL.dll`이 현재 Windows 본경로의 공식 변환 DLL이다.
- `0x10`은 DLL 이름이 아니라 point 출력 구조체 안의 offset이다.
- `/64`는 raw 픽셀에 직접 적용하는 식이 아니라, `MTlib_OL.dll`이 채운 point 구조체의 int32 temperature 값을 섭씨로 바꾸는 scale이다.
- `temperature_c = point_i32_at_0x10 / 64.0`이라고 정리한다.

CSV/ML에 쓰는 온도 분석값은 단일 온도 하나가 아니다. 온도 행렬에서 ROI와 전체 행렬 통계를 뽑는다.

대표 저장/분석 feature:

```text
thermal_roi_avg
thermal_roi_min
thermal_roi_max
thermal_roi_std
thermal_roi_range
thermal_roi_iqr
thermal_roi_p05 / p25 / p50 / p75 / p95
thermal_roi_hot_fraction
thermal_roi_cold_fraction
thermal_roi_delta
thermal_matrix_avg / min / max / std / range / iqr / p05 / p25 / p50 / p75 / p95
thermal_raw_* 보조 feature
thermal_frame_rate_hz
thermal_time_s
abs_sync_offset_ms
```

실험용 변환 경로는 많이 있었지만, 현재 인수인계 기준으로는 아래처럼 분류한다.

### 현재 인정 경로

```text
MTlib_OL.dll official matrix path
```

- Windows 본경로다.
- 공식 Analyzer DLL을 호출한다.
- point offset `0x10`의 int32 값을 `/64`해서 섭씨로 쓴다.
- `auto_titrator/official_hikmicro.py`와 `tools/mini2_mtlib_official_matrix_win.py`를 기준으로 본다.

### 증거/검증용 경로

```text
same-file raw lookup
metadata_u16[284] 보정 후보식
```

관련 문서:

```text
data/mini2_internal_uncompress_probe/ir00001_raw_conversion_report.md
data/mini2_internal_uncompress_probe/ir00001_formula_analysis.md
data/mini2_multi_image_formula/multi_image_formula_report.md
data/mini2_multi_image_formula/formula_sweep/formula_sweep_report.md
```

해석:

- 같은 이미지 안에서는 raw 값과 CSV 온도가 lookup으로 0 오차 대응될 수 있었다.
- 여러 이미지 전체로 보면 같은 raw 값이 다른 온도를 가질 수 있어 전역 `T=f(raw)` 식은 반증되었다.
- `metadata_u16[284]`를 이용한 후보식은 오차가 작았지만 공식 SDK 복원은 아니므로 본경로로 쓰지 않는다.

### 폐기 또는 본경로 아님

```text
raw_u16 단순 /1024
raw_u16 단순 /8192
raw_u16 /64
전역 선형식 T = a*raw+b
min/max-only scaling
palette/fake-color RGB 분석
같은 파일 CSV lookup을 실시간 일반식처럼 쓰는 방법
```

이 경로들은 공식 온도 변환이라고 보고하면 안 된다.

### 아직 탐색용으로만 남은 경로

```text
MicroJITA_Release_x64.dll grayToTemperature 계열
MicroTA_Release_x64.dll TempAnalyzer 계열
MicroJPEG_Release_x64.dll radiometric JPEG parsing 계열
MT_SubFunction 계열
MicroPixeler / TPI 계열
```

이 스크립트들은 `tools/mini2_*_probe_win.py`에 많이 남아 있다. 일부 결과 JSON은 현재 clone에 남아 있지 않으므로, 성공/폐기 판단은 남아 있는 보고서와 현재 본경로 코드 기준으로 한다. 새로 이어받는 사람은 이 경로들을 다시 본경로처럼 주장하지 말고, 공식앱 역분석이나 Android 포팅 때 참고 자료로만 본다.

검증 프로토콜은 다음 문서를 같이 본다.

```text
docs/validation_protocol.md
```

## 5. 소프트웨어 구조

처음 보는 사람은 아래 파일부터 보면 된다.

```text
launchers/windows/21_open_dashboard_server.bat
launchers/windows/20_windows_live_collect.bat
tools/dashboard_server.py
tools/windows_live_collect.py
website/index.html
website/app.js
website/style.css
```

역할은 다음과 같다.

- `21_open_dashboard_server.bat`: 사용자가 더블클릭하는 메인 실행기
- `20_windows_live_collect.bat`: collector만 직접 실행하는 보조 실행기
- `tools/dashboard_server.py`: 웹 화면 제공, API 프록시, 파일 목록 제공
- `tools/windows_live_collect.py`: 카메라, Mini2, 펌프, CSV, ML 예측을 실제로 처리하는 핵심 수집기
- `website/index.html`: 화면 구조
- `website/app.js`: 버튼, 상태 표시, API 호출, UI 로직
- `website/style.css`: 화면 디자인

수정할 때 가장 자주 보게 되는 파일은 `tools/windows_live_collect.py`와 `website/app.js`다.

## 6. CSV가 왜 중요한가

CSV는 이 프로젝트의 핵심 결과물이다. 단순 로그가 아니라 머신러닝 학습과 보고서 분석에 쓰이는 원자료다.

CSV에는 대략 다음이 들어간다.

- 실험 조건
- 적정 종류
- 시료 물질과 표준용액 물질
- 농도, 부피, 지시약
- 현재 시간
- 현재 주입량
- 펌프 상태
- 일반 카메라 RGB/HSV 값
- 열화상 ROI 온도 값
- ROI 상태와 품질
- 동기화 관련 시간 정보
- 이론 당량점
- 머신러닝 예측 당량점
- 예측 농도
- 예측 pH
- 예측 source

실험 중 CSV row 수가 너무 적으면 나중에 머신러닝에 쓰기 어렵다. 실제 실험 전에는 10초 정도 테스트 녹화하고 row 수와 FPS가 정상인지 확인해야 한다.

## 7. 화학 계산

관련 파일:

```text
auto_titrator/chemistry.py
auto_titrator/chemical_constants.py
auto_titrator/indicator_models.py
data/chemistry_constants/iupac/iupac_high-confidence_v2_3.csv
```

현재 기본 물질은 다음 네 가지다.

```text
HCl
Acetic acid
NaOH
Ammonia
```

현재 기본 적정 종류는 다음 네 가지다.

```text
strong_acid_strong_base
strong_acid_weak_base
weak_acid_strong_base
weak_acid_weak_base
```

구현된 계산 기능은 다음과 같다.

- 당량 관계식 기반 이론 당량점 계산
- 예측 당량점 부피 기반 미지 시료 농도 계산
- 약산/약염기 pKa, pKb 적용
- IUPAC 해리상수 CSV lookup
- 지시약 변색 범위 기록
- pH 곡선 계산
- Davies 식 기반 활동도 보정 정보

중요한 구분:

- 이론 당량점은 사용자가 입력한 농도/부피로 계산한 값이다.
- 예측 당량점은 센서값과 주입량을 보고 모델이 고른 값이다.
- 농도 계산 결과는 예측 당량점 부피에 직접 영향을 받는다.

## 8. 머신러닝 상태

현재 실험 종료 후 최종 당량점 계산이 우선 사용하는 모델은 다음 파일이다.

```text
data/labeled/type-conditioned-sensor-endpoint-ranker.pkl
```

관련 코드:

```text
auto_titrator/type_conditioned_sensor_live_model.py
auto_titrator/typewise_live_model.py
tools/export_type_conditioned_sensor_live_model.py
tools/export_live_typewise_model.py
tools/validate_optimized_endpoint_research.py
tools/windows_live_collect.py
```

현재 source 이름은 다음이다.

```text
predicted_equivalence_source = type_conditioned_sensor_endpoint_ranker
```

웹 UI에서는 이를 다음처럼 표시한다.

```text
적정 종류별 시계열 모델
```

완료된 CSV의 점 추정은 12개 leave-one-run-out 모델의 예측 중앙값으로 계산한다. 고밀도 25 fps 입력은 적정 종류별 학습 부피 간격으로 두 위상 재표본화한다. 색상·열화상 중 하나가 부족하거나 신호가 평탄하면 이 모델은 예측을 보류하고 기존 `typewise-current-volume-classifier.pkl` 또는 peak 추정으로 넘어간다. 선택형 자동 정지는 사후 시계열 모델이 아니라 기존 causal classifier를 계속 사용한다.

현재 문서화된 개발셋 결과:

```text
12개 실험 run 기준
MAE  약 0.392 mL
RMSE 약 0.685 mL
MAPE 약 1.27%
```

적정 종류별 MAPE:

```text
강산-강염기:   약 0.47%
강산-약염기:   약 0.67%
약산-강염기:   약 3.49%
약산-약염기:   약 0.45%
```

이 수치는 포스터에 쓸 수 있지만, 새 실험에서 보장되는 성능이라고 쓰면 안 된다. 현재 수집된 12개 run 기준의 개발셋 결과다.

ML 입력으로 써도 되는 값:

- 현재 주입량
- 펌프 시간
- RGB/HSV 센서값
- 열화상 센서값
- ROI 품질
- 적정 종류
- 표준용액 정보

ML 입력으로 쓰면 안 되는 값:

- 이론 당량점 부피
- 당량점까지 남은 거리
- 정답 라벨
- 최종 총 주입량
- 전체 진행률
- 미지 시료 농도 정답

현재 live collector는 기존 leaky JSON 모델보다 typewise classifier pickle을 우선 사용한다. 예전 JSON 모델 파일이 남아 있어도 기본 경로가 아니다.

## 9. Android 앱 상태

Android 프로젝트는 다음 위치에 있다.

```text
mobile/android/
```

주요 파일:

```text
mobile/android/settings.gradle.kts
mobile/android/build.gradle.kts
mobile/android/app/build.gradle.kts
mobile/android/app/src/main/AndroidManifest.xml
mobile/android/README.md
```

주요 Kotlin 코드:

```text
mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/AndroidBridge.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/MobileFeatureClient.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/
mobile/android/app/src/main/java/kr/auto/titration/mobile/pump/
mobile/android/app/src/main/java/kr/auto/titration/mobile/data/
mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/
```

Android native library 위치:

```text
mobile/android/app/src/main/jniLibs/arm64-v8a/
```

공식 HIKMICRO APK 분석 요약:

```text
docs/hikmicro_apk_androguard_summary.txt
```

Android는 아직 Windows 본경로와 같은 수준으로 검증된 완성본이 아니다. 다음 작업의 1순위는 UI, CSV, YOLO, ML, Bluetooth가 아니다. 1순위는 공식 HIKMICRO 앱이 Mini2를 여는 최소 호출 경로를 역분석해서 우리 앱에서 재현하는 것이다.

Android 쪽 P0 목표:

```text
공식앱 APK/XAPK 분석
→ Mini2 관련 Java/JNA/JNI call path 추출
→ 어떤 .so 함수가 어떤 순서로 호출되는지 정리
→ 우리 Android 코드에서 최소 호출 순서 재현
→ 실제 Mini2 frame callback 수신
→ 256x344 또는 공식 frame shape 확인
→ 공식 앱/Windows 결과와 비교해 섭씨 변환 검증
```

P0에서 봐야 할 도구와 자료:

```text
JADX 또는 apktool: Java/Kotlin/decompiled call path 확인
androguard: manifest, class, method, call graph 보조 분석
Ghidra 또는 IDA: libHCUSBSDK.so, libMTlib.so, lib_thermal_module.so 등 native symbol/string 확인
logcat: 공식 앱 실행 중 로그와 에러 코드 확인
Frida 등 동적 추적: 가능하면 공식 앱의 실제 함수 호출 순서 확인
```

P0에서 찾아야 하는 최소 흐름:

```text
USB 권한 요청
→ HCUSBSDK 초기화
→ 장치 enum 또는 register/login
→ F2/Mini2 module type 설정
→ stream parameter 설정
→ USB_StartStreamCallback 또는 같은 역할의 함수 호출
→ frame callback 수신
→ thermal 처리 함수로 온도 행렬 또는 int temperature matrix 생성
→ Windows 공식 DLL 결과와 비교
```

이 단계가 끝나기 전에는 아래 작업을 후순위로 둔다.

- Android 화면 예쁘게 다듬기
- YOLO ROI 개선
- CSV export 확장
- Bluetooth 펌프 연동
- Android ML 적용

단, 공식앱 코드를 통째로 복붙하는 것이 목표는 아니다. 목표는 Mini2를 여는 데 필요한 호출 순서와 데이터 구조만 뽑아 우리 앱에서 최소 재현하는 것이다. 섭씨 변환이 검증되기 전에는 thermal 값은 `raw_unverified` 또는 `thermal_calibrated=false`로 남긴다.

Android에서 Python pickle을 직접 쓰기는 어렵다. Mini2 호출 경로가 해결된 뒤에야 ML 적용 방식을 정한다. 선택지는 다음 중 하나다.

1. Android는 수집만 하고 Windows/Python에서 예측한다.
2. 모델을 JSON/Kotlin 경량 모델로 변환한다.
3. TFLite/ONNX 등 모바일용 모델로 변환한다.

전람회 일정이 급하면 1번이 가장 안전하다.

## 10. 자주 생기는 문제와 확인 위치

## 10.1 웹은 뜨는데 카메라가 안 뜸

확인할 것:

- collector가 8766 포트에서 살아 있는지
- 브라우저 콘솔에 API 오류가 있는지
- `tools/windows_live_collect.py` 로그에 camera index 오류가 있는지
- 다른 앱이 카메라를 점유하고 있는지

## 10.2 Mini2가 안 뜸

확인할 것:

- Mini2가 Windows 장치로 보이는지
- HIKMICRO 공식 앱이나 다른 프로그램이 Mini2를 점유하고 있지 않은지
- `vendor/hikmicro_analyzer/` DLL이 있는지
- collector 로그에서 Mini2 index 탐색 실패가 있는지

## 10.3 Arduino IDE에서는 되는데 웹에서는 펌프가 안 됨

확인할 것:

- Arduino IDE Serial Monitor를 닫았는지
- 포트가 collector 실행 후에 연결되었는지
- collector가 재연결 중인지
- 웹 버튼이 `a`, `b`, `c` 중 맞는 명령을 보내는지
- `PUMP_START_COMMAND=b`, `PUMP_RETRACT_COMMAND=a`, `PUMP_STOP_COMMAND=c` 설정이 맞는지

## 10.4 농도 계산창이 이상함

확인할 것:

- `predicted_equivalence_volume_ml`이 있는지
- `predicted_equivalence_source`가 `typewise_frame_zone_classifier`인지
- 예측값 대신 이론값 fallback을 보여주는지
- 사용자가 입력한 미지 농도를 정답처럼 다시 쓰고 있지 않은지

## 10.5 CSV row 수가 적음

확인할 것:

- 녹화 상태가 실제로 시작되었는지
- collector loop가 멈추는 예외가 있는지
- 카메라 frame이 안 들어와 row 생성이 막히는지
- 펌프 미연결 때문에 녹화가 막히지 않는지
- 저장 경로 권한 문제가 있는지

## 11. 수정 작업 우선순위

가장 먼저 할 일:

1. Windows에서 `21_open_dashboard_server.bat` 실행 확인
2. 일반 카메라 표시 확인
3. Mini2 표시 확인
4. Arduino 없이도 녹화가 되는지 확인
5. Arduino 연결 후 `b`, `c`, `a` 명령 확인
6. 10초 테스트 CSV row 수 확인
7. 녹화 종료 후 `typewise_frame_zone_classifier` 예측 source 확인
8. 농도 계산창이 예측 당량점 기반으로 계산되는지 확인

그 다음 할 일:

1. 공식앱 APK/XAPK를 JADX, apktool, androguard로 다시 분석
2. Mini2 관련 Java/JNA/JNI call path를 문서화
3. `libHCUSBSDK.so`, `libMTlib.so`, `lib_thermal_module.so` 호출 순서를 찾기
4. 공식앱의 stream callback 흐름을 우리 Android 코드와 비교
5. 우리 앱에서 Mini2 최소 호출 경로만 재현
6. 실제 Mini2 frame callback이 들어오는지 확인
7. frame shape와 온도 변환을 Windows 공식 DLL 결과와 비교

나중에 할 일:

1. Android 화면/ROI/CSV 정리
2. Android Bluetooth 펌프 확인
3. Android ML 적용 방식 결정
4. 새 실험 데이터로 모델 재검증
5. release ZIP 또는 installer 정리

## 12. 수정 후 검증 방법

Python 코드나 웹 수집기를 고친 뒤에는 최소한 아래를 확인한다.

```bash
python3 -m unittest discover -v
```

가능하면 다음도 확인한다.

```bash
python3 -m py_compile tools/windows_live_collect.py tools/dashboard_server.py auto_titrator/*.py
```

Windows에서 실제 실행 확인은 다음이다.

```text
C:\Users\Jio\Downloads\auto_titration\launchers\windows\21_open_dashboard_server.bat
```

Android를 고쳤다면 다음을 확인한다.

```bash
cd mobile/android
./gradlew assembleDebug
```

Windows에서는 다음이다.

```bat
cd mobile\android
gradlew.bat assembleDebug
```

하드웨어가 있어야만 확인 가능한 항목은 테스트 결과에 `Not-tested: hardware run`처럼 남긴다.

## 13. 문서와 보고서 위치

전체 상세 현황:

```text
docs/PROJECT_STATUS_AND_REMAINING_WORK.md
```

Windows 실행 안내:

```text
docs/README_WINDOWS_CLICK_ME.txt
```

Android 참고:

```text
docs/mobile_companion_runbook.md
docs/hikmicro_apk_androguard_summary.txt
```

머신러닝 참고:

```text
docs/ml_current_volume_no_progress.md
docs/포스터_머신러닝_모델선정.txt
docs/포스터_적정종류별_성능표.csv
```

보고서/포스터 문장:

```text
docs/science_fair_report_final_draft.md
docs/보고서.txt
docs/포스터_*.txt
```

## 14. 새 Codex가 작업할 때의 안전한 순서

처음 받은 Codex는 바로 코드를 고치기보다 아래 순서로 확인한다.

1. `docs/WINDOWS_CODEX_HANDOFF.md` 읽기
2. `docs/PROJECT_STATUS_AND_REMAINING_WORK.md` 읽기
3. `git status --short` 확인
4. `launchers/windows/21_open_dashboard_server.bat` 실행 경로 확인
5. `tools/windows_live_collect.py`에서 현재 기본 모델 경로 확인
6. `website/app.js`에서 예측 source 표시 확인
7. 실제 버그 하나만 골라 수정
8. 최소 검증 실행
9. 커밋
10. Windows 단일 폴더에서 `git pull`로 동기화

Windows에 새 복사본을 만들지 않는다. 필요한 Windows 작업 폴더는 `C:\Users\Jio\Downloads\auto_titration` 하나다.

## 15. 이 문서의 핵심 한 줄

Windows 본경로는 `C:\Users\Jio\Downloads\auto_titration`에서 `21_open_dashboard_server.bat`를 실행하는 구조이고, 핵심 코드는 `tools/windows_live_collect.py`와 `website/app.js`이며, 현재 목표는 색 변화·열화상·주입량 CSV를 안정적으로 저장하고 `typewise_frame_zone_classifier` 예측으로 당량점과 농도를 계산하는 것이다.
