# XGBoost·LightGBM·CatBoost 당량점 모델 비교

## 실행 조건

- 라이브러리: XGBoost 3.4.1, LightGBM 4.7.0, CatBoost 1.2.10
- 원자료: 6월 습식 적정 CSV 12개
- 분할: CSV 한 파일을 통째로 제외하는 leave-one-run-out
- 난수: 42, 1729, 20260728을 모두 실행하고 최저 seed를 선택하지 않음
- 모델 입력: 색상·열화상 후보 특징 34개와 실험 전에 선택한 적정 종류
- 제외 입력: 현재 주입량, 이론 당량점, 미지 농도, 시간, 진행률과 정답 필드

## 직접 회귀 결과

| 모델 | MAE | RMSE | MAPE |
|---|---:|---:|---:|
| CatBoost Regressor | 9.777 mL | 11.142 mL | 38.31% |
| LightGBM Regressor | 11.099 mL | 12.159 mL | 41.35% |
| XGBoost Regressor | 13.005 mL | 14.435 mL | 46.81% |

센서 후보에서 당량점 부피를 직접 회귀하는 방식은 세 모델 모두 오차가 컸다.

## 후보 순위학습 결과

| 모델 | 방식 | 평균 MAE | 평균 MAPE | seed 간 MAPE 표준편차 | 최악 절대오차 |
|---|---|---:|---:|---:|---:|
| XGBoost | pairwise ranking+상위 5개 집계 | 3.556 mL | **13.39%** | 1.64%p | 9.058 mL |
| CatBoost | YetiRankPairwise+상위 5개 집계 | 4.277 mL | 15.78% | 0.86%p | **7.998 mL** |
| LightGBM | LambdaRank+상위 5개 집계 | 6.021 mL | 21.92% | **0.20%p** | 15.373 mL |

세 boosting 모델 중 평균 오차는 XGBoost가 가장 낮았다. CatBoost는 평균 오차는 더 컸지만 최악 절대오차가 상대적으로 작았고, LightGBM은 seed 변화에는 가장 안정적이었으나 평균 오차가 가장 컸다.

XGBoost의 상위 특징은 `color_state_w5`, `thermal_state_w8`, `color_terminal_coordinate`, `thermal_shift_w16`, `color_state_w16`이었다. 따라서 boosting 모델도 순간값보다 색 변화의 지속상태와 장시간 열 변화에 주로 반응하였다.

## 적정 종류를 완전히 분리한 결과

각 평가에서 같은 적정 종류의 나머지 두 실험만 학습하고 한 실험을 평가하였다. 다음은 각 boosting 라이브러리에서 가장 낮은 전체 MAPE를 보인 구성이다.

| 모델 | 종류별 개별학습 MAPE |
|---|---:|
| XGBoost | **18.67%** |
| CatBoost | 19.80% |
| LightGBM | 19.95% |

적정 종류마다 boosting 모델과 집계 방법을 별도로 고른 탐색 결과는 다음과 같다.

| 적정 종류 | 가장 낮은 boosting 구성 | MAPE |
|---|---|---:|
| 강산–강염기 | CatBoost 회귀+상위 5개 집계 | 16.39% |
| 강산–약염기 | XGBoost 순위학습+상위 5개 집계 | 12.26% |
| 약산–강염기 | XGBoost 순위학습+최고 후보 | 24.35% |
| 약산–약염기 | LightGBM 회귀+최고 후보 | **8.99%** |

완전 개별학습에서는 평가 run을 제외하면 종류당 학습 실험이 두 개만 남아, 전체 11개 run을 공유한 학습보다 성능이 낮아졌다. 적정 종류를 구분하는 것은 필요하지만 현재 자료에서는 모델 학습까지 완전히 분리하는 것보다 모든 반응계의 공통 센서 변화를 함께 학습하고 적정 종류를 조건으로 주는 편이 더 안정적이었다.

## 12개 전체를 학습한 결과

검증용 run을 제외하지 않고 12개를 모두 학습한 최종 모델을 같은 자료에 다시 적용하였다. 이 값은 배포용 full-fit 모델의 학습자료 재현 정도이며 검증 정확도는 아니다.

| 모델 | 12개 전체 학습 후 재적용 MAPE |
|---|---:|
| LightGBM Ranker | **0.41%** |
| XGBoost Ranker | 1.92% |
| XGBoost 회귀 | 4.16% |
| LightGBM 회귀 | 5.38% |
| CatBoost 회귀 | 7.80% |
| CatBoost Ranker | 8.67% |

LightGBM Ranker의 적정 종류별 재적용 MAPE는 강산–강염기 0.25%, 강산–약염기 0.32%, 약산–강염기 0.36%, 약산–약염기 0.73%였다.

LightGBM full-fit 모델을 설정 변경 없이 7월 지정 미지 시료 3회에 적용한 예측 농도는 0.11062, 0.11075, 0.10408 M였고 변동계수는 3.51%였다. 기존 배포 모델의 동일 자료 CV 0.96%보다 반복성이 낮아 사이트 모델로 승격하지 않았다. 실제 농도가 표정되지 않았으므로 두 모델의 정확도는 비교하지 않았다.

## 결론

XGBoost·LightGBM·CatBoost는 일반적으로 강한 표형 데이터 모델이지만, 이번 자료에서는 독립 실험이 12회뿐이고 종류별로는 3회뿐이어서 복잡한 트리 분기를 안정적으로 학습하지 못했다. 후보 행은 많아도 같은 CSV 안의 행은 독립 실험이 아니므로 실질적인 표본 수가 증가한 것으로 볼 수 없다.

후보 순위학습의 run 제외 평가에서는 가장 좋은 XGBoost도 MAPE 13.39%였다. 12개를 모두 학습한 LightGBM은 같은 자료 재적용에서 0.41%까지 낮아졌지만, 이후 7월 반복자료의 CV가 3.51%로 나타나 현재 배포 모델보다 불안정했다. 따라서 세 모델은 비교 실험 결과로 보존하고 실제 사이트 모델은 변경하지 않았다.

## 산출물

- `data/labeled/boosting-candidate-ranker-comparison.json`
- `data/labeled/lightgbm-fullfit-july-repeatability.json`
- `data/ml/model_zoo_boosting_20260903/aggregate_by_model.csv`
- `tools/compare_boosting_candidate_rankers.py`
- `tests/test_boosting_candidate_rankers.py`
