---
title: "detail-report-image-map-01-part-2"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:14:05.309Z
updated: 2026-09-10T11:14:05.309Z
sources: []
links: ["detail-report-image-map-01-part-2.md", "detail-report-image-map-01.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-report-image-map-01-part-2

원문 [docs/report_images_organized/README.md](../docs/report_images_organized/README.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-report-image-map-01]] / [[detail-report-image-map-01-part-2]]
<!-- BEGIN SOURCE EXCERPT -->
| `image14.png` | `04_results_charts/14_manual_reference_vs_endpoint.png` | 직접 생성 데이터 그래프 | 그림 20 | **본문 핵심** | 수동 적정 기준 당량점과 관찰 종말점 비교 — 수동 적정 12회 결과 |
| `image15.png` | `04_results_charts/15_manual_signed_error.png` | 직접 생성 데이터 그래프 | 그림 21 | **본문 핵심** | 수동 적정 조건별 부호 오차 — 오차 방향과 편향 확인 |
| `image16.png` | `04_results_charts/16_manual_vs_smart_mae_rmse.png` | 직접 생성 데이터 그래프 | 그림 22 | **본문 핵심** | 수동 적정과 스마트 적정기의 MAE·RMSE 비교 — 수동 1.22%와 ML 융합 1.52% 해석 문단에 사용 |
| `image17.png` | `04_results_charts/17_endpoint_method_mape.png` | 직접 생성 데이터 그래프 | 그림 23·25 | **본문 핵심** | 비ML 두 방식과 ML 세 입력군의 MAPE 비교 — DOCX에서 같은 그림을 두 번 사용함. 최종 보고서에서는 한 번만 배치 |
| `image18.png` | `04_results_charts/18_fusion_actual_vs_predicted.png` | 직접 생성 데이터 그래프 | 그림 26 | **본문 핵심** | 이론 당량점과 색상·열화상 융합 모델 추정값 비교 — 최종 센서 융합 모델 MAPE 1.52% 결과 |
| `image19.png` | `04_results_charts/19_ml_modality_overall.png` | 직접 생성 데이터 그래프 | 그림 27 | **본문 핵심** | 색상·열화상·융합 모델 전체 성능 — 현재 주입량을 제외한 세 모델 비교 |
| `image20.png` | `04_results_charts/20_fusion_mape_by_titration_type.png` | 직접 생성 데이터 그래프 | 그림 28 | **본문 핵심** | 적정 종류별 융합 모델 MAPE — 약산-강염기 성능 저하를 보여주는 핵심 결과 |
| `image21.png` | `04_results_charts/21_repeatability_three_runs.png` | 직접 생성 데이터 그래프 | 그림 29 | **본문 핵심** | 동일 용액 3회 반복 측정 환산 농도 — 평균 0.0855 M, 변동계수 3.85% |
| `image22.png` | `05_prior_research/22_prior_work_search_composite.png` | 직접 캡처 화면 합성 | 그림 31 | **본문 선택** | 과학전람회 DB와 RISS 유사작품 검색 — 원본 캡처 두 장을 별도로 보관. 검색일과 URL/검색어를 본문에 함께 기록 권장 |

## 최종 본문 권장 순서

1. 전체 탐구 흐름 (`06_additional_created_assets/research_flow.png`)
2. 전체 장치와 촬영 구성 (`01_system_experiment/01_system_overview_three_views.png`)
3. 하드웨어 설계 개요 (`02_hardware_design/03_pump_3d_models_overview.png`)
4. 회로와 완성 장치 (`02_hardware_design/07_arduino_a4988_stepper_circuit.png`, `01_system_experiment/08_completed_syringe_pump.png`)
5. Windows·Android 수집 화면 (`03_software_ui/10_windows_android_comparison.png`)
6. 실험 용액과 실제 적정 (`01_system_experiment/11_four_reagent_solutions.png`, `01_system_experiment/12_phenolphthalein_titration_setup.png`)
7. 수동 적정 결과 (`04_results_charts/14_...`~`16_...`)
8. 머신러닝 효과와 비ML 기준선 (`04_results_charts/17_endpoint_method_mape.png`)
9. 융합 모델 결과 (`04_results_charts/18_...`~`20_...`)
10. 동일 용액 반복성 (`04_results_charts/21_repeatability_three_runs.png`)
11. 유사작품 검색 (`05_prior_research/22_prior_work_search_composite.png`)

## 중복·주의 사항

- `image1`은 DOCX에서 그림 1·2·17로 세 번 쓰였으므로 최종본에서는 한 번만 배치한다.
- `image10`은 그림 15·30으로 중복 사용되었다. 앱 개발 부분에서 한 번만 사용한다.
- `image17`은 그림 23·25로 중복 사용되었다. 머신러닝 비교 절에서 한 번만 사용한다.
- `image4`~`image6`은 `image3`의 세부 확대본이다. 본문 분량이 부족하면 부록으로 이동한다.
- `image13`의 BTB 실험은 최종 12회 실험 조건과 구분하여 탐색 실험으로 표시한다.
- `image2`의 제품 사진은 출처가 불명확할 수 있어 직접 촬영 부품 사진으로 교체하는 편이 안전하다.
- 앱 화면에는 얼굴이 포함되어 있다. 공개 제출본에서는 사용 동의를 확인하거나 영상 영역을 크롭한다.

## 추가 제작 이미지

`06_additional_created_assets/`에는 연구 흐름, 실험 행렬, 데이터 흐름, 자동 정지 상태도와 원본 사진·검색 화면을 모았다. DOCX에서 빠진 제작 과정 설명을 복원할 때 우선 사용한다.

## 보류 이미지

`90_review_outdated_injection_model/`에는 현재 주입량을 포함한 1.27% 결과를 중심으로 만든 구버전 그림을 모았다. 파일은 삭제하지 않았지만, 현재 최종 서사에는 사용하지 않는다. `docs/poster_visuals/`도 모델 결과가 여러 버전이 섞여 있어 별도 검토 전까지 자동 삽입하지 않는다.
<!-- END SOURCE EXCERPT -->

