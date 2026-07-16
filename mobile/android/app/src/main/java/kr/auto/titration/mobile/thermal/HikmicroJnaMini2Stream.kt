package kr.auto.titration.mobile.thermal

import android.content.Context
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.SystemClock
import android.util.Base64
import android.view.SurfaceView
import android.widget.TextView
import com.hcusbsdk.Interface.JavaInterface
import com.hik.f2module.F2StreamFrame
import com.hik.f2module.F2StreamAttemptDiagnostic
import com.hik.f2module.F2UsbModuleApi
import com.hik.f2module.F2UsbModuleHelper
import com.hik.viewer.manager.PreviewManagerII
import kr.auto.titration.mobile.OfficialPreviewBinding
import java.io.File
import kotlin.math.max
import kotlin.math.min
import org.json.JSONObject

const val FRAME_WAIT_TIMEOUT_MS = 30_000L
private const val MAX_CAPTURE_BYTES = 512 * 1024
private const val HIKMICRO_THERMAL_IMAGE_WIDTH = 256
private const val HIKMICRO_THERMAL_IMAGE_HEIGHT = 192
private const val HIKMICRO_OFFICIAL_MAX_PROVED_WIDTH = 384
private const val HIKMICRO_OFFICIAL_MAX_PROVED_HEIGHT = 288
private const val HIKMICRO_DEFAULT_DISPLAY_ROTATION_DEGREES = 90
private const val HIKMICRO_RAW_BYTES_PER_PIXEL = 2
private const val MAX_PREVIEW_PIXELS = HIKMICRO_OFFICIAL_MAX_PROVED_WIDTH * HIKMICRO_OFFICIAL_MAX_PROVED_HEIGHT
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
    private var lastFailureReason: String = "not_started"

    @Volatile
    private var lastStreamStageReport: String = "not_started"

    @Volatile
    private var lastInvalidPacketDiagnostic: Mini2InvalidPacketDiagnostic? = null

    @Volatile
    private var thermalPreviewRotationDegrees: Int = HIKMICRO_DEFAULT_DISPLAY_ROTATION_DEGREES

    private var previewSuccessTimes: Long = 0L

    private val f2Api: F2UsbModuleApi = F2UsbModuleApi.INSTANCE
    private val f2Helper: F2UsbModuleHelper = F2UsbModuleHelper.INSTANCE
    @Volatile
    private var officialPreviewBound = false
    // startedElapsedMs is owned by F2UsbModuleHelper; this adapter reads activeStartedElapsedMs().

    /** Compatibility wrapper for legacy tests; production must use the full official boundary. */
    fun bindOfficialPreviewSurface(surfaceView: SurfaceView) {
        PreviewManagerIIAppBinding.manager().l0(surfaceView)
    }

    /** Binds the exact official PreviewManagerII.m0/l0 production boundary. */
    @Synchronized
    fun bindOfficialPreviewSurface(binding: OfficialPreviewBinding) {
        val manager = PreviewManagerIIAppBinding.manager()
        if (officialPreviewBound) {
            manager.u0()
        }
        PreviewManagerII.m0(
            manager,
            binding.root,
            binding.selectedSurface,
            null as TextView?,
            binding.visibleLightView,
            binding.sceneMode,
            { value: Boolean -> binding.freezeCallback(value); Unit },
            { value: Boolean -> binding.overlayAvailabilityCallback(value); Unit },
            null,
            128,
            null,
        )
        officialPreviewBound = true
    }

    @Synchronized
    fun unbindOfficialPreviewSurface() {
        if (!officialPreviewBound) return
        PreviewManagerIIAppBinding.manager().u0()
        officialPreviewBound = false
    }

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
                    "Mini2 F2 raw preview frame observed through official F2 module callback; mode=$modeLabel; route=$route; stages=$lastStreamStageReport; device-reported Celsius summary is allowed only when provenance=device_global_summary; full-matrix Celsius remains unproved and blocked",
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
            lastFailureReason = "explicit manual confirm forces fresh official retry after ${elapsed}ms without F2 frame callback"
            lastStreamStageReport = "${f2Helper.lastStageReport}; explicit_manual_confirm_full_cleanup_before_fresh_start elapsedMs=$elapsed"
            f2Helper.closeSession()
        }

        return try {
            lastInvalidPacketDiagnostic = null
            previewSuccessTimes = 0L
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
                callback = { frame ->
                    captureOfficialF2Frame(frame)
                    onOfficialPreviewSuccess(context.cacheDir)
                },
                onInvalidPacketSizeTimeout = { packetSize, elapsedMs ->
                    lastInvalidPacketDiagnostic = Mini2InvalidPacketDiagnostic(
                        observedPacketSize = packetSize,
                        elapsedMs = elapsedMs,
                        allowedPacketSizes = f2Helper.activeProfileResolution()?.profile?.allowedPacketSizes ?: emptySet(),
                        userId = f2Helper.activeUserId(),
                        channel = f2Helper.activeChannel(),
                        fd = f2Helper.activeSelectedFd(),
                        profileClass = f2Helper.activeProfileResolution()?.profile?.officialClassName ?: "",
                    )
                },
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
                    callbackEntryCount = javaCallbackEntryCount(),
                    callbackEntryDetail = javaCallbackEntryDetail(),
                    invalidPacketDiagnostic = lastInvalidPacketDiagnostic,
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
                    "Mini2 F2 raw preview frame observed during passive_status_peek through official F2 module callback; mode=$modeLabel; route=$route; stages=$lastStreamStageReport; device-reported Celsius summary is allowed only when provenance=device_global_summary; full-matrix Celsius remains unproved and blocked",
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
                    callbackEntryCount = javaCallbackEntryCount(),
                    callbackEntryDetail = javaCallbackEntryDetail(),
                    invalidPacketDiagnostic = lastInvalidPacketDiagnostic,
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
                callbackEntryCount = javaCallbackEntryCount(),
                callbackEntryDetail = javaCallbackEntryDetail(),
                invalidPacketDiagnostic = lastInvalidPacketDiagnostic,
            )
        }

        lastFailureReason = "passive_status_peek found stalled HIKMICRO stream attempt after ${elapsed}ms without F2 frame callback; no new stream opened"
        lastStreamStageReport = "${f2Helper.lastStageReport}; passive_status_peek stalled_without_frame elapsedMs=$elapsed"
        return Mini2RawStreamStatus(
            rawStreamStatus = "blocked_native_stream",
            reason = "$lastFailureReason; passive_status_peek is read-only and leaves the active official session untouched; press Mini2 USB 확인 to restart an explicit official-primary probe",
            nativeSymbolDiscovery = "hikmicro_official_f2_module_passive_peek_stalled",
            selectedBackend = HikmicroMini2ModuleType.F2.backendName,
            stageReport = lastStreamStageReport,
            deviceRoute = route,
            fd = fd,
            userId = userId,
            channel = channel,
            callbackEntryCount = javaCallbackEntryCount(),
            callbackEntryDetail = javaCallbackEntryDetail(),
            invalidPacketDiagnostic = lastInvalidPacketDiagnostic,
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
            callbackEntryCount = javaCallbackEntryCount(),
            callbackEntryDetail = javaCallbackEntryDetail(),
            invalidPacketDiagnostic = lastInvalidPacketDiagnostic,
        )

    private fun blockedNativeStreamWithStage(
        reason: String,
        stageReport: String,
        route: String,
        attemptDiagnostics: List<F2StreamAttemptDiagnostic> = emptyList(),
        fd: Int = f2Helper.activeSelectedFd(),
        userId: Int = f2Helper.activeUserId(),
        channel: Int = f2Helper.activeChannel(),
        callbackEntryCount: Long = javaCallbackEntryCount(),
        callbackEntryDetail: String = javaCallbackEntryDetail(),
        invalidPacketDiagnostic: Mini2InvalidPacketDiagnostic? = lastInvalidPacketDiagnostic,
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
            callbackEntryCount = callbackEntryCount,
            callbackEntryDetail = callbackEntryDetail,
            invalidPacketDiagnostic = invalidPacketDiagnostic,
        )

    private fun javaCallbackEntryCount(): Long = JavaInterface.getInstance().streamCallbackEntryCount

    private fun javaCallbackEntryDetail(): String = JavaInterface.getInstance().lastStreamCallbackEntryDetail

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
        .put("profile_class", profileClass)
        .put("profile_module_id", profileModuleId)
        .put("profile_firmware_date", profileFirmwareDate)
        .put("profile_allowed_sizes", org.json.JSONArray(profileAllowedSizes.toList()))

    private fun captureOfficialF2Frame(frame: F2StreamFrame) {
        val bytes = frame.bytes.copyOf(frame.bytes.size.coerceIn(0, MAX_CAPTURE_BYTES))
        val previewRotation = thermalPreviewRotationDegrees
        val officialFrame = PreviewManagerIIAppBinding.latestOfficialProcessedFrame(PreviewManagerIIAppBinding.manager(), frame.frameCounter)
        val preview = if (officialFrame != null) {
            buildPreviewFrameFromOfficial(officialFrame, frame.width, frame.height, previewRotation)
        } else {
            ThermalPreviewFrame(
                width = frame.width.takeIf { it > 0 } ?: HIKMICRO_THERMAL_IMAGE_WIDTH,
                height = frame.height.takeIf { it > 0 } ?: HIKMICRO_THERMAL_IMAGE_HEIGHT,
                previewRotationDegrees = previewRotation,
                packetClassification = "official_preview_stream_info_missing",
                packetStatus = "unsupported_no_official_data_object",
                packetEvidencePrefixHex = bytes.prefixHexForStatus(),
            )
        }
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
            deviceTemperatureSummary = preview.deviceTemperatureSummary,
            packetClassification = preview.packetClassification,
            packetStatus = preview.packetStatus,
            packetEvidencePrefixHex = preview.packetEvidencePrefixHex,
            capturedElapsedMs = SystemClock.elapsedRealtime(),
        )
    }

    @Synchronized
    internal fun onOfficialPreviewSuccess(cacheDir: File): Long {
        previewSuccessTimes += 1L
        if (previewSuccessTimes == 10L) {
            f2Helper.onPreviewFrameForCalibrationPrefetch(cacheDir, previewSuccessTimes)
        }
        return previewSuccessTimes
    }

    @Synchronized
    internal fun resetOfficialPreviewSuccessCounter() {
        previewSuccessTimes = 0L
    }


    private fun buildPreviewFrameFromOfficial(
        officialFrame: OfficialProcessedF2Frame,
        transportWidth: Int,
        transportHeight: Int,
        previewRotationDegrees: Int,
    ): ThermalPreviewFrame {
        val previewData = officialFrame.previewStreamInfo.getPreviewInfoData()
        val officialNv12 = previewData.getByteArrDst()
        val rawBytes = previewData.getOffByteArrRawData().takeIf { it.isNotEmpty() }
            ?: previewData.getByteArrRawData().takeIf { it.isNotEmpty() }
        val rawValues = rawBytes?.decodeOfficialRaw16(officialFrame.width, officialFrame.height)
        val stats = rawValues?.let { summarizeAllRawValues(it) }
        val metadata: HikmicroF2TemperatureMetadata? = when (val streamInfo = officialFrame.previewStreamInfo.getIStreamInfo()) {
            is h3.c -> streamInfo.a().toMetadata()
            is h3.b -> streamInfo.a().toMetadata()
            else -> null
        }
        val packetStatus = if (officialFrame.previewStreamInfo.getIStreamInfo() is h3.c) {
            "official_preview_stream_info_offline_upload"
        } else {
            "official_preview_stream_info_private"
        }
        if (officialNv12.isEmpty()) {
            return ThermalPreviewFrame(
                width = officialFrame.width.takeIf { it > 0 } ?: transportWidth.takeIf { it > 0 } ?: HIKMICRO_THERMAL_IMAGE_WIDTH,
                height = officialFrame.height.takeIf { it > 0 } ?: transportHeight.takeIf { it > 0 } ?: HIKMICRO_THERMAL_IMAGE_HEIGHT,
                previewRotationDegrees = previewRotationDegrees,
                rawAvg = stats?.average,
                rawMin = stats?.min,
                rawMax = stats?.max,
                rawMatrixWidth = if (rawValues != null) officialFrame.width else 0,
                rawMatrixHeight = if (rawValues != null) officialFrame.height else 0,
                rawValues = rawValues,
                deviceTemperatureSummary = metadata.validatedDeviceGlobalTemperatureSummary(),
                packetClassification = "official_g3_preview_stream_info",
                packetStatus = packetStatus,
                packetEvidencePrefixHex = previewData.getByteArrSrc().prefixHexForStatus(),
            )
        }
        val matrixWidth = officialFrame.width.takeIf { it > 0 }
            ?: transportWidth.takeIf { it > 0 }
            ?: HIKMICRO_THERMAL_IMAGE_WIDTH
        val matrixHeight = officialFrame.height.takeIf { it > 0 }
            ?: transportHeight.takeIf { it > 0 }
            ?: HIKMICRO_THERMAL_IMAGE_HEIGHT
        val pixelCount = matrixWidth * matrixHeight
        if (pixelCount <= 0 || pixelCount > MAX_PREVIEW_PIXELS || officialNv12.size < pixelCount * 3 / 2) {
            return ThermalPreviewFrame(
                width = matrixWidth,
                height = matrixHeight,
                previewRotationDegrees = previewRotationDegrees,
                rawAvg = stats?.average,
                rawMin = stats?.min,
                rawMax = stats?.max,
                rawMatrixWidth = if (rawValues != null) matrixWidth else 0,
                rawMatrixHeight = if (rawValues != null) matrixHeight else 0,
                rawValues = rawValues,
                deviceTemperatureSummary = metadata.validatedDeviceGlobalTemperatureSummary(),
                packetClassification = "official_g3_preview_stream_info",
                packetStatus = packetStatus,
                packetEvidencePrefixHex = previewData.getByteArrSrc().prefixHexForStatus(),
            )
        }
        val extractedPicture = PreviewManagerIIAppBinding.manager().i1(android.util.Size(matrixWidth, matrixHeight))
        val dataUrl = extractedPicture?.takeIf { it.isNotEmpty() }?.let {
            "data:image/jpeg;base64,${Base64.encodeToString(it, Base64.NO_WRAP)}"
        }.orEmpty()
        return ThermalPreviewFrame(
            dataUrl = dataUrl,
            width = matrixWidth,
            height = matrixHeight,
            previewRotationDegrees = previewRotationDegrees,
            rawAvg = stats?.average,
            rawMin = stats?.min,
            rawMax = stats?.max,
            rawMatrixWidth = if (rawValues != null) matrixWidth else 0,
            rawMatrixHeight = if (rawValues != null) matrixHeight else 0,
            rawValues = rawValues,
            deviceTemperatureSummary = metadata.validatedDeviceGlobalTemperatureSummary(),
            packetClassification = "official_g3_preview_stream_info",
            packetStatus = packetStatus,
            packetEvidencePrefixHex = previewData.getByteArrSrc().prefixHexForStatus(),
        )
    }

    private fun ByteArray.decodeOfficialRaw16(width: Int, height: Int): IntArray? {
        val sampleCount = width * height
        if (sampleCount <= 0 || size < sampleCount * HIKMICRO_RAW_BYTES_PER_PIXEL) return null
        val values = IntArray(sampleCount)
        for (index in values.indices) {
            val byteIndex = index * HIKMICRO_RAW_BYTES_PER_PIXEL
            values[index] = (this[byteIndex].toInt() and 0xff) or ((this[byteIndex + 1].toInt() and 0xff) shl 8)
        }
        return values
    }

    private fun summarizeAllRawValues(rawValues: IntArray): RawStats? {
        if (rawValues.isEmpty()) return null
        var minRaw = Int.MAX_VALUE
        var maxRaw = Int.MIN_VALUE
        var sumRaw = 0L
        for (value in rawValues) {
            minRaw = min(minRaw, value)
            maxRaw = max(maxRaw, value)
            sumRaw += value.toLong()
        }
        return RawStats(sumRaw.toDouble() / rawValues.size.toDouble(), minRaw, maxRaw)
    }

    private fun ByteArray.prefixHexForStatus(): String = take(32).joinToString("") { byte -> "%02x".format(byte) }

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

    private data class RawStats(
        val average: Double,
        val min: Int,
        val max: Int,
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
        val deviceTemperatureSummary: Mini2DeviceTemperatureSummary? = null,
        val packetClassification: String = "unknown",
        val packetStatus: String = "unsupported_no_matrix",
        val packetEvidencePrefixHex: String = "",
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
        val deviceTemperatureSummary: Mini2DeviceTemperatureSummary?,
        val packetClassification: String,
        val packetStatus: String,
        val packetEvidencePrefixHex: String,
        val capturedElapsedMs: Long,
    ) {
        fun toStatus(reason: String, route: String): Mini2RawStreamStatus = Mini2RawStreamStatus.streamAttemptStarted(
            reason = "$reason; userId=$callbackUserId frameType=$frameType dataType=$dataType streamType=$streamType bytes=$bufferSize packet_classification=$packetClassification packet_status=$packetStatus evidence_prefix=$packetEvidencePrefixHex elapsedMs=$capturedElapsedMs",
            frameCounter = frameCounter,
            frameWidth = width,
            frameHeight = height,
            transportFrameWidth = transportWidth,
            transportFrameHeight = transportHeight,
            previewRotationDegrees = previewRotationDegrees,
            frameFormat = "hikmicro_f2_${packetClassification}_${packetStatus}",
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
            deviceTemperatureSummary = deviceTemperatureSummary,
            callbackEntryCount = javaCallbackEntryCount(),
            callbackEntryDetail = javaCallbackEntryDetail(),
            invalidPacketDiagnostic = lastInvalidPacketDiagnostic,
        )
    }

    private fun com.hik.f2module.IFR_INFO.IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO.toMetadata(): HikmicroF2TemperatureMetadata? {
        val unit = HikmicroF2TemperatureUnit.fromDeviceCode(enumTempUnit) ?: return null
        val global = HikmicroF2DeviceGlobalSummary(enumTempUnit, unit, byRefTempkey.toInt() and 0xff, fDistance, fRefTemp, unit.validatedRawCelsius(fRefTemp), unit.fromCelsius(fRefTemp), fEmissionRate, fEnvTemp, unit.validatedRawCelsius(fEnvTemp), unit.fromCelsius(fEnvTemp), fMinTmp, unit.validatedRawCelsius(fMinTmp), unit.fromCelsius(fMinTmp), fMaxTmp, unit.validatedRawCelsius(fMaxTmp), unit.fromCelsius(fMaxTmp), fAvrTmp, unit.validatedRawCelsius(fAvrTmp), unit.fromCelsius(fAvrTmp), ifrPointArr.map { HikmicroF2TemperaturePoint(it.x, it.y) }, u32TempMode, pointNum.toInt() and 0xff, boxNum.toInt() and 0xff, lineNum.toInt() and 0xff, total.toInt() and 0xff, uploadType, u32CrcVal)
        return HikmicroF2TemperatureMetadata(global, emptyList(), null)
    }

    private fun com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO.toMetadata(): HikmicroF2TemperatureMetadata? {
        val info = temp_Info.GlobalInfo
        val unit = HikmicroF2TemperatureUnit.fromDeviceCode(info.tempUnit) ?: return null
        val global = HikmicroF2DeviceGlobalSummary(info.tempUnit, unit, info.refTempkey.toInt() and 0xff, info.f32Distance, info.refTemp, unit.validatedRawCelsius(info.refTemp), unit.fromCelsius(info.refTemp), info.emissionRate, 0f, unit.validatedRawCelsius(0f), unit.fromCelsius(0f), info.minTmp, unit.validatedRawCelsius(info.minTmp), unit.fromCelsius(info.minTmp), info.maxTmp, unit.validatedRawCelsius(info.maxTmp), unit.fromCelsius(info.maxTmp), info.avrTmp, unit.validatedRawCelsius(info.avrTmp), unit.fromCelsius(info.avrTmp), info.points.map { HikmicroF2TemperaturePoint(it.x, it.y) }, 0, temp_Info.Upload.ifrOutcomeList.regionNum.pointNum.toInt() and 0xff, temp_Info.Upload.ifrOutcomeList.regionNum.boxNum.toInt() and 0xff, temp_Info.Upload.ifrOutcomeList.regionNum.lineNum.toInt() and 0xff, temp_Info.Upload.ifrOutcomeList.regionNum.total.toInt() and 0xff, 0, 0)
        return HikmicroF2TemperatureMetadata(global, emptyList(), null)
    }

    private fun HikmicroF2TemperatureMetadata?.validatedDeviceGlobalTemperatureSummary(): Mini2DeviceTemperatureSummary? {
        val metadata = this ?: return null
        if (metadata.blockedInvalidMetadata != null) return null
        val global = metadata.deviceGlobalSummary ?: return null
        val nativeUnit = global.nativeUnit ?: return null
        val avgC = global.avgTemperatureCelsius ?: return null
        val minC = global.minTemperatureCelsius ?: return null
        val maxC = global.maxTemperatureCelsius ?: return null
        return Mini2DeviceTemperatureSummary(
            avgC = avgC.toDouble(),
            minC = minC.toDouble(),
            maxC = maxC.toDouble(),
            requestedDisplayUnit = nativeUnit.name.lowercase(),
            requestedDisplayUnitCode = global.enumTempUnit,
            provenance = global.provenance,
            scope = global.provenance,
        )
    }

}
