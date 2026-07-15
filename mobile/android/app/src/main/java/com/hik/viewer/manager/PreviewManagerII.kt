package com.hik.viewer.manager

import android.graphics.Bitmap
import android.util.Size
import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.USB_FRAME_INFO
import com.hcusbsdk.jna.USB_FRAME_INFO as JnaUSB_FRAME_INFO
import com.hik.f2module.F2StreamFrame
import com.hik.viewercommon.data.bean.PreviewInfoDataBean
import com.hik.viewercommon.data.bean.PreviewStreamInfo
import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback
import com.sun.jna.Pointer
import g3.d as G3DProcessor
import java.util.Arrays
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import kotlin.math.min

private const val MAX_F2_FRAME_COPY_BYTES = 10 * 1024 * 1024
private const val F2_CONSUMER_PERIOD_MS = 20L
private const val OFFICIAL_INVALID_PACKET_ERROR_DELAY_MS = 40_000L

/**
 * Official-package-compatible PreviewManagerII F2 callback layer.
 *
 * The production callback now follows the extracted Viewer path:
 * USB_FRAME_INFO.dwBufSize/pBuf -> profile packet-size gate -> g3.d/g3.e
 * PreviewStreamInfo -> off/normal buffering -> preview frame dispatch. App code
 * may adapt the official PreviewStreamInfo after this boundary only.
 */
class PreviewManagerII private constructor() {
    private val lifecycleLock = Any()
    private var frameCounter: Long = 0L
    private var invalidPacketStartMs: Long = 0L
    private var streamClosed: Boolean = false
    private var scheduler: ScheduledExecutorService? = null
    private var callbackExecutor: ExecutorService? = Executors.newSingleThreadExecutor()
    private var offlineSlot: BufferedF2Packet? = null
    private var normalSlot: BufferedF2Packet? = null
    private var lastNormalContentHash: Int = 0
    private var noChangeCounter: Int = 0
    private var activeOnFrame: ((F2StreamFrame) -> Unit)? = null
    private var latestProcessedFrame: OfficialProcessedF2Frame? = null
    private var latestOfficialOfflinePreviewInfo: PreviewInfoDataBean? = null
    @Volatile
    internal var latestOfficialOsdBgCallbackBean: com.hik.viewercommon.data.bean.OsdBgCallbackBean? = null
    @Volatile
    internal var latestExecutedOfflineCallback: Pair<PreviewInfoDataBean, Int>? = null

    fun createF2ModuleStreamCallback(
        allowedPacketSizes: Set<Int>,
        streamingNew: Boolean = false,
        invalidPacketErrorDelayMs: Long = OFFICIAL_INVALID_PACKET_ERROR_DELAY_MS,
        onInvalidPacketSizeTimeout: ((packetSize: Int, elapsedMs: Long) -> Unit)? = null,
        onFrame: (F2StreamFrame) -> Unit,
    ): F2ModuleStreamCallback {
        synchronized(lifecycleLock) {
            activeOnFrame = onFrame
            streamClosed = false
            clearSlotsLocked()
            latestProcessedFrame = null
            latestOfficialOfflinePreviewInfo = null
            if (callbackExecutor?.isShutdown != false) callbackExecutor = Executors.newSingleThreadExecutor()
            startConsumerLocked()
        }
        val officialF2Callback = OfficialF2StreamCallback(
            allowedPacketSizes = allowedPacketSizes,
            streamingNew = streamingNew,
            invalidPacketErrorDelayMs = invalidPacketErrorDelayMs,
            onInvalidPacketSizeTimeout = onInvalidPacketSizeTimeout,
        )
        return F2ModuleStreamCallback(null, officialF2Callback)
    }

    fun latestOfficialProcessedFrame(frameCounter: Long): OfficialProcessedF2Frame? = synchronized(lifecycleLock) {
        latestProcessedFrame?.takeIf { it.frameCounter == frameCounter }
    }

    /** Hands the official g3 NV12 output through the recovered GYUV/NV21 bitmap path. */
    fun renderOfficialNv12Preview(nv12: ByteArray, width: Int, height: Int): Bitmap {
        require(width > 0 && height > 0)
        require(nv12.size >= width * height * 3 / 2)
        val nv21 = k3.a.a.g(nv12, Size(width, height))
        return k3.a.a.a(nv21, width, height)
    }

    fun closePreviewCallback() {
        synchronized(lifecycleLock) {
            streamClosed = true
            clearSlotsLocked()
            latestProcessedFrame = null
            latestOfficialOfflinePreviewInfo = null
            cleanupProcessorsLocked()
            stopConsumerLocked()
            stopCallbackExecutorLocked()
        }
    }

    fun openPreviewCallback() {
        synchronized(lifecycleLock) {
            streamClosed = false
            clearSlotsLocked()
            latestProcessedFrame = null
            latestOfficialOfflinePreviewInfo = null
            if (callbackExecutor?.isShutdown != false) callbackExecutor = Executors.newSingleThreadExecutor()
            if (activeOnFrame != null) startConsumerLocked()
        }
    }

