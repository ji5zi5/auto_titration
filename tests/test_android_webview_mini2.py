from pathlib import Path
import json
import re
import unittest


ANDROID_ROOT = Path("mobile/android")
JAVA_ROOT = ANDROID_ROOT / "app/src/main/java/kr/auto/titration/mobile"
WEBSITE_ROOT = Path("website")


class AndroidWebViewMini2Tests(unittest.TestCase):
    def test_android_runtime_loads_existing_website_in_webview(self):
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        bridge = (JAVA_ROOT / "AndroidBridge.kt").read_text(encoding="utf-8")
        gradle = (ANDROID_ROOT / "app/build.gradle.kts").read_text(encoding="utf-8")
        index = (WEBSITE_ROOT / "index.html").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertIn("WebView", main)
        self.assertIn("file:///android_asset/index.html", main)
        self.assertIn("addJavascriptInterface", main)
        self.assertIn("AutoTitrationAndroid", main)
        self.assertIn("TRUSTED_WEBVIEW_ASSET_PREFIX", main)
        self.assertIn("shouldOverrideUrlLoading", main)
        self.assertIn("blockUntrustedWebViewNavigation", main)
        self.assertIn('url.startsWith(TRUSTED_WEBVIEW_ASSET_PREFIX)', main)
        self.assertIn('removeJavascriptInterface("AutoTitrationAndroid")', main)
        self.assertIn("settings.allowContentAccess = false", main)
        self.assertIn("settings.allowFileAccessFromFileURLs = false", main)
        self.assertIn("settings.allowUniversalAccessFromFileURLs = false", main)
        self.assertIn("sourceSets", gradle)
        self.assertIn("../../website", gradle)
        self.assertIn("android-webview.js", index)
        self.assertIn("window.AutoTitrationAndroid", adapter)
        self.assertIn("@JavascriptInterface", bridge)
        self.assertNotIn("LinearLayout", main)
        self.assertNotIn("Button", main)

    def test_webview_bridge_exposes_android_permissions_hardware_without_server_pairing(self):
        bridge = (JAVA_ROOT / "AndroidBridge.kt").read_text(encoding="utf-8")
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        for method in [
            "getStatusJson",
            "probeMini2",
            "pumpStatus",
            "sendPumpCommand",
            "startNewRun",
            "lockRoi",
            "startRecording",
            "stopRecording",
            "csvPreviewJson",
            "saveCsvToDownloads",
        ]:
            self.assertIn(f"fun {method}", bridge)

        self.assertIn("ActivityResultContracts.RequestPermission", main)
        self.assertIn("onPermissionRequest", main)
        self.assertIn("PermissionRequest.RESOURCE_VIDEO_CAPTURE", main)
        self.assertIn("replaceButtonHandler", adapter)
        self.assertIn("Mini2 USB 확인", adapter)
        self.assertIn("펌프 BT 상태", adapter)
        self.assertIn("Android WebView", adapter)

    def test_android_csv_download_button_saves_phone_local_csv_to_downloads(self):
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        bridge = (JAVA_ROOT / "AndroidBridge.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertIn("fun saveCsvToDownloads", bridge)
        self.assertIn("fun saveCsvToDownloadsFromBridge", main)
        self.assertIn("SessionExporter.buildCsv", main)
        self.assertIn("MediaStore.Downloads.EXTERNAL_CONTENT_URI", main)
        self.assertIn("auto-titration-android-run-", main)
        self.assertIn("csvDownloadLink", adapter)
        self.assertIn("calcCsvDownloadLink", adapter)
        self.assertIn("saveCsvToDownloads", adapter)
        self.assertIn("saveAndroidCsvToDownloads", adapter)
        self.assertIn("saveAndroidCsvToDownloads({ auto: true })", adapter)
        self.assertIn("CSV 자동 저장 중", adapter)
        self.assertIn("event.preventDefault()", adapter)
        self.assertIn("CSV 저장 완료", adapter)
        for token in [
            'payload.put("csv_export", exportJson)',
            '.put("display_name", fileName)',
            '.put("uri", uri.toString())',
            '.put("bytes", csvText.toByteArray(Charsets.UTF_8).size)',
            '?.put("export_file_name", fileName)',
            '?.put("export_uri", uri.toString())',
            'payload.csv_export || {}',
        ]:
            with self.subTest(export_payload_token=token):
                self.assertIn(token, main + adapter)

    def test_modern_android_usb_permission_is_explicit_mutable_and_vendor_tolerant(self):
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")
        device_filter = (ANDROID_ROOT / "app/src/main/res/xml/mini2_device_filter.xml").read_text(encoding="utf-8")

        self.assertIn("Intent(USB_PERMISSION_ACTION).setPackage(context.packageName)", probe)
        self.assertIn("PendingIntent.FLAG_MUTABLE", probe)
        self.assertIn("PendingIntent.FLAG_UPDATE_CURRENT", probe)
        self.assertNotIn("PendingIntent.FLAG_IMMUTABLE", probe)
        self.assertIn("UsbManager.EXTRA_PERMISSION_GRANTED", probe)
        self.assertIn("UsbManager.EXTRA_DEVICE", probe)
        self.assertIn("findMini2Candidate", probe)
        self.assertIn("knownMini2ProductIds", probe)
        self.assertIn("requestPermissionIfMissing", probe)
        self.assertIn('vendor-id="11231"', device_filter)
        self.assertNotIn("product-id", device_filter)

    def test_hikmicro_android_libraries_are_packaged_and_temperature_is_honest(self):
        jni_root = ANDROID_ROOT / "app/src/main/jniLibs/arm64-v8a"
        expected_libs = [
            "libc++_shared.so",
            "libjpeg.so",
            "libcrypto.so",
            "libifrgisp.so",
            "libColorAlarm_PcProc.so",
            "libtvf.so",
            "libtsr_v2.0.0.so",
            "libacnn_v2.3.4.so",
            "libomp.so",
            "libxml2.so",
            "libHwCodecer.so",
            "libRID_ANDROID_V1.0.6_BUILD_20250312.so",
            "libHCUSBSDK.so",
            "lib_thermal_module.so",
            "libMicroJITA_Release_v8a.so",
            "libMicroTA_Release_v8a.so",
            "libMTlib.so",
            "libusbCam_host.so",
            "libuvc.so",
            "libusb-1.0.so",
            "libhikdsp.so",
            "libdadsp.so",
        ]
        for lib in expected_libs:
            with self.subTest(lib=lib):
                self.assertTrue((jni_root / lib).is_file(), f"missing packaged {lib}")

        backend = (JAVA_ROOT / "thermal/HikmicroNativeBackend.kt").read_text(encoding="utf-8")
        conversion = (JAVA_ROOT / "thermal/HikmicroTemperatureConversionAttempt.kt").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")

        for token in ["System.loadLibrary", "libHCUSBSDK.so", "libMTlib.so", "MT_Gray2Temp", "grayToTemperature"]:
            self.assertIn(token, backend + conversion)
        self.assertIn("net.java.dev.jna:jna:5.18.1@aar", (ANDROID_ROOT / "app/build.gradle.kts").read_text(encoding="utf-8"))
        self.assertIn('"libc++_shared.so"', backend)
        self.assertIn('"libjpeg.so"', backend)
        self.assertIn("raw_unverified", backend + conversion + probe)
        self.assertIn("liveStreamObserved = false", backend + conversion)
        self.assertIn("fixtureCompared = false", backend + conversion)
        self.assertIn("NoFakeCelsiusGuard", conversion)
        self.assertNotIn("temperatureCelsius = raw", backend + conversion + probe)

    def test_android_webview_does_not_boot_browser_streams_before_native_bridge(self):
        app = (WEBSITE_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn("function isAndroidWebViewBridge()", app)
        self.assertIn("if (isAndroidWebViewBridge())", app)
        self.assertIn("Android WebView bridge 연결 중", app)
        self.assertIn("return;", app[app.index("if (isAndroidWebViewBridge())"):])

    def test_android_camera_preview_is_pushed_into_existing_web_ui(self):
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertIn("latestVisiblePreviewDataUrl", main)
        self.assertIn("buildVisiblePreviewDataUrl", main)
        self.assertIn("Bitmap.createBitmap", main)
        self.assertIn("Base64.NO_WRAP", main)
        self.assertIn("visible_preview_data_url", main)
        self.assertIn("visible_preview_data_url", adapter)
        self.assertIn("visiblePreview", adapter)

    def test_android_camera_preview_uses_color_yuv_planes_not_luma_only(self):
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")

        self.assertIn("imageProxy.planes[1]", main)
        self.assertIn("imageProxy.planes[2]", main)
        self.assertIn("previewYuvToArgb", main)
        self.assertNotIn("luminance shl 16", main)

    def test_android_camera_preview_uses_camerax_rotation_and_maps_roi_coordinates(self):
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")

        self.assertIn("imageProxy.imageInfo.rotationDegrees", main)
        self.assertIn("normalizedRotationDegrees", main)
        self.assertIn("buildVisiblePreviewDataUrl(imageProxy, rotationDegrees = rotationDegrees)", main)
        self.assertIn("rotatedFrameWidth", main)
        self.assertIn("rotatedFrameHeight", main)
        self.assertIn("visible_preview_rotation_degrees", main)
        self.assertIn("visible_preview_width", main)
        self.assertIn("visible_preview_height", main)
        self.assertIn("sensorRoiToDisplayRoi", main)
        self.assertIn("displayRoiToSensorRoi", main)
        self.assertIn("latestVisiblePreviewWidth", main)
        self.assertIn("latestVisiblePreviewHeight", main)

    def test_hikmicro_libraries_load_from_android_native_library_dir_on_arm64(self):
        backend = (JAVA_ROOT / "thermal/HikmicroNativeBackend.kt").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")
        gradle = (ANDROID_ROOT / "app/build.gradle.kts").read_text(encoding="utf-8")

        self.assertIn("nativeLibraryDir", backend)
        self.assertIn("System.load(", backend)
        self.assertIn("Build.SUPPORTED_ABIS", backend)
        self.assertIn("context.applicationInfo.nativeLibraryDir", probe)
        self.assertIn('abiFilters += "arm64-v8a"', gradle)

    def test_android_status_polling_keeps_retrying_mini2_without_reopening_app(self):
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")

        self.assertIn("MINI2_AUTO_RETRY_INTERVAL_MS", main)
        self.assertIn("shouldAutoRetryMini2", main)
        self.assertIn("requestPermissionIfMissing = mini2AutoRetry", main)
        self.assertIn("forcePermissionRequest", probe)
        self.assertIn("requestPermissionOnce(mini2, forcePermissionRequest)", probe)
        self.assertIn("FRAME_WAIT_TIMEOUT_MS", stream)
        self.assertIn("restart stalled HIKMICRO stream attempt", stream)
        self.assertIn("startedElapsedMs", stream)
        self.assertIn("window.setInterval(pollAndroidStatus, 1000)", adapter)

    def test_android_status_polling_does_not_crash_app_when_native_probe_fails(self):
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")

        self.assertIn("safeBuildStatusJson", main)
        self.assertIn("status_build_failed", main)
        self.assertIn("catch (error: Throwable)", main)
        self.assertIn("attemptRawStream = false", main)
        self.assertIn("safeRawStreamStatus", probe)
        self.assertIn("safeProbeStatus", probe)
        self.assertIn("Mini2 official HCUSBSDK/JNI stream is not started by passive status polling", probe)
        self.assertNotIn("Mini2 raw JNA stream is not auto-started", probe)
        self.assertIn("raw_stream_exception", probe)
        self.assertIn("catch (error: Throwable)", probe)

    def test_android_native_stream_probe_is_manual_one_shot_not_polling_loop(self):
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")

        self.assertIn("lastExplicitMini2Probe", main)
        self.assertIn("native_stream_manual_one_shot", main + adapter)
        self.assertIn("attemptRawStream = false", main)
        self.assertIn("attemptRawStream = true", main)
        self.assertNotIn("mini2RawStreamEnabled = true", main)
        self.assertIn("safePassiveRawStreamStatus", probe)
        self.assertIn("HikmicroJnaMini2Stream.peekActiveStatus", probe)
        self.assertIn("fun peekActiveStatus", stream)
        self.assertIn("passive_status_peek", stream)
        self.assertIn("passive_peek_stalled_stale_frame", stream)
        self.assertIn("isActiveMini2Peek", main)
        self.assertIn("val rawStream = if (isActiveMini2Peek(currentRawStream)) currentRawStream else explicitRawStream", main)
        self.assertIn('put("last_stream_attempt", explicitRawStream)', main)

    def test_android_webview_requires_manual_mini2_probe_after_usb_permission(self):
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        prompt_fn = adapter[
            adapter.index("function maybePromptManualMini2Probe"):
            adapter.index("  function applyBridgePayload")
        ]

        self.assertIn("mini2ManualProbePromptShown", adapter)
        self.assertIn("mini2?.mini2_usb_permission === true", adapter)
        self.assertIn("수동 확인 필요", prompt_fn)
        self.assertIn("크래시 위험 때문에 자동 실행하지 않습니다", prompt_fn)
        self.assertNotIn("readBridgeJson('probeMini2')", prompt_fn)
        self.assertNotIn("setTimeout(() =>", prompt_fn)
        self.assertLess(
            adapter.index("showAndroidThermalPlaceholder(payload.mini2 || {}, payload.live || {})"),
            adapter.index("maybePromptManualMini2Probe(payload);", adapter.index("function applyBridgePayload")),
            "UI should render passive status first, then prompt for manual official probe",
        )
        self.assertLess(
            adapter.index("setAndroidText('previewStatus', `${ANDROID_LABEL}"),
            adapter.index("maybePromptManualMini2Probe(payload);", adapter.index("function applyBridgePayload")),
            "manual Mini2 prompt must be the final visible status update, not overwritten by generic status text",
        )

    def test_android_mini2_diagnostic_copy_forces_probe_when_last_export_is_passive_only(self):
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        copy_handler = adapter[
            adapter.index("replaceButtonHandler('mini2CopyDiagnosticButton'"):
            adapter.index("  replaceButtonHandler('roiSetupButton'")
        ]

        self.assertIn("manual_probe_not_run_passive_status_guard", adapter)
        self.assertIn("let latestMini2DiagnosticExport", adapter)
        self.assertIn("function shouldRunMini2ProbeBeforeDiagnosticCopy", adapter)
        self.assertIn("runManualMini2Probe('diagnostic_copy')", copy_handler)
        self.assertIn("readBridgeJson('probeMini2')", adapter)
        self.assertLess(
            copy_handler.index("runManualMini2Probe('diagnostic_copy')"),
            copy_handler.index("navigator.clipboard"),
            "copying a passive-only diagnostic should run the explicit one-shot Mini2 probe before exporting",
        )

    def test_android_crash_report_is_saved_and_exposed_after_restart(self):
        crash_store = JAVA_ROOT / "AndroidCrashLogStore.kt"
        self.assertTrue(crash_store.is_file(), "missing Android crash log store")
        crash = crash_store.read_text(encoding="utf-8")
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        bridge = (JAVA_ROOT / "AndroidBridge.kt").read_text(encoding="utf-8")
        index = (WEBSITE_ROOT / "index.html").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertIn("Thread.setDefaultUncaughtExceptionHandler", crash)
        self.assertIn("last-crash.txt", crash)
        self.assertIn("AndroidCrashLogStore.install", main)
        self.assertIn("last_crash_report", main)
        self.assertIn("getCrashReport", bridge)
        self.assertIn("crashDownloadLink", index + adapter)

    def test_failed_hikmicro_library_loads_retry_instead_of_staying_cached_forever(self):
        backend = (JAVA_ROOT / "thermal/HikmicroNativeBackend.kt").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")

        self.assertIn("NATIVE_LOAD_RETRY_INTERVAL_MS", backend)
        self.assertIn("cachedReportLoadedAtMs", backend)
        self.assertIn("forceRetry", backend)
        self.assertIn("!cached.allLoaded", backend)
        self.assertIn("forceNativeLoad", probe)

    def test_webview_header_is_removed_but_status_remains_visible(self):
        index = (WEBSITE_ROOT / "index.html").read_text(encoding="utf-8")
        styles = (WEBSITE_ROOT / "styles.css").read_text(encoding="utf-8")
        manifest = (ANDROID_ROOT / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        app_theme = (ANDROID_ROOT / "app/src/main/res/values/styles.xml").read_text(encoding="utf-8")

        self.assertNotIn("app-topbar", index + styles)
        self.assertNotIn("app-brand", index + styles)
        self.assertIn('id="previewStatus"', index)
        self.assertIn("status-strip", index)
        self.assertIn("toast-notice", styles)
        self.assertNotIn("top: 76px", styles)
        self.assertIn('android:theme="@style/AppTheme"', manifest)
        self.assertIn("Theme.Material.Light.NoActionBar", app_theme)
        self.assertIn("android:windowNoTitle", app_theme)

    def test_usb_permission_lifecycle_is_observable_and_retryable(self):
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")

        self.assertIn("startMonitoring", main + probe)
        self.assertIn("stopMonitoring", main + probe)
        self.assertIn("BroadcastReceiver", probe)
        self.assertIn("ACTION_USB_DEVICE_ATTACHED", probe)
        self.assertIn("ACTION_USB_DEVICE_DETACHED", probe)
        self.assertIn("EXTRA_PERMISSION_GRANTED", probe)
        self.assertIn("ContextCompat.registerReceiver", probe)
        self.assertIn("permission_request_count", probe)
        self.assertIn("mini2_permission_state", probe)
        self.assertIn("last_usb_event", probe)

    def test_mini2_raw_stream_status_is_explicit_blocker_until_native_stream_is_proven(self):
        status_model = (JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")
        backend = (JAVA_ROOT / "thermal/HikmicroNativeBackend.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        index = (WEBSITE_ROOT / "index.html").read_text(encoding="utf-8")
        styles = (WEBSITE_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn("blocked_no_stream_entrypoint", status_model + probe)
        self.assertIn("raw_stream_status", status_model + probe)
        self.assertIn("native_symbol_discovery", status_model + backend + probe)
        self.assertIn("frame_counter", status_model)
        self.assertIn("thermal_preview_data_url", status_model)
        self.assertNotIn("temperature_avg_c", status_model + probe)
        self.assertIn("showAndroidThermalPlaceholder", adapter)
        self.assertIn("적외선 화면 대기", adapter)
        self.assertIn("Mini2 연결 재시도 중", adapter)
        self.assertNotIn("Mini2 native stream blocker</text>", adapter)
        self.assertIn("mini2DebugLabel", index + adapter)
        self.assertIn("splitSvgLines", adapter)
        self.assertIn("escapeSvgText", adapter)
        self.assertIn("overflow-wrap: anywhere", styles)


    def test_mini2_raw_stream_uses_exact_official_f2_facade_structure(self):
        gradle = (ANDROID_ROOT / "app/build.gradle.kts").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")
        stream_path = JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt"
        f2_root = ANDROID_ROOT / "app/src/main/java/com/hik/f2module"
        jna_root = ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/jna"
        interface_root = ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface"

        self.assertTrue(stream_path.is_file(), "missing app adapter")
        self.assertTrue((f2_root / "F2UsbModuleApi.kt").is_file(), "missing exact F2UsbModuleApi facade")
        self.assertTrue((f2_root / "F2UsbModuleHelper.kt").is_file(), "missing exact F2UsbModuleHelper facade")
        self.assertTrue((jna_root / "HCUSBSDK.kt").is_file(), "missing exact HCUSBSDK singleton facade")
        self.assertTrue((jna_root / "HCUSBSDKByJNA.kt").is_file(), "missing exact HCUSBSDKByJNA binding")
        self.assertTrue((interface_root / "USB_USER_LOGIN_INFO.kt").is_file())
        self.assertTrue((interface_root / "USB_DEVICE_REG_RES.kt").is_file())

        stream = stream_path.read_text(encoding="utf-8")
        helper = (f2_root / "F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        api = (f2_root / "F2UsbModuleApi.kt").read_text(encoding="utf-8")
        jna = (jna_root / "HCUSBSDKByJNA.kt").read_text(encoding="utf-8")

        self.assertIn("net.java.dev.jna:jna:5.18.1", gradle)
        self.assertIn("HikmicroJnaMini2Stream.ensureStreaming", probe)
        self.assertIn("F2UsbModuleApi.INSTANCE", stream)
        self.assertIn("F2UsbModuleHelper.INSTANCE", stream)
        self.assertIn("latestFrameSnapshot", stream)
        self.assertIn("thermal_preview_data_url", stream)
        self.assertIn("USB_FRAME_INFO", helper)
        for token in ["USB_Init", "USB_Login", "USB_StartStreamCallback", "USB_DEVICE_INFO", "USB_USER_LOGIN_INFO", "USB_DEVICE_REG_RES"]:
            self.assertIn(token, helper + jna)

    def test_mini2_routes_official_f1_f2_backends_by_vid_pid(self):
        route = (JAVA_ROOT / "thermal/HikmicroMini2ModuleType.kt").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")
        f1_stream = (JAVA_ROOT / "thermal/HikmicroF1Mini2Stream.kt").read_text(encoding="utf-8")
        f2_stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")
        f2_helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        device_filter = (ANDROID_ROOT / "app/src/main/res/xml/mini2_device_filter.xml").read_text(encoding="utf-8")

        self.assertIn("11231:320 -> F1 _thermal_module", route)
        self.assertIn("11231:258/257(F2)", route)
        self.assertIn("HIKMICRO_F2_ALT_VENDOR_ID = 0x20af", route)
        self.assertIn("HikmicroF1Mini2Stream.ensureStreaming", probe)
        self.assertIn("HikmicroJnaMini2Stream.ensureStreaming", probe)
        self.assertIn("mini2_official_module_type", probe + adapter)
        self.assertIn("mini2_selected_backend", probe + adapter)
        self.assertIn("THERMAL_MSG_FOR_USB", f1_stream)
        self.assertIn("thermal_function_stream_realtime_init", f1_stream)
        self.assertIn("USB_SetPreviewEnable", f1_stream)
        self.assertIn("F2UsbModuleApi", f2_stream)
        self.assertIn("USB_StartStreamCallback", f2_helper)
        self.assertIn('vendor-id="8367"', device_filter)

    def test_mini2_full_official_package_class_inventory(self):
        expected = [
            "com/hcusbsdk/jna/HCUSBSDK.kt",
            "com/hcusbsdk/jna/HCUSBSDKByJNA.kt",
            "com/hcusbsdk/Interface/JavaInterface.kt",
            "com/hcusbsdk/Interface/USB_DEVICE_INFO.kt",
            "com/hcusbsdk/Interface/USB_FRAME_INFO.kt",
            "com/hcusbsdk/Interface/USB_USER_LOGIN_INFO.kt",
            "com/hcusbsdk/Interface/USB_DEVICE_REG_RES.kt",
            "com/hik/f2module/F2UsbModuleApi.kt",
            "com/hik/f2module/F2UsbModuleHelper.kt",
            "com/hik/viewercommon/data/device/api/callback/F2ModuleStreamCallback.kt",
            "com/hik/viewer/manager/PreviewManagerII.kt",
        ]
        for rel in expected:
            with self.subTest(rel=rel):
                self.assertTrue((ANDROID_ROOT / "app/src/main/java" / rel).is_file())

    def test_mini2_java_interface_official_shape_and_branching(self):
        java_interface = (ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/JavaInterface.kt").read_text(encoding="utf-8")

        for token in [
            "m_fnStreamCallBack",
            "m_fnStreamCallBack_jna",
            "m_fnStreamCallBack_jni",
            "m_iEnumType",
            "m_bInit",
            "USB_Init",
            "USB_Cleanup",
            "USB_GetLastError",
            "USB_GetDeviceCount(context: Context)",
            "USB_EnumDevices",
            "USB_EnumDevices_C",
            "USB_EnumDevices_Java",
            "USB_Login(loginInfo: USB_USER_LOGIN_INFO, deviceRegRes: USB_DEVICE_REG_RES)",
            "USB_SetVideoParam",
            "USB_StartStreamCallback",
            "USB_StartStreamCallback_jni",
            "lastStartStreamCallbackDetail",
            "USB_SetThermalStreamParam",
            "USB_SetThermalStreamCtrl",
            "USB_StopChannel",
            "USB_Logout",
        ]:
            self.assertIn(token, java_interface)

        self.assertLess(java_interface.index("USB_GetDeviceCount(context: Context)"), java_interface.index("USB_EnumDevices(count"))
        self.assertIn("if (m_iEnumType == ENUM_TYPE_JAVA)", java_interface)
        self.assertIn("arrayOfNulls<FStreamCallBack>(10_000)", java_interface)
        self.assertIn("m_iEnumType: Int = ENUM_TYPE_JAVA", java_interface)
        self.assertIn("val m_fnStreamCallBack_jna", java_interface)
        self.assertIn("val m_fnStreamCallBack_jni", java_interface)
        self.assertIn("com.hcusbsdk.jni.USB_FRAME_INFO?.toInterfaceFrame", java_interface)

    def test_mini2_dto_boundary_keeps_facade_strings_and_native_byte_arrays(self):
        facade = (ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/USB_DEVICE_INFO.kt").read_text(encoding="utf-8")
        jna = (ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/jna/HCUSBSDKByJNA.kt").read_text(encoding="utf-8")

        for token in [
            "var szManufacturer: String",
            "var szDeviceName: String",
            "var szSerialNumber: String",
            "var dwFd: Int",
        ]:
            self.assertIn(token, facade)
        for token in [
            "class USB_DEVICE_INFO : Structure()",
            "var szManufacturer: ByteArray",
            "var szDeviceName: ByteArray",
            "var szSerialNumber: ByteArray",
        ]:
            self.assertIn(token, jna)

    def test_mini2_f2_api_helper_own_official_state_and_call_order(self):
        api = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt").read_text(encoding="utf-8")
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")

        self.assertIn("class F2UsbModuleApi", api)
        self.assertIn("class F2UsbModuleHelper", helper)
        self.assertIn("val INSTANCE: F2UsbModuleHelper", helper)
        self.assertIn("fun openUsbModule", api)
        self.assertIn("F2UsbModuleApi.openUsbModule:start retryIndex=0", api)
        for token in ["sdkInited", "deviceInfoList", "userId", "channel"]:
            self.assertIn(token, helper)

        self.assertLess(
            api.index("helper.stopStreamPreview(context, streamingNew)"),
            api.index("helper.startStreamPreview"),
        )

        for forbidden in [
            "sdkInited",
            "deviceInfoList",
            "USB_Login(",
            "USB_GetDeviceCount",
            "class USB_DEVICE_INFO",
            "class USB_USER_LOGIN_INFO",
            "officialCallbackSlots",
            "m_fnStreamCallBack",
        ]:
            self.assertNotIn(forbidden, stream)

    def test_mini2_official_open_and_start_order_are_in_helper_facades(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        api = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt").read_text(encoding="utf-8")

        self.assertLess(helper.index("if (!sdkInited)"), helper.index("USB_GetDeviceCount(context)"))
        self.assertLess(helper.index("USB_GetDeviceCount(context)"), helper.index("USB_EnumDevices(count"))
        self.assertLess(helper.index("cleanupPreviousOfficialF2Login()"), helper.index("USB_Login(loginInfo"))
        self.assertIn("nativeEnum=count=", helper)
        open_slice = helper.split("fun openUsbDevice(", 1)[1].split("fun openUsbDevice(context: Context): Boolean", 1)[0]
        self.assertIn("val nativeEnumCount = runCatching { javaInterface.USB_GetDeviceCount() }.getOrDefault(-1)", open_slice)

        self.assertLess(api.index("helper.stopStreamPreview(context, streamingNew)"), api.index("helper.startStreamPreview"))
        start_slice = helper[helper.index("private fun startStreamPreviewCandidate"):]
        self.assertLess(start_slice.index("USB_SetVideoParam"), start_slice.index("USB_StartStreamCallback"))
        self.assertLess(start_slice.index("USB_StartStreamCallback"), start_slice.index("USB_SetThermalStreamParam"))
        self.assertLess(start_slice.index("USB_SetThermalStreamParam"), start_slice.index("Thread.sleep(100)"))
        self.assertLess(start_slice.index("Thread.sleep(100)"), start_slice.index("USB_SetThermalStreamCtrl"))

        for token in [
            "HIKMICRO_PREVIEW_WIDTH: Int = 256",
            "HIKMICRO_PREVIEW_HEIGHT: Int = 344",
            "HIKMICRO_FRAME_RATE: Int = 25",
            "HIKMICRO_THERMAL_VIDEO_CODING_TYPE: Int = 12",
            "HIKMICRO_OFFICIAL_MODULE_CONFIG_LABEL",
            "HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE: Int = 103",
            "dwStreamType = streamType",
        ]:
            self.assertIn(token, helper)

    def test_mini2_error29_regression_reconciles_official_thermal_coding_type_12(self):
        payload = json.loads(Path("error6.txt").read_text(encoding="utf-8"))
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        api = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt").read_text(encoding="utf-8")
        readme = (ANDROID_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("USB_StartStreamCallback=ok channel=0", payload["rawStageReport"])
        self.assertIn("USB_SET_THERMAL_STREAM_PARAM=failed command=2039 videoCodingType=12 error=29", payload["rawStageReport"])
        self.assertIn("HIKMICRO_PREVIEW_HEIGHT: Int = 344", helper)
        self.assertIn("HIKMICRO_THERMAL_VIDEO_CODING_TYPE: Int = 12", helper)
        self.assertNotIn("HIKMICRO_THERMAL_VIDEO_CODING_TYPE: Int = 8", helper)
        self.assertIn("mini2_f2_p20_256x344_thermal_type12", helper)
        self.assertIn("thermal coding `12`", readme)
        self.assertIn("videoCodingType: Int = HIKMICRO_THERMAL_VIDEO_CODING_TYPE", api)

    def test_mini2_stop_lifecycle_verifies_thermal_ctrl_before_stop_channel(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        java_interface = (ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/JavaInterface.kt").read_text(encoding="utf-8")
        jna = (ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/jna/HCUSBSDKByJNA.kt").read_text(encoding="utf-8")
        decompiled = Path(".omx/analysis/hikmicro_viewer_xapk/deep_callbacks_helpers_methods.txt").read_text(encoding="utf-8")

        official_stop = decompiled.split("## METHOD stopStreamPreview (Landroid/content/Context; Z)Z", 1)[1]
        self.assertIn("USB_GetThermalStreamCtrl", official_stop)
        self.assertIn("USB_SetThermalStreamCtrl2", official_stop)

        for token in [
            "USB_GetDeviceConfig",
            "USB_GetThermalStreamCtrl",
            "getThermalStreamCtrlState",
            "verifyThermalStreamCtrlDisabled",
            "OFFICIAL_STOP_THERMAL_CTRL_MAX_RETRIES",
            "streamEnable=",
            "retryIndex=",
            "USB_SetThermalStreamCtrl(false)#retry",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, helper + java_interface + jna)

        stop_slice = helper.split("fun stopStreamPreview(", 1)[1].split("fun closeSession", 1)[0]
        self.assertLess(stop_slice.index("setThermalStreamCtrl(currentUserId, enable = false)"), stop_slice.index("verifyThermalStreamCtrlDisabled"))
        self.assertLess(stop_slice.index("verifyThermalStreamCtrlDisabled"), stop_slice.index("USB_StopChannel"))

    def test_mini2_first_frame_wait_uses_official_patience_and_reuses_active_session(self):
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertIn("const val FRAME_WAIT_TIMEOUT_MS = 30_000L", stream)
        self.assertIn("STREAM_RETRY_INTERVAL_MS = 30_500L", stream)
        self.assertIn("active_session_reuse_no_restart", stream)
        self.assertIn("elapsedMs=$elapsed", stream)
        self.assertIn("MINI2_MANUAL_PROBE_MIN_INTERVAL_MS = 10000", adapter)

    def test_mini2_error8_regression_active_probe_uses_official_public_api_interface_route(self):
        payload = json.loads(Path("error8.txt").read_text(encoding="utf-8"))
        decompiled = Path(".omx/analysis/hikmicro_viewer_xapk/deep_f1_f2_key_methods.txt").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")

        self.assertEqual(payload["classification"], "thermal_stream_param_failed_error29_after_callback_ok")
        self.assertIn("videoCodingType=8 error=29", payload["rawStageReport"])
        self.assertTrue(payload["official_wrapper_parity"]["checks"]["startStreamPreviewJNA"])
        self.assertIn("## METHOD startStreamPreview (Lm2/a;)Lcom/hik/library/data/ApiResult;", decompiled)
        self.assertIn("getFStreamCallBack()Lcom/hcusbsdk/Interface/FStreamCallBack", decompiled)
        self.assertIn("F2UsbModuleHelper;->startStreamPreview(Lcom/hcusbsdk/Interface/FStreamCallBack;", decompiled)

        ensure_entry = stream.split("fun ensureStreaming(", 1)[1].split("fun peekActiveStatus", 1)[0]
        self.assertIn("f2Api.startStreamPreview(", ensure_entry)
        self.assertIn("callback = { frame -> captureOfficialF2Frame(frame) }", ensure_entry)
        self.assertNotIn("f2Api.startStreamPreviewJNA", ensure_entry)

    def test_mini2_error8_thermal_param_failure_is_official_nonfatal_after_callback_start(self):
        payload = json.loads(Path("error8.txt").read_text(encoding="utf-8"))
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertEqual(payload["startMode"], "official_jna_wrapper")
        self.assertTrue(payload["official_wrapper_parity"]["checks"]["startStreamPreviewJNA"])
        self.assertIn("USB_StartStreamCallback=ok channel=0", payload["rawStageReport"])
        self.assertIn("USB_SET_THERMAL_STREAM_PARAM=failed command=2039 videoCodingType=8 error=29", payload["rawStageReport"])

        self.assertIn("thermalParamSummary", helper)
        self.assertIn("USB_SET_THERMAL_STREAM_PARAM=failed_nonfatal", helper)
        self.assertIn("official_continue_after_thermal_param_result", helper)
        self.assertIn("thermalCtrlSummary", helper)
        self.assertIn("USB_SET_THERMAL_STREAM_CTRL=failed_nonfatal", helper)
        self.assertNotIn('lastFailureReason = "USB_SetThermalStreamParam failed error=$error"', helper)
        self.assertNotIn('stopCurrentChannelAfterStartFailure("thermal_param_failed")', helper)
        self.assertIn("thermal_stream_param_nonfatal_waiting_for_frame", adapter)
        self.assertLess(
            adapter.index("thermal_stream_param_nonfatal_waiting_for_frame"),
            adapter.index("thermal_stream_param_failed_error29_after_callback_ok"),
        )

    def test_mini2_f2_context_enum_keeps_native_count_warmup_before_login(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        error4 = json.loads(Path("error4.txt").read_text(encoding="utf-8"))
        earlier_login_ok = json.loads(Path("error.txt").read_text(encoding="utf-8"))

        self.assertIn("nativeEnum=not_run_official_context_route", error4["rawStageReport"])
        self.assertIn("USB_Login=failed error=13", error4["rawStageReport"])
        self.assertIn("nativeEnum=count=0", earlier_login_ok["rawStageReport"])
        self.assertIn("USB_Login(deviceInfoList[0])=ok", earlier_login_ok["rawStageReport"])

        open_slice = helper.split("fun openUsbDevice(", 1)[1].split("val selected = selectDevice", 1)[0]
        self.assertIn("val nativeEnumCount = runCatching { javaInterface.USB_GetDeviceCount() }.getOrDefault(-1)", open_slice)
        self.assertIn("nativeEnum=count=$nativeEnumCount", helper)
        self.assertNotIn("nativeEnum=not_run_official_context_route", helper)

    def test_mini2_f2_login_inputs_match_official_helper_without_serial_selector(self):
        decompiled = Path(".omx/analysis/hikmicro_viewer_xapk/deep_callbacks_helpers_methods.txt").read_text(encoding="utf-8")
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")

        official_login = decompiled.split(
            "## METHOD USB_Login (Lcom/hcusbsdk/Interface/USB_DEVICE_INFO;)Lkotlin/Pair;",
            1,
        )[1].split("## METHOD USB_Logout", 1)[0]
        for token in [
            "USB_USER_LOGIN_INFO",
            "->dwDevIndex I",
            "->dwVID I",
            "->dwPID I",
            "->byLoginMode B",
            "->dwFd I",
        ]:
            self.assertIn(token, official_login)
        self.assertNotIn("->szSerialNumber", official_login)

        open_slice = helper.split("fun openUsbDevice(", 1)[1].split("val reg = USB_DEVICE_REG_RES", 1)[0]
        for token in [
            "dwDevIndex = selected.dwIndex",
            "dwVID = selected.dwVID",
            "dwPID = selected.dwPID",
            "byLoginMode = 0",
            "dwFd = selected.dwFd",
        ]:
            self.assertIn(token, open_slice)
        self.assertNotIn("szSerialNumber = selected.szSerialNumber", open_slice)

    def test_mini2_f2_primary_entry_matches_decompiled_start_stream_preview_and_callback_holder(self):
        decompiled = Path(".omx/analysis/hikmicro_viewer_xapk/deep_callbacks_helpers_methods.txt").read_text(encoding="utf-8")
        api = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt").read_text(encoding="utf-8")
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        callback_holder = (ANDROID_ROOT / "app/src/main/java/com/hik/viewercommon/data/device/api/callback/F2ModuleStreamCallback.kt").read_text(encoding="utf-8")
        preview_manager = (ANDROID_ROOT / "app/src/main/java/com/hik/viewer/manager/PreviewManagerII.kt").read_text(encoding="utf-8")

        official_jna = decompiled.split("## METHOD startStreamPreviewJNA (", 1)[1].split("## METHOD stopStreamPreview", 1)[0]
        for token in [
            "USB_SetVideoParam",
            "USB_StartStreamCallbackJNA",
            "USB_SetThermalStreamParam",
            "Thread;->sleep",
            "USB_SetThermalStreamCtrl",
        ]:
            self.assertIn(token, official_jna)

        self.assertIn("F2ModuleStreamCallback", api + callback_holder)
        self.assertIn("getFStreamCallBack()", api + callback_holder)
        self.assertIn("helper.startStreamPreview(", api)
        self.assertIn("PreviewManagerII.INSTANCE.createF2ModuleStreamCallback", api)
        self.assertIn("fun startStreamPreviewJNA(", helper)
        self.assertIn("FStreamCallBack_JNA", callback_holder + preview_manager + helper)
        self.assertIn("officialF2AllowedPacketSizes", preview_manager)
        self.assertIn("101_320", preview_manager)
        self.assertIn("98_304", preview_manager)
        self.assertIn("183_496", preview_manager)
        self.assertIn("400_584", preview_manager)
        self.assertIn("41_160", preview_manager)

        official_entry = helper.split("fun startStreamPreviewJNA(", 1)[1].split("fun startStreamPreview(", 1)[0]
        self.assertIn("official_f2_startStreamPreviewJNA_behavior_clone", official_entry)
        self.assertIn("JnaUSB_STREAM_CALLBACK_PARAM", official_entry)
        self.assertIn("official startStreamPreviewJNA$1 compatibility callback slot", official_entry)
        self.assertIn("officialPrimaryJnaCandidate.copy", official_entry)
        self.assertIn("videoFormat = streamType", official_entry)
        self.assertIn("callbackStreamType = streamType", official_entry)
        self.assertIn("startStreamPreviewCandidate", official_entry)
        self.assertNotIn("diagnostic_fallback_format_ladder", official_entry)

        interface_entry = helper.split("fun startStreamPreview(", 1)[1].split("fun stopStreamPreview", 1)[0]
        self.assertIn("USB_STREAM_CALLBACK_PARAM", interface_entry)
        self.assertIn("official_f2_startStreamPreview_behavior_clone", interface_entry)
        self.assertIn("startStreamPreviewCandidate", interface_entry)

    def test_mini2_error84_recovery_uses_official_primary_without_ladder(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        java_interface = (ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/JavaInterface.kt").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")
        bridge = (JAVA_ROOT / "AndroidBridge.kt").read_text(encoding="utf-8")
        activity = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertIn("USB_StartStreamCallbackJNA", helper)
        self.assertIn("USB_StartStreamCallbackJNA", java_interface)
        self.assertIn("USB_StartStreamCallback_jna", java_interface)
        self.assertIn("HCUSBSDK.getInstance().USB_StartStreamCallback", java_interface)
        self.assertIn("Pointer.NULL", java_interface)
        self.assertIn("dwSize = nativeParam.size()", java_interface)

        self.assertIn("F2StreamStartMode.OFFICIAL_JNA", helper)
        self.assertIn("official_primary_f2_lifecycle_jna", helper)
        self.assertIn("next=official_primary_error_report", helper)
        self.assertNotIn("F2StreamStartMode.OFFICIAL_JNI", helper)
        self.assertNotIn("official_primary_f2_lifecycle_jni_compare", helper)
        self.assertNotIn("HIKMICRO_PRIMARY_VIDEO_FORMAT_CANDIDATES", helper)
        self.assertNotIn("HIKMICRO_VERBOSE_VIDEO_FORMAT_CANDIDATES", helper)
        self.assertNotIn("diagnostic_fallback_format_ladder", helper + stream + bridge + activity + adapter)
        self.assertNotIn("MANUAL_DIAGNOSTIC", helper + stream + bridge + activity + adapter)
        self.assertNotIn("startMini2DiagnosticProbe", bridge + activity + adapter)

        official_entry = stream.split("fun ensureStreaming(", 1)[1].split("private fun waitingForFrameStatus", 1)[0]
        self.assertIn("OFFICIAL_PRIMARY stopped after official F2 startStreamPreview failure", official_entry)
        self.assertNotIn("runManualDiagnosticFormatLadder", official_entry)

    def test_mini2_error84_lifecycle_and_diagnostics_are_structured(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        status_model = (JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertIn("lightweight_start_retry_no_fd_close", helper)
        self.assertIn("full_reset_stop_channel_logout_close_selected_connection", helper)
        self.assertLess(helper.index("USB_StopChannel"), helper.index("USB_Logout"))
        self.assertLess(helper.index("USB_Logout"), helper.index("closeConnection"))

        for token in [
            "stream_diagnostics",
            "attempt_diagnostics",
            "start_mode",
            "reset_mode",
            "video_format",
            "callback_stream_type",
            "set_video_status",
            "start_status",
            "last_error",
            "fd",
            "user_id",
            "converter_status",
            "raw_stage_report",
        ]:
            self.assertIn(token, status_model + stream + adapter)

        self.assertIn("MAX_PREVIEW_PIXELS", stream)
        self.assertIn("HIKMICRO_THERMAL_IMAGE_WIDTH", stream)
        self.assertIn("HIKMICRO_THERMAL_IMAGE_HEIGHT", stream)
        self.assertIn("availableRows", stream)
        self.assertIn("pixelCount > MAX_PREVIEW_PIXELS", stream)
        for token in ["fd", "userId", "user_id", "channel"]:
            with self.subTest(native_field=token):
                self.assertIn(token, status_model + stream)

    def test_mini2_official_primary_has_no_manual_diagnostic_ladder(self):
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        bridge = (JAVA_ROOT / "AndroidBridge.kt").read_text(encoding="utf-8")
        activity = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertIn("official_primary_f2_lifecycle", helper)
        self.assertIn("formatAttempts=", helper)
        self.assertIn("enum class Mini2OfficialRuntimeMode", stream + activity)
        self.assertIn("OFFICIAL_PRIMARY", stream + activity + adapter)
        self.assertNotIn("MANUAL_DIAGNOSTIC", stream + activity + adapter)
        self.assertNotIn("startMini2DiagnosticProbe", bridge + activity + adapter)
        self.assertNotIn("startDiagnosticFallbackFormatLadder", helper + stream)
        self.assertNotIn("runManualDiagnosticFormatLadder", helper + stream)
        self.assertNotIn("diagnostic_fallback_format_ladder", helper + stream + bridge + activity + adapter)

    def test_mini2_asdf_error84_replay_preserves_f2_last_stream_attempt(self):
        fixture = Path("asdf.txt")
        self.assertTrue(fixture.is_file(), "asdf.txt must stay available as the live error84 replay fixture")
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        raw_stream = payload["mini2"]["raw_stream"]
        stage_report = raw_stream["stage_report"]

        self.assertEqual(payload["classification"], "callback_start_failed_error84_after_video_ok")
        self.assertEqual(payload["lastError"], 84)
        self.assertEqual(payload["setVideoStatus"], "ok")
        self.assertEqual(payload["startStatus"], "failed")
        self.assertIn("official_apk_vid_pid_route 11231:258 -> F2 HCUSBSDK", raw_stream["device_route"])
        self.assertIn("USB_Login(deviceInfoList[0])=ok userId=181 dwFd=181", stage_report)
        self.assertIn("USB_SET_VIDEO_PARAM=ok videoFormat=103 size=256x392 fps=25", stage_report)
        self.assertIn("startStream=failed error=84", stage_report)
        self.assertEqual(payload["mini2"]["last_usb_event"], "android.hardware.usb.action.USB_DEVICE_DETACHED")
        self.assertEqual(payload["mini2"]["mini2_route_reason"], "device_not_found")

        status_model = (JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")
        activity = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        combined = status_model + probe + activity + adapter
        for token in [
            "current_usb_presence",
            "last_stream_attempt",
            "passive_raw_stream",
            "JSONObject.NULL",
            "callback_start_failed_error84_after_video_ok",
            "error84_after_video_ok",
            "USB_DEVICE_DETACHED",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, combined)

    def test_mini2_error84_screenshot_clusters_are_classified_and_visible_summary_is_bounded(self):
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        index = (WEBSITE_ROOT / "index.html").read_text(encoding="utf-8")
        status_model = (JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt").read_text(encoding="utf-8")

        self.assertIn("function classifyMini2StageReport", adapter)
        self.assertIn("function buildMini2DiagnosticExport", adapter)
        self.assertIn("function truncateMini2DiagnosticText", adapter)
        self.assertIn("MAX_VISIBLE_MINI2_DIAGNOSTIC_CHARS", adapter)

        for classifier in [
            "context_enum_login_ok_native_enum_secondary",
            "usb_permission_denied_before_native_stream",
            "usb_permission_pending_before_native_stream",
            "callback_start_failed_error84_after_video_ok",
            "thermal_stream_param_failed_error29_after_callback_ok",
            "video_param_failed_error21",
            "all_start_paths_failed_blocked_no_celsius",
            "converter_status_secondary_not_raw_stream_blocker",
        ]:
            with self.subTest(classifier=classifier):
                self.assertIn(classifier, adapter)

        for field in [
            "route",
            "vid",
            "pid",
            "fd",
            "userId",
            "channel",
            "startMode",
            "videoFormat",
            "callbackStreamType",
            "setVideoStatus",
            "startStatus",
            "lastError",
            "converterStatus",
            "rawStageReport",
        ]:
            with self.subTest(field=field):
                self.assertIn(field, adapter)

        self.assertIn("mini2CopyDiagnosticButton", index + adapter)
        self.assertIn("mini2FullDiagnosticText", index + adapter)
        self.assertIn("navigator.clipboard.writeText", adapter)
        self.assertIn("raw_streaming_unverified", adapter + status_model)
        self.assertNotIn("temperature_avg_c", adapter + status_model)

    def test_mini2_error6_thermal_param_failure_is_classified_and_cleans_session(self):
        payload = json.loads(Path("error6.txt").read_text(encoding="utf-8"))
        stage_report = payload["rawStageReport"]
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")

        self.assertIn("USB_StartStreamCallback=ok channel=0", stage_report)
        self.assertIn("USB_SET_THERMAL_STREAM_PARAM=failed command=2039", stage_report)
        self.assertIn("error=29", stage_report)
        self.assertIn("thermal_stream_param_failed_error29_after_callback_ok", adapter)
        self.assertIn("USB_SET_THERMAL_STREAM_PARAM=failed.*error=29", adapter)
        self.assertIn("full_session_reset_after_start_failure", stream)
        self.assertIn("closeSessionAfterStartFailure", stream)
        self.assertLess(
            stream.index("val blocked = blockedNativeStreamWithStage"),
            stream.index("closeSessionAfterStartFailure"),
            "diagnostic status should preserve failed attempt ids before native logout/close cleanup",
        )

    def test_android_mini2_usb_button_is_debounced_against_repeated_manual_probes(self):
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        button_handler = adapter[
            adapter.index("replaceButtonHandler('mobilePairButton'"):
            adapter.index("  replaceButtonHandler('mini2CopyDiagnosticButton'")
        ]
        copy_handler = adapter[
            adapter.index("replaceButtonHandler('mini2CopyDiagnosticButton'"):
            adapter.index("  replaceButtonHandler('roiSetupButton'")
        ]

        self.assertIn("MINI2_MANUAL_PROBE_MIN_INTERVAL_MS", adapter)
        self.assertIn("mini2ManualProbeInFlight", adapter)
        self.assertIn("lastMini2ManualProbeAt", adapter)
        self.assertIn("function runManualMini2Probe", adapter)
        self.assertIn("Mini2 USB 확인 연타 차단", adapter)
        self.assertNotIn("readBridgeJson('probeMini2')", button_handler)
        self.assertIn("runManualMini2Probe('button')", button_handler)
        self.assertIn("runManualMini2Probe('diagnostic_copy')", copy_handler)
        self.assertLess(
            adapter.index("mini2ManualProbeInFlight = true"),
            adapter.index("readBridgeJson('probeMini2')"),
        )

    def test_mini2_official_jna_wrapper_and_bounded_error84_start_order_are_explicit(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        java_interface = (ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/JavaInterface.kt").read_text(encoding="utf-8")

        self.assertIn("fun USB_StartStreamCallbackJNA", java_interface)
        self.assertIn("JnaUSB_STREAM_CALLBACK_PARAM", java_interface)
        self.assertIn("HCUSBSDKByJNA.USB_StartStreamCallback", java_interface)
        self.assertIn("official_jna_wrapper", helper)
        self.assertNotIn("repo_keepalive_safety_deviation", java_interface + helper)

        self.assertIn("enum class F2StreamStartMode", helper)
        self.assertIn("OFFICIAL_JNA", helper)
        for label in [
            "official_jna_primary_103_103",
            "official_f2_startStreamPreviewJNA_behavior_clone",
            "next=official_primary_error_report",
        ]:
            with self.subTest(label=label):
                self.assertIn(label, helper)

        self.assertNotIn("OFFICIAL_JNI", helper)
        self.assertNotIn("official_jni_comparison_103_103", helper)
        self.assertNotIn("official_jna_low_format_101_103", helper)
        self.assertNotIn("official_jna_low_format_102_103", helper)
        self.assertNotIn("official_jna_low_format_104_103", helper)
        self.assertNotIn("appendVerboseOnlyDiagnostics", helper)
        for structured_field in ["val fd: Int", "val userId: Int", '.put("fd", fd)', '.put("user_id", userId)']:
            with self.subTest(structured_field=structured_field):
                self.assertIn(structured_field, helper + (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8"))

        official_entry = helper.split("fun startStreamPreviewJNA(", 1)[1].split("fun startStreamPreview(", 1)[0]
        self.assertIn("official_jna_primary_103_103", helper)
        self.assertNotIn("101", official_entry)
        self.assertNotIn("102", official_entry)
        self.assertNotIn("104", official_entry)

    def test_mini2_official_wrapper_parity_export_and_channel_semantics_are_explicit(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        java_interface = (ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/JavaInterface.kt").read_text(encoding="utf-8")
        status_model = (JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        probe = (JAVA_ROOT / "Mini2UsbProbe.kt").read_text(encoding="utf-8")

        compact_helper = re.sub(r"\s+", " ", helper)
        self.assertRegex(compact_helper, r"private fun USB_StartStreamCallbackJNA\([^)]*\): Boolean")
        self.assertIn("val callbackStarted = USB_StartStreamCallbackJNA", helper)
        self.assertIn("if (callbackStarted) channel else -1", helper)
        self.assertIn("callbackSlots[currentUserId] = struStreamCBParam.fnStreamCallBack", helper)
        self.assertIn("HCUSBSDK.getInstance().USB_StartStreamCallback(currentUserId, nativeParam.pointer)", helper)
        self.assertIn("channel = rawChannel", helper)
        self.assertRegex(java_interface, r"fun USB_StartStreamCallbackJNA\([\s\S]*?\): Int")

        for token in [
            "official_wrapper_parity",
            "official_wrapper_parity_ok",
            "route_selection_f2",
            "context_enum_login",
            "stop_before_start",
            "startStreamPreviewJNA",
            "callback_slot_keepalive",
            "channel_storage_semantics",
            "structure_field_order",
            "native_library_path_load_order",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, status_model + adapter)

        self.assertIn("current_usb_presence", probe + adapter)
        self.assertIn("last_stream_attempt", probe + adapter)
        self.assertIn("passive_raw_stream", probe)
        self.assertIn("if (attemptRawStream)", probe)
        self.assertIn('result.put("last_stream_attempt", JSONObject.NULL)', probe)

    def test_mini2_jna_structure_field_order_is_locked_against_androguard(self):
        jna = (ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/jna/HCUSBSDKByJNA.kt").read_text(encoding="utf-8")
        androguard = Path(".omx/analysis/hikmicro_viewer_xapk/error84_parallel/task3_jna_structs_constants_error84.md").read_text(encoding="utf-8")

        expected_orders = [
            '@Structure.FieldOrder(\n    "dwSize",\n    "dwIndex",\n    "dwVID",\n    "dwPID",\n    "szManufacturer",\n    "szDeviceName",\n    "szSerialNumber",\n    "byHaveAudio",\n    "byRes",\n)',
            '@Structure.FieldOrder(\n    "dwSize",\n    "dwTimeout",\n    "dwDevIndex",\n    "dwVID",\n    "dwPID",',
            '@Structure.FieldOrder("dwSize", "dwStreamType", "fnStreamCallBack", "pUser", "byRes")',
            '@Structure.FieldOrder("dwVideoFormat", "dwWidth", "dwHeight", "dwFramerate", "dwBitrate", "dwParamType", "dwValue", "byRes")',
            '@Structure.FieldOrder(\n    "nStamp",\n    "dwStreamType",\n    "dwWidth",\n    "dwHeight",',
        ]
        for order in expected_orders:
            with self.subTest(order=order[:48]):
                self.assertIn(order, jna)

        for evidence in [
            "USB_DEVICE_INFO",
            "USB_USER_LOGIN_INFO",
            "USB_DEVICE_REG_RES",
            "USB_STREAM_CALLBACK_PARAM",
            "USB_VIDEO_PARAM",
            "USB_FRAME_INFO",
            "Matches current",
        ]:
            with self.subTest(evidence=evidence):
                self.assertIn(evidence, androguard)

    def test_mini2_lifecycle_reset_labels_and_fd_invariants_are_locked(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        java_interface = (ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/JavaInterface.kt").read_text(encoding="utf-8")

        for token in [
            "enum class F2ResetMode",
            "LIGHTWEIGHT_RETRY_NO_FD_CLOSE",
            "FULL_SESSION_RESET_BEFORE_CANDIDATE",
            "lightweight_retry_no_fd_close",
            "full_session_reset_before_candidate",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, helper)

        self.assertIn("JnaUSB_FRAME_INFO(this).apply { read() }", (ANDROID_ROOT / "app/src/main/java/com/hik/viewer/manager/PreviewManagerII.kt").read_text(encoding="utf-8"))
        self.assertIn("lastStageReport", helper)
        self.assertIn("lastFailureReason", helper)

        self.assertLess(helper.index("USB_StopChannel(currentUserId"), helper.index("USB_Logout(currentUserId"))
        self.assertLess(helper.index("USB_Logout(currentUserId"), helper.index("selectedDeviceInfo?.closeConnection()"))
        self.assertIn("clearCallbackSlot(userId)", java_interface)
        self.assertLess(java_interface.index("clearCallbackSlot(userId)"), java_interface.index("nativeBridge.USB_StopChannel"))

    def test_mini2_login_failure_cleanup_and_stage_report_evidence(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")

        self.assertIn("USB_Cleanup", helper)
        self.assertIn("sdkInited = false", helper)
        self.assertIn("USB_Login=failed", helper)
        self.assertIn("stageReport", helper + stream)
        for token in ["selectedFd=", "selectedIndex=", "targetVid=", "targetPid=", "userId", "channel", "official_primary_f2_lifecycle"]:
            self.assertIn(token, helper + stream)

    def test_mini2_f2_no_fake_celsius_success(self):
        status_model = (JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")

        self.assertIn("Celsius still blocked", stream)
        self.assertIn("raw_unverified", stream)
        self.assertNotIn("temperature_avg_c", status_model + stream + helper)
        self.assertNotIn("temperatureCelsius = raw", status_model + stream + helper)

    def test_mini2_error9_preview_uses_top_256x192_matrix_and_raw_fallback_stats(self):
        payload_text = Path("error9.txt").read_text(encoding="utf-8")
        payload, _ = json.JSONDecoder().raw_decode(payload_text)
        raw_stream = payload["mini2"]["raw_stream"]
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")
        status_model = (JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt").read_text(encoding="utf-8")
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")

        self.assertEqual(raw_stream["frame_width"], 256)
        self.assertEqual(raw_stream["frame_height"], 344)
        self.assertEqual(raw_stream["raw_stream_status"], "raw_streaming_unverified")
        self.assertIn("HIKMICRO_THERMAL_IMAGE_HEIGHT = 192", stream)
        self.assertIn("transport_frame_height", status_model)
        self.assertIn("raw_avg", status_model)
        self.assertIn("raw_min", status_model)
        self.assertIn("raw_max", status_model)
        self.assertIn('live.put("raw_avg"', main)
        self.assertIn('live.put("raw_min"', main)
        self.assertIn('live.put("raw_max"', main)

    def test_android_mini2_thermal_frame_uses_dynamic_aspect_and_refreshes_roi_on_load(self):
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertIn("applyAndroidThermalPreviewFrame", adapter)
        self.assertIn("thermal_frame_width", adapter)
        self.assertIn("thermal_frame_height", adapter)
        self.assertIn("style.aspectRatio", adapter)
        self.assertIn("closest('.camera-frame')", adapter)
        self.assertIn("thermal.onload", adapter)
        self.assertIn("refreshRoiOverlays", adapter)

    def test_mini2_thermal_preview_rotation_is_correctable_from_android_ui(self):
        index = (WEBSITE_ROOT / "index.html").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        bridge = (JAVA_ROOT / "AndroidBridge.kt").read_text(encoding="utf-8")
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        status_model = (JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")

        self.assertIn("mini2RotateButton", index + adapter)
        self.assertIn("rotateThermalPreview", bridge)
        self.assertIn("rotateThermalPreviewFromBridge", main)
        self.assertIn("HIKMICRO_DEFAULT_DISPLAY_ROTATION_DEGREES = 90", stream)
        self.assertIn("rotatePreviewClockwise", stream)
        self.assertIn("rotateThermalPixels", stream)
        self.assertIn("preview_rotation_degrees", status_model + stream + main)
        self.assertIn('readBridgeJson(\'rotateThermalPreview\')', adapter)
        self.assertIn("Mini2 화면 회전", adapter)

    def test_android_visible_roi_can_be_updated_from_webview_bridge(self):
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        bridge = (JAVA_ROOT / "AndroidBridge.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertIn("setVisibleRoi", bridge)
        self.assertIn("setVisibleRoiFromBridge", main)
        self.assertIn("visible_frame_width", main)
        self.assertIn("visible_frame_height", main)
        self.assertIn("addAndroidVisibleRoiHandler", adapter)
        self.assertIn("bridge.setVisibleRoi", adapter)
        self.assertIn("normalized", adapter)


if __name__ == "__main__":
    unittest.main()
