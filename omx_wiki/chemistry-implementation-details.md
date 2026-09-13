---
title: "Chemistry Implementation Details"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:13:02.904Z
updated: 2026-09-10T11:13:02.904Z
sources: []
links: ["code-and-data-atlas.md", "detail-prediction-readiness-01.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# Chemistry Implementation Details

# 농도·pH·해리상수 구현 해설
## 주어진 정보와 출력
표준용액 물질·농도, 미지 시료 물질·부피 및 반응 가수는 실험 전에 알려진다. 시료의 참 농도는 예측 시 알 수 없는 값이다. 학습 실험에서는 명목 농도를 별도로 라벨 계산에만 쓴다.
동일 부피 단위를 쓰면 n_s C_s V_s=n_t C_t V_eq. 따라서 C_s=n_t C_t V_eq/(n_s V_s). 약산이라는 이유만으로 당량 관계가 사라지지는 않지만 어떤 단계의 반응 당량인지와 반응 완결성은 모델 범위에 종속된다.

## 코드별 책임
- auto_titrator/chemistry.py: calculate_equivalence_volume_ml, calculate_unknown_sample_concentration_m, calculate_unknown_titrant_concentration_m, generate_theoretical_ph_curve, davies_activity_coefficient.
- auto_titrator/chemical_constants.py: IupacPkaDatabase.lookup, pKa 문구 파싱, 후보 품질/온도/물질 일치 정렬. 후보 모호성·출처를 보존한다.
- auto_titrator/indicator_models.py: 지시약 preset, 변색 pH 하한·상한에 해당하는 곡선 교차 부피 및 신뢰도.
- auto_titrator/experiment_config.py: 물질·농도·상수 출처·선택 해리 단계·지시약·활동도 메타데이터.

## 확인된 계산 경계
Davies 함수의 temperature_c 인자는 있어도 구현은 25℃ A 상수를 사용한다고 docstring에 명시한다. 전하 z와 이온세기 I에서 log10(gamma)=-A z²(sqrt(I)/(1+sqrt(I))-0.3I)를 계산한다. 이를 모든 농도·온도에서 정확하다고 표현하지 않는다.
_estimate_equivalence_ph에는 강강7.0, 약강 짝염기 가수분해, 강약 짝산 가수분해, 약약7+0.5(pKb-pKa)의 참고 계산이 있다. pKa/pKb 누락 시 아세트산4.76/암모니아4.75를 placeholder로 넣고 경고하는 경로도 있다.
그러므로 사용자의 '근사 없이 모든 물질'은 목표이지 현 구현 보증이 아니다. IUPAC 데이터가 있어도 혼합물·다단계·농후용액·온도의존 평형까지 자동 해결되는 것은 아니다.

## 웹 예측을 읽는 법
입력 이론 농도와 실제 예측 농도를 혼동한 버그 이력이 있다. 예측 부피가 생긴 뒤 표준용액 농도와 시료 부피로 역산해야 한다. pH도 예측 농도에서 계산한 모델 pH인지 이론 입력을 재사용했는지 확인한다.
현 예측 준비조건은 최소8개 사용가능 관측, 3초 시간폭, 양의 부피진행, 비평탄 센서 등이다. 화학적 종말점 도달의 증명은 아니며 상태 pending/available/withheld/unavailable을 구분한다.
[[detail-prediction-readiness-01]] / [[code-and-data-atlas]] / [[detailed-library]]

