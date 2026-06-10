package com.hik.viewer.manager

import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.USB_FRAME_INFO
import com.hcusbsdk.jna.FStreamCallBack_JNA
import com.hcusbsdk.jna.USB_FRAME_INFO as JnaUSB_FRAME_INFO
import com.hik.f2module.F2StreamFrame
import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback
import com.sun.jna.Pointer
import kotlin.math.min

private const val MAX_F2_FRAME_COPY_BYTES = 10 * 1024 * 1024

/**
 * Minimal official-shaped PreviewManagerII F2 callback layer.
 *
 * The HIKMICRO Viewer PreviewManagerII owns F2 callback objects and passes a
 * F2ModuleStreamCallback into F2UsbModuleApi. Its F2 callback copies
 * USB_FRAME_INFO.dwBufSize bytes from pBuf and keeps the official f3/b-j
 * packet-size family visible to the stream pipeline.
 */
class PreviewManagerII private constructor() {
    private var frameCounter: Long = 0L
    private var streamClosed: Boolean = false

    fun createF2ModuleStreamCallback(onFrame: (F2StreamFrame) -> Unit): F2ModuleStreamCallback {
        val officialF2Callback = OfficialF2StreamCallback(onFrame)
        val jnaCallback = FStreamCallBack_JNA { callbackUserId, framePointer, _ ->
            officialF2Callback.fStreamCallback(callbackUserId, framePointer.toJniFrame())
        }
        return F2ModuleStreamCallback(jnaCallback, officialF2Callback)
    }

    fun closePreviewCallback() {
        streamClosed = true
    }

    fun openPreviewCallback() {
        streamClosed = false
    }

    private inner class OfficialF2StreamCallback(
        private val onFrame: (F2StreamFrame) -> Unit,
    ) : FStreamCallBack {
        override fun fStreamCallback(userId: Int, frameInfo: USB_FRAME_INFO?) {
            synchronized(this@PreviewManagerII) {
                if (streamClosed || frameInfo == null) return
                val copiedSize = frameInfo.dwBufSize
                    .coerceAtLeast(0)
                    .coerceAtMost(frameInfo.pBuf.size)
                    .coerceAtMost(MAX_F2_FRAME_COPY_BYTES)
                if (copiedSize <= 0) return
                val copied = frameInfo.pBuf.copyOf(copiedSize)
                val acceptedByOfficialShape = copiedSize in officialF2AllowedPacketSizes
                frameCounter += 1L
                onFrame(
                    F2StreamFrame(
                        callbackUserId = userId,
                        frameCounter = frameInfo.nFrameNum.toLong().takeIf { it > 0 } ?: frameCounter,
                        width = frameInfo.dwWidth,
                        height = frameInfo.dwHeight,
                        frameType = frameInfo.dwFrameType,
                        dataType = frameInfo.dwDataType,
                        streamType = frameInfo.dwStreamType,
                        bytes = if (acceptedByOfficialShape || copied.isNotEmpty()) copied else ByteArray(0),
                    )
                )
            }
        }
    }

    companion object {
        @JvmField
        val INSTANCE: PreviewManagerII = PreviewManagerII()

        @JvmField
        val officialF2AllowedPacketSizes: Set<Int> = setOf(
            41_160,
            61_384,
            98_304,
            101_320,
            183_496,
            193_480,
            203_720,
            221_184,
            400_584,
        )
    }
}

private fun Pointer?.toJniFrame(): USB_FRAME_INFO? {
    if (this == null || this == Pointer.NULL) return null
    return try {
        val nativeFrame = JnaUSB_FRAME_INFO(this).apply { read() }
        val byteCount = nativeFrame.dwBufSize.coerceIn(0, MAX_F2_FRAME_COPY_BYTES)
        val bytes = if (byteCount > 0) {
            nativeFrame.pBuf?.getByteArray(0, byteCount) ?: ByteArray(0)
        } else {
            ByteArray(0)
        }
        USB_FRAME_INFO().apply {
            nStamp = nativeFrame.nStamp
            dwStreamType = nativeFrame.dwStreamType
            dwWidth = nativeFrame.dwWidth
            dwHeight = nativeFrame.dwHeight
            dwFrameRate = nativeFrame.dwFrameRate
            dwFrameType = nativeFrame.dwFrameType
            dwDataType = nativeFrame.dwDataType
            nFrameNum = nativeFrame.nFrameNum
            pBuf = bytes.copyOf(min(bytes.size, MAX_F2_FRAME_COPY_BYTES))
            dwBufSize = pBuf.size
            byRes = nativeFrame.byRes.copyOf()
        }
    } catch (_: Throwable) {
        null
    }
}
