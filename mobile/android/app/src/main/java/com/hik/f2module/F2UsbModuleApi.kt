package com.hik.f2module

import android.content.Context
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.util.Size
import com.hik.viewer.manager.PreviewManagerII
import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolution
import kr.auto.titration.mobile.thermal.PreviewManagerIIAppBinding
import kr.auto.titration.mobile.thermal.HikmicroF2Size

/** Public API boundary for the F2 USB preview lifecycle. */
class F2UsbModuleApi private constructor() {
    private val helper: F2UsbModuleHelper = F2UsbModuleHelper.INSTANCE
    private val lifecycleLock = Any()

    @Synchronized
    fun openUsbModule(
        context: Context,
        usbManager: UsbManager,
        device: UsbDevice,
        nativeLibraryDir: String,
    ): F2OpenResult = synchronized(lifecycleLock) {
        val result = helper.openUsbDevice(
            context = context,
            usbManager = usbManager,
            device = device,
            nativeLibraryDir = nativeLibraryDir,
        )
        result.copy(
            stageReport = "F2UsbModuleApi.openUsbModule:singleAttempt success=${result.ok}; ${result.stageReport}",
        )
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
        PreviewManagerIIAppBinding.bind(previewManager, callback)
        val previewCallback = F2ModuleStreamCallback(null, previewManager.R())
        startStreamPreviewLocked(
            context = context,
            streamCallback = previewCallback,
            config = config,
        )
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
        helper.stopStreamPreview(context, config.streamingNew)
        val fStreamCallBack = streamCallback.getFStreamCallBack()
            ?: return F2StartResult(
                ok = false,
                waitingForFrame = false,
                channel = -1,
                reason = "F2ModuleStreamCallback.getFStreamCallBack returned null",
                stageReport = "F2UsbModuleApi.startStreamPreview callback=null",
            )
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
        helper.stopStreamPreview(context, config.streamingNew)
        val fStreamCallBackJNA = streamCallback.getFStreamCallBackJNA()
            ?: return@synchronized F2StartResult(
                ok = false,
                waitingForFrame = false,
                channel = -1,
                reason = "F2ModuleStreamCallback.getFStreamCallBackJNA returned null",
                stageReport = "F2UsbModuleApi.startStreamPreviewJNA callback=null",
            )
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
        synchronized(lifecycleLock) { helper.stopStreamPreview(context, streamingNew) }

    companion object {
        @JvmField
        val INSTANCE: F2UsbModuleApi = F2UsbModuleApi()

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
        stageReport = "$stageReport; profile_unresolved ${profileResolution?.reason ?: "system_device_info_not_read"}; USB_SET_VIDEO_PARAM=not_run; USB_StartStreamCallback=not_run",
        profileResolution = profileResolution,
    )
}
