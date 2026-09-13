---
title: "detail-project-status-02-part-2"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:13:56.438Z
updated: 2026-09-10T11:13:56.438Z
sources: []
links: ["detail-project-status-02-part-2.md", "detail-project-status-02-part-3.md", "detail-project-status-02.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-project-status-02-part-2

원문 [docs/PROJECT_STATUS_AND_REMAINING_WORK.md](../docs/PROJECT_STATUS_AND_REMAINING_WORK.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-project-status-02]] / [[detail-project-status-02-part-2]] / [[detail-project-status-02-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
`tools/windows_live_collect.py`에는 다음 기본값이 들어 있다.

```text
DEFAULT_LIVE_ML_MODEL = ""
DEFAULT_ENDPOINT_ML_MODEL = ROOT / "data" / "labeled" / "type-conditioned-sensor-endpoint-ranker.pkl"
DEFAULT_TYPEWISE_LIVE_ML_MODEL = ROOT / "data" / "labeled" / "typewise-current-volume-classifier.pkl"
```

완료된 CSV에는 사후 시계열 모델을 먼저 적용한다. 이 모델은 적정 종류별 PLS·RBF 커널 릿지·LDA·QDA 경로를 사용하고, 12개 leave-one-run-out 모델의 예측 중앙값을 점 추정으로 사용한다. 색상 또는 열화상 자료가 부족하면 기존 typewise classifier와 peak 추정으로 넘어간다. 자동 정지는 미래 프레임을 사용할 수 없으므로 기존 causal typewise classifier를 계속 사용한다.

현재 live 예측 source는 다음으로 표시된다.

```text
predicted_equivalence_source = type_conditioned_sensor_endpoint_ranker
```

웹에서는 이를 다음처럼 표시한다.

```text
적정 종류별 시계열 모델
```

현재 머신러닝 정리는 다음과 같다.

- 실험 종료 후 색상·열화상 시계열에서 변화 후보를 만들고 적정 종류별 평가기로 당량점 하나를 고른다.
- 현재 주입량은 센서 특징이 아니라 고밀도 입력의 부피축 재표본화와 선택된 프레임의 mL 환산에만 사용한다.
- 25 fps 입력은 학습 당시의 부피 간격에 맞춰 두 위상으로 재표본화하여 프레임 밀도 차이를 줄인다.
- 진행률, 이론 당량점, 당량점까지의 거리, 미지 농도와 정답 라벨은 모델 특징에서 제외한다.
- 색상·열화상 유효 행 비율이 80% 미만이거나 신호가 평탄하면 융합 예측을 보류한다.

현재 검증 범위는 다음과 같다.

```text
선택된 고정 설정의 사후 개발 MAPE: 0.295%
배포 fold 중앙값 모델의 6월 재적용 MAPE: 1.106%
25 fps 고밀도 모의 입력 재적용 MAPE: 1.192%
원래 예측 대비 고밀도 입력 평균 이동: 0.252 mL
고밀도 입력 최대 이동: 1.043 mL
7월 지정 동일 미지 시료 3회 CV: 0.961%
```

0.295%는 2,030,370개 설정을 같은 12회에서 비교한 사후 개발값이고, 1.106%와 1.192%도 기존 자료 재적용 진단이다. 7월 0.961%는 정확도가 아니라 지정된 동일 미지 시료의 반복성이다. 독립적으로 표정한 새 습식 시료의 정확도로 표현하면 안 된다.

## 3.8 Android 앱

Android 프로젝트 위치는 다음과 같다.

```text
mobile/android/
```

주요 파일은 다음과 같다.

```text
mobile/android/settings.gradle.kts
mobile/android/build.gradle.kts
mobile/android/app/build.gradle.kts
mobile/android/app/src/main/AndroidManifest.xml
mobile/android/README.md
```

주요 Kotlin 코드 위치는 다음과 같다.

```text
mobile/android/app/src/main/java/kr/auto/titration/mobile/
```

구현 또는 scaffold가 있는 영역은 다음과 같다.

- `MainActivity.kt`: 앱 진입점
- `AndroidBridge.kt`: WebView와 native bridge
- `MobileFeatureClient.kt`: 노트북 서버로 feature frame 전송
- `Mini2UsbProbe.kt`: USB Mini2 권한/연결 probe
- `session/PhoneRunSession.kt`: 폰 단독 session 구조
- `data/LocalCsvWriter.kt`: Android 로컬 CSV 저장
- `data/CsvFeatureRow.kt`, `data/CsvSchema.kt`: Android CSV schema
- `chemistry/EquivalenceCalculator.kt`: Android 농도/당량 계산
- `pump/BluetoothPumpTransport.kt`: Bluetooth Classic SPP 펌프 통신
- `pump/PumpCommandContract.kt`: `a`, `b`, `c` 명령 계약
- `vision/VisibleFeatureExtractor.kt`: 스마트폰 카메라 RGB/HSV feature
- `vision/YoloSegmentationDetector.kt`: YOLO segmentation ROI 후보
- `ml/LiteRtYoloSegmenter.kt`: TFLite YOLO 실행
- `thermal/HikmicroF1Mini2Stream.kt`: HIKMICRO F1/Mini2 stream 시도
- `thermal/HikmicroJnaMini2Stream.kt`: HIKMICRO JNA stream 시도
- `thermal/Mini2ValidationGate.kt`: calibrated/raw_unverified gate

Android asset은 다음과 같다.

```text
mobile/android/app/src/main/assets/models/yolo11n-seg-256-fp32.tflite
mobile/android/app/src/main/assets/models/yolo11n-seg-256-fp32.metadata.json
```

Android native library는 다음 위치에 있다.

```text
mobile/android/app/src/main/jniLibs/arm64-v8a/
```

중요 `.so`는 다음과 같다.

```text
libHCUSBSDK.so
libMTlib.so
libAnalyzeData.so
lib_thermal_module.so
libMicroJITA_Release_v8a.so
libMicroJPEG_Release_v8a.so
libusbCam_host.so
libuvc.so
libusb-1.0.so
```

공식 APK/XAPK 분석 요약은 다음 문서에 있다.

```text
docs/hikmicro_apk_androguard_summary.txt
```

공식 앱 구조를 맞추기 위한 namespace도 repo에 들어 있다.

```text
mobile/android/app/src/main/java/com/hcusbsdk/
mobile/android/app/src/main/java/com/hik/f2module/
mobile/android/app/src/main/java/com/hik/viewer/
mobile/android/app/src/main/java/com/hik/viewercommon/
```

현재 Android에 대한 정확한 판단은 다음과 같다.

- Android 파일은 많이 만들어져 있다.
- 공식 APK 분석 흔적과 `.so` 복사본도 있다.
- 하지만 Windows 본경로처럼 실제 실험에서 안정적으로 작동 검증된 상태는 아니다.
<!-- END SOURCE EXCERPT -->

