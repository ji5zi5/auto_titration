---
title: "detail-windows-handoff-03"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:12.356Z
updated: 2026-09-10T11:10:12.356Z
sources: []
links: ["detail-windows-handoff-01.md", "detail-windows-handoff-02.md", "detail-windows-handoff-03.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-windows-handoff-03

## 문서의 역할과 해석
운영 인수인계 이력. 날짜·배포 경로는 실행본과 재확인.

원문: [docs/WINDOWS_CODEX_HANDOFF.md](../docs/WINDOWS_CODEX_HANDOFF.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-windows-handoff-01]] / [[detail-windows-handoff-02]] / [[detail-windows-handoff-03]]

<!-- BEGIN SOURCE EXCERPT -->

## 10.5 CSV row 수가 적음

확인할 것:

- 녹화 상태가 실제로 시작되었는지
- collector loop가 멈추는 예외가 있는지
- 카메라 frame이 안 들어와 row 생성이 막히는지
- 펌프 미연결 때문에 녹화가 막히지 않는지
- 저장 경로 권한 문제가 있는지

## 11. 수정 작업 우선순위

가장 먼저 할 일:

1. Windows에서 `21_open_dashboard_server.bat` 실행 확인
2. 일반 카메라 표시 확인
3. Mini2 표시 확인
4. Arduino 없이도 녹화가 되는지 확인
5. Arduino 연결 후 `b`, `c`, `a` 명령 확인
6. 10초 테스트 CSV row 수 확인
7. 녹화 종료 후 `typewise_frame_zone_classifier` 예측 source 확인
8. 농도 계산창이 예측 당량점 기반으로 계산되는지 확인

그 다음 할 일:

1. 공식앱 APK/XAPK를 JADX, apktool, androguard로 다시 분석
2. Mini2 관련 Java/JNA/JNI call path를 문서화
3. `libHCUSBSDK.so`, `libMTlib.so`, `lib_thermal_module.so` 호출 순서를 찾기
4. 공식앱의 stream callback 흐름을 우리 Android 코드와 비교
5. 우리 앱에서 Mini2 최소 호출 경로만 재현
6. 실제 Mini2 frame callback이 들어오는지 확인
7. frame shape와 온도 변환을 Windows 공식 DLL 결과와 비교

나중에 할 일:

1. Android 화면/ROI/CSV 정리
2. Android Bluetooth 펌프 확인
3. Android ML 적용 방식 결정
4. 새 실험 데이터로 모델 재검증
5. release ZIP 또는 installer 정리

## 12. 수정 후 검증 방법

Python 코드나 웹 수집기를 고친 뒤에는 최소한 아래를 확인한다.

```bash
python3 -m unittest discover -v
```

가능하면 다음도 확인한다.

```bash
python3 -m py_compile tools/windows_live_collect.py tools/dashboard_server.py auto_titrator/*.py
```

Windows에서 실제 실행 확인은 다음이다.

```text
C:\Users\Jio\Downloads\auto_titration\launchers\windows\21_open_dashboard_server.bat
```

Android를 고쳤다면 다음을 확인한다.

```bash
cd mobile/android
./gradlew assembleDebug
```

Windows에서는 다음이다.

```bat
cd mobile\android
gradlew.bat assembleDebug
```

하드웨어가 있어야만 확인 가능한 항목은 테스트 결과에 `Not-tested: hardware run`처럼 남긴다.

## 13. 문서와 보고서 위치

전체 상세 현황:

```text
docs/PROJECT_STATUS_AND_REMAINING_WORK.md
```

Windows 실행 안내:

```text
docs/README_WINDOWS_CLICK_ME.txt
```

Android 참고:

```text
docs/mobile_companion_runbook.md
docs/hikmicro_apk_androguard_summary.txt
```

머신러닝 참고:

```text
docs/ml_current_volume_no_progress.md
docs/포스터_머신러닝_모델선정.txt
docs/포스터_적정종류별_성능표.csv
```

보고서/포스터 문장:

```text
docs/science_fair_report_final_draft.md
docs/보고서.txt
docs/포스터_*.txt
```

## 14. 새 Codex가 작업할 때의 안전한 순서

처음 받은 Codex는 바로 코드를 고치기보다 아래 순서로 확인한다.

1. `docs/WINDOWS_CODEX_HANDOFF.md` 읽기
2. `docs/PROJECT_STATUS_AND_REMAINING_WORK.md` 읽기
3. `git status --short` 확인
4. `launchers/windows/21_open_dashboard_server.bat` 실행 경로 확인
5. `tools/windows_live_collect.py`에서 현재 기본 모델 경로 확인
6. `website/app.js`에서 예측 source 표시 확인
7. 실제 버그 하나만 골라 수정
8. 최소 검증 실행
9. 커밋
10. Windows 단일 폴더에서 `git pull`로 동기화

Windows에 새 복사본을 만들지 않는다. 필요한 Windows 작업 폴더는 `C:\Users\Jio\Downloads\auto_titration` 하나다.

## 15. 이 문서의 핵심 한 줄

Windows 본경로는 `C:\Users\Jio\Downloads\auto_titration`에서 `21_open_dashboard_server.bat`를 실행하는 구조이고, 핵심 코드는 `tools/windows_live_collect.py`와 `website/app.js`이며, 현재 목표는 색 변화·열화상·주입량 CSV를 안정적으로 저장하고 `typewise_frame_zone_classifier` 예측으로 당량점과 농도를 계산하는 것이다.
<!-- END SOURCE EXCERPT -->