    private fun startConsumerLocked() {
        if (scheduler?.isShutdown == false) return
        stopConsumerLocked()
        scheduler = Executors.newSingleThreadScheduledExecutor()
        scheduler?.scheduleAtFixedRate(
            K2.e(this),
            0L,
            F2_CONSUMER_PERIOD_MS,
            TimeUnit.MILLISECONDS,
        )
    }

    private fun stopConsumerLocked() {
        scheduler?.shutdownNow()
        scheduler = null
    }

    private fun clearSlotsLocked() {
        offlineSlot = null
        normalSlot = null
        lastNormalContentHash = 0
        noChangeCounter = 0
    }

    internal fun consumeBufferedFrame() {
        val packetToProcess: BufferedF2Packet
        val onFrame: (F2StreamFrame) -> Unit
        synchronized(lifecycleLock) {
            if (streamClosed) return
            onFrame = activeOnFrame ?: return
            val offlinePacket = offlineSlot
            if (offlinePacket != null) {
                offlineSlot = null
                packetToProcess = offlinePacket
            } else {
                val normalPacket = normalSlot ?: return
                val contentHash = Arrays.hashCode(normalPacket.bytes)
                if (contentHash == lastNormalContentHash) {
                    noChangeCounter += 1
                    if (noChangeCounter % 100 == 0) {
                        println("PreviewManager: 超过2秒（100次）没有更新。")
                    }
                    return
                }
                lastNormalContentHash = contentHash
                noChangeCounter = 0
                packetToProcess = normalPacket
            }
        }

        // Official PreviewManagerII$d only copies/gates into r0/s0. Parsing is
        // deliberately performed here by the K2.e 20 ms consumer via G(byte[]).
        val processedFrame = processOfficialPacket(packetToProcess)
        synchronized(lifecycleLock) {
            if (streamClosed) return
            latestProcessedFrame = processedFrame
        }
        onFrame(packetToProcess.toStreamFrame())
    }

    private fun processOfficialPacket(packet: BufferedF2Packet): OfficialProcessedF2Frame {
        val processor = packet.processor
        activeProcessor = processor
        installOfficialProcessorCallbacks(processor)
        val previewStreamInfo = processor.d(packet.bytes)
        return OfficialProcessedF2Frame(
            frameCounter = packet.frameCounter,
            packetSize = packet.bytes.size,
            width = packet.packetWidth,
            height = packet.packetHeight,
            previewStreamInfo = previewStreamInfo,
            isOffStreamInfo = packet.isOffStreamInfo,
            processorBucket = if (packet.streamingNew) "g3.e" else "g3.d",
        )
    }

    private fun installOfficialProcessorCallbacks(processor: g3.a) {
        processor.j(
            OfficialFreezeCallback(this),
            K2.f(this),
            OfficialMetadataCallback(this),
            OfficialOverlayCallback(this),
            K2.g(this),
        )
        if (processor is G3DProcessor) {
            processor.o(K2.h(this))
        }
    }

    private fun cleanupProcessorsLocked() {
        activeProcessor?.k()
        activeProcessor = null
    }

    private fun stopCallbackExecutorLocked() {
        callbackExecutor?.shutdownNow()
        callbackExecutor = null
    }

    private var activeProcessor: g3.a? = null

    private inner class OfficialF2StreamCallback(
        private val allowedPacketSizes: Set<Int>,
        private val streamingNew: Boolean,
        private val invalidPacketErrorDelayMs: Long,
        private val onInvalidPacketSizeTimeout: ((packetSize: Int, elapsedMs: Long) -> Unit)?,
    ) : FStreamCallBack {
        private val processor: g3.a = g3.b.a.a(Z2.a.a.p().k(), streamingNew)

        override fun fStreamCallback(userId: Int, frameInfo: USB_FRAME_INFO?) {
            synchronized(lifecycleLock) {
                if (streamClosed || frameInfo == null) return
                frameCounter += 1L
                if (invalidPacketStartMs == 0L) {
                    invalidPacketStartMs = System.currentTimeMillis()
                }
                val copiedSize = frameInfo.dwBufSize
                val copied = Arrays.copyOf(frameInfo.pBuf, copiedSize)
                Z2.g.a.A0(copiedSize)
                if (copiedSize !in allowedPacketSizes) {
                    onUnsupportedPacketSizeLocked(copiedSize)
                    return
                }
                val effectiveFrameCounter = frameInfo.nFrameNum.toLong().takeIf { it > 0 } ?: frameCounter
                val dimensions = officialF2PacketDimensions(copiedSize)
                val bufferedPacket = BufferedF2Packet(
                    callbackUserId = userId,
                    frameCounter = effectiveFrameCounter,
                    width = frameInfo.dwWidth.takeIf { it > 0 } ?: dimensions.first,
                    height = frameInfo.dwHeight.takeIf { it > 0 } ?: dimensions.second,
                    frameType = frameInfo.dwFrameType,
                    dataType = frameInfo.dwDataType,
                    streamType = frameInfo.dwStreamType,
                    bytes = copied,
                    packetWidth = dimensions.first,
                    packetHeight = dimensions.second,
                    isOffStreamInfo = isOfficialOfflineMailboxFrame(copiedSize),
                    streamingNew = streamingNew,
                    processor = processor,
                )
                if (bufferedPacket.isOffStreamInfo) {
                    offlineSlot = bufferedPacket
                } else {
                    normalSlot = bufferedPacket
                }
            }
        }

        private fun onUnsupportedPacketSizeLocked(packetSize: Int) {
            val elapsedMs = System.currentTimeMillis() - invalidPacketStartMs
            if (elapsedMs > invalidPacketErrorDelayMs) {
                onInvalidPacketSizeTimeout?.invoke(packetSize, elapsedMs)
                invalidPacketStartMs = 0L
            }
        }
    }

