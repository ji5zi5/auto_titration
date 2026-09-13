---
title: "detail-windows-handoff-01-part-2"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:13:54.502Z
updated: 2026-09-10T11:13:54.502Z
sources: []
links: ["detail-windows-handoff-01-part-2.md", "detail-windows-handoff-01-part-3.md", "detail-windows-handoff-01.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-windows-handoff-01-part-2

원문 [docs/WINDOWS_CODEX_HANDOFF.md](../docs/WINDOWS_CODEX_HANDOFF.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-windows-handoff-01]] / [[detail-windows-handoff-01-part-2]] / [[detail-windows-handoff-01-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
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
<!-- END SOURCE EXCERPT -->

