package com.hik.f2module

import android.content.Context
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.util.Size
import com.hcusbsdk.Interface.JavaInterface
import com.hik.viewer.manager.PreviewManagerII
import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolution
import kr.auto.titration.mobile.thermal.PreviewManagerIIAppBinding
import kr.auto.titration.mobile.thermal.HikmicroF2Size
import kr.auto.titration.mobile.thermal.OfficialF2MeasurementCoordinator

/** Public API boundary for the F2 USB preview lifecycle. */
class F2UsbModuleApi private constructor() {
    private val helper: F2UsbModuleHelper = F2UsbModuleHelper.INSTANCE
    private val lifecycleLock = Any()
    private var activeAppCallback: F2StreamCallback? = null
    private var activeInvalidPacketSizeTimeout: ((packetSize: Int, elapsedMs: Long) -> Unit)? = null

    @Synchronized
    fun openUsbModule(
        context: Context,
        usbManager: UsbManager,
        device: UsbDevice,
        nativeLibraryDir: String,
    ): F2OpenResult = synchronized(lifecycleLock) {
        val previousAppCallback = activeAppCallback
        val previousInvalidPacketSizeTimeout = activeInvalidPacketSizeTimeout
        val previousUserId = helper.activeUserId()
        val previousChannel = helper.activeChannel()
        val previousManager = if (previousAppCallback != null) {
            try {
                PreviewManagerIIAppBinding.manager()
            } catch (_: IllegalStateException) {
                null
            }
        } else {
            null
        }
        runF2StartTransition(
            rollback = {
                restorePriorAppBindingIfSessionUnchanged(
                    previousUserId,
                    previousChannel,
                    previousManager,
                    previousAppCallback,
                    previousInvalidPacketSizeTimeout,
                )
            },
        ) {
            OfficialF2MeasurementCoordinator.resetLifecycle()
            activeAppCallback = null
            activeInvalidPacketSizeTimeout = null
            try {
                PreviewManagerIIAppBinding.prepareForUsbReopen()
            } catch (_: IllegalStateException) {
                // The lifecycle may be installed after USB login; startStreamPreview
                // still performs the mandatory processor refresh before native start.
            }
            var retryIndex = 0
            lateinit var result: F2OpenResult
            do {
                result = helper.openUsbDevice(
                    context = context,
                    usbManager = usbManager,
                    device = device,
                    nativeLibraryDir = nativeLibraryDir,
                )
                if (!result.ok) {
                    retryIndex += 1
                    try {
                        Thread.sleep(retryIndex * 500L)
                    } catch (_: InterruptedException) {
                        Thread.currentThread().interrupt()
                        break
                    }
                }
            } while (!result.ok && retryIndex < 5)
            var finalResult = synchronizeRuntimeAfterOpen(result.copy(
                stageReport = "F2UsbModuleApi.openUsbModule:officialRetry retryIndex=$retryIndex success=${result.ok}; ${result.stageReport}",
            ))
            if (!finalResult.ok &&
                restorePriorAppBindingIfSessionUnchanged(
                    previousUserId,
                    previousChannel,
                    previousManager,
                    previousAppCallback,
                    previousInvalidPacketSizeTimeout,
                )
            ) {
                finalResult = finalResult.copy(
                    stageReport =
                        "${finalResult.stageReport}; prior_app_binding_restore_after_failed_reopen=exact_prior_owner " +
                            "userId=$previousUserId channel=$previousChannel",
                )
            }
            finalResult
        }
    }

