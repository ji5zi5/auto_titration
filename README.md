# Smart Auto Titration Data Collector

This app collects synchronized CSV data from a normal USB camera and a HIKMICRO Mini2 V2. The live collection path prioritizes Windows-native raw UVC capture at camera rate; exact official HIKMICRO MTlib Celsius conversion is kept for validation/post-processing so it does not throttle CSV rows.

It does not stop the motor automatically. Its goal is data collection for later equivalence-point estimation.

Science-fair framing: the visible-camera color change is treated as an
experimental endpoint signal, not the true chemical equivalence point. The
neutral point is pH 7, and it is not always the same as the equivalence point,
especially for weak-acid or weak-base titrations. The project records color, Mini2 raw thermal ROI summaries, pump, and experiment metadata so later analysis can compare the observed endpoint with a reference equivalence point.

## Current scope

The codebase is ready for a supervised science-fair run, but model accuracy cannot
be claimed until real titration CSVs exist. The current system should be used as:

1. start the Windows dashboard,
2. lock visible-camera and Mini2 thermal ROIs,
3. record synchronized color/thermal/pump-timeline CSV,
4. add `reference_equivalence_volume_ml` after the run from theory, UV-vis, or a
   trusted comparison method,
5. train/evaluate the equivalence-volume model from those completed CSVs.

It intentionally does **not** use manual status labels and does **not** stop the
pump automatically.

## Run

전람회 시연은 BAT를 2개만 유지합니다. 보통은 21번만 더블클릭하면 됩니다.

```bat
launchers\windows\21_open_dashboard_server.bat
```

21번은 로컬 웹 서버(`http://127.0.0.1:8765/`)를 열고, Mini2 + 일반 카메라
수집기(`http://127.0.0.1:8766/`)를 같이 시작합니다. 노트북과 폰이 같은 Wi-Fi
(same Wi-Fi)에 있으면 폰에서는 21번 창에 표시되는 LAN mode 주소로 접속합니다:

```text
http://<laptop-ip>:8765
```

예: `http://192.168.0.15:8765`. 이때 폰은 Cloudflare/Vercel 같은 외부
호스팅이 아니라 노트북 웹 서버에 직접 접속합니다. 웹 화면의 백엔드는 같은
웹사이트 주소를 통해 collector 프록시를 사용하므로, 폰의 `127.0.0.1`로 잘못
붙지 않습니다. 폰에서 접속이 안 되면 Windows Defender Firewall에서 Python
또는 TCP `%PORT%`/`8765` 접근을 허용합니다.

수집기만 따로 확인할 때만 20번을 실행합니다.

```bat
launchers\windows\20_windows_live_collect.bat
```

### Android companion mode

`mobile/android` is an **Android companion** scaffold for the case where the
phone owns the visible camera and a Mini2 is attached through the phone USB-C
port. The laptop still runs 21번 and **laptop remains the CSV/ML owner**: the
phone sends sensor frames to the existing laptop bridge, and the laptop writes
CSV rows, pump timeline fields, chemistry metadata, and later ML inputs.

Basic flow:

1. On the laptop, run `launchers\windows\21_open_dashboard_server.bat`.
2. On the dashboard, press `Android 연결` to create a pairing token.
3. Open the Android app, enter `http://<laptop-ip>:8765` and the token.
4. The app sends `mobile_feature_frame.v1` JSON to `/api/mobile/ingest`.

The Android side uses `CameraX ImageAnalysis` for visible-camera frames and an
`Android USB host` / `UsbManager` probe for Mini2. The probe only reports
evidence states: `calibrated`, `raw_unverified`, or `blocked`. Until a verified
Android Mini2 converter is attached, frames must keep `thermal_calibrated=false`;
do not create Celsius values from raw bytes on Android. For the current
temperature-calibrated path, use the Windows-native Mini2 collector below.

가장 간단한 Python 확인:

```bash
python3 run.py          # 하드웨어 없이 smoke CSV 생성
python3 run.py cameras  # 카메라 번호 확인
python3 run.py visible  # 일반 카메라만 30프레임 CSV 저장, 펌프 꺼짐
python3 run.py dual     # 일반 카메라 + Mini2/열화상 CSV 저장, 펌프 꺼짐
python3 run.py collect  # auto_titrator/config.yaml 그대로 실행
python3 run.py analyze-simulated  # 하드웨어 없이 estimated equivalence 결과 JSON 생성
python -m auto_titrator.main --dry-run-smoke --smoke-output data/raw/dry-run-smoke.csv
```

`visible`/`dual`은 ROI를 자동으로 중앙에 잡기 때문에 처음 테스트할 때
`config.yaml`을 바로 수정하지 않아도 됩니다.

## First real-run checklist

