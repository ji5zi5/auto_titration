# ML 모델-zoo 당량점 예측 결과 요약

## 실행 조건

- 입력 폴더: `머신러닝용 파일모음`
- 실험 수: 12개
- fold 수: 12개, 적정 종류별 leave-one-concentration-out
- 모델 spec 수: 41개
- 주입량 축 보간: 0.05 mL 간격
- smoothing window: 0.25 mL
- headline 모델 입력에서 진행률, 전체 run 길이, 정답/오차/라벨 계열 feature 제외
- RMSE는 모델별 전체 run 예측오차로 다시 계산한 global RMSE이다.

## 전체 결과

| 구분 | 모델 | feature | MAE | RMSE | MAPE | 농도 환산 오차 |
|---|---|---|---:|---:|---:|---:|
| 최저 headline | baseline_extra_trees_sensor_signal | sensor_signal_only | 8.062083 mL | 10.110606 mL | 29.195937% | 29.195937% |
| 최저 exploratory | random_forest_regressor | sensor_plus_current_volume | 8.322167 mL | 10.413353 mL | 30.207882% | 30.207882% |

## 적정 종류별 최저 headline 결과

| 적정 종류 | 모델 | MAE | RMSE | MAPE | 농도 환산 오차 |
|---|---|---:|---:|---:|---:|
| strong_acid_strong_base | baseline_extra_trees_sensor_signal | 4.422222 mL | 4.916851 mL | 15.561133% | 15.561133% |
| strong_acid_weak_base | baseline_extra_trees_sensor_signal | 6.725866 mL | 8.139951 mL | 28.635725% | 28.635725% |
| weak_acid_strong_base | baseline_extra_trees_sensor_signal | 5.2585 mL | 6.081802 mL | 19.305139% | 19.305139% |
| weak_acid_weak_base | svr_rbf_sensor_plus_current_volume | 3.92612 mL | 4.304237 mL | 15.599156% | 15.599156% |


## 핵심 해석

진행률과 전체 run 길이를 제거하고, 실제 실험 중 알 수 있는 현재 주입량 mL와 색/온도 변화만 사용하자 기존 진행률 보조 결과보다 오차가 커졌다. 이는 강한 모델이 부족해서라기보다, 현재 데이터 수가 적고 센서 후보를 고르는 정보가 불안정하기 때문이다.

후보 진단에서 최고 score 후보를 그대로 고르면 MAE는 10.3625 mL였지만, 같은 센서 후보 목록 안에 정답 근처 후보가 존재한다고 가정하면 MAE는 3.129167 mL였다. 즉 현재 병목은 “후보가 아예 없음”보다 “후보 중 무엇을 고를지”에 더 가깝다.

## Optional strong model 처리

XGBoost, LightGBM, CatBoost는 현재 환경에 설치되어 있지 않아 optional dependency로 skip 기록했다. sklearn 기반 GradientBoosting, HistGradientBoosting, KernelRidge, GaussianProcess, MLP는 exploratory로 실행했다.

```json
[
  {
    "dependency": "xgboost",
    "error": "ModuleNotFoundError(\"No module named 'xgboost'\")"
  },
  {
    "dependency": "lightgbm",
    "error": "ModuleNotFoundError(\"No module named 'lightgbm'\")"
  },
  {
    "dependency": "catboost",
    "error": "ModuleNotFoundError(\"No module named 'catboost'\")"
  }
]
```

## 저장 파일

- `data/ml/model_zoo_equivalence_current/model_comparison.csv`
- `data/ml/model_zoo_equivalence_current/model_comparison.json`
- `data/ml/model_zoo_equivalence_current/aggregate_by_model.csv`
- `data/ml/model_zoo_equivalence_current/typewise_best_headline.csv`
- `data/ml/model_zoo_equivalence_current/candidate_availability_diagnostic.csv`
- `data/ml/model_zoo_equivalence_current/warnings.csv`
- `data/ml/model_zoo_equivalence_current/predictions/` 아래 492개 model/fold별 예측 파일
- `data/ml/model_zoo_equivalence_current/candidate_feature_tables/` 아래 492개 model/fold별 후보 feature 파일
- `docs/poster_visuals/14_model_zoo_top_headline_mae.svg`
- `docs/poster_visuals/15_model_zoo_typewise_best_mae.svg`
- `docs/poster_visuals/16_candidate_availability_diagnostic.svg`
