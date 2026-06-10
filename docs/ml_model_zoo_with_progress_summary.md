# 진행률 포함 머신러닝 재평가 결과

## 실행 조건
- 입력 폴더: 머신러닝용 파일모음
- 출력 폴더: data/ml/model_zoo_equivalence_with_progress
- 검증 방식: 적정 종류별 leave-one-concentration-out
- 진행률 포함: candidate_fraction_of_run, run_volume_max_ml, run_duration_s
- 프로토콜 후보 포함: 전체 주입량의 55~88% 지점 후보
- xgboost, lightgbm, catboost는 설치되어 있지 않아 제외됨

## 전체 최고 결과
- 최고 headline 모델: svr_rbf_sensor_plus_current_volume
- feature set: sensor_plus_progress
- MAE: 5.066699 mL
- RMSE: 6.638629 mL
- 상대오차 MAE: 20.59%

## 이전 결과와 비교
- 진행률 제거 엄격 모델: MAE 8.062083 mL
- 진행률 포함 새 모델: MAE 5.066699 mL
- 예전 curve 모델: MAE 2.306494 mL

진행률을 넣자 엄격 모델보다 오차가 줄었다. 다만 예전 curve 모델보다 낮아지지는 않았다. 이번 모델은 새 후보 추출, 새 feature schema, split artifact 구조를 사용하므로 예전 결과와 완전히 같은 조건은 아니다.

## 적정 종류별 best headline
- strong_acid_strong_base: MAE 1.601694 mL, RMSE 1.827675 mL, 상대오차 6.11% (extra_trees_sensor_plus_current_volume)
- strong_acid_weak_base: MAE 2.477934 mL, RMSE 3.456955 mL, 상대오차 11.36% (svr_rbf_sensor_plus_current_volume)
- weak_acid_strong_base: MAE 5.795167 mL, RMSE 6.151898 mL, 상대오차 22.40% (extra_trees_sensor_plus_current_volume)
- weak_acid_weak_base: MAE 5.241105 mL, RMSE 7.691830 mL, 상대오차 24.31% (svr_rbf_sensor_plus_current_volume)

## 후보 진단
- max_candidate_score: 평균 후보 오차 5.141667 mL
- oracle_best_available_sensor_candidate: 평균 후보 오차 0.258333 mL

해석: 진행률과 전체 주입량 비율 후보를 넣으면 정답 근처 후보가 훨씬 잘 생긴다. 하지만 이것은 센서만으로 당량점을 찾은 성능이라기보다, 실험 프로토콜 정보를 함께 사용한 보조 모델 성능으로 표시해야 한다.