    private data class BufferedF2Packet(
        val callbackUserId: Int,
        val frameCounter: Long,
        val width: Int,
        val height: Int,
        val frameType: Int,
        val dataType: Int,
        val streamType: Int,
        val bytes: ByteArray,
        val packetWidth: Int,
        val packetHeight: Int,
        val isOffStreamInfo: Boolean,
        val streamingNew: Boolean,
        val processor: g3.a,
    ) {
        fun toStreamFrame(): F2StreamFrame = F2StreamFrame(
            callbackUserId = callbackUserId,
            frameCounter = frameCounter,
            width = width,
            height = height,
            frameType = frameType,
            dataType = dataType,
            streamType = streamType,
            bytes = bytes,
        )
    }

    private fun isOfficialOfflineMailboxFrame(packetSize: Int): Boolean =
        Z2.a.a.p().k() == 12 && packetSize in officialF2Coding12OfflinePacketSizes

    private class OfficialFreezeCallback(private val manager: PreviewManagerII) : (Boolean) -> Unit {
        override fun invoke(value: Boolean) { manager.lastFreezeState = value }
    }

    private class OfficialMetadataCallback(private val manager: PreviewManagerII) : (Any?) -> Unit {
        override fun invoke(value: Any?) { manager.latestOfficialMetadata = value }
    }

    private class OfficialOverlayCallback(private val manager: PreviewManagerII) : (Any?, Any?, Any?, Any?, Any?) -> Unit {
        override fun invoke(p1: Any?, p2: Any?, p3: Any?, p4: Any?, p5: Any?) {
            manager.latestOfficialOverlay = listOf(p1, p2, p3, p4, p5)
        }
    }

    @Volatile
    private var lastFreezeState: Boolean? = null
    @Volatile
    private var latestOfficialMetadata: Any? = null
    @Volatile
    private var latestOfficialOverlay: List<Any?>? = null

    companion object {
        @JvmField
        val INSTANCE: PreviewManagerII = PreviewManagerII()

        @JvmStatic
        fun c(manager: PreviewManagerII, isFreezeData: Boolean) {
            manager.lastFreezeState = isFreezeData
        }

        @JvmStatic
        fun d(manager: PreviewManagerII, osdBgCallbackBean: com.hik.viewercommon.data.bean.OsdBgCallbackBean) {
            manager.latestOfficialOsdBgCallbackBean = osdBgCallbackBean
        }

        @JvmStatic
        fun f(manager: PreviewManagerII, previewInfoData: PreviewInfoDataBean) {
            manager.latestOfficialOfflinePreviewInfo = previewInfoData
            val frameNumStamp = d3.b.a.c(previewInfoData.getByteArrYuvAppendData())
            if (Z2.a.a.p().k() == 12) {
                z3.c.a.r(frameNumStamp)
                manager.callbackExecutor?.execute(K2.i(manager, previewInfoData, frameNumStamp))
            }
        }

        @JvmStatic
        fun e(manager: PreviewManagerII, previewInfoData: PreviewInfoDataBean, frameNumStamp: Int) {
            manager.latestExecutedOfflineCallback = previewInfoData to frameNumStamp
        }

        @JvmStatic
        fun g(manager: PreviewManagerII) {
            manager.consumeBufferedFrame()
        }

        @JvmField
        val officialF2KnownPacketSizes: Set<Int> = setOf(
            41_160,
            61_384,
            101_320,
            183_496,
            193_480,
            203_720,
            400_584,
        )

        @JvmField
        val officialF2Coding12OfflinePacketSizes: Set<Int> = setOf(
            41_160,
            183_496,
            400_584,
        )
    }
}

data class OfficialProcessedF2Frame(
    val frameCounter: Long,
    val packetSize: Int,
    val width: Int,
    val height: Int,
    val previewStreamInfo: PreviewStreamInfo,
    val isOffStreamInfo: Boolean,
    val processorBucket: String,
)

private fun officialF2PacketDimensions(packetSize: Int): Pair<Int, Int> = when (packetSize) {
    41_160, 61_384 -> 96 to 96
    183_496, 203_720, 101_320 -> 256 to 192
    400_584, 193_480 -> 384 to 288
    else -> 0 to 0
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
