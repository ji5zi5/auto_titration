---
title: "Thermal and Recording"
tags: ["Mini2", "DLL", "온도", "25fps", "CSV", "HSV"]
created: 2026-09-10T11:05:02.368Z
updated: 2026-09-10T11:05:02.368Z
sources: []
links: ["consultation-and-report.md", "ml-results-and-selection.md"]
category: architecture
confidence: medium
schemaVersion: 1
---

# Thermal and Recording

# 공식 온도변환과 데이터 수집
## 변환 경로
근거: auto_titrator/official_hikmicro.py.
Windows MTlib_OL.dll의 MT_Create_INT, MT_SetConfig/MT_SetConfig_INT, MT_Process_INT를 감싼다. 방사측정 JPEG의 APP2/APP3 보정·환경 메타데이터가 관련된다.
공식 처리 결과의 포인트 레코드 +0x10 int32 값을 64로 나누면 ℃다. 이 식은 원시 UVC 픽셀에 직접 적용하는 식이 아니다.
256×344 raw 프레임과 256×192 열화상 분석 영역을 구분한다. 전체 온도행렬을 생성할 수 있지만 CSV는 전체 픽셀 행렬이 아닌 ROI/전체 통계와 특징 중심이다.
1/64 ℃는 수치 표현 간격이지 장비의 절대 정확도 향상이 아니다. 팔레트 RGB 색을 온도로 간주하거나 임의 아핀 근사식으로 공식 변환을 대체하지 않는다.
과거 pythermal/WSL 접근에서는 USB shared와 attached 구분, 권한, uvcvideo 점유, 프레임 획득 후 장치 사라짐을 겪었다. 해당 시도가 최종 온도 경로는 아니다.

## 기록
일반 카메라 RGB/HSV, 변화량, 열화상 평균·최소·최대·표준편차·분위값, ROI 품질, 프레임 시각, 동기화 상태, 주입량·조건 등을 기록한다. 정확한 열 목록은 최신 CSV 스키마를 우선한다.
실제 기존 12회 1,822행의 평균 절대 센서 시각 차이는 문서상 3.66 ms. 동일 PC 수신 시각의 대응이며 하드웨어 동시 노출의 증거는 아니다.

## 저장 성능
미리보기 최신 프레임 유지와 녹화 FIFO 전체 보존을 분리했다. 종료 시 finalizing 상태에서 잔여 큐를 비운 뒤 확정한다.
2026-07-14 기록: 저장 raw+공식 DLL 250프레임 시험 24.93행/s, p95 8.91 ms, 누락 0. Python 경로 25.06행/s, p95 4.03 ms, 누락 0.
출처: docs/LIVE_PERFORMANCE_VALIDATION.md, tools/benchmark_live_pipeline.py.
이는 USB 실시간 습식 전체 검증이 아니다. 실제 확인 필드: mini2_capture_fps, mini2_recording_backlog_frames, mini2_recording_dropped_frames, processing_latency_ms.
과거 실제 CSV는 약 3.10~4.60행/s. 보간은 독립 관측 증가가 아니다.
관련: [[ml-results-and-selection]], [[consultation-and-report]].

