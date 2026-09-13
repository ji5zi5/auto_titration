---
title: "detail-ml-posthoc-01"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:19.153Z
updated: 2026-09-10T11:10:19.153Z
sources: []
links: ["detail-ml-posthoc-01.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-ml-posthoc-01

## 문서의 역할과 해석
종류별 사후 모델 선택 이력. 독립 평가로 제시 금지.

원문: [docs/ml_posthoc_typewise_model_selection.md](../docs/ml_posthoc_typewise_model_selection.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-ml-posthoc-01]]

<!-- BEGIN SOURCE EXCERPT -->
# 타입별 사후 선택 ML 모델 비교

이 문서는 예전 curve 모델의 `typewise selected`와 같은 방식으로, 적정 종류별로 가장 낮은 MAE를 보인 모델/feature 조합을 고른 결과이다.
단, 이 선택은 held-out fold 성능을 확인한 뒤 가장 좋은 조합을 고르는 방식이므로 실제 일반화 성능보다 낙관적으로 보일 수 있다.
`with_progress_protocol` 결과는 진행률과 전체 주입량 비율 후보를 포함한 비엄격 프로토콜 보조 수치이며, 센서만으로 실시간 배포 가능한 성능으로 해석하면 안 된다.
따라서 이 결과는 최종 후보 선정용 탐색 결과이며, 단일 고정 모델을 미리 정하고 평가한 엄격 성능과 반드시 구분해야 한다.

## 전체 비교
| 데이터셋 | 선택 범위 | MAE mL | RMSE mL | 상대오차 MAE | 설명 |
|---|---|---:|---:|---:|---|
| old_curve_equivalence_current | old_typewise_selected | 2.306494 | 3.012460 | 8.81% | 예전 curve typewise selected (Extra Trees Regression) |
| with_progress_protocol | all_model_zoo | 2.990418 | 4.006366 | 11.57% | 진행률 포함, 전체 model zoo |
| with_progress_protocol | headline_only | 3.778975 | 5.298609 | 16.05% | 진행률 포함, headline 모델만 |
| strict_no_progress | all_model_zoo | 4.103502 | 4.688437 | 14.91% | 진행률 제거, 전체 model zoo |
| strict_no_progress | headline_only | 5.083177 | 6.040468 | 19.78% | 진행률 제거, headline 모델만 |

## 타입별 선택 결과
| 데이터셋 | 선택 범위 | 적정 종류 | 선택 모델 | feature set | MAE mL | 상대오차 MAE |
|---|---|---|---|---|---:|---:|
| strict_no_progress | all_model_zoo | strong_acid_strong_base | baseline_extra_trees_sensor_signal | sensor_signal_only | 4.422222 | 15.56% |
| strict_no_progress | all_model_zoo | strong_acid_weak_base | kernel_ridge_rbf | sensor_plus_current_volume | 3.466667 | 11.62% |
| strict_no_progress | all_model_zoo | weak_acid_strong_base | random_forest_regressor | sensor_plus_current_volume | 4.599000 | 16.87% |
| strict_no_progress | all_model_zoo | weak_acid_weak_base | svr_rbf_sensor_plus_current_volume | sensor_plus_current_volume | 3.926120 | 15.60% |
| strict_no_progress | headline_only | strong_acid_strong_base | baseline_extra_trees_sensor_signal | sensor_signal_only | 4.422222 | 15.56% |
| strict_no_progress | headline_only | strong_acid_weak_base | baseline_extra_trees_sensor_signal | sensor_signal_only | 6.725866 | 28.64% |
| strict_no_progress | headline_only | weak_acid_strong_base | baseline_extra_trees_sensor_signal | sensor_signal_only | 5.258500 | 19.31% |
| strict_no_progress | headline_only | weak_acid_weak_base | svr_rbf_sensor_plus_current_volume | sensor_plus_current_volume | 3.926120 | 15.60% |
| with_progress_protocol | all_model_zoo | strong_acid_strong_base | extra_trees_sensor_plus_current_volume | sensor_plus_progress | 1.601694 | 6.11% |
| with_progress_protocol | all_model_zoo | strong_acid_weak_base | svr_rbf_sensor_plus_current_volume | sensor_plus_progress | 2.477934 | 11.36% |
| with_progress_protocol | all_model_zoo | weak_acid_strong_base | gaussian_process_regressor | sensor_plus_progress | 4.032044 | 13.03% |
| with_progress_protocol | all_model_zoo | weak_acid_weak_base | kernel_ridge_rbf | sensor_plus_progress | 3.850000 | 15.78% |
| with_progress_protocol | headline_only | strong_acid_strong_base | extra_trees_sensor_plus_current_volume | sensor_plus_progress | 1.601694 | 6.11% |
| with_progress_protocol | headline_only | strong_acid_weak_base | svr_rbf_sensor_plus_current_volume | sensor_plus_progress | 2.477934 | 11.36% |
| with_progress_protocol | headline_only | weak_acid_strong_base | extra_trees_sensor_plus_current_volume | sensor_plus_progress | 5.795167 | 22.40% |
| with_progress_protocol | headline_only | weak_acid_weak_base | svr_rbf_sensor_plus_current_volume | sensor_plus_progress | 5.241105 | 24.31% |

## 해석
- 타입별 사후 선택을 하면 진행률 포함 새 model-zoo도 단일 최고 모델보다 낮은 오차를 낸다.
- 그래도 예전 curve 결과가 더 낮은 이유는 예전 후보 생성과 feature set 구조가 더 강하게 프로토콜 비율 후보를 활용했기 때문이다.
- 이 표는 모델 선택과 성능 보고에 같은 작은 데이터셋을 사용하므로 낙관적이다.
- 보고서에는 이 결과를 `타입별 최적 조합 선정 결과` 또는 `탐색적 최종 후보`라고 표시하고, 확정 일반화 성능처럼 쓰지 않는 것이 안전하다.
<!-- END SOURCE EXCERPT -->

