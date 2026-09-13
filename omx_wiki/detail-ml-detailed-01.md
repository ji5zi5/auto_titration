---
title: "detail-ml-detailed-01"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:17.116Z
updated: 2026-09-10T11:10:17.116Z
sources: []
links: ["detail-ml-detailed-01-part-2.md", "detail-ml-detailed-01-part-3.md", "detail-ml-detailed-01.md", "detail-ml-detailed-02.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-ml-detailed-01

## 문서의 역할과 해석
과거 상세 ML 결과. 입력·검증 조건을 함께 보존.

원문: [docs/ml_equivalence_result_detailed_summary.md](../docs/ml_equivalence_result_detailed_summary.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-ml-detailed-01]] / [[detail-ml-detailed-02]]


분할 이어읽기: [[detail-ml-detailed-01]] / [[detail-ml-detailed-01-part-2]] / [[detail-ml-detailed-01-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
# 머신러닝 당량점 예측 결과 상세 정리

## 1. 분석 목적

이번 머신러닝 분석의 목표는 프레임마다 `before/endpoint` 같은 상태를 맞히는 것이 아니라, **한 번의 적정 실험에서 최종 당량점 부피 1개를 예측**하는 것이다.

즉, 모델의 최종 출력은 다음과 같다.

```text
이 실험에서 당량점은 약 몇 mL 지점인가?
```

전람회 관점에서는 “색 변화와 열화상 변화, 그리고 주입량 정보를 이용해 사람이 눈으로만 판단하던 지점을 정량적으로 찾을 수 있는가”를 확인하는 proof-of-concept 분석이다.

## 2. 사용한 데이터

현재 분석에 사용한 데이터는 `머신러닝용 파일모음` 폴더의 실제 실험 CSV이다. 총 12개 run을 사용했다.

| 적정 종류 | run 수 | 농도 조건 |
|---|---:|---|
| 강산-강염기 | 3 | 0.10 M, 0.15 M, 0.20 M |
| 강산-약염기 | 3 | 0.10 M, 0.15 M, 0.20 M |
| 약산-강염기 | 3 | 0.10 M, 0.15 M, 0.20 M |
| 약산-약염기 | 3 | 0.10 M, 0.15 M, 0.20 M |

CSV에는 대략 다음 계열의 값이 들어 있다.

- 시간, 프레임 번호
- 주입량 또는 주입량으로 환산 가능한 값
- 일반 카메라 ROI의 RGB/HSV 평균값
- RGB/HSV 변화량
- 열화상 ROI의 평균/최대/최소/분포값
- raw thermal 요약값
- 적정 종류, 표준용액/시료 정보
- 이론 당량점 부피

중요한 점은 **25fps의 많은 행을 독립 실험 25개처럼 보지 않았다는 것**이다. 한 CSV 전체를 하나의 실험 run으로 보고, 각 run에서 당량점 부피 하나를 예측했다.

## 3. 머신러닝 문제 정의

처음에는 프레임별로 당량점까지 남은 부피를 회귀하는 방식도 생각할 수 있었지만, 실제 목적과 맞지 않았다. 그래서 현재 방식은 다음처럼 바꿨다.

1. 실험 CSV 하나를 하나의 run으로 본다.
2. run 내부에서 주입량-센서값 곡선을 만든다.
3. 색 변화, 열 변화, 색+열 융합 변화가 큰 지점을 당량점 후보로 뽑는다.
4. 각 후보 주변의 색/열/기울기/곡률/안정도 feature를 만든다.
5. 머신러닝 모델이 후보 중 실제 당량점에 가장 가까운 후보를 고른다.
6. 최종적으로 run 하나당 예측 당량점 부피 1개를 출력한다.

따라서 모델 평가는 “프레임별 정확도”가 아니라 **run-level 당량점 부피 오차**로 했다.

## 4. 입력 feature와 target

### 입력 feature

모델 입력으로 사용 가능한 값은 실험 중 실제로 측정하거나 계산할 수 있는 값이다.

- visible RGB 평균: `R_mean`, `G_mean`, `B_mean`
- visible HSV 평균: `H_mean`, `S_mean`, `V_mean`
- 색 변화량, HSV 변화량
- 열화상 ROI 평균/최대/최소/표준편차/분위수
- raw thermal ROI 분포 feature
- 색 변화 곡선의 기울기, 곡률, 전후 변화량
- 열 변화 곡선의 기울기, 곡률, 전후 변화량
- 후보 source: color, thermal, fusion
- 후보 점수, 후보 간 일치도, 후보 순위
- 주입량/현재 부피, run 진행 정보

여기서 **주입량/현재 부피는 정답 누수가 아니다.** 펌프가 일정 속도로 주입하고 앱이 녹화 시작 시간을 알고 있으므로, 실제 실험 중 수집 가능한 정보이다. 그래서 최종 모델에서는 사용하는 것이 맞다.

### target

정답 target은 이론 당량점 부피이다.

```text
actual_equivalence_volume_ml
```

하지만 이 값은 **학습 정답과 평가 기준으로만 사용**했다. 모델 입력 feature에는 넣지 않았다.

입력에서 제외한 대표적인 누수 위험 값은 다음과 같다.

- 이론 당량점 부피
- 실제 당량점과의 거리
- 예측 오차
- pH 이론값
- endpoint label 계열 값
- pKa 자체를 직접 정답처럼 쓰는 값

## 5. 학습/검증 방식

데이터가 적기 때문에 train/test를 무작위로 섞으면 결과가 과장될 수 있다. 그래서 같은 적정 종류 안에서 농도 하나를 빼고 검증하는 방식을 사용했다.

예를 들어 강산-강염기에서:

```text
0.10 M run을 테스트로 빼고, 0.15 M + 0.20 M으로 학습
0.15 M run을 테스트로 빼고, 0.10 M + 0.20 M으로 학습
0.20 M run을 테스트로 빼고, 0.10 M + 0.15 M으로 학습
```

이 방식을 각 적정 종류별로 반복했다. 즉, 타입별로 3개의 leave-one-run-out 검증 결과가 있다.

주의할 점은 타입별 run 수가 3개뿐이라는 것이다. 따라서 성공률은 다음처럼 거칠게만 나온다.

```text
0.000000 = 0/3 성공
0.333333 = 1/3 성공
0.666667 = 2/3 성공
1.000000 = 3/3 성공
```

그래서 성공률보다는 MAE, 상대오차, run별 예측값을 중심으로 해석하는 것이 더 정직하다.

## 6. 비교한 모델 feature set

여러 feature set을 비교했다.

| feature set | 의미 |
|---|---|
| `current_fusion` | 기존 색+열 융합 후보 모델 기준선 |
| `compact_plus` | current_fusion에 후보 간 일치도, 순위, 밀도 feature를 추가 |
| `compact_plus_no_progress` | 주입량/진행 정보 제거 후 sensor-only 후보 일치도만 확인하는 ablation |
| `thermal_basic` | 기본 열화상 feature 중심 |
| `thermal_expanded` | 열화상 분포 feature 확장 |
<!-- END SOURCE EXCERPT -->

