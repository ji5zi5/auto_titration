package kr.auto.titration.mobile.thermal

import android.content.Context
import android.graphics.Bitmap
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.SystemClock
import android.util.Base64
import com.hik.f2module.F2StreamFrame
import com.hik.f2module.F2StreamAttemptDiagnostic
import com.hik.f2module.F2UsbModuleApi
import com.hik.f2module.F2UsbModuleHelper
import java.io.ByteArrayOutputStream
import kotlin.math.max
import kotlin.math.min
import org.json.JSONObject

private const val STREAM_RETRY_INTERVAL_MS = 30_500L
const val FRAME_WAIT_TIMEOUT_MS = 30_000L
private const val MAX_CAPTURE_BYTES = 512 * 1024
private const val HIKMICRO_THERMAL_IMAGE_WIDTH = 256
private const val HIKMICRO_THERMAL_IMAGE_HEIGHT = 192
private const val HIKMICRO_DEFAULT_DISPLAY_ROTATION_DEGREES = 90
private const val HIKMICRO_RAW_BYTES_PER_PIXEL = 2
private const val MAX_PREVIEW_PIXELS = HIKMICRO_THERMAL_IMAGE_WIDTH * HIKMICRO_THERMAL_IMAGE_HEIGHT
private const val THERMAL_PREVIEW_JSON_KEY = "thermal_preview_data_url"

enum class Mini2OfficialRuntimeMode {
    OFFICIAL_PRIMARY,
}

/**
 * Thin app adapter for the official-shaped F2 stack:
 * com.hik.f2module.F2UsbModuleApi -> F2UsbModuleHelper ->
 * com.hcusbsdk.Interface.JavaInterface -> com.hcusbsdk.jna/HCUSBSDKByJNA and
 * com.hcusbsdk.jni/HCUSBSDKByJNI. The adapter only handles retry throttling,
 * preview-frame capture, and Mini2RawStreamStatus translation for WebView.
 */
object HikmicroJnaMini2Stream {
    @Volatile
    private var latestFrameSnapshot: StreamFrameSnapshot? = null

    @Volatile
    private var lastAttemptElapsedMs: Long = 0L

    @Volatile
    private var lastFailureReason: String = "not_started"

    @Volatile
    private var lastStreamStageReport: String = "not_started"

    @Volatile
    private var thermalPreviewRotationDegrees: Int = HIKMICRO_DEFAULT_DISPLAY_ROTATION_DEGREES

    private val f2Api: F2UsbModuleApi = F2UsbModuleApi.INSTANCE
    private val f2Helper: F2UsbModuleHelper = F2UsbModuleHelper.INSTANCE
    // startedElapsedMs is owned by F2UsbModuleHelper; this adapter reads activeStartedElapsedMs().

