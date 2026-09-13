from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
ANDROID_ROOT = ROOT / "mobile/android"
JAVA_ROOT = ANDROID_ROOT / "app/src/main/java/kr/auto/titration/mobile"
WEBSITE_ROOT = ROOT / "website"
TECH_ANALYSIS = ROOT / "_workspace/hikmicro-analysis-20260714/final-technical-analysis.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def function_slice(source: str, start: str, end: str | None = None) -> str:
    begin = source.index(start)
    finish = source.index(end, begin) if end else len(source)
    return source[begin:finish]


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

    def test_manual_probe_returns_fresh_status_instead_of_reinserting_probe_snapshot(self):
        main = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        method = main[
            main.index("private fun runMini2ProbeFromBridge("):
            main.index("\n    @Synchronized", main.index("private fun runMini2ProbeFromBridge(") + 1)
        ]

        self.assertIn("lastExplicitMini2Probe = mini2", method)
        self.assertIn("val result = safeBuildStatusJson()", method)
        self.assertNotIn('.put("mini2", mini2)', method)

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
        self.assertIn('put("last_stream_attempt", explicitRawStream)', main)
        self.assertNotIn('put("raw_stream", explicitRawStream)', main)
        self.assertNotIn("isActiveMini2Peek", main)

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
        self.assertIn("coreLoadedFor(moduleType)", backend)
        self.assertIn("attempted_libraries_loaded", backend)
        self.assertNotIn("!cached.allLoaded", backend)
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
        self.assertIn('put("temperature_avg_c", JSONObject.NULL)', status_model)
        self.assertIn('put("device_global_temperature_avg_c", summary?.avgC ?: JSONObject.NULL)', status_model)
        self.assertNotIn("temperature_avg_c || 0", adapter)
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
        java_interface = (interface_root / "JavaInterface.kt").read_text(encoding="utf-8")
        preview_manager = (ANDROID_ROOT / "app/src/main/java/com/hik/viewer/manager/PreviewManagerII.java").read_text(encoding="utf-8")
        g3_factory = (ANDROID_ROOT / "app/src/main/java/g3/b.java").read_text(encoding="utf-8")
        for token in ["USB_Init", "USB_Login", "USB_StartStreamCallback", "USB_DEVICE_INFO", "USB_USER_LOGIN_INFO", "USB_DEVICE_REG_RES"]:
            self.assertIn(token, helper + jna + java_interface)
        for token in ["PreviewManagerIIAppBinding", "processor.d(packet)", "officialProcessedF2PacketDimensions", "g3.b.a.a"]:
            self.assertIn(token, stream + preview_manager)
        self.assertIn("case 12: return streamingNew ? new g3.e(streamInfoDeal) : new g3.d(streamInfoDeal);", g3_factory)

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
            "com/hik/viewer/manager/PreviewManagerII.java",
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
        self.assertIn("com.hcusbsdk.jni.USB_FRAME_INFO.toInterfaceFrame", java_interface)
        self.assertIn("com.hcusbsdk.jni.USB_FRAME_INFO?.copyRejectionReason", java_interface)

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
        open_body = function_slice(api, "fun openUsbModule(", "    @Synchronized\n    fun startStreamPreview")
        self.assertIn("F2UsbModuleApi.openUsbModule:officialRetry", open_body)
        self.assertEqual(1, open_body.count("helper.openUsbDevice("))
        for required in ["retryIndex", "retryIndex < 5", "Thread.sleep(retryIndex * 500L)", "do {", "while ("]:
            with self.subTest(required_official_open_retry=required):
                self.assertIn(required, open_body)
        for token in ["sdkInited", "deviceInfoList", "userId", "channel"]:
            self.assertIn(token, helper)

        start_locked = function_slice(api, "private fun startStreamPreviewLocked", "    @Synchronized\n    fun startStreamPreviewJNA")
        self.assertLess(
            start_locked.index("stopForTransition(context, config.streamingNew)"),
            start_locked.index("startNativeStreamPreviewLocked"),
        )
        stop_transition = function_slice(api, "private fun stopForTransition", "    private fun setInvalidPacketSizeTimeoutCallback")
        native_start = function_slice(api, "private fun startNativeStreamPreviewLocked", "    @Synchronized\n    fun startStreamPreviewJNA")
        self.assertIn("helper.stopStreamPreview(context, streamingNew)", stop_transition)
        self.assertIn("helper.startStreamPreview", native_start)

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
        self.assertIn("enumerationInventory=", helper)
        open_slice = function_slice(helper, "fun openUsbDevice(\n        context: Context", "    @Synchronized\n    fun openUsbDevice(context: Context)")
        self.assertLess(open_slice.index("cleanupPreviousOfficialF2Login"), open_slice.index("USB_Login(loginInfo"))
        self.assertIn("officialSelection=deviceInfoList[0]", open_slice)

        start_locked = function_slice(api, "private fun startStreamPreviewLocked", "    @Synchronized\n    fun startStreamPreviewJNA")
        self.assertLess(start_locked.index("stopForTransition(context, config.streamingNew)"), start_locked.index("startNativeStreamPreviewLocked"))
        stop_transition = function_slice(api, "private fun stopForTransition", "    private fun setInvalidPacketSizeTimeoutCallback")
        native_start = function_slice(api, "private fun startNativeStreamPreviewLocked", "    @Synchronized\n    fun startStreamPreviewJNA")
        self.assertIn("helper.stopStreamPreview(context, streamingNew)", stop_transition)
        self.assertIn("helper.startStreamPreview", native_start)
        start_slice = function_slice(helper, "fun startStreamPreview(\n        fStreamCallBack: FStreamCallBack", "    @Synchronized\n    fun stopStreamPreview")
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


    def test_mini2_error29_regression_reconciles_official_thermal_param_nonfatal_contract(self):
        """error6/error8 logs are gone; lock the durable source/evidence contract instead.

        Durable evidence: _workspace/hikmicro-analysis-20260714/final-technical-analysis.md §1, §5.2, §6.
        """
        analysis = read(TECH_ANALYSIS)
        helper = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt")
        api = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt")
        readme = read(ANDROID_ROOT / "README.md")

        self.assertIn("오류 29", analysis)
        self.assertIn("USB_SetThermalStreamParam", analysis)
        self.assertIn("실패를 비치명적으로 처리", analysis)
        self.assertIn("thermal coding `12`", readme)
        self.assertIn("HIKMICRO_THERMAL_VIDEO_CODING_TYPE: Int = 12", helper)
        self.assertIn("videoCodingTypeOverride ?: profile.thermalCoding", api)
        self.assertNotIn("HIKMICRO_THERMAL_VIDEO_CODING_TYPE: Int = 8", helper)
        start_candidate = function_slice(helper, "fun startStreamPreview(\n        fStreamCallBack: FStreamCallBack", "    @Synchronized\n    fun stopStreamPreview")
        self.assertLess(start_candidate.index("USB_StartStreamCallback(callbackParam)"), start_candidate.index("USB_SetThermalStreamParam(videoCodingType)"))
        self.assertNotIn("USB_SET_THERMAL_STREAM_PARAM=failed_nonfatal", helper)
        self.assertNotIn("diagnostic_fallback_format_ladder", helper)


    def test_mini2_stop_lifecycle_verifies_thermal_ctrl_before_stop_channel(self):
        """Stop must use bounded thermal-control teardown before channel stop.

        Durable evidence: _workspace/hikmicro-analysis-20260714/final-technical-analysis.md §5.2 establishes
        the official stream lifecycle; source locks the app's conservative 100-poll safety teardown.
        """
        helper = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt")
        java_interface = read(ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/JavaInterface.kt")
        jna = read(ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/jna/HCUSBSDKByJNA.kt")

        for token in [
            "USB_GetDeviceConfig",
            "USB_GetThermalStreamCtrl",
            "getThermalStreamCtrlState",
            "verifyThermalStreamCtrlDisabled",
            "OFFICIAL_STOP_THERMAL_CTRL_MAX_RETRIES: Int = 100",
            "OFFICIAL_STOP_THERMAL_CTRL_POLL_SLEEP_MS: Long = 10L",
            "streamEnable=",
            "maxAttempts=",
            "attempt=",
            "unsuccessfulPolls=",
            "USB_SetThermalStreamCtrl(false)#retry",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, helper + java_interface + jna)

        stop_slice = function_slice(helper, "fun stopStreamPreview(context: Context", "    @Synchronized\n    fun closeSession")
        self.assertLess(stop_slice.index("setThermalStreamCtrl(currentUserId, enable = false)"), stop_slice.index("verifyThermalStreamCtrlDisabled"))
        self.assertLess(stop_slice.index("verifyThermalStreamCtrlDisabled"), stop_slice.index("USB_StopChannel"))
        verify_slice = function_slice(
            helper,
            "internal fun verifyThermalStreamCtrlDisabledBounded",
            "data class F2StreamFrame",
        )
        self.assertIn("while (unsuccessfulPolls < maxAttempts)", verify_slice)
        self.assertIn("unsuccessfulPolls += 1", verify_slice)
        self.assertIn("unsuccessfulPolls >= maxAttempts", verify_slice)
        self.assertIn("sleep(OFFICIAL_STOP_THERMAL_CTRL_POLL_SLEEP_MS)", verify_slice)
        self.assertIn("Thread.currentThread().interrupt()", verify_slice)
        self.assertIn("reason=max_attempts", verify_slice)
        self.assertNotIn("USB_EnumDevices", verify_slice)
        self.assertNotIn("coerceAtMost", verify_slice)
        self.assertIn("Thread.sleep(100)", stop_slice)
        self.assertIn("stopChannelOperation(currentUserId, currentChannel)", stop_slice)
        self.assertNotIn("currentChannel != -1", stop_slice)

    def test_mini2_official_interface_callback_abi_uses_jna_callback_invoke(self):
        callback = read(ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/FStreamCallBack.kt")
        preview = read(ANDROID_ROOT / "app/src/main/java/com/hik/viewer/manager/PreviewManagerII$d.java")

        self.assertIn("fun interface FStreamCallBack : Callback", callback)
        self.assertIn("fun invoke(userId: Int, frameInfo: USB_FRAME_INFO?)", callback)
        self.assertIn("synchronized void invoke(int userId, USB_FRAME_INFO frameInfo)", preview)
        self.assertNotIn("fStreamCallback", callback)

    def test_mini2_native_start_without_java_callback_has_specific_classification(self):
        adapter = read(WEBSITE_ROOT / "android-webview.js")
        classifier = function_slice(adapter, "function classifyMini2StageReport", "  function buildMini2DiagnosticExport")
        script = f"""
const assert = require('assert');
{classifier}
const stage = 'USB_StartStreamCallback=ok channel=0; startStreamPreview resultCode=1 channel=0';
assert.strictEqual(
  classifyMini2StageReport(stage, 'stream_attempt_started no_callback_entry'),
  'native_start_succeeded_waiting_for_java_callback',
);
assert.strictEqual(
  classifyMini2StageReport(stage, 'blocked_native_stream stalled_without_frame no_callback_entry'),
  'native_start_succeeded_no_java_callback',
);
assert.strictEqual(
  classifyMini2StageReport(stage, 'stream_attempt_started no_callback_entry', {{
    dispatchedCallbackCount: 129,
    callbackEntryDetail: 'route=jni disposition=dispatched dispatchedCount=129',
    frameCounter: 0,
    postStartState: 'native_start_accepted_callback_packet_observed_official_handoff_missing',
  }}),
  'callback_packet_observed_official_handoff_missing',
);
assert.strictEqual(
  classifyMini2StageReport(stage, 'stream_attempt_started no_callback_entry', {{
    dispatchedCallbackCount: 0,
    callbackEntryDetail: 'route=jni disposition=rejected rejectedCount=129',
    frameCounter: 0,
    postStartState: 'native_start_accepted_callback_packet_observed_official_handoff_missing',
  }}),
  'native_start_succeeded_waiting_for_java_callback',
);
assert.strictEqual(
  classifyMini2StageReport(stage, 'stream_attempt_started', {{
    dispatchedCallbackCount: 0,
    callbackEntryDetail: 'route=jni disposition=rejected rejectedCount=129',
    frameCounter: 0,
    postStartState: 'native_start_accepted_callback_invalid_packet_size_timeout',
    invalidPacketSizeTimeout: {{
      observed_packet_size: 102944,
      allowed_packet_sizes: [203720, 183496],
    }},
  }}),
  'native_start_accepted_callback_invalid_packet_size_timeout',
);
"""
        subprocess.run(["node", "-e", script], check=True)

        status_model = read(JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt")
        self.assertIn('stageReport.contains("startStreamPreview resultCode=1"', status_model)
        callback_branch = status_model.index("callbackEntryCount > 0L &&")
        self.assertIn('callbackEntryDetail.contains("disposition=dispatched")', status_model)
        waiting_branch = status_model.index('if (rawStreamStatus == "stream_attempt_started")')
        self.assertLess(callback_branch, waiting_branch)

    def test_mini2_structured_callback_evidence_overrides_waiting_web_classification(self):
        adapter = read(WEBSITE_ROOT / "android-webview.js")
        diagnostic_functions = function_slice(
            adapter,
            "function isAndroidPlainObject",
            "  function updateMini2DiagnosticExport",
        )
        script = f"""
const assert = require('assert');
const MINI2_OFFICIAL_PRIMARY_MODE = 'OFFICIAL_PRIMARY';
{diagnostic_functions}
const result = buildMini2DiagnosticExport({{
  mini2: {{
    raw_stream: {{
      raw_stream_status: 'stream_attempt_started',
      reason: 'stream_attempt_started no_callback_entry',
      stage_report: 'USB_StartStreamCallback=ok channel=0 lastError=0',
      frame_counter: 0,
      java_interface_dispatched_callback_count: 129,
      java_interface_callback_entry_count: 129,
      java_interface_callback_entry_detail: 'route=jni disposition=dispatched dispatchedCount=129 callbackUserId=116 dwBufSize=203720',
      post_start_state: 'native_start_accepted_callback_packet_observed_official_handoff_missing',
      celsius_allowed: false,
      temperature_avg_c: null,
    }},
  }},
}});
assert.strictEqual(result.callbackEntryCount, 129);
assert.strictEqual(result.classification, 'callback_packet_observed_official_handoff_missing');
assert.notStrictEqual(result.classification, 'native_start_succeeded_waiting_for_java_callback');
"""
        subprocess.run(["node", "-e", script], check=True)

    def test_mini2_current_raw_stream_wins_over_stale_last_attempt(self):
        adapter = read(WEBSITE_ROOT / "android-webview.js")
        diagnostic_functions = function_slice(
            adapter,
            "function isAndroidPlainObject",
            "  function updateMini2DiagnosticExport",
        )
        script = f"""
const assert = require('assert');
const MINI2_OFFICIAL_PRIMARY_MODE = 'OFFICIAL_PRIMARY';
{diagnostic_functions}
const current = {{
  raw_stream_status: 'raw_streaming_unverified',
  reason: 'current official frame observed',
  stage_report: 'USB_StartStreamCallback=ok channel=0 lastError=0',
  frame_counter: 129,
  java_interface_dispatched_callback_count: 129,
  java_interface_callback_entry_detail: 'route=jni disposition=dispatched dispatchedCount=129',
}};
const stale = {{
  raw_stream_status: 'stream_attempt_started',
  reason: 'stream_attempt_started no_callback_entry',
  stage_report: 'USB_StartStreamCallback=ok channel=0 lastError=0',
  frame_counter: 0,
  java_interface_dispatched_callback_count: 0,
  java_interface_callback_entry_detail: 'no_callback_entry',
}};
const result = buildMini2DiagnosticExport({{
  mini2: {{
    raw_stream: current,
    last_stream_attempt: stale,
  }},
}});
assert.strictEqual(result.classification, 'official_frame_observed');
assert.strictEqual(result.callbackEntryCount, 129);
assert.strictEqual(result.diagnosticStream.frame_counter, 129);
assert.strictEqual(result.lastStreamAttempt.frame_counter, 0);
"""
        subprocess.run(["node", "-e", script], check=True)

    def test_mini2_stale_only_attempt_is_not_classified_as_current_frame(self):
        adapter = read(WEBSITE_ROOT / "android-webview.js")
        diagnostic_functions = function_slice(
            adapter,
            "function isAndroidPlainObject",
            "  function updateMini2DiagnosticExport",
        )
        script = f"""
const assert = require('assert');
const MINI2_OFFICIAL_PRIMARY_MODE = 'OFFICIAL_PRIMARY';
{diagnostic_functions}
const historical = {{
  raw_stream_status: 'raw_streaming_unverified',
  reason: 'historical official frame observed',
  stage_report: 'USB_StartStreamCallback=ok channel=0 lastError=0',
  frame_counter: 129,
  celsius_allowed: true,
  official_measurement_status: 'READY',
}};
const result = buildMini2DiagnosticExport({{
  mini2: {{
    last_stream_attempt: historical,
  }},
}});
assert.strictEqual(result.classification, 'historical_last_attempt_only');
assert.strictEqual(result.diagnosticClassification, 'official_frame_observed');
assert.strictEqual(result.diagnosticStreamIsCurrent, false);
assert.strictEqual(result.lastStreamAttempt.frame_counter, 129);
assert.notStrictEqual(result.classification, 'official_frame_observed');
"""
        subprocess.run(["node", "-e", script], check=True)

    def test_mini2_invalid_packet_timeout_overrides_generic_callback_handoff_classification(self):
        adapter = read(WEBSITE_ROOT / "android-webview.js")
        diagnostic_functions = function_slice(
            adapter,
            "function isAndroidPlainObject",
            "  function updateMini2DiagnosticExport",
        )
        script = f"""
const assert = require('assert');
const MINI2_OFFICIAL_PRIMARY_MODE = 'OFFICIAL_PRIMARY';
{diagnostic_functions}
const timeout = {{
  observed_packet_size: 102944,
  allowed_packet_sizes: [203720, 183496],
  elapsed_ms: 40001,
}};
const result = buildMini2DiagnosticExport({{
  mini2: {{
    raw_stream: {{
      raw_stream_status: 'stream_attempt_started',
      reason: 'stream_attempt_started',
      stage_report: 'USB_StartStreamCallback=ok channel=0 lastError=0',
      frame_counter: 0,
      java_interface_callback_entry_count: 129,
      post_start_state: 'native_start_accepted_callback_invalid_packet_size_timeout',
      invalid_packet_size_timeout: timeout,
      celsius_allowed: false,
      temperature_avg_c: null,
    }},
  }},
}});
assert.strictEqual(
  result.classification,
  'native_start_accepted_callback_invalid_packet_size_timeout',
);
assert.deepStrictEqual(result.invalidPacketSizeTimeout, timeout);
assert.strictEqual(result.live?.celsius_allowed, undefined);
"""
        subprocess.run(["node", "-e", script], check=True)

    def test_mini2_first_frame_wait_explicit_retry_cleans_and_passive_poll_does_not_restart(self):
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")

        self.assertIn("const val FRAME_WAIT_TIMEOUT_MS = 30_000L", stream)
        self.assertNotIn("STREAM_RETRY_INTERVAL_MS = 30_500L", stream)
        self.assertNotIn("active_session_reuse_no_restart", stream)
        self.assertNotIn("retry_throttled", stream)
        ensure_entry = function_slice(stream, "fun ensureStreaming(", "    /**\n     * Passive status polling")
        self.assertIn("explicit manual confirm forces fresh official retry", ensure_entry)
        self.assertNotIn("f2Helper.closeSession()", stream)
        self.assertIn("f2Api.closeSessionForFreshOpen(reason)", stream)
        self.assertIn("reason = \"stale_frame\"", ensure_entry)
        self.assertIn("reason = \"explicit_retry\"", ensure_entry)
        self.assertIn("reason = \"pre_open_cleanup\"", ensure_entry)
        self.assertIn("F2SessionCloseOutcome.STREAM_PRESERVED", ensure_entry)
        self.assertIn("exact prior binding ownership retained", stream)
        self.assertIn("f2Api.openUsbModule(", ensure_entry)
        self.assertLess(ensure_entry.index('reason = "pre_open_cleanup"'), ensure_entry.index("f2Api.openUsbModule("))
        self.assertLess(ensure_entry.index("?.let { return it }"), ensure_entry.index("f2Api.openUsbModule("))
        passive_entry = function_slice(stream, "fun peekActiveStatus(", "    @Synchronized\n    fun latestRawFrameSummary")
        self.assertIn("passive_status_peek is read-only", passive_entry)
        self.assertNotIn("f2Api.openUsbModule(", passive_entry)


    def test_mini2_error8_regression_active_probe_uses_official_public_api_interface_route(self):
        """Official UI path is interface/JNI, not direct JNA.

        Durable evidence: _workspace/hikmicro-analysis-20260714/final-technical-analysis.md §5.1-§5.3.
        """
        analysis = read(TECH_ANALYSIS)
        api = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt")
        stream = read(JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt")

        self.assertIn("공식 UI의 F2 기본 시작 경로", analysis)
        self.assertIn("직접 JNA 콜백이 아니라 JNI 콜백", analysis)
        api_entry = function_slice(api, "private fun startStreamPreviewLocked", "    @Synchronized\n    fun startStreamPreviewJNA")
        self.assertIn("streamCallback.getFStreamCallBack()", api_entry)
        self.assertNotIn("wrapCalibrationPrefetchCallbacks", api)
        self.assertIn("helper.startStreamPreview(", api_entry)
        self.assertNotIn("getFStreamCallBackJNA", api_entry)
        self.assertNotIn("startStreamPreviewJNA", api_entry)
        ensure_entry = function_slice(stream, "fun ensureStreaming(", "    /**\n     * Passive status polling")
        self.assertIn("f2Api.startStreamPreview(", ensure_entry)
        self.assertIn("callback = { frame ->", ensure_entry)
        self.assertIn("captureOfficialF2Frame(frame)", ensure_entry)
        self.assertIn("val successCount = onOfficialPreviewSuccess()", ensure_entry)
        self.assertIn("f2Helper.onPreviewFrameForCalibrationPrefetch(", ensure_entry)
        self.assertIn("cacheDir = officialF2DataDirectory(context)", ensure_entry)
        self.assertIn("previewFrameCounter = successCount", ensure_entry)
        self.assertLess(ensure_entry.index("captureOfficialF2Frame(frame)"), ensure_entry.index("val successCount = onOfficialPreviewSuccess()"))
        self.assertLess(ensure_entry.index("val successCount = onOfficialPreviewSuccess()"), ensure_entry.index("f2Helper.onPreviewFrameForCalibrationPrefetch("))
        self.assertNotIn("context.cacheDir", ensure_entry)
        f2data_entry = function_slice(stream, "internal fun officialF2DataDirectory(context: Context)", "    private fun waitingForFrameStatus")
        self.assertIn("A5.y.c.b().u()", f2data_entry)
        self.assertIn("context.getExternalFilesDir(null)", f2data_entry)
        self.assertIn('File(root, "F2Data")', f2data_entry)
        self.assertNotIn("f2Api.startStreamPreviewJNA", ensure_entry)


    def test_mini2_waiting_status_surfaces_java_interface_callback_and_invalid_packet_diagnostics(self):
        status = read(JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt")
        stream = read(JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt")
        api = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt")

        for token in [
            "java_interface_callback_entry_count",
            "java_interface_callback_entry_detail",
            "invalid_packet_size_timeout",
            "observed_packet_size",
            "allowed_packet_sizes",
            "profile_class",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, status)
        self.assertIn("JavaInterface.getInstance().streamCallbackEntryCount", stream)
        self.assertIn("JavaInterface.getInstance().lastStreamCallbackEntryDetail", stream)
        self.assertIn("onInvalidPacketSizeTimeout", api)
        self.assertIn("onInvalidPacketSizeTimeout = { packetSize, elapsedMs ->", stream)
        self.assertIn("lastInvalidPacketDiagnostic = Mini2InvalidPacketDiagnostic", stream)

    def test_f2_open_logs_inventory_and_uses_context_enumerated_first_device_without_fallback_ladder(self):
        helper = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt")
        java_interface = read(ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/JavaInterface.kt")

        self.assertIn("enumerationInventory=", helper)
        self.assertIn("officialSelection=deviceInfoList[0]", helper)
        self.assertIn("private fun selectOfficialContextEnumeratedDeviceInfo(): USB_DEVICE_INFO?", helper)
        selection = function_slice(helper, "private fun selectOfficialContextEnumeratedDeviceInfo", "    private fun normalizeOfficialFirmwareVersion")
        self.assertIn("deviceInfoList.firstOrNull()", selection)
        self.assertNotIn("?:", selection)
        enum_slice = function_slice(java_interface, "fun USB_GetDeviceCount(context: Context)", "    fun USB_EnumDevices(count")
        self.assertNotIn("sortedWith(compareBy<UsbDevice>", enum_slice)


    def test_mini2_error8_thermal_param_failure_is_official_nonfatal_after_callback_start(self):
        """SetVideo and SetThermalParam failures remain diagnostic/nonfatal where official ordering allows it.

        Durable evidence: _workspace/hikmicro-analysis-20260714/final-technical-analysis.md §5.2.
        """
        helper = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt")
        adapter = read(WEBSITE_ROOT / "android-webview.js")

        start_candidate = function_slice(helper, "fun startStreamPreview(\n        fStreamCallBack: FStreamCallBack", "    @Synchronized\n    fun stopStreamPreview")
        self.assertLess(start_candidate.index("USB_SetVideoParam"), start_candidate.index("USB_StartStreamCallback(callbackParam)"))
        self.assertLess(start_candidate.index("USB_StartStreamCallback(callbackParam)"), start_candidate.index("USB_SetThermalStreamParam"))
        self.assertLess(start_candidate.index("USB_SetThermalStreamParam"), start_candidate.index("Thread.sleep(100)"))
        self.assertLess(start_candidate.index("Thread.sleep(100)"), start_candidate.index("USB_SetThermalStreamCtrl"))
        self.assertNotIn("USB_SET_VIDEO_PARAM=failed_nonfatal", helper)
        self.assertNotIn("USB_SET_THERMAL_STREAM_PARAM=failed_nonfatal", helper)
        self.assertNotIn("diagnostic_fallback_format_ladder", helper)
        self.assertIn("thermal_stream_param_nonfatal_waiting_for_frame", adapter)
        self.assertLess(adapter.index("thermal_stream_param_nonfatal_waiting_for_frame"), adapter.index("thermal_stream_param_failed_error29_after_callback_ok"))


    def test_mini2_f2_context_enum_keeps_native_count_warmup_before_login(self):
        """Replaces missing error4/error.txt replay logs with the current source contract."""
        helper = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt")
        open_slice = function_slice(helper, "fun openUsbDevice(\n        context: Context", "    @Synchronized\n    fun openUsbDevice(context: Context)")

        self.assertLess(open_slice.index("USB_GetDeviceCount(context)"), open_slice.index("USB_EnumDevices(count"))
        self.assertLess(open_slice.index("USB_EnumDevices"), open_slice.index("selectOfficialContextEnumeratedDeviceInfo()"))
        self.assertLess(open_slice.index("cleanupPreviousOfficialF2Login"), open_slice.index("USB_Login(loginInfo"))
        self.assertIn("enumerationInventory=", open_slice)
        self.assertIn("officialSelection=deviceInfoList[0]", open_slice)
        self.assertIn("USB_Login(deviceInfoList[0])=ok", open_slice)
        self.assertNotIn("nativeEnum=not_run_official_context_route", helper)


    def test_mini2_f2_login_inputs_match_official_helper_without_serial_selector(self):
        """Login must use selected device index/VID/PID/fd, not a serial-number selector.

        Durable evidence: _workspace/hikmicro-analysis-20260714/final-technical-analysis.md §4.2.
        """
        analysis = read(TECH_ANALYSIS)
        helper = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt")
        login_info = read(ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/USB_USER_LOGIN_INFO.kt")

        self.assertIn("공식 로그인 구조체", analysis)
        self.assertIn("dwFd", analysis)
        open_slice = function_slice(helper, "val loginInfo = USB_USER_LOGIN_INFO().apply", "        val reg = USB_DEVICE_REG_RES")
        for token in [
            "dwDevIndex = selected.dwIndex",
            "dwVID = selected.dwVID",
            "dwPID = selected.dwPID",
            "byLoginMode = 0",
            "dwFd = selected.dwFd",
        ]:
            self.assertIn(token, open_slice)
        self.assertNotIn("szSerialNumber = selected.szSerialNumber", open_slice)
        self.assertIn("var dwFd: Int", login_info)


    def test_mini2_f2_primary_entry_matches_current_start_stream_preview_and_callback_holder(self):
        """Primary route uses stream type 103 with no diagnostic format ladder.

        Durable evidence: _workspace/hikmicro-analysis-20260714/final-technical-analysis.md §5.2.
        """
        api = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt")
        helper = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt")
        callback_holder = read(ANDROID_ROOT / "app/src/main/java/com/hik/viewercommon/data/device/api/callback/F2ModuleStreamCallback.kt")
        preview_manager = read(ANDROID_ROOT / "app/src/main/java/com/hik/viewer/manager/PreviewManagerII.java")

        g3_sources = "".join(read(path) for path in sorted((ANDROID_ROOT / "app/src/main/java/g3").glob("*.java")))
        self.assertIn("F2ModuleStreamCallback", api + callback_holder)
        self.assertIn("getFStreamCallBack()", api + callback_holder)
        self.assertIn("helper.startStreamPreview(", api)
        self.assertIn("PreviewManagerIIAppBinding.manager()", api)
        self.assertIn("PreviewManagerIIAppBinding.bind(previewManager, callback)", api)
        self.assertIn("new g3.d(streamInfoDeal)", g3_sources)
        self.assertIn("new g3.e(streamInfoDeal)", g3_sources)
        self.assertIn("processor.d(packet)", preview_manager)
        known_packet_sizes = function_slice(preview_manager, "officialProcessedF2PacketDimensions", "    void onOfficialSurfaceCreated")
        self.assertEqual(
            {"41160", "61384", "101320", "183496", "193480", "203720", "400584"},
            set(re.findall(r"case (\d+)", known_packet_sizes)),
        )
        for unproven_size in ["98304", "221184"]:
            self.assertNotIn(f"case {unproven_size}", known_packet_sizes)

        interface_entry = function_slice(helper, "fun startStreamPreview(\n        fStreamCallBack: FStreamCallBack", "    @Synchronized\n    fun stopStreamPreview")
        self.assertIn("dwStreamType = streamType", interface_entry)
        self.assertIn("USB_StartStreamCallback(callbackParam)", interface_entry)
        self.assertNotIn("startStreamPreviewCandidate", interface_entry)
        self.assertNotIn("diagnostic_fallback_format_ladder", interface_entry)

    def test_mini2_error84_recovery_uses_official_primary_without_ladder(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        api = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")
        bridge = (JAVA_ROOT / "AndroidBridge.kt").read_text(encoding="utf-8")
        activity = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        combined = helper + api + stream + bridge + activity + adapter

        self.assertIn("PreviewManagerIIAppBinding.manager()", api)
        self.assertIn("PreviewManagerIIAppBinding.bind(previewManager, callback)", api)
        self.assertIn("helper.startStreamPreview(", api)
        self.assertIn("USB_StartStreamCallback(callbackParam)", helper)
        self.assertIn("OFFICIAL_PRIMARY stopped after official F2 startStreamPreview failure", stream)
        for forbidden in [
            "F2StreamStartMode",
            "F2ResetMode",
            "HIKMICRO_PRIMARY_VIDEO_FORMAT_CANDIDATES",
            "HIKMICRO_VERBOSE_VIDEO_FORMAT_CANDIDATES",
            "diagnostic_fallback_format_ladder",
            "MANUAL_DIAGNOSTIC",
            "startMini2DiagnosticProbe",
            "runManualDiagnosticFormatLadder",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined)


    def test_mini2_error84_lifecycle_and_diagnostics_are_structured(self):
        helper = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt")
        status_model = read(JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt")
        stream = read(JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt")
        adapter = read(WEBSITE_ROOT / "android-webview.js")

        self.assertIn("official_login_reset", helper)
        self.assertIn("USB_StopChannel", helper)
        cleanup_slice = function_slice(helper, "private fun cleanupPreviousOfficialF2Login", "    private fun setThermalStreamCtrl")
        self.assertLess(cleanup_slice.index("USB_StopChannel"), cleanup_slice.index("USB_Logout"))
        self.assertLess(cleanup_slice.index("USB_Logout"), cleanup_slice.index("closeConnection"))

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
        self.assertIn("pixelCount > MAX_PREVIEW_PIXELS", stream)
        self.assertIn("unsupported_no_matrix", stream)
        preview_manager = read(ANDROID_ROOT / "app/src/main/java/com/hik/viewer/manager/PreviewManagerII.java")
        self.assertIn("officialProcessedF2PacketDimensions", preview_manager)
        self.assertIn("PreviewManagerIIAppBinding.afterOfficialG", preview_manager)
        for token in ["fd", "userId", "user_id", "channel"]:
            with self.subTest(native_field=token):
                self.assertIn(token, status_model + stream)

    def test_mini2_official_primary_has_no_manual_diagnostic_ladder(self):
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        bridge = (JAVA_ROOT / "AndroidBridge.kt").read_text(encoding="utf-8")
        activity = (JAVA_ROOT / "MainActivity.kt").read_text(encoding="utf-8")
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")

        self.assertIn("USB_StartStreamCallback(callbackParam)", helper)
        self.assertIn("F2UsbModuleApi", stream)
        self.assertIn("enum class Mini2OfficialRuntimeMode", stream + activity)
        self.assertIn("OFFICIAL_PRIMARY", stream + activity + adapter)
        self.assertNotIn("MANUAL_DIAGNOSTIC", stream + activity + adapter)
        self.assertNotIn("startMini2DiagnosticProbe", bridge + activity + adapter)
        self.assertNotIn("startDiagnosticFallbackFormatLadder", helper + stream)
        self.assertNotIn("runManualDiagnosticFormatLadder", helper + stream)
        self.assertNotIn("diagnostic_fallback_format_ladder", helper + stream + bridge + activity + adapter)


    def test_mini2_error84_secondhand_evidence_preserves_f2_last_stream_attempt_fields(self):
        """asdf.txt is historical and missing; retain reconstructable source/analysis assertions only."""
        analysis = read(TECH_ANALYSIS)
        status_model = read(JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt")
        probe = read(JAVA_ROOT / "Mini2UsbProbe.kt")
        activity = read(JAVA_ROOT / "MainActivity.kt")
        adapter = read(WEBSITE_ROOT / "android-webview.js")
        combined = status_model + probe + activity + adapter

        self.assertIn("asdf.txt", analysis)
        self.assertIn("원문은 현재 작업공간과 git 이력에서 사라졌", analysis)
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

    def test_android_webview_g004_diagnostics_separate_presence_attempt_profile_packet_converter(self):
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        diagnostic_fn = adapter[
            adapter.index("function buildMini2DiagnosticExport"):
            adapter.index("  function updateMini2DiagnosticExport")
        ]

        for token in [
            "explicitLastStreamAttempt",
            "hasExplicitLastStreamAttempt",
            "const diagnosticStream = hasCurrentRawStream ? rawStream : explicitLastStreamAttempt",
            "const lastAttempt = hasExplicitLastStreamAttempt ? explicitLastStreamAttempt : diagnosticStream",
            "const currentPresence = isAndroidPlainObject(mini2.current_usb_presence)",
            "lastAttemptRoute",
            "currentPresenceRoute",
            "currentUsbPresence",
            "lastStreamAttempt",
            "diagnosticStream",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, diagnostic_fn)

        for token in [
            "selectedProfile",
            "packetClassification",
            "packetStatus",
            "converterValidation",
            "converterProfileStatus",
            "celsiusPublishState",
            "validationEvidence",
            "androidRegexValue(stageReport, /selectedProfile=",
            "androidRegexValue(diagnosticStream.reason || live.mini2_reason || stageReport, /packet_classification=",
        ]:
            with self.subTest(diagnostic_field=token):
                self.assertIn(token, diagnostic_fn)

    def test_android_webview_g004_sanitizes_unavailable_celsius_and_unproven_thermal_roi(self):
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        sanitize_fn = adapter[
            adapter.index("function hasProvenAndroidRawMatrix"):
            adapter.index("  function classifyMini2StageReport")
        ]
        apply_fn = adapter[
            adapter.index("function applyBridgePayload"):
            adapter.index("  function replaceButtonHandler")
        ]

        for token in [
            "function sanitizeAndroidBridgePayload",
            "function hasProvenAndroidRawMatrix",
            "raw_matrix_present === true",
            "raw_matrix_status === 'available'",
            "live.thermal_roi_ready = false",
            "roi.thermal_roi_ready = false",
            "delete roi.thermal_roi",
            "['avg_c', 'min_c', 'max_c', 'delta_c'].forEach",
            "live[`temperature_${suffix}`] = null",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, sanitize_fn)

        self.assertIn("payload = sanitizeAndroidBridgePayload(payload);", apply_fn)
        self.assertLess(
            apply_fn.index("payload = sanitizeAndroidBridgePayload(payload);"),
            apply_fn.index("applyLiveMetadata(payload.live)"),
        )
        self.assertNotIn("temperature_avg_c || 0", adapter)
        self.assertNotIn("Number(live.temperature_avg_c", adapter)
        self.assertNotIn("0.0°C", adapter)
        self.assertNotIn("0.0℃", adapter)

    def test_android_webview_rejects_device_global_fallback_for_public_celsius(self):
        adapter = (WEBSITE_ROOT / "android-webview.js").read_text(encoding="utf-8")
        sanitize_fn = adapter[
            adapter.index("function isAndroidPlainObject"):
            adapter.index("  function classifyMini2StageReport")
        ]
        script = f"""
const assert = require('assert');
{sanitize_fn}
const validZero = sanitizeAndroidBridgePayload({{
  live: {{ celsius_allowed: false, raw_avg: 8192 }},
  mini2: {{
    raw_stream: {{
      raw_stream_status: 'raw_streaming_unverified',
      frame_counter: 7,
      frame_width: 256,
      frame_height: 192,
      raw_avg: 8192,
      celsius_allowed: true,
      temperature_avg_c: 0,
      temperature_min_c: -0.25,
      temperature_max_c: 0.25,
      temperature_provenance: 'device_global_summary',
      temperature_scope: 'device_global_summary',
      full_matrix_celsius_allowed: false,
    }},
  }},
}});
assert.strictEqual(validZero.live.temperature_avg_c, null);
assert.strictEqual(validZero.live.temperature_delta_c, null);
assert.strictEqual(validZero.live.temperature_source, undefined);
assert.strictEqual(validZero.live.celsius_allowed, false);

const fabricatedZero = sanitizeAndroidBridgePayload({{
  live: {{
    celsius_allowed: true,
    temperature_avg_c: 0,
    temperature_min_c: 0,
    temperature_max_c: 0,
    raw_avg: 8192,
  }},
  mini2: {{
    raw_stream: {{
      celsius_allowed: true,
      temperature_avg_c: 0,
      temperature_min_c: 0,
      temperature_max_c: 0,
      temperature_provenance: 'roi_matrix',
      temperature_scope: 'roi_matrix',
      full_matrix_celsius_allowed: false,
    }},
  }},
}});
assert.strictEqual(fabricatedZero.live.temperature_avg_c, null);
assert.strictEqual(fabricatedZero.live.celsius_allowed, false);

const blocked = sanitizeAndroidBridgePayload({{
  live: {{
    celsius_allowed: false,
    temperature_avg_c: 0,
    converter_profile_status: 'blocked_no_fake_celsius',
  }},
  mini2: {{ raw_stream: {{ celsius_allowed: false }} }},
}});
assert.strictEqual(blocked.live.temperature_avg_c, null);
assert.strictEqual(blocked.live.celsius_allowed, false);
"""
        subprocess.run(["node", "-e", script], check=True)


    def test_mini2_error84_screenshot_clusters_are_classified_and_visible_summary_is_bounded(self):
        adapter = read(WEBSITE_ROOT / "android-webview.js")
        index = read(WEBSITE_ROOT / "index.html")
        status_model = read(JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt")
        preview_manager = read(ANDROID_ROOT / "app/src/main/java/com/hik/viewer/manager/PreviewManagerII.java")

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

        diagnostic_fn = function_slice(adapter, "function buildMini2DiagnosticExport", "  function updateMini2DiagnosticExport")
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
            "selectedProfile",
            "packetClassification",
            "packetStatus",
            "rawStageReport",
        ]:
            with self.subTest(field=field):
                self.assertIn(field, diagnostic_fn)

        self.assertIn("mini2CopyDiagnosticButton", index + adapter)
        self.assertIn("mini2FullDiagnosticText", index + adapter)
        self.assertIn("navigator.clipboard.writeText", adapter)
        self.assertIn("raw_streaming_unverified", adapter + status_model)
        self.assertIn("temperature_avg_c", status_model, "explicit null Celsius keys are allowed for schema honesty")
        self.assertIn("officialProcessedF2PacketDimensions", preview_manager)
        self.assertIn("PreviewManagerIIAppBinding.afterOfficialG", preview_manager)


    def test_mini2_error6_thermal_param_failure_is_classified_and_cleans_session(self):
        """Missing error6.txt is replaced by the classifier/source contract it originally protected."""
        adapter = read(WEBSITE_ROOT / "android-webview.js")
        stream = read(JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt")
        helper = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt")

        classifier = function_slice(adapter, "function classifyMini2StageReport", "  function buildMini2DiagnosticExport")
        self.assertIn("thermal_stream_param_failed_error29_after_callback_ok", classifier)
        self.assertIn("USB_SET_THERMAL_STREAM_PARAM=failed.*error=29", classifier)
        self.assertIn("thermal_stream_param_nonfatal_waiting_for_frame", classifier)
        self.assertIn("USB_SetThermalStreamParam(videoCodingType)", helper)
        self.assertNotIn("USB_SET_THERMAL_STREAM_PARAM=failed_nonfatal", helper)
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

    def test_mini2_official_primary_interface_route_and_bounded_start_order_are_explicit(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        api = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")

        self.assertIn("streamCallback.getFStreamCallBack()", api)
        self.assertIn("helper.startStreamPreview(", api)
        self.assertIn("USB_StartStreamCallback(callbackParam)", helper)
        self.assertIn("HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE: Int = 103", helper)
        self.assertNotIn("repo_keepalive_safety_deviation", api + helper)

        for forbidden in [
            "enum class F2StreamStartMode",
            "OFFICIAL_JNA",
            "OFFICIAL_JNI",
            "official_jna_low_format_101_103",
            "official_jna_low_format_102_103",
            "official_jna_low_format_104_103",
            "appendVerboseOnlyDiagnostics",
            "diagnostic_fallback_format_ladder",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, helper + api + stream)
        for structured_field in ["val fd: Int", "val userId: Int", '.put("fd", fd)', '.put("user_id", userId)']:
            with self.subTest(structured_field=structured_field):
                self.assertIn(structured_field, helper + stream)

        official_entry = function_slice(helper, "fun startStreamPreview(\n        fStreamCallBack: FStreamCallBack", "    @Synchronized\n    fun stopStreamPreview")
        self.assertLess(official_entry.index("USB_SetVideoParam"), official_entry.index("USB_StartStreamCallback(callbackParam)"))
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
        self.assertRegex(compact_helper, r"private fun USB_StartStreamCallback\([^)]*\): Boolean")
        self.assertIn("val callbackStarted = USB_StartStreamCallback(callbackParam)", helper)
        self.assertIn("channel = rawChannel", helper)
        self.assertIn("return rawChannel != -1", helper)
        self.assertIn("fun USB_StartStreamCallback(userId: Int", java_interface)
        self.assertIn("USB_StartStreamCallback_jni(userId, param)", java_interface)

        self.assertNotIn("official_wrapper_parity_ok", status_model)
        for token in [
            "java_interface_callback_entry_count",
            "java_interface_callback_entry_detail",
            "invalid_packet_size_timeout",
            "channel",
            "fd",
            "user_id",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, status_model + adapter)

        self.assertIn("current_usb_presence", probe + adapter)
        self.assertIn("last_stream_attempt", probe + adapter)
        self.assertIn("passive_raw_stream", probe)
        self.assertIn("if (attemptRawStream)", probe)
        self.assertIn('result.put("last_stream_attempt", JSONObject.NULL)', probe)


    def test_mini2_jna_structure_field_order_is_locked_against_source_and_current_analysis(self):
        """Old .omx/analysis markdown is ephemeral; source plus final analysis are durable here."""
        jna = read(ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/jna/HCUSBSDKByJNA.kt")
        analysis = read(TECH_ANALYSIS)

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
        ]:
            with self.subTest(evidence=evidence):
                self.assertIn(evidence, jna + analysis)

    def test_mini2_lifecycle_teardown_invariants_do_not_reintroduce_reset_enums(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        java_interface = (ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/JavaInterface.kt").read_text(encoding="utf-8")
        preview_manager = (ANDROID_ROOT / "app/src/main/java/com/hik/viewer/manager/PreviewManagerII.java").read_text(encoding="utf-8")

        for token in [
            "enum class F2ResetMode",
            "LIGHTWEIGHT_RETRY_NO_FD_CLOSE",
            "FULL_SESSION_RESET_BEFORE_CANDIDATE",
            "lightweight_retry_no_fd_close",
            "full_session_reset_before_candidate",
        ]:
            with self.subTest(removed_reset_token=token):
                self.assertNotIn(token, helper)

        self.assertIn("PreviewManagerII$d implements FStreamCallBack", read(ANDROID_ROOT / "app/src/main/java/com/hik/viewer/manager/PreviewManagerII$d.java"))
        self.assertIn("rememberFrame", preview_manager)
        self.assertIn("lastStageReport", helper)
        self.assertIn("lastFailureReason", helper)

        cleanup_slice = function_slice(helper, "private fun cleanupPreviousOfficialF2Login", "    private fun setThermalStreamCtrl")
        self.assertLess(cleanup_slice.index("invokeStopChannel(currentUserId, currentChannel)"), cleanup_slice.index("logoutOperation(currentUserId)"))
        self.assertIn("stopChannelOperation(currentUserId, currentChannel)", cleanup_slice)
        self.assertLess(cleanup_slice.index("logoutOperation(currentUserId)"), cleanup_slice.index("selected?.closeConnection()"))
        self.assertIn("invalidateStreamCallbackRegistration(userId)", java_interface)
        self.assertIn("activeStreamRegistrationEpochs[userId] = 0L", java_interface)
        self.assertIn("USB_StopChannel(userId: Int, channel: Int)", java_interface)

    def test_mini2_login_failure_cleanup_and_stage_report_evidence(self):
        helper = (ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").read_text(encoding="utf-8")
        stream = (JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt").read_text(encoding="utf-8")

        self.assertIn("USB_Cleanup", helper)
        self.assertIn("sdkInited = false", helper)
        self.assertIn("USB_Login=failed", helper)
        self.assertIn("stageReport", helper + stream)
        for token in ["selectedFd=", "selectedIndex=", "targetVid=", "targetPid=", "userId", "channel", "F2UsbModuleApi"]:
            self.assertIn(token, helper + stream)
        self.assertNotIn("official_primary_f2_lifecycle", helper + stream)


    def test_mini2_f2_no_fake_celsius_success(self):
        status_model = read(JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt")
        stream = read(JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt")
        helper = read(ANDROID_ROOT / "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt")
        adapter = read(WEBSITE_ROOT / "android-webview.js")

        self.assertIn("device-reported Celsius summary is allowed only when provenance=device_global_summary", stream)
        self.assertIn("raw_streaming_unverified", status_model)
        self.assertIn("official_g3_preview_stream_info", stream)
        self.assertIn('put("temperature_avg_c", JSONObject.NULL)', status_model)
        self.assertIn('put("device_global_temperature_avg_c", summary?.avgC ?: JSONObject.NULL)', status_model)
        self.assertIn("live[`temperature_${suffix}`] = null", adapter)
        self.assertNotIn("temperatureCelsius = raw", status_model + stream + helper)
        self.assertNotIn("temperature_avg_c || 0", adapter)
        self.assertNotIn("0.0°C", adapter)
        self.assertNotIn("0.0℃", adapter)


    def test_mini2_current_raw_packet_status_rejects_unknown_packets_without_offset0_matrix(self):
        """error9.txt is gone; assert the current Mini2 packet contract instead.

        Durable evidence: _workspace/hikmicro-analysis-20260714/final-technical-analysis.md §7-§8.
        """
        analysis = read(TECH_ANALYSIS)
        preview_manager = read(ANDROID_ROOT / "app/src/main/java/com/hik/viewer/manager/PreviewManagerII.java")
        official_processor = read(ANDROID_ROOT / "app/src/main/java/g3/d.java") + read(ANDROID_ROOT / "app/src/main/java/g3/e.java")
        stream = read(JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt")
        status_model = read(JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt")
        main = read(JAVA_ROOT / "MainActivity.kt")

        self.assertIn("패킷 0번 바이트부터 16비트 raw 온도 행렬", analysis)
        self.assertIn("공식 처리 구조와 다르", analysis)
        self.assertIn("HIKMICRO_THERMAL_IMAGE_HEIGHT = 192", stream)
        self.assertIn("transport_frame_height", status_model)
        self.assertIn("raw_avg", status_model)
        self.assertIn("raw_min", status_model)
        self.assertIn("raw_max", status_model)
        self.assertIn('live.put("raw_avg"', main)
        self.assertIn('live.put("raw_min"', main)
        self.assertIn('live.put("raw_max"', main)
        self.assertIn("officialProcessedF2PacketDimensions", preview_manager)
        self.assertIn("processor.d(packet)", preview_manager)
        self.assertIn("PreviewInfoDataBean", official_processor)
        self.assertIn("frameInfoData.length", official_processor)
        self.assertNotIn("bytes[0]", official_processor, "official processor must not build raw matrices from packet byte zero")

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
        index = read(WEBSITE_ROOT / "index.html")
        adapter = read(WEBSITE_ROOT / "android-webview.js")
        bridge = read(JAVA_ROOT / "AndroidBridge.kt")
        main = read(JAVA_ROOT / "MainActivity.kt")
        status_model = read(JAVA_ROOT / "thermal/Mini2RawStreamStatus.kt")
        stream = read(JAVA_ROOT / "thermal/HikmicroJnaMini2Stream.kt")

        self.assertIn("mini2RotateButton", index + adapter)
        self.assertIn("rotateThermalPreview", bridge)
        self.assertIn("rotateThermalPreviewFromBridge", main)
        self.assertIn("HIKMICRO_DEFAULT_DISPLAY_ROTATION_DEGREES = 90", stream)
        self.assertIn("rotatePreviewClockwise", stream)
        self.assertIn("rotateThermalPixels", stream)
        self.assertIn("preview_rotation_degrees", status_model + stream + main)
        self.assertIn("readBridgeJson('rotateThermalPreview')", adapter)
        self.assertIn("적외선 180° 회전", index)
        self.assertIn("적외선 회전", adapter)

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

class TestHikmicroG002ParityContracts(unittest.TestCase):
    def test_g002_thermal_stream_ctrl_get_uses_2110_set_uses_2111(self):
        java_interface = read(ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/JavaInterface.kt")
        get_bridge_index = java_interface.rindex("override fun USB_GetThermalStreamCtrl")
        set_bridge_index = java_interface.rindex("override fun USB_SetThermalStreamCtrl")
        get_slice = java_interface[get_bridge_index:set_bridge_index]
        set_slice = java_interface[set_bridge_index:java_interface.index("        override fun USB_StopChannel", set_bridge_index)]

        self.assertIn("private const val USB_GET_THERMAL_STREAM_CTRL = 2110", java_interface)
        self.assertIn("private const val USB_SET_THERMAL_STREAM_CTRL = 2111", java_interface)
        self.assertIn("getDeviceConfig(userId, USB_GET_THERMAL_STREAM_CTRL, nativeParam)", get_slice)
        self.assertIn("setDeviceConfig(userId, USB_SET_THERMAL_STREAM_CTRL, nativeParam)", set_slice)
        self.assertLess(get_slice.index("param.byEnable = nativeParam.byEnable"), len(get_slice))

    def test_g002_f2_load_plan_only_attempts_hcusbsdk_and_defers_inventory(self):
        backend = read(ANDROID_ROOT / "app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroNativeBackend.kt")
        probe = read(ANDROID_ROOT / "app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt")

        self.assertIn('HikmicroMini2ModuleType.F2 -> setOf("libHCUSBSDK.so")', backend)
        self.assertIn('HikmicroMini2ModuleType.F1 -> setOf("lib_thermal_module.so")', backend)
        self.assertIn('"libuvc.so", "libusb1.0.so"', backend)
        self.assertIn('"packaged_dt_needed_dependency_deferred"', backend)
        self.assertIn('"packaged_deferred_not_attempted"', backend)
        self.assertIn("moduleType = moduleType", probe)
        self.assertNotIn('setOf("libHCUSBSDK.so",\n                "libMTlib.so"', backend)

    def test_g002_hcusbsdk_jni_load_site_is_not_reached_by_passive_probe(self):
        jni = read(ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/jni/HCUSBSDKByJNI.kt")
        java_interface = read(ANDROID_ROOT / "app/src/main/java/com/hcusbsdk/Interface/JavaInterface.kt")
        probe = read(ANDROID_ROOT / "app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt")

        self.assertIn('System.loadLibrary("HCUSBSDK")', jni)
        self.assertIn("USB_StartStreamCallback_jni", java_interface)
        self.assertIn("com.hcusbsdk.jni.HCUSBSDKByJNI.getInstance()", java_interface)
        passive_slice = function_slice(probe, "private fun passiveRawStreamStatus", "    private fun safePassiveRawStreamStatus")
        self.assertNotIn("ensureLibrariesLoaded", passive_slice)
        self.assertNotIn("HCUSBSDKByJNI", passive_slice)
