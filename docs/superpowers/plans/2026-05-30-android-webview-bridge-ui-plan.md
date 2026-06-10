# Android WebView Bridge UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 `website/` 웹 UI를 APK 안에서 그대로 띄우고, Android native 권한/하드웨어 기능을 JavaScript bridge로 연결해 모바일 화면 불일치와 Mini2 권한 크래시를 해결한다.

**Architecture:** `MainActivity`는 native 위젯 화면을 만들지 않고 `WebView` shell을 띄운다. `website/index.html`, `website/styles.css`, `website/app.js`, 폰트 파일을 Android assets로 패키징하고, `AndroidBridge`가 CameraX/Mini2/session 상태를 JSON으로 노출한다. Mini2는 Android USB host 권한 요청을 native에서 처리하되, 검증된 converter가 없으면 `blocked`/`raw_unverified`만 웹 UI에 전달한다.

**Tech Stack:** Kotlin, Android WebView, `@JavascriptInterface`, Android USB Host `UsbManager`, CameraX, Python `unittest`, Gradle `assembleDebug`.

---

## File structure

- Modify: `mobile/android/app/build.gradle.kts`
  - WebView/JavaScript bridge에 필요한 Android dependency는 추가하지 않는다. 기존 AndroidX/CameraX를 유지한다.
- Modify: `mobile/android/app/src/main/AndroidManifest.xml`
  - WebView asset shell에는 인터넷이 필요 없다. `INTERNET` permission은 계속 넣지 않는다.
  - USB host feature와 Mini2 attached intent는 유지한다.
- Modify: `mobile/android/app/src/main/res/xml/mini2_device_filter.xml`
  - HIKMICRO vendor `0x2bdf`는 유지하되 product를 특정하지 않아 Android attach intent 누락을 줄인다.
- Create: `mobile/android/app/src/main/assets/web/index.html`
- Create: `mobile/android/app/src/main/assets/web/styles.css`
- Create: `mobile/android/app/src/main/assets/web/app.js`
- Create: `mobile/android/app/src/main/assets/web/assets/fonts/PretendardVariable.woff2`
  - 위 네 파일은 repo root `website/`의 현재 UI 자산을 빌드 입력으로 복사한 사본이다.
- Create: `mobile/android/app/src/main/java/kr/auto/titration/mobile/AndroidBridge.kt`
  - WebView JS가 호출하는 native API 표면: app status, Mini2 probe, ROI lock, recording toggle, CSV preview metadata.
- Modify: `mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt`
  - 기존 native `LinearLayout/Button/TextView` UI를 제거하고 WebView shell + bridge registration으로 대체한다.
- Modify: `mobile/android/app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt`
  - Android 14+/targetSdk 35에서 USB permission PendingIntent가 크래시하지 않도록 explicit package intent와 safe flags를 사용한다.
  - Mini2 후보 탐지는 `vendorId == 0x2bdf` 우선, 알려진 productId `0x0102`는 evidence에 기록한다.
- Modify: `tests/test_android_scaffold.py`
  - WebView asset, bridge, no-native-dashboard, Android 14 USB permission guard, no fake Celsius를 잠근다.
- Modify: `tests/test_readme_docs.py` or `mobile/android/README.md`
  - Android 앱이 WebView shell + native bridge 구조임을 문서화한다.

---

### Task 1: Lock the intended WebView-shell behavior with failing tests

**Files:**
- Modify: `tests/test_android_scaffold.py`

- [ ] **Step 1: Add the failing WebView asset and bridge test**

Insert this method after `test_android_project_contains_phone_standalone_foundation`:

