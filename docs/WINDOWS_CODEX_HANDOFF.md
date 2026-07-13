# Windows Codex 인수인계 문서

이 문서는 이 프로젝트를 Windows 환경의 Codex가 바로 이어받기 위한 요약이다. 2026-07-13 기준 현재 repo의 핵심 상태, 실행법, 모델 연결, 주의할 점을 정리한다.

## 1. 현재 프로젝트 한 줄 요약

고등학교 과학전람회 프로젝트로, 산·염기 중화적정에서 사람이 뷰렛 콕과 색 변화를 직접 판단할 때 생기는 오차를 줄이기 위해 만든 자동 적정 보조 시스템이다. Arduino 시린지 펌프가 적정액을 일정하게 밀고, Windows 웹 대시보드가 일반 카메라 색 변화, HIKMICRO Mini2 V2 열화상 ROI 온도, 펌프 주입량, 실험 조건을 CSV로 저장한다. 녹화 종료 후 머신러닝 모델이 당량점 부피를 예측하고, 그 부피로 미지 시료 농도와 예측 pH를 계산한다.

중요: 이 장치는 펌프를 자동 정지하지 않는다. 사람이 시작·정지하고, 앱은 수집·계산·예측 보조만 한다.

## 2. 현재 git / 배포 상태

- Repo: `https://github.com/ji5zi5/auto_titration`
- 최신 확인 commit: `b274086 Use the honest typewise model for live equivalence prediction`
- 최신 release: `v0.1.3 Windows 실행본`
- Release URL: `https://github.com/ji5zi5/auto_titration/releases/tag/v0.1.3`
- Windows 배포 ZIP은 EXE 하나로 완전 독립 실행되는 구조가 아니다. ZIP 안에 코드, DLL, 모델, requirements가 같이 들어 있고 `AutoTitration.exe`는 `launchers/windows/21_open_dashboard_server.bat`를 실행하는 런처다.

## 3. Windows에서 가장 먼저 실행할 것

일반 사용자는 아래 파일만 더블클릭하면 된다.

```bat
launchers\windows\21_open_dashboard_server.bat
```

이 BAT가 하는 일:

- Python 위치 자동 탐색: `py -3` 우선, 없으면 `python`
- 필요한 Python 패키지 자동 설치: `requirements.txt`
- YOLO 사용 시 `requirements-yolo.txt` 자동 설치
- 기존 dashboard/collector 프로세스 정리
- 대시보드 서버 실행: `http://127.0.0.1:8765/`
- Mini2 + 일반 카메라 collector 실행: `http://127.0.0.1:8766/`
- LAN URL 표시: 같은 Wi-Fi의 폰에서 `http://<laptop-ip>:8765` 접속 가능

수집기만 따로 테스트할 때는 아래 BAT를 실행한다.

```bat
launchers\windows\20_windows_live_collect.bat
```

## 4. Windows 폴더 위치

현재 작업 중인 Windows 복사본은 보통 아래 둘 중 하나다.

```text
C:\Users\Jio\Downloads\auto_titration_20260513-170048
C:\Users\Jio\Downloads\auto_titration_windows
```

WSL에서 같은 경로는 다음과 같다.

```text
/mnt/c/Users/Jio/Downloads/auto_titration_20260513-170048
/mnt/c/Users/Jio/Downloads/auto_titration_windows
```

새 Windows Codex가 작업한다면 가능하면 GitHub repo를 clone하거나, 위 폴더에서 `git pull` 가능한 상태인지 확인한다. 단, 배포 ZIP 폴더는 git repo가 아닐 수 있다.

## 5. 핵심 파일 지도

### 실행 / 웹

- `launchers/windows/21_open_dashboard_server.bat`
  - 사용자가 더블클릭하는 메인 실행 파일.
  - 서버와 collector를 같이 띄운다.
- `launchers/windows/20_windows_live_collect.bat`
  - Mini2, 일반 카메라, 펌프, CSV 수집기 직접 실행.
- `tools/dashboard_server.py`
  - 정적 웹사이트 제공 + `/api/live`, `/api/files`, collector proxy.
  - 폰에서 접속할 때 웹사이트가 collector API를 프록시로 연결하도록 함.
- `tools/windows_live_collect.py`
  - 가장 중요한 실시간 수집기.
  - Mini2 raw UVC, 일반 카메라, ROI, 공식 DLL 온도 변환, 펌프 serial, CSV 기록, 녹화 종료 시 ML 예측을 담당.
- `website/index.html`, `website/app.js`, `website/style.css`
  - 실험자가 보는 대시보드 UI.

### Mini2 / 온도

