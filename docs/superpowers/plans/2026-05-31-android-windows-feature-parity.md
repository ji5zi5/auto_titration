# Android Windows Feature Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Android APK include the same Windows/live-collector feature set instead of Android-only approximations, with ROI candidate, mask metadata, thermal raw ROI, CSV, and diagnostics behaving like the laptop path.

**Architecture:** Keep the existing WebView UI. Port the Windows ROI/data semantics into native Android Kotlin behind the JavaScript bridge: YOLO segmentation visible ROI, raw-matrix thermal contrast ROI, mask/state models, latest-only worker, Windows-compatible bridge payloads, CSV mask fields. Disable the current luma heuristic as the parity path.

**Tech Stack:** Kotlin, Android WebView `@JavascriptInterface`, CameraX ImageAnalysis, HIKMICRO Mini2 raw stream/JNA, Google AI Edge LiteRT `com.google.ai.edge.litert:litert:2.1.5` CPU Interpreter/CompiledModel path, packaged `assets/models/yolo11n-seg-256-fp32.tflite`, Python `unittest`, Android Gradle `lintDebug`/`assembleDebug`.



## Current G001 lane evidence snapshot (2026-05-31)

This plan is implementation guidance; the leader-owned Ultragoal artifacts remain the audit source of truth and workers must not mutate `.omx/ultragoal`.

- Active story: `G001-lock-failing-parity-tests-and-no-fal`.
- Worker-2 model/runtime lane evidence gathered so far:
  - `mobile/android/app/build.gradle.kts` already contains `implementation("com.google.ai.edge.litert:litert:2.1.5")` and packages `src/main/assets` alongside the WebView assets.
  - `mobile/android/app/src/main/assets/models/yolo11n-seg-256-fp32.tflite` and `.metadata.json` exist, but the current `.tflite` is an intentional placeholder.
  - Metadata sets `placeholder_model: true`; therefore runtime code must return `yolo_model_unavailable` and must not emit YOLO success until a real exported TFLite model replaces it and SHA/tensor metadata are updated.
  - `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/YoloSegmentationDetector.kt` is the current contract-gate owner for metadata, SHA256, placeholder, input size, and output tensor checks.
  - `AndroidAutoRoiWorker.kt` should remain a thin latest-only orchestration shell and must not own model-contract parsing.
- Current expected-red locks:
  - `python3 -m unittest tests.test_android_mobile_roi tests.test_android_webview_mini2 tests.test_android_scaffold -v` currently fails only on the old ROI candidate path (`requestAutoRoiCandidate` missing and luma/center fallback still present), proving the new no-false-parity tests are active.
  - `python3 -m unittest tests.test_android_roi_parity_contract -v` currently fails on missing bridge/domain/CSV/runtime contract items and should drive the next implementation slices.
- Current environment limitation: `/home/jio/code/auto_titration` is not a git repository, so worker commits cannot be created in this workspace; report exact files and command evidence instead.

---

## File structure and responsibilities

- Modify `mobile/android/app/build.gradle.kts`: add Android inference runtime dependency and model asset packaging checks.
- Create `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/RoiMask.kt`: Android equivalent of Windows `RoiMask` plus JSON helpers.
- Create `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/RoiDetectionResult.kt`: Android equivalent of Windows `RoiDetectionResult` and settings/result snapshots.
- Create `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/MaskOps.kt`: nearest-mask resize, largest component, smoothing, bbox, centroid, clamp helpers.
- Create `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/YoloSegmentationDetector.kt`: Android YOLO segmentation parser/detector for the pinned TFLite tensor contract with Windows-compatible reason strings.
- Create `mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/ThermalRoiDetector.kt`: Android raw-matrix contrast ROI detector equivalent to Windows `auto_detect_thermal_roi`.
- Create `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/AndroidRoiSelectionState.kt`: pending request queue, lock/recording guards, current/stale result checks, mask reuse behavior.
- Create `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/AndroidAutoRoiWorker.kt`: latest-only background worker for YOLO/thermal candidates.
- Modify `mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt`: replace luma candidate route with Windows-compatible candidate request/apply flow; attach masks to live/session payloads.
- Modify `mobile/android/app/src/main/java/kr/auto/titration/mobile/AndroidBridge.kt`: add `requestAutoRoiCandidate(target)` and optional `autoRoiStatus()` bridge methods.
- Modify `website/android-webview.js`: route ROI candidate button to the new bridge and apply Windows-compatible payload keys.
- Modify session/data classes under `mobile/android/app/src/main/java/kr/auto/titration/mobile/data/` and `session/`: persist mask/thermal raw fields into CSV rows.
- Add/extend tests listed in `.omx/plans/test-spec-android-windows-feature-parity-20260531T064356Z.md`.