```python
    def test_android_app_packages_existing_web_ui_as_webview_shell(self):
        root = Path("mobile/android")
        main = (root / "app/src/main/java/kr/auto/titration/mobile/MainActivity.kt").read_text(encoding="utf-8")
        bridge_path = root / "app/src/main/java/kr/auto/titration/mobile/AndroidBridge.kt"
        assets = root / "app/src/main/assets/web"

        expected_assets = [
            assets / "index.html",
            assets / "styles.css",
            assets / "app.js",
            assets / "assets/fonts/PretendardVariable.woff2",
        ]
        for path in expected_assets:
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"missing packaged web UI asset {path}")

        index = (assets / "index.html").read_text(encoding="utf-8")
        styles = (assets / "styles.css").read_text(encoding="utf-8")
        app_js = (assets / "app.js").read_text(encoding="utf-8")
        bridge = bridge_path.read_text(encoding="utf-8")

        self.assertIn("WebView", main)
        self.assertIn("addJavascriptInterface", main)
        self.assertIn("AndroidBridge", main)
        self.assertIn("file:///android_asset/web/index.html", main)
        self.assertNotIn("LinearLayout.VERTICAL", main)
        self.assertNotIn("Button(this)", main)
        self.assertIn("Auto Titration Assistant", index)
        self.assertIn("카메라 + Mini2 수집", index)
        self.assertIn("Mini2 적외선", index)
        self.assertIn("Pretendard", styles)
        self.assertIn("window.AutoTitrationAndroid", app_js)
        self.assertIn("@JavascriptInterface", bridge)
        self.assertIn("probeMini2", bridge)
        self.assertIn("getStatusJson", bridge)
```

- [ ] **Step 2: Add the failing Mini2 USB crash guard test**

Insert this method after the WebView shell test:

```python
    def test_mini2_usb_permission_path_is_android14_safe_and_vendor_tolerant(self):
        root = Path("mobile/android")
        probe = (root / "app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt").read_text(encoding="utf-8")
        device_filter = (root / "app/src/main/res/xml/mini2_device_filter.xml").read_text(encoding="utf-8")

        self.assertIn(".setPackage(context.packageName)", probe)
        self.assertIn("PendingIntent.FLAG_UPDATE_CURRENT", probe)
        self.assertIn("findMini2Candidate", probe)
        self.assertIn("mini2_product_id_detected", probe)
        self.assertIn("device.vendorId == MINI2_VENDOR_ID", probe)
        self.assertIn("knownMini2Product", probe)
        self.assertIn('<usb-device vendor-id="11231" />', device_filter)
        self.assertNotIn('product-id="258"', device_filter)
        self.assertNotIn("FLAG_MUTABLE\n        } else {\n            0", probe)
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
python3 -m unittest \
  tests.test_android_scaffold.AndroidScaffoldTests.test_android_app_packages_existing_web_ui_as_webview_shell \
  tests.test_android_scaffold.AndroidScaffoldTests.test_mini2_usb_permission_path_is_android14_safe_and_vendor_tolerant \
  -v
```

Expected: FAIL because `AndroidBridge.kt` and `mobile/android/app/src/main/assets/web/*` do not exist yet, `MainActivity.kt` still uses native `LinearLayout`, and `Mini2UsbProbe.kt` still uses the old permission intent.

---

### Task 2: Package the existing website assets inside the APK

**Files:**
- Create: `mobile/android/app/src/main/assets/web/index.html`
- Create: `mobile/android/app/src/main/assets/web/styles.css`
- Create: `mobile/android/app/src/main/assets/web/app.js`
- Create: `mobile/android/app/src/main/assets/web/assets/fonts/PretendardVariable.woff2`
- Modify: `mobile/android/app/src/main/assets/web/app.js`

- [ ] **Step 1: Copy current website assets into Android assets**

Run:

```bash
mkdir -p mobile/android/app/src/main/assets/web/assets/fonts
cp website/index.html mobile/android/app/src/main/assets/web/index.html
cp website/styles.css mobile/android/app/src/main/assets/web/styles.css
cp website/app.js mobile/android/app/src/main/assets/web/app.js
cp website/assets/fonts/PretendardVariable.woff2 mobile/android/app/src/main/assets/web/assets/fonts/PretendardVariable.woff2
```

Expected: files exist under `mobile/android/app/src/main/assets/web/`.

- [ ] **Step 2: Add a small Android bridge adapter to the copied `app.js`**