    @Synchronized
    fun ensureStreaming(
        context: Context,
        usbManager: UsbManager,
        device: UsbDevice,
        nativeLibraryDir: String,
        nativeReport: NativeLibraryLoadReport,
        runtimeMode: Mini2OfficialRuntimeMode = Mini2OfficialRuntimeMode.OFFICIAL_PRIMARY,
    ): Mini2RawStreamStatus {
        val route = HikmicroMini2ModuleType.routeReason(device.vendorId, device.productId)
        val now = SystemClock.elapsedRealtime()
        val modeLabel = runtimeMode.name

        latestFrameSnapshot?.let { snapshot ->
            if (now - snapshot.capturedElapsedMs <= FRAME_WAIT_TIMEOUT_MS) {
                return snapshot.toStatus(
                    "Mini2 F2 raw preview frame observed through official F2 module callback; mode=$modeLabel; route=$route; stages=$lastStreamStageReport; Celsius still blocked until fixture validation",
                    route = route,
                )
            }
            lastFailureReason = "restart stalled HIKMICRO stream attempt after stale frame ${now - snapshot.capturedElapsedMs}ms old"
            lastStreamStageReport = "$lastStreamStageReport; restart stalled HIKMICRO stream attempt stale_frame"
            latestFrameSnapshot = null
            f2Helper.closeSession()
        }

        if (!nativeReport.coreUsbLoaded) {
            return Mini2RawStreamStatus.blockedNativeUsbLibrary(
                nativeReport.coreMissingReason.ifBlank { "libHCUSBSDK.so is not loaded" },
                discovery = "hikmicro_official_f2_stack_blocked_native_library",
            )
        }

        if (f2Helper.isStreamingForDevice(device.deviceName)) {
            val elapsed = now - f2Helper.activeStartedElapsedMs()
            if (elapsed >= FRAME_WAIT_TIMEOUT_MS) {
                lastFailureReason = "restart stalled HIKMICRO stream attempt after ${elapsed}ms without F2 frame callback"
                lastStreamStageReport = "${f2Helper.lastStageReport}; restart stalled HIKMICRO stream attempt"
                f2Helper.closeSession()
            } else {
                return Mini2RawStreamStatus.streamAttemptStarted(
                    reason = "F2 official module stream attempt is active_session_reuse_no_restart and no frame callback has arrived yet; mode=$modeLabel; route=$route; elapsedMs=$elapsed; stages=${f2Helper.lastStageReport}; lastFailure=$lastFailureReason",
                    discovery = "hikmicro_official_f2_module_callback_waiting_for_frame",
                    selectedBackend = HikmicroMini2ModuleType.F2.backendName,
                    stageReport = f2Helper.lastStageReport,
                    deviceRoute = route,
                    fd = f2Helper.activeSelectedFd(),
                    userId = f2Helper.activeUserId(),
                    channel = f2Helper.activeChannel(),
                )
            }
        }

        if (now - lastAttemptElapsedMs < STREAM_RETRY_INTERVAL_MS) {
            return Mini2RawStreamStatus.streamAttemptStarted(
                reason = "Retry throttled after previous F2 official module attempt; mode=$modeLabel; route=$route; stages=$lastStreamStageReport; lastFailure=$lastFailureReason",
                discovery = "hikmicro_official_f2_module_retry_throttled",
                selectedBackend = HikmicroMini2ModuleType.F2.backendName,
                stageReport = lastStreamStageReport,
                deviceRoute = route,
                fd = f2Helper.activeSelectedFd(),
                userId = f2Helper.activeUserId(),
                channel = f2Helper.activeChannel(),
            )
        }
        lastAttemptElapsedMs = now

        return try {
            f2Helper.closeSession()
            val open = f2Api.openUsbModule(
                context = context,
                usbManager = usbManager,
                device = device,
                nativeLibraryDir = nativeLibraryDir,
            )
            lastStreamStageReport = open.stageReport
            if (!open.ok) {
                lastFailureReason = open.reason
                return blockedNativeStreamWithStage(open.reason, open.stageReport, route)
            }

            val start = f2Api.startStreamPreview(
                context = context,
                callback = { frame -> captureOfficialF2Frame(frame) },
                streamingNew = true,
            )
            lastStreamStageReport = start.stageReport
            if (!start.ok) {
                lastFailureReason = start.reason
                val failedAttempt = start.attemptDiagnostics.lastOrNull()
                val blocked = blockedNativeStreamWithStage(
                    reason = "${start.reason}; OFFICIAL_PRIMARY stopped after official F2 startStreamPreview failure; no alternate format path is executed in official-clone mode",
                    stageReport = start.stageReport,
                    route = route,
                    attemptDiagnostics = start.attemptDiagnostics,
                    fd = failedAttempt?.fd ?: f2Helper.activeSelectedFd(),
                    userId = failedAttempt?.userId ?: f2Helper.activeUserId(),
                    channel = failedAttempt?.channel ?: start.channel,
                )
                return blocked.copy(stageReport = closeSessionAfterStartFailure("startStreamPreview_failed"))
            }

            waitingForFrameStatus(start.reason, start.stageReport, route, start.attemptDiagnostics)
        } catch (error: Throwable) {
            f2Helper.closeSession()
            lastFailureReason = "${error.javaClass.simpleName}: ${error.message ?: "no message"}"
            lastStreamStageReport = "exception=$lastFailureReason"
            blockedNativeStreamWithStage(lastFailureReason, lastStreamStageReport, route)
        }
    }

