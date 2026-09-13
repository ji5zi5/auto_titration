---
title: "detail-project-status-04"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:13.608Z
updated: 2026-09-10T11:10:13.608Z
sources: []
links: ["detail-project-status-01.md", "detail-project-status-02.md", "detail-project-status-03.md", "detail-project-status-04.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-project-status-04

## 문서의 역할과 해석
통합 현황 원문. 작성시점이 다른 단락과 완료/미완료 표현을 구별.

원문: [docs/PROJECT_STATUS_AND_REMAINING_WORK.md](../docs/PROJECT_STATUS_AND_REMAINING_WORK.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-project-status-01]] / [[detail-project-status-02]] / [[detail-project-status-03]] / [[detail-project-status-04]]

<!-- BEGIN SOURCE EXCERPT -->
GitHub에 EXE 하나만 올리면 전체가 동작하는 구조가 아니다. 현재는 ZIP 안의 파일들이 같이 있어야 한다.

수정할 점:

1. release ZIP에 다음이 포함되는지 확인
   - `AutoTitration.exe`
   - `launchers/windows/21_open_dashboard_server.bat`
   - `tools/`
   - `auto_titrator/`
   - `website/`
   - `vendor/hikmicro_analyzer/`
   - `data/labeled/typewise-current-volume-classifier.pkl`
   - `requirements.txt`
   - `requirements-yolo.txt`
2. 새로 수정하면 `v0.1.4` 같은 버전으로 release 후보 생성
3. README에 “ZIP 압축을 풀고 BAT 또는 EXE 실행”이라고 명확히 적기
4. DLL 라이선스/배포 가능성은 공개 release 전에 확인

## 4.10 P2 - 문서 정리

문서가 많아졌으므로 안내 문서를 계층화할 필요가 있다.

수정할 점:

1. 사용자가 보는 문서
   - `README.md`
   - `docs/README_WINDOWS_CLICK_ME.txt`
2. 개발자가 보는 문서
   - `docs/WINDOWS_CODEX_HANDOFF.md`
   - `docs/PROJECT_STATUS_AND_REMAINING_WORK.md`
3. 포스터/보고서 문서
   - `docs/포스터_*.txt`
   - `docs/science_fair_report_*.md`
4. 연구 기록 문서
   - `docs/ml_*.md`
   - `docs/hikmicro_apk_androguard_summary.txt`
5. 오래된 가설/실패 파일은 지우기보다 archive 또는 “not current” 표시

## 4.11 P2 - 불필요 파일/캐시 정리

이미 일부 정리를 했지만, 용량 문제가 다시 생기면 다음을 우선 확인한다.

수정할 점:

1. pip cache
2. `__pycache__`
3. 오래된 raw probe dump
4. 중복 ZIP
5. 오래된 dist build
6. 실패한 Mini2 연구 dump 중 현재 재현에 필요 없는 파일

삭제 제외 대상은 “현재 실험 CSV, 공식 DLL, Android native libs, 모델 pkl”이다. 삭제 전에는 문서에서 현재 쓰는 파일인지 확인한다.

## 5. Windows에서 다음 Codex가 바로 할 작업 순서

추천 순서는 다음이다.

1. GitHub repo clone 또는 기존 폴더 pull
2. `docs/WINDOWS_CODEX_HANDOFF.md` 읽기
3. 이 문서 읽기
4. Windows에서 `21_open_dashboard_server.bat` 실행
5. Arduino 없이도 웹/카메라/CSV가 되는지 확인
6. Arduino를 꽂고 재연결 상태 확인
7. Mini2를 꽂고 열화상 frame 확인
8. 10초 물 테스트로 CSV row 수와 주입량 확인
9. 녹화 종료 후 typewise model 예측 source 확인
10. Windows release ZIP은 DLL 재배포 권한을 별도로 확인한 뒤에만 재생성
11. Android Studio에서 `mobile/android` build 시작
12. Android 카메라 preview부터 고침
13. Android Mini2 USB permission/stream 확인
14. Android CSV schema를 Windows와 맞춤
15. Bluetooth 펌프 연결 확인

## 6. Android 담당 Codex가 반드시 먼저 읽을 파일

Android를 이어서 만들 Codex는 아래 순서로 읽으면 된다.

```text
docs/PROJECT_STATUS_AND_REMAINING_WORK.md
docs/WINDOWS_CODEX_HANDOFF.md
docs/mobile_companion_runbook.md
docs/hikmicro_apk_androguard_summary.txt
mobile/android/README.md
mobile/android/app/src/main/AndroidManifest.xml
mobile/android/app/build.gradle.kts
mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/AndroidBridge.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/Mini2ValidationGate.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroF1Mini2Stream.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/pump/BluetoothPumpTransport.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/data/CsvSchema.kt
```