## Implementation tasks

### Task 1: Lock failing parity tests before production edits

**Files:**
- Modify: `tests/test_android_mobile_roi.py`
- Modify: `tests/test_android_webview_mini2.py`
- Modify: `tests/test_android_scaffold.py`

- [ ] Add static regression tests that fail on current Android luma/center path:
  - `test_android_roi_candidate_button_uses_auto_candidate_bridge_not_luma_center`
  - `test_android_defines_windows_equivalent_mask_and_detection_models`
  - `test_android_live_payload_exposes_mask_metadata_like_windows`
- [ ] Run `python3 -m unittest tests.test_android_mobile_roi -v`.
- [ ] Expected before implementation: FAIL because Android has no mask models/auto-candidate bridge and still uses `autoSetRoi` luma/default behavior.

### Task 2: Add Android ROI/mask domain models

**Files:**
- Create: `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/RoiMask.kt`
- Create: `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/RoiDetectionResult.kt`
- Create: `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/MaskOps.kt`
- Add JVM tests under `mobile/android/app/src/test/java/kr/auto/titration/mobile/vision/`

- [ ] Write tests for bbox, area, centroid, largest component, smoothing, and JSON field names matching Windows payload.
- [ ] Implement models and mask ops.
- [ ] Run targeted Gradle unit tests if test harness exists; otherwise use static Python tests plus `:app:compileDebugKotlin` through `:app:assembleDebug`.

### Task 3: Lock Android YOLO model/runtime artifact

**Files:**
- Modify: `mobile/android/app/build.gradle.kts`
- Create: `mobile/android/app/src/main/assets/models/yolo11n-seg-256-fp32.tflite`
- Create: `mobile/android/app/src/main/assets/models/yolo11n-seg-256-fp32.metadata.json`
- Modify: `tests/test_android_scaffold.py`

- [ ] Add a failing test that asserts Gradle pins `com.google.ai.edge.litert:litert:2.1.5`, not a `+` dependency.
- [ ] Add a failing test that asserts the APK assets include `models/yolo11n-seg-256-fp32.tflite` and `models/yolo11n-seg-256-fp32.metadata.json`.
- [ ] Export the Windows default model with: `yolo export model=yolo11n-seg.pt format=tflite imgsz=256 nms=False half=False int8=False`.
- [ ] Write metadata JSON containing `source_model: yolo11n-seg.pt`, `export_command`, `input_size: 256`, `accepted_classes: ["cup","bottle","wine glass","bowl","vase","beaker","flask","glass","container"]`, actual model class names, output tensor shapes, and SHA256.
- [ ] If the model cannot be exported/fetched, implementation must stop with `yolo_model_unavailable`; do not replace this with luma/center fallback.
- [ ] Keep `placeholder_model: true` metadata as a hard no-success gate until the exported `.tflite` is real; placeholder assets are allowed only to exercise honest `yolo_model_unavailable` behavior.
- [ ] Add/keep a validator surface with explicit names locked by tests: `VisibleRoiModelMetadata`, `YoloTensorContractValidator`, `LiteRtYoloSegmenter`, `validateTensorContract`, and `checkLiteRtDependencyCache`.
- [ ] Run `python3 -m unittest tests.test_android_roi_parity_contract -v`; expected before full implementation: RED on missing runtime/bridge/domain/CSV slices; expected after implementation: PASS with placeholder still returning no-success model errors.
- [ ] Run the scaffold tests; expected after implementation: PASS and model SHA256 reported.