    /**
     * Passive status polling must not start a fresh native stream, but it still
     * has to notice a frame that arrives after the manual bridge call returns.
     * This mirrors the active-session checks in ensureStreaming without opening
     * USB, logging in, or trying alternate stream formats.
     */
    @Synchronized
    fun peekActiveStatus(
        device: UsbDevice,
        runtimeMode: Mini2OfficialRuntimeMode = Mini2OfficialRuntimeMode.OFFICIAL_PRIMARY,
    ): Mini2RawStreamStatus? {
        val route = HikmicroMini2ModuleType.routeReason(device.vendorId, device.productId)
        val now = SystemClock.elapsedRealtime()
        val modeLabel = runtimeMode.name
        var staleFrameReason = ""

        latestFrameSnapshot?.let { snapshot ->
            val frameAgeMs = now - snapshot.capturedElapsedMs
            if (frameAgeMs <= FRAME_WAIT_TIMEOUT_MS) {
                return snapshot.toStatus(
                    "Mini2 F2 raw preview frame observed during passive_status_peek through official F2 module callback; mode=$modeLabel; route=$route; stages=$lastStreamStageReport; Celsius still blocked until fixture validation",
                    route = route,
                )
            }
            lastFailureReason = "passive_status_peek found stale HIKMICRO frame ${frameAgeMs}ms old; no new stream opened"
            lastStreamStageReport = "$lastStreamStageReport; passive_status_peek stale_frame ageMs=$frameAgeMs"
            staleFrameReason = lastFailureReason
            latestFrameSnapshot = null
        }

        if (!f2Helper.isStreamingForDevice(device.deviceName)) {
            if (staleFrameReason.isNotBlank()) {
                return Mini2RawStreamStatus(
                    rawStreamStatus = "blocked_native_stream",
                    reason = "$staleFrameReason; no active F2 session remains; press Mini2 USB 확인 to restart an explicit official-primary probe",
                    nativeSymbolDiscovery = "hikmicro_official_f2_module_passive_peek_stalled_stale_frame",
                    selectedBackend = HikmicroMini2ModuleType.F2.backendName,
                    stageReport = lastStreamStageReport,
                    deviceRoute = route,
                )
            }
            return null
        }

        val elapsed = now - f2Helper.activeStartedElapsedMs()
        val fd = f2Helper.activeSelectedFd()
        val userId = f2Helper.activeUserId()
        val channel = f2Helper.activeChannel()
        if (elapsed < FRAME_WAIT_TIMEOUT_MS) {
            return Mini2RawStreamStatus.streamAttemptStarted(
                reason = "F2 official module stream attempt is still active during passive_status_peek but no frame callback has arrived yet; mode=$modeLabel; route=$route; elapsedMs=$elapsed; stages=${f2Helper.lastStageReport}; lastFailure=$lastFailureReason",
                discovery = "hikmicro_official_f2_module_passive_peek_waiting_for_frame",
                selectedBackend = HikmicroMini2ModuleType.F2.backendName,
                stageReport = f2Helper.lastStageReport,
                deviceRoute = route,
                fd = fd,
                userId = userId,
                channel = channel,
            )
        }

        lastFailureReason = "passive_status_peek found stalled HIKMICRO stream attempt after ${elapsed}ms without F2 frame callback; no new stream opened"
        lastStreamStageReport = "${f2Helper.lastStageReport}; passive_status_peek stalled_without_frame elapsedMs=$elapsed"
        f2Helper.closeSession()
        return Mini2RawStreamStatus(
            rawStreamStatus = "blocked_native_stream",
            reason = "$lastFailureReason; press Mini2 USB 확인 to restart an explicit official-primary probe",
            nativeSymbolDiscovery = "hikmicro_official_f2_module_passive_peek_stalled",
            selectedBackend = HikmicroMini2ModuleType.F2.backendName,
            stageReport = lastStreamStageReport,
            deviceRoute = route,
            fd = fd,
            userId = userId,
            channel = channel,
        )
    }

