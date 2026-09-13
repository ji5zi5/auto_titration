---
title: "Thermal Investigation Details"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:13:03.299Z
updated: 2026-09-10T11:13:03.299Z
sources: []
links: ["code-and-data-atlas.md", "detail-android-reverse-engineering-01.md", "detail-android-runtime-01.md", "thermal-and-recording.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# Thermal Investigation Details

# Mini2 온도변환 조사 과정
## 문제의 출발
USB 카메라로 보이는 색 영상이 온도행렬인지 확인되지 않았다. 팔레트 색은 표시용이며 자동 범위 조절에 따라 달라질 수 있다. -20~150℃ 측정모드 고정과 화면 min/max 또는 raw 부호화 고정은 같은 의미가 아니다.

## 시도와 판정
대화 기록에는 OpenCV ANY/DSHOW/MSMF 비교, WSL usbipd attach, USB권한·uvcvideo 바인딩, pythermal metadata seq0/온도0, V4L2 ffmpeg 256×344 raw 획득, 연속 획득 중 USB 노드 소실이 있다. 일부 raw 확보는 성공했지만 그것만으로 ℃ 변환과 실시간 연속성이 증명되지 않았다.
IR_00001 포함 사용자 장비 CSV와 공식 예시 장비 CSV를 구분해야 했다. min/max를 맞춘 선형·아핀·비선형 근사나 답 CSV를 사용한 보정은 실시간 독립 변환 경로로 채택하면 안 된다.

## 현재 Windows 직접 코드 근거
파일 auto_titrator/official_hikmicro.py는 MTlib_OL.dll을 ctypes로 사용한다.
MT_Create_INT(256,192) → APP2 tag519 보정 설정 → 환경키 설정 → APP3 tag1 관련 설정 → MT_Process_INT point records.
출력 point+0x10 signed int32 /64가 ℃다. 따라서 '/64가 맞다'와 'raw pixel/64가 맞다'는 전혀 다르다. 분해능1/64를 절대정확도1/64로 쓰지 않는다.
보정 메타데이터·환경 값·ABI/구조체 크기·초기화 순서가 필요하다. 서브함수 이름을 찾거나 DLL 파일만 복사해도 자동으로 맞는 결과가 나오는 것이 아니다.
vendor/hikmicro_analyzer/MTlib_OL.dll이 현재 확인된 파일이다. MicroPixeler_Release_x64.dll, MicroTA_Release_x64.dll도 있지만 이름 유사성으로 핵심 변환 DLL을 바꾸지 않는다.

## Android 공식 프로그램 분석
HIKMICRO Viewer2.6.0 XAPK의 DEX/JNA와 ARM64 so 구조 분석을 남겼다. libHCUSBSDK.so, lib_thermal_module.so, libMTlib.so, libMicroJITA_Release_v8a.so, libMicroTA_Release_v8a.so가 후보 계층이다.
USB 권한→SDK 초기화→열거/등록/login→Mini2 F2 profile→stream 설정→callback→프레임→온도 처리 순서를 확인해야 한다. 정적 심볼 발견은 실제 native 호출 순서의 확증이 아니다.
mobile/android/app/src/main/assets/hikmicro/mtlib-fixture/IR_00001/에 raw/tag519/tag1/expected_first32 fixture가 있다. 공식 DEX assets도 있지만 존재만으로 phone-only 성공이라 할 수 없다.

## 다음 조사자가 남겨야 할 증거
장치명/측정모드/환경설정, 사용 DLL·so 해시, 함수순서, ABI, 입력raw 해시와 크기, 비교 CSV 출처, 픽셀별 오차, 반복프레임 처리량, 실제 USB 연속성. 성공한 fixture와 다른 장면 일반화를 분리한다.
[[thermal-and-recording]] / [[detail-android-reverse-engineering-01]] / [[detail-android-runtime-01]] / [[code-and-data-atlas]]