### Task 4: Port visible YOLO segmentation semantics

**Files:**
- Create: `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/YoloSegmentationDetector.kt`
- Modify: `mobile/android/app/build.gradle.kts`
- Add model asset path under Android assets after exporting/placing model.
- Add tests under `mobile/android/app/src/test/java/kr/auto/titration/mobile/vision/YoloSegmentationDetectorTest.kt`

- [ ] Add tests for cup/beaker mask accepted, person/background rejected, box-only rejected, oversized rejected.
- [ ] Add inference runtime dependency and a detector wrapper that can be fixture-tested without loading a real model.
- [ ] Implement output parser only against a known fixture/model metadata; do not guess tensor order silently.
- [ ] Use Windows-compatible reason strings exactly.

### Task 5: Port thermal raw contrast ROI semantics

**Files:**
- Create: `mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/ThermalRoiDetector.kt`
- Modify: `mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt` if raw matrix exposure needs a stable getter.
- Add tests under `mobile/android/app/src/test/java/kr/auto/titration/mobile/thermal/ThermalRoiDetectorTest.kt`

- [ ] Add flat matrix and contrast blob tests.
- [ ] Implement median/std threshold, smoothing/largest-component, bbox padding, confidence/source fields matching Windows.
- [ ] Return blocker/no-candidate when raw matrix is unavailable; never call center ROI thermal success.

### Task 6: Port ROI state queue, stale guards, and latest-only worker

**Files:**
- Create: `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/AndroidRoiSelectionState.kt`
- Create: `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/AndroidAutoRoiWorker.kt`
- Modify: `MainActivity.kt` to own the state/worker lifecycle.

- [ ] Test pending request queue waits for required visible/thermal frame availability.
- [ ] Test locked/recording state rejects candidate application.
- [ ] Test settings-generation and result-age stale rejection.
- [ ] Implement latest-only queue so YOLO never runs in CameraX analyzer hot path.

### Task 7: Replace Android luma candidate bridge with Windows-compatible bridge payload

**Files:**
- Modify: `AndroidBridge.kt`
- Modify: `MainActivity.kt`
- Modify: `website/android-webview.js`

- [ ] Add `requestAutoRoiCandidate(targetJsonOrString)` bridge method.
- [ ] Keep `autoSetRoi` only as deprecated compatibility or map it to the new candidate request with explicit non-parity fallback disabled.
- [ ] Make immediate bridge response match Windows `/api/roi-auto-candidate` top-level shape exactly: `ok`, `target`, `applied_now`, `reason`, `confidence`, and nested `roi`.
- [ ] Also include live/status fields inside the nested `roi`/status payload: `pending_auto_candidate_requests`, `pending_auto_candidate_target`, `auto_roi_result_status`, `auto_roi_result_reason`, `visible_roi_shape`, `thermal_roi_shape`, mask fields, and ROI strings.
- [ ] Change ROI button handler to call new bridge, not `autoSetRoi`.

### Task 8: Port mask feature extraction and CSV fields

**Files:**
- Modify: `mobile/android/app/src/main/java/kr/auto/titration/mobile/vision/VisibleFeatureExtractor.kt`
- Modify: `mobile/android/app/src/main/java/kr/auto/titration/mobile/data/StandaloneFeatureFrame.kt`
- Modify: `mobile/android/app/src/main/java/kr/auto/titration/mobile/session/PhoneRunSession.kt`
- Modify: `mobile/android/app/src/main/java/kr/auto/titration/mobile/export/SessionExporter.kt`

- [ ] Add tests proving visible mask features use mask pixels, not bbox rectangle.
- [ ] Add tests proving raw thermal mask features use mask pixels and remain raw/unverified.
- [ ] Add CSV columns matching Windows mask fields and pump/thermal status fields.