    @Synchronized
    fun latestRawFrameSummary(device: UsbDevice): ThermalRawFrameSummary? {
        val snapshot = latestFrameSnapshot ?: return null
        val ageMs = SystemClock.elapsedRealtime() - snapshot.capturedElapsedMs
        if (ageMs > FRAME_WAIT_TIMEOUT_MS) return null
        if (!f2Helper.isStreamingForDevice(device.deviceName)) return null
        val rawValues = snapshot.rawValues ?: return null
        val matrix = summarizeRawValues(
            rawValues = rawValues,
            matrixWidth = snapshot.rawMatrixWidth,
            startX = 0,
            startY = 0,
            width = snapshot.rawMatrixWidth,
            height = snapshot.rawMatrixHeight,
        )
        val roiWidth = max(1, snapshot.rawMatrixWidth / 2)
        val roiHeight = max(1, snapshot.rawMatrixHeight / 2)
        val roiX = ((snapshot.rawMatrixWidth - roiWidth) / 2).coerceAtLeast(0)
        val roiY = ((snapshot.rawMatrixHeight - roiHeight) / 2).coerceAtLeast(0)
        val roi = summarizeRawValues(
            rawValues = rawValues,
            matrixWidth = snapshot.rawMatrixWidth,
            startX = roiX,
            startY = roiY,
            width = roiWidth,
            height = roiHeight,
        )
        return ThermalRawFrameSummary(
            frameWidth = snapshot.rawMatrixWidth,
            frameHeight = snapshot.rawMatrixHeight,
            rawRoi = roi,
            rawMatrix = matrix,
            rawValues = rawValues.copyOf(),
        )
    }

    @Synchronized
    fun rotatePreviewClockwise(): Int {
        thermalPreviewRotationDegrees = normalizedRotationDegrees(thermalPreviewRotationDegrees + 90)
        latestFrameSnapshot = null
        lastStreamStageReport = "$lastStreamStageReport; preview_rotation_degrees=$thermalPreviewRotationDegrees"
        return thermalPreviewRotationDegrees
    }

    fun activePreviewRotationDegrees(): Int = thermalPreviewRotationDegrees

    private fun waitingForFrameStatus(
        reason: String,
        stageReport: String,
        route: String,
        attemptDiagnostics: List<F2StreamAttemptDiagnostic> = emptyList(),
    ): Mini2RawStreamStatus =
        Mini2RawStreamStatus.streamAttemptStarted(
            reason = "$reason; route=$route; stages=$stageReport",
            discovery = "hikmicro_official_f2_module_stream_callback_waiting_for_frame",
            selectedBackend = HikmicroMini2ModuleType.F2.backendName,
            stageReport = stageReport,
            deviceRoute = route,
            fd = f2Helper.activeSelectedFd(),
            userId = f2Helper.activeUserId(),
            channel = f2Helper.activeChannel(),
            attemptDiagnostics = attemptDiagnostics.map { it.toJson() },
        )

