package kr.auto.titration.mobile

import android.Manifest
import android.annotation.SuppressLint
import android.content.ContentValues
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.SystemClock
import android.provider.MediaStore
import android.util.Base64
import android.webkit.PermissionRequest
import android.webkit.WebResourceRequest
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kr.auto.titration.mobile.data.StandaloneFeatureFrame
import kr.auto.titration.mobile.data.ExperimentConfig
import kr.auto.titration.mobile.export.SessionExporter
import kr.auto.titration.mobile.pump.BluetoothPumpTransport
import kr.auto.titration.mobile.pump.ManualPumpController
import kr.auto.titration.mobile.pump.PumpCommand
import kr.auto.titration.mobile.pump.PumpSnapshot
import kr.auto.titration.mobile.roi.RoiAutoCandidateResponse
import kr.auto.titration.mobile.session.PhoneRunSession
import kr.auto.titration.mobile.session.SessionState
import kr.auto.titration.mobile.thermal.HikmicroJnaMini2Stream
import kr.auto.titration.mobile.thermal.Mini2OfficialRuntimeMode
import kr.auto.titration.mobile.thermal.ThermalRawFrameSummary
import kr.auto.titration.mobile.thermal.ThermalStatus
import kr.auto.titration.mobile.thermal.ThermalRoiDetector
import kr.auto.titration.mobile.vision.AndroidAutoRoiWorker
import kr.auto.titration.mobile.vision.AndroidRoiSelectionState
import kr.auto.titration.mobile.vision.MaskOps
import kr.auto.titration.mobile.vision.Roi
import kr.auto.titration.mobile.vision.RoiDetectionResult
import kr.auto.titration.mobile.vision.RoiMask
import kr.auto.titration.mobile.vision.VisibleFeatureExtractor
import kr.auto.titration.mobile.vision.VisibleFeatures
import kr.auto.titration.mobile.vision.YoloInputFrame
import kr.auto.titration.mobile.vision.YoloSegmentationDetector
import kr.auto.titration.mobile.vision.roiMaskFromBool
import org.json.JSONObject

private const val MINI2_AUTO_RETRY_INTERVAL_MS = 2_000L
private const val VISIBLE_PREVIEW_MIN_INTERVAL_MS = 40L
private const val VISIBLE_STATUS_MIN_INTERVAL_MS = 500L
private const val VISIBLE_PREVIEW_MAX_WIDTH = 320
private const val HIKMICRO_THERMAL_PREVIEW_WIDTH = 256
private const val HIKMICRO_THERMAL_PREVIEW_HEIGHT = 192
private const val TRUSTED_WEBVIEW_ASSET_PREFIX = "file:///android_asset/"

private data class VisiblePreviewPayload(
    val dataUrl: String,
    val width: Int,
    val height: Int,
)

/**
 * Phone-standalone Android runtime backed by the existing website UI.
 *
 * The visible UI is the repository's `website/index.html` loaded in a WebView.
 * Native Android owns permissions, CameraX ImageAnalysis, USB host probing, Mini2
 * native-library status, CSV/session state, and exposes that evidence through
 * the `AutoTitrationAndroid` JavaScript bridge.
 */
class MainActivity : ComponentActivity() {
    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private val frameId = AtomicLong(0)
    private val runSession = PhoneRunSession()
    private lateinit var webView: WebView
    private lateinit var officialPreviewHost: OfficialPreviewHost
    private lateinit var mini2Probe: Mini2UsbProbe
    private lateinit var pumpController: ManualPumpController
    private var lockedVisibleRoi: Roi? = null
    private var previousVisibleFeatures: VisibleFeatures? = null
    private var cameraPermissionGranted = false
    private var statusMessage = "Android WebView 초기화 중"
    @Volatile
    private var latestVisiblePreviewDataUrl = ""
    @Volatile
    private var latestVisiblePreviewFrameId = 0L
    @Volatile
    private var latestVisibleFrameWidth = 0
    @Volatile
    private var latestVisibleFrameHeight = 0
    @Volatile
    private var latestVisiblePreviewWidth = 0
    @Volatile
    private var latestVisiblePreviewHeight = 0
    @Volatile
    private var latestVisiblePreviewImageWidth = 0
    @Volatile
    private var latestVisiblePreviewImageHeight = 0
    @Volatile
    private var latestVisiblePreviewRotationDegrees = 0
    @Volatile
    private var latestVisibleYoloInput: YoloInputFrame? = null
    private val androidRoiState = AndroidRoiSelectionState()
    private lateinit var yoloDetector: YoloSegmentationDetector
    private lateinit var autoRoiWorker: AndroidAutoRoiWorker
    @Volatile
    private var latestVisibleRoiMask: RoiMask? = null
    @Volatile
    private var latestThermalRoiMask: RoiMask? = null
    @Volatile
    private var latestAutoRoiResultStatus: String = "not_started"
    @Volatile
    private var latestAutoRoiResultReason: String = "not_started"
    @Volatile
    private var latestAutoRoiDroppedPending: Int = 0
    @Volatile
    private var latestAutoRoiDetectionResult: RoiDetectionResult? = null
    private var lastMini2AutoRetryAtMs = 0L
    private var lastVisiblePreviewPushElapsedMs = 0L
    private var lastVisibleStatusPushElapsedMs = 0L
    private val visibleRoiRevision = AtomicLong(0)
    private var lastExplicitMini2Probe: JSONObject? = null
    @Volatile
    private var bluetoothPermissionGranted = Build.VERSION.SDK_INT < Build.VERSION_CODES.S