- `auto_titrator/mini2_live.py`
  - Mini2 `256x344` UVC raw frame 처리.
  - 위쪽 `256x192` 영역을 thermal raw matrix로 사용.
- `auto_titrator/official_hikmicro.py`
  - HIKMICRO Analyzer DLL 연동.
- `vendor/hikmicro_analyzer/`
  - 공식 DLL/Analyzer 관련 파일. Windows 배포에 반드시 포함되어야 함.

온도 변환 원칙:

```text
temperature_c = point_i32_at_0x10 / 64.0
```

이것은 공식 DLL이 반환한 int 값을 해석하는 경로다. 과거 affine/lookup 근사식, MT_SubFunction 조사 파일은 연구/검증용이며 현재 공식 주장 경로로 쓰면 안 된다.

### 펌프 / Arduino

- `auto_titrator/arduino_stepper/arduino_stepper.ino`
- `auto_titrator/arduino_stepper_original_working/arduino_stepper_original_working.ino`

현재 둘 다 같은 단순 펌웨어다.

명령:

```text
a = 역방향/당기기
b = 정방향/밀기
c = 정지
```

핀:

```text
STEP_PIN = 2
DIR_PIN = 3
ENABLE_PIN = 4
Serial = 9600 baud
```

웹/collector 기본 명령도 이와 맞다.

```text
PUMP_START_COMMAND=b
PUMP_RETRACT_COMMAND=a
PUMP_STOP_COMMAND=c
```

실험에서 녹화 시작은 `b`, 녹화 종료는 `c`와 연결된다. Arduino IDE Serial Monitor가 열려 있으면 Python이 포트를 못 잡을 수 있으므로 닫아야 한다. collector는 Arduino를 나중에 꽂아도 재연결을 시도한다.

### 화학 계산

- `auto_titrator/chemistry.py`
  - 당량점 부피, 당량점 pH, 활동도/Davies 관련 계산.
- `auto_titrator/chemical_constants.py`
  - IUPAC 해리상수 CSV lookup.
- `data/chemistry_constants/iupac/iupac_high-confidence_v2_3.csv`
  - pKa/pKb lookup 데이터.
- `auto_titrator/indicator_models.py`
  - 지시약 변색 범위.

기본 실험 물질:

```text
HCl, acetic acid, NaOH, ammonia
```

적정 종류:

```text
strong_acid_strong_base
strong_acid_weak_base
weak_acid_strong_base
weak_acid_weak_base
```

### ML / 예측

- `data/labeled/typewise-current-volume-classifier.pkl`
  - 현재 live 앱이 녹화 종료 후 먼저 사용하는 모델 artifact.
- `auto_titrator/typewise_live_model.py`
  - 위 pickle 모델을 로드하고 예측하는 코드.
- `tools/export_live_typewise_model.py`
  - 현재 실험 CSV/summary에서 live용 typewise classifier pickle을 다시 만드는 스크립트.
- `tools/train_equivalence_current_volume.py`
  - 진행률/이론값 누수 없이 current injected volume을 허용한 모델 평가 스크립트.
- `docs/포스터_머신러닝_모델선정.txt`
  - 포스터용 ML 설명 문장.
- `docs/포스터_적정종류별_성능표.csv`
  - 포스터용 성능표.

현재 live 기본 모델은 다음 경로다.

```text
data/labeled/typewise-current-volume-classifier.pkl
```

현재 모델 구성:

| 적정 종류 | 모델 | window | aggregate | 개발셋 MAPE |
|---|---|---:|---|---:|
| 강산-강염기 | Extra Trees leaf3 classifier | 0.3 mL | top80 | 0.470296% |
| 강산-약염기 | Extra Trees classifier | 0.5 mL | top25 | 0.674847% |
| 약산-강염기 | Random Forest classifier | 0.75 mL | top40 | 3.486481% |
| 약산-약염기 | Extra Trees classifier | 0.15 mL | weighted_median_top10 | 0.452964% |

전체 typewise 조합 성능은 문서상 MAPE 약 `1.27%`, MAE 약 `0.392 mL`다. 단, 현재 데이터 12개 실험에서 고른 development-set 결과라 외부 독립검증 성능으로 과장하면 안 된다.

중요한 최근 수정:

- `tools/windows_live_collect.py`의 `DEFAULT_LIVE_ML_MODEL`은 빈 문자열이다.
- 기존 `data/labeled/theory-equivalence-holdout-session16-model.json`은 남아 있지만 live 기본 모델이 아니다.
- `sample_concentration_M`, `theoretical_equivalence_volume_ml`, `distance_to_equivalence_ml`, `equivalence_window_label` 같은 누수 feature가 들어간 legacy JSON 모델은 자동 거부된다.
- 웹 UI는 `predicted_equivalence_source=typewise_frame_zone_classifier`를 `적정 종류별 분류 모델`로 표시한다.

