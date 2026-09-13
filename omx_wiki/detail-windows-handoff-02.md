---
title: "detail-windows-handoff-02"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:12.028Z
updated: 2026-09-10T11:10:12.028Z
sources: []
links: ["detail-windows-handoff-01.md", "detail-windows-handoff-02-part-2.md", "detail-windows-handoff-02-part-3.md", "detail-windows-handoff-02.md", "detail-windows-handoff-03.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-windows-handoff-02

## 문서의 역할과 해석
운영 인수인계 이력. 날짜·배포 경로는 실행본과 재확인.

원문: [docs/WINDOWS_CODEX_HANDOFF.md](../docs/WINDOWS_CODEX_HANDOFF.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-windows-handoff-01]] / [[detail-windows-handoff-02]] / [[detail-windows-handoff-03]]


분할 이어읽기: [[detail-windows-handoff-02]] / [[detail-windows-handoff-02-part-2]] / [[detail-windows-handoff-02-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
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

<!-- END SOURCE EXCERPT -->