Append this exact block to `mobile/android/app/src/main/assets/web/app.js`:

```javascript

// Android APK bridge: keep the existing web UI, but let native Android own sensors/permissions.
window.AutoTitrationAndroid = window.AutoTitrationAndroid || (() => {
  const nativeBridge = window.AndroidBridge;

  function parseJson(raw, fallback = {}) {
    try {
      return JSON.parse(raw || '{}');
    } catch (error) {
      return { ...fallback, ok: false, error: String(error && error.message ? error.message : error) };
    }
  }

  function applyAndroidStatus(status) {
    if (typeof setText === 'function') {
      setText('mobileSourceValue', 'Android APK');
      setText('mobilePairStatus', status.bridge || 'native bridge');
      setText('mobileRoiStatus', status.session_state || '-');
      setText('previewStatus', status.message || 'Android WebView bridge ready');
    }
  }

  return {
    refreshStatus() {
      const status = nativeBridge?.getStatusJson ? parseJson(nativeBridge.getStatusJson()) : { bridge: 'missing' };
      applyAndroidStatus(status);
      return status;
    },
    probeMini2() {
      const result = nativeBridge?.probeMini2 ? parseJson(nativeBridge.probeMini2()) : { ok: false, error: 'AndroidBridge missing' };
      if (typeof setText === 'function') {
        setText('statusLabel', result.mini2_status || result.error || '-');
        setText('temperatureUnit', result.thermal_calibrated ? '℃' : 'raw');
        setText('previewStatus', result.mini2_reason || result.error || 'Mini2 checked');
      }
      return result;
    },
  };
})();

window.addEventListener('DOMContentLoaded', () => {
  if (!window.AndroidBridge || !window.AutoTitrationAndroid) return;
  window.AutoTitrationAndroid.refreshStatus();
  const mini2Button = document.getElementById('mobilePairButton');
  if (mini2Button) {
    mini2Button.textContent = 'Mini2 USB 확인';
    mini2Button.addEventListener('click', () => window.AutoTitrationAndroid.probeMini2());
  }
});
```

- [ ] **Step 3: Run the WebView asset test and verify partial RED**

Run:

```bash
python3 -m unittest tests.test_android_scaffold.AndroidScaffoldTests.test_android_app_packages_existing_web_ui_as_webview_shell -v
```

Expected: still FAIL because `AndroidBridge.kt` does not exist and `MainActivity.kt` has not switched to WebView yet. Asset-related assertions should pass.

---

### Task 3: Add the Android JavaScript bridge

**Files:**
- Create: `mobile/android/app/src/main/java/kr/auto/titration/mobile/AndroidBridge.kt`

- [ ] **Step 1: Create `AndroidBridge.kt`**

Create the file with this content:

```kotlin
package kr.auto.titration.mobile

import android.webkit.JavascriptInterface
import kr.auto.titration.mobile.export.SessionExporter
import kr.auto.titration.mobile.session.PhoneRunSession
import org.json.JSONObject

/** JavaScript bridge for the packaged website UI running inside Android WebView. */
class AndroidBridge(
    private val session: PhoneRunSession,
    private val mini2Probe: Mini2UsbProbe,
) {
    @JavascriptInterface
    fun getStatusJson(): String {
        return JSONObject()
            .put("ok", true)
            .put("bridge", "android_webview_native")
            .put("message", "기존 웹 UI + Android 권한 브리지 실행 중")
            .put("session_state", session.state.name.lowercase())
            .put("run_id", session.runId)
            .put("frame_count", session.frameCount)
            .put("csv_rows", session.recordedRowCount)
            .toString()
    }

    @JavascriptInterface
    fun probeMini2(): String {
        return try {
            val evidence = mini2Probe.probe()
            evidence.put("ok", true)
            evidence.toString()
        } catch (error: RuntimeException) {
            JSONObject()
                .put("ok", false)
                .put("mini2_status", "blocked")
                .put("mini2_reason", "Mini2 USB 확인 실패: ${error.message ?: error.javaClass.simpleName}")
                .put("thermal_calibrated", false)
                .toString()
        }
    }

    @JavascriptInterface
    fun lockRoi(): String {
        return try {
            session.markRoiLocked()
            JSONObject()
                .put("ok", true)
                .put("session_state", session.state.name.lowercase())
                .put("message", "ROI 잠금 완료")
                .toString()
        } catch (error: IllegalArgumentException) {
            JSONObject()
                .put("ok", false)
                .put("session_state", session.state.name.lowercase())
                .put("error", error.message ?: "ROI lock failed")
                .toString()
        }
    }

    @JavascriptInterface
    fun csvPreviewJson(): String {
        val csv = SessionExporter.buildCsv(session.config, session.rows)
        return JSONObject()
            .put("ok", true)
            .put("csv_rows", session.recordedRowCount)
            .put("csv_bytes", csv.length)
            .toString()
    }
}
```