    private val cameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        cameraPermissionGranted = granted
        if (granted) {
            statusMessage = "CameraX ImageAnalysis 실행 중 · Android WebView"
            startCameraXImageAnalysis()
        } else {
            statusMessage = "카메라 권한이 필요합니다. Android 앱 권한에서 카메라를 허용하세요."
        }
        notifyWebStatus()
    }

    private val bluetoothPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        bluetoothPermissionGranted = granted
        statusMessage = if (granted) {
            "Bluetooth 펌프 권한 허용됨 · paired SPP 장치 사용 가능"
        } else {
            "Bluetooth 펌프 권한이 필요합니다. Android 권한에서 Nearby devices/Bluetooth를 허용하세요."
        }
        notifyWebStatus()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AndroidCrashLogStore.install(applicationContext)
        mini2Probe = Mini2UsbProbe(this)
        pumpController = ManualPumpController(BluetoothPumpTransport(this))
        yoloDetector = YoloSegmentationDetector(this)
        autoRoiWorker = AndroidAutoRoiWorker(yoloDetector, androidRoiState)
        mini2Probe.startMonitoring()
        runSession.startSetup()
        runSession.updatePumpSnapshot(pumpController.snapshot())
        webView = buildWebView()
        officialPreviewHost = OfficialPreviewHost(this)
        officialPreviewHost.attachUserInterface(webView)
        setContentView(officialPreviewHost.rootView)
        cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        requestBluetoothPermissionIfNeeded()
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraExecutor.shutdown()
        if (::mini2Probe.isInitialized) {
            mini2Probe.stopMonitoring()
        }
        if (::officialPreviewHost.isInitialized) {
            officialPreviewHost.destroy()
        }
        if (::webView.isInitialized) {
            webView.removeJavascriptInterface("AutoTitrationAndroid")
            webView.destroy()
        }
    }

    private fun requestBluetoothPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            bluetoothPermissionGranted = true
            return
        }
        val granted = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.BLUETOOTH_CONNECT,
        ) == PackageManager.PERMISSION_GRANTED
        bluetoothPermissionGranted = granted
        if (!granted) {
            bluetoothPermissionLauncher.launch(Manifest.permission.BLUETOOTH_CONNECT)
        }
    }

    @Suppress("DEPRECATION")
    @SuppressLint("SetJavaScriptEnabled")
    private fun buildWebView(): WebView {
        val debugWebView = (applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
        WebView.setWebContentsDebuggingEnabled(debugWebView)
        return WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.cacheMode = WebSettings.LOAD_NO_CACHE
            settings.allowFileAccess = true
            settings.allowContentAccess = false
            settings.allowFileAccessFromFileURLs = false
            settings.allowUniversalAccessFromFileURLs = false
            settings.mediaPlaybackRequiresUserGesture = false
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    return blockUntrustedWebViewNavigation(view, request.url, request.isForMainFrame)
                }

                @Deprecated("Deprecated in Android API")
                override fun shouldOverrideUrlLoading(view: WebView, url: String): Boolean {
                    return blockUntrustedWebViewNavigation(view, Uri.parse(url), isMainFrame = true)
                }
            }
            webChromeClient = object : WebChromeClient() {
                override fun onPermissionRequest(request: PermissionRequest) {
                    val wantsCamera = request.resources.contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE)
                    if (wantsCamera && cameraPermissionGranted) {
                        request.grant(arrayOf(PermissionRequest.RESOURCE_VIDEO_CAPTURE))
                    } else {
                        request.deny()
                    }
                }
            }
            addJavascriptInterface(AndroidBridge(this@MainActivity), "AutoTitrationAndroid")
            loadUrl("file:///android_asset/index.html")
        }
    }

    private fun blockUntrustedWebViewNavigation(view: WebView, uri: Uri?, isMainFrame: Boolean): Boolean {
        if (!isMainFrame) return false
        val url = uri?.toString().orEmpty()
        if (url.startsWith(TRUSTED_WEBVIEW_ASSET_PREFIX)) return false
        view.removeJavascriptInterface("AutoTitrationAndroid")
        statusMessage = "Blocked untrusted WebView navigation: ${uri?.scheme ?: "unknown"}"
        return true
    }

    private fun startCameraXImageAnalysis() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            val cameraProvider = cameraProviderFuture.get()
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
                analysis,
            )
            statusMessage = "CameraX ImageAnalysis 실행 중 · phone-local Android WebView"
            notifyWebStatus()
        }, ContextCompat.getMainExecutor(this))
    }

    private fun analyzeVisibleFrame(imageProxy: ImageProxy) {
        try {
            val id = frameId.incrementAndGet()
            val rotationDegrees = normalizedRotationDegrees(imageProxy.imageInfo.rotationDegrees)
            latestVisibleFrameWidth = imageProxy.width
            latestVisibleFrameHeight = imageProxy.height
            latestVisiblePreviewRotationDegrees = rotationDegrees
            latestVisiblePreviewWidth = rotatedFrameWidth(imageProxy.width, imageProxy.height, rotationDegrees)
            latestVisiblePreviewHeight = rotatedFrameHeight(imageProxy.width, imageProxy.height, rotationDegrees)
            if (lockedVisibleRoi == null) {
                lockedVisibleRoi = defaultVisibleSensorRoi(imageProxy.width, imageProxy.height)
            }
            val visible = VisibleFeatureExtractor.extract(
                image = imageProxy,
                roi = lockedVisibleRoi ?: VisibleFeatureExtractor.defaultCenterRoi(imageProxy.width, imageProxy.height),
                previous = previousVisibleFeatures,
            )
            val nowMs = SystemClock.elapsedRealtime()
            if (shouldPublishVisiblePreview(id, nowMs)) {
                val yoloInput = try {
                    buildVisibleYoloInputFrame(imageProxy, rotationDegrees = rotationDegrees, frameId = id)
                } catch (_: RuntimeException) {
                    null
                }
                if (yoloInput != null) {
                    latestVisibleYoloInput = yoloInput
                }
                val preview = try {
                    buildVisiblePreviewDataUrl(imageProxy, rotationDegrees = rotationDegrees)
                } catch (_: RuntimeException) {
                    null
                }
                if (preview != null && preview.dataUrl.isNotBlank()) {
                    latestVisiblePreviewDataUrl = preview.dataUrl
                    latestVisiblePreviewImageWidth = preview.width
                    latestVisiblePreviewImageHeight = preview.height
                    latestVisiblePreviewFrameId = id
                    lastVisiblePreviewPushElapsedMs = nowMs
                    notifyWebPreview()
                }
            }
            previousVisibleFeatures = visible
            val frame = StandaloneFeatureFrame(
                runId = runSession.runId,
                frameId = id,
                capturedElapsedNanos = SystemClock.elapsedRealtimeNanos(),
                visible = visible,
                thermalStatus = currentThermalStatus(),
                thermalRawFrame = currentThermalRawFrame(),
                visibleMask = latestVisibleRoiMask,
                thermalMask = latestThermalRoiMask,
                autoRoiResultStatus = latestAutoRoiResultStatus,
                autoRoiResultReason = latestAutoRoiResultReason,
                autoRoiDroppedPending = latestAutoRoiDroppedPending,
                pendingAutoCandidateRequests = androidRoiState.pendingRequests(),
                pendingAutoCandidateTarget = androidRoiState.pendingTarget(),
            )
            synchronized(this) {
                if (::pumpController.isInitialized) {
                    runSession.updatePumpSnapshot(pumpController.snapshot())
                }
                runSession.recordFrame(frame)
            }
            if (shouldPublishVisibleStatus(id, nowMs)) {
                lastVisibleStatusPushElapsedMs = nowMs
                notifyWebStatus()
            }
        } finally {
            imageProxy.close()
        }
    }

    private fun currentThermalStatus(): ThermalStatus {
        return currentThermalStatus(requestPermissionIfMissing = false)
    }

    private fun currentThermalStatus(requestPermissionIfMissing: Boolean): ThermalStatus {
        return try {
            mini2Probe.safeProbeStatus(requestPermissionIfMissing = requestPermissionIfMissing)
        } catch (error: Throwable) {
            ThermalStatus.blocked("status_build_failed thermal probe exception ${error.javaClass.simpleName}: ${error.message ?: "no message"}")
        }
    }

    private fun currentThermalRawFrame(): ThermalRawFrameSummary? {
        return if (::mini2Probe.isInitialized) {
            mini2Probe.latestRawFrameSummary()
        } else {
            null
        }
    }

    private fun refreshPumpStatusFromUserAction(): String {
        if (!::pumpController.isInitialized) return ""
        val response = pumpController.sendUserCommand(PumpCommand.Status)
        currentPumpSnapshot()
        return response
    }

    private fun currentPumpSnapshot(): PumpSnapshot {
        val snapshot = if (::pumpController.isInitialized) {
            pumpController.snapshot()
        } else {
            PumpSnapshot(
                mode = "android_manual_bluetooth",
                state = "uninitialized",
                runRateMlPerS = 0.0,
                warning = "pump controller not initialized",
            )
        }
        runSession.updatePumpSnapshot(snapshot)
        return snapshot
    }

    private fun shouldAutoRetryMini2(): Boolean {
        val now = SystemClock.elapsedRealtime()
        if (now - lastMini2AutoRetryAtMs < MINI2_AUTO_RETRY_INTERVAL_MS) return false
        lastMini2AutoRetryAtMs = now
        return true
    }

    private fun buildVisiblePreviewDataUrl(
        imageProxy: ImageProxy,
        maxWidth: Int = VISIBLE_PREVIEW_MAX_WIDTH,
        rotationDegrees: Int = normalizedRotationDegrees(imageProxy.imageInfo.rotationDegrees),
    ): VisiblePreviewPayload {
        val sourceWidth = imageProxy.width
        val sourceHeight = imageProxy.height
        if (sourceWidth <= 0 || sourceHeight <= 0 || imageProxy.planes.size < 3) {
            return VisiblePreviewPayload("", 0, 0)
        }

        val normalizedRotation = normalizedRotationDegrees(rotationDegrees)
        val rotatedSourceWidth = rotatedFrameWidth(sourceWidth, sourceHeight, normalizedRotation)
        val rotatedSourceHeight = rotatedFrameHeight(sourceWidth, sourceHeight, normalizedRotation)
        val yPlane = imageProxy.planes[0]
        val uPlane = imageProxy.planes[1]
        val vPlane = imageProxy.planes[2]
        val targetWidth = min(maxWidth, rotatedSourceWidth).coerceAtLeast(1)
        val targetHeight = max(1, (rotatedSourceHeight.toDouble() * targetWidth / rotatedSourceWidth).toInt())
        val pixels = IntArray(targetWidth * targetHeight)

        for (targetY in 0 until targetHeight) {
            val rotatedY = ((targetY.toLong() * rotatedSourceHeight) / targetHeight).toInt()
                .coerceIn(0, rotatedSourceHeight - 1)
            for (targetX in 0 until targetWidth) {
                val rotatedX = ((targetX.toLong() * rotatedSourceWidth) / targetWidth).toInt()
                    .coerceIn(0, rotatedSourceWidth - 1)
                val (sourceX, sourceY) = sourcePointForRotatedPreview(
                    rotatedX = rotatedX,
                    rotatedY = rotatedY,
                    sourceWidth = sourceWidth,
                    sourceHeight = sourceHeight,
                    rotationDegrees = normalizedRotation,
                )
                val yValue = planeValue(yPlane, sourceX, sourceY, defaultValue = 0)
                val uValue = planeValue(uPlane, sourceX / 2, sourceY / 2, defaultValue = 128)
                val vValue = planeValue(vPlane, sourceX / 2, sourceY / 2, defaultValue = 128)
                pixels[targetY * targetWidth + targetX] = previewYuvToArgb(yValue, uValue, vValue)
            }
        }

        val bitmap = Bitmap.createBitmap(pixels, targetWidth, targetHeight, Bitmap.Config.ARGB_8888)
        val dataUrl = ByteArrayOutputStream().use { output ->
            bitmap.compress(Bitmap.CompressFormat.JPEG, 62, output)
            bitmap.recycle()
            "data:image/jpeg;base64,${Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP)}"
        }
        return VisiblePreviewPayload(dataUrl = dataUrl, width = targetWidth, height = targetHeight)
    }

    private fun buildVisibleYoloInputFrame(
        imageProxy: ImageProxy,
        rotationDegrees: Int = normalizedRotationDegrees(imageProxy.imageInfo.rotationDegrees),
        frameId: Long,
    ): YoloInputFrame? {
        val sourceWidth = imageProxy.width
        val sourceHeight = imageProxy.height
        if (sourceWidth <= 0 || sourceHeight <= 0 || imageProxy.planes.size < 3) return null

        val normalizedRotation = normalizedRotationDegrees(rotationDegrees)
        val rotatedSourceWidth = rotatedFrameWidth(sourceWidth, sourceHeight, normalizedRotation)
        val rotatedSourceHeight = rotatedFrameHeight(sourceWidth, sourceHeight, normalizedRotation)
        val yPlane = imageProxy.planes[0]
        val uPlane = imageProxy.planes[1]
        val vPlane = imageProxy.planes[2]
        val inputSize = YoloInputFrame.INPUT_SIZE
        val rgb = FloatArray(inputSize * inputSize * 3)
        var offset = 0
        for (targetY in 0 until inputSize) {
            val rotatedY = ((targetY.toLong() * rotatedSourceHeight) / inputSize).toInt()
                .coerceIn(0, rotatedSourceHeight - 1)
            for (targetX in 0 until inputSize) {
                val rotatedX = ((targetX.toLong() * rotatedSourceWidth) / inputSize).toInt()
                    .coerceIn(0, rotatedSourceWidth - 1)
                val (sourceX, sourceY) = sourcePointForRotatedPreview(
                    rotatedX = rotatedX,
                    rotatedY = rotatedY,
                    sourceWidth = sourceWidth,
                    sourceHeight = sourceHeight,
                    rotationDegrees = normalizedRotation,
                )
                val yValue = planeValue(yPlane, sourceX, sourceY, defaultValue = 0)
                val uValue = planeValue(uPlane, sourceX / 2, sourceY / 2, defaultValue = 128)
                val vValue = planeValue(vPlane, sourceX / 2, sourceY / 2, defaultValue = 128)
                val argb = previewYuvToArgb(yValue, uValue, vValue)
                rgb[offset++] = ((argb shr 16) and 0xff) / 255f
                rgb[offset++] = ((argb shr 8) and 0xff) / 255f
                rgb[offset++] = (argb and 0xff) / 255f
            }
        }
        return YoloInputFrame(
            frameId = frameId,
            frameWidth = rotatedSourceWidth,
            frameHeight = rotatedSourceHeight,
            sensorWidth = sourceWidth,
            sensorHeight = sourceHeight,
            rotationDegrees = normalizedRotation,
            rgbFloat32 = rgb,
        )
    }

    @Synchronized
    fun buildStatusJson(): JSONObject {
        val mini2AutoRetry = shouldAutoRetryMini2()
        val thermalStatus = currentThermalStatus(requestPermissionIfMissing = mini2AutoRetry)
        val crashReport = AndroidCrashLogStore.readLastCrash(this)
        val visible = runSession.lastFrame?.visible
        val roi = visible?.roi ?: lockedVisibleRoi
        val effectiveRoi = roi ?: defaultVisibleSensorRoi()
        val visibleRoiEvidence = visibleRoiEvidence(roi)
        val visibleRoiReady = visibleRoiEvidence != "default_unverified"
        val thermalRoiReady = latestThermalRoiMask != null
        val androidRoiReadyForRecording = androidRoiReadyForRecording(effectiveRoi)
        val previewImageWidth = (latestVisiblePreviewImageWidth.takeIf { it > 0 }
            ?: latestVisiblePreviewWidth.takeIf { it > 0 }
            ?: latestVisibleFrameWidth)
            .coerceAtLeast(1)
        val previewImageHeight = (latestVisiblePreviewImageHeight.takeIf { it > 0 }
            ?: latestVisiblePreviewHeight.takeIf { it > 0 }
            ?: latestVisibleFrameHeight)
            .coerceAtLeast(1)
        val previewRoi = effectiveRoi.let {
            sensorRoiToPreviewRoi(
                roi = it,
                sensorWidth = latestVisibleFrameWidth,
                sensorHeight = latestVisibleFrameHeight,
                rotationDegrees = latestVisiblePreviewRotationDegrees,
                previewWidth = previewImageWidth,
                previewHeight = previewImageHeight,
            )
        }
        val currentVisibleRoiRevision = visibleRoiRevision.get()
        val mini2 = mini2Probe.probe(
            requestPermissionIfMissing = mini2AutoRetry,
            attemptRawStream = false,
            runtimeMode = Mini2OfficialRuntimeMode.OFFICIAL_PRIMARY,
        ).withLastExplicitMini2Probe()
        val rawStream = mini2.optJSONObject("raw_stream")
        val thermalPreviewWidth = rawStream?.optInt("frame_width")?.takeIf { it > 0 } ?: HIKMICRO_THERMAL_PREVIEW_WIDTH
        val thermalPreviewHeight = rawStream?.optInt("frame_height")?.takeIf { it > 0 } ?: HIKMICRO_THERMAL_PREVIEW_HEIGHT
        val thermalRoi = defaultThermalPreviewRoi(thermalPreviewWidth, thermalPreviewHeight)
        val pumpSnapshot = currentPumpSnapshot()
        val latestRow = runSession.rows.lastOrNull()
        val pumpJson = JSONObject()
            .put("pump_mode", pumpSnapshot.mode)
            .put("pump_state", pumpSnapshot.state)
            .put("pump_connected", pumpSnapshot.connected)
            .put("pump_commanded_step_count", pumpSnapshot.commandedStepCount)
            .put("pump_confirmed_step_count", pumpSnapshot.confirmedStepCount ?: JSONObject.NULL)
            .put("pump_step_count", pumpSnapshot.confirmedStepCount ?: JSONObject.NULL)
            .put("pump_firmware_volume_ml", pumpSnapshot.firmwareVolumeMl ?: JSONObject.NULL)
            .put("pump_last_status", pumpSnapshot.lastStatusLine)
            .put("pump_last_response", pumpSnapshot.lastCommandResponse)
            .put("pump_bluetooth_device_name", pumpSnapshot.bluetoothDeviceName)
            .put("pump_warning", pumpSnapshot.warning)
            .put("bluetooth_permission_granted", bluetoothPermissionGranted)
        val roiJson = JSONObject()
            .put("roi_state", runSession.state.name.lowercase(Locale.US))
            .put("roi_locked", runSession.state != SessionState.SETUP && runSession.state != SessionState.IDLE)
            .put("roi_complete", visibleRoiReady)
            .put("roi_recordable", androidRoiReadyForRecording)
            .put("roi_editable", runSession.state != SessionState.RECORDING)
            .put("visible_roi_ready", visibleRoiReady)
            .put("thermal_roi_ready", thermalRoiReady)
            .put("visible_roi_evidence", visibleRoiEvidence)
            .put("thermal_roi_evidence", if (thermalRoiReady) "thermal_raw_mask" else "thermal_default_unverified")
            .put("roi_error", if (visibleRoiReady) JSONObject.NULL else "default_unverified_visible_roi")
            .put("visible_roi", previewRoi.toCsvString())
            .put("visible_roi_revision", currentVisibleRoiRevision)
            .put("thermal_roi", thermalRoi.toCsvString())
            .put("visible_roi_shape", latestVisibleRoiMask?.shape ?: if (visibleRoiReady) previewRoi.shape else "default_unverified")
            .put("thermal_roi_shape", latestThermalRoiMask?.shape ?: "default_unverified")
            .put("visible_mask_source", latestVisibleRoiMask?.source ?: "")
            .put("thermal_mask_source", latestThermalRoiMask?.source ?: "")
            .put("visible_mask_area_px", latestVisibleRoiMask?.areaPx ?: JSONObject.NULL)
            .put("thermal_mask_area_px", latestThermalRoiMask?.areaPx ?: JSONObject.NULL)
            .put("mask_bbox", (latestVisibleRoiMask ?: latestThermalRoiMask)?.bboxCsvString().orEmpty())
            .put("mask_confidence", (latestVisibleRoiMask ?: latestThermalRoiMask)?.confidence ?: JSONObject.NULL)
            .put("mask_component_count", (latestVisibleRoiMask ?: latestThermalRoiMask)?.componentCount ?: JSONObject.NULL)
            .put("mask_stability", (latestVisibleRoiMask ?: latestThermalRoiMask)?.stability.orEmpty())
            .put("pending_auto_candidate_requests", androidRoiState.pendingRequests())
            .put("pending_auto_candidate_target", androidRoiState.pendingTarget())
            .put("auto_roi_worker_enabled", true)
            .put("auto_roi_result_status", latestAutoRoiResultStatus)
            .put("auto_roi_result_reason", latestAutoRoiResultReason)
            .put("auto_roi_dropped_pending", latestAutoRoiDroppedPending)
            .put("roi_session_id", runSession.runId.take(8))

        val csvJson = JSONObject()
            .put("recording", runSession.state == SessionState.RECORDING)
            .put("state", runSession.state.name.lowercase(Locale.US))
            .put("row_count", runSession.recordedRowCount)
            .put("path", "phone-local WebView session")
            .put("titration_type", runSession.config.titrationType)
            .put("sample_name", runSession.config.sampleName)
            .put("sample_concentration_M", runSession.config.sampleConcentrationM)
            .put("sample_volume_ml", runSession.config.sampleVolumeMl)
            .put("sample_valence", runSession.config.sampleValence)
            .put("titrant_name", runSession.config.titrantName)
            .put("titrant_concentration_M", runSession.config.titrantConcentrationM)
            .put("titrant_valence", runSession.config.titrantValence)
            .put("equivalence_formula", runSession.config.equivalenceFormula)
            .put("calculated_theoretical_equivalence_volume_ml", runSession.config.calculatedTheoreticalEquivalenceVolumeMl)
            .put("sample_concentration_from_theoretical_equivalence_M", runSession.config.sampleConcentrationFromTheoreticalEquivalenceM)
            .put("theoretical_equivalence_volume_ml", runSession.config.theoreticalEquivalenceVolumeMl)
            .put("pump_rate_ml_per_s", runSession.config.pumpRunRateMlPerS)
            .put("injected_volume_ml", latestRow?.injectedVolumeMl)
            .put("distance_to_equivalence_ml", latestRow?.distanceToEquivalenceMl)
            .put("sample_concentration_from_injected_M", latestRow?.sampleConcentrationFromInjectedM ?: JSONObject.NULL)
            .put("sample_concentration_error_percent", latestRow?.sampleConcentrationErrorPercent ?: JSONObject.NULL)
            .put("pump_step_count", pumpSnapshot.confirmedStepCount ?: JSONObject.NULL)
            .put("pump_firmware_volume_ml", pumpSnapshot.firmwareVolumeMl ?: JSONObject.NULL)
            .put("pump_last_status", pumpSnapshot.lastStatusLine)

        val live = JSONObject()
            .put("frame_id", if (runSession.frameCount > 0) runSession.frameCount else JSONObject.NULL)
            .put("csv_row_count", runSession.recordedRowCount)
            .put("csv_recording", runSession.state == SessionState.RECORDING)
            .put("csv_state", runSession.state.name.lowercase(Locale.US))
            .put("sync_quality", "phone_local_android_webview")
            .put("status_label", thermalStatus.state.name.lowercase(Locale.US))
            .put("thermal_status", thermalStatus.state.name.lowercase(Locale.US))
            .put("thermal_calibrated", thermalStatus.calibrated)
            .put("thermal_conversion_model", thermalStatus.conversionModel)
            .put("mini2_reason", thermalStatus.reason)
            .put("mini2_official_module_type", mini2.optString("mini2_official_module_type"))
            .put("mini2_selected_backend", mini2.optString("mini2_selected_backend"))
            .put("mini2_route_reason", mini2.optString("mini2_route_reason"))
            .put("roi_state", roiJson.optString("roi_state"))
            .put("roi_locked", roiJson.optBoolean("roi_locked"))
            .put("roi_complete", roiJson.optBoolean("roi_complete"))
            .put("roi_recordable", roiJson.optBoolean("roi_recordable"))
            .put("roi_editable", roiJson.optBoolean("roi_editable"))
            .put("visible_roi_ready", roiJson.optBoolean("visible_roi_ready"))
            .put("thermal_roi_ready", roiJson.optBoolean("thermal_roi_ready"))
            .put("visible_roi", roiJson.optString("visible_roi"))
            .put("visible_roi_revision", currentVisibleRoiRevision)
            .put("thermal_roi", roiJson.optString("thermal_roi"))
            .put("visible_roi_shape", roiJson.optString("visible_roi_shape"))
            .put("thermal_roi_shape", roiJson.optString("thermal_roi_shape"))
            .put("visible_mask_stability", latestVisibleRoiMask?.stability ?: "")
            .put("thermal_mask_stability", latestThermalRoiMask?.stability ?: "")
            .put("visible_roi_detector", "android_litert_yolo_segmentation")
            .put("visible_mask_source", latestVisibleRoiMask?.source ?: "")
            .put("thermal_mask_source", latestThermalRoiMask?.source ?: "")
            .put("visible_mask_area_px", latestVisibleRoiMask?.areaPx ?: JSONObject.NULL)
            .put("thermal_mask_area_px", latestThermalRoiMask?.areaPx ?: JSONObject.NULL)
            .put("mask_bbox", (latestVisibleRoiMask ?: latestThermalRoiMask)?.bboxCsvString().orEmpty())
            .put("mask_confidence", (latestVisibleRoiMask ?: latestThermalRoiMask)?.confidence ?: JSONObject.NULL)
            .put("mask_component_count", (latestVisibleRoiMask ?: latestThermalRoiMask)?.componentCount ?: JSONObject.NULL)
            .put("mask_stability", (latestVisibleRoiMask ?: latestThermalRoiMask)?.stability.orEmpty())
            .put("pending_auto_candidate_requests", androidRoiState.pendingRequests())
            .put("pending_auto_candidate_target", androidRoiState.pendingTarget())
            .put("auto_roi_worker_enabled", true)
            .put("auto_roi_result_status", latestAutoRoiResultStatus)
            .put("auto_roi_result_reason", latestAutoRoiResultReason)
            .put("auto_roi_dropped_pending", latestAutoRoiDroppedPending)
            .put("roi_source", latestAutoRoiResultReason)
            .put("pump_mode", pumpSnapshot.mode)
            .put("pump_state", pumpSnapshot.state)
            .put("pump_connected", pumpSnapshot.connected)
            .put("pump_step_count", pumpSnapshot.confirmedStepCount ?: JSONObject.NULL)
            .put("pump_confirmed_step_count", pumpSnapshot.confirmedStepCount ?: JSONObject.NULL)
            .put("pump_firmware_volume_ml", pumpSnapshot.firmwareVolumeMl ?: JSONObject.NULL)
            .put("pump_last_status", pumpSnapshot.lastStatusLine)
            .put("pump_bluetooth_device_name", pumpSnapshot.bluetoothDeviceName)
            .put("visible_frame_width", previewImageWidth)
            .put("visible_frame_height", previewImageHeight)
            .put("visible_sensor_frame_width", latestVisibleFrameWidth)
            .put("visible_sensor_frame_height", latestVisibleFrameHeight)
            .put("visible_display_frame_width", latestVisiblePreviewWidth)
            .put("visible_display_frame_height", latestVisiblePreviewHeight)
            .put("visible_preview_width", previewImageWidth)
            .put("visible_preview_height", previewImageHeight)
            .put("visible_preview_frame_id", latestVisiblePreviewFrameId)
            .put("visible_preview_rotation_degrees", latestVisiblePreviewRotationDegrees)
            .put("last_crash_present", crashReport.optBoolean("present"))
            .put("updated_epoch_s", System.currentTimeMillis() / 1000.0)
            .put("stream_updated_epoch_s", System.currentTimeMillis() / 1000.0)

        rawStream?.let { stream ->
            live.put("raw_stream_status", stream.optString("raw_stream_status"))
            live.put("raw_frame_status", stream.optString("raw_frame_status"))
            live.put("thermal_preview_data_url", stream.optString("thermal_preview_data_url"))
            live.put("thermal_frame_counter", stream.optLong("frame_counter"))
            live.put("thermal_frame_width", stream.optInt("frame_width"))
            live.put("thermal_frame_height", stream.optInt("frame_height"))
            live.put("thermal_transport_frame_width", stream.optInt("transport_frame_width"))
            live.put("thermal_transport_frame_height", stream.optInt("transport_frame_height"))
            live.put("thermal_preview_rotation_degrees", stream.optInt("preview_rotation_degrees"))
            if (!stream.isNull("raw_avg")) live.put("raw_avg", stream.optDouble("raw_avg"))
            if (!stream.isNull("raw_min")) live.put("raw_min", stream.optInt("raw_min"))
            if (!stream.isNull("raw_max")) live.put("raw_max", stream.optInt("raw_max"))
            if (!stream.isNull("raw_delta")) live.put("raw_delta", stream.optInt("raw_delta"))
            live.put("native_symbol_discovery", stream.optString("native_symbol_discovery"))
            live.put("mini2_selected_backend", stream.optString("selected_backend"))
            live.put("mini2_stage_report", stream.optString("stage_report"))
            live.put("mini2_device_route", stream.optString("device_route"))
        }

        if (latestVisiblePreviewDataUrl.isNotBlank()) {
            live.put("visible_preview_data_url", latestVisiblePreviewDataUrl)
        }

        visible?.let { features ->
            live.put("visible_R_mean", features.rMean)
            live.put("visible_G_mean", features.gMean)
            live.put("visible_B_mean", features.bMean)
            live.put("visible_H_mean", features.hMean)
            live.put("visible_S_mean", features.sMean)
            live.put("visible_V_mean", features.vMean)
            live.put("visible_HSV_delta", features.hsvDelta)
            live.put("visible_color_delta", features.colorDelta)
            live.put("visible_capture_index", runSession.frameCount)
        }
        latestRow?.let { row ->
            live.put("injected_volume_ml", row.injectedVolumeMl)
            live.put("distance_to_equivalence_ml", row.distanceToEquivalenceMl)
            live.put("sample_concentration_from_injected_M", row.sampleConcentrationFromInjectedM ?: JSONObject.NULL)
            live.put("sample_concentration_error_percent", row.sampleConcentrationErrorPercent ?: JSONObject.NULL)
            live.put("pump_run_rate_ml_per_s", row.pumpRateMlPerS)
            live.put("pump_step_count", row.pumpStepCount ?: JSONObject.NULL)
            live.put("pump_firmware_volume_ml", row.pumpFirmwareVolumeMl ?: JSONObject.NULL)
        }

        return JSONObject()
            .put("ok", true)
            .put("mode", "android_webview")
            .put("message", statusMessage)
            .put("mobile", JSONObject()
                .put("enabled", true)
                .put("paired", true)
                .put("state", "streaming")
                .put("source", "Android WebView")
                .put("last_frame_id", runSession.frameCount)
                .put("sync_quality", "phone_local_android_webview"))
            .put("roi", roiJson)
            .put("csv", csvJson)
            .put("pump", pumpJson)
            .put("live", live)
            .put("last_crash_report", crashReport)
            .put("crash", crashReport)
            .put("mini2", mini2)
    }

    @Synchronized
    fun startNewRunFromBridge(): JSONObject {
        frameId.set(0)
        lockedVisibleRoi = null
        previousVisibleFeatures = null
        latestVisiblePreviewDataUrl = ""
        latestVisiblePreviewFrameId = 0L
        latestVisiblePreviewImageWidth = 0
        latestVisiblePreviewImageHeight = 0
        latestVisibleYoloInput = null
        latestVisibleRoiMask = null
        latestThermalRoiMask = null
        latestAutoRoiResultStatus = "not_started"
        latestAutoRoiResultReason = "not_started"
        latestAutoRoiDroppedPending = 0
        visibleRoiRevision.incrementAndGet()
        runSession.startSetup()
        statusMessage = "새 Android WebView 세션 생성 · run=${runSession.runId.take(8)}"
        notifyWebStatus()
        return buildStatusJson()
    }

    @Synchronized
    fun lockRoiFromBridge(): JSONObject {
        if (!androidRoiReadyForRecording(lockedVisibleRoi)) {
            statusMessage = "ROI lock blocked · verified ROI required · ROI 후보 요청 또는 화면에서 ROI를 직접 지정하세요"
            notifyWebStatus()
            return buildStatusJson()
                .put("roi_lock_blocked", true)
                .put("roi_error", statusMessage)
        }
        if (runSession.state == SessionState.SETUP || runSession.state == SessionState.STOPPED) {
            runSession.markRoiLocked()
        }
        statusMessage = "ROI locked · Android WebView bridge"
        notifyWebStatus()
        return buildStatusJson()
    }

    @Synchronized
    fun setVisibleRoiFromBridge(payloadJson: String): JSONObject {
        if (runSession.state == SessionState.RECORDING) {
            statusMessage = "녹화 중에는 Android WebView ROI를 바꿀 수 없습니다."
            return buildStatusJson()
        }
        val payload = JSONObject(payloadJson)
        val sensorFrameWidth = (runSession.lastFrame?.visible?.frameWidth ?: latestVisibleFrameWidth).coerceAtLeast(1)
        val sensorFrameHeight = (runSession.lastFrame?.visible?.frameHeight ?: latestVisibleFrameHeight).coerceAtLeast(1)
        val displayFrameWidth = (latestVisiblePreviewWidth.takeIf { it > 0 }
            ?: rotatedFrameWidth(sensorFrameWidth, sensorFrameHeight, latestVisiblePreviewRotationDegrees))
            .coerceAtLeast(1)
        val displayFrameHeight = (latestVisiblePreviewHeight.takeIf { it > 0 }
            ?: rotatedFrameHeight(sensorFrameWidth, sensorFrameHeight, latestVisiblePreviewRotationDegrees))
            .coerceAtLeast(1)
        val previewFrameWidth = (latestVisiblePreviewImageWidth.takeIf { it > 0 } ?: displayFrameWidth)
            .coerceAtLeast(1)
        val previewFrameHeight = (latestVisiblePreviewImageHeight.takeIf { it > 0 } ?: displayFrameHeight)
            .coerceAtLeast(1)
        val normalized = payload.optBoolean("normalized", true)
        val coordinateFrameWidth = if (normalized) displayFrameWidth else previewFrameWidth
        val coordinateFrameHeight = if (normalized) displayFrameHeight else previewFrameHeight
        val x = if (normalized) {
            (payload.optDouble("x", 0.0) * displayFrameWidth).roundToInt()
        } else {
            payload.optInt("x", 0)
        }
        val y = if (normalized) {
            (payload.optDouble("y", 0.0) * displayFrameHeight).roundToInt()
        } else {
            payload.optInt("y", 0)
        }
        val width = if (normalized) {
            (payload.optDouble("width", 0.2) * displayFrameWidth).roundToInt()
        } else {
            payload.optInt("width", max(1, coordinateFrameWidth / 5))
        }
        val height = if (normalized) {
            (payload.optDouble("height", 0.2) * displayFrameHeight).roundToInt()
        } else {
            payload.optInt("height", max(1, coordinateFrameHeight / 5))
        }
        val safeX = x.coerceIn(0, max(0, coordinateFrameWidth - 1))
        val safeY = y.coerceIn(0, max(0, coordinateFrameHeight - 1))
        val safeWidth = width.coerceAtLeast(1).coerceAtMost(max(1, coordinateFrameWidth - safeX))
        val safeHeight = height.coerceAtLeast(1).coerceAtMost(max(1, coordinateFrameHeight - safeY))
        val bridgeRoi = Roi(
            x = safeX,
            y = safeY,
            width = safeWidth,
            height = safeHeight,
            shape = "android_webview_rect",
        )
        val sensorRoi = if (normalized) {
            displayRoiToSensorRoi(
                roi = bridgeRoi,
                sensorWidth = sensorFrameWidth,
                sensorHeight = sensorFrameHeight,
                rotationDegrees = latestVisiblePreviewRotationDegrees,
            )
        } else {
            previewRoiToSensorRoi(
                roi = bridgeRoi,
                sensorWidth = sensorFrameWidth,
                sensorHeight = sensorFrameHeight,
                rotationDegrees = latestVisiblePreviewRotationDegrees,
                previewWidth = previewFrameWidth,
                previewHeight = previewFrameHeight,
            )
        }
        lockedVisibleRoi = sensorRoi.copy(shape = "android_webview_rect")
        latestVisibleRoiMask = null
        val revision = visibleRoiRevision.incrementAndGet()
        statusMessage = "Android WebView ROI updated · rev=$revision · ${lockedVisibleRoi?.toCsvString()}"
        notifyWebStatus()
        return buildStatusJson()
    }

    private val AUTO_ROI_RESPONSE_KEYS_FOR_WINDOWS_PARITY = arrayOf("ok", "target", "applied_now", "reason", "confidence", "roi")

    @Synchronized
    fun requestAutoRoiCandidateFromBridge(targetPayload: String): JSONObject {
        val responseShapeForStaticParityGate = "ok,target,applied_now,reason,confidence,roi"
        val target = parseAutoRoiTarget(targetPayload)
        if (runSession.state == SessionState.RECORDING) {
            latestAutoRoiResultStatus = "rejected"
            latestAutoRoiResultReason = "roi_locked_or_recording"
            val rejected = RoiDetectionResult(
                ok = false,
                target = target,
                appliedNow = false,
                reason = latestAutoRoiResultReason,
                pendingRequests = androidRoiState.pendingRequests(),
                pendingTarget = androidRoiState.pendingTarget(),
                status = latestAutoRoiResultStatus,
            )
            statusMessage = "ROI 후보 요청 거부 · ${latestAutoRoiResultReason}"
            notifyWebStatus()
            latestAutoRoiDetectionResult = rejected
            val status = buildStatusJson()
            return RoiAutoCandidateResponse.fromDetection(rejected).toJson()
                .put("live", status.optJSONObject("live"))
        }

        val visibleInput = latestVisibleYoloInput
        val visibleResult = if (target == "visible" || target == "both") {
            val workerResult = autoRoiWorker.requestVisibleCandidate(
                target,
                visibleInput?.frameId ?: latestVisiblePreviewFrameId,
                visibleInput,
            ).also { latestAutoRoiDroppedPending = it.droppedPending }
            val detection = workerResult.detection
            val sensorMask = detection.visibleMask?.let { mask ->
                visibleInput?.let { displayYoloMaskToSensorMask(mask, it) } ?: mask
            }
            if (sensorMask != null) detection.copy(visibleMask = sensorMask) else detection
        } else null

        val thermalResult = if (target == "thermal" || target == "both") {
            val raw = currentThermalRawFrame()
            ThermalRoiDetector.detect(raw?.rawValues, raw?.frameWidth ?: 0, raw?.frameHeight ?: 0)
        } else null

        visibleResult?.visibleMask?.let { mask ->
            latestVisibleRoiMask = mask
            lockedVisibleRoi = mask.bbox.copy(shape = "mask")
            visibleRoiRevision.incrementAndGet()
        }
        thermalResult?.thermalMask?.let { mask -> latestThermalRoiMask = mask }

        val applied = listOfNotNull(visibleResult, thermalResult).any { it.ok }
        val reason = when {
            visibleResult?.ok == true -> visibleResult.reason
            thermalResult?.ok == true -> thermalResult.reason
            visibleResult != null && thermalResult != null -> "${visibleResult.reason};${thermalResult.reason}"
            visibleResult != null -> visibleResult.reason
            thermalResult != null -> thermalResult.reason
            else -> "auto_roi_target_unavailable"
        }
        latestAutoRoiResultStatus = if (applied) "applied" else "failed"
        latestAutoRoiResultReason = reason
        val confidence = listOfNotNull(visibleResult?.confidence, thermalResult?.confidence).maxOrNull()
        val merged = RoiDetectionResult(
            ok = applied,
            target = target,
            appliedNow = applied,
            reason = reason,
            confidence = confidence,
            visibleMask = visibleResult?.visibleMask,
            thermalMask = thermalResult?.thermalMask,
            pendingRequests = androidRoiState.pendingRequests(),
            pendingTarget = androidRoiState.pendingTarget(),
            status = latestAutoRoiResultStatus,
        )
        latestAutoRoiDetectionResult = merged
        statusMessage = if (applied) {
            "ROI 후보 적용 · $reason"
        } else {
            "ROI 후보 없음 · $reason"
        }
        notifyWebStatus()
        val status = buildStatusJson()
        return RoiAutoCandidateResponse.fromDetection(merged).toJson()
            .put("live", status.optJSONObject("live"))
            .put("message", statusMessage)
    }

    @Synchronized
    fun autoSetRoiFromBridge(): JSONObject {
        return requestAutoRoiCandidateFromBridge("{\"target\":\"both\"}")
    }

    private fun displayYoloMaskToSensorMask(mask: RoiMask, inputFrame: YoloInputFrame): RoiMask {
        if (mask.frameWidth == inputFrame.sensorWidth &&
            mask.frameHeight == inputFrame.sensorHeight &&
            inputFrame.rotationDegrees == 0) {
            return mask
        }
        val sensorMask = BooleanArray(inputFrame.sensorWidth * inputFrame.sensorHeight)
        for (y in 0 until mask.frameHeight) {
            val row = y * mask.frameWidth
            for (x in 0 until mask.frameWidth) {
                if (!mask.mask[row + x]) continue
                val (sourceX, sourceY) = sourcePointForRotatedPreview(
                    rotatedX = x,
                    rotatedY = y,
                    sourceWidth = inputFrame.sensorWidth,
                    sourceHeight = inputFrame.sensorHeight,
                    rotationDegrees = inputFrame.rotationDegrees,
                )
                sensorMask[sourceY * inputFrame.sensorWidth + sourceX] = true
            }
        }
        val converted = roiMaskFromBool(
            sensorMask,
            inputFrame.sensorWidth,
            inputFrame.sensorHeight,
            mask.confidence,
            mask.source,
            mask.componentCount,
            mask.stability,
        )
        return MaskOps.keepLargestComponent(converted, minAreaPx = 4) ?: converted
    }

    @Synchronized
    fun rotateThermalPreviewFromBridge(): JSONObject {
        val rotation = HikmicroJnaMini2Stream.rotatePreviewClockwise()
        statusMessage = "Mini2 화면 회전 · ${rotation}도 · 다음 프레임부터 적용"
        notifyWebStatus()
        return buildStatusJson()
            .put("thermal_preview_rotation_degrees", rotation)
            .put("mini2_rotation_message", statusMessage)
    }

    @Synchronized
    fun startRecordingFromBridge(configJson: String): JSONObject {
        val recordingConfig = try {
            ExperimentConfig.fromJson(configJson)
        } catch (error: IllegalArgumentException) {
            statusMessage = "녹화 시작 차단 · ${error.message ?: "invalid experiment config"}"
            notifyWebStatus()
            return buildStatusJson()
                .put("recording_start_blocked", true)
                .put("recording_error", statusMessage)
        }
        if (runSession.state == SessionState.SETUP || runSession.state == SessionState.STOPPED) {
            ensureRoiLockedForRecording()
        }
        if (!androidRoiReadyForRecording(lockedVisibleRoi)) {
            statusMessage = "녹화 시작 차단 · verified ROI required · ROI 후보 요청 또는 화면에서 ROI를 직접 지정하세요"
            notifyWebStatus()
            return buildStatusJson()
                .put("recording_start_blocked", true)
                .put("recording_error", statusMessage)
        }
        if (runSession.state != SessionState.ROI_LOCKED) {
            statusMessage = "녹화 시작 차단 · verified ROI required · ROI 후보 요청 또는 화면에서 ROI를 직접 지정하세요"
            notifyWebStatus()
            return buildStatusJson()
                .put("recording_start_blocked", true)
                .put("recording_error", statusMessage)
        }
        if (runSession.state == SessionState.ROI_LOCKED) {
            val resetResponse = pumpController.sendUserCommand(PumpCommand.Reset)
            currentPumpSnapshot()
            if (isPumpFailureResponse(resetResponse)) {
                statusMessage = "녹화 시작 차단 · 펌프 reset 실패 · ${briefPumpResponse(resetResponse)}"
                notifyWebStatus()
                return buildStatusJson()
                    .put("recording_start_blocked", true)
                    .put("recording_error", statusMessage)
            }
            val startResponse = pumpController.sendUserCommand(PumpCommand.StartRight)
            currentPumpSnapshot()
            if (isPumpFailureResponse(startResponse)) {
                statusMessage = "녹화 시작 차단 · 펌프 start 실패 · ${briefPumpResponse(startResponse)}"
                notifyWebStatus()
                return buildStatusJson()
                    .put("recording_start_blocked", true)
                    .put("recording_error", statusMessage)
            }
            runSession.config = recordingConfig
            runSession.startRecording(
                startedElapsedNanos = SystemClock.elapsedRealtimeNanos(),
                pumpRateMlPerS = recordingConfig.pumpRunRateMlPerS,
            )
            val pumpEvidence = startResponse.ifBlank { resetResponse }
            statusMessage = "recording + pump b ${pumpEvidenceLabel(pumpEvidence)} · ${briefPumpResponse(pumpEvidence)}"
        } else {
            statusMessage = "녹화 시작 불가 · state=${runSession.state}"
        }
        notifyWebStatus()
        return buildStatusJson()
    }

    @Synchronized
    fun stopRecordingFromBridge(): JSONObject {
        val stopResponse = pumpController.sendUserCommand(PumpCommand.Stop)
        val statusResponse = pumpController.sendUserCommand(PumpCommand.Status)
        currentPumpSnapshot()
        runSession.stopRecording()
        statusMessage = "stopped + pump c/s · rows=${runSession.recordedRowCount} · ${briefPumpResponse(statusResponse.ifBlank { stopResponse })}"
        notifyWebStatus()
        return buildStatusJson()
    }

    @Synchronized
    fun csvPreviewJsonFromBridge(): JSONObject {
        return JSONObject()
            .put("ok", true)
            .put("row_count", runSession.recordedRowCount)
            .put("csv", SessionExporter.buildCsv(runSession.config, runSession.rows))
    }

    @Synchronized
    fun saveCsvToDownloadsFromBridge(): JSONObject {
        val csvText = SessionExporter.buildCsv(runSession.config, runSession.rows)
        val fileName = buildCsvExportFileName()
        val uri = writeCsvTextToDownloads(fileName, csvText)
        statusMessage = "CSV 저장 완료 · Downloads/$fileName · rows=${runSession.recordedRowCount}"
        val payload = buildStatusJson()
        val exportJson = JSONObject()
            .put("display_name", fileName)
            .put("uri", uri.toString())
            .put("path", "Downloads/$fileName")
            .put("row_count", runSession.recordedRowCount)
            .put("bytes", csvText.toByteArray(Charsets.UTF_8).size)
        payload.put("csv_export", exportJson)
        payload.optJSONObject("csv")
            ?.put("path", "Downloads/$fileName")
            ?.put("export_file_name", fileName)
            ?.put("export_uri", uri.toString())
        return payload
    }

    private fun buildCsvExportFileName(): String {
        val safeRunId = runSession.runId
            .lowercase(Locale.US)
            .replace(Regex("[^a-z0-9_-]+"), "-")
            .trim('-')
            .ifBlank { "session" }
            .take(36)
        return "auto-titration-android-run-$safeRunId.csv"
    }

    private fun writeCsvTextToDownloads(fileName: String, csvText: String): Uri {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val resolver = contentResolver
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                put(MediaStore.MediaColumns.MIME_TYPE, "text/csv")
                put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val uri = requireNotNull(resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)) {
                "failed to create Downloads CSV entry"
            }
            try {
                requireNotNull(resolver.openOutputStream(uri, "w")) {
                    "failed to open Downloads CSV output stream"
                }.use { output ->
                    output.write(csvText.toByteArray(Charsets.UTF_8))
                    output.flush()
                }
                values.clear()
                values.put(MediaStore.MediaColumns.IS_PENDING, 0)
                resolver.update(uri, values, null, null)
                return uri
            } catch (error: Throwable) {
                resolver.delete(uri, null, null)
                throw error
            }
        }

        val directory = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: filesDir
        directory.mkdirs()
        val file = File(directory, fileName)
        file.writeText(csvText, Charsets.UTF_8)
        return Uri.fromFile(file)
    }

    @Synchronized
    fun probeMini2FromBridge(): JSONObject {
        return runMini2ProbeFromBridge(
            runtimeMode = Mini2OfficialRuntimeMode.OFFICIAL_PRIMARY,
            bridgeModeLabel = "OFFICIAL_PRIMARY native_stream_manual_one_shot",
        )
    }

    private fun runMini2ProbeFromBridge(
        runtimeMode: Mini2OfficialRuntimeMode,
        bridgeModeLabel: String,
    ): JSONObject {
        val mini2 = mini2Probe.probe(
            requestPermissionIfMissing = true,
            forcePermissionRequest = true,
            forceNativeLoad = true,
            attemptRawStream = true,
            runtimeMode = runtimeMode,
        ).put("mini2_last_stream_probe_mode", bridgeModeLabel)
        lastExplicitMini2Probe = mini2
        val result = safeBuildStatusJson().put("mini2", mini2)
        val moduleType = mini2.optString("mini2_official_module_type", "-")
        val rawStatus = mini2.optString("raw_stream_status", mini2.optString("mini2_status", "-"))
        statusMessage = "Mini2 $moduleType · $rawStatus · $bridgeModeLabel · ${mini2.optString("mini2_reason", "Mini2 probe updated")}"
        notifyWebStatus()
        return result
    }

    @Synchronized
    fun crashReportJsonFromBridge(): JSONObject =
        AndroidCrashLogStore.readLastCrash(this)

    @Synchronized
    fun clearCrashReportFromBridge(): JSONObject {
        val crash = AndroidCrashLogStore.clearLastCrash(this)
        statusMessage = "Android crash log cleared"
        return buildStatusJson().put("last_crash_report", crash).put("crash", crash)
    }

    @Synchronized
    fun pumpStatusFromBridge(): JSONObject {
        val response = refreshPumpStatusFromUserAction()
        statusMessage = "펌프 BT 상태 · ${briefPumpResponse(response)}"
        notifyWebStatus()
        return buildStatusJson()
    }

    @Synchronized
    fun sendPumpCommandFromBridge(command: String): JSONObject {
        val pumpCommand = PumpCommand.fromBridge(command)
        val response = pumpController.sendUserCommand(pumpCommand)
        currentPumpSnapshot()
        statusMessage = "펌프 ${pumpCommand.letter} 전송 · ${briefPumpResponse(response)}"
        notifyWebStatus()
        return buildStatusJson()
    }

    private fun briefPumpResponse(response: String): String {
        val compact = response.replace('\n', ' ').trim()
        return if (compact.length <= 110) compact else "${compact.take(110)}…"
    }

    private fun ensureRoiLockedForRecording() {
        if (androidRoiReadyForRecording(lockedVisibleRoi) &&
            (runSession.state == SessionState.SETUP || runSession.state == SessionState.STOPPED)) {
            runSession.markRoiLocked()
        }
    }

    private fun androidRoiReadyForRecording(roi: Roi?): Boolean {
        val hasVisibleFrame = latestVisibleFrameWidth > 0 && latestVisibleFrameHeight > 0
        val notRecording = runSession.state != SessionState.RECORDING
        return roi != null && hasVisibleFrame && notRecording && visibleRoiEvidence(roi) != "default_unverified"
    }

    private fun visibleRoiEvidence(roi: Roi?): String {
        if (latestVisibleRoiMask != null) return "yolo_visible_mask"
        return when (roi?.shape) {
            "android_webview_rect" -> "manual_webview_rect"
            "mask" -> "yolo_visible_mask"
            else -> "default_unverified"
        }
    }

    private fun parseAutoRoiTarget(targetPayload: String): String {
        val trimmed = targetPayload.trim()
        val raw = if (trimmed.startsWith("{")) {
            JSONObject(trimmed).optString("target", "both")
        } else {
            trimmed.ifBlank { "both" }
        }
        return when (raw.lowercase(Locale.US)) {
            "visible", "camera" -> "visible"
            "thermal", "mini2" -> "thermal"
            else -> "both"
        }
    }

    private fun defaultVisibleSensorRoi(
        frameWidth: Int = latestVisibleFrameWidth,
        frameHeight: Int = latestVisibleFrameHeight,
    ): Roi {
        val safeWidth = frameWidth.coerceAtLeast(1)
        val safeHeight = frameHeight.coerceAtLeast(1)
        return if (safeWidth > 1 && safeHeight > 1) {
            VisibleFeatureExtractor.defaultCenterRoi(safeWidth, safeHeight).copy(shape = "default_unverified_center_rect")
        } else {
            Roi(0, 0, 1, 1, "default_unverified_pending_frame")
        }
    }

    private fun defaultThermalPreviewRoi(
        frameWidth: Int = HIKMICRO_THERMAL_PREVIEW_WIDTH,
        frameHeight: Int = HIKMICRO_THERMAL_PREVIEW_HEIGHT,
    ): Roi {
        val safeFrameWidth = frameWidth.coerceAtLeast(1)
        val safeFrameHeight = frameHeight.coerceAtLeast(1)
        val width = max(1, safeFrameWidth / 2)
        val height = max(1, safeFrameHeight / 2)
        return Roi(
            x = max(0, (safeFrameWidth - width) / 2),
            y = max(0, (safeFrameHeight - height) / 2),
            width = width,
            height = height,
            shape = "mini2_auto_center_rect",
        )
    }

    private fun isPumpFailureResponse(response: String): Boolean {
        val normalized = response.trimStart().uppercase(Locale.US)
        return normalized.startsWith("ERROR") || normalized.startsWith("BLOCKED")
    }

    private fun pumpEvidenceLabel(response: String): String {
        return if (response.contains("STATUS steps=", ignoreCase = true)) {
            "firmware STATUS observed"
        } else {
            "command accepted/sent"
        }
    }

    private fun shouldPublishVisiblePreview(frameNumber: Long, nowMs: Long): Boolean {
        return frameNumber == 1L || nowMs - lastVisiblePreviewPushElapsedMs >= VISIBLE_PREVIEW_MIN_INTERVAL_MS
    }

    private fun shouldPublishVisibleStatus(frameNumber: Long, nowMs: Long): Boolean {
        return frameNumber == 1L || nowMs - lastVisibleStatusPushElapsedMs >= VISIBLE_STATUS_MIN_INTERVAL_MS
    }

    private fun appendLatestThermalPreview(live: JSONObject): JSONObject {
        if (!::mini2Probe.isInitialized) return live
        val stream = mini2Probe.latestRawStreamStatus(
            runtimeMode = Mini2OfficialRuntimeMode.OFFICIAL_PRIMARY,
        ) ?: return live
        live.put("raw_stream_status", stream.rawStreamStatus)
        live.put("raw_frame_status", stream.rawStreamStatus)
        live.put("thermal_preview_data_url", stream.thermalPreviewDataUrl)
        live.put("thermal_frame_counter", stream.frameCounter)
        live.put("thermal_frame_width", stream.frameWidth)
        live.put("thermal_frame_height", stream.frameHeight)
        live.put("thermal_transport_frame_width", stream.transportFrameWidth)
        live.put("thermal_transport_frame_height", stream.transportFrameHeight)
        live.put("thermal_preview_rotation_degrees", stream.previewRotationDegrees)
        live.put("native_symbol_discovery", stream.nativeSymbolDiscovery)
        live.put("mini2_selected_backend", stream.selectedBackend)
        live.put("mini2_stage_report", stream.stageReport)
        live.put("mini2_device_route", stream.deviceRoute)
        stream.rawAvg?.let { live.put("raw_avg", it) }
        stream.rawMin?.let { live.put("raw_min", it) }
        stream.rawMax?.let { live.put("raw_max", it) }
        if (stream.rawMin != null && stream.rawMax != null) {
            live.put("raw_delta", stream.rawMax - stream.rawMin)
        }
        return live
    }

    private fun notifyWebPreview() {
        if (!::webView.isInitialized || latestVisiblePreviewDataUrl.isBlank()) return
        val live = JSONObject()
            .put("frame_id", latestVisiblePreviewFrameId)
            .put("visible_capture_index", latestVisiblePreviewFrameId)
            .put("visible_preview_frame_id", latestVisiblePreviewFrameId)
            .put("visible_preview_data_url", latestVisiblePreviewDataUrl)
            .put("visible_frame_width", latestVisiblePreviewImageWidth)
            .put("visible_frame_height", latestVisiblePreviewImageHeight)
            .put("visible_preview_width", latestVisiblePreviewImageWidth)
            .put("visible_preview_height", latestVisiblePreviewImageHeight)
            .put("visible_display_frame_width", latestVisiblePreviewWidth)
            .put("visible_display_frame_height", latestVisiblePreviewHeight)
            .put("visible_preview_rotation_degrees", latestVisiblePreviewRotationDegrees)
            .put("visible_roi_revision", visibleRoiRevision.get())
            .put("stream_updated_epoch_s", System.currentTimeMillis() / 1000.0)
        appendLatestThermalPreview(live)
        runOnUiThread {
            val js = "window.AutoTitrationAndroidOnPreview && window.AutoTitrationAndroidOnPreview($live);"
            webView.evaluateJavascript(js, null)
        }
    }

    private fun notifyWebStatus() {
        if (!::webView.isInitialized) return
        runOnUiThread {
            val js = "window.AutoTitrationAndroidOnStatus && window.AutoTitrationAndroidOnStatus(${safeBuildStatusJson()});"
            webView.evaluateJavascript(js, null)
        }
    }

    private fun safeBuildStatusJson(): JSONObject {
        return try {
            buildStatusJson()
        } catch (error: Throwable) {
            val message = "status_build_failed ${error.javaClass.simpleName}: ${error.message ?: "no message"}"
            JSONObject()
                .put("ok", false)
                .put("mode", "android_webview")
                .put("message", message)
                .put("last_crash_report", AndroidCrashLogStore.readLastCrash(this))
                .put("mobile", JSONObject()
                    .put("enabled", true)
                    .put("paired", true)
                    .put("state", "status_build_failed")
                    .put("source", "Android WebView"))
                .put("live", JSONObject()
                    .put("status_label", "blocked")
                    .put("thermal_status", "blocked")
                    .put("mini2_reason", message)
                    .put("sync_quality", "status_build_failed"))
                .put("mini2", JSONObject()
                    .put("mini2_status", "blocked")
                    .put("mini2_reason", message)
                    .put("raw_stream_status", "blocked_native_stream")
                    .put("raw_frame_status", "blocked_native_stream")
                    .put("raw_stream", JSONObject()
                        .put("raw_stream_status", "blocked_native_stream")
                        .put("raw_frame_status", "blocked_native_stream")
                        .put("reason", message)
                        .put("native_symbol_discovery", "status_build_failed")))
        }
    }

    private fun normalizedRotationDegrees(rotationDegrees: Int): Int {
        val normalized = ((rotationDegrees % 360) + 360) % 360
        return when {
            normalized < 45 || normalized >= 315 -> 0
            normalized < 135 -> 90
            normalized < 225 -> 180
            else -> 270
        }
    }

    private fun rotatedFrameWidth(width: Int, height: Int, rotationDegrees: Int): Int {
        val normalized = normalizedRotationDegrees(rotationDegrees)
        return if (normalized == 90 || normalized == 270) height else width
    }

    private fun rotatedFrameHeight(width: Int, height: Int, rotationDegrees: Int): Int {
        val normalized = normalizedRotationDegrees(rotationDegrees)
        return if (normalized == 90 || normalized == 270) width else height
    }

    private fun sourcePointForRotatedPreview(
        rotatedX: Int,
        rotatedY: Int,
        sourceWidth: Int,
        sourceHeight: Int,
        rotationDegrees: Int,
    ): Pair<Int, Int> {
        val normalized = normalizedRotationDegrees(rotationDegrees)
        return when (normalized) {
            90 -> Pair(
                rotatedY.coerceIn(0, sourceWidth - 1),
                (sourceHeight - 1 - rotatedX).coerceIn(0, sourceHeight - 1),
            )
            180 -> Pair(
                (sourceWidth - 1 - rotatedX).coerceIn(0, sourceWidth - 1),
                (sourceHeight - 1 - rotatedY).coerceIn(0, sourceHeight - 1),
            )
            270 -> Pair(
                (sourceWidth - 1 - rotatedY).coerceIn(0, sourceWidth - 1),
                rotatedX.coerceIn(0, sourceHeight - 1),
            )
            else -> Pair(
                rotatedX.coerceIn(0, sourceWidth - 1),
                rotatedY.coerceIn(0, sourceHeight - 1),
            )
        }
    }

    private fun planeValue(
        plane: ImageProxy.PlaneProxy,
        x: Int,
        y: Int,
        defaultValue: Int,
    ): Int {
        val buffer = plane.buffer.duplicate()
        val index = plane.rowStride * y + plane.pixelStride * x
        return if (index >= 0 && index < buffer.limit()) {
            buffer.get(index).toInt() and 0xff
        } else {
            defaultValue
        }
    }

    private fun previewYuvToArgb(y: Int, u: Int, v: Int): Int {
        val c = y - 16
        val d = u - 128
        val e = v - 128
        val r = clampByte((298 * c + 409 * e + 128) shr 8)
        val g = clampByte((298 * c - 100 * d - 208 * e + 128) shr 8)
        val b = clampByte((298 * c + 516 * d + 128) shr 8)
        return 0xff000000.toInt() or (r shl 16) or (g shl 8) or b
    }

    private fun clampByte(value: Int): Int = min(255, max(0, value))

    private fun JSONObject.withLastExplicitMini2Probe(): JSONObject {
        val currentPresence = optJSONObject("current_usb_presence") ?: JSONObject()
        val currentRawStream = optJSONObject("raw_stream")
        val explicit = lastExplicitMini2Probe ?: return this
        val explicitRawStream = explicit.optJSONObject("last_stream_attempt")
            ?: explicit.optJSONObject("raw_stream")
            ?: return this
        val rawStream = if (isActiveMini2Peek(currentRawStream)) currentRawStream else explicitRawStream
        put("raw_stream", rawStream)
        put("last_stream_attempt", explicitRawStream)
        put("current_usb_presence", currentPresence)
        put("raw_stream_status", rawStream.optString("raw_stream_status", explicit.optString("raw_stream_status")))
        put("raw_frame_status", rawStream.optString("raw_frame_status", explicit.optString("raw_frame_status")))
        put("mini2_last_stream_probe_mode", explicit.optString("mini2_last_stream_probe_mode", "OFFICIAL_PRIMARY native_stream_manual_one_shot"))
        put("mini2_last_stream_probe_reason", rawStream.optString("reason"))
        return this
    }

    private fun isActiveMini2Peek(rawStream: JSONObject?): Boolean {
        if (rawStream == null) return false
        val status = rawStream.optString("raw_stream_status")
        val discovery = rawStream.optString("native_symbol_discovery")
        val statusCanReplaceExplicitAttempt =
            status == "raw_streaming_unverified" ||
                status == "stream_attempt_started" ||
                discovery.contains("passive_peek_stalled")
        return discovery.contains("hikmicro_official_f2_module") &&
            !discovery.contains("passive_poll_crash_guard") &&
            statusCanReplaceExplicitAttempt
    }

    private fun sensorRoiToDisplayRoi(
        roi: Roi,
        sensorWidth: Int,
        sensorHeight: Int,
        rotationDegrees: Int,
    ): Roi {
        val safeSensorWidth = sensorWidth.coerceAtLeast(1)
        val safeSensorHeight = sensorHeight.coerceAtLeast(1)
        val safe = clampRoiToFrame(roi, safeSensorWidth, safeSensorHeight)
        val normalized = normalizedRotationDegrees(rotationDegrees)
        val mapped = when (normalized) {
            90 -> Roi(
                x = safeSensorHeight - (safe.y + safe.height),
                y = safe.x,
                width = safe.height,
                height = safe.width,
                shape = safe.shape,
            )
            180 -> Roi(
                x = safeSensorWidth - (safe.x + safe.width),
                y = safeSensorHeight - (safe.y + safe.height),
                width = safe.width,
                height = safe.height,
                shape = safe.shape,
            )
            270 -> Roi(
                x = safe.y,
                y = safeSensorWidth - (safe.x + safe.width),
                width = safe.height,
                height = safe.width,
                shape = safe.shape,
            )
            else -> safe
        }
        return clampRoiToFrame(
            mapped,
            rotatedFrameWidth(safeSensorWidth, safeSensorHeight, normalized),
            rotatedFrameHeight(safeSensorWidth, safeSensorHeight, normalized),
        )
    }

    private fun sensorRoiToPreviewRoi(
        roi: Roi,
        sensorWidth: Int,
        sensorHeight: Int,
        rotationDegrees: Int,
        previewWidth: Int,
        previewHeight: Int,
    ): Roi {
        val safeSensorWidth = sensorWidth.coerceAtLeast(1)
        val safeSensorHeight = sensorHeight.coerceAtLeast(1)
        val normalized = normalizedRotationDegrees(rotationDegrees)
        val displayRoi = sensorRoiToDisplayRoi(
            roi = roi,
            sensorWidth = safeSensorWidth,
            sensorHeight = safeSensorHeight,
            rotationDegrees = normalized,
        )
        return scaleRoi(
            roi = displayRoi,
            fromWidth = rotatedFrameWidth(safeSensorWidth, safeSensorHeight, normalized),
            fromHeight = rotatedFrameHeight(safeSensorWidth, safeSensorHeight, normalized),
            toWidth = previewWidth,
            toHeight = previewHeight,
        )
    }

    private fun displayRoiToSensorRoi(
        roi: Roi,
        sensorWidth: Int,
        sensorHeight: Int,
        rotationDegrees: Int,
    ): Roi {
        val safeSensorWidth = sensorWidth.coerceAtLeast(1)
        val safeSensorHeight = sensorHeight.coerceAtLeast(1)
        val normalized = normalizedRotationDegrees(rotationDegrees)
        val displayWidth = rotatedFrameWidth(safeSensorWidth, safeSensorHeight, normalized)
        val displayHeight = rotatedFrameHeight(safeSensorWidth, safeSensorHeight, normalized)
        val safe = clampRoiToFrame(roi, displayWidth, displayHeight)
        val mapped = when (normalized) {
            90 -> Roi(
                x = safe.y,
                y = safeSensorHeight - (safe.x + safe.width),
                width = safe.height,
                height = safe.width,
                shape = safe.shape,
            )
            180 -> Roi(
                x = safeSensorWidth - (safe.x + safe.width),
                y = safeSensorHeight - (safe.y + safe.height),
                width = safe.width,
                height = safe.height,
                shape = safe.shape,
            )
            270 -> Roi(
                x = safeSensorWidth - (safe.y + safe.height),
                y = safe.x,
                width = safe.height,
                height = safe.width,
                shape = safe.shape,
            )
            else -> safe
        }
        return clampRoiToFrame(mapped, safeSensorWidth, safeSensorHeight)
    }

    private fun previewRoiToSensorRoi(
        roi: Roi,
        sensorWidth: Int,
        sensorHeight: Int,
        rotationDegrees: Int,
        previewWidth: Int,
        previewHeight: Int,
    ): Roi {
        val safeSensorWidth = sensorWidth.coerceAtLeast(1)
        val safeSensorHeight = sensorHeight.coerceAtLeast(1)
        val normalized = normalizedRotationDegrees(rotationDegrees)
        val displayWidth = rotatedFrameWidth(safeSensorWidth, safeSensorHeight, normalized)
        val displayHeight = rotatedFrameHeight(safeSensorWidth, safeSensorHeight, normalized)
        val displayRoi = scaleRoi(
            roi = roi,
            fromWidth = previewWidth,
            fromHeight = previewHeight,
            toWidth = displayWidth,
            toHeight = displayHeight,
        )
        return displayRoiToSensorRoi(
            roi = displayRoi,
            sensorWidth = safeSensorWidth,
            sensorHeight = safeSensorHeight,
            rotationDegrees = normalized,
        )
    }

    private fun scaleRoi(
        roi: Roi,
        fromWidth: Int,
        fromHeight: Int,
        toWidth: Int,
        toHeight: Int,
    ): Roi {
        val safeFromWidth = fromWidth.coerceAtLeast(1)
        val safeFromHeight = fromHeight.coerceAtLeast(1)
        val safeToWidth = toWidth.coerceAtLeast(1)
        val safeToHeight = toHeight.coerceAtLeast(1)
        val safe = clampRoiToFrame(roi, safeFromWidth, safeFromHeight)
        return clampRoiToFrame(
            Roi(
                x = (safe.x.toDouble() * safeToWidth / safeFromWidth).roundToInt(),
                y = (safe.y.toDouble() * safeToHeight / safeFromHeight).roundToInt(),
                width = max(1, (safe.width.toDouble() * safeToWidth / safeFromWidth).roundToInt()),
                height = max(1, (safe.height.toDouble() * safeToHeight / safeFromHeight).roundToInt()),
                shape = safe.shape,
            ),
            safeToWidth,
            safeToHeight,
        )
    }

    private fun clampRoiToFrame(roi: Roi, frameWidth: Int, frameHeight: Int): Roi {
        val safeFrameWidth = frameWidth.coerceAtLeast(1)
        val safeFrameHeight = frameHeight.coerceAtLeast(1)
        val x = roi.x.coerceIn(0, max(0, safeFrameWidth - 1))
        val y = roi.y.coerceIn(0, max(0, safeFrameHeight - 1))
        val width = roi.width.coerceAtLeast(1).coerceAtMost(max(1, safeFrameWidth - x))
        val height = roi.height.coerceAtLeast(1).coerceAtMost(max(1, safeFrameHeight - y))
        return roi.copy(x = x, y = y, width = width, height = height)
    }

    private fun Roi.toCsvString(): String = "$x,$y,$width,$height"
}
