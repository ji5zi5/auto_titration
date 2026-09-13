---
title: "detail-report-captions-01-part-2"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:14:00.307Z
updated: 2026-09-10T11:14:00.307Z
sources: []
links: ["detail-report-captions-01-part-2.md", "detail-report-captions-01.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-report-captions-01-part-2

원문 [docs/report_evidence_no_new_wet/표_및_그림_캡션.md](../docs/report_evidence_no_new_wet/표_및_그림_캡션.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-report-captions-01]] / [[detail-report-captions-01-part-2]]
<!-- BEGIN SOURCE EXCERPT -->
## [표 7] 종말점 구간 민감도

| 종말점 구간 | 대비도 산출 가능 run | 융합 APE 개선량과의 탐색적 Spearman ρ |
|---|---:|---:|
| 0.95 ≤ V/Veq ≤ 1.05 | 12/12 | -0.223776 |
| 명목 이론 당량점 ±0.5 mL | 1/12 | 산출하지 않음 |
| 명목 이론 당량점 ±1.0 mL | 12/12 | -0.251748 |
| 명목 이론 당량점 ±2.0 mL | 12/12 | -0.265734 |

**캡션.** 종말점 구간을 바꾼 민감도 분석. ±0.5 mL 구간은 최소 종말점 행 수를 충족한 run이 1개에 그쳐 순위상관을 산출하지 않았다. 이 분석은 탐색적이며 운영적 대비도의 예측력을 입증하지 않는다.

## [표 8] 적정 종류별 탐색적 기술 요약

| 적정 종류 | run | 중앙 운영적 대비도 | 평균 APE 개선량 (pp) | 융합 개선 / 악화 |
|---|---:|---:|---:|---:|
| 강산-강염기 | 3 | 5.132654 | 1.032414 | 2 / 1 |
| 강산-약염기 | 3 | 4.143881 | 0.836381 | 2 / 1 |
| 약산-강염기 | 3 | 3.357544 | -1.897031 | 2 / 1 |
| 약산-약염기 | 3 | 8.676334 | 0.138475 | 1 / 2 |

**캡션.** 적정 종류별 run이 3개인 탐색적 기술 통계. 유형별 검정은 수행하지 않았으며, 특정 유형에서 열화상의 조건부 이득을 입증하는 표로 사용하지 않는다.

## [그림 1] run별 색상 및 색상+열화상 절대오차

**사용 파일:** `data/analysis/report_evidence_no_new_wet/paired_endpoint_errors.png`

**캡션.** 12개 개발 run에서 색상 모델과 색상+열화상 융합 모델의 절대오차를 짝지어 비교한 결과. 융합 오차는 7/12 run에서 줄고 5/12 run에서 커졌다. 주 추정량은 부피 오차가 아닌 APE 차이며, 그 적정 종류 층화 구간은 0을 포함한다.

## [그림 2] run별 운영적 종말점-기저 대비도

**사용 파일:** `data/analysis/report_evidence_no_new_wet/thermal_contrast_by_run.png`

**캡션.** 0.05 ≤ V/Veq ≤ 0.20을 기저, 0.95 ≤ V/Veq ≤ 1.05를 종말점 구간으로 두고, 부호 중앙값 차이의 절대값을 1.4826×MAD로 나눈 run별 운영적 대비도. 모든 ROI 요약값이 0인 행 11개는 제외했다. 이는 사후 운영 지표이며 기기 신호대잡음비가 아니다.

## [그림 3] 운영적 대비도와 융합 APE 개선량

**사용 파일:** `data/analysis/report_evidence_no_new_wet/thermal_contrast_vs_fusion_improvement.png`

**캡션.** 주 구간의 운영적 대비도와 색상 APE - 융합 APE의 run별 관계. Spearman ρ는 -0.223776이고, 고정 seed 100,000회 탐색적 비보정 순열 검정의 p값은 0.485015였다. 이 그림은 운영적 대비도가 융합 개선량을 예측함을 보여 주지 않는다.

## [그림 4] 보고서용 제어 흐름 캡션

**캡션.** 일반 카메라와 열화상 카메라의 신호를 같은 시간축에 저장하고, 펌프 작동 시간×설정 유량으로 계산한 주입량과 함께 CSV에 기록한 흐름. 펄스 제어는 기존 12회 습식 적정의 성능이 아닌 **software-only, dry-tested** 구현으로 표시한다.

## [그림 5] 기준 당량점과 적정 종류 조건부 모델 추정값

**사용 파일:** `docs/report_evidence_no_new_wet/figures/01_actual_vs_predicted.png`

**캡션.** 12개 개발 run의 기준 당량점과 모델 추정값을 비교한 결과. 점선은 기준값과 추정값이 같은 `y=x` 선이며, 점의 색과 모양은 적정 종류를 나타낸다. 평가 run은 모델 적합에서 제외했지만 적정 종류별 설정은 같은 12개 자료에서 선택했다.

## [그림 6] 12개 조건별 모델 추정 오차

**사용 파일:** `docs/report_evidence_no_new_wet/figures/02_ape_by_condition.png`

**캡션.** 적정 종류와 기준 당량점별 절대백분율오차. 12/12 run이 1% 이내였다.

## [그림 7] 적정 종류별 조건부 모델 MAPE

**사용 파일:** `docs/report_evidence_no_new_wet/figures/03_mape_by_titration_type.png`

**캡션.** 적정 종류별 세 run의 평균 절대백분율오차. 강산-강염기 0.25%, 강산-약염기 0.32%, 약산-강염기 0.16%, 약산-약염기 0.45%였다.

## [그림 8] 판정 방식별 MAPE

**사용 파일:** `docs/report_evidence_no_new_wet/figures/04_mape_by_method.png`

**캡션.** 같은 12개 개발 자료에서 산출한 색 최대 기울기, 색·온도 임계값, 기존 머신러닝 입력군 모델과 적정 종류 조건부 센서 모델의 MAPE. 새 조건부 모델은 0.30%로 단순 규칙 기반 방식보다 낮았지만, 총 2,030,370개 설정을 같은 개발 자료에서 비교해 선택한 값이므로 새 시료의 독립 검증 정확도를 뜻하지 않는다.
<!-- END SOURCE EXCERPT -->