- [ ] **Step 2: Run the WebView asset test and verify partial RED**

Run:

```bash
python3 -m unittest tests.test_android_scaffold.AndroidScaffoldTests.test_android_app_packages_existing_web_ui_as_webview_shell -v
```

Expected: still FAIL because `MainActivity.kt` has not switched to WebView yet.

---

### Task 4: Replace the native Android widget UI with WebView shell

**Files:**
- Modify: `mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt`

- [ ] **Step 1: Replace `MainActivity.kt` imports and class body with WebView shell**

Replace the file content with:

```kotlin
package kr.auto.titration.mobile

import android.Manifest
import android.annotation.SuppressLint
import android.os.Bundle
import android.os.SystemClock
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import kr.auto.titration.mobile.data.StandaloneFeatureFrame
import kr.auto.titration.mobile.session.PhoneRunSession
import kr.auto.titration.mobile.thermal.ThermalStatus
import kr.auto.titration.mobile.vision.Roi
import kr.auto.titration.mobile.vision.VisibleFeatureExtractor
import kr.auto.titration.mobile.vision.VisibleFeatures

/** WebView shell that reuses the existing website UI while Android owns permissions and sensors. */
class MainActivity : ComponentActivity() {
    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private val frameId = AtomicLong(0)
    private val runSession = PhoneRunSession()
    private lateinit var webView: WebView
    private lateinit var mini2Probe: Mini2UsbProbe
    private var lockedVisibleRoi: Roi? = null
    private var previousVisibleFeatures: VisibleFeatures? = null

    private val cameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            startCameraXImageAnalysis()
        } else {
            postWebStatus("카메라 권한이 필요합니다.")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        mini2Probe = Mini2UsbProbe(this)
        runSession.startSetup()
        webView = buildWebView()
        setContentView(webView)
        cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraExecutor.shutdown()
        webView.destroy()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun buildWebView(): WebView {
        return WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.cacheMode = WebSettings.LOAD_NO_CACHE
            settings.allowFileAccess = true
            settings.allowContentAccess = true
            webViewClient = WebViewClient()
            webChromeClient = WebChromeClient()
            addJavascriptInterface(AndroidBridge(runSession, mini2Probe), "AndroidBridge")
            loadUrl("file:///android_asset/web/index.html")
        }
    }

    private fun startCameraXImageAnalysis() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            try {
                val cameraProvider = cameraProviderFuture.get()
                val preview = Preview.Builder().build()
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                    .also { imageAnalysis ->
                        imageAnalysis.setAnalyzer(cameraExecutor) { imageProxy ->
                            analyzeVisibleFrame(imageProxy)
                        }
                    }

                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(
                    this,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    analysis,
                )
                postWebStatus("CameraX ImageAnalysis 실행 중 · Android WebView bridge")
            } catch (error: RuntimeException) {
                postWebStatus("카메라 시작 실패: ${error.message ?: error.javaClass.simpleName}")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun analyzeVisibleFrame(imageProxy: ImageProxy) {
        try {
            val id = frameId.incrementAndGet()
            if (lockedVisibleRoi == null) {
                lockedVisibleRoi = VisibleFeatureExtractor.defaultCenterRoi(imageProxy.width, imageProxy.height)
            }
            val visible = VisibleFeatureExtractor.extract(
                image = imageProxy,
                roi = lockedVisibleRoi ?: VisibleFeatureExtractor.defaultCenterRoi(imageProxy.width, imageProxy.height),
                previous = previousVisibleFeatures,
            )
            previousVisibleFeatures = visible
            val frame = StandaloneFeatureFrame(
                runId = runSession.runId,
                frameId = id,
                capturedElapsedNanos = SystemClock.elapsedRealtimeNanos(),
                visible = visible,
                thermalStatus = currentThermalStatus(),
            )
            runSession.recordFrame(frame)
            if (id == 1L || id % 25L == 0L) {
                val visibleMeanText = visible.vMean?.let { String.format("%.1f", it) } ?: "-"
                postWebStatus("state=${runSession.state} · frames=${runSession.frameCount} · csv=${runSession.recordedRowCount} · V≈$visibleMeanText · thermal=${frame.thermalStatus.state}")
            }
        } catch (error: RuntimeException) {
            postWebStatus("프레임 분석 실패: ${error.message ?: error.javaClass.simpleName}")
        } finally {
            imageProxy.close()
        }
    }

    private fun currentThermalStatus(): ThermalStatus {
        return try {
            mini2Probe.probeStatus()
        } catch (error: RuntimeException) {
            ThermalStatus.blocked("Mini2 USB 확인 실패: ${error.message ?: error.javaClass.simpleName}")
        }
    }

    private fun postWebStatus(message: String) {
        runOnUiThread {
            val escaped = JSONObjectString.escape(message)
            webView.evaluateJavascript(
                "if (window.AutoTitrationAndroid) { window.AutoTitrationAndroid.refreshStatus(); }" +
                    "if (typeof setText === 'function') { setText('previewStatus', '$escaped'); }",
                null,
            )
        }
    }
}

private object JSONObjectString {
    fun escape(value: String): String {
        return value
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "")
    }
}
```