    @Synchronized
    fun startStreamPreview(
        context: Context,
        callback: F2StreamCallback,
        streamingNew: Boolean? = null,
        onInvalidPacketSizeTimeout: ((packetSize: Int, elapsedMs: Long) -> Unit)? = null,
    ): F2StartResult = synchronized(lifecycleLock) {
        val startConfig = resolveStartConfig(
            helper.activeProfileResolution(),
            streamingNewOverride = streamingNew,
        )
        if (!startConfig.ok) return@synchronized startConfig.toStartResult(helper.lastStageReport)
        val config = startConfig.config ?: return@synchronized startConfig.toStartResult(helper.lastStageReport)
        val previewManager = PreviewManagerIIAppBinding.manager()
        val stopTransition = stopForTransition(
            context = context,
            streamingNew = config.streamingNew,
            previewManager = previewManager,
        )
        replacementStartBlockedResult(
            activeChannelBeforeStop = stopTransition.activeChannelBeforeStop,
            stopResult = stopTransition.stopResult,
            startPath = "official_interface_wrapper",
            stageReport = helper.lastStageReport,
            profileResolution = helper.activeProfileResolution(),
        )?.let { return@synchronized it }
        val result = runF2StartTransition(
            rollback = { rollbackPreparedAppStart(previewManager) },
        ) {
            PreviewManagerIIAppBinding.bind(previewManager, callback)
            if (!previewManager.refreshF2ProcessorFromRuntimeProfile()) {
                return@runF2StartTransition F2StartResult(
                    ok = false,
                    waitingForFrame = false,
                    channel = -1,
                    reason = "F2 runtime processor unavailable after resolved profile activation",
                    stageReport = "${helper.lastStageReport}; runtimeProfile=resolved; previewProcessor=not_initialized; USB_StartStreamCallback=not_run",
                    profileResolution = startConfig.profileResolution,
                )
            }
            setInvalidPacketSizeTimeoutCallback(previewManager, onInvalidPacketSizeTimeout)
            val previewCallback = F2ModuleStreamCallback(null, previewManager.R())
            startNativeStreamPreviewLocked(
                streamCallback = previewCallback,
                config = config,
            )
        }
        if (!result.ok) {
            rollbackPreparedAppStart(previewManager)
            return@synchronized result
        }
        activeAppCallback = callback
        activeInvalidPacketSizeTimeout = onInvalidPacketSizeTimeout
        result
    }

    @Synchronized
    fun startStreamPreview(
        context: Context,
        streamCallback: F2ModuleStreamCallback,
        streamingNew: Boolean? = null,
        frameRate: Int? = null,
        videoCodingType: Int? = null,
        previewSize: Size? = null,
    ): F2StartResult = synchronized(lifecycleLock) {
        val startConfig = resolveStartConfig(
            helper.activeProfileResolution(),
            streamingNewOverride = streamingNew,
            frameRateOverride = frameRate,
            videoCodingTypeOverride = videoCodingType,
            previewSizeOverride = previewSize,
        )
        if (!startConfig.ok) return@synchronized startConfig.toStartResult(helper.lastStageReport)
        val config = startConfig.config ?: return@synchronized startConfig.toStartResult(helper.lastStageReport)
        startStreamPreviewLocked(
            context = context,
            streamCallback = streamCallback,
            config = config,
        )
    }

    private fun startStreamPreviewLocked(
        context: Context,
        streamCallback: F2ModuleStreamCallback,
        config: F2ProfileStartConfig,
    ): F2StartResult {
        val stopTransition = stopForTransition(context, config.streamingNew)
        replacementStartBlockedResult(
            activeChannelBeforeStop = stopTransition.activeChannelBeforeStop,
            stopResult = stopTransition.stopResult,
            startPath = "official_interface_wrapper",
            stageReport = helper.lastStageReport,
            profileResolution = helper.activeProfileResolution(),
        )?.let { return it }
        return startNativeStreamPreviewLocked(streamCallback, config)
    }

    private fun startNativeStreamPreviewLocked(
        streamCallback: F2ModuleStreamCallback,
        config: F2ProfileStartConfig,
    ): F2StartResult {
        val fStreamCallBack = streamCallback.getFStreamCallBack()
            ?: return F2StartResult(
                ok = false,
                waitingForFrame = false,
                channel = -1,
                reason = "F2ModuleStreamCallback.getFStreamCallBack returned null",
                stageReport = "F2UsbModuleApi.startStreamPreview callback=null",
            )
        JavaInterface.getInstance().resetStreamCallbackEntryDiagnostics()
        return helper.startStreamPreview(
            fStreamCallBack = fStreamCallBack,
            size = config.previewSize,
            frameRate = config.frameRate,
            videoCodingType = config.videoCodingType,
            streamType = HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE,
            streamingNew = config.streamingNew,
        )
    }

