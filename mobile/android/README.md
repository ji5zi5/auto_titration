# Auto Titration Android WebView Runtime

This Android project now uses the **existing web dashboard UI** from `website/` inside a local `WebView`. Native Android code owns permissions and hardware for a phone-only Standalone runtime, then exposes phone-local state to the page through `window.AutoTitrationAndroid`.

## What this app owns now

- **WebView UI parity**: `MainActivity` loads `file:///android_asset/index.html`; Gradle packages `../../website` as app assets, so the mobile screen uses the same dashboard layout as the web UI instead of a separate native mock layout.
- **Android JavaScript bridge**: `AndroidBridge` exposes `getStatusJson`, `probeMini2`, `startNewRun`, `lockRoi`, `startRecording`, `stopRecording`, and `csvPreviewJson` to `website/android-webview.js`.
- **CameraX visible analysis**: native `MainActivity` requests camera permission, runs CameraX `ImageAnalysis`, extracts RGB/HSV ROI features, and records rows into a local `PhoneRunSession`.
- **USB host Mini2 probe**: `Mini2UsbProbe` searches HIKMICRO vendor ID `0x2bdf` with vendor-tolerant product matching, uses an explicit package-scoped immutable `PendingIntent`, and reports permission/device evidence back to the WebView.
- **Private HIKMICRO native backend gate**: the APK packages ARM64 libraries extracted from the analyzed HIKMICRO Viewer APK (`libHCUSBSDK.so`, `lib_thermal_module.so`, `libMicroJITA_Release_v8a.so`, `libMicroTA_Release_v8a.so`, `libMTlib.so`, `libuvc.so`, and related dependencies) under `jniLibs/arm64-v8a` for local feasibility testing.
- **CSV/session ownership**: `PhoneRunSession` records pump-derived `injected_volume_ml`, equivalence distance, RGB/HSV features, thermal status, and sync fields into phone-local rows for export.
- **Chemistry/ML/pump contracts**: chemistry presets, stoichiometric equivalence calculations, JSON ML model contracts, and manual-only pump commands are represented on-device.
- **Legacy bridge kept for compatibility**: `MobileFeatureClient` still documents the old `mobile_feature_frame.v1` `/api/mobile/ingest` bridge, but it is no longer the phone-local runtime owner.


## Current next task: Mini2 official-app call path first

Do not continue with UI polish, YOLO ROI, CSV expansion, Bluetooth, or Android ML before the Mini2 stream path is proven. The next Android task is to reverse-analyze the official HIKMICRO APK/XAPK and reproduce only the minimum Mini2 call sequence in this app.

Target sequence to recover:

```text
USB permission
→ HCUSBSDK init
→ device enum/register/login
→ F2/Mini2 module type setup
→ stream parameter setup
→ USB_StartStreamCallback or equivalent
→ frame callback
→ thermal processing to int temperature matrix
→ compare against official app or Windows DLL output
```

Use `docs/hikmicro_apk_androguard_summary.txt`, JADX/apktool/androguard for Java-side call paths, Ghidra/IDA for native symbols/strings, and logcat or dynamic tracing if available. The goal is not to copy the official app wholesale; the goal is to identify and implement the minimum Mini2 stream and temperature conversion path needed for this project. Until that path is validated, keep Celsius blocked as `thermal_calibrated=false` / `raw_unverified`.

## Important calibration rule

The Android app must not fake temperature. HIKMICRO native libraries can be loaded and the USB backend can be probed, but Celsius is still blocked until live Mini2 frames and fixture-vs-official conversion validation pass on the target phone. Until then, the app reports `thermal_calibrated=false` with `raw_unverified` or `blocked` evidence and leaves Celsius fields blank.

## Pump rule

The current Arduino firmware contract is the simple serial command set: `a` = retract/pull, `b` = inject/push, `c` = stop. Android pump work must match those commands unless the firmware is intentionally changed. ML/equivalence status must never send automatic stop commands; the user still starts and stops pumping manually from the UI.

## Development notes

Open `mobile/android` in Android Studio or build with the repo-local Gradle/JDK/Android SDK tools. This APK is a phone-local WebView runtime scaffold with Android permissions, CameraX feature extraction, Mini2 USB permission repair, and HIKMICRO native-library load gates. The F2 Mini2 probe uses the official-app module-profile shape recovered for the live Mini2 path (`256x344`, `25fps`, thermal coding `12`, stream type `103`); live raw streaming and calibrated Celsius still require phone hardware smoke validation.
