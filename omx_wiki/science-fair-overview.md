---
title: "Science Fair Overview"
tags: ["전람회", "시작", "overview"]
created: 2026-09-10T11:05:01.679Z
updated: 2026-09-10T11:05:01.679Z
sources: []
links: ["chemistry-implementation-details.md", "code-and-data-atlas.md", "consultation-and-report.md", "detailed-library.md", "development-timeline-and-troubleshooting.md", "evidence-conflicts-and-current-status.md", "ml-results-and-selection.md", "pump-and-safety.md", "thermal-and-recording.md", "thermal-investigation-details.md", "windows-and-android.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# Science Fair Overview

# 전람회 프로젝트 전체 안내
정리일: 2026-09-10. 기존 저장소 문서와 대화에서 확인한 지식을 요약한 위키다. 이 날짜에 장치 시험이나 재학습을 새로 수행한 것은 아니다.

## 작품과 목적
작품명: 자격루에서 착안한 비접촉 스마트 자동 적정 장치(이전 명칭: 스마트 자동 적정 보조장치).
뷰렛 콕을 계속 조작하는 불편과 인적 오류를 줄이기 위해 시린지 펌프, 일반 영상, 열화상, 분석 앱을 통합했다. 자격루의 외형 복제가 아니라 일정 흐름·계량·자동 알림 개념을 적용했다.
관찰 종말점과 화학량론적 당량점은 다르다. 센서 변화로 당량점 후보 부피를 추정하고 표준용액 정보 및 시료 부피로 미지 농도를 환산하는 것이 목표다. pH는 직접 측정값이 아니라 화학 모델 계산값이다.

## 읽는 순서
1. [[windows-and-android]]: 실행·플랫폼·파일 위치
2. [[thermal-and-recording]]: 공식 온도변환과 센서 기록
3. [[pump-and-safety]]: 펌프·명령·미세 주입
4. [[ml-results-and-selection]]: 모델·평가·선택 편향
5. [[consultation-and-report]]: 컨설팅·보고서·남은 검증

## 변경 이력의 핵심
처음에는 자동정지 없이 연속 주입·데이터 수집을 목표로 했다. 이후 사용자가 선택형 자동정지를 요청해 추가했고, 기존 12회 습식 실험 이후 미세 펄스 주입 기능을 보강했다.
ROI는 YOLO·자동 마스크·클릭·올가미를 시험했으나 투명 비커에서 불안정했다. 실제 12회 실험은 일반 영상·열화상 ROI를 각각 사각형으로 고정했다.
초기 CSV 저장 누락 이후 미리보기와 기록 경로를 분리했다. 과거 자료가 소급해 25 fps가 되는 것은 아니다.

## 증거 규칙
코드 구현, 과거 테스트 기록, 실제 습식 측정, 모의 계산을 구분한다. 원본 CSV를 정정하거나 보간값을 새 측정으로 표현하지 않는다. 과거 수치·예전 APK·GitHub 배포가 현재 코드와 같다고 가정하지 않는다.
원본 대화 전체의 완전한 전사는 아니며 핵심 의사결정과 근거 파일을 찾아가는 지식 색인이다.
출처: docs/science_fair_report_national_formatted.md, docs/WINDOWS_CODEX_HANDOFF.md, docs/report_evidence_no_new_wet/4차컨설팅_반영요약.md.



## 상세판 안내 (2026-09-10 확장)
이전 6개 페이지는 빠른 요약이다. 생략 없는 상세 원문과 현재 코드 지도는 다음에서 읽는다.
- [[detailed-library]]: 34개 문서 본문 통합 서가
- [[evidence-conflicts-and-current-status]]: 9월 boosting·배포·과거 결과 충돌 구분
- [[chemistry-implementation-details]]
- [[thermal-investigation-details]]
- [[development-timeline-and-troubleshooting]]
- [[code-and-data-atlas]]

주의: 최초 요약의 모든 미검증 설명은 해당 시점/분석 범위 기준이다. 특히 9월 비교에서 언급한 7월 지정 미지시료 자료와 최근 RATE/V 저속단계는 상세판을 우선한다.