    @Synchronized
    fun startStreamPreviewJNA(
        context: Context,
        streamCallback: F2ModuleStreamCallback,
        streamingNew: Boolean? = null,
        frameRate: Int? = null,
        videoCodingType: Int? = null,
        previewSize: Size? = null,
    ): F2StartResult = synchronized(lifecycleLock) {
        val startConfig = resolveStartConfig(
            helper.activeProfileResolution(),
            streamingNewOverride = streamingNew,
            frameRateOverride = frameRate,
            videoCodingTypeOverride = videoCodingType,
            previewSizeOverride = previewSize,
        )
        if (!startConfig.ok) return@synchronized startConfig.toStartResult(helper.lastStageReport)
        val config = startConfig.config ?: return@synchronized startConfig.toStartResult(helper.lastStageReport)
        val stopTransition = stopForTransition(context, config.streamingNew)
        replacementStartBlockedResult(
            activeChannelBeforeStop = stopTransition.activeChannelBeforeStop,
            stopResult = stopTransition.stopResult,
            startPath = "official_jna_wrapper",
            stageReport = helper.lastStageReport,
            profileResolution = helper.activeProfileResolution(),
        )?.let { return@synchronized it }
        val fStreamCallBackJNA = streamCallback.getFStreamCallBackJNA()
            ?: return@synchronized F2StartResult(
                ok = false,
                waitingForFrame = false,
                channel = -1,
                reason = "F2ModuleStreamCallback.getFStreamCallBackJNA returned null",
                stageReport = "F2UsbModuleApi.startStreamPreviewJNA callback=null",
            )
        JavaInterface.getInstance().resetStreamCallbackEntryDiagnostics()
        helper.startStreamPreviewJNA(
            fStreamCallBack = fStreamCallBackJNA,
            size = config.previewSize,
            frameRate = config.frameRate,
            videoCodingType = config.videoCodingType,
            streamType = HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE,
            streamingNew = config.streamingNew,
        )
    }

    @Synchronized
    fun stopStreamPreview(context: Context, streamingNew: Boolean = true): F2StageResult =
        synchronized(lifecycleLock) { stopForTransition(context, streamingNew).stopResult }

    @Synchronized
    fun closeSession(): F2StageResult = synchronized(lifecycleLock) {
        val previousAppCallback = activeAppCallback
        val previousInvalidPacketSizeTimeout = activeInvalidPacketSizeTimeout
        val previousUserId = helper.activeUserId()
        val previousChannel = helper.activeChannel()
        val bindingManager = if (previousAppCallback != null) {
            try {
                PreviewManagerIIAppBinding.manager()
            } catch (_: IllegalStateException) {
                null
            }
        } else {
            null
        }
        runF2StartTransition(
            rollback = {
                restorePriorAppBindingIfSessionUnchanged(
                    previousUserId,
                    previousChannel,
                    bindingManager,
                    previousAppCallback,
                    previousInvalidPacketSizeTimeout,
                )
            },
        ) {
            if (bindingManager != null) {
                PreviewManagerIIAppBinding.suspendForUsbTransition(bindingManager)
            }
            OfficialF2MeasurementCoordinator.resetLifecycle()
            val closeResult = helper.closeSession()
            if (closeResult.closeOutcome == F2SessionCloseOutcome.STREAM_PRESERVED &&
                bindingManager != null && previousAppCallback != null
            ) {
                restorePriorAppBinding(
                    bindingManager,
                    previousAppCallback,
                    previousInvalidPacketSizeTimeout,
                )
                PreviewManagerIIAppBinding.retainManagerForTerminalCloseRetry(bindingManager)
                return@runF2StartTransition closeResult.copy(
                    summary =
                        "${closeResult.summary}; terminal_app_binding_restore=exact_prior_owner " +
                            "native_stream_preserved=true",
                )
            }

            activeAppCallback = null
            activeInvalidPacketSizeTimeout = null
            if (bindingManager != null) {
                PreviewManagerIIAppBinding.releaseManagerFromTerminalCloseRetry(bindingManager)
                PreviewManagerIIAppBinding.unbind(bindingManager)
            }
            closeResult.copy(
                summary =
                    "${closeResult.summary}; terminal_app_binding_committed=true " +
                        "close_outcome=${closeResult.closeOutcome.name}",
            )
        }
    }

