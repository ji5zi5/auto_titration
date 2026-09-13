---
title: "Detailed Library"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:27.098Z
updated: 2026-09-10T11:10:27.098Z
sources: []
links: ["chemistry-implementation-details.md", "code-and-data-atlas.md", "detail-android-reverse-engineering-01.md", "detail-android-runtime-01.md", "detail-app-development-01.md", "detail-app-development-02.md", "detail-app-development-03.md", "detail-auto-stop-01.md", "detail-auto-stop-02.md", "detail-consultation-four-01.md", "detail-indicator-correction-01.md", "detail-ml-12-runs-01.md", "detail-ml-boosting-september-01.md", "detail-ml-current-volume-01.md", "detail-ml-curve-01.md", "detail-ml-detailed-01.md", "detail-ml-detailed-02.md", "detail-ml-final-candidates-01.md", "detail-ml-injection-01.md", "detail-ml-maximize-01.md", "detail-ml-posthoc-01.md", "detail-ml-progress-01.md", "detail-ml-protocol-01.md", "detail-ml-selection-audit-01.md", "detail-ml-zoo-01.md", "detail-mobile-companion-01.md", "detail-performance-01.md", "detail-poster-figures-01.md", "detail-prediction-readiness-01.md", "detail-project-status-01.md", "detail-project-status-02.md", "detail-project-status-03.md", "detail-project-status-04.md", "detail-pulse-replay-01.md", "detail-report-captions-01.md", "detail-report-image-map-01.md", "detail-report-main-01.md", "detail-report-main-02.md", "detail-report-main-03.md", "detail-report-main-04.md", "detail-report-main-05.md", "detail-report-replacement-01.md", "detail-report-submission-01.md", "detail-revision-figures-01.md", "detail-site-validation-01.md", "detail-staged-dosing-01.md", "detail-windows-handoff-01.md", "detail-windows-handoff-02.md", "detail-windows-handoff-03.md", "development-timeline-and-troubleshooting.md", "evidence-conflicts-and-current-status.md", "science-fair-overview.md", "thermal-investigation-details.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# Detailed Library

# 상세 원문 통합 서가
요약에 생략된 개발·실험·모델·보고서 세부사항을 직접 읽는 공간이다. 큰 문서는 분할했고 내용은 생략하지 않았다. 사진·DLL·CSV 등 바이너리/대용량 원자료는 복제하지 않고 원래 위치를 유지한다.
원문 보존 페이지는 이력이다. 모든 옛 문장을 현재 사실로 승인한 것이 아니다.

[[science-fair-overview]] / [[evidence-conflicts-and-current-status]] / [[code-and-data-atlas]] / [[chemistry-implementation-details]] / [[thermal-investigation-details]] / [[development-timeline-and-troubleshooting]]

## 주제별 상세 문서
- **windows-handoff** — 운영 인수인계 이력. 날짜·배포 경로는 실행본과 재확인.
  [[detail-windows-handoff-01]], [[detail-windows-handoff-02]], [[detail-windows-handoff-03]]

- **project-status** — 통합 현황 원문. 작성시점이 다른 단락과 완료/미완료 표현을 구별.
  [[detail-project-status-01]], [[detail-project-status-02]], [[detail-project-status-03]], [[detail-project-status-04]]

- **prediction-readiness** — 최종 예측 가용성 계약과 배포 모델 연결. 이론값으로 준비상태를 통과시키지 않음.
  [[detail-prediction-readiness-01]]

- **site-validation** — 사이트 수정 시점의 검증 기록. 현재 하드웨어 재시험 결과 아님.
  [[detail-site-validation-01]]

- **performance** — 저장 raw 및 처리경로 벤치마크. 실제 USB 장시간 습식 성능과 별개.
  [[detail-performance-01]]

- **auto-stop** — 건식 제어 시험·미세 주입·안전성 및 습식 검증 공백.
  [[detail-auto-stop-01]], [[detail-auto-stop-02]]

- **staged-dosing** — 선택형 고속→저속→펄스 단계. 기본 기능과 펌웨어 capability 계약 구별.
  [[detail-staged-dosing-01]]

- **android-runtime** — Android 개발 구조. Celsius가 검증 전 차단되는 조건 및 Windows와 다른 명령 계약 확인.
  [[detail-android-runtime-01]]

- **android-reverse-engineering** — 공식 APK 정적 분석 이력. 라이브러리 존재와 실제 전화기 변환 성공은 별개.
  [[detail-android-reverse-engineering-01]]

- **mobile-companion** — 과거 companion 구성. 현재 phone-local 구조와 혼동 금지.
  [[detail-mobile-companion-01]]

- **ml-curve** — 과거 curve 후보 회귀 탐색. 현행 배포 정확도 아님.
  [[detail-ml-curve-01]]

- **ml-detailed** — 과거 상세 ML 결과. 입력·검증 조건을 함께 보존.
  [[detail-ml-detailed-01]], [[detail-ml-detailed-02]]

- **ml-12-runs** — 과거 12회 예측표. 최신 표로 임의 대체하지 않음.
  [[detail-ml-12-runs-01]]

- **ml-zoo** — 모델 zoo 탐색 이력.
  [[detail-ml-zoo-01]]

- **ml-progress** — 진행률을 사용한 과거 비교. 현재 진행률 금지 요구와 구분.
  [[detail-ml-progress-01]]

- **ml-current-volume** — 현재 부피 허용/진행률 제외 단계의 모델 기록.
  [[detail-ml-current-volume-01]]

- **ml-posthoc** — 종류별 사후 모델 선택 이력. 독립 평가로 제시 금지.
  [[detail-ml-posthoc-01]]

- **ml-injection** — 주입량 유무 비교. 프로토콜과 특징 구성이 다르면 직접 비교 제한.
  [[detail-ml-injection-01]]

- **ml-protocol** — 프로토콜 보정 포함 과거 결과. 센서만의 일반화 성능과 구분.
  [[detail-ml-protocol-01]]

- **ml-maximize** — 후보·집계 확장 탐색 이력.
  [[detail-ml-maximize-01]]

- **ml-boosting-september** — 9월 boosting 회귀·ranker·full-fit·7월 반복자료 평가. 각 수치 평가 범위 구별.
  [[detail-ml-boosting-september-01]]

- **ml-selection-audit** — 8계열 최종 후보 평가 및 사후 설정 선택의 제한.
  [[detail-ml-selection-audit-01]]

- **ml-final-candidates** — 0.30% 개발자료 선택 결과. 실시간 자동정지와 별개.
  [[detail-ml-final-candidates-01]]

- **consultation-four** — 4차 컨설팅 반영과 수정된 운영적 대비도·짝지은 검정.
  [[detail-consultation-four-01]]

- **report-replacement** — 보고서 교체 문안. 최신 근거 문맥과 같이 사용.
  [[detail-report-replacement-01]]

- **report-captions** — 표·그림 설명과 검증 한계.
  [[detail-report-captions-01]]

- **indicator-correction** — 원본 CSV 지시약과 사후 진술의 충돌. 원본 불변.
  [[detail-indicator-correction-01]]

- **pulse-replay** — 기존 CSV 반사실 재생. 변경 주입에 따른 실제 새 센서 반응을 측정한 것이 아님.
  [[detail-pulse-replay-01]]

- **report-main** — 보고서 주 원고 스냅샷. 추후 코드/실험/9월 분석과 자동 동기화되지 않음.
  [[detail-report-main-01]], [[detail-report-main-02]], [[detail-report-main-03]], [[detail-report-main-04]], [[detail-report-main-05]]

- **report-submission** — 제출 서식 및 한글 렌더링 확인 항목.
  [[detail-report-submission-01]]

- **app-development** — 앱 기능 설명 초안. 구현·UI·하드웨어 검증 주장에 작성시점 주의.
  [[detail-app-development-01]], [[detail-app-development-02]], [[detail-app-development-03]]

- **poster-figures** — 기존 그래프 번호와 설명. 최신 평가 지표와 일치 여부 재확인.
  [[detail-poster-figures-01]]

- **report-image-map** — 원본 사진과 보고서 삽입 자료 위치.
  [[detail-report-image-map-01]]

- **revision-figures** — 수정 보고서 그래프 묶음의 출처와 범위.
  [[detail-revision-figures-01]]