Before using acid/base, do one water-only rehearsal:

1. Clamp the syringe body, hose, flask, normal camera, and Mini2 so nothing moves.
2. Prime syringe and hose with water; remove visible bubbles and dead volume.
3. Confirm the hose tip is 1–2 cm above the flask opening and not submerged.
4. Upload/check Arduino firmware and confirm Serial Monitor controls:
   `a` rotates left/reverse, `b` rotates right/forward, and `c` stops.
5. Run pump calibration with water by measuring mL dispensed over a known run
   time; put that measured flow rate into the dashboard/config timeline.
6. Start `21_open_dashboard_server.bat`, set chemistry/pump timeline values, and
   lock both ROIs before pressing CSV record.
7. Record 20–30 seconds of water-only data and download the CSV. Confirm
   `injected_volume_ml`, `visible_*`, `thermal_*`, and `sync_offset_ms` are being
   written before real reagents.

For actual titration, keep raw CSVs unchanged in `data/raw/`. Copy selected runs
to `data/labeled/` only after adding reference/validation values for analysis.

### Windows live collector

현재 기본 실험 경로는 Windows-native Mini2 UVC raw capture입니다. Mini2가
노출하는 `256x344` raw frame의 위쪽 `256x192` 영역을 IR 원본 행렬로 다루고,
라이브 CSV에는 ROI/전체행렬 scalar feature를 저장합니다. 기본 Windows
launcher는 `THERMAL_PROCESSING=roi`로 공식 DLL ℃ 변환을 먼저 시도하고,
converter가 없거나 `suspect_all_zero`/`non_finite`/`empty`처럼 무효 결과를
반환하면 `thermal_conversion_status`와 경고를 남긴 뒤 raw preview/CSV로
내려갑니다. 전체 25fps thermal matrix CSV는 기본으로 만들지 않습니다.

본 구현은 Analyzer CSV 값으로 맞춘 근사식이 아니라, 공식 DLL이 반환하는
`point_i32_at_0x10` 값을 `temperature_c = point_i32_at_0x10 / 64.0`으로
해석하는 `raw→℃ converter` 후처리/검증 경로를 보유합니다. Analyzer CSV는 0.1℃ 단위 표시/절삭
결과라 검증 참고용으로만 사용하며, 전람회 설명에서는 `/64` 공식 DLL 경로를
본 온도 변환으로 설명합니다.
`MT_SubFunction` full-frame 테이블 경로와 affine/lookup 근사식은 과거 조사/검증용
경로라 본 경로로 쓰지 않습니다.

주의: `--frame-rate-hz 25`는 카메라에 25fps를 요청하는 값입니다. 실제 fps는
USB/UVC/PC 부하에 따라 달라지므로 실행 로그의 measured fps를 같이 기록합니다.
기본 실행이 안 잡히면 `python3 run.py cameras`로 번호를 확인하고,
Mini2가 `DSHOW=blank`처럼 보이는 경우에는 Windows MSMF 쪽을 우선 확인합니다:

```bash
py run.py dual --visible 0 --thermal 1 --thermal-backend msmf
```

### Optional YOLO visible ROI mode

Windows live collection can use YOLO for the optional visible-camera ROI setup
button. Automatic ROI is off by default, so the model is not loaded and does not
reduce recording FPS. When the user turns automatic ROI on, YOLO is loaded on
demand; locking the ROI or starting a recording turns automatic setup off. The
default launcher does not install Ultralytics automatically. Install
`requirements-yolo.txt` only when visible-camera automatic ROI is wanted. Mini2
thermal ROI detection remains independent and works without YOLO.

Manual command example:

```bash
py -3 tools/windows_live_collect.py --visible-roi-detector yolo --yolo-model yolo11n-seg.pt --roi-auto-detect both
```

Accepted YOLO classes default to cup/bottle/glass-like containers, and
person/face/hand detections are ignored so a student walking in front of the
camera is not treated as the titration vessel.

## 센서 동기화

Windows live collector는 Mini2 프레임과 일반 카메라 프레임을 같은 프로세스의
공통 PC clock으로 timestamp합니다. 이것은 전용 trigger 선을 쓰는 하드웨어 동기화는
아니며, 각 Mini2 thermal frame 시간에 가장 가까운 visible frame을
매칭하는 software synchronization입니다.

CSV에는 `thermal_time_s`, `visible_time_s`, `sync_offset_ms`, `sync_quality`,
`sync_warning`을 저장합니다. 기본 허용 기준은 `20 ms`입니다. 예를 들어 펌프가
`1 mL/s`로 움직이면 20 ms 시간차는 약 0.02 mL 주입량 차이에 해당하므로,
`sync_quality=warning` 또는 `sync_warning`이 뜬 구간은 당량점 후보 해석에서
주의해서 보거나 재촬영합니다. 수집은 25fps history를 유지하고, ML/status 판단은
이 기록을 백그라운드에서 더 느리게 소비할 수 있습니다.

