---
title: "detail-report-main-03-part-3"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:14:02.270Z
updated: 2026-09-10T11:14:02.270Z
sources: []
links: ["detail-report-main-03-part-2.md", "detail-report-main-03-part-3.md", "detail-report-main-03.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-report-main-03-part-3

원문 [docs/science_fair_report_national_formatted.md](../docs/science_fair_report_national_formatted.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-report-main-03]] / [[detail-report-main-03-part-2]] / [[detail-report-main-03-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
| 색·온도 임계값 | 색 진행도와 열 변화 점수의 지속 임계값 | 2.033 mL | 3.308 mL | **5.65%** | 7/12 |
| 머신러닝-색상(이전 파이프라인) | 색상 특징+실험 조건, ET·LR·RF | 0.548 mL | 0.754 mL | **1.55%** | **12/12** |
| 머신러닝-열화상(이전 파이프라인) | 열화상 특징+실험 조건, ET·LR | 0.917 mL | 1.267 mL | **3.66%** | **9/12** |
| 머신러닝-색상+열화상(이전 파이프라인) | 두 센서 특징+실험 조건, RF·ET | 0.476 mL | 0.831 mL | **1.52%** | **11/12** |
| 적정 종류 조건부 센서 시계열 모델 | 센서 후보+적정 종류별 PLS·KRR·LDA·QDA | **0.078 mL** | **0.091 mL** | **0.30%** | **12/12** |

¹ `data/report/manual_titration_results.csv`의 최종 제공 기록을 재계산했다. 자동 방식과 판독 시점·검증 구조가 달라 직접 우열 비교에는 사용하지 않았다.

![당량점 판정 방식별 MAPE 비교](report_evidence_no_new_wet/comparison_visuals/06_comprehensive_method_mape.png)

**그림 16.** 제공된 수동 기록, 두 규칙 기반 방식, 이전 파이프라인의 세 센서 입력군 모델과 현재 적정 종류 조건부 모델의 MAPE. 수동 기록은 자동 방식과 판독·검증 구조가 달라 참고값으로 표시하였다.

![당량점 판정 방식별 MAE와 RMSE](report_evidence_no_new_wet/comparison_visuals/07_comprehensive_method_mae_rmse.png)

**그림 17.** 같은 판정 방식의 MAE와 RMSE 비교. 평균 오차뿐 아니라 큰 오차에 민감한 RMSE를 함께 나타냈다.

![조건별 판정 방식 오차](report_evidence_no_new_wet/comparison_visuals/04_condition_method_ape_heatmap.png)

<!-- END SOURCE EXCERPT -->