- [ ] **Step 2: Run the WebView shell test and verify GREEN for UI shell**

Run:

```bash
python3 -m unittest tests.test_android_scaffold.AndroidScaffoldTests.test_android_app_packages_existing_web_ui_as_webview_shell -v
```

Expected: PASS.

---

### Task 5: Harden Mini2 USB permission and vendor detection

**Files:**
- Modify: `mobile/android/app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt`
- Modify: `mobile/android/app/src/main/res/xml/mini2_device_filter.xml`

- [ ] **Step 1: Update the Android USB device filter**

Replace `mobile/android/app/src/main/res/xml/mini2_device_filter.xml` with:

```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <!-- HIKMICRO Mini2 family: keep vendor-only attach intent because product IDs can differ by firmware/model. -->
    <usb-device vendor-id="11231" />
</resources>
```

- [ ] **Step 2: Replace `Mini2UsbProbe.kt` with safe permission code**

Replace the file content with:

```kotlin
package kr.auto.titration.mobile

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import kr.auto.titration.mobile.thermal.ThermalStatus
import org.json.JSONObject

private const val MINI2_VENDOR_ID = 0x2bdf
private const val MINI2_PRODUCT_ID = 0x0102
private const val USB_PERMISSION_ACTION = "kr.auto.titration.mobile.USB_PERMISSION"

/** USB host probe for HIKMICRO Mini2 in phone-standalone/WebView-bridge mode. */
class Mini2UsbProbe(private val context: Context) {
    private val usbManager: UsbManager = context.getSystemService(Context.USB_SERVICE) as UsbManager
    private val permissionRequests: MutableSet<String> = mutableSetOf()

    fun probe(): JSONObject {
        val mini2 = findMini2Candidate()
        val status = probeStatus()
        val result = JSONObject()
            .put("thermal_calibrated", status.calibrated)
            .put("mini2_vendor_id", String.format("0x%04x", MINI2_VENDOR_ID))
            .put("mini2_product_id_expected", String.format("0x%04x", MINI2_PRODUCT_ID))
            .put("mini2_status", status.state.name.lowercase())
            .put("mini2_reason", status.reason)
            .put("thermal_conversion_model", status.conversionModel)

        if (mini2 != null) {
            result
                .put("mini2_device_name", mini2.deviceName)
                .put("mini2_product_id_detected", String.format("0x%04x", mini2.productId))
                .put("mini2_known_product", knownMini2Product(mini2))
                .put("mini2_interface_count", mini2.interfaceCount)
        }
        return result
    }

    fun probeStatus(): ThermalStatus {
        val mini2 = findMini2Candidate()
            ?: return ThermalStatus.blocked("Mini2 USB device not found on Android USB host")

        if (!usbManager.hasPermission(mini2)) {
            val requested = requestPermissionOnce(mini2)
            return if (requested) {
                ThermalStatus.blocked("USB permission requested; waiting for Android grant")
            } else {
                ThermalStatus.blocked("USB permission pending; waiting for Android grant")
            }
        }

        return ThermalStatus.rawUnverified(
            "USB permission granted, but calibrated Mini2 Android converter has not passed validation gates",
        )
    }

    fun findMini2Device(): UsbDevice? = findMini2Candidate()

    fun findMini2Candidate(): UsbDevice? {
        return usbManager.deviceList.values
            .filter { device -> device.vendorId == MINI2_VENDOR_ID }
            .sortedWith(compareByDescending<UsbDevice> { knownMini2Product(it) }.thenBy { it.productId })
            .firstOrNull()
    }

    fun requestPermission(): Boolean {
        val device = findMini2Candidate() ?: return false
        return requestPermission(device)
    }

    fun requestPermission(device: UsbDevice): Boolean {
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            PendingIntent.FLAG_IMMUTABLE
        } else {
            0
        }
        val permissionIntent = PendingIntent.getBroadcast(
            context,
            0,
            Intent(USB_PERMISSION_ACTION).setPackage(context.packageName),
            flags,
        )
        usbManager.requestPermission(device, permissionIntent)
        return true
    }

    private fun requestPermissionOnce(device: UsbDevice): Boolean {
        return if (permissionRequests.add(device.deviceName)) {
            requestPermission(device)
        } else {
            false
        }
    }

    private fun knownMini2Product(device: UsbDevice): Boolean = device.productId == MINI2_PRODUCT_ID

    /** Legacy compatibility for older mobile-frame protocol tests. */
    fun attachThermalFields(frame: JSONObject): JSONObject {
        val evidence = probe()
        frame.put("thermal_calibrated", false)
        frame.put("thermal_status", evidence.optString("mini2_status", "blocked"))
        frame.put("thermal_raw_status", evidence.optString("mini2_status", "blocked"))
        frame.put("thermal_raw_note", evidence.optString("mini2_reason", "Mini2 not calibrated"))
        frame.put("mini2", evidence)
        return frame
    }
}
```

