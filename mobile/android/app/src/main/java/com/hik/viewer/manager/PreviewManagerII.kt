package com.hik.viewer.manager

import android.graphics.Bitmap
import android.util.Size
import android.view.SurfaceView
import android.view.View
import android.widget.TextView
import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.USB_FRAME_INFO
import com.hcusbsdk.jna.USB_FRAME_INFO as JnaUSB_FRAME_INFO
import com.hik.f2module.F2StreamFrame
import com.hik.viewer.bean.DiagnoseBean
import com.hik.viewercommon.data.bean.PreviewInfoDataBean
import com.hik.viewercommon.data.bean.PreviewStreamInfo
import com.hik.viewercommon.data.bean.SceneModeBean
import com.hik.viewercommon.data.bean.UsbModuleType
import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback
import com.sun.jna.Pointer
import g3.d as G3DProcessor
import hik.common.yyrj.uicommon.widget.FloatTextureView
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
    private var E: V2.f? = null
    private var G: View? = null
    private var H: SurfaceView? = null
    private var I: TextView? = null
    private var J: FloatTextureView? = null
    private var O: SceneModeBean? = null
    private var P: Bitmap? = null
    private var Q: ((Boolean) -> Unit)? = null
    private var T: ((Int) -> Unit)? = null
    private var U: Int = 0
    private var V: Boolean = false
    private var X: ((Boolean) -> Unit)? = null
    private var Z: (() -> Unit)? = null
    private var m: Size = Size(0, 0)
    private var n: Size = Size(0, 0)
    private var t: Size = Size(0, 0)
    private var w0: List<*>? = null
    private var diagnoseFrameCount: Int = 0
    private var diagnoseFrames: Boolean = false
    private var h0: ((Any?, Any?, Any?, Any?, Any?) -> Unit)? = null
    private var z: ((DiagnoseBean) -> Unit)? = null
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

    /** Official eight-parameter PreviewManagerII.l0 surface from Viewer 2.6.0. */
    fun l0(viewerSurfaceView: SurfaceView) {
        l0(null, viewerSurfaceView, null, null, null, null, null, null)
    }

    fun l0(
        viewerRootView: View?,
        viewerSurfaceView: SurfaceView,
        viewerErrorText: TextView?,
        visibleLightView: FloatTextureView?,
        sceneModeBean: SceneModeBean?,
        freezeCallback: ((Boolean) -> Unit)?,
        overlayAvailabilityCallback: ((Boolean) -> Unit)?,
        frameNumberCallback: ((Int) -> Unit)?,
    ) {
        this.G = viewerRootView
        this.H = viewerSurfaceView
        this.J = visibleLightView
        this.I = viewerErrorText
        this.X = freezeCallback
        this.O = sceneModeBean
        this.Q = overlayAvailabilityCallback
        this.T = frameNumberCallback

        val moduleType = Z2.g.a.a(true)
        if (moduleType === UsbModuleType.F2) {
            m = Z2.a.a.p().c()
            n = Z2.a.a.p().c()
            t = Size(m.width, m.height)
            activeProcessor = g3.b.a.a(Z2.a.a.p().k(), Z2.a.a.t())
        } else if (moduleType === UsbModuleType.F1) {
            m = Size(120, 160)
            n = Size(120, 160)
            t = Size(120, 160)
            setOfficialF1YuvSize(t)
        }

        U = Z2.g.a.w(Z2.g.a.U().getSerialNumber())
        val showSize = Z2.g.a.E()
        configureVisibleLightView()
        bindOfficialRenderer(
            viewerSurfaceView = viewerSurfaceView,
            useM4 = l2.k.a("useM4", true),
            isF2Module = moduleType === UsbModuleType.F2,
            useNonF1Processing = Z2.a.a.t(),
        )
        E?.let { activeRenderer ->
            if (shouldApplyRendererShowSize()) activeRenderer.i(showSize)
            activeRenderer.b(OfficialPlaybackListener())
        }
    }

    internal fun bindOfficialRenderer(
        viewerSurfaceView: SurfaceView,
        useM4: Boolean,
        isF2Module: Boolean,
        useNonF1Processing: Boolean,
    ): V2.f {
        val factory: X2.b = if (useM4) X2.c() else X2.a()
        val selected = when {
            !isF2Module -> factory.a(viewerSurfaceView)
            useNonF1Processing -> factory.c(viewerSurfaceView)
            else -> factory.b(viewerSurfaceView)
        }
        synchronized(lifecycleLock) {
            this.H = viewerSurfaceView
            E = selected
        }
        return selected
    }

    fun i1(picSize: Size): ByteArray? = synchronized(lifecycleLock) { E?.e(picSize) }

    fun W(picSize: Size): com.hik.library.player.d? = synchronized(lifecycleLock) { E?.f(picSize) }

    fun D0(callback: ((DiagnoseBean) -> Unit)?) {
        z = callback
    }

    fun G0(callback: (() -> Unit)?) {
        Z = callback
    }

    fun J0(callback: ((Any?, Any?, Any?, Any?, Any?) -> Unit)?) {
        h0 = callback
    }

    fun x0(enabled: Boolean) {
        diagnoseFrames = enabled
    }

    /** Compatibility validator only; rendering is exclusively owned by V2.f. */
    @Deprecated("Bind a SurfaceView through l0; PreviewManagerII no longer returns bitmaps")
    fun renderOfficialNv12Preview(nv12: ByteArray, width: Int, height: Int) {
        require(width > 0 && height > 0)
        require(nv12.size >= width * height * 3 / 2)
    }

    fun closePreviewCallback() {
        synchronized(lifecycleLock) {
            streamClosed = true
            cleanupRendererLocked()
            clearSlotsLocked()
            latestProcessedFrame = null
            latestOfficialOfflinePreviewInfo = null
            cleanupProcessorsLocked()
            stopConsumerLocked()
            stopCallbackExecutorLocked()
            G = null
            H = null
            I = null
            J = null
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
        handOffOfficialFrame(previewStreamInfo, packet)
        return OfficialProcessedF2Frame(
            frameCounter = packet.frameCounter,
            packetSize = packet.bytes.size,
            width = packet.packetWidth,
            height = packet.packetHeight,
            previewStreamInfo = previewStreamInfo,
            isOffStreamInfo = packet.isOffStreamInfo,
            processorBucket = processor.javaClass.name,
        )
    }

    private fun handOffOfficialFrame(previewStreamInfo: PreviewStreamInfo, packet: BufferedF2Packet) {
        val previewInfo = previewStreamInfo.getPreviewInfoData()
        val nv12Data = previewInfo.getByteArrDst()
        if (nv12Data.isEmpty()) return

        previewStreamInfo.getIStreamInfo()?.let(Z2.g.a::B0)
        val frameNumStamp = d3.b.a.c(previewInfo.getByteArrYuvAppendData())
        val packetSize = officialProcessedF2PacketDimensions(packet.bytes.size)
        val sourceSize = m.takeIf { it.width > 0 && it.height > 0 } ?: packetSize
        val outputSize = t.takeIf { it.width > 0 && it.height > 0 } ?: sourceSize
        if (sourceSize.width <= 0 || sourceSize.height <= 0) return
        val transformedNv12: ByteArray
        val transformedSize: Size
        if (Z2.a.a.t()) {
            z3.c.a.w(U)
            z3.c.a.x(V)
            z3.c.a.p(V)
            transformedNv12 = nv12Data
            transformedSize = outputSize
        } else {
            transformedNv12 = k3.a.a.e(nv12Data, sourceSize, outputSize, U, V)
            if (U == 90 || U == 270) {
                t = Size(outputSize.height, outputSize.width)
            }
            transformedSize = t
        }

        recordOfficialPacket(
            src = previewInfo.getByteArrSrc(),
            dst = transformedNv12,
            head = previewInfo.getByteArrHead(),
            allData = packet.bytes,
        )
        val activeRenderer = synchronized(lifecycleLock) { E }
        if (Z2.a.a.t()) {
            // DEX offsets 0b98-0bbe and 0cba-0ce0 pass a literal null raw argument.
            // F2 private data is published through Z2.g.B0(iStreamInfo) above.
            activeRenderer?.j(null, transformedNv12, transformedSize, frameNumStamp, w0, P)
        } else {
            activeRenderer?.h(null, transformedNv12, transformedSize, frameNumStamp)
        }
        T?.invoke(frameNumStamp)
    }

    private fun installOfficialProcessorCallbacks(processor: g3.a) {
        processor.j(
            X,
            K2.f(this),
            OfficialMetadataCallback(this),
            h0,
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

    private fun cleanupRendererLocked() {
        E?.c()
        E?.release()
        E = null
        X = null
        Z = null
        h0 = null
    }

    private inner class OfficialPlaybackListener : com.hik.library.player.b {
        override fun a() {
            showViewerErrorTip("onSurfaceInvalid")
            z?.invoke(DiagnoseBean())
        }

        override fun b() {
            showViewerErrorTip("onTimeout")
            Z?.invoke()
            z?.invoke(DiagnoseBean())
        }

        override fun onError(message: String) {
            showViewerErrorTip(message)
            z?.invoke(DiagnoseBean())
        }

        override fun onPause() = Unit
        override fun onResume() = Unit
        override fun onStart() {
            if (officialBoolean("u5.B", "a", "d0", false)) Z?.invoke()
        }

        override fun onStop() = Unit
    }

    private fun showViewerErrorTip(error: String?) {
        if (error == null) return
        I?.post { I?.visibility = if (error.isEmpty()) View.GONE else View.VISIBLE }
    }

    private fun configureVisibleLightView() {
        val visibleLight = J ?: return
        val previewRoot = G ?: return
        visibleLight.post {
            val parentSize = Size(previewRoot.width, previewRoot.height)
            val visibleSize = Size(visibleLight.width, visibleLight.height)
            visibleLight.f(Z2.g.a.W(), false, parentSize, visibleSize)
            if (shouldApplyRendererShowSize()) E?.i(parentSize)
            Z2.g.a.M0(parentSize)
        }
    }

    private fun shouldApplyRendererShowSize(): Boolean =
        !officialBoolean("u5.B", "a", "h0", false) &&
            !Z2.g.a.b0() &&
            officialPreviewLogoEnabled()

    private fun officialPreviewLogoEnabled(): Boolean = runCatching {
        val storeClass = Class.forName("hik.common.yyrj.businesscommon.b")
        val companion = storeClass.getField("d").get(null)
        val store = companion.javaClass.getMethod("a").invoke(companion)
        val defaultMethod = storeClass.getDeclaredMethod(
            "x",
            storeClass,
            String::class.java,
            Int::class.javaPrimitiveType,
            Any::class.java,
        )
        defaultMethod.invoke(null, store, null, 1, null) as Boolean
    // Official businesscommon.b.w/x defaults to visible unless the serial is in
    // preview_logo_visible; the class is outside this task's recovered closure.
    }.getOrDefault(true)

    private fun officialBoolean(
        className: String,
        singletonField: String,
        methodName: String,
        officialDefault: Boolean,
    ): Boolean = runCatching {
        val owner = Class.forName(className)
        val singleton = owner.getField(singletonField).get(null)
        owner.getMethod(methodName).invoke(singleton) as Boolean
    }.getOrDefault(officialDefault)

    private fun setOfficialF1YuvSize(size: Size) {
        runCatching {
            val helper = Class.forName("com.hik.f1module.F1UsbModuleHelper")
            val singleton = helper.getField("INSTANCE").get(null)
            helper.getMethod("USB_SetYuvSize", Size::class.java).invoke(singleton, size)
        }
    }

    private fun recordOfficialPacket(src: ByteArray, dst: ByteArray, head: ByteArray, allData: ByteArray) {
        if (frameCounter % 5L != 0L || !diagnoseFrames) return
        diagnoseFrameCount += 1
        z?.invoke(
            DiagnoseBean(
                success = true,
                count = diagnoseFrameCount,
                src = src,
                dst = dst,
                head = head,
                allData = allData,
                srcFormat = if (Z2.a.a.p().k() == 12) "yuy2" else "nv12",
                dstFormat = "nv12",
            ),
        )
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

    private class OfficialMetadataCallback(private val manager: PreviewManagerII) : (Any?) -> Unit {
        override fun invoke(value: Any?) { manager.latestOfficialMetadata = value }
    }

    @Volatile
    private var lastFreezeState: Boolean? = null
    @Volatile
    private var latestOfficialMetadata: Any? = null

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

private fun officialProcessedF2PacketDimensions(packetSize: Int): Size = when (packetSize) {
    41_160, 61_384 -> Size(96, 96)
    183_496, 203_720, 101_320 -> Size(192, 256)
    400_584, 193_480 -> Size(288, 384)
    else -> Size(0, 0)
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