    private fun blockedNativeStreamWithStage(
        reason: String,
        stageReport: String,
        route: String,
        attemptDiagnostics: List<F2StreamAttemptDiagnostic> = emptyList(),
        fd: Int = f2Helper.activeSelectedFd(),
        userId: Int = f2Helper.activeUserId(),
        channel: Int = f2Helper.activeChannel(),
    ): Mini2RawStreamStatus =
        Mini2RawStreamStatus(
            rawStreamStatus = "blocked_native_stream",
            reason = reason,
            nativeSymbolDiscovery = "hikmicro_official_f2_module_stream_callback_attempt",
            selectedBackend = HikmicroMini2ModuleType.F2.backendName,
            stageReport = stageReport,
            deviceRoute = route,
            fd = fd,
            userId = userId,
            channel = channel,
            attemptDiagnostics = attemptDiagnostics.map { it.toJson() },
        )

    private fun closeSessionAfterStartFailure(reason: String): String {
        f2Helper.closeSession()
        lastStreamStageReport = "${f2Helper.lastStageReport}; full_session_reset_after_start_failure=$reason"
        return lastStreamStageReport
    }

    private fun F2StreamAttemptDiagnostic.toJson(): JSONObject = JSONObject()
        .put("start_mode", startMode)
        .put("reset_mode", resetMode)
        .put("video_format", videoFormat)
        .put("callback_stream_type", callbackStreamType)
        .put("set_video_status", setVideoStatus)
        .put("start_status", startStatus)
        .put("last_error", lastError)
        .put("channel", channel)
        .put("fd", fd)
        .put("userId", userId)
        .put("user_id", userId)
        .put("start_path", startPath)
        .put("verbose_only", verboseOnly)

    private fun captureOfficialF2Frame(frame: F2StreamFrame) {
        val bytes = frame.bytes.copyOf(frame.bytes.size.coerceIn(0, MAX_CAPTURE_BYTES))
        val previewRotation = thermalPreviewRotationDegrees
        val preview = buildPreviewFrame(bytes, frame.width, frame.height, previewRotation)
        latestFrameSnapshot = StreamFrameSnapshot(
            frameCounter = max(1L, frame.frameCounter),
            callbackUserId = frame.callbackUserId,
            width = preview.width,
            height = preview.height,
            transportWidth = frame.width,
            transportHeight = frame.height,
            previewRotationDegrees = previewRotation,
            frameType = frame.frameType,
            dataType = frame.dataType,
            streamType = frame.streamType,
            bufferSize = bytes.size,
            previewDataUrl = preview.dataUrl,
            rawAvg = preview.rawAvg,
            rawMin = preview.rawMin,
            rawMax = preview.rawMax,
            rawMatrixWidth = preview.rawMatrixWidth,
            rawMatrixHeight = preview.rawMatrixHeight,
            rawValues = preview.rawValues,
            capturedElapsedMs = SystemClock.elapsedRealtime(),
        )
    }

