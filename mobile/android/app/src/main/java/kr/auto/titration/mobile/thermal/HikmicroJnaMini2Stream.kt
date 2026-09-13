package kr.auto.titration.mobile.thermal

import android.content.Context
import android.graphics.Rect
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.SystemClock
import android.util.Base64
import android.view.SurfaceView
import android.widget.TextView
import com.hcusbsdk.Interface.JavaInterface
import com.hik.f2module.F2StreamFrame
import com.hik.f2module.F2StageResult
import com.hik.f2module.F2StreamAttemptDiagnostic
import com.hik.f2module.F2SessionCloseOutcome
import com.hik.f2module.F2UsbModuleApi
import com.hik.f2module.F2UsbModuleHelper
import com.hik.viewer.manager.PreviewManagerII
import kr.auto.titration.mobile.OfficialPreviewBinding
import java.io.File
import java.util.LinkedHashSet
import java.util.concurrent.Executor
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
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
private const val MAX_REMEMBERED_MEASUREMENT_SCHEDULE_KEYS = 256
private const val THERMAL_PREVIEW_JSON_KEY = "thermal_preview_data_url"

enum class Mini2OfficialRuntimeMode {
    OFFICIAL_PRIMARY,
}

internal data class OfficialF2MeasurementRoiKey(
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
) {
    fun toRect(): Rect = Rect(left, top, right, bottom)
}

internal data class OfficialF2MeasurementScheduleKey(
    val frameCounter: Long,
    val roi: OfficialF2MeasurementRoiKey?,
)

internal fun isOfficialMeasurementScheduleEligible(
    frameCounter: Long?,
    capturedElapsedMs: Long?,
    nowElapsedMs: Long,
    managerBound: Boolean,
): Boolean {
    if (!managerBound || frameCounter == null || capturedElapsedMs == null) return false
    val ageMs = nowElapsedMs - capturedElapsedMs
    return frameCounter > 0L && ageMs in 0L..FRAME_WAIT_TIMEOUT_MS
}

