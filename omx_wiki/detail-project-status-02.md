---
title: "detail-project-status-02"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:12.975Z
updated: 2026-09-10T11:10:12.975Z
sources: []
links: ["detail-project-status-01.md", "detail-project-status-02-part-2.md", "detail-project-status-02-part-3.md", "detail-project-status-02.md", "detail-project-status-03.md", "detail-project-status-04.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-project-status-02

## 문서의 역할과 해석
통합 현황 원문. 작성시점이 다른 단락과 완료/미완료 표현을 구별.

원문: [docs/PROJECT_STATUS_AND_REMAINING_WORK.md](../docs/PROJECT_STATUS_AND_REMAINING_WORK.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-project-status-01]] / [[detail-project-status-02]] / [[detail-project-status-03]] / [[detail-project-status-04]]


분할 이어읽기: [[detail-project-status-02]] / [[detail-project-status-02-part-2]] / [[detail-project-status-02-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
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
auto_titrator/type_conditioned_sensor_live_model.py
auto_titrator/typewise_live_model.py
tools/export_type_conditioned_sensor_live_model.py
tools/export_live_typewise_model.py
tools/validate_optimized_endpoint_research.py
data/labeled/type-conditioned-sensor-endpoint-ranker.pkl
data/labeled/typewise-current-volume-classifier.pkl
docs/endpoint_ml_maximize_report.md
```

실험 종료 후 최종 당량점 계산이 먼저 사용하는 모델은 다음이다.

```text
data/labeled/type-conditioned-sensor-endpoint-ranker.pkl
```

<!-- END SOURCE EXCERPT -->

