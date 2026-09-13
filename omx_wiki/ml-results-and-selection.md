---
title: "ML Results and Selection"
tags: ["머신러닝", "MAPE", "PLS", "LDA", "QDA", "선택편향"]
created: 2026-09-10T11:05:03.108Z
updated: 2026-09-10T11:05:03.108Z
sources: []
links: ["consultation-and-report.md", "thermal-and-recording.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# ML Results and Selection

# 머신러닝 결과와 모델 선정
## 자료와 학습 목표
네 적정 종류(강강/강약/약강/약약), 시료 농도 0.10/0.15/0.20 M, 조건별 1회로 12개 CSV·1,822행. 명목 이론 부피 20/30/40 mL. 독립 단위는 프레임이 아닌 실험 파일이다. 새 실험 없이 분석을 확장했다.
초기 목표는 이론 당량점 주변 ±0.5 mL 분류와 거리 예측. 이후 실험별 당량점 부피 하나를 선택하는 후보 평가로 발전했다. 이론값은 실제 독립 측정 당량점과 동일하다고 보장되지 않는다.

## 최신 문서의 센서 후보 평가
최신 탐색 8계열: PLS, LDA, QDA, prototype 거리법, pairwise ridge, RBF kernel ridge, polynomial2 kernel ridge, RBF-SVR.
1,242개 평가 사양, 정규화·가중치·81개 집계 방식으로 1,006,020 조합. 이후 조밀 집계 1,024,350 조합. 총 2,030,370은 알고리즘 개수가 아니라 설정 조합 수다.
최종 개발자료 선택: 강강 PLS, 강약 RBF kernel ridge, 약강 LDA(전역0.64/동일종류0.36, 상위26 집계), 약약 QDA(상위5 집계).
개발자료 MAE 0.078 mL, RMSE 0.091 mL, MAPE 0.295000%(보고서 0.30%). 평가 run은 모델 적합·스케일링에서 제외했지만 최종 설정 선택은 같은 12개 결과를 사용했다. 후보 오라클과 같으므로 강한 사후 선택 편향이 있다. 독립 정확도·실시간 자동정지 성능으로 제시하지 않는다.
추론 특징에서 현재 주입량·시간·진행률·미지농도·이론값·지시약 제외. 적정 종류는 알려진 조건이다. 선택 시점을 부피로 환산할 때 부피를 쓰는 것과 모델 특징 입력은 구별한다. 전체 시계열/말단 특징을 쓰는 사후 모델을 인과적 실시간 모델로 혼동하지 않는다.

## 다른 결과와 혼동 금지
색상 개발 MAPE1.552%, 열화상3.662%, 융합1.524%는 별도 입력군 분류 비교다. 과거 대화의 1.27%, 0.47%, 4.98%, 8.81% 등은 서로 다른 탐색·입력·선택 조건의 결과로 최신 단일 성능이 아니다.
이전 코드에는 Ridge/KNN/RF/ET 분류·회귀, Logistic, SVM, boosting 등의 예비 탐색도 있다. 코드에 선택지가 존재하는 것과 실제 실행 결과가 남은 것은 구분한다.
프레임 이동/확인지연 보정은 바깥 실험 제외 선택에서 악화되어 기각. 출처·방향 특징 확장도 악화. 3개 seed 동일 결과는 결정론적 재실행이지 일반화 증거가 아니다.

## 근거
- docs/report_evidence_no_new_wet/model_search_audit/README.md
- 같은 폴더 advanced_ranker_search/summary.json 및 dense_aggregation_search/
- tools/search_advanced_type_conditioned_sensor_rankers.py
- docs/science_fair_report_national_formatted.md
배포 앱 모델이 위 사후 모델과 동일한지는 실행 경로·모델 파일 해시를 따로 확인한다.
관련: [[consultation-and-report]], [[thermal-and-recording]].

