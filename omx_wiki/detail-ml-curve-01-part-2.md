---
title: "detail-ml-curve-01-part-2"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:13:58.353Z
updated: 2026-09-10T11:13:58.353Z
sources: []
links: ["detail-ml-curve-01-part-2.md", "detail-ml-curve-01-part-3.md", "detail-ml-curve-01.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-ml-curve-01-part-2

원문 [docs/ml_curve_equivalence_summary.md](../docs/ml_curve_equivalence_summary.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-ml-curve-01]] / [[detail-ml-curve-01-part-2]] / [[detail-ml-curve-01-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
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
<!-- END SOURCE EXCERPT -->

