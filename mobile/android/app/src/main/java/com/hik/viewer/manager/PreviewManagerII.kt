package com.hik.viewer.manager

import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.util.Size
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.widget.TextView
import androidx.fragment.app.Fragment
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.findViewTreeLifecycleOwner
import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.USB_FRAME_INFO
import com.hcusbsdk.jna.USB_FRAME_INFO as JnaUSB_FRAME_INFO
import com.hik.f2module.F2StreamFrame
import com.hik.f1module.hcusbcamerasdk.callback.IStreamCallback
import com.hik.viewer.bean.DiagnoseBean
import com.hik.viewercommon.data.bean.PreviewInfoDataBean
import com.hik.viewercommon.data.bean.PreviewStreamInfo
import com.hik.viewercommon.data.bean.SceneModeBean
import com.hik.viewercommon.data.bean.UsbModuleType
import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback
import com.sun.jna.Pointer
import g3.d as G3DProcessor
import hik.common.yyrj.uicommon.data.ModuleType
import hik.common.yyrj.uicommon.widget.FloatTextureView
import java.io.File
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
class PreviewManagerII(
    private var a: Lifecycle,
    private val b: Boolean,
    private val c: Boolean,
) {
    private val lifecycleLock = Any()
    private val d: Int = 830
    private var frameCounter: Long = 0L
    private var invalidPacketStartMs: Long = 0L
    private var streamClosed: Boolean = false
    private var x0: ScheduledExecutorService? = null
    private var C: ExecutorService? = Executors.newSingleThreadExecutor()
    private var offlineSlot: BufferedF2Packet? = null
    private var normalSlot: BufferedF2Packet? = null
    private var lastNormalContentHash: Int = 0
    private var noChangeCounter: Int = 0
    private var activeOnFrame: ((F2StreamFrame) -> Unit)? = null
    private var latestProcessedFrame: OfficialProcessedF2Frame? = null
    private var latestOfficialOfflinePreviewInfo: PreviewInfoDataBean? = null
    private var E: V2.f? = null
    private var D: g3.a? = null
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
    private var W: Boolean = false
    private var X: ((Boolean) -> Unit)? = null
    private var Y: (() -> Unit)? = null
    private var Z: (() -> Unit)? = null
    private var a0: (() -> Unit)? = null
    private var b0: (() -> Unit)? = null
    private var c0: ((Any?) -> Unit)? = null
    private var d0: (() -> Unit)? = null
    private var e0: (() -> Unit)? = null
    private var f0: ((Any?) -> Unit)? = null
    private var g0: ((Any?, Any?) -> Unit)? = null
    private var p: Size = Size(0, 0)
    private var m: Size = Size(0, 0)
    private var n: Size = Size(0, 0)
    private var t: Size = Size(0, 0)
    private var v: ArrayList<Any?> = ArrayList(10)
    private var F: Boolean = true
    private var L: Boolean = true
    private var w0: List<*>? = null
    private var diagnoseFrameCount: Int = 0
    private var diagnoseFrames: Boolean = false
    private var h0: ((Any?, Any?, Any?, Any?, Any?) -> Unit)? = null
    private var z: ((DiagnoseBean) -> Unit)? = null
    private var B0: IStreamCallback? = null
    private var C0: FStreamCallBack? = null
    private var S: Boolean = true
    private var q0: Boolean = true
    private var m0: Boolean = true
    private var i0: PreviewInfoDataBean = PreviewInfoDataBean()
    private var j0: ByteArray = ByteArray(0)
    private var l0: Boolean = true
    private var l: ByteArray? = null
    private var r0: ByteArray = ByteArray(0)
    private var s0: ByteArray = ByteArray(0)
    private var y0: String = ""
    private var z0: String = ""
    private var A0: ByteArray = ByteArray(0)
    private var q: Float = 1f
    private var r: Int = 0
    private var s: Int = 0
    private lateinit var K: Handler

    private val A = g(this)
    private val B = `defaultLifecycleObserver$1`(this)

    private fun onOfficialSurfaceCreated() {
        E?.start()
    }

    private fun onOfficialSurfaceDestroyed() {
        E?.stop()
    }

    private fun onOfficialLifecycleCreate() {
        if (c) {
            q = 1f
            r = 0
            s = 0
        } else {
            q = l2.k.c("FUSE_VIS_SCALE", 1f)
            r = l2.k.e("FUSE_VIS_TRANSLATE_X", 0)
            s = l2.k.e("FUSE_VIS_TRANSLATE_Y", 0)
        }
    }

    private fun onOfficialLifecycleDestroy(owner: LifecycleOwner) {
        if (owner is Fragment) owner.lifecycle.removeObserver(B)
        u0()
    }

    private fun onOfficialLifecyclePause() {
        Y?.invoke()
    }

    private fun onOfficialLifecycleStart() {
        H?.holder?.addCallback(A)
        H?.visibility = View.VISIBLE
        m0 = false
    }

    private fun onOfficialLifecycleStop() {
        H?.visibility = View.GONE
        H?.holder?.removeCallback(A)
        l = null
        m0 = true
    }

    private class g(
        private val manager: PreviewManagerII,
    ) : SurfaceHolder.Callback {
        override fun surfaceCreated(holder: SurfaceHolder) {
            manager.onOfficialSurfaceCreated()
        }

        override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) = Unit

        override fun surfaceDestroyed(holder: SurfaceHolder) {
            manager.onOfficialSurfaceDestroyed()
        }
    }

    private class `defaultLifecycleObserver$1`(
        private val manager: PreviewManagerII,
    ) : DefaultLifecycleObserver {
        override fun onCreate(owner: LifecycleOwner) {
            manager.onOfficialLifecycleCreate()
        }

        override fun onDestroy(owner: LifecycleOwner) {
            manager.onOfficialLifecycleDestroy(owner)
        }

        override fun onPause(owner: LifecycleOwner) {
            manager.onOfficialLifecyclePause()
        }

        override fun onStart(owner: LifecycleOwner) {
            manager.onOfficialLifecycleStart()
        }

        override fun onStop(owner: LifecycleOwner) {
            manager.onOfficialLifecycleStop()
        }
    }
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
            if (C?.isShutdown != false) C = Executors.newSingleThreadExecutor()
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
        viewerSurfaceView.findViewTreeLifecycleOwner()?.let { a = it.lifecycle }
        if (!::K.isInitialized) K = Handler(Looper.getMainLooper())
        hik.common.yyrj.businesscommon.b.d.a().v(d2.a.a())
        A5.y.c.b().K(d2.a.a())
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
        if (!::K.isInitialized) K = Handler(Looper.getMainLooper())

        if (s0()) {
            m = Z2.a.a.p().c()
            n = Z2.a.a.p().c()
            t = Size(m.width, m.height)
            if (O != null && (t0() || q0())) {
                n0(n)
                p0()
            }
            b1()
            D = g3.b.a.a(Z2.a.a.p().k(), t0())
        } else if (r0()) {
            m = Size(120, 160)
            n = Size(120, 160)
            t = Size(120, 160)
            com.hik.f1module.F1UsbModuleHelper.USB_SetYuvSize(t)
        }

        S = u5.B.a.L() == 1
        U = Z2.g.a.w(Z2.g.a.U().getSerialNumber())
        g1(this, false, 1, null)
        val showSize = Z2.g.a.E()
        bindOfficialRenderer(viewerSurfaceView, l2.k.a("useM4", true))
        E?.let { activeRenderer ->
            if (shouldApplyRendererShowSize()) activeRenderer.i(showSize)
            activeRenderer.b(OfficialPlaybackListener())
        }
        a.addObserver(B)
    }

    private fun bindOfficialRenderer(viewerSurfaceView: SurfaceView, useM4: Boolean): V2.f {
        val factory: X2.b = if (useM4) X2.c() else X2.a()
        val selected = when {
            !s0() -> factory.a(viewerSurfaceView)
            Z2.a.a.t() -> factory.c(viewerSurfaceView)
            else -> factory.b(viewerSurfaceView)
        }
        E = selected
        return selected
    }

    private fun X(): String = Z2.g.a.U().getModuleID()

    private fun Y(): ModuleType = d3.c.a.a(X())

    private fun q0(): Boolean = Y() == ModuleType.F2ModuleType.F0

    private fun r0(): Boolean =
        Z2.g.b(Z2.g.a, false, 1, null) == UsbModuleType.F1

    private fun s0(): Boolean =
        Z2.g.b(Z2.g.a, false, 1, null) == UsbModuleType.F2

    private fun t0(): Boolean = Y() == ModuleType.F2ModuleType.F2V2

    private fun n0(size: Size) {
        com.hikvision.rid.AnalyzerPaletteRid.a.initRID(size.width, size.height)
    }

    private fun p0() {
        val serialNumber = Z2.g.a.U().getSerialNumber()
        val calibration = File(A5.y.c.b().u(), "HM-Calibration_$serialNumber.dat")
        if (calibration.exists()) calibration.readBytes()
    }

    private fun b1() {
        e1()
        x0 = Executors.newSingleThreadScheduledExecutor()
        x0?.scheduleAtFixedRate(K2.e(this), 0L, F2_CONSUMER_PERIOD_MS, TimeUnit.MILLISECONDS)
    }

    private fun e1() {
        x0?.shutdownNow()
        x0 = null
    }

    fun f1(secondMenuVisible: Boolean) {
        var showWidth = l2.l.a.b()
        val widerThanReportLimit = showWidth > d
        if (q0() && widerThanReportLimit && !W) showWidth = d
        val sourceWidth = m.width
        val sourceHeight = m.height
        if (sourceWidth <= 0 || sourceHeight <= 0) return
        var showHeight = (showWidth.toFloat() * sourceHeight / sourceWidth).toInt()
        val statusBarHeight = l2.l.a.c()
        val titleBarHeight = l2.n.a.a(44)
        l2.n.a.a(22)
        val firstMenuHeight = l2.n.a.a(72)
        val mediaControllerHeight = l2.n.a.a(120)
        var availableHeight = l2.l.a.a() -
            (titleBarHeight + statusBarHeight + firstMenuHeight + mediaControllerHeight)
        if (secondMenuVisible) availableHeight -= statusBarHeight
        if (showHeight > availableHeight) {
            showWidth = (availableHeight.toFloat() * sourceWidth / sourceHeight).toInt()
            showHeight = availableHeight
        }
        J?.let { visibleLight ->
            val visibleWidth = showWidth / 3
            val visibleHeight = showHeight / 3
            visibleLight.layoutParams.width = visibleWidth + (40 - visibleWidth % 40)
            visibleLight.layoutParams.height = visibleHeight + (40 - visibleHeight % 40)
            visibleLight.requestLayout()
        }
        if (U == 90 || U == 270) {
            showWidth = l2.l.a.b()
            if (q0() && widerThanReportLimit && !W) showWidth = d
            showHeight = (showWidth.toFloat() * sourceWidth / sourceHeight).toInt()
        }
        val showSize = Size(showWidth, showHeight)
        G?.layoutParams?.let {
            it.width = showSize.width
            it.height = showSize.height
        }
        J?.post { h1(this, showSize) }
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
            u0()
            clearSlotsLocked()
            latestProcessedFrame = null
            latestOfficialOfflinePreviewInfo = null
        }
    }

    /** Exact Viewer 2.6.0 teardown core; app synchronization remains in closePreviewCallback(). */
    fun u0() {
        E?.c()
        E?.release()
        E = null
        B0 = null
        C0 = null
        X = null
        Y = null
        Z = null
        a0 = null
        b0 = null
        c0 = null
        d0 = null
        e0 = null
        f0 = null
        g0 = null
        h0 = null
        D?.k()
        D = null
        C?.shutdownNow()
        C = null
        e1()
        q0 = true
        m0 = true
        G = null
        H = null
        I = null
        J = null
        if (::K.isInitialized) K.removeCallbacksAndMessages(null)
    }

    fun openPreviewCallback() {
        synchronized(lifecycleLock) {
            streamClosed = false
            clearSlotsLocked()
            latestProcessedFrame = null
            latestOfficialOfflinePreviewInfo = null
            if (C?.isShutdown != false) C = Executors.newSingleThreadExecutor()
            if (activeOnFrame != null) startConsumerLocked()
        }
    }

    private fun startConsumerLocked() {
        if (x0?.isShutdown == false) return
        stopConsumerLocked()
        x0 = Executors.newSingleThreadScheduledExecutor()
        x0?.scheduleAtFixedRate(
            K2.e(this),
            0L,
            F2_CONSUMER_PERIOD_MS,
            TimeUnit.MILLISECONDS,
        )
    }

    private fun stopConsumerLocked() = e1()

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
        D = processor
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
            if (u5.B.a.d0()) Z?.invoke()
        }

        override fun onStop() = Unit
    }

    private fun showViewerErrorTip(error: String?) {
        if (error == null) return
        if (I == null) return
        K.post { I?.visibility = if (error.isEmpty()) View.GONE else View.VISIBLE }
    }

    private fun shouldApplyRendererShowSize(): Boolean =
        !u5.B.a.h0() &&
            !Z2.g.a.b0() &&
            hik.common.yyrj.businesscommon.b.x(
                hik.common.yyrj.businesscommon.b.d.a(),
                null,
                1,
                null,
            )

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
        private class DetachedLifecycleOwner : LifecycleOwner {
            private val registry = LifecycleRegistry(this)
            override val lifecycle: Lifecycle = registry
        }

        private val detachedLifecycleOwner = DetachedLifecycleOwner()

        @JvmField
        val INSTANCE: PreviewManagerII = PreviewManagerII(
            detachedLifecycleOwner.lifecycle,
            false,
            false,
        )

        @JvmStatic
        fun g1(manager: PreviewManagerII, secondMenuVisible: Boolean, mask: Int, unused: Any?) {
            manager.f1(if (mask and 1 != 0) false else secondMenuVisible)
        }

        @JvmStatic
        fun m0(
            manager: PreviewManagerII,
            viewerRootView: View?,
            viewerSurfaceView: SurfaceView,
            viewerErrorText: TextView?,
            visibleLightView: FloatTextureView?,
            sceneModeBean: SceneModeBean?,
            freezeCallback: ((Boolean) -> Unit)?,
            overlayAvailabilityCallback: ((Boolean) -> Unit)?,
            frameNumberCallback: ((Int) -> Unit)?,
            mask: Int,
            unused: Any?,
        ) {
            manager.l0(
                viewerRootView,
                viewerSurfaceView,
                if (mask and 4 != 0) null else viewerErrorText,
                visibleLightView,
                if (mask and 16 != 0) null else sceneModeBean,
                if (mask and 32 != 0) null else freezeCallback,
                if (mask and 64 != 0) null else overlayAvailabilityCallback,
                if (mask and 128 != 0) null else frameNumberCallback,
            )
        }

        @JvmStatic
        private fun h1(manager: PreviewManagerII, showSize: Size) {
            manager.J?.let { visibleLight ->
                val visibleSize = Size(visibleLight.width, visibleLight.height)
                visibleLight.f(Z2.g.a.W(), false, showSize, visibleSize)
            }
            if (manager.shouldApplyRendererShowSize()) manager.E?.i(showSize)
            Z2.g.a.M0(showSize)
        }

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
                manager.C?.execute(K2.i(manager, previewInfoData, frameNumStamp))
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