    /**
     * Closes the current lifecycle before a caller attempts a fresh USB open.
     *
     * Callers must treat [F2SessionCloseOutcome.STREAM_PRESERVED] as a hard block:
     * closeSession() has restored the exact prior app binding and the existing native
     * owner must not be replaced.
     */
    @Synchronized
    fun closeSessionForFreshOpen(reason: String): F2StageResult = synchronized(lifecycleLock) {
        val result = closeSession()
        result.copy(
            summary =
                "${result.summary}; fresh_open_cleanup_reason=$reason " +
                    "fresh_open_blocked=${result.closeOutcome == F2SessionCloseOutcome.STREAM_PRESERVED}",
        )
    }

    private fun stopForTransition(
        context: Context,
        streamingNew: Boolean,
        previewManager: PreviewManagerII? = null,
    ): F2StopTransition {
        val activeChannelBeforeStop = helper.activeChannel()
        val activeUserIdBeforeStop = helper.activeUserId()
        val previousAppCallback = activeAppCallback
        val previousInvalidPacketSizeTimeout = activeInvalidPacketSizeTimeout
        val bindingManager = previewManager ?: if (previousAppCallback != null) {
            try {
                PreviewManagerIIAppBinding.manager()
            } catch (_: IllegalStateException) {
                null
            }
        } else {
            null
        }
        return runF2StartTransition(
            rollback = {
                restorePriorAppBindingIfSessionUnchanged(
                    activeUserIdBeforeStop,
                    activeChannelBeforeStop,
                    bindingManager,
                    previousAppCallback,
                    previousInvalidPacketSizeTimeout,
                )
            },
        ) {
            if (bindingManager != null) {
                PreviewManagerIIAppBinding.suspendForUsbTransition(bindingManager)
            }
            if (activeChannelBeforeStop != -1) {
                OfficialF2MeasurementCoordinator.resetLifecycle()
            }
            val stopResult = helper.stopStreamPreview(context, streamingNew)
            val restoredPriorOwner = activeChannelBeforeStop != -1 &&
                !stopResult.ok &&
                restorePriorAppBindingIfSessionUnchanged(
                    activeUserIdBeforeStop,
                    activeChannelBeforeStop,
                    bindingManager,
                    previousAppCallback,
                    previousInvalidPacketSizeTimeout,
                )
            if (!restoredPriorOwner) {
                activeAppCallback = null
                activeInvalidPacketSizeTimeout = null
            }
            F2StopTransition(activeChannelBeforeStop, stopResult)
        }
    }

    private fun restorePriorAppBinding(
        previewManager: PreviewManagerII,
        callback: F2StreamCallback,
        invalidPacketSizeTimeout: ((packetSize: Int, elapsedMs: Long) -> Unit)?,
    ) {
        setInvalidPacketSizeTimeoutCallback(previewManager, invalidPacketSizeTimeout)
        PreviewManagerIIAppBinding.bind(previewManager, callback)
        activeAppCallback = callback
        activeInvalidPacketSizeTimeout = invalidPacketSizeTimeout
    }

    private fun restorePriorAppBindingIfSessionUnchanged(
        previousUserId: Int,
        previousChannel: Int,
        previousManager: PreviewManagerII?,
        previousAppCallback: F2StreamCallback?,
        previousInvalidPacketSizeTimeout: ((packetSize: Int, elapsedMs: Long) -> Unit)?,
    ): Boolean {
        if (previousChannel == -1 ||
            helper.activeUserId() != previousUserId ||
            helper.activeChannel() != previousChannel ||
            previousManager == null ||
            previousAppCallback == null
        ) {
            return false
        }
        restorePriorAppBinding(
            previousManager,
            previousAppCallback,
            previousInvalidPacketSizeTimeout,
        )
        return true
    }

