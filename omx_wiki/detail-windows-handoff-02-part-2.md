---
title: "detail-windows-handoff-02-part-2"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:13:55.152Z
updated: 2026-09-10T11:13:55.152Z
sources: []
links: ["detail-windows-handoff-02-part-2.md", "detail-windows-handoff-02-part-3.md", "detail-windows-handoff-02.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-windows-handoff-02-part-2

원문 [docs/WINDOWS_CODEX_HANDOFF.md](../docs/WINDOWS_CODEX_HANDOFF.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-windows-handoff-02]] / [[detail-windows-handoff-02-part-2]] / [[detail-windows-handoff-02-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
이 수치는 포스터에 쓸 수 있지만, 새 실험에서 보장되는 성능이라고 쓰면 안 된다. 현재 수집된 12개 run 기준의 개발셋 결과다.

ML 입력으로 써도 되는 값:

- 현재 주입량
- 펌프 시간
- RGB/HSV 센서값
- 열화상 센서값
- ROI 품질
- 적정 종류
- 표준용액 정보

ML 입력으로 쓰면 안 되는 값:

- 이론 당량점 부피
- 당량점까지 남은 거리
- 정답 라벨
- 최종 총 주입량
- 전체 진행률
- 미지 시료 농도 정답

현재 live collector는 기존 leaky JSON 모델보다 typewise classifier pickle을 우선 사용한다. 예전 JSON 모델 파일이 남아 있어도 기본 경로가 아니다.

## 9. Android 앱 상태

Android 프로젝트는 다음 위치에 있다.

```text
mobile/android/
```

주요 파일:

```text
mobile/android/settings.gradle.kts
mobile/android/build.gradle.kts
mobile/android/app/build.gradle.kts
mobile/android/app/src/main/AndroidManifest.xml
mobile/android/README.md
```

주요 Kotlin 코드:

```text
mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/AndroidBridge.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/MobileFeatureClient.kt
mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/
mobile/android/app/src/main/java/kr/auto/titration/mobile/pump/
mobile/android/app/src/main/java/kr/auto/titration/mobile/data/
mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/
```

Android native library 위치:

```text
mobile/android/app/src/main/jniLibs/arm64-v8a/
```

공식 HIKMICRO APK 분석 요약:

```text
docs/hikmicro_apk_androguard_summary.txt
```

Android는 아직 Windows 본경로와 같은 수준으로 검증된 완성본이 아니다. 다음 작업의 1순위는 UI, CSV, YOLO, ML, Bluetooth가 아니다. 1순위는 공식 HIKMICRO 앱이 Mini2를 여는 최소 호출 경로를 역분석해서 우리 앱에서 재현하는 것이다.

Android 쪽 P0 목표:

```text
공식앱 APK/XAPK 분석
→ Mini2 관련 Java/JNA/JNI call path 추출
→ 어떤 .so 함수가 어떤 순서로 호출되는지 정리
→ 우리 Android 코드에서 최소 호출 순서 재현
→ 실제 Mini2 frame callback 수신
→ 256x344 또는 공식 frame shape 확인
→ 공식 앱/Windows 결과와 비교해 섭씨 변환 검증
```

P0에서 봐야 할 도구와 자료:

```text
JADX 또는 apktool: Java/Kotlin/decompiled call path 확인
androguard: manifest, class, method, call graph 보조 분석
Ghidra 또는 IDA: libHCUSBSDK.so, libMTlib.so, lib_thermal_module.so 등 native symbol/string 확인
logcat: 공식 앱 실행 중 로그와 에러 코드 확인
Frida 등 동적 추적: 가능하면 공식 앱의 실제 함수 호출 순서 확인
```

P0에서 찾아야 하는 최소 흐름:

```text
USB 권한 요청
→ HCUSBSDK 초기화
→ 장치 enum 또는 register/login
→ F2/Mini2 module type 설정
→ stream parameter 설정
→ USB_StartStreamCallback 또는 같은 역할의 함수 호출
→ frame callback 수신
→ thermal 처리 함수로 온도 행렬 또는 int temperature matrix 생성
→ Windows 공식 DLL 결과와 비교
```

이 단계가 끝나기 전에는 아래 작업을 후순위로 둔다.

- Android 화면 예쁘게 다듬기
- YOLO ROI 개선
- CSV export 확장
- Bluetooth 펌프 연동
- Android ML 적용

단, 공식앱 코드를 통째로 복붙하는 것이 목표는 아니다. 목표는 Mini2를 여는 데 필요한 호출 순서와 데이터 구조만 뽑아 우리 앱에서 최소 재현하는 것이다. 섭씨 변환이 검증되기 전에는 thermal 값은 `raw_unverified` 또는 `thermal_calibrated=false`로 남긴다.

Android에서 Python pickle을 직접 쓰기는 어렵다. Mini2 호출 경로가 해결된 뒤에야 ML 적용 방식을 정한다. 선택지는 다음 중 하나다.

1. Android는 수집만 하고 Windows/Python에서 예측한다.
2. 모델을 JSON/Kotlin 경량 모델로 변환한다.
3. TFLite/ONNX 등 모바일용 모델로 변환한다.

전람회 일정이 급하면 1번이 가장 안전하다.

## 10. 자주 생기는 문제와 확인 위치

## 10.1 웹은 뜨는데 카메라가 안 뜸

확인할 것:

- collector가 8766 포트에서 살아 있는지
- 브라우저 콘솔에 API 오류가 있는지
- `tools/windows_live_collect.py` 로그에 camera index 오류가 있는지
- 다른 앱이 카메라를 점유하고 있는지

## 10.2 Mini2가 안 뜸

확인할 것:

- Mini2가 Windows 장치로 보이는지
- HIKMICRO 공식 앱이나 다른 프로그램이 Mini2를 점유하고 있지 않은지
- `vendor/hikmicro_analyzer/` DLL이 있는지
- collector 로그에서 Mini2 index 탐색 실패가 있는지

## 10.3 Arduino IDE에서는 되는데 웹에서는 펌프가 안 됨

확인할 것:

- Arduino IDE Serial Monitor를 닫았는지
- 포트가 collector 실행 후에 연결되었는지
- collector가 재연결 중인지
- 웹 버튼이 `a`, `b`, `c` 중 맞는 명령을 보내는지
- `PUMP_START_COMMAND=b`, `PUMP_RETRACT_COMMAND=a`, `PUMP_STOP_COMMAND=c` 설정이 맞는지

## 10.4 농도 계산창이 이상함

<!-- END SOURCE EXCERPT -->

