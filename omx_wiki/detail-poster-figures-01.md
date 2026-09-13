---
title: "detail-poster-figures-01"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:26.108Z
updated: 2026-09-10T11:10:26.108Z
sources: []
links: ["detail-poster-figures-01.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-poster-figures-01

## 문서의 역할과 해석
기존 그래프 번호와 설명. 최신 평가 지표와 일치 여부 재확인.

원문: [docs/poster_visuals/README.txt](../docs/poster_visuals/README.txt)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-poster-figures-01]]

<!-- BEGIN SOURCE EXCERPT -->
포스터용 시각화 파일 목록

공통 스타일: Pretendard 폰트, 큰 제목/축 글자, 흰 배경, PNG 출력

주요 그림
01_all_runs_sensor_curves_grid.png	12개 실험 run 전체의 색 차이량과 열화상 변화. 수집 데이터만 표시하고 모델 예측값은 제외.
01c_all_runs_hue_thermal_grid.png	H 색상과 온도 변화만 남긴 포스터 권장 그림. 수집 데이터와 이론 당량점만 표시.
01b_all_runs_hsv_channels_grid.png	실제 HSV 성분 변화. S/V까지 확인할 때 사용하는 보조 그림. 모델 예측값은 제외.
02_type_mean_sensor_curves.png	적정 종류별 평균 H 색상과 온도 변화. 당량점 전후의 평균 경향 비교.
03_prediction_actual_vs_predicted.png	이론 당량점과 머신러닝 예측 당량점 산점도.
04_typewise_mae_bar.png	적정 종류별 MAE 비교. 강산-강염기 성능이 가장 안정적임을 보여줌.
05_model_algorithm_comparison.png	Ridge, KNN, Random Forest, Extra Trees 모델 비교. 최종 모델 선정 근거.
05b_model_algorithm_comparison_zoom.png	Ridge를 제외하고 주요 모델만 확대 비교. 포스터에는 이 그림이 더 읽기 쉬움.
06_run_signed_error_bars.png	12개 run별 예측 오차. 어느 조건에서 크게 틀렸는지 확인.
07_dataset_summary.png	데이터 구성 요약. 4종류, 3농도, 총 12개 run 구조 설명.

개별 run 그림
run_curves 폴더 안에 각 실험별 평활 색 변화/온도 변화 그래프 12개 저장.
session_5_strong_acid_strong_base_0.1M.png
session_6_strong_acid_strong_base_0.15M.png
session_4_strong_acid_strong_base_0.2M.png
session_11_strong_acid_weak_base_0.1M.png
session_12_strong_acid_weak_base_0.15M.png
session_13_strong_acid_weak_base_0.2M.png
session_7_weak_acid_strong_base_0.1M.png
session_8_weak_acid_strong_base_0.15M.png
session_9_weak_acid_strong_base_0.2M.png
session_14_weak_acid_weak_base_0.1M.png
session_15_weak_acid_weak_base_0.15M.png
session_16_weak_acid_weak_base_0.2M.png

추가 분석 그림
08_feature_importance_top10.png	최종 Extra Trees 모델에서 중요도가 높게 나온 입력값 상위 10개.
09_feature_set_mae_heatmap.png	입력 feature set별 MAE 히트맵. 색/열/주입량 조합과 sensor-only/no-progress 비교.
10_concentration_error_heatmap.png	적정 종류와 농도 조건별 예측 오차 히트맵.
11_actual_vs_predicted_grouped_bars.png	12개 실험별 이론 당량점과 ML 예측 당량점 부피 비교.
12_success_rate_summary.png	최종 모델의 허용오차별 성공률 요약.
13_sensor_ablation_overall.png	센서 조합과 주입량/진행 정보가 예측 성능에 미친 영향 비교.
<!-- END SOURCE EXCERPT -->