    private fun rollbackPreparedAppStart(previewManager: PreviewManagerII) {
        activeAppCallback = null
        activeInvalidPacketSizeTimeout = null
        PreviewManagerIIAppBinding.suspendForUsbTransition(previewManager)
    }

    private fun setInvalidPacketSizeTimeoutCallback(
        previewManager: PreviewManagerII,
        handler: ((packetSize: Int, elapsedMs: Long) -> Unit)?,
    ) {
        previewManager.setInvalidPacketSizeTimeoutCallback(
            handler?.let {
                java.util.function.BiConsumer { packetSize, elapsedMs ->
                    it(packetSize, elapsedMs)
                }
            },
        )
    }

    companion object {
        @JvmField
        val INSTANCE: F2UsbModuleApi = F2UsbModuleApi()

        @JvmStatic
        internal fun synchronizeRuntimeAfterOpen(result: F2OpenResult): F2OpenResult {
            if (!result.ok) return result
            val resolution = result.profileResolution
            if (resolution?.isResolved != true) {
                return result.copy(
                    stageReport = "${result.stageReport}; runtimeProfile=not_applied reason=${resolution?.reason ?: "profile_missing"}",
                )
            }
            val previewManager = try {
                PreviewManagerIIAppBinding.manager()
            } catch (_: IllegalStateException) {
                null
            }
            if (!F2RuntimeProfile.apply(resolution, result.systemDeviceInfo)) {
                return result.copy(
                    ok = false,
                    reason = "runtime_profile_activation_failed ${resolution.reason}",
                    stageReport = "${result.stageReport}; runtimeProfile=activation_failed; previewProcessor=not_refreshed",
                )
            }

            val processorState = if (previewManager == null) {
                "pending_lifecycle_install"
            } else if (previewManager.refreshF2ProcessorFromRuntimeProfile()) {
                "refreshed"
            } else {
                "not_initialized"
            }
            return if (processorState == "not_initialized") {
                result.copy(
                    ok = false,
                    reason = "runtime_profile_activated_but_preview_processor_unavailable",
                    stageReport = "${result.stageReport}; runtimeProfile=applied; previewProcessor=$processorState",
                )
            } else {
                result.copy(
                    stageReport = "${result.stageReport}; runtimeProfile=applied; previewProcessor=$processorState",
                )
            }
        }

        fun resolveStartConfig(
            resolution: HikmicroF2ProfileResolution?,
            streamingNewOverride: Boolean? = null,
            frameRateOverride: Int? = null,
            videoCodingTypeOverride: Int? = null,
            previewSizeOverride: Size? = null,
            previewSizeValueOverride: HikmicroF2Size? = null,
        ): F2ProfileStartConfigResult {
            val profile = resolution?.profile
                ?: return F2ProfileStartConfigResult(
                    ok = false,
                    reason = "profile_unresolved ${resolution?.reason ?: "system_device_info_not_read"}",
                    profileResolution = resolution,
                )
            val mismatches = buildList {
                if (streamingNewOverride != null && streamingNewOverride != profile.streamingNew) {
                    add("streamingNew=$streamingNewOverride expected=${profile.streamingNew}")
                }
                if (frameRateOverride != null && frameRateOverride != profile.fps) {
                    add("frameRate=$frameRateOverride expected=${profile.fps}")
                }
                if (videoCodingTypeOverride != null && videoCodingTypeOverride != profile.thermalCoding) {
                    add("videoCodingType=$videoCodingTypeOverride expected=${profile.thermalCoding}")
                }
                previewSizeOverride?.let {
                    if (it.width != profile.previewSize.width || it.height != profile.previewSize.height) {
                        add("previewSize=${it.width}x${it.height} expected=${profile.previewSize}")
                    }
                }
                previewSizeValueOverride?.let {
                    if (it != profile.previewSize) {
                        add("previewSizeValue=$it expected=${profile.previewSize}")
                    }
                }
            }
            if (mismatches.isNotEmpty()) {
                return F2ProfileStartConfigResult(
                    ok = false,
                    reason =
                        "profile_override_mismatch profile=${profile.officialClassName} " +
                            mismatches.joinToString(separator = ", "),
                    profileResolution = resolution,
                )
            }
            val purePreviewSize = previewSizeValueOverride
                ?: previewSizeOverride?.let { HikmicroF2Size(it.width, it.height) }
                ?: profile.previewSize
            return F2ProfileStartConfigResult(
                ok = true,
                reason = "profile_resolved ${resolution.reason}",
                profileResolution = resolution,
                config = F2ProfileStartConfig(
                    previewSize = previewSizeOverride ?: Size(purePreviewSize.width, purePreviewSize.height),
                    previewSizeValue = purePreviewSize,
                    frameRate = frameRateOverride ?: profile.fps,
                    videoCodingType = videoCodingTypeOverride ?: profile.thermalCoding,
                    streamingNew = streamingNewOverride ?: profile.streamingNew,
                    allowedPacketSizes = profile.allowedPacketSizes,
                    profileClass = profile.officialClassName,
                ),
            )
        }
    }
}

