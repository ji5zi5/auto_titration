# 주입량 사용 여부별 당량점 예측 ablation

## 핵심 결론
- 주입량을 전혀 쓰지 않은 센서 요약 모델의 현재 최저 MAPE는 25.83%이다. 따라서 현재 12개 CSV만으로는 무주입량 5% 이내를 달성하지 못했다.
- 최종 최대 주입량을 쓰는 protocol-assisted 모델은 훨씬 낮아진다. 진단용 최저 모델은 gradient_boosting로 MAPE 0.16%이다.
- 다만 gradient_boosting 결과는 현재 12-run 프로토콜에서 최종 주입량 패턴을 거의 lookup처럼 쓰는 성격이 강하므로, 보고서의 안전한 메인 결과는 nested protocol 보정 MAPE 4.98%로 두는 편이 낫다.
- 모든 결과는 leave-one-run-out으로 계산했고, held-out run의 정답 부피는 입력 feature로 넣지 않았다.

## 전체 모델 비교
| 구분 | 모델 | MAE mL | RMSE mL | MAPE | 5% 이내 | 해석 |
|---|---|---:|---:|---:|---|---|
| 센서만 | knn5 | 7.034 | 8.653 | 25.83% | no | 무주입량 |
| 센서+적정종류 | knn5 | 7.035 | 8.655 | 25.83% | no | 무주입량 |
| 센서+적정종류 | random_forest | 7.350 | 8.442 | 27.13% | no | 무주입량 |
| 센서만 | random_forest | 7.506 | 8.734 | 27.77% | no | 무주입량 |
| 센서+적정종류 | ridge_standard | 8.285 | 10.052 | 30.11% | no | 무주입량 |
| 센서만 | ridge_standard | 8.298 | 10.066 | 30.15% | no | 무주입량 |
| 센서만 | extra_trees | 8.331 | 9.391 | 30.29% | no | 무주입량 |
| 센서+적정종류 | extra_trees | 8.539 | 9.610 | 30.95% | no | 무주입량 |
| 센서만 | knn3 | 9.048 | 10.528 | 34.61% | no | 무주입량 |
| 센서+적정종류 | knn3 | 9.051 | 10.531 | 34.61% | no | 무주입량 |
| 센서만 | knn1 | 9.167 | 11.902 | 35.42% | no | 무주입량 |
| 센서+적정종류 | knn1 | 9.167 | 11.902 | 35.42% | no | 무주입량 |
| 센서만 | gradient_boosting | 10.615 | 12.257 | 36.47% | no | 무주입량 |
| 센서+적정종류 | gradient_boosting | 10.966 | 12.555 | 38.20% | no | 무주입량 |
| 최대주입량+적정종류 | gradient_boosting | 0.043 | 0.053 | 0.16% | yes | post-experiment |
| 최대주입량+적정종류 | random_forest | 0.586 | 0.729 | 1.95% | yes | post-experiment |
| 최대주입량+적정종류 | extra_trees | 1.131 | 1.405 | 3.71% | yes | post-experiment |
| 최대주입량+적정종류 | ridge_standard | 2.465 | 3.000 | 8.95% | no | post-experiment |
| 최대주입량+센서+적정종류 | extra_trees | 5.689 | 6.796 | 20.77% | no | post-experiment |
| 최대주입량+적정종류 | knn5 | 5.644 | 6.733 | 20.81% | no | post-experiment |
| 최대주입량+센서+적정종류 | knn5 | 7.033 | 8.652 | 25.82% | no | post-experiment |
| 최대주입량+센서+적정종류 | gradient_boosting | 7.600 | 8.902 | 26.96% | no | post-experiment |
| 최대주입량+센서+적정종류 | random_forest | 7.425 | 8.611 | 27.69% | no | post-experiment |
| 최대주입량+적정종류 | knn3 | 7.444 | 8.824 | 27.80% | no | post-experiment |
| 최대주입량+센서+적정종류 | ridge_standard | 8.146 | 9.894 | 29.62% | no | post-experiment |
| 최대주입량+센서+적정종류 | knn3 | 9.048 | 10.528 | 34.61% | no | post-experiment |
| 최대주입량+센서+적정종류 | knn1 | 9.167 | 11.902 | 35.42% | no | 진단용 lookup 성격 |
| 최대주입량+적정종류 | knn1 | 10.000 | 10.000 | 36.11% | no | 진단용 lookup 성격 |

## 안전하게 보고서에 쓸 수 있는 값
- 무주입량: 현재 best는 knn5 / sensor_no_volume이며 MAPE 25.83%로 실패.
- 주입량 사용: fixed alpha protocol 보정 MAPE 4.91%, nested protocol 보정 MAPE 4.98%.
- 더 공격적인 진단 모델: gradient_boosting는 MAPE 0.16%까지 내려간다. 단, 최종 주입량 패턴과 12개뿐인 데이터에 강하게 의존하므로 일반화 성능 주장에는 쓰지 않는 것이 안전하다.

## 적정 종류별 nested protocol 보정 한계
| 적정 종류 | MAE mL | MAPE |
|---|---:|---:|
| strong_acid_strong_base | 0.188 | 0.67% |
| strong_acid_weak_base | 2.644 | 9.60% |
| weak_acid_strong_base | 1.063 | 4.73% |
| weak_acid_weak_base | 1.106 | 4.92% |

## 주의 문구
최대 주입량을 쓰는 모델은 실험이 끝난 뒤 알 수 있는 정보를 사용한다. 그래서 실시간 자동 정지 성능이나 순수 색·온도 센서 성능으로 해석하면 안 된다. 본 연구에서는 자동 정지를 목표로 하지 않으므로, 실험 후 당량점·농도 계산 보정 모델로 제한해서 해석한다.

## 생성 파일
- `data/ml/injection_ablation_search/model_comparison.csv`
- `data/ml/injection_ablation_search/typewise_comparison.csv`
- `data/ml/injection_ablation_search/selected_predictions.csv`
- `docs/poster_visuals/19_injection_ablation_mape.svg`
