package z3

import android.graphics.Bitmap
import android.view.SurfaceView
import com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy
import com.hikmicro.pm_hrl_bussinesscmp.model.Frame
import com.hikmicro.pm_hrl_bussinesscmp.model.FrameInfo
import com.hikmicro.pm_hrl_bussinesscmp.model.ThermalModel

/** Official z3.c singleton state graph recovered from HIKMICRO Viewer 2.6.0 DEX. */
class c private constructor() {
    private fun s(width: Int, height: Int) {
        if (width >= height) {
            v = 720
            u = A3.f.a.f(width * 720 / height)
        } else {
            u = 720
            v = A3.f.a.f(height * 720 / width)
        }
    }

    private fun t() {
        d = x3.a()
        d!!.l(x3.a.b.b)
        d!!.o(z3.b())
        e = w3.k()
        d!!.i(e!!)
        f = w3.k()
    }

    fun A(frameInfo: FrameInfo) {
        if (r) {
            val drawer = e ?: throwUninitialized("drawer")
            val bitmap = drawer.m(frameInfo.getThermalPrivateInfo(), b, c) ?: Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888)
            val model = ThermalModel(
                frameInfo.getNv12ByteArray(),
                frameInfo.getYuvSize().width,
                frameInfo.getYuvSize().height,
                bitmap,
                frameInfo.getFrameNumStamp(),
            )
            drawer.z(model)
            (d ?: throwUninitialized("renderer")).k(System.currentTimeMillis())
            if (s) {
                val recordDrawer = f ?: throwUninitialized("recordDrawer")
                recordDrawer.z(model)
                g?.r((System.currentTimeMillis() - t) * 1_000_000L, listOf(recordDrawer))
            }
        }
    }

    fun b(): Float = j
    fun c(): Float = k
    fun d(): Frame = (e ?: throwUninitialized("drawer")).q()
    fun e(): Int = m
    fun f(): Float = l
    fun g(): Boolean = h
    fun h(): Boolean = i
    fun i(): Boolean = p
    fun j(): Boolean = o
    fun k() { m = -1; (e ?: throwUninitialized("drawer")).y(null) }
    fun l(enable: Boolean, value: Float) { if (enable) { h = true; j = value } else h = false }
    fun n(enable: Boolean, value: Float) { if (enable) { i = true; k = value } else i = false }
    fun p(value: Boolean) { p = value }
    fun q(bitmap: Bitmap?, point: HCUSBCameraSDKBy.IFR_POINT?) { b = bitmap; c = point }
    fun r(frameNumStamp: Int) { m = frameNumStamp }
    fun u(surfaceView: SurfaceView) { t(); (d ?: throwUninitialized("renderer")).n(surfaceView) }
    fun w(rotationDegree: Int) { l = when (rotationDegree) { 90 -> 1.5707964f; 180 -> 3.1415927f; 270 -> 4.712389f; else -> 0f } }
    fun x(value: Boolean) { o = value }
    fun y(path: String): Boolean { s = true; t = System.currentTimeMillis(); g = y3.b(null); g?.t(u, v); g?.u(1.0f, path); return true }
    fun z(): Boolean { g?.v(); return true }

    private fun <T> throwUninitialized(name: String): T {
        kotlin.jvm.internal.Intrinsics.throwUninitializedPropertyAccessException(name)
        throw IllegalStateException(name)
    }

    companion object {
        @JvmField val a: c = c()
        @JvmStatic fun a(width: Int, height: Int): kotlin.Unit { z3.c.a.s(width, height); return kotlin.Unit }
        @JvmStatic fun m(self: c, enable: Boolean, value: Float = 0f, mask: Int = 0, unused: Any? = null) { self.l(enable, if (mask and 2 != 0) 0f else value) }
        @JvmStatic fun o(self: c, enable: Boolean, value: Float = 0f, mask: Int = 0, unused: Any? = null) { self.n(enable, if (mask and 2 != 0) 0f else value) }
        private var b: Bitmap? = null
        private var c: HCUSBCameraSDKBy.IFR_POINT? = null
        private lateinit var d: x3.a
        private lateinit var e: w3.k
        private lateinit var f: w3.k
        private var g: y3.b? = null
        private var h: Boolean = false
        private var i: Boolean = false
        private var j: Float = 30.0f
        private var k: Float = 10.0f
        private var l: Float = 0.0f
        @Volatile private var m: Int = -1
        @Volatile private var n: Int = -1
        private var o: Boolean = false
        private var p: Boolean = false
        private var q: Boolean = true
        @Volatile private var r: Boolean = false
        private var s: Boolean = false
        private var t: Long = 0L
        private var u: Int = 960
        private var v: Int = 720
    }
}