## 7. 현재 가장 중요한 수정점 10개

1. Windows에서 실제 실험 10초 테스트로 CSV row 수와 예측 source 확인
2. Arduino를 나중에 꽂아도 collector가 자동 재연결하는지 확인
3. 펌프 미연결 상태에서도 녹화가 막히지 않게 유지
4. 농도 계산창이 이론값이 아니라 예측 당량점 기반 계산을 표시하는지 확인
5. 예측 pH가 `-`로만 뜨는 원인 수정
6. Android Studio에서 mobile/android build 성공시키기
7. Android 카메라 preview와 ROI 좌표 오류 수정
8. Android Mini2 USB 권한과 native stream 실제 연결 확인
9. Android Mini2 섭씨 변환은 공식 `.so` 경로로만 검증
10. 포스터/보고서에서 머신러닝 성능을 개발셋 기준으로 표현

## 8. 현재 주장해도 되는 것과 아직 주장하면 안 되는 것

주장해도 되는 것:

- Windows 앱에서 일반 카메라, Mini2, 펌프, CSV, 화학 계산, ML 예측을 통합하려는 구조를 구현했다.
- Windows Mini2 온도는 공식 DLL 처리 결과를 `/64`로 해석하는 경로를 사용한다.
- Arduino 시린지 펌프는 `a`, `b`, `c` 명령으로 후퇴, 주입, 정지한다.
- 물 주입 실험에서 약 1 mL/s 수준의 보정 유량을 사용했다.
- 수집 데이터 기준 머신러닝 개발셋 MAPE는 약 1.27%로 정리되어 있다.
- 약산-강염기 조건이 상대적으로 어려운 조건으로 나타났다.
- Android host-side debug/unit software 검증과 private lab APK 빌드는 수행할 수 있다.

아직 조심해야 하는 것:

- Android 단독 Mini2 섭씨 변환이 Windows처럼 완전히 검증되었다고 말하면 안 된다.
- 과거 G009 Android/Python/JS 검증 또는 release APK hash/signature 기록을 현재
  공개 배포 승인으로 해석하면 안 된다. 해당 기록은 historical software evidence이고,
  현재 active G009 software audit와 release-governance 상태는 별도다.
- 현재 official-byte Android 트리, APK, source backup을 push/publish/재배포하면
  안 된다. boolean Gradle property는 외부 권한을 대체하지 않는다.
- 머신러닝 MAPE 1.27%를 모든 새 실험에서 보장되는 성능처럼 말하면 안 된다.
- EXE 하나만 있으면 모든 PC에서 동작한다고 말하면 안 된다. ZIP 내부 파일과 DLL이 필요하다.
- 자동으로 펌프가 당량점에서 멈춘다고 말하면 안 된다. 현재 설계는 자동 정지가 아니다.
- 이론 당량점이 실제 실험의 참값이라고 단정하면 안 된다. 용액 조제 오차가 있을 수 있다.

## 9. 마지막 정리

현재 프로젝트는 Windows 노트북 기준으로는 전람회 시연과 데이터 수집이 가능한 수준까지 많이 진행되어 있다. 핵심은 Windows 앱에서 카메라 색 변화, Mini2 열화상 온도, 펌프 주입량, 화학 계산, 머신러닝 예측을 하나의 CSV와 UI로 묶은 것이다.

앞으로의 핵심 수정 방향은 두 가지다.

첫째, Windows 본경로를 실제 실험에서 더 안정적으로 만드는 것이다. 특히 CSV row 수, Arduino 재연결, 예측 source, 농도 계산 UI, Mini2 표시를 확인해야 한다.

둘째, Android 앱을 Windows 기능과 맞게 실사용 가능하게 만드는 것이다. Android에는 이미 코드와 공식 앱 분석 자료, native library가 들어 있지만, 빌드와 실제 USB Mini2 stream, Bluetooth 펌프, CSV 저장, ML 적용을 다시 검증해야 한다.

따라서 다음 개발자는 새 기능을 크게 추가하기보다, 먼저 “현재 구현된 기능이 실제 실험에서 끝까지 끊기지 않고 기록되는가”를 검증하고, 그 다음 Android 단독/companion 기능을 완성하는 순서로 가야 한다.
<!-- END SOURCE EXCERPT -->