## 6. 절대 헷갈리면 안 되는 점

### 6.1 이론값과 예측값 구분

이론 당량점은 입력 농도/부피로 계산한 기준값이다. 머신러닝 예측값은 센서/주입량 데이터를 바탕으로 모델이 고른 당량점 부피다. 예전에는 leaky JSON 모델이 `sample_concentration_M`로 이론 당량점을 거의 그대로 재구성해서 문제가 됐다. 지금은 그 경로를 기본에서 제거했고, 누수 feature가 있으면 거부한다.

### 6.2 주입량은 허용, 진행률은 금지

ML 입력으로 `injected_volume_ml`은 허용된다. 실제 실험 중 펌프 유량과 시간으로 알 수 있는 값이기 때문이다. 그러나 `distance_to_equivalence_ml`, `time_to_equivalence_s`, `equivalence_window_label`, `sample_concentration_M`, `theoretical_equivalence_volume_ml`은 정답/이론값을 포함하므로 예측 feature로 쓰면 안 된다.

### 6.3 Android는 본 경로가 아님

`mobile/android`는 companion scaffold다. 현재 온도 보정이 필요한 실험 본 경로는 Windows-native collector다. Android에서 Mini2 공식 ℃ 변환이 완전히 검증되기 전까지 Android thermal 값은 `thermal_calibrated=false` 또는 raw evidence로만 다룬다.

### 6.4 자동정지 금지

이 프로젝트는 자동 펌프 정지 장치가 아니라 자동 적정 보조장치다. 예측 당량점에 도달해도 펌프를 자동으로 끄지 않는다. 안전상 정지는 사람이 한다.

## 7. 실제 실험 전 체크리스트

1. 주사기/호스 기포 제거. 가능하면 주사기 토출 방향을 실험에서 확인된 안정 방향으로 둔다.
2. Arduino에 `auto_titrator/arduino_stepper/arduino_stepper.ino` 업로드.
3. Arduino IDE Serial Monitor에서 `a`, `b`, `c`가 먹는지 확인하고 Serial Monitor를 닫는다.
4. 물로 토출량 확인. 현재 보고서에는 약 `0.99 mL/s` 보정 흐름이 언급됨.
5. `21_open_dashboard_server.bat` 실행.
6. 일반 카메라와 Mini2 화면이 둘 다 뜨는지 확인.
7. 일반 카메라 ROI와 열화상 ROI를 수동 사각형으로 잡고 lock.
8. 실험 조건 입력: 적정 종류, 시료/표준용액, 농도, 부피, 지시약.
9. 녹화 시작. 펌프 `b` 명령으로 밀기 시작.
10. 녹화 종료. 펌프 `c` 명령으로 정지.
11. CSV 다운로드. `predicted_equivalence_volume_ml`, `sample_concentration_from_predicted_equivalence_M`, `predicted_equivalence_source` 확인.

## 8. CSV에서 봐야 할 핵심 열

- 시간/동기화
  - `time_s`
  - `thermal_time_s`
  - `visible_time_s`
  - `sync_offset_ms`
  - `sync_quality`
- 펌프/부피
  - `pump_elapsed_s`
  - `pump_run_rate_ml_per_s`
  - `injected_volume_ml`
- 화학 조건
  - `titration_type`
  - `sample_name`
  - `titrant_name`
  - `sample_volume_ml`
  - `titrant_concentration_M`
  - `indicator`
  - `selected_pka_value`
  - `selected_pkb_value`
- 일반 카메라
  - `visible_*`
  - `visible_H*`, `visible_S*`, `visible_V*`
  - `visible_color_delta*`
- 열화상
  - `thermal_roi_avg`
  - `thermal_roi_min`
  - `thermal_roi_max`
  - `thermal_roi_p50`, `thermal_roi_p95`
  - `thermal_raw_*`
  - `thermal_conversion_status`
- 예측 결과
  - `predicted_equivalence_volume_ml`
  - `predicted_equivalence_confidence`
  - `predicted_equivalence_source`
  - `predicted_equivalence_model_key`
  - `sample_concentration_from_predicted_equivalence_M`
  - `predicted_equivalence_pH`

## 9. 검증 명령

Windows/WSL 공통으로 가능한 Python 테스트:

```bash
python -m unittest tests.test_windows_live_collect tests.test_website_assets tests.test_ml_train_predict -v
```

전체 테스트:

```bash
python -m unittest discover -v
```

JS 문법 확인:

```bash
node --check website/app.js
```

typewise model smoke:

```bash
python - <<'PY'
from auto_titrator.typewise_live_model import load_typewise_model
m = load_typewise_model('data/labeled/typewise-current-volume-classifier.pkl')
print(m['artifact_type'])
print(sorted(m['models']))
PY
```

live model artifact 재생성:

```bash
python tools/export_live_typewise_model.py --output data/labeled/typewise-current-volume-classifier.pkl
```

주의: `scikit-learn`이 필요하다.

## 10. 배포 ZIP 새로 만들기

Windows에서 launcher exe를 빌드하고 ZIP을 만들 때:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\build_launcher.ps1
py -3 packaging\windows\create_release_zip.py
```

배포 ZIP에는 다음이 포함되어야 한다.

- `AutoTitration.exe`
- `launchers/`
- `tools/`
- `website/`
- `auto_titrator/`
- `vendor/`
- `data/labeled/typewise-current-volume-classifier.pkl`
- `data/chemistry_constants/`
- `requirements.txt`, `requirements-yolo.txt`

## 11. 현재 문서/포스터 자료 위치

- 최종 보고서 초안: `docs/science_fair_report_final_draft.md`
- 공식 형식 txt: `docs/science_fair_report_final_draft_official_format.txt`
- 앱 개발 보고서 초안: `docs/report_laptop_app_development_draft.md`
- 포스터 ML 문장: `docs/포스터_머신러닝_모델선정_예측정확도_문장.txt`
- 포스터 적정 종류별 성능표: `docs/포스터_적정종류별_성능표.csv`
- 포스터 이미지: `docs/poster_assets/`, `docs/poster_visuals/`

## 12. Windows Codex가 이어서 할 가능성이 높은 작업

우선순위 높은 작업:

1. Windows 실기 실행 확인
   - 21번 BAT 실행
   - 카메라 2개 표시
   - ROI lock
   - Arduino 재연결
   - 녹화 시작/종료
   - CSV에 예측값 저장 확인
2. 실제 실험 CSV 1개로 live 예측 확인
   - `predicted_equivalence_source`가 `typewise_frame_zone_classifier`인지 확인
   - 이론값과 똑같이 고정되어 나오지 않는지 확인
3. 포스터/보고서 수치와 앱 수치 일치 확인
   - 포스터 성능은 development-set임을 문장에 반영
   - 독립 검증처럼 과장하지 않기
4. 릴리즈 ZIP 재생성
   - 수정 후 `v0.1.4` 등으로 release 가능

낮은 우선순위 또는 위험 작업:

- Android 단독 Mini2 ℃ 변환 완성
- 자동 펌프 정지 기능 추가
- full 25fps 온도행렬 CSV 저장
- 모델 성능을 새 데이터 없이 과장하는 변경

## 13. 빠른 장애 대응

### 웹은 뜨는데 카메라가 안 뜸

- `Auto Titration Collector` 창 확인.
- `http://127.0.0.1:8766/api/collector-health` 확인.
- Mini2나 웹캠을 다른 앱이 잡고 있으면 종료.
- `VISIBLE_INDEX`, `MINI2_INDEX`를 수동 지정해 보기.

### 폰에서 접속 안 됨

- 노트북과 폰 같은 Wi-Fi 확인.
- 21번 창의 LAN URL 사용.
- Windows Defender Firewall에서 Python 또는 8765 포트 허용.

### Arduino 버튼이 안 먹음

- Arduino IDE Serial Monitor 닫기.
- 포트가 자동으로 잡혔는지 collector health 확인.
- 펌웨어 baud 9600 확인.
- 원본 펌웨어 명령은 `a`, `b`, `c` 한 글자다.

### 농도 계산이 이론값처럼 보임

- `predicted_equivalence_source` 확인.
- 정상은 `typewise_frame_zone_classifier` 또는 fallback인 `live_feature_peak_estimator`다.
- `ml_json_regression_model`이 뜨면 legacy JSON을 수동 지정한 것일 수 있다.
- `sample_concentration_M` 등 누수 feature 모델은 현재 loader가 거부해야 정상이다.

## 14. 마지막으로 기억할 프로젝트 원칙

- 목표는 산업용 자동적정기가 아니라 전람회용 자동 적정 보조장치다.
- 당량점과 종말점은 구분한다.
- 색 변화만으로 당량점을 정확히 안다고 주장하지 않는다.
- Mini2는 가짜색이 아니라 공식 DLL 기반 ℃ 값 또는 raw evidence로 다룬다.
- 주입량은 실험 중 알 수 있는 값이라 ML 입력 가능하다.
- 진행률, 이론 당량점, 입력한 미지 농도는 ML 예측 feature로 금지한다.
- 자동정지는 하지 않는다.