    private fun buildPreviewFrame(bytes: ByteArray, width: Int, height: Int, previewRotationDegrees: Int): ThermalPreviewFrame {
        if (bytes.size >= 4 && bytes[0] == 0xff.toByte() && bytes[1] == 0xd8.toByte()) {
            return ThermalPreviewFrame(
                dataUrl = "data:image/jpeg;base64,${Base64.encodeToString(bytes, Base64.NO_WRAP)}",
                width = width.takeIf { it > 0 } ?: HIKMICRO_THERMAL_IMAGE_WIDTH,
                height = height.takeIf { it > 0 } ?: HIKMICRO_THERMAL_IMAGE_HEIGHT,
                previewRotationDegrees = previewRotationDegrees,
            )
        }
        val safeWidth = width.takeIf { it > 0 } ?: HIKMICRO_THERMAL_IMAGE_WIDTH
        val matrixWidth = min(HIKMICRO_THERMAL_IMAGE_WIDTH, safeWidth).coerceAtLeast(1)
        val availableRows = if (safeWidth > 0) bytes.size / (safeWidth * HIKMICRO_RAW_BYTES_PER_PIXEL) else 0
        val matrixHeight = min(HIKMICRO_THERMAL_IMAGE_HEIGHT, min(height.takeIf { it > 0 } ?: HIKMICRO_THERMAL_IMAGE_HEIGHT, availableRows)).coerceAtLeast(1)
        val pixelCount = matrixWidth * matrixHeight
        if (pixelCount <= 0 || pixelCount > MAX_PREVIEW_PIXELS || bytes.size < HIKMICRO_RAW_BYTES_PER_PIXEL) {
            return ThermalPreviewFrame(width = matrixWidth, height = matrixHeight)
        }
        val rawValues = IntArray(pixelCount)
        var minRaw = Int.MAX_VALUE
        var maxRaw = Int.MIN_VALUE
        var sumRaw = 0L
        for (row in 0 until matrixHeight) {
            val sourceRowOffset = row * safeWidth * HIKMICRO_RAW_BYTES_PER_PIXEL
            for (col in 0 until matrixWidth) {
                val index = row * matrixWidth + col
                val byteIndex = sourceRowOffset + col * HIKMICRO_RAW_BYTES_PER_PIXEL
                if (byteIndex + 1 >= bytes.size) break
                val value = (bytes[byteIndex].toInt() and 0xff) or ((bytes[byteIndex + 1].toInt() and 0xff) shl 8)
                rawValues[index] = value
                minRaw = min(minRaw, value)
                maxRaw = max(maxRaw, value)
                sumRaw += value.toLong()
            }
        }
        if (minRaw == Int.MAX_VALUE || maxRaw == Int.MIN_VALUE) {
            return ThermalPreviewFrame(width = matrixWidth, height = matrixHeight)
        }
        val pixels = IntArray(pixelCount)
        for (index in 0 until pixelCount) {
            val luminance = normalizeRawToLuminance(rawValues[index], minRaw, maxRaw)
            pixels[index] = 0xff000000.toInt() or (luminance shl 16) or (luminance shl 8) or luminance
        }
        val rotated = rotateThermalPixels(pixels, matrixWidth, matrixHeight, previewRotationDegrees)
        val bitmap = Bitmap.createBitmap(rotated.pixels, rotated.width, rotated.height, Bitmap.Config.ARGB_8888)
        val dataUrl = ByteArrayOutputStream().use { output ->
            bitmap.compress(Bitmap.CompressFormat.JPEG, 70, output)
            bitmap.recycle()
            "data:image/jpeg;base64,${Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP)}"
        }
        return ThermalPreviewFrame(
            dataUrl = dataUrl,
            width = rotated.width,
            height = rotated.height,
            previewRotationDegrees = previewRotationDegrees,
            rawAvg = sumRaw.toDouble() / pixelCount,
            rawMin = minRaw,
            rawMax = maxRaw,
            rawMatrixWidth = matrixWidth,
            rawMatrixHeight = matrixHeight,
            rawValues = rawValues,
        )
    }

    private fun summarizeRawValues(
        rawValues: IntArray,
        matrixWidth: Int,
        startX: Int,
        startY: Int,
        width: Int,
        height: Int,
    ): MatrixSummary? {
        if (matrixWidth <= 0 || width <= 0 || height <= 0 || rawValues.isEmpty()) return null
        var minRaw = Int.MAX_VALUE
        var maxRaw = Int.MIN_VALUE
        var sumRaw = 0L
        var count = 0
        for (row in startY until startY + height) {
            val rowOffset = row * matrixWidth
            if (rowOffset < 0 || rowOffset >= rawValues.size) break
            for (col in startX until startX + width) {
                val index = rowOffset + col
                if (index !in rawValues.indices) continue
                val value = rawValues[index]
                minRaw = min(minRaw, value)
                maxRaw = max(maxRaw, value)
                sumRaw += value.toLong()
                count += 1
            }
        }
        if (count <= 0 || minRaw == Int.MAX_VALUE || maxRaw == Int.MIN_VALUE) return null
        return MatrixSummary(
            avg = sumRaw.toDouble() / count.toDouble(),
            min = minRaw.toDouble(),
            max = maxRaw.toDouble(),
        )
    }

