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
- `concentration_mae_percent`: 예측 당량부피로 미지시료 농도를 계산했을 때의 농도 상대오차

농도 계산에서 표준용액 농도, 시료 부피, 반응 몰비가 같다면 예측 농도 상대오차는 예측 당량부피 상대오차와 같다. 따라서 전람회에서는 “mL 오차”와 “농도 환산 오차(%)”를 같이 제시하는 것이 더 설득력 있다.

## 해석

확장 feature를 많이 넣는다고 무조건 정확도가 좋아지지는 않았다. 현재 데이터 12개에서는 `fusion_expanded`가 오히려 과적합 또는 잡음 증폭 경향을 보였고, `compact_plus`도 전체적으로는 소폭 개선에 그쳤다.

중요한 점은 `compact_plus_no_progress`가 매우 나쁘다는 것이다. 여기서 제거한 `candidate_volume_ml`, `candidate_fraction_of_run`, `run_volume_max_ml`, `run_duration_s`는 정답 누수가 아니라 펌프와 시간으로 실제 수집 가능한 정보다. 따라서 최종 실사용 모델에서는 주입량/현재 부피를 당연히 써야 한다. 다만 이 ablation 결과는 현재 12개 run에서 순수 sensor-only 후보 일치도만으로는 당량점을 안정적으로 고르기 어렵다는 뜻이다.

전람회에서는 다음처럼 설명하는 것이 안전하다.

> 색/열 변화와 실제 주입량 정보를 함께 사용해 당량점 후보를 만들고, 머신러닝으로 후보 중 하나를 고른다. 후보 간 일치도 feature를 추가하면 일부 조건에서는 개선됐지만, 현재 데이터가 적어 모든 적정 종류에서 안정적으로 좋아지지는 않았다. 따라서 현재 결과는 실험 가능성을 보인 proof-of-concept이며 반복 실험을 늘려야 한다.

## 산출물 해석 주의

- `candidate_tables/`: 진단용 전체 후보표다. 여기에는 `actual_equivalence_volume_ml`, `candidate_error_ml` 같은 평가용 열과 넓은 센서 feature가 들어갈 수 있다.
- `candidate_feature_tables/`: 실제 모델 입력 feature만 투영한 표다. 모델이 무엇을 입력으로 썼는지 확인할 때는 이 폴더를 봐야 한다.
- `feature_importance.csv`: 각 fold에서 모델이 중요하게 본 feature다. 주입량/현재 부피 feature가 상위에 뜨는 것은 허용되지만, 그 경우 “센서만으로 예측했다”가 아니라 “센서+주입량 정보 융합”이라고 표현해야 한다.

## 누수 방지

모델 input에서 제외하는 값:

- 이론 당량점 부피/시간/pH
- 실제 당량점, 예측 당량점, 오차값
- `delta_ml`, `distance_to_equivalence_ml`
- pKa 관련 열 (`pka_value`, `acid_pka`, `solution_pKa` 등)
- 지시약 endpoint 관련 열
- label/target 계열 열

즉, 정답을 feature로 넣어서 맞히는 꼼수는 막아 두었다.

## 생성되는 산출물

실행 후 `data/ml/curve_equivalence_current/`에 생성된다.

- `report.md`: 사람이 읽는 한국어 요약 보고서
- `curve_equivalence_summary.json`: 전체 상세 결과
- `curve_equivalence_summary.csv`: fold별 요약
- `primary_comparison.csv`: 핵심 feature set 비교
- `feature_set_comparison.csv`: 전체 feature set 비교
- `typewise_run_metrics.csv`: 적정 종류별 선택 모델의 MAE, 상대오차, 농도 환산 오차, 성공률 비교
- `feature_importance.csv`: 모델이 중요하게 본 feature 목록
- `predictions/`: 예측 결과
- `candidate_tables/`: 진단용 후보별 전체 테이블
- `candidate_feature_tables/`: 실제 모델 입력 feature만 담은 후보 테이블

## 실행 명령

WSL/리눅스 환경에서:

```bash
source .venv/bin/activate
python -m auto_titrator.ml_curve_equivalence '머신러닝용 파일모음' \
  --output-dir data/ml/curve_equivalence_current \
  --fps 25
```

검증 명령:

```bash
source .venv/bin/activate
python -m unittest tests.test_ml_curve_equivalence -v
python -m unittest discover -v
npx --yes pyright auto_titrator/ml_curve_equivalence.py tests/test_ml_curve_equivalence.py
```

## 현재 한계

- 총 12개 run뿐이라 일반화 정확도라고 주장하면 안 된다.
- 각 적정 종류마다 농도 3개 수준이라 학습 데이터가 매우 적다.
- 약산/약염기 계열은 강산-강염기보다 오차가 크다.
- 후보 pool 안에는 실제 당량점에 가까운 후보가 이미 있는 편이라, 다음 개선은 후보 생성보다 **후보 선택/랭킹 안정화**에 집중해야 한다.
- sensor-only ablation 모델이 크게 악화되므로, 새 실험 데이터를 수집하기 전에는 `compact_plus`를 “완성된 센서-only 모델”로 주장하면 안 된다. 최종 모델은 센서값과 실제 주입량 정보를 함께 쓰는 모델로 설명해야 한다.
- 현재 결과는 “완성된 실사용 모델”이 아니라 “센서 데이터로 당량점 예측이 가능한지 검증한 proof-of-concept”로 표현해야 한다.

## 전람회 발표용 핵심 문장

- “프레임 하나하나를 독립 데이터처럼 보지 않고, 한 번의 적정 실험을 하나의 run으로 처리했다.”
- “이론 당량점은 정답 label로만 사용하고, 입력 feature에서는 제거해 데이터 누수를 방지했다.”
- “색 변화와 열화상 변화를 함께 이용해 당량점 후보를 만들고, 머신러닝으로 후보 중 가장 가능성 높은 부피를 선택했다.”
- “후보 간 일치도 feature를 추가해 일부 조건에서 개선을 확인했지만, 데이터 부족 때문에 반복 실험 검증이 필요하다.”