- [ ] **Step 3: Run the Mini2 USB guard test and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_android_scaffold.AndroidScaffoldTests.test_mini2_usb_permission_path_is_android14_safe_and_vendor_tolerant -v
```

Expected: PASS.

---

### Task 6: Update Android docs for the new WebView + native bridge design

**Files:**
- Modify: `mobile/android/README.md`
- Modify: `tests/test_readme_docs.py` if it has Android wording assertions

- [ ] **Step 1: Replace the Android README opening with WebView bridge wording**

Update the first section of `mobile/android/README.md` to include these paragraphs:

```markdown
# Auto Titration Android WebView Bridge

This Android project packages the existing `website/` dashboard UI inside an Android `WebView` so the phone screen matches the web dashboard instead of using a separate native mock UI.

The Android layer owns permissions and hardware access. `AndroidBridge` exposes safe JavaScript calls for app status, Mini2 USB probing, ROI/session state, and CSV preview metadata. The WebView UI remains the presentation layer; CameraX, USB host permission, and Mini2 evidence status remain native Android responsibilities.
```

Keep the existing no-fake-Celsius and pump manual-only sections.

- [ ] **Step 2: Run docs and Android scaffold tests**

Run:

```bash
python3 -m unittest tests.test_android_scaffold tests.test_readme_docs -v
```

Expected: PASS.

---

### Task 7: Build and inspect the APK

**Files:**
- Output: `mobile/android/app/build/outputs/apk/debug/app-debug.apk`
- Output copy: `dist/auto_titrator-debug.apk`
- Output copy: `/mnt/c/Users/Jio/Downloads/auto_titrator-debug.apk`

- [ ] **Step 1: Run Android build**

Run:

```bash
ANDROID_HOME=/home/jio/code/auto_titration/.tools/android-sdk \
ANDROID_SDK_ROOT=/home/jio/code/auto_titration/.tools/android-sdk \
JAVA_HOME=/home/jio/code/auto_titration/.tools/jdk/temurin-17 \
GRADLE_USER_HOME=/home/jio/code/auto_titration/.gradle-cache \
/home/jio/code/auto_titration/.tools/gradle/gradle-8.10.2/bin/gradle \
  -p mobile/android assembleDebug
