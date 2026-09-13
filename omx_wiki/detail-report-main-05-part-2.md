---
title: "detail-report-main-05-part-2"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:14:03.256Z
updated: 2026-09-10T11:14:03.256Z
sources: []
links: ["detail-report-main-05-part-2.md", "detail-report-main-05-part-3.md", "detail-report-main-05.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-report-main-05-part-2

원문 [docs/science_fair_report_national_formatted.md](../docs/science_fair_report_national_formatted.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-report-main-05]] / [[detail-report-main-05-part-2]] / [[detail-report-main-05-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
| 열화상 융합 이득 불확실·변환 0값 11행 | 일부 조건에서 오히려 오차 증가 | blank·접촉 온도 기준·결측 처리와 사전 고정 ablation 검증 |
| 미세 펄스 주입의 습식 검증 부족 | 명목상 0.0495 mL와 실제 토출량의 차이, 정지 지연·과주입량 불명 | 질량 또는 부피로 5스텝 토출량을 반복 측정하고 저위험 조건에서 최종 정지 부피 확인 |

## 4. 탐구의 의의

학교 적정에서 색과 겉보기 표면온도를 비접촉으로 측정하고 계산 주입량과 동기화하여 관찰·기록·추정·제어를 연결한 데 의의가 있다.

---

# Ⅴ. 결론 및 활용 방안

## 1. 결론

본 탐구에서는 학교 환경에서 제작한 시린지 펌프, 일반 카메라와 열화상 카메라를 하나의 기록 흐름으로 연결하고, 12회 습식 적정에서 1,822개 시계열 행을 저장하였다. 이전 센서 입력군 파이프라인에서 색상 전용과 색상·열화상 융합 모델의 개발자료 MAPE는 각각 1.55%와 1.52%로 비슷했고, 열화상 추가 후 오차는 7회 감소하고 5회 증가하여 일관된 향상을 확인하지 못하였다. 이후 구성한 현재 적정 종류 조건부 센서 시계열 모델은 현재 주입량·시간·진행률·미지 농도·이론 당량점을 입력하지 않고 MAE 0.078 mL, RMSE 0.091 mL, MAPE 0.30%를 보였다. 다만 2,030,370개 설정을 같은 12회 자료에서 사후 선택했고 후보 오라클과 일치하므로, 이 값은 새 시료의 독립 정확도가 아닌 개발자료 내부 결과이다. 별도 7월 동일 미지 시료 3회에는 6월 설정을 고정하여 적용했고 예측 농도의 변동계수는 0.96%였으나, 실제 농도를 표정하지 않아 정확도는 평가하지 않았다. 종말점 근처에서는 연속 주입을 멈추고 명목상 0.0495 mL의 5스텝 펄스와 0.50초 대기를 반복하도록 구현했지만, 실제 펄스 토출량과 습식 자동정지 정확성은 검증하지 않았다. 본 작품의 확인된 성과는 적정액 주입, 비접촉 관찰, 동기화 기록, 사후 당량점 추정과 안전한 제어 명령을 하나의 시제품으로 통합한 데 있으며, 실제 유량 반복성·표정한 용액의 조건별 반복 실험·새 시료 정확도 검증은 후속 과제로 남는다.

## 2. 활용 방안

1. **학교 적정 기록**: 색 변화 전후의 색·열화상·주입량을 다시 확인한다.
2. **지시약 비교**: 지시약별 색 변화 시점과 이론 당량점의 차이를 비교한다.
3. **센서 융합**: 같은 절차로 세 입력군의 기여도와 적용 범위를 비교한다.
4. **자동 제어 교육**: 측정·저장·머신러닝 판단·모터 제어의 연결을 학습한다.

---

# Ⅵ. 생성형 AI 활용 목적 및 범위

본 탐구에서는 생성형 AI를 프로그램 구조 검토, 코드 오류 원인 탐색, CSV 항목 점검, 분석 코드 작성 보조와 보고서 수치의 교차 확인에 활용하였다. AI의 제안은 원본 자료, 실행 결과와 실제 장치 동작을 확인한 뒤 선택적으로 사용하였다. 시린지 펌프 제작, 장치 조립, 시약 준비, 실제 적정과 원본 CSV 수집은 탐구자가 직접 수행했으며, 생성형 AI로 가상의 실험값을 만들거나 원본 측정값을 바꾸지 않았다.

**[표 15] 생성형 AI 활용 내역**

| 도구 | 모델·버전 | 활용 시기 | 활용 범위 | 주소 |
|---|---|---|---|---|
| OpenAI Codex | GPT-5.5 | 2026. 7. | 코드·자료 구조 점검, 분석 및 보고서 검토 보조 | https://openai.com/codex/ |

---

# Ⅶ. 참고문헌

1. IUPAC. “equivalence-point.” *Compendium of Chemical Terminology (Gold Book)*, 5th ed., 2025. https://doi.org/10.1351/goldbook.09042
2. IUPAC. “titration.” *Compendium of Chemical Terminology (Gold Book)*, 5th ed., 2025. https://doi.org/10.1351/goldbook.T06387
3. Siqueira, L. A., et al. “Accurate automatic titration procedure for low sharpness and dichroism in end point detection using digital movies as detection technique.” *Microchemical Journal*, 133, 593–599, 2017. https://doi.org/10.1016/j.microc.2017.04.041
4. Tan, S. W. B., Naraharisetti, P. K., Chin, S. K., & Lee, L. Y. “Simple Visual-Aided Automated Titration Using the Python Programming Language.” *Journal of Chemical Education*, 97(3), 850–854, 2020. https://doi.org/10.1021/acs.jchemed.9b00802
5. Alessio, K. O., et al. “Open source, low-cost device for thermometric titration with non-contact temperature measurement.” *Talanta*, 216, 120975, 2020. https://doi.org/10.1016/j.talanta.2020.120975
6. del Castillo-Santaella, T., Maldonado-Valderrama, J., & Fernández-Rodríguez, M. Á. “Autotitrator based on an Arduino Open Source Pump.” *HardwareX*, 15, e00464, 2023. https://doi.org/10.1016/j.ohx.2023.e00464
7. Olbemo, S. K., Sakai, Y., Takeuchi, M., & Tanaka, H. “Application of digital-movie-based flow colorimetry to hue-based end point detection of acid-base titration by feedback-based flow ratiometry using universal indicator.” *Analytical Sciences*, 41, 419–425, 2025. https://doi.org/10.1007/s44211-024-00712-6
<!-- END SOURCE EXCERPT -->