공식 DLL 변환 검증/후처리:

```bash
py.exe -3 tools/mini2_official_fullframe_validation_win.py --dll-dir vendor/hikmicro_analyzer
```

온도 ℃ 후처리는 Analyzer CSV 값으로 맞춘 근사식이 아니라, 공식 DLL이 반환하는
`point_i32_at_0x10` 값을 `temperature_c = point_i32_at_0x10 / 64.0`으로
해석하는 경로입니다. Analyzer CSV는 0.1℃ 단위 표시/절삭 결과라 검증 참고용으로만
사용하며, 전람회 설명에서는 `/64` 공식 DLL 경로를 본 온도 변환으로 설명합니다.
`MT_SubFunction` full-frame 테이블 경로와 affine/lookup 근사식은 과거 조사/검증용
경로라 본 경로로 쓰지 않습니다.

기존 직접 실행:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m auto_titrator.main --config auto_titrator/config.yaml
```

The app writes rows to `data/raw/run-YYYYMMDD-HHMMSS.csv` until `Ctrl+C`.

Hardware-free smoke check:

```bash
python -m auto_titrator.main --dry-run-smoke --smoke-output data/raw/dry-run-smoke.csv
```

This writes one synthetic-camera CSV row with estimated/not-connected pump metadata.


## Status-only equivalence analysis

`analyze-simulated`는 실제 카메라 없이 feature history와 retrospective analyzer를
테스트합니다. 결과 JSON에는 `estimated equivalence` 시간/부피, 신뢰도, 근거,
이론 당량점과의 오차가 들어갑니다. 이 경로는 **status-only** 분석이며 펌프를
자동으로 멈추지 않습니다. 기본 저장물은 가벼운 feature history와 final result만
포함하고, **full 25fps thermal matrix CSV**를 만들지 않습니다. Mini2 보정 온도
행렬이 없으면 color-only/thermal-unavailable 경고를 남기고 낮은 신뢰도로 계속
동작합니다.

```bash
python3 run.py analyze-simulated --output data/raw/simulated-equivalence-result.json
python3 -m auto_titrator.live_app --simulated --output data/raw/simulated-equivalence-result.json
```

## Configure cameras

Edit `auto_titrator/config.yaml`:

- `visible_camera.device_index`: normal camera, usually `0`
- `thermal_camera.device_index`: Mini2 V2 USB/mirrored stream, often `1`
- `roi`: crop rectangle for the flask or thermal app area
- `pump.estimated_ml_per_second`: temporary flow estimate before calibration

Supported `experiment.titration_type` values:

- `strong_acid_strong_base`
- `weak_acid_strong_base`
- `strong_acid_weak_base`
- `weak_acid_weak_base`

## Chemical model metadata

The web run screen records chemistry context with every CSV row. It currently
stores the selected titration class, sample name, standard-solution name and
concentration, indicator, local IUPAC pKa lookup result, and the indicator
transition range. The web UI auto-selects the closest room-temperature pKa
candidate by default and records that as `auto_selected_room_temperature`; a
manual candidate change is recorded as `confirmed_by_user`. The
standard-solution concentration is user-entered; this app
does not run a separate standard solution verification workflow. The live web
screen records metadata only: full pH-curve/indicator endpoint calculations are
separate analysis/model work, not silently claimed during live collection.

The local lookup API is:

```text
POST /api/chemistry/constants/lookup
{"query": "acetic acid", "limit": 8}
```

It searches `data/chemistry_constants/iupac/iupac_high-confidence_v2_3.csv`
only. If several pKa candidates are returned, the browser auto-selects the
closest room-temperature candidate and records
`constants_confirmation_status=auto_selected_room_temperature`; manual changes
are recorded as `confirmed_by_user`. Strong electrolytes such as HCl/NaOH are
handled by the strong-electrolyte model, not by invented pKa presets.

## Stepper pump wiring

The syringe pump is driven by an Arduino/ESP32-style board plus a stepper
motor driver. The actual firmware is intentionally short and lives at
`auto_titrator/arduino_stepper/arduino_stepper.ino`.

Default Arduino pin map:

| Firmware name | Arduino pin | Driver signal |
| --- | ---: | --- |
| `STEP_PIN` | 2 | STEP / PUL |
| `DIR_PIN` | 3 | DIR |
| `ENABLE_PIN` | 4 | EN / ENABLE |

Connect driver GND to Arduino GND. Power the stepper motor from a separate
motor supply that matches the driver and motor rating; do not power the motor
from the Arduino 5 V pin.

Current serial controls are deliberately simple for the real pump build:

| Serial Monitor key | Action |
| --- | --- |
| `a` | rotate left continuously; in the current pump build this is the pull-back direction |
| `b` | rotate right continuously; in the current pump build this is the dispense/start direction |
| `c` | stop motor and disable driver |

Open Serial Monitor at 9600 baud for direct testing. The website uses the same
one-letter protocol: recording start sends `b`, recording stop sends `c`, and
the pull-back button sends `a`. The separate **펌프 밀기** button also sends
`b`, so the pump can be pushed manually without starting CSV recording. If the
physical direction is backwards, change the launcher command mapping
(`PUMP_START_COMMAND`/`PUMP_RETRACT_COMMAND`) or swap the `HIGH`/`LOW` values in
the original sketch. Speed is set by the two `delayMicroseconds(5000)` calls;
smaller values are faster. Keep a physical power switch or driver-enable access
as the real emergency stop.

The original working Arduino sketch does not calculate volume. The app estimates
`injected_volume_ml` from the configured pump timeline: elapsed recording time ×
measured flow rate.

This project still keeps pump operation supervised. Camera/thermal/ML output
estimates the equivalence point but does not stop the motor automatically.

## Pump calibration

Use 물 보정 before real titration:

1. Fill the syringe and hose with water and remove bubbles.
2. Press recording start or send `a`, then run for a measured time.
3. Press recording stop or send `c`.
4. Measure dispensed water volume with a graduated cylinder or balance.
5. Calculate `flow_rate_ml_per_s = measured_volume_ml / run_time_s` and put that
   value into the configured pump timeline. For example, 10 mL / 10.05 s is
   about 0.995 mL/s.
6. If the rate is too high or too low, adjust the sketch's
   `delayMicroseconds(5000)` timing or the motor driver microstepping, then repeat.

Recalibrate after changing the syringe, hose, tip, lead screw, microstepping,
motor driver current, or supply voltage.

## CSV fields

The CSV schema is version `1.7`. It contains schema version, experiment and
chemistry-model metadata, theoretical equivalence volume, reference/label
placeholders, CSV session/row index/recording elapsed time/event note, pump
state/rate, time, frame ID, injected volume estimate, visible
RGB/HSV/color-delta/HSV-delta features, thermal-palette RGB/HSV/color-delta/
HSV-delta features, and Mini2 raw thermal ROI/full-matrix scalar features.
Optional official Celsius columns are added only when `THERMAL_PROCESSING=roi`
or `full` is deliberately enabled, or during post-processing. Thermal summaries
include mean/min/max/std/delta plus p05/p25/p50/
p75/p95, IQR, range, hot/cold fractions, and min/max pixel coordinates for the
ROI where available. Schema 1.6 also adds ML-derived values: baseline shifts,
1-second rolling means/maxima, short-window slopes, titration-type one-hot
columns, `abs_sync_offset_ms`, `training_quality_score`, and `valid_for_training`.
Full 25fps raw thermal matrices are kept in memory for ROI/scalar analysis but
are not written as huge per-pixel CSV columns by default.

The legacy thermal RGB/HSV columns are palette-color features. For real
temperature features, use the calibrated Mini2 temperature post-processing path:
official Analyzer-exported matrix replay or `MTlib_OL.dll` conversion.
Approximate affine/lookup converters remain only for old validation experiments
and must not be presented as the official temperature conversion.
Sensor alignment fields are also recorded:
`thermal_time_s`, `visible_time_s`, `sync_offset_ms`, `sync_quality`, and
`sync_warning`.

## Train, predict, evaluate

During collection, the web screen records sensor features, pump timing, chemistry metadata,
and derived ML features automatically. After collecting runs, copy selected CSVs to
`data/labeled/` and add reference equivalence values from the theoretical calculation,
UV-vis comparison, or other validation source. Keep raw files unchanged.

Train a simple transparent equivalence-volume model:

```bash
python -m auto_titrator.ml_train data/labeled/run1.csv --model data/labeled/equivalence-model.json
```

Add equivalence-volume predictions to a CSV:

```bash
python -m auto_titrator.ml_predict --model data/labeled/equivalence-model.json --input data/labeled/run1.csv --output data/labeled/run1-predicted.csv
```

Compare color endpoint error vs ML prediction error:

```bash
python -m auto_titrator.evaluation data/labeled/run1-predicted.csv --output data/labeled/metrics.json
python -m auto_titrator.plot_results --metrics data/labeled/metrics.json --output data/labeled/error-comparison.svg
```

The model is optional until labeled CSV data exists. Sparse data produces a
warning and a constant fallback model rather than a confident claim.
