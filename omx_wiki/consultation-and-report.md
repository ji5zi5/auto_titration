---
title: "Consultation and Report"
tags: ["컨설팅", "보고서", "포스터", "검증", "남은일"]
created: 2026-09-10T11:05:03.475Z
updated: 2026-09-10T11:05:03.475Z
sources: []
links: ["ml-results-and-selection.md", "pump-and-safety.md", "science-fair-overview.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# Consultation and Report

# 컨설팅 반영·보고서·남은 일
## 최신 문서와 산출물
주 원고 docs/science_fair_report_national_formatted.md.
HWPX: docs/제72회_작품설명서_자동생성검토본.hwpx 및 개인정보삭제_자동생성검토본.hwpx.
생성기 tools/build_national_report_hwpx.py. 한글 렌더러로 쪽수·표 잘림·개인정보를 최종 확인하는 작업은 별도다.
docs/report_evidence_no_new_wet/에 반영요약, 교체문안, 표_및_그림_캡션, claim_source_manifest.csv, 모델탐색 감사 기록이 있다.
그림: docs/poster_visuals/01c_all_runs_hue_thermal_grid.png, docs/report_evidence_no_new_wet/figures/의 이론-예측 산점도·조건별 APE·종류별 MAPE·방법별 MAPE.
사용자 선호: Pretendard 큰 글씨, 포스터 문장 짧게, 소목차당 1~2문장, 표 꼭 필요할 때만, 수집 그래프와 예측 결과 분리, H와 온도 중심. TXT 산출 선호. 보고서는 과장보다 기능·근거가 명확해야 한다.

## 4차 컨설팅
PDF 제목: [화학]서면컨설팅 보고서(4차)_1245_자격루에서 착안한 비접촉 스마트 자동 적정 장치.pdf.
요구: 유량 정밀도/재현성, 피스톤 위치 마찰, 종말점 미세 주입, 열화상 기여와 S/N, 독립 실험 부족.
최신 재분석은 초기 대화의 국소 S/N≈1.02와 구분한다. 운영적 대비도는 기저 0.05≤V/Veq≤0.20, 종말점 0.95≤V/Veq≤1.05, 중앙값 차이/1.4826 MAD. 장비 물리 S/N 또는 검출한계가 아니다. 이론 부피는 사후 분석 구간 정의용이며 추론 입력과 다르다.
ROI 요약 모두 0인 11행을 주 대비도 분석에서 제외. 이것이 모든 ML 학습의 전처리까지 수정됐다는 의미는 아니다.
색상 APE-융합 APE 평균 0.0275599%p, 종류 층화 100,000회 bootstrap 95%구간 [-1.204831,1.147784]%p. 7개 개선/5개 악화, 부호 뒤집기 p=0.978027. 융합 우수성이나 동등성은 확립되지 않았다.
수동 자료 MAE0.642 mL/RMSE0.750 mL/MAPE2.00%. 모델과 판독·검증 구조가 달라 직접 우열 근거가 아니다.
약약 지시약은 수행자 사후 확인 BTB지만 원 CSV methyl_orange와 상충한다. 원본 수정 없이 미독립검증 정정으로 표시한다.

## 아직 안 된 것
실제 펄스당 부피·위치별 반복성·정지 후 추가 토출량, blank/접촉식 온도계 검증, 새 조제 배치 독립 일반화, 실제 25fps 장시간 장치 시험은 별도 필요하다.
중첩 CV 30시드·순수 센서 ablation·가상 교란 등 초기 권고안의 모든 항목을 완료했다고 간주하지 않는다. 산출물과 실행 기록 없는 제안은 미완료다.
보고서에서는 물리 측정/소프트웨어 검증/모의 계산/미검증을 나눠 쓴다. 테스트 개수는 해당 시점 실행 기록이며 미래 코드의 보증이 아니다.
관련: [[ml-results-and-selection]], [[pump-and-safety]], [[science-fair-overview]].

