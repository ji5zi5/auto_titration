---
title: "detail-performance-01"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:14.563Z
updated: 2026-09-10T11:10:14.563Z
sources: []
links: ["detail-performance-01.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-performance-01

## 문서의 역할과 해석
저장 raw 및 처리경로 벤치마크. 실제 USB 장시간 습식 성능과 별개.

원문: [docs/LIVE_PERFORMANCE_VALIDATION.md](../docs/LIVE_PERFORMANCE_VALIDATION.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-performance-01]]

<!-- BEGIN SOURCE EXCERPT -->
# 실시간 수집 성능 검증

## 목표

- Mini2 캡처 속도: 25 fps
- 녹화 중 프레임 누락: 0
- Python 처리 지연 p95: 40 ms 이하
- 미리보기는 오래된 프레임을 쌓지 않고 최신 프레임만 표시
- 녹화 종료 후 남은 프레임을 모두 CSV에 반영한 뒤 다운로드

## 구조

Mini2 입력은 두 경로로 분리한다. 브라우저 미리보기는 최신 프레임만 유지하므로 화면 지연이 누적되지 않는다. 녹화 프레임은 별도의 순서 보장 FIFO에 저장하며, 처리 속도가 순간적으로 느려져도 프레임을 자동 삭제하지 않는다. 종료 버튼을 누르면 상태가 `finalizing`으로 바뀌고 FIFO가 완전히 비워진 뒤 CSV 다운로드가 시작된다.

CSV와 화면에서 다음 값을 확인할 수 있다.

- `mini2_capture_fps`: 실제 캡처 속도
- `mini2_recording_backlog_frames`: 아직 처리되지 않은 녹화 프레임 수
- `mini2_recording_max_backlog_frames`: 실험 중 최대 처리 대기량
- `mini2_recording_dropped_frames`: CSV에 저장하지 못한 녹화 프레임 수
- `processing_latency_ms`: 캡처 후 분석이 시작될 때까지의 지연

`mini2_recording_dropped_frames`가 0이 아니면 해당 실험은 완전한 25 fps 기록으로 취급하지 않는다.

## 자동 벤치마크

```bash
python3 tools/benchmark_live_pipeline.py --frames 250 --target-fps 25 \
  --min-throughput-fps 24.5 --max-p95-latency-ms 40 \
  --max-recording-drops 0
```

2026-07-14 최종 검증 결과는 250행 모두 저장, 25.06 rows/s, p95 4.03 ms, 녹화 누락 0이었다.

Windows Python에서 실제 `MTlib_OL.dll`과 Mini2 저장 raw 프레임을 사용한 동일한 250프레임 최종 검증 결과는 24.93 rows/s, p95 8.91 ms, 녹화 누락 0이었다. 온도 변환은 근사식이 아니라 공식 DLL의 `MT_Process_INT` 결과를 사용한다.

## 실제 장치 확인

저장 프레임 벤치마크는 공식 DLL 처리량을 검증하지만 USB 카메라 드라이버 상태까지 대신하지는 않는다. 실제 실험 전 10초 동안 화면의 캡처 속도가 약 25 fps로 유지되고, 처리 대기량이 다시 0으로 내려가며, 기록 누락이 0인지 확인한다. ROI 자동 탐색은 설정 단계에서만 사용하고 녹화 전 ROI를 고정한다.
<!-- END SOURCE EXCERPT -->

