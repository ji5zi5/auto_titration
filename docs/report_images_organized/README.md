# 전국과학전람회 보고서 이미지 정리

원본 DOCX는 수정하지 않았으며, 내부 이미지 22개를 추출한 뒤 내용과 사용 목적에 따라 재분류했다. 정리 폴더의 파일은 원본 추출본과 하드링크되어 추가 저장공간을 거의 사용하지 않는다.

## 폴더 구성

- `00_docx_original/`: DOCX에서 추출한 원래 파일명 보존본
- `01_system_experiment/`: 실험 장치·용액·반복 실험 사진
- `02_hardware_design/`: 부품·3D 모델·회로도
- `03_software_ui/`: Windows·Android 앱 화면
- `04_results_charts/`: 수동 적정·기준선·머신러닝·반복성 그래프
- `05_prior_research/`: 유사작품 검색 화면
- `06_additional_created_assets/`: DOCX에는 없거나 원본을 따로 보존한 추가 제작 이미지
- `90_review_outdated_injection_model/`: 현재 주입량 포함 1.27% 서사 등 최종 보고서에서 제외한 구버전 이미지
- `source_mapping.csv`: DOCX 파일명, 새 파일명, 출처 성격, 캡션과 사용 판단
- `organized_contact_sheet.jpg`: 전체 이미지 빠른 확인표

## 한눈에 보는 판단

- 본문 핵심: **15개**
- 본문 선택: **2개**
- 부록·세부: **4개**
- 교체 권장: **1개**

최종 보고서의 머신러닝 결과는 **현재 주입량을 제외한 색상+열화상 모델 MAPE 1.52%**를 기준으로 한다. `90_review_outdated_injection_model/`과 `docs/poster_assets/`의 1.27% 관련 이미지는 그대로 사용하지 않는다.

## DOCX 이미지 목록

| 원본 | 정리 파일 | 구분 | DOCX 그림 | 사용 | 내용/주의 |
|---|---|---|---|---|---|
| `image1.png` | `01_system_experiment/01_system_overview_three_views.png` | 직접 촬영 사진 합성 | 그림 1·2·17 | **본문 핵심** | 실제 적정 장치의 주입·일반 촬영·열화상 촬영을 한 장에 정리 — DOCX에서 세 번 재사용됨. 본문에서는 한 번만 크게 사용하고 이후에는 참조 권장 |
| `image2.png` | `02_hardware_design/02_syringe_pump_parts_overview.png` | 부품 이미지 합성 | 그림 5 | **교체 권장** | 시린지 펌프 제작 부품 목록 — 제품 사진 출처가 불명확할 수 있어 직접 촬영한 부품 사진이나 단순 아이콘 도식으로 교체 권장 |
| `image3.png` | `02_hardware_design/03_pump_3d_models_overview.png` | 직접 제작 3D 모델 합성 | 그림 6 | **본문 핵심** | 푸셔 블록·모터 홀더/가이드·주사기 고정대 3D 모델 — 세부 모델 그림 4~6을 묶는 대표 설계 그림 |
| `image4.png` | `02_hardware_design/04_pusher_block_3d_model.png` | 직접 제작 3D 모델 | 그림 7 | **부록/세부** | 푸셔 블록 3D 모델 — 그림 3과 일부 중복. 제작 과정 설명에서만 사용 |
| `image5.png` | `02_hardware_design/05_motor_holder_rail_3d_model.png` | 직접 제작 3D 모델 | 그림 8 | **부록/세부** | 스텝모터 홀더와 가이드 레일 3D 모델 — 그림 3과 일부 중복. 제작 과정 설명에서만 사용 |
| `image6.png` | `02_hardware_design/06_syringe_holder_3d_model.png` | 직접 제작 3D 모델 | 그림 9 | **부록/세부** | 주사기 고정대 3D 모델 — 세로로 좁은 이미지. 본문에서는 그림 3에 통합 가능 |
| `image7.png` | `02_hardware_design/07_arduino_a4988_stepper_circuit.png` | 직접 제작 회로도 | 그림 10 | **본문 핵심** | Arduino Uno·A4988·스텝모터 회로 — 배선과 전원 연결 설명에 사용 |
| `image8.png` | `01_system_experiment/08_completed_syringe_pump.png` | 직접 촬영 사진 | 그림 11 | **본문 핵심** | 조립 완료한 100 mL 시린지 펌프 — 프로젝트 원본 docs/report_assets/syringe_pump_completed.jpg와 동일 장면의 고해상도 PNG |
| `image9.png` | `03_software_ui/09_windows_dashboard_full.png` | 직접 개발 화면 캡처 | 그림 13 | **본문 선택** | Windows 통합 앱 전체 화면 — 얼굴이 포함되어 있으므로 공개 보고서 사용 전 초상 노출 확인 또는 카메라 영역 크롭 권장 |
| `image10.png` | `03_software_ui/10_windows_android_comparison.png` | 직접 개발 화면 합성 | 그림 15·30 | **본문 핵심** | Windows·Android 일반/열화상 화면 비교 — DOCX에서 두 번 재사용됨. 한 번만 사용하고 다른 위치에서는 참조. 얼굴 노출 확인 권장 |
| `image11.png` | `01_system_experiment/11_four_reagent_solutions.png` | 직접 촬영 사진 합성 | 그림 16 | **본문 핵심** | 염산·아세트산·수산화나트륨·암모니아수 용액 — 시약 제조와 실험 조건 설명에 사용 |
| `image12.png` | `01_system_experiment/12_phenolphthalein_titration_setup.png` | 직접 촬영 사진 | 그림 18 | **본문 핵심** | 페놀프탈레인 적정 실험 장치 — 프로젝트 원본 docs/report_assets/wet_titration_setup.jpg와 동일 장면 |
| `image13.png` | `01_system_experiment/13_btb_color_change_setup.png` | 직접 촬영 사진 | 그림 19 | **부록/탐색** | BTB 색 변화 확인 실험 — 최종 12회 실험의 핵심 지시약 표와 혼동될 수 있어 탐색 실험 또는 부록으로 명시 |
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
