package com.hik.f2module

import android.content.Context
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.util.Size
import com.hik.viewer.manager.PreviewManagerII
import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback

/** Official-shaped public API boundary for the F2 USB preview lifecycle. */
class F2UsbModuleApi private constructor() {
    private val helper: F2UsbModuleHelper = F2UsbModuleHelper.INSTANCE

    fun openUsbModule(
        context: Context,
        usbManager: UsbManager,
        device: UsbDevice,
        nativeLibraryDir: String,
        maxRetries: Int = 5,
    ): F2OpenResult {
        var retryIndex = 0
        val attemptReports = mutableListOf("F2UsbModuleApi.openUsbModule:start retryIndex=0")
        var last = helper.openUsbDevice(
            context = context,
            usbManager = usbManager,
            device = device,
            nativeLibraryDir = nativeLibraryDir,
        )
        attemptReports += "F2UsbModuleApi.openUsbModule:do retryIndex=$retryIndex success=${last.ok}"
        while (!last.ok && retryIndex + 1 < maxRetries) {
            retryIndex += 1
            try {
                Thread.sleep(retryIndex * 500L)
            } catch (error: InterruptedException) {
                Thread.currentThread().interrupt()
                attemptReports += "F2UsbModuleApi.openUsbModule:sleepInterrupted retryIndex=$retryIndex"
                break
            }
            last = helper.openUsbDevice(
                context = context,
                usbManager = usbManager,
                device = device,
                nativeLibraryDir = nativeLibraryDir,
            )
            attemptReports += "F2UsbModuleApi.openUsbModule:do retryIndex=$retryIndex success=${last.ok}"
        }
        attemptReports += "F2UsbModuleApi.openUsbModule:end retryIndex=$retryIndex success=${last.ok}"
        return last.copy(stageReport = "${attemptReports.joinToString("; ")}; ${last.stageReport}")
    }

    fun startStreamPreview(
        context: Context,
        callback: F2StreamCallback,
        streamingNew: Boolean = true,
    ): F2StartResult {
        val previewCallback = PreviewManagerII.INSTANCE.createF2ModuleStreamCallback { frame ->
            callback.onFrame(frame)
        }
        return startStreamPreview(
            context = context,
            streamCallback = previewCallback,
            streamingNew = streamingNew,
        )
    }

    fun startStreamPreview(
        context: Context,
        streamCallback: F2ModuleStreamCallback,
        streamingNew: Boolean = true,
        frameRate: Int = HIKMICRO_FRAME_RATE,
        videoCodingType: Int = HIKMICRO_THERMAL_VIDEO_CODING_TYPE,
        previewSize: Size = Size(HIKMICRO_PREVIEW_WIDTH, HIKMICRO_PREVIEW_HEIGHT),
    ): F2StartResult {
        helper.stopStreamPreview(context, streamingNew)
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
            size = previewSize,
            frameRate = frameRate,
            videoCodingType = videoCodingType,
            streamType = HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE,
            streamingNew = streamingNew,
        )
    }

    fun startStreamPreviewJNA(
        context: Context,
        streamCallback: F2ModuleStreamCallback,
        streamingNew: Boolean = true,
        frameRate: Int = HIKMICRO_FRAME_RATE,
        videoCodingType: Int = HIKMICRO_THERMAL_VIDEO_CODING_TYPE,
        previewSize: Size = Size(HIKMICRO_PREVIEW_WIDTH, HIKMICRO_PREVIEW_HEIGHT),
    ): F2StartResult {
        helper.stopStreamPreview(context, streamingNew)
        val fStreamCallBackJNA = streamCallback.getFStreamCallBackJNA()
            ?: return F2StartResult(
                ok = false,
                waitingForFrame = false,
                channel = -1,
                reason = "F2ModuleStreamCallback.getFStreamCallBackJNA returned null",
                stageReport = "F2UsbModuleApi.startStreamPreviewJNA callback=null",
            )
        return helper.startStreamPreviewJNA(
            fStreamCallBack = fStreamCallBackJNA,
            size = previewSize,
            frameRate = frameRate,
            videoCodingType = videoCodingType,
            streamType = HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE,
            streamingNew = streamingNew,
        )
    }

    fun stopStreamPreview(context: Context, streamingNew: Boolean = true): F2StageResult =
        helper.stopStreamPreview(context, streamingNew)

    companion object {
        @JvmField
        val INSTANCE: F2UsbModuleApi = F2UsbModuleApi()
    }
}