/** Serial, restart-safe scheduler for the blocking official renderer boundary. */
internal class OfficialF2MeasurementScheduler(
    private val executor: Executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "OfficialF2LatestMeasurementScheduler").apply { isDaemon = true }
    },
) {
    private val lock = Any()
    private val rememberedKeys = LinkedHashSet<OfficialF2MeasurementScheduleKey>()
    private var generation = 0L
    private var activeToken: Any? = null

    fun schedule(
        key: OfficialF2MeasurementScheduleKey,
        worker: (Long) -> Unit,
    ): Boolean {
        val token = Any()
        val taskGeneration: Long
        synchronized(lock) {
            if (activeToken != null || rememberedKeys.contains(key)) return false
            activeToken = token
            rememberedKeys.add(key)
            trimRememberedKeys()
            taskGeneration = generation
        }
        return try {
            executor.execute {
                try {
                    if (isTaskCurrent(token, taskGeneration)) worker(taskGeneration)
                } finally {
                    synchronized(lock) {
                        if (activeToken === token) activeToken = null
                    }
                }
            }
            true
        } catch (_: Throwable) {
            synchronized(lock) {
                if (activeToken === token) activeToken = null
                rememberedKeys.remove(key)
            }
            false
        }
    }

    fun resetLifecycle() {
        synchronized(lock) {
            generation += 1L
            activeToken = null
            rememberedKeys.clear()
        }
    }

    fun isGenerationCurrent(expectedGeneration: Long): Boolean =
        synchronized(lock) { generation == expectedGeneration }

    fun <T> runIfGenerationCurrent(expectedGeneration: Long, action: () -> T): T? =
        synchronized(lock) {
            if (generation == expectedGeneration) action() else null
        }

    private fun isTaskCurrent(token: Any, expectedGeneration: Long): Boolean =
        synchronized(lock) { activeToken === token && generation == expectedGeneration }

    private fun trimRememberedKeys() {
        while (rememberedKeys.size > MAX_REMEMBERED_MEASUREMENT_SCHEDULE_KEYS) {
            val iterator = rememberedKeys.iterator()
            if (!iterator.hasNext()) return
            iterator.next()
            iterator.remove()
        }
    }
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
    private val officialScalarMeasurementScheduler = OfficialF2MeasurementScheduler()

    @Volatile
    private var officialPreviewManager: PreviewManagerII? = null
    private var officialPreviewSurfaceAttached = false
    private var officialPreviewSurfaceView: SurfaceView? = null
    private val previewSurfaceLifecycleLock = Any()
    private val terminalShutdownRetryLock = Any()
    private var terminalShutdownRetryExecutor: java.util.concurrent.ScheduledExecutorService? = null
    private var terminalShutdownRetryFuture: ScheduledFuture<*>? = null
    private var terminalShutdownRetryAttempts = 0
    private var terminalShutdownRetryPending = false
    private var terminalShutdownRetryEpoch = 0L
    private var terminalShutdownRetryOwner: TerminalShutdownRetryOwner? = null
    private val terminalShutdownCompletionCallbacks = mutableListOf<() -> Unit>()
    // startedElapsedMs is owned by F2UsbModuleHelper; this adapter reads activeStartedElapsedMs().

    /** Compatibility wrapper for legacy tests; production must use the full official boundary. */
    fun bindOfficialPreviewSurface(surfaceView: SurfaceView) {
        synchronized(previewSurfaceLifecycleLock) {
            val manager = PreviewManagerIIAppBinding.manager()
            if (officialPreviewManager !== manager) {
                closeBoundOfficialPreviewLocked()
            } else if (officialPreviewSurfaceAttached && officialPreviewSurfaceView !== surfaceView) {
                manager.detachOfficialRenderer()
                officialPreviewSurfaceAttached = false
                officialPreviewSurfaceView = null
            }
            bindOfficialPreviewManagerLocked(manager, surfaceView) {
                manager.l0(surfaceView)
            }
        }
    }

    /** Binds the exact official PreviewManagerII.m0/l0 production boundary. */
    fun bindOfficialPreviewSurface(binding: OfficialPreviewBinding) {
        synchronized(previewSurfaceLifecycleLock) {
            val manager = PreviewManagerIIAppBinding.manager()
            if (officialPreviewManager !== manager) {
                closeBoundOfficialPreviewLocked()
            } else if (
                officialPreviewSurfaceAttached &&
                officialPreviewSurfaceView !== binding.selectedSurface
            ) {
                manager.detachOfficialRenderer()
                officialPreviewSurfaceAttached = false
                officialPreviewSurfaceView = null
            }
            bindOfficialPreviewManagerLocked(manager, binding.selectedSurface) {
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
            }
        }
    }

    fun unbindOfficialPreviewSurface(surfaceView: SurfaceView) {
        synchronized(previewSurfaceLifecycleLock) {
            if (
                !officialPreviewSurfaceAttached ||
                officialPreviewSurfaceView !== surfaceView
            ) return
            // Surface recreation is renderer-only. Keep the manager, callback generation,
            // processor, scheduler, and native F2 stream alive.
            officialPreviewManager?.detachOfficialRenderer()
            officialPreviewSurfaceAttached = false
            officialPreviewSurfaceView = null
        }
    }

    @Synchronized
    fun shutdownOfficialPreviewSession(): F2StageResult {
        resetOfficialMeasurementLifecycle()
        val closeResult = f2Api.closeSession()
        if (closeResult.closeOutcome == F2SessionCloseOutcome.STREAM_PRESERVED) {
            lastFailureReason =
                "terminal official preview shutdown blocked; native stream preserved; ${closeResult.summary}"
            lastStreamStageReport =
                "${f2Helper.lastStageReport}; terminal_official_preview_shutdown_failed native_stream_preserved=true"
            return closeResult
        }
        synchronized(previewSurfaceLifecycleLock) {
            closeBoundOfficialPreviewLocked()
        }
        latestFrameSnapshot = null
        lastInvalidPacketDiagnostic = null
        previewSuccessTimes = 0L
        if (closeResult.ok) {
            lastFailureReason = "terminal official preview shutdown"
            lastStreamStageReport = "${f2Helper.lastStageReport}; terminal_official_preview_shutdown"
        } else {
            lastFailureReason =
                "terminal official preview stream stopped but native login close remains incomplete; ${closeResult.summary}"
            lastStreamStageReport =
                "${f2Helper.lastStageReport}; terminal_official_preview_shutdown_incomplete native_stream_preserved=false"
        }
        return closeResult
    }

    /**
     * Performs the initial terminal close and publishes any retry before releasing admission.
     *
     * Fresh-session claims acquire the same lock first, so an old close result can never be
     * registered against a session that started after that close returned.
     */
    internal fun shutdownOfficialPreviewSessionWithRetryRegistration(
        shutdown: () -> F2StageResult = ::shutdownOfficialPreviewSession,
        beforeRetryScheduled: (F2StageResult) -> Unit = {},
        onRetryClosed: (() -> Unit)? = null,
    ): F2StageResult = synchronized(terminalShutdownRetryLock) {
        val result = shutdown()
        if (result.isTerminalRetryable()) {
            beforeRetryScheduled(result)
            scheduleTerminalShutdownRetryLocked(onRetryClosed)
        }
        result
    }

    fun retryPendingTerminalShutdownNow(): F2StageResult? = runTerminalShutdownRetryAttempt()

    internal fun isTerminalShutdownRetryPending(): Boolean =
        synchronized(terminalShutdownRetryLock) { terminalShutdownRetryPending }

    /**
     * Claims a preserved session for a replacement Activity before its lifecycle is installed.
     *
     * The retry lock is held for the entire close attempt, so this either waits for an already
     * admitted close to finish or cancels the old retry before the new host can adopt/bind.
     */
    internal fun claimPendingTerminalShutdownRetryForReplacementHost(
        onLoginCloseCompleted: (() -> Unit)? = null,
    ): Boolean = synchronized(terminalShutdownRetryLock) {
        if (!terminalShutdownRetryPending) return@synchronized false
        if (terminalShutdownRetryOwner?.retainedManager == null) {
            // STREAM_STOPPED_LOGIN_RETAINED has no stream manager for the replacement host to
            // adopt. Keep its logout retry alive, but transfer renderer-rebind notification.
            onLoginCloseCompleted?.let(terminalShutdownCompletionCallbacks::add)
            return@synchronized false
        }
        terminalShutdownRetryPending = false
        terminalShutdownRetryEpoch += 1L
        terminalShutdownRetryOwner = null
        terminalShutdownRetryFuture?.cancel(false)
        terminalShutdownRetryFuture = null
        terminalShutdownRetryAttempts = 0
        terminalShutdownCompletionCallbacks.clear()
        true
    }

    private fun cancelPendingTerminalShutdownRetry(notifyHostCallbacks: Boolean): Boolean {
        val callbacks = synchronized(terminalShutdownRetryLock) {
            if (!terminalShutdownRetryPending) return@synchronized null
            terminalShutdownRetryPending = false
            terminalShutdownRetryEpoch += 1L
            terminalShutdownRetryOwner = null
            terminalShutdownRetryFuture?.cancel(false)
            terminalShutdownRetryFuture = null
            terminalShutdownRetryAttempts = 0
            terminalShutdownCompletionCallbacks.toList().also {
                terminalShutdownCompletionCallbacks.clear()
            }
        }
        if (callbacks == null) return false
        if (notifyHostCallbacks) {
            callbacks.forEach { callback -> runCatching(callback) }
        }
        return true
    }

    internal fun runTerminalShutdownRetryAttempt(
        retryEpoch: Long? = null,
        shutdown: () -> F2StageResult = ::shutdownOfficialPreviewSession,
    ): F2StageResult? {
        val attempt = synchronized(terminalShutdownRetryLock) {
            if (!terminalShutdownRetryPending) return@synchronized null
            if (retryEpoch != null && retryEpoch != terminalShutdownRetryEpoch) {
                return@synchronized null
            }
            val owner = terminalShutdownRetryOwner
            if (owner == null || !owner.isCurrent()) {
                terminalShutdownRetryPending = false
                terminalShutdownRetryEpoch += 1L
                terminalShutdownRetryOwner = null
                terminalShutdownRetryFuture?.cancel(false)
                terminalShutdownRetryFuture = null
                terminalShutdownRetryAttempts = 0
                terminalShutdownCompletionCallbacks.clear()
                return@synchronized null
            }

            // Keep retry admission and shutdown atomic with replacement-host/new-session claims.
            val result = shutdown()
            terminalShutdownRetryAttempts += 1
            val callbacks: List<() -> Unit>
            if (result.closeOutcome == F2SessionCloseOutcome.CLOSED) {
                terminalShutdownRetryPending = false
                terminalShutdownRetryOwner = null
                terminalShutdownRetryFuture?.cancel(false)
                terminalShutdownRetryFuture = null
                terminalShutdownRetryAttempts = 0
                callbacks = terminalShutdownCompletionCallbacks.toList().also {
                    terminalShutdownCompletionCallbacks.clear()
                }
            } else {
                terminalShutdownRetryOwner =
                    currentTerminalShutdownRetryOwner(terminalShutdownRetryEpoch)
                if (terminalShutdownRetryAttempts >= 60) {
                    terminalShutdownRetryFuture?.cancel(false)
                    terminalShutdownRetryFuture = null
                }
                callbacks = emptyList()
            }
            result to callbacks
        }
        if (attempt == null) return null
        val (result, callbacks) = attempt
        callbacks.forEach { callback -> runCatching(callback) }
        return result
    }

    private fun currentTerminalShutdownRetryOwner(epoch: Long): TerminalShutdownRetryOwner =
        TerminalShutdownRetryOwner(
            epoch = epoch,
            userId = f2Helper.activeUserId(),
            channel = f2Helper.activeChannel(),
            fd = f2Helper.activeSelectedFd(),
            startedElapsedMs = f2Helper.activeStartedElapsedMs(),
            retainedManager = runCatching { PreviewManagerIIAppBinding.manager() }
                .getOrNull()
                ?.takeIf(PreviewManagerIIAppBinding::isManagerRetainedForTerminalCloseRetry),
        )

    private fun scheduleTerminalShutdownRetryLocked(onClosed: (() -> Unit)?) {
        onClosed?.let(terminalShutdownCompletionCallbacks::add)
        terminalShutdownRetryPending = true
        if (terminalShutdownRetryFuture?.isDone == false) {
            terminalShutdownRetryAttempts = 0
            terminalShutdownRetryOwner =
                currentTerminalShutdownRetryOwner(terminalShutdownRetryEpoch)
            return
        }
        terminalShutdownRetryAttempts = 0
        terminalShutdownRetryEpoch += 1L
        val retryEpoch = terminalShutdownRetryEpoch
        terminalShutdownRetryOwner = currentTerminalShutdownRetryOwner(retryEpoch)
        val executor = terminalShutdownRetryExecutor
            ?: Executors.newSingleThreadScheduledExecutor { runnable ->
                Thread(runnable, "OfficialF2TerminalShutdownRetry").apply { isDaemon = true }
            }.also { terminalShutdownRetryExecutor = it }
        terminalShutdownRetryFuture = executor.scheduleWithFixedDelay(
            { runTerminalShutdownRetryAttempt(retryEpoch = retryEpoch) },
            250L,
            1_000L,
            TimeUnit.MILLISECONDS,
        )
    }

    private fun F2StageResult.isTerminalRetryable(): Boolean =
        closeOutcome == F2SessionCloseOutcome.STREAM_PRESERVED ||
            closeOutcome == F2SessionCloseOutcome.STREAM_STOPPED_LOGIN_RETAINED

    private fun bindOfficialPreviewManagerLocked(
        manager: PreviewManagerII,
        surfaceView: SurfaceView,
        bindRenderer: () -> Unit,
    ) {
        if (
            officialPreviewManager === manager &&
            officialPreviewSurfaceAttached &&
            officialPreviewSurfaceView === surfaceView
        ) return
        if (officialPreviewManager !== manager) {
            closeBoundOfficialPreviewLocked()
        }
        bindRenderer()
        officialPreviewManager = manager
        officialPreviewSurfaceAttached = true
        officialPreviewSurfaceView = surfaceView
    }

    private fun closeBoundOfficialPreviewLocked() {
        val manager = officialPreviewManager
        officialPreviewManager = null
        officialPreviewSurfaceAttached = false
        officialPreviewSurfaceView = null
        if (manager == null) return
        PreviewManagerIIAppBinding.unbind(manager)
        latestFrameSnapshot = null
    }

    private fun currentOfficialPreviewSurface(): PreviewSurfaceSnapshot? =
        synchronized(previewSurfaceLifecycleLock) {
            val manager = officialPreviewManager ?: return@synchronized null
            if (!officialPreviewSurfaceAttached) return@synchronized null
            val rendererEpoch = manager.currentRendererEpoch()
            if (!manager.isOfficialRendererEpochCurrent(rendererEpoch)) return@synchronized null
            PreviewSurfaceSnapshot(manager, rendererEpoch)
        }

    private fun isOfficialPreviewSurfaceCurrent(expected: PreviewSurfaceSnapshot): Boolean =
        synchronized(previewSurfaceLifecycleLock) {
            officialPreviewSurfaceAttached &&
                officialPreviewManager === expected.manager &&
                expected.manager.isOfficialRendererEpochCurrent(expected.rendererEpoch)
        }

    fun ensureStreaming(
        context: Context,
        usbManager: UsbManager,
        device: UsbDevice,
        nativeLibraryDir: String,
        nativeReport: NativeLibraryLoadReport,
        runtimeMode: Mini2OfficialRuntimeMode = Mini2OfficialRuntimeMode.OFFICIAL_PRIMARY,
    ): Mini2RawStreamStatus {
        // A fresh explicit start owns the next session. Cancel/wait for any close retry from the
        // previous session before entering the stream object's synchronized start boundary.
        cancelPendingTerminalShutdownRetry(notifyHostCallbacks = true)
        return ensureStreamingLocked(
            context = context,
            usbManager = usbManager,
            device = device,
            nativeLibraryDir = nativeLibraryDir,
            nativeReport = nativeReport,
            runtimeMode = runtimeMode,
        )
    }

    @Synchronized
    private fun ensureStreamingLocked(
        context: Context,
        usbManager: UsbManager,
        device: UsbDevice,
        nativeLibraryDir: String,
        nativeReport: NativeLibraryLoadReport,
        runtimeMode: Mini2OfficialRuntimeMode,
    ): Mini2RawStreamStatus {
        val route = HikmicroMini2ModuleType.routeReason(device.vendorId, device.productId)
        val now = SystemClock.elapsedRealtime()
        val modeLabel = runtimeMode.name

        var currentSnapshot = currentFrameSnapshotOrNull()
        while (currentSnapshot != null) {
            val snapshot = currentSnapshot
            if (now - snapshot.capturedElapsedMs <= FRAME_WAIT_TIMEOUT_MS) {
                return snapshot.toStatus(
                    "Mini2 F2 raw preview frame observed through official F2 module callback; mode=$modeLabel; route=$route; stages=$lastStreamStageReport; device-reported Celsius summary is allowed only when provenance=device_global_summary; full-matrix Celsius remains unproved and blocked",
                    route = route,
                )
            }
            if (!clearFrameSnapshotIfSame(snapshot)) {
                currentSnapshot = currentFrameSnapshotOrNull()
                continue
            }
            lastFailureReason = "restart stalled HIKMICRO stream attempt after stale frame ${now - snapshot.capturedElapsedMs}ms old"
            lastStreamStageReport = "$lastStreamStageReport; restart stalled HIKMICRO stream attempt stale_frame"
            resetOfficialMeasurementLifecycle()
            closeSessionForFreshOpenOrBlocked(
                route = route,
                reason = "stale_frame",
            )?.let { return it }
            break
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
            resetOfficialMeasurementLifecycle()
            closeSessionForFreshOpenOrBlocked(
                route = route,
                reason = "explicit_retry",
            )?.let { return it }
        }

        return try {
            resetOfficialMeasurementLifecycle()
            lastInvalidPacketDiagnostic = null
            previewSuccessTimes = 0L
            closeSessionForFreshOpenOrBlocked(
                route = route,
                reason = "pre_open_cleanup",
            )?.let { return it }
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
                    if (captureOfficialF2Frame(frame)) {
                        val successCount = onOfficialPreviewSuccess()
                        f2Helper.onPreviewFrameForCalibrationPrefetch(
                            cacheDir = officialF2DataDirectory(context),
                            previewFrameCounter = successCount,
                            diagnoseMode = false,
                            previewPathEligible = true,
                        )
                    }
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
                    streamProcessingFailure = streamProcessingFailure(),
                    managerIngressDiagnostic = managerIngressDiagnostic(),
                    invalidPacketDiagnostic = lastInvalidPacketDiagnostic,
                    fd = failedAttempt?.fd ?: f2Helper.activeSelectedFd(),
                    userId = failedAttempt?.userId ?: f2Helper.activeUserId(),
                    channel = failedAttempt?.channel ?: start.channel,
                )
                return blocked.copy(stageReport = closeSessionAfterStartFailure("startStreamPreview_failed"))
            }

            waitingForFrameStatus(start.reason, start.stageReport, route, start.attemptDiagnostics)
        } catch (error: Throwable) {
            val closeResult = f2Api.closeSession()
            val exceptionReason = "${error.javaClass.simpleName}: ${error.message ?: "no message"}"
            lastFailureReason = if (closeResult.closeOutcome == F2SessionCloseOutcome.STREAM_PRESERVED) {
                "$exceptionReason; exception cleanup blocked with native stream preserved and exact prior binding retained"
            } else {
                exceptionReason
            }
            lastStreamStageReport =
                "exception=$exceptionReason; exception_cleanup=${closeResult.summary} " +
                    "close_outcome=${closeResult.closeOutcome.name}"
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

        var currentSnapshot = currentFrameSnapshotOrNull()
        while (currentSnapshot != null) {
            val snapshot = currentSnapshot
            val frameAgeMs = now - snapshot.capturedElapsedMs
            if (frameAgeMs <= FRAME_WAIT_TIMEOUT_MS) {
                return snapshot.toStatus(
                    "Mini2 F2 raw preview frame observed during passive_status_peek through official F2 module callback; mode=$modeLabel; route=$route; stages=$lastStreamStageReport; device-reported Celsius summary is allowed only when provenance=device_global_summary; full-matrix Celsius remains unproved and blocked",
                    route = route,
                )
            }
            if (!clearFrameSnapshotIfSame(snapshot)) {
                currentSnapshot = currentFrameSnapshotOrNull()
                continue
            }
            lastFailureReason = "passive_status_peek found stale HIKMICRO frame ${frameAgeMs}ms old; no new stream opened"
            lastStreamStageReport = "$lastStreamStageReport; passive_status_peek stale_frame ageMs=$frameAgeMs"
            staleFrameReason = lastFailureReason
            break
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
                    streamProcessingFailure = streamProcessingFailure(),
                    managerIngressDiagnostic = managerIngressDiagnostic(),
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
                streamProcessingFailure = streamProcessingFailure(),
                managerIngressDiagnostic = managerIngressDiagnostic(),
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
            streamProcessingFailure = streamProcessingFailure(),
            managerIngressDiagnostic = managerIngressDiagnostic(),
            invalidPacketDiagnostic = lastInvalidPacketDiagnostic,
        )
    }

    @Synchronized
    fun latestRawFrameSummary(device: UsbDevice): ThermalRawFrameSummary? {
        val snapshot = currentFrameSnapshotOrNull() ?: return null
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

    /**
     * Enqueues the blocking official renderer capture and scalar request on the
     * dedicated daemon worker. No renderer/native measurement work runs on the
     * caller, preview callback, or status-polling thread.
     */
    fun scheduleLatestOfficialScalarMeasurement(
        context: Context,
        measurementRoi: Rect? = null,
    ): Boolean {
        val snapshot = currentFrameSnapshotOrNull()
        val previewSurface = currentOfficialPreviewSurface()
        val now = SystemClock.elapsedRealtime()
        if (!isOfficialMeasurementScheduleEligible(
                frameCounter = snapshot?.frameCounter,
                capturedElapsedMs = snapshot?.capturedElapsedMs,
                nowElapsedMs = now,
                managerBound = previewSurface != null,
            )
        ) {
            return false
        }
        val scheduledSnapshot = snapshot ?: return false
        val scheduledSurface = previewSurface ?: return false
        val roiKey = measurementRoi?.let {
            OfficialF2MeasurementRoiKey(it.left, it.top, it.right, it.bottom)
        }
        val scheduleKey = OfficialF2MeasurementScheduleKey(scheduledSnapshot.frameCounter, roiKey)
        return officialScalarMeasurementScheduler.schedule(scheduleKey) worker@{ scheduleGeneration ->
            if (!officialScalarMeasurementScheduler.isGenerationCurrent(scheduleGeneration)) return@worker
            requestLatestOfficialScalarMeasurementInternal(
                context = context,
                measurementRoi = roiKey?.toRect(),
                expectedFrameCounter = scheduledSnapshot.frameCounter,
                expectedManager = scheduledSurface.manager,
                expectedRendererEpoch = scheduledSurface.rendererEpoch,
                expectedScheduleGeneration = scheduleGeneration,
            )
        }
    }

    /**
     * Blocking/manual boundary. This may spend up to 50 x 10 ms waiting for the
     * official renderer timestamp and must not be called from preview or status
     * threads. Production callers should use scheduleLatestOfficialScalarMeasurement.
     */
    fun requestLatestOfficialScalarMeasurement(
        context: Context,
        measurementRoi: Rect? = null,
    ): OfficialF2ScalarMeasurementState = requestLatestOfficialScalarMeasurementInternal(
        context = context,
        measurementRoi = measurementRoi,
        expectedFrameCounter = null,
        expectedManager = null,
        expectedRendererEpoch = null,
        expectedScheduleGeneration = null,
    )

    private fun requestLatestOfficialScalarMeasurementInternal(
        context: Context,
        measurementRoi: Rect?,
        expectedFrameCounter: Long?,
        expectedManager: PreviewManagerII?,
        expectedRendererEpoch: Long?,
        expectedScheduleGeneration: Long?,
    ): OfficialF2ScalarMeasurementState {
        if (expectedScheduleGeneration != null &&
            !officialScalarMeasurementScheduler.isGenerationCurrent(expectedScheduleGeneration)
        ) {
            return officialMeasurementFailure(
                frameCounter = expectedFrameCounter ?: -1L,
                reason = "official_f2_measurement_schedule_lifecycle_changed_before_worker_start",
                generation = expectedScheduleGeneration,
            )
        }
        val snapshot = currentFrameSnapshotOrNull()
            ?: return officialMeasurementFailure(
                frameCounter = -1L,
                reason = "official_f2_measurement_requires_completed_preview_frame",
                generation = expectedScheduleGeneration ?: -1L,
            )
        if (expectedFrameCounter != null && snapshot.frameCounter != expectedFrameCounter) {
            return officialMeasurementFailure(
                frameCounter = expectedFrameCounter,
                reason = "official_f2_measurement_scheduled_frame_replaced expected=$expectedFrameCounter current=${snapshot.frameCounter}",
                generation = expectedScheduleGeneration ?: -1L,
            )
        }
        val ageMs = SystemClock.elapsedRealtime() - snapshot.capturedElapsedMs
        if (ageMs > FRAME_WAIT_TIMEOUT_MS) {
            return officialMeasurementFailure(
                frameCounter = snapshot.frameCounter,
                reason = "official_f2_measurement_snapshot_stale ageMs=$ageMs",
                generation = expectedScheduleGeneration ?: -1L,
            )
        }
        val previewSurface = currentOfficialPreviewSurface()
            ?: return officialMeasurementFailure(
            frameCounter = snapshot.frameCounter,
            reason = "official_f2_measurement_requires_attached_preview_renderer",
            generation = expectedScheduleGeneration ?: -1L,
        )
        val manager = previewSurface.manager
        if (expectedManager != null && manager !== expectedManager) {
            return officialMeasurementFailure(
                frameCounter = snapshot.frameCounter,
                reason = "official_f2_measurement_bound_preview_manager_changed",
                generation = expectedScheduleGeneration ?: -1L,
            )
        }
        if (expectedRendererEpoch != null && previewSurface.rendererEpoch != expectedRendererEpoch) {
            return officialMeasurementFailure(
                frameCounter = snapshot.frameCounter,
                reason = "official_f2_measurement_renderer_changed expected=$expectedRendererEpoch current=${previewSurface.rendererEpoch}",
                generation = expectedScheduleGeneration ?: -1L,
            )
        }
        val measurementSurface = PreviewSurfaceSnapshot(
            manager = manager,
            rendererEpoch = expectedRendererEpoch ?: previewSurface.rendererEpoch,
        )
        val calibrationDir = try {
            officialF2DataDirectory(context)
        } catch (error: Throwable) {
            return officialMeasurementFailure(
                frameCounter = snapshot.frameCounter,
                reason = "official_f2_persistent_calibration_directory_unavailable_fail_closed: ${error.message ?: error.javaClass.simpleName}",
                generation = expectedScheduleGeneration ?: -1L,
            )
        }
        val officialFrame = try {
            val displaySize = Z2.g.a.E()
            PreviewManagerIIAppBinding.latestOfficialProcessedFrameWithOfflineCapture(
                manager,
                snapshot.frameCounter,
                displaySize.width,
                displaySize.height,
                measurementSurface.rendererEpoch,
            )
        } catch (error: Throwable) {
            return officialMeasurementFailure(
                frameCounter = snapshot.frameCounter,
                reason = "official_f2_renderer_capture_failed_closed: ${error.javaClass.simpleName}: ${error.message ?: "no message"}",
                generation = expectedScheduleGeneration ?: -1L,
            )
        } ?: return officialMeasurementFailure(
                frameCounter = snapshot.frameCounter,
                reason = "official_f2_measurement_requires_completed_official_packet_processor_snapshot",
                generation = expectedScheduleGeneration ?: -1L,
        )
        val enqueueMeasurement = {
            if (!isOfficialPreviewSurfaceCurrent(measurementSurface)) {
                officialMeasurementFailure(
                    frameCounter = snapshot.frameCounter,
                    reason = "official_f2_measurement_renderer_changed_after_capture",
                    generation = expectedScheduleGeneration ?: -1L,
                )
            } else {
                OfficialF2MeasurementCoordinator.requestMeasurement(
                    context = context,
                    officialFrame = officialFrame,
                    calibrationDir = calibrationDir,
                    measurementRoi = measurementRoi,
                    requestLifecycleGuard = {
                        isOfficialPreviewSurfaceCurrent(measurementSurface)
                    },
                )
            }
        }
        return if (expectedScheduleGeneration == null) {
            enqueueMeasurement()
        } else {
            officialScalarMeasurementScheduler.runIfGenerationCurrent(
                expectedScheduleGeneration,
                enqueueMeasurement,
            ) ?: officialMeasurementFailure(
                frameCounter = snapshot.frameCounter,
                reason = "official_f2_measurement_schedule_lifecycle_changed_after_renderer_capture",
                generation = expectedScheduleGeneration,
            )
        }
    }

    fun latestOfficialScalarMeasurement(): OfficialF2ScalarMeasurementState =
        OfficialF2MeasurementCoordinator.latest()

    private fun officialMeasurementFailure(
        frameCounter: Long,
        reason: String,
        generation: Long,
    ): OfficialF2ScalarMeasurementState = OfficialF2ScalarMeasurementState.failed(
        frameCounter = frameCounter,
        reason = reason,
        calibration = f2Helper.latestCalibrationAcquisitionResult(),
        identity = f2Helper.activeCalibrationIdentitySummary(),
        generation = generation,
    )

    private fun resetOfficialMeasurementLifecycle() {
        officialScalarMeasurementScheduler.resetLifecycle()
        OfficialF2MeasurementCoordinator.resetLifecycle()
    }


    internal fun officialF2DataDirectory(context: Context): File {
        return try {
            A5.y.c.b().u().also { directory ->
                if (!directory.exists() && !directory.mkdirs()) {
                    error("unable_to_create_official_f2data_directory path=${directory.absolutePath}")
                }
            }
        } catch (_: Throwable) {
            officialF2DataDirectoryFromExternalFilesRoot(context.getExternalFilesDir(null))
        }
    }

    internal fun officialF2DataDirectoryFromExternalFilesRoot(externalRoot: File?): File {
        val root = externalRoot ?: error("official_f2data_external_files_dir_unavailable_fail_closed")
        return File(root, "F2Data").also { directory ->
            if (!directory.exists() && !directory.mkdirs()) {
                error("unable_to_create_official_f2data_directory path=${directory.absolutePath}")
            }
        }
    }

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
            streamProcessingFailure = streamProcessingFailure(),
            managerIngressDiagnostic = managerIngressDiagnostic(),
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
        streamProcessingFailure: String? = streamProcessingFailure(),
        managerIngressDiagnostic: Mini2ManagerIngressDiagnostic? = managerIngressDiagnostic(),
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
            streamProcessingFailure = streamProcessingFailure,
            managerIngressDiagnostic = managerIngressDiagnostic,
            invalidPacketDiagnostic = invalidPacketDiagnostic,
        )

    private fun javaCallbackEntryCount(): Long = JavaInterface.getInstance().streamCallbackEntryCount

    private fun javaCallbackEntryDetail(): String = JavaInterface.getInstance().lastStreamCallbackEntryDetail

    private fun streamProcessingFailure(): String? =
        officialPreviewManager?.lastStreamProcessingFailure?.takeIf { it.isNotBlank() }

    private fun managerIngressDiagnostic(): Mini2ManagerIngressDiagnostic? {
        val diagnostic = runCatching {
            PreviewManagerIIAppBinding.manager().streamIngressDiagnostic
        }.getOrNull() ?: return null
        if (diagnostic.reason == "not_observed") return null
        return Mini2ManagerIngressDiagnostic(
            reason = diagnostic.reason,
            userId = diagnostic.userId,
            packetSize = diagnostic.packetSize,
            streamType = diagnostic.streamType,
            frameNumber = diagnostic.frameNumber,
            allowedPacketSizes = diagnostic.allowedPacketSizes,
            streamClosedCount = diagnostic.streamClosedCount,
            packetSizeNotAllowedCount = diagnostic.packetSizeNotAllowedCount,
            mailboxAcceptedCount = diagnostic.mailboxAcceptedCount,
            processorAcceptedCount = diagnostic.processorAcceptedCount,
            appHandoffCount = diagnostic.appHandoffCount,
        )
    }

    private fun closeSessionForFreshOpenOrBlocked(
        route: String,
        reason: String,
    ): Mini2RawStreamStatus? {
        val closeResult = f2Api.closeSessionForFreshOpen(reason)
        lastStreamStageReport =
            "${closeResult.summary}; fresh_open_cleanup=$reason " +
                "close_outcome=${closeResult.closeOutcome.name}"
        if (closeResult.closeOutcome != F2SessionCloseOutcome.STREAM_PRESERVED) return null

        lastFailureReason =
            "fresh official open blocked after $reason cleanup; native stream preserved and " +
                "exact prior binding ownership retained"
        return blockedNativeStreamWithStage(
            reason = lastFailureReason,
            stageReport = lastStreamStageReport,
            route = route,
        )
    }

    private fun closeSessionAfterStartFailure(reason: String): String {
        val closeResult = f2Api.closeSession()
        lastStreamStageReport =
            "${closeResult.summary}; full_session_reset_after_start_failure=$reason " +
                "close_outcome=${closeResult.closeOutcome.name}"
        return lastStreamStageReport
    }

    private data class TerminalShutdownRetryOwner(
        val epoch: Long,
        val userId: Int,
        val channel: Int,
        val fd: Int,
        val startedElapsedMs: Long,
        val retainedManager: PreviewManagerII?,
    ) {
        fun isCurrent(): Boolean {
            if (epoch != HikmicroJnaMini2Stream.terminalShutdownRetryEpoch) return false
            if (userId != HikmicroJnaMini2Stream.f2Helper.activeUserId()) return false
            if (channel != HikmicroJnaMini2Stream.f2Helper.activeChannel()) return false
            if (fd != HikmicroJnaMini2Stream.f2Helper.activeSelectedFd()) return false
            if (startedElapsedMs != HikmicroJnaMini2Stream.f2Helper.activeStartedElapsedMs()) return false
            return retainedManager == null ||
                PreviewManagerIIAppBinding.isManagerRetainedForTerminalCloseRetry(retainedManager)
        }
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

    private fun captureOfficialF2Frame(frame: F2StreamFrame): Boolean {
        if (!PreviewManagerIIAppBinding.isCurrentLifecycleGeneration(frame.lifecycleGeneration)) {
            return false
        }
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
        val snapshot = StreamFrameSnapshot(
            lifecycleGeneration = frame.lifecycleGeneration,
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
        synchronized(PreviewManagerIIAppBinding::class.java) {
            if (!PreviewManagerIIAppBinding.isCurrentLifecycleGeneration(frame.lifecycleGeneration)) {
                return false
            }
            latestFrameSnapshot = snapshot
        }
        return true
    }

    private fun currentFrameSnapshotOrNull(): StreamFrameSnapshot? =
        synchronized(PreviewManagerIIAppBinding::class.java) {
            val snapshot = latestFrameSnapshot ?: return@synchronized null
            if (!PreviewManagerIIAppBinding.isCurrentLifecycleGeneration(snapshot.lifecycleGeneration)) {
                latestFrameSnapshot = null
                null
            } else {
                snapshot
            }
        }

    private fun clearFrameSnapshotIfSame(snapshot: StreamFrameSnapshot): Boolean =
        synchronized(PreviewManagerIIAppBinding::class.java) {
            if (latestFrameSnapshot !== snapshot) {
                false
            } else {
                latestFrameSnapshot = null
                true
            }
        }

    @Synchronized
    internal fun onOfficialPreviewSuccess(): Long {
        previewSuccessTimes += 1L
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

    private data class PreviewSurfaceSnapshot(
        val manager: PreviewManagerII,
        val rendererEpoch: Long,
    )

    private data class StreamFrameSnapshot(
        val lifecycleGeneration: Long,
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
            streamProcessingFailure = streamProcessingFailure(),
            managerIngressDiagnostic = managerIngressDiagnostic(),
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
        if (!avgC.isFinite() || !minC.isFinite() || !maxC.isFinite()) return null
        if (minC > avgC || avgC > maxC) return null
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