private data class F2StopTransition(
    val activeChannelBeforeStop: Int,
    val stopResult: F2StageResult,
)

internal fun <T> runF2StartTransition(
    rollback: () -> Unit,
    start: () -> T,
): T {
    return try {
        start()
    } catch (error: RuntimeException) {
        try {
            rollback()
        } catch (rollbackError: RuntimeException) {
            error.addSuppressed(rollbackError)
        } catch (rollbackError: LinkageError) {
            error.addSuppressed(rollbackError)
        }
        throw error
    } catch (error: LinkageError) {
        try {
            rollback()
        } catch (rollbackError: RuntimeException) {
            error.addSuppressed(rollbackError)
        } catch (rollbackError: LinkageError) {
            error.addSuppressed(rollbackError)
        }
        throw error
    }
}

internal fun replacementStartBlockedResult(
    activeChannelBeforeStop: Int,
    stopResult: F2StageResult,
    startPath: String,
    stageReport: String,
    profileResolution: HikmicroF2ProfileResolution?,
): F2StartResult? {
    if (activeChannelBeforeStop == -1 || stopResult.ok) return null
    val reason =
        "replacement_start_blocked existing_active_channel_stop_failed channel=$activeChannelBeforeStop path=$startPath"
    return F2StartResult(
        ok = false,
        waitingForFrame = false,
        channel = activeChannelBeforeStop,
        reason = reason,
        stageReport = "$stageReport; replacementStart=blocked activeChannelBeforeStop=$activeChannelBeforeStop stopOk=${stopResult.ok} stopSummary=${stopResult.summary}; USB_StartStreamCallback=not_run startPath=$startPath",
        attemptDiagnostics = listOf(
            F2StreamAttemptDiagnostic(
                startMode = startPath,
                resetMode = "stop_existing_active_channel",
                startStatus = "blocked_existing_channel_stop_failed",
                channel = activeChannelBeforeStop,
                startPath = startPath,
                profileClass = profileResolution?.profile?.officialClassName.orEmpty(),
                profileModuleId = profileResolution?.moduleId.orEmpty(),
                profileFirmwareDate = profileResolution?.firmwareDate ?: -1,
                profileAllowedSizes = profileResolution?.profile?.allowedPacketSizes.orEmpty(),
            ),
        ),
        profileResolution = profileResolution,
    )
}

data class F2ProfileStartConfig(
    val previewSize: Size,
    val previewSizeValue: HikmicroF2Size,
    val frameRate: Int,
    val videoCodingType: Int,
    val streamingNew: Boolean,
    val allowedPacketSizes: Set<Int>,
    val profileClass: String,
)

data class F2ProfileStartConfigResult(
    val ok: Boolean,
    val reason: String,
    val profileResolution: HikmicroF2ProfileResolution?,
    val config: F2ProfileStartConfig? = null,
) {
    fun toStartResult(stageReport: String): F2StartResult = F2StartResult(
        ok = false,
        waitingForFrame = false,
        channel = -1,
        reason = reason,
        stageReport = "$stageReport; profile_authority_rejected reason=$reason; USB_SET_VIDEO_PARAM=not_run; USB_StartStreamCallback=not_run",
        profileResolution = profileResolution,
    )
}
