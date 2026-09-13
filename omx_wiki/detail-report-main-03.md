---
title: "detail-report-main-03"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:23.769Z
updated: 2026-09-10T11:10:23.769Z
sources: []
links: ["detail-report-main-01.md", "detail-report-main-02.md", "detail-report-main-03-part-2.md", "detail-report-main-03-part-3.md", "detail-report-main-03.md", "detail-report-main-04.md", "detail-report-main-05.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-report-main-03

## 문서의 역할과 해석
보고서 주 원고 스냅샷. 추후 코드/실험/9월 분석과 자동 동기화되지 않음.

원문: [docs/science_fair_report_national_formatted.md](../docs/science_fair_report_national_formatted.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-report-main-01]] / [[detail-report-main-02]] / [[detail-report-main-03]] / [[detail-report-main-04]] / [[detail-report-main-05]]


분할 이어읽기: [[detail-report-main-03]] / [[detail-report-main-03-part-2]] / [[detail-report-main-03-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
![네 적정 종류의 대표 실험 신호](report_evidence_no_new_wet/comparison_visuals/00_representative_sensor_curves_by_type.png)

**그림 8.** 각 적정 종류의 0.15 M 대표 실험에서 기록한 색조와 겉보기 표면온도 변화.

종류별 평균 곡선과 대표 실험 곡선을 함께 보면 색 변화가 비교적 뚜렷한 조건과 열화상 변동이 큰 조건이 서로 달랐다. 따라서 한 센서의 고정 임계값보다 여러 특징을 함께 비교하는 분석이 필요하다고 판단하였다.

### 마. 소결론

12개 시간축 자료는 반응계별 신호와 기록 가능성을 비교하는 개발자료로 사용하였다. 각 종류·농도 조건이 한 번씩만 측정되어 반복성이나 재현성을 정량화할 수 없으므로, 이는 후속 습식 반복시험 항목으로 남겼다.
## 4. 심화 탐구 1: 머신러닝을 이용한 당량점 부피와 미지 농도 추정

### 가. 탐구 질문

비접촉으로 얻은 색과 열화상 특징만으로 당량점에 가까운 구간을 찾을 수 있는가? 머신러닝은 단순한 색 변화 또는 색·온도 임계값보다 당량점 부피 오차를 줄이는가? 또한 색상, 열화상, 두 신호의 융합 가운데 어떤 입력이 가장 효과적인가?

### 나. 분석 방법

분석 단위는 연속 프레임이 아니라 **CSV 한 파일에 해당하는 습식 실험 한 회**로 정하였다. 색상과 열화상 시계열에서 여러 시간 폭의 변화 후보를 만든 뒤, 실험 전에 알고 있는 적정 종류에 따라 후보 평가기를 선택하여 실험별 당량점 부피 하나를 산출하였다. 입력은 색상·열화상 센서 특징과 적정 종류뿐이며, 현재 주입량, 시료 농도, 이론 당량점, 시간, 진행률, 최종 주입량, 전체 실험 길이와 지시약은 최종 모델 입력에서 제외하였다.

평가 실험 하나를 후보 평가기의 학습과 스케일링에서 제외하는 outer leave-one-run-out 방식을 사용하였다. 초기 공통 회귀 실험에서는 Ridge, KNN, Random Forest, Extra Trees를 같은 특징 구성에서 비교하였다. 이후 센서 변화 후보를 직접 평가하는 단계에서는 PLS, 선형 판별분석(LDA), 이차 판별분석(QDA), prototype, pairwise ridge, RBF 커널 릿지, 2차 커널 릿지, RBF SVR의 여덟 알고리즘 계열과 후보 점수의 정규화·집계 방법을 탐색하였다. 초기 공통 회귀와 최종 후보 평가 방식은 특징 표현과 탐색 범위가 다르므로 두 단계의 오차를 같은 조건의 순위처럼 직접 비교하지 않았다. 최종적으로 강산-강염기는 PLS, 강산-약염기는 RBF 커널 릿지, 약산-강염기는 LDA, 약산-약염기는 QDA가 선택되었다.

다만 후보 생성과 최종 설정 선택에는 같은 12회 자료의 정답이 사용되었다. 초기 1,006,020개와 추가 1,024,350개를 합친 **2,030,370개 설정**을 같은 자료에서 비교했고, 선택 결과의 MAPE가 후보 오라클과 같았다. 따라서 아래 결과는 평가 실험을 평가기 학습에서 제외한 값이지만, 설정 선택 편향이 남아 있는 **사후 개발자료 결과**이다. 새로 조제한 미지 시료에서 확인한 독립 정확도가 아니다.

센서 자체의 기여도는 현재 주입량을 제외한 색상 전용, 열화상 전용, 색상+열화상 모델을 별도로 비교하였다. 또한 같은 12개 CSV에 색 최대 기울기와 색·온도 임계값 규칙을 적용하였다. 수동 적정 기록은 최종 원자료 파일의 12개 값을 재계산하되, 자동 방식과 판독법·검증 구조가 달라 참고 비교로만 사용하였다.

![당량점 부피 추정 과정](report_assets/ml_pipeline.png)

**그림 9.** 색상·열화상 시계열에서 후보를 만들고, 적정 종류별 평가기로 실험별 당량점 부피 하나를 정하는 과정.

![탐색 알고리즘 계열과 선택 결과](report_evidence_no_new_wet/comparison_visuals/03_advanced_family_selection_map.png)

**그림 10.** 후보 평가 단계에서 탐색한 여덟 알고리즘 계열과 적정 종류별 최종 선택 결과. 이 그림은 탐색 범위를 보여주며 서로 다른 계열의 전체 MAPE 순위를 뜻하지 않는다.

![적정 종류별 선택 평가기와 오차](report_evidence_no_new_wet/comparison_visuals/02_selected_evaluator_by_type.png)

**그림 11.** 네 적정 종류에서 선택된 평가기와 종류별 개발자료 MAPE. 종류마다 신호 변화 형태가 달라 서로 다른 평가기가 선택되었다.

평가에는 평균 절대편차(MAE), 평균 제곱근편차(RMSE), 평균 절대백분율편차(MAPE)를 사용하였다.

\[
MAE=\frac{1}{N}\sum_{i=1}^{N}|V_i-\hat{V}_i|
\]

\[
RMSE=\sqrt{\frac{1}{N}\sum_{i=1}^{N}(V_i-\hat{V}_i)^2}
\]

\[
MAPE=\frac{100}{N}\sum_{i=1}^{N}\left|\frac{V_i-\hat{V}_i}{V_i}\right|
\]

여기서 \(V_i\)는 이론 당량점 부피, \(\hat{V}_i\)는 모델의 추정 부피이다.

### 다. 분석 결과

<!-- END SOURCE EXCERPT -->

