---
title: "detail-project-status-03-part-2"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:13:57.061Z
updated: 2026-09-10T11:13:57.061Z
sources: []
links: ["detail-project-status-03-part-2.md", "detail-project-status-03-part-3.md", "detail-project-status-03.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-project-status-03-part-2

원문 [docs/PROJECT_STATUS_AND_REMAINING_WORK.md](../docs/PROJECT_STATUS_AND_REMAINING_WORK.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-project-status-03]] / [[detail-project-status-03-part-2]] / [[detail-project-status-03-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
1. 공식 앱/APK/XAPK 분석부터 다시 한다.
   - `docs/hikmicro_apk_androguard_summary.txt`를 읽는다.
   - JADX, apktool, androguard로 Mini2 관련 class와 method를 다시 찾는다.
   - 공식 앱에서 USB 권한, 장치 enum, register/login, stream start가 어디서 호출되는지 call path를 뽑는다.

2. native `.so` 호출 관계를 확인한다.
   - `libHCUSBSDK.so`
   - `libMTlib.so`
   - `lib_thermal_module.so`
   - `libusbCam_host.so`
   - `libuvc.so`
   - Ghidra/IDA로 export symbol, string, error code, callback 관련 이름을 확인한다.

3. 공식 앱의 실제 실행 흐름을 추적한다.
   - 가능하면 logcat으로 공식 앱 실행 로그를 본다.
   - 가능하면 Frida 같은 동적 추적으로 USB/stream/native 함수 호출 순서를 확인한다.
   - 목표는 앱 전체 복붙이 아니라 Mini2를 여는 최소 call sequence를 얻는 것이다.

4. 우리 Android 코드와 비교한다.
   - `Mini2UsbProbe.kt`
   - `thermal/HikmicroF1Mini2Stream.kt`
   - `thermal/HikmicroJnaMini2Stream.kt`
   - `thermal/HikmicroNativeBackend.kt`
   - `com/hcusbsdk/`
   - `com/hik/f2module/`
   - 공식 앱과 다르게 호출하는 부분을 찾는다.

5. 최소 Mini2 stream 경로만 먼저 구현한다.
   - USB 권한 요청
   - SDK 초기화
   - device enum 또는 register/login
   - F2/Mini2 module type 설정
   - stream parameter 설정
   - `USB_StartStreamCallback` 또는 같은 역할의 함수 호출
   - frame callback 수신

6. frame evidence를 먼저 저장한다.
   - width, height, type, sequence
   - raw byte size
   - fps
   - error code
   - callback count
   - 공식 앱 또는 Windows와 shape 비교

7. 온도 변환은 frame 수신 이후에 한다.
   - 공식 처리 함수가 int temperature matrix를 주는지 확인한다.
   - Windows 공식 DLL의 `/64` 결과와 비교한다.
   - 검증 전에는 `thermal_calibrated=false` 또는 `raw_unverified`로 둔다.

P0에서 후순위로 미룰 것:

- Android 화면 예쁘게 만들기
- YOLO ROI 개선
- CSV export 확장
- Bluetooth 펌프 연결
- Android ML 적용
- WebView UI 세부 정리

이 후순위 작업들은 Mini2 공식 호출 경로가 잡힌 뒤에 진행한다.

## 4.4 P0 - Mini2 Android 공식앱 역분석 계속

공식 앱/APK 분석을 이어가야 할 때 참고할 자료는 다음이다.

```text
docs/hikmicro_apk_androguard_summary.txt
mobile/android/app/src/main/java/com/hcusbsdk/
mobile/android/app/src/main/java/com/hik/f2module/
mobile/android/app/src/main/java/com/hik/viewer/
mobile/android/app/src/main/java/com/hik/viewercommon/
mobile/android/app/src/main/jniLibs/arm64-v8a/
```

수정할 점:

1. 공식 앱의 USB stream callback 호출 순서를 정리한다.
2. 우리 Kotlin/JNI bridge가 그 순서와 얼마나 다른지 비교한다.
3. `USB_StartStreamCallback` 또는 유사 callback에서 frame을 받는지 확인한다.
4. frame metadata에 width, height, type, sequence가 들어오는지 확인한다.
5. Windows의 `256x344` raw frame과 Android frame shape가 일치하는지 확인한다.
6. 온도 행렬을 얻는 공식 함수가 있는지 찾는다.
7. 공식 앱 화면의 min/max 온도와 우리 계산 min/max를 비교한다.

완료 기준:

- Android에서도 실제 Mini2를 꽂았을 때 25fps 근처 frame이 들어온다.
- raw frame shape가 문서화된다.
- 섭씨 변환이 공식 앱 또는 Windows DLL 결과와 비교 검증된다.
- 검증 실패 시 원인을 문서화하고 Android는 raw_unverified로 남긴다.

## 4.5 P1 - 실험 전 체크리스트 추가

실제 전람회 실험 전에는 다음을 한 화면 또는 README에 넣는 것이 좋다.

수정할 점:

1. 카메라 고정
2. Mini2 고정
3. 조명 고정
4. 비커 위치 고정
5. 일반 카메라 ROI lock
6. 열화상 ROI lock
7. 펌프 공기 제거
8. 10초 물 토출로 유량 확인
9. Arduino 포트 연결 확인
10. CSV row 수 확인
11. 예측 source 확인
12. 파일 저장 위치 확인

이 체크리스트는 사용자가 당일 급하게 실험할 때 매우 중요하다.

## 4.6 P1 - CSV 품질 진단 기능

CSV가 저장되더라도 row 수가 부족하거나 센서값이 비어 있으면 머신러닝에 쓰기 어렵다. 따라서 녹화 종료 후 자동 진단을 추가하는 것이 좋다.

수정할 점:

1. row 수 표시
2. duration 표시
3. 평균 FPS 표시
4. 일반 카메라 frame 누락률 표시
5. 열화상 frame 누락률 표시
6. ROI 준비 안 된 row 비율 표시
7. thermal 값이 `-`인 row 비율 표시
8. predicted source 표시
9. CSV 저장 경로 표시
10. “이 파일은 학습용으로 충분/부족” 간단 판정 표시

## 4.7 P1 - 머신러닝 검증 보강

현재 모델 결과가 좋아졌지만, 데이터가 12개 run으로 매우 적다. 따라서 다음을 추가해야 한다.

수정할 점:

1. 새 실험 CSV 1개 이상으로 blind 검증
2. 같은 조건 반복 실험으로 재현성 확인
3. 모델이 이론값을 베끼지 않는지 feature leakage 재검사
4. 적정 종류별 모델이 올바르게 선택되는지 확인
5. 약산-강염기에서 오차가 큰 원인 재분석
6. 포스터 수치와 실제 모델 artifact가 같은 결과에서 나온 것인지 확인
<!-- END SOURCE EXCERPT -->

