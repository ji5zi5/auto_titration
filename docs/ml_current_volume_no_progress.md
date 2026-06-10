# 현재 주입량 허용 / 진행도 금지 ML 학습 결과

이 평가는 `injected_volume_ml`은 입력으로 사용하지만, 최종 주입량·진행률·전체 시간·프레임 수·정답 거리 같은 누수 정보는 입력에서 제외했다.

- 입력 CSV: 머신러닝용 파일모음
- 실험 run 수: 12
- 예측 단위: one_equivalence_volume_prediction_per_csv_run
- 최고 모델: typewise_development_selector:best_per_titration_type
- MAE: 0.392472 mL
- RMSE: 0.685276 mL
- MAPE: 1.271147 %

> 주의: 현재 최고값은 적정 종류별로 모델을 따로 고른 development-set 결과이다. 금지 feature를 쓰지는 않았지만, 독립 외부 검증 성능으로 과장하면 안 된다.

## 금지한 정보

최종 주입량(run_volume_max), 진행률/fraction, 전체 실험 시간/duration, 프레임 수/행 번호, 이론 당량점, 정답과의 거리/오차/라벨은 feature에서 제거했다.

## 적정 종류별 최고 모델 성능

| 적정 종류 | MAE(mL) | RMSE(mL) | MAPE(%) |
|---|---:|---:|---:|
| strong_acid_strong_base | 0.139702 | 0.164010 | 0.470296 |
| strong_acid_weak_base | 0.232267 | 0.306315 | 0.674847 |
| weak_acid_strong_base | 1.084854 | 1.319882 | 3.486481 |
| weak_acid_weak_base | 0.113065 | 0.124882 | 0.452964 |

## 해석

이 파일은 보고서용 수치 주장을 바로 고정하기보다, 누수 없는 조건에서 어떤 방식이 가장 나은지 확인하기 위한 학습 산출물이다.
MAPE가 목표값 이하가 아니면 데이터 또는 모델 탐색을 더 해야 하며, 진행도 기반 결과와 섞어 주장하면 안 된다.
