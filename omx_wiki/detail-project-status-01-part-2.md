---
title: "detail-project-status-01-part-2"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:13:55.820Z
updated: 2026-09-10T11:13:55.820Z
sources: []
links: ["detail-project-status-01-part-2.md", "detail-project-status-01-part-3.md", "detail-project-status-01.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-project-status-01-part-2

원문 [docs/PROJECT_STATUS_AND_REMAINING_WORK.md](../docs/PROJECT_STATUS_AND_REMAINING_WORK.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-project-status-01]] / [[detail-project-status-01-part-2]] / [[detail-project-status-01-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
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


## 3.2.1 Mini2 온도 분석 경로 분류

온도 분석은 두 단계로 나눈다.

1. Mini2 raw frame을 섭씨 온도 행렬로 변환한다.
2. 변환된 256x192 온도 행렬에서 ROI/전체 행렬 통계를 뽑아 CSV와 ML feature로 저장한다.

현재 Windows 본경로:

```text
Mini2 UVC 256x344 raw frame
→ upper 256x192 thermal raw matrix
→ addline/metadata block
→ HIKMICRO Analyzer MTlib_OL.dll
→ point 구조체 offset +0x10 int32 temperature
→ temperature_c = point_i32_at_0x10 / 64.0
```

현재 본경로 파일:

```text
auto_titrator/official_hikmicro.py
auto_titrator/mini2_live.py
tools/mini2_mtlib_official_matrix_win.py
tools/mini2_official_mtlib_worker_win.py
vendor/hikmicro_analyzer/MTlib_OL.dll
```

온도 분석 feature는 다음처럼 ROI와 전체 행렬을 모두 기록한다.

```text
thermal_roi_avg/min/max/std/range/iqr
thermal_roi_p05/p25/p50/p75/p95
thermal_roi_hot_fraction/cold_fraction/delta
thermal_matrix_avg/min/max/std/range/iqr
thermal_matrix_p05/p25/p50/p75/p95
thermal_raw_* 보조 feature
thermal_frame_rate_hz, thermal_time_s, abs_sync_offset_ms
```

실험용 변환 경로 분류:

- 현재 인정: `MTlib_OL.dll` official matrix path, `point_i32_at_0x10 / 64.0`.
- 검증/증거용: same-file raw lookup, `metadata_u16[284]` 보정 후보식.
- 폐기/본경로 아님: raw 단순 `/1024`, raw 단순 `/8192`, raw 단순 `/64`, 전역 선형식, min/max-only scaling, palette/fake-color RGB 분석.
- 탐색용 잔재: MicroJITA, MicroTA, MicroJPEG, MT_SubFunction, MicroPixeler, TPI 관련 probe 스크립트.

관련 보고서:

```text
data/mini2_internal_uncompress_probe/ir00001_raw_conversion_report.md
data/mini2_internal_uncompress_probe/ir00001_formula_analysis.md
data/mini2_multi_image_formula/multi_image_formula_report.md
data/mini2_multi_image_formula/formula_sweep/formula_sweep_report.md
data/mini2_rjpeg_raw_research/mini2_rjpeg_raw_research_report.md
docs/validation_protocol.md
```

현재 clone에는 수십 개 probe의 결과 JSON이 모두 남아 있지는 않다. 그러므로 새 작업자는 “스크립트가 있다”는 이유만으로 성공 경로라고 판단하면 안 된다. 현재 공식 주장 경로는 `MTlib_OL.dll` 기반 Windows 경로이고, 나머지는 Android 공식앱 역분석 또는 검증용 참고로 본다.

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
<!-- END SOURCE EXCERPT -->