    private fun normalizeRawToLuminance(value: Int, minRaw: Int, maxRaw: Int): Int {
        val range = max(1, maxRaw - minRaw)
        return (((value - minRaw).toLong() * 255L) / range).toInt().coerceIn(0, 255)
    }

    private fun rotateThermalPixels(pixels: IntArray, width: Int, height: Int, rotationDegrees: Int): RotatedPixels {
        val normalized = normalizedRotationDegrees(rotationDegrees)
        if (normalized == 0) return RotatedPixels(pixels, width, height)
        val outputWidth = if (normalized == 90 || normalized == 270) height else width
        val outputHeight = if (normalized == 90 || normalized == 270) width else height
        val output = IntArray(outputWidth * outputHeight)
        for (y in 0 until height) {
            for (x in 0 until width) {
                val source = pixels[y * width + x]
                val destX: Int
                val destY: Int
                when (normalized) {
                    90 -> {
                        destX = height - 1 - y
                        destY = x
                    }
                    180 -> {
                        destX = width - 1 - x
                        destY = height - 1 - y
                    }
                    else -> {
                        destX = y
                        destY = width - 1 - x
                    }
                }
                output[destY * outputWidth + destX] = source
            }
        }
        return RotatedPixels(output, outputWidth, outputHeight)
    }

    private fun normalizedRotationDegrees(rotationDegrees: Int): Int =
        (((rotationDegrees % 360) + 360) % 360 / 90) * 90

    private data class RotatedPixels(
        val pixels: IntArray,
        val width: Int,
        val height: Int,
    )

    private data class ThermalPreviewFrame(
        val dataUrl: String = "",
        val width: Int = HIKMICRO_THERMAL_IMAGE_WIDTH,
        val height: Int = HIKMICRO_THERMAL_IMAGE_HEIGHT,
        val previewRotationDegrees: Int = 0,
        val rawAvg: Double? = null,
        val rawMin: Int? = null,
        val rawMax: Int? = null,
        val rawMatrixWidth: Int = 0,
        val rawMatrixHeight: Int = 0,
        val rawValues: IntArray? = null,
    )

    private data class StreamFrameSnapshot(
        val frameCounter: Long,
        val callbackUserId: Int,
        val width: Int,
        val height: Int,
        val transportWidth: Int,
        val transportHeight: Int,
        val previewRotationDegrees: Int,
        val frameType: Int,
        val dataType: Int,
        val streamType: Int,
        val bufferSize: Int,
        val previewDataUrl: String,
        val rawAvg: Double?,
        val rawMin: Int?,
        val rawMax: Int?,
        val rawMatrixWidth: Int,
        val rawMatrixHeight: Int,
        val rawValues: IntArray?,
        val capturedElapsedMs: Long,
    ) {
        fun toStatus(reason: String, route: String): Mini2RawStreamStatus = Mini2RawStreamStatus.streamAttemptStarted(
            reason = "$reason; userId=$callbackUserId frameType=$frameType dataType=$dataType streamType=$streamType bytes=$bufferSize elapsedMs=$capturedElapsedMs",
            frameCounter = frameCounter,
            frameWidth = width,
            frameHeight = height,
            transportFrameWidth = transportWidth,
            transportFrameHeight = transportHeight,
            previewRotationDegrees = previewRotationDegrees,
            frameFormat = "hikmicro_f2_official_module_frame_raw_unverified",
            thermalPreviewDataUrl = previewDataUrl,
            rawAvg = rawAvg,
            rawMin = rawMin,
            rawMax = rawMax,
            discovery = "hikmicro_official_f2_module_frame_observed",
            selectedBackend = HikmicroMini2ModuleType.F2.backendName,
            stageReport = lastStreamStageReport,
            deviceRoute = route,
            fd = f2Helper.activeSelectedFd(),
            userId = callbackUserId,
            channel = f2Helper.activeChannel(),
        )
    }
}
