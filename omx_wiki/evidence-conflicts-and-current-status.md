---
title: "Evidence Conflicts and Current Status"
tags: ["충돌", "최신", "평가범위"]
created: 2026-09-10T11:13:02.552Z
updated: 2026-09-10T11:13:02.552Z
sources: []
links: ["chemistry-implementation-details.md", "detail-ml-boosting-september-01.md", "detailed-library.md", "ml-results-and-selection.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# Evidence Conflicts and Current Status

# 신규 독자를 위한 충돌·최신성 판정
## 어느 결과를 믿어야 하는가
위키는 원문을 보존하지만 모든 문장이 현행 상태는 아니다. 최신 날짜 하나만으로 모델·실험·배포를 묶지 않는다. 서로 다른 평가 목적의 결과는 동시에 존재한다.

### 0.30% 대 1.52% 대 13.39% 대 0.41%
- 0.30%: 8계열 후보 평가·집계 조합을 같은 12회에서 대규모 사후 선택한 값. 독립 성능 아님.
- 1.52%: 별도의 색상+열화상 입력군 개발 비교. 0.30% 평가기와 같은 모델이 아니다.
- 13.39%: 9월 XGBoost 후보 ranker의 run 제외·3시드 평균 MAPE. 다른 고정 평가 조건이다.
- 0.41%: LightGBM을 12회 전체로 학습한 뒤 동일 자료에 재적용한 오차. 검증 정확도 아님.
- 7월 지정 미지 시료 3회 LightGBM 예측농도 0.11062/0.11075/0.10408 M, CV3.51%; 기존 배포 모델 CV0.96%는 반복자료 변동 지표다. 실제 농도 미표정이므로 정확도 우열 아님. 근거는 [[detail-ml-boosting-september-01]].
앞선 요약의 '새 자료 전혀 없음'은 6월 12회 기반 컨설팅 재분석 범위에 한정해야 한다. 7월 3회 자료의 존재와 독립 참값 부재를 분리한다.

### 전체 1,185 테스트 / 최신 펌웨어
이는 8월 기록이다. 현재 STAGED_DOSING에는 RATE/V capability가 추가돼 있다. 4,174 byte 빌드 크기와 테스트 개수를 최신 모든 코드에 자동 적용하지 않는다.

### 25 fps
250개 저장 raw 입력 처리량과 실제 USB 카메라 캡처 속도는 다르다. 기존 습식 CSV를 재표본화해도 과거 센서 측정이 늘어나지 않는다.

### Android
README의 native library·bridge 구현, 실제 APK 빌드, USB live 성공, 섭씨 검증, Windows 기능 동등성은 다른 단계다. 오래된 README는 a/b/c/s/r, Windows 신형은 G/STEP/RATE/V를 말하므로 동일 펌웨어 호환을 확인해야 한다.

### 화학 계산
scientific_equilibrium_davies라는 설정명 자체는 모든 물질의 정확한 비이상 평형 해석 증거가 아니다. 현 chemistry.py에 25℃ 상수·참고 pKa 대입·약약 근사식 경로가 있다. 최신 웹 호출부를 확인하고 보고서 주장 범위를 제한한다.

### 문서와 배포
이 위키는 2026-09-10 로컬 파일 스냅샷이다. GitHub 및 Windows 배포를 새로 조회·실행한 것은 아니다. 물리시험·외부 검증·권한·릴리스 허가를 문서 문구에서 추론하지 않는다.
[[detailed-library]] / [[ml-results-and-selection]] / [[chemistry-implementation-details]]