### Task 9: Full verification and APK delivery

**Files:**
- Build output: `mobile/android/app/build/outputs/apk/debug/app-debug.apk`
- Copy to: `/mnt/c/Users/Jio/Downloads/auto-titration-android-windows-parity-20260531.apk`

- [ ] Run `python3 -m unittest tests.test_android_roi_parity_contract tests.test_android_mobile_roi tests.test_android_webview_mini2 tests.test_android_scaffold tests.test_website_assets tests.test_windows_live_collect tests.test_mobile_protocol tests.test_mobile_bridge -v`.
- [ ] Run `node --check website/android-webview.js`.
- [ ] Run `python3 -m unittest discover -v`.
- [ ] Run Gradle lint/build with local JDK/SDK env.
- [ ] Copy APK to Windows Downloads.
- [ ] Report SHA256 and honest device-test limitations.

## Self-review
- Spec coverage: ROI candidate, mask metadata, thermal raw ROI, async worker, WebView bridge, CSV, pump/session audit covered.
- Placeholder scan: no implementation step is allowed to claim parity without fixture tests and build verification.
- Type consistency: Kotlin names mirror Windows concepts: `RoiMask`, `RoiDetectionResult`, `AutoRoiSettingsSnapshot`, `AutoRoiWorkerResult`, `AndroidRoiSelectionState`.

## External evidence used for runtime/model choice
- Google AI Edge LiteRT Android docs list `com.google.ai.edge.litert:litert:2.1.5` and show Kotlin APIs for running `.tflite` models on Android.
- Ultralytics export docs support exporting segmentation models to TFLite; segmentation exports expose detection and prototype tensors that must be pinned in metadata before parsing.

## ADR / runtime alternatives

**Decision:** Use Google AI Edge LiteRT `com.google.ai.edge.litert:litert:2.1.5` with packaged `models/yolo11n-seg-256-fp32.tflite` and metadata/SHA256 validation.

**Drivers:** phone-local parity, YOLO segmentation/mask equivalence, build/test repeatability.

**Rejected alternatives:**
- LiteRT 1.4.2 Interpreter as primary: lacks newer CompiledModel path; only fallback if 2.1.5 fails after explicit evidence.
- Legacy `org.tensorflow:tensorflow-lite`: stale API/package direction and duplicate-class risk.
- ONNX Runtime Mobile: separate runtime/export path and larger parity surface.
- NCNN: native/C++ integration risk in already native-heavy APK.
- MediaPipe Tasks: hides custom YOLO mask filtering/reason strings.
- Remote laptop `/api/roi-auto-candidate`: not phone-local APK parity.
- Luma/center heuristic: explicitly rejected by Windows behavior and false-selection history.

## Dependency prefetch before offline build

Run once without `--offline` after adding LiteRT:

```bash
JAVA_HOME=/home/jio/code/auto_titration/.tools/jdk/jdk-21.0.11+10 \
ANDROID_HOME=/home/jio/code/auto_titration/.tools/android-sdk \
ANDROID_SDK_ROOT=/home/jio/code/auto_titration/.tools/android-sdk \
GRADLE_USER_HOME=/home/jio/code/auto_titration/.gradle-cache \
/home/jio/code/auto_titration/.tools/gradle/gradle-8.10.2/bin/gradle \
  -p mobile/android :app:dependencies :app:assembleDebug
```

Then assert cache before final offline build:

```bash
find .gradle-cache/caches/modules-2/files-2.1 -path '*com.google.ai.edge.litert*litert*2.1.5*' -print -quit
```

## No-false-parity gate

Do not report Android Windows parity if `roiCandidateButton` still calls `autoSetRoi`, if the CameraX hot analyzer still invokes `detectVisibleRoiCandidate(imageProxy)` for parity auto-candidate, if center/default ROI is reported as auto-candidate success, if mask fields are emitted without a real `RoiMask`, or if YOLO success appears without a packaged model/runtime/tensor contract.
