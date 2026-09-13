---
title: "detail-ml-protocol-01"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:19.824Z
updated: 2026-09-10T11:10:19.824Z
sources: []
links: ["detail-ml-protocol-01.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-ml-protocol-01

## 문서의 역할과 해석
프로토콜 보정 포함 과거 결과. 센서만의 일반화 성능과 구분.

원문: [docs/ml_protocol_calibrated_mape_under_5.md](../docs/ml_protocol_calibrated_mape_under_5.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-ml-protocol-01]]

<!-- BEGIN SOURCE EXCERPT -->
# MAPE 5% 이내 프로토콜 보정 모델 결과

현재 12개 CSV만으로 센서-only 모델은 5% 이내에 도달하지 못했지만, 실험 종료 후 확인 가능한 최대 주입량을 사용하는 비엄격 프로토콜 보정 모델은 nested 검증에서 MAPE 5% 이내에 도달하였다.
이 모델은 각 적정 종류에서 남은 두 농도 실험으로 `최대 주입량 -> 당량점 부피` 선형 보정을 만들고, held-out run이 학습 최대 주입량 범위 밖이면 ratio 보정으로 일부 shrink한다.
shrink 비율 alpha는 바깥 테스트 run을 제외한 나머지 run에서 nested leave-one-run-out으로 고른다.
따라서 정답 부피를 held-out 입력으로 직접 넣지는 않지만, 최종 최대 주입량을 쓰므로 실시간 센서-only 성능이 아니라 post-experiment/protocol-assisted 성능이다.

## 전체 성능
| 모델 | MAE mL | RMSE mL | MAPE | 5% 이내 달성 | 비고 |
|---|---:|---:|---:|---|---|
| nested_protocol_calibrated_max_volume | 1.250516 | 1.680475 | 4.981% | yes | alpha selected by nested leave-one-run-out; protocol-assisted |
| fixed_alpha_0p25_protocol_calibrated | 1.229952 | 1.666120 | 4.906% | yes | fixed alpha=0.25 exploratory reference; protocol-assisted |

## 적정 종류별 성능
| 모델 | 적정 종류 | MAE mL | MAPE |
|---|---|---:|---:|
| nested_protocol_calibrated_max_volume | strong_acid_strong_base | 0.188377 | 0.669% |
| nested_protocol_calibrated_max_volume | strong_acid_weak_base | 2.644026 | 9.599% |
| nested_protocol_calibrated_max_volume | weak_acid_strong_base | 1.063292 | 4.733% |
| nested_protocol_calibrated_max_volume | weak_acid_weak_base | 1.106368 | 4.923% |
| fixed_alpha_0p25_protocol_calibrated | strong_acid_strong_base | 0.188377 | 0.669% |
| fixed_alpha_0p25_protocol_calibrated | strong_acid_weak_base | 2.627263 | 9.510% |
| fixed_alpha_0p25_protocol_calibrated | weak_acid_strong_base | 0.997798 | 4.521% |
| fixed_alpha_0p25_protocol_calibrated | weak_acid_weak_base | 1.106368 | 4.923% |

## 오차가 큰 run
| 적정 종류 | 농도 | 실제 mL | 예측 mL | 오차 mL | 오차 % | alpha | mode |
|---|---:|---:|---:|---:|---:|---:|---|
| strong_acid_weak_base | 0.10 | 20.000 | 17.008 | 2.992 | 14.96% | 0.24 | outside_range_blend_linear_ratio |
| weak_acid_weak_base | 0.10 | 20.000 | 22.295 | 2.295 | 11.48% | 0.25 | outside_range_blend_linear_ratio |
| weak_acid_strong_base | 0.10 | 20.000 | 22.227 | 2.227 | 11.14% | 0.27 | outside_range_blend_linear_ratio |
| strong_acid_weak_base | 0.20 | 40.000 | 36.842 | 3.158 | 7.90% | 0.24 | outside_range_blend_linear_ratio |
| strong_acid_weak_base | 0.15 | 30.000 | 31.781 | 1.781 | 5.94% | 0.24 | inside_range_linear |
| weak_acid_weak_base | 0.15 | 30.000 | 29.120 | 0.880 | 2.93% | 0.25 | inside_range_linear |

## 보고서용 해석
- 5% 이내 결과는 센서-only 머신러닝이 아니라, 주입 프로토콜 정보까지 포함한 보정 모델에서 달성되었다.
- 이 결과는 실험 종료 후 전체 주입 범위를 알 수 있을 때 유효하며, 실시간 자동 정지 성능으로 해석하면 안 된다.
- 그래도 펌프 주입량 기록이 당량점 예측 정확도 개선에 매우 크게 기여한다는 근거로 사용할 수 있다.
<!-- END SOURCE EXCERPT -->

