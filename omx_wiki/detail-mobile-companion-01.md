---
title: "detail-mobile-companion-01"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:16.469Z
updated: 2026-09-10T11:10:16.469Z
sources: []
links: ["detail-mobile-companion-01.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-mobile-companion-01

## 문서의 역할과 해석
과거 companion 구성. 현재 phone-local 구조와 혼동 금지.

원문: [docs/mobile_companion_runbook.md](../docs/mobile_companion_runbook.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-mobile-companion-01]]

<!-- BEGIN SOURCE EXCERPT -->
# Android Companion Runbook

This runbook is for the phone-based sensor path. Use it only when the visible camera and/or Mini2 are plugged into the phone. The Windows laptop server still owns CSV recording, chemistry metadata, pump timing, and ML files.

## Roles

- **Laptop**: run `launchers/windows/21_open_dashboard_server.bat`, create pairing tokens, receive `/api/mobile/ingest`, write CSV.
- **Android companion**: capture visible-camera features through CameraX ImageAnalysis, probe Mini2 through Android USB host, and send `mobile_feature_frame.v1` payloads.
- **Pump**: remains manually supervised. This path does not add automatic motor stop.

## Pairing flow

1. Connect laptop and phone to the same Wi-Fi.
2. Start 21번 on the laptop and open `http://<laptop-ip>:8765`.
3. Press `Android 연결` in the dashboard to create a token.
4. Open the Android app from `mobile/android`, enter the laptop URL and token.
5. Start CSV recording on the laptop dashboard and confirm row count increases.

## Mini2 calibration guard

The Android scaffold can detect the Mini2 VID/PID and request USB permission, but it must not claim calibrated Celsius without a validated converter path. Until then, Android frames use `thermal_calibrated=false` with `raw_unverified` or `blocked` status. Use the Windows-native Mini2 collector for calibrated temperature experiments.

## Verification before real reagent

Run a water-only trial first. Confirm CSV rows contain mobile provenance fields, visible features, pump timeline fields, and safe Mini2 status fields. Keep raw CSVs in `data/raw/` and copy only selected runs to `data/labeled/` after reference equivalence values are added.
<!-- END SOURCE EXCERPT -->

