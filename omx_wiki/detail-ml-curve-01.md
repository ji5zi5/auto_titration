---
title: "detail-ml-curve-01"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:16.797Z
updated: 2026-09-10T11:10:16.797Z
sources: []
links: ["detail-ml-curve-01-part-2.md", "detail-ml-curve-01-part-3.md", "detail-ml-curve-01.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-ml-curve-01

## 문서의 역할과 해석
과거 curve 후보 회귀 탐색. 현행 배포 정확도 아님.

원문: [docs/ml_curve_equivalence_summary.md](../docs/ml_curve_equivalence_summary.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-ml-curve-01]]


분할 이어읽기: [[detail-ml-curve-01]] / [[detail-ml-curve-01-part-2]] / [[detail-ml-curve-01-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
# ML 당량점 예측 구현 정리

## 목적

이 문서는 현재 코드에서 구현된 **곡선 기반 당량점 예측 머신러닝** 기능을 요약한다. 목표는 프레임마다 정답 부피를 맞히는 것이 아니라, 한 번의 적정 실험에서 최종적으로 **당량점 부피 1개**를 예측하는 것이다.

## 현재 방식

1. 실험 CSV 1개를 하나의 run으로 본다.
2. 25fps로 기록된 색상/열화상/주입량 데이터를 주입량-센서값 곡선으로 바꾼다.
3. 색 변화, 열 변화, 융합 변화가 큰 지점을 당량점 후보로 뽑는다.
4. 후보마다 주변 색/열 변화량, 기울기, 곡률, 안정도, 후보 간 일치도 등을 feature로 만든다.
5. 같은 적정 종류 안에서 한 농도 run을 빼고 나머지로 학습한 뒤, 빠진 run의 당량점 부피를 예측한다.

이론 당량점은 **학습 정답/평가 target으로만 사용**하고 model input feature에는 넣지 않는다.

## 사용한 주요 feature

- 일반 카메라: RGB 평균, HSV 평균, 색 변화량, 색 변화 기울기/곡률
- 열화상: ROI 평균/최대/최소/표준편차/분위수/범위/IQR
- raw thermal: raw ROI 분포값, 전체 raw 요약값
- 후보 신뢰도: 색/열/융합 후보끼리 가까운 정도, 후보 점수 순위, 주변 후보 밀도
- sensor-only 후보 신뢰도: 실제 주입량/진행 정보와 고정비율 후보를 일부러 뺀 후보 일치도
- 주입량/현재 부피: 펌프 구동 시간과 보정 유량으로 실시간 수집 가능한 정당한 입력값
- 좌표 feature: thermal hot/cold point의 ROI 내 정규화 위치 변화
- 품질/동기화: sync offset, training quality, ROI 크기 등은 별도 feature set에서만 평가

## 비교한 feature set

- `current_fusion`: 기존에 가장 안정적이었던 compact 색+열 융합 기준선
- `compact_plus`: `current_fusion`에 후보 간 source agreement, score rank, local density를 소량 추가한 모델
- `compact_plus_no_progress`: `compact_plus`에서 실제 주입량/진행 정보와 고정비율 후보를 일부러 제거한 sensor-only ablation 모델
- `thermal_basic`: 기본 열화상 feature만 사용
- `thermal_expanded`: 확장 열화상/분포 feature 사용
- `color_expanded`: 확장 RGB/HSV feature 사용
- `fusion_expanded`: 색+열 확장 feature 전체 사용
- `fusion_no_progress`: 실제 주입량/진행 정보를 일부러 제거해 센서 feature만 남겼을 때의 성능을 보는 ablation 모델
- `run_quality_context`: 동기화/품질/ROI 크기 등 실험 품질 context 평가

## 현재 결과

현재 `머신러닝용 파일모음`의 12개 run 기준 결과는 다음과 같다.

| 항목 | 값 |
|---|---:|
| 전체 run 수 | 12 |
| 전체 MAE | 2.306494 mL |
| median AE | 2.358796 mL |
| RMSE | 3.012460 mL |
| 상대오차 MAE | 8.810450% |
| 농도 환산 오차 MAE | 8.810450% |
| ±0.5 mL 성공률 | 0.333333 |
| ±1.0 mL 성공률 | 0.416667 |
| ±1/±2/±5% 성공률 | 0.250000 / 0.333333 / 0.416667 |

이전 `current_fusion`만 썼을 때 전체 MAE는 2.371490 mL였고, `compact_plus`를 후보로 추가한 뒤 탐색적 best-per-type 기준 전체 MAE는 2.306494 mL로 소폭 개선됐다. 하지만 이 개선은 작고, 후처리식 best-per-type 선택이므로 일반화 성능으로 주장하면 안 된다.

| 적정 종류 | 선택된 feature set | 실제/예측 평균 부피 | MAE | 상대오차 MAE | 농도 환산 오차 MAE | ±1/±2/±5% 성공률 |
|---|---|---:|---:|---:|---:|---:|
| 강산-강염기 | current_fusion | 30.000000 / 30.029541 mL | 0.344194 mL | 1.345296% | 1.345296% | 0.333333 / 0.666667 / 1.000000 |
| 강산-약염기 | current_fusion | 30.000000 / 30.123287 mL | 3.021775 mL | 9.932038% | 9.932038% | 0.000000 / 0.000000 / 0.000000 |
| 약산-강염기 | compact_plus | 30.000000 / 30.777155 mL | 3.037659 mL | 13.216226% | 13.216226% | 0.333333 / 0.333333 / 0.333333 |
| 약산-약염기 | current_fusion | 30.000000 / 30.125907 mL | 2.822347 mL | 10.748239% | 10.748239% | 0.333333 / 0.333333 / 0.333333 |

핵심 비교는 다음과 같다.

| 적정 종류 | current_fusion | compact_plus | compact_plus_no_progress | 해석 |
|---|---:|---:|---:|---|
| 강산-강염기 | 0.344194 | 1.802157 | 14.877467 | 기존 compact 기준선이 더 안정적 |
| 강산-약염기 | 3.021775 | 5.459623 | 15.113180 | compact_plus가 악화됨 |
| 약산-강염기 | 3.297643 | 3.037659 | 13.251869 | compact_plus만 약간 개선됨 |
| 약산-약염기 | 2.822347 | 3.797470 | 28.086324 | current_fusion이 평균 MAE는 더 낮음 |


## MAE 말고 같이 봐야 하는 지표

MAE(mL)는 직관적이지만, 당량부피가 작은 실험과 큰 실험을 같은 기준으로 비교하기 어렵다. 그래서 리포트에는 다음 값을 함께 기록한다.

- `mean_actual_equivalence_volume_ml`, `mean_predicted_equivalence_volume_ml`: 실제/예측 당량부피 평균
- `mae_percent_of_equivalence`: 당량부피 대비 상대오차 MAE
- `bias_percent_of_equivalence`: 예측이 체계적으로 크거나 작은지 보는 상대 bias
- `within_1pct_rate`, `within_2pct_rate`, `within_5pct_rate`: 상대오차 허용범위 성공률
<!-- END SOURCE EXCERPT -->