```

Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 2: Verify web assets are packaged inside APK**

Run:

```bash
unzip -l mobile/android/app/build/outputs/apk/debug/app-debug.apk | grep -E 'assets/web/(index.html|styles.css|app.js|assets/fonts/PretendardVariable.woff2)'
```

Expected output includes all four asset paths.

- [ ] **Step 3: Copy APK to project dist and Windows Downloads**

Run:

```bash
mkdir -p dist
cp -f mobile/android/app/build/outputs/apk/debug/app-debug.apk dist/auto_titrator-debug.apk
cp -f dist/auto_titrator-debug.apk /mnt/c/Users/Jio/Downloads/auto_titrator-debug.apk
sha256sum dist/auto_titrator-debug.apk /mnt/c/Users/Jio/Downloads/auto_titrator-debug.apk
```

Expected: both SHA256 values match.

---

### Task 8: Final verification pass

**Files:**
- No source edits in this task.

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
python3 -m unittest tests.test_android_scaffold tests.test_readme_docs -v
```

Expected: all tests pass.

- [ ] **Step 2: Run Android build again after docs/test updates**

Run:

```bash
ANDROID_HOME=/home/jio/code/auto_titration/.tools/android-sdk \
ANDROID_SDK_ROOT=/home/jio/code/auto_titration/.tools/android-sdk \
JAVA_HOME=/home/jio/code/auto_titration/.tools/jdk/temurin-17 \
GRADLE_USER_HOME=/home/jio/code/auto_titration/.gradle-cache \
/home/jio/code/auto_titration/.tools/gradle/gradle-8.10.2/bin/gradle \
  -p mobile/android assembleDebug
```

Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 3: Report known runtime limits**

Final report must include:

```text
- APK now shows the packaged existing web dashboard UI via Android WebView.
- Android native owns CameraX permission and Mini2 USB permission/probe through AndroidBridge.
- Mini2 calibrated Celsius remains intentionally unavailable until a validated Android converter/backend passes the existing no-fake-Celsius gate.
- The rebuilt debug APK was copied to C:\Users\Jio\Downloads\auto_titrator-debug.apk.
```

---

## Self-review

- Spec coverage: Covers existing web UI reuse, Android permissions/native bridge, Mini2 permission crash hardening, vendor-tolerant Mini2 detection, docs, APK rebuild, and Windows Downloads copy.
- Placeholder scan: No placeholder tasks remain; every code-producing step includes exact file paths and concrete code blocks or commands.
- Type consistency: `AndroidBridge`, `Mini2UsbProbe`, `PhoneRunSession`, and `ThermalStatus` names match current Kotlin package structure. Test assertions align with code snippets in later tasks.
- Risk boundary: This plan does not claim calibrated Mini2 Celsius on Android. It only makes detection/permission safe and displays honest `blocked`/`raw_unverified` evidence in the reused UI.
