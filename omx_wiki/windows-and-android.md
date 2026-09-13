---
title: "Windows and Android"
tags: ["windows", "android", "실행", "인수인계"]
created: 2026-09-10T11:05:01.999Z
updated: 2026-09-10T11:05:01.999Z
sources: []
links: ["pump-and-safety.md", "thermal-and-recording.md"]
category: architecture
confidence: medium
schemaVersion: 1
---

# Windows and Android

# Windows 및 Android
## Windows 실행
기존 인수인계 기준 실행 파일: launchers/windows/21_open_dashboard_server.bat.
대시보드 기본 주소 http://127.0.0.1:8765/ ; 수집기 기본 포트 8766. 실사용 주소는 실행 로그를 우선한다.
WSL 저장소 /home/jio/code/auto_titration. Windows 단일 작업 폴더는 인수인계 기준 C:\Users\Jio\Downloads\auto_titration. 이번 위키 작성에서 Windows 배포 상태·GitHub 릴리스·장치 연결은 확인하지 않았다.
사용자는 날짜별 프로젝트 복사본과 ZIP 남발을 원하지 않는다. 단일 작업 폴더를 유지한다.

## 구성과 기능
- tools/dashboard_server.py: 웹 서버·수집기 연결.
- tools/windows_live_collect.py: 카메라, 공식 온도변환 연결, ROI, 시리얼, CSV, 모델 연결.
- website/: 화면, 실험 조건, 녹화, 펌프 버튼, 센서값 표시.
- auto_titrator/: 화학 계산·센서·모델·제어 모듈.
농도·이론 당량점 계산, IUPAC pKa/pKb 선택, 활동도 및 pH 모델, 지시약 범위, CSV 기록을 개발했다. 각 경로의 실제 적용 여부는 최신 코드와 결과 필드를 확인해야 하며 표시 기능과 실시간 보정 실행을 혼동하지 않는다.
농도 예측 입력에 미지 농도·이론 정답을 넣으면 안 된다. 실험 학습 라벨용 입력과 추론 입력을 분리한다.

## Android 상태와 이전 시행착오
폰 단독 기본 카메라+USB Mini2+로컬 온도변환+펌프+CSV를 목표로 별도 개발했다. 대화에는 WebView, CameraX, 공식 XAPK/네이티브 라이브러리 분석, Bluetooth SPP 연결 시도가 있다. 개발 이력을 현재 장치에서 검증된 완성 기능으로 단정하지 않는다.
현재 mobile/ 디렉터리가 있으며 예전 website/android-webview 경로는 이번 확인에서 존재하지 않았다. APK 최신 위치와 실제 작동·Windows 기능 동등성은 별도 확인 필요하다. Windows DLL을 Android에 그대로 로드할 수 있다고 가정하지 않는다.
공식 프로그램 참고 경로(과거 사용자 제공): C:\Users\Public\AnalyzerTool\RunAnalyzerExe 및 C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer.
출처: docs/WINDOWS_CODEX_HANDOFF.md, docs/PROJECT_STATUS_AND_REMAINING_WORK.md, docs/WINDOWS_PREDICTION_READINESS.md.
관련: [[thermal-and-recording]], [[pump-and-safety]].

