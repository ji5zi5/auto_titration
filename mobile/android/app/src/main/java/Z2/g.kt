package Z2

import android.util.Size
import com.hik.modulelib.UsbModuleInfo
import com.hik.modulelib.bean.ThermometryBasicBean
import com.hik.viewercommon.data.bean.SceneModeBean
import com.hik.viewercommon.data.bean.UsbModuleType
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

/** Official Viewer global singleton state graph recovered from HIKMICRO Viewer 2.6.0 DEX. */
class g private constructor() {
    fun a(updateCache: Boolean): UsbModuleType {
        var detected: UsbModuleType = UsbModuleType.NONE
        val device = o2.a.a.c(d2.a.a())
        if (device != null) {
            detected = when {
                device.vendorId == 11231 && device.productId == 320 -> UsbModuleType.F1
                device.vendorId == 11231 && (device.productId == 258 || device.productId == 257) -> UsbModuleType.F2
                device.vendorId == 8367 -> UsbModuleType.F2
                else -> UsbModuleType.NONE
            }
        }
        if (updateCache) {
            f = detected
            g = detected
        }
        return detected
    }

    fun A(): List<SceneModeBean> = N
    fun A0(value: Int) { G = value }
    fun B(): String = l2.k.h("scene_mode_data" + o.getSerialNumber(), "")
    fun B0(value: h3.a?) { E = value }
    fun C(): Int = l2.k.e("scene_mode_index" + o.getSerialNumber(), 0)
    fun C0(value: Boolean?) { e = value }
    fun D(): String = A
    fun D0(value: UsbModuleType) { g = value }
    fun E(): Size = D
    fun E0(value: Boolean) { j = value }
    fun F(): List<SceneModeBean> = M
    fun F0(value: Boolean) { k = value }
    fun G(): Boolean = l2.k.b("VIEWER_SHOW_VIS_VIEW" + u5.B.a.k().getSerialNumber(), false, 2, null)
    fun G0(value: Int) { J = value }
    fun H(): Boolean = d
    fun H0(value: Boolean) { c = value }
    fun I(): Int = l2.k.e("TSR_CTRL_" + o.getSerialNumber(), -1)
    fun I0(value: Boolean) { m = value }
    fun J(): String = l2.k.i("testJson_movLists" + o.getSerialNumber(), "", 2, null)
    fun J0(value: Boolean) { b = value }
    fun K(): ThermometryBasicBean = C
    fun K0(value: Boolean) { p = value }
    fun L(): List<Any> = B
    fun L0(value: String) { A = value }
    fun M(): Int = L
    fun M0(value: Size) { D = value }
    fun N(): String = s
    fun N0(value: Boolean) { d = value }
    fun O(): String = t
    fun O0(str: String) { l2.k.m("testJson_movLists" + o.getSerialNumber(), str) }
    fun P(): String = u
    fun P0(value: ThermometryBasicBean) { C = value }
    fun Q(): String = v
    fun Q0(value: List<Any>) { B = value }
    fun R(): String = q
    fun R0(value: Int) { L = value }
    fun S(): String = r
    fun S0(value: String) { s = value }
    fun T(): String = w
    fun T0(value: String) { t = value }
    fun U(): UsbModuleInfo = o
    fun U0(value: String) { u = value }
    fun V(): UsbModuleType = f
    fun V0(value: String) { x = value }
    fun W(): Int = l2.k.e("VIEWER_VISIBLE_LIGHT_GRAVITY", 8388659)
    fun W0(value: String) { y = value }
    fun X() {
        val persistedJson = B()
        val gson = Gson()
        O.clear()
        if (persistedJson.isNotEmpty()) {
            val restored: List<SceneModeBean> = gson.fromJson(
                persistedJson,
                object : TypeToken<List<SceneModeBean>>() {}.type,
            )
            O.addAll(restored)
        }
        if (O.isEmpty()) O.addAll(N.map { it.copy() })
    }
    fun X0(value: String) { v = value }
    fun Y(): Boolean = n
    fun Y0(value: String) { q = value }
    fun Z(): Boolean = m
    fun Z0(value: String) { r = value }
    fun a0(): Boolean = p
    fun a1(value: String) { w = value }
    fun b0(): Boolean = i
    fun b1(value: Boolean) { l = value }
    fun c(serialNo: String, defaultValue: Boolean): Boolean = l2.k.a("AGC_VIS_CTRL_$serialNo", defaultValue)
    fun c0(): Boolean = l
    fun c1(value: UsbModuleInfo) { o = value }
    fun d(): Boolean = K
    fun d0() { l2.k.n("VIEWER_IS_DUAL_FUSE_MODE" + u5.B.a.k().getSerialNumber()); l2.k.n("VIEWER_DUAL_FUSE_DISTANCE" + u5.B.a.k().getSerialNumber()) }
    fun d1(value: UsbModuleType) { f = value }
    fun e(): String = I
    fun e0() { l2.k.n("TSR_CTRL_" + u5.B.a.k().getSerialNumber()) }
    fun e1(value: Int) { l2.k.l("VIEWER_VISIBLE_LIGHT_GRAVITY", value) }
    fun f(): Boolean = H
    fun f0(serialNo: String) { l2.k.n("testJson_movLists$serialNo") }
    fun g(serialNo: String, defaultValue: String): String = l2.k.h("VIEWER_ALARM_TEMP_HIGH_C_$serialNo", defaultValue)
    fun g0() { l2.k.n("VIEWER_SHOW_VIS_VIEW" + u5.B.a.k().getSerialNumber()) }
    fun h(serialNo: String): String = l2.k.h("VIEWER_ALARM_TEMP_LOW_C_$serialNo", "20")
    fun h0(serialNo: String, value: Boolean) { l2.k.j("AGC_VIS_CTRL_$serialNo", value) }
    fun i(serialNo: String, defaultValue: Int): Int = l2.k.e("VIEWER_ALARM_TEMP_STATUS_$serialNo", defaultValue)
    fun i0(serialNo: String, alarmTempHighC: String) { l2.k.m("VIEWER_ALARM_TEMP_HIGH_C_$serialNo", alarmTempHighC) }
    fun j(): ByteArray = F
    fun j0(serialNo: String, alarmTempLowC: String) { l2.k.m("VIEWER_ALARM_TEMP_LOW_C_$serialNo", alarmTempLowC) }
    fun k(): Boolean = l2.k.b("customPseudoColorEnable" + o.getSerialNumber(), false, 2, null)
    fun k0(serialNo: String, status: Int) { l2.k.l("VIEWER_ALARM_TEMP_STATUS_$serialNo", status) }
    fun l(): Int = l2.k.e("VIEWER_DUAL_FUSE_DISTANCE" + o.getSerialNumber(), 5)
    fun l0(value: Boolean) { l2.k.j("VIEWER_IS_DUAL_FUSE_MODE" + o.getSerialNumber(), value) }
    fun m(): String = z
    fun m0(serialNo: String, degree: Int) { l2.k.l("ROTATE_DEGREE_$serialNo", degree) }
    fun n(): Int = G
    fun n0(serialNo: String, value: Boolean) { l2.k.j("PREVIEW_ZOOM_$serialNo", value) }
    fun o(): h3.a? = E
    fun o0(json: String) { l2.k.m("scene_mode_data" + o.getSerialNumber(), json) }
    fun p(): Boolean = l2.k.b("VIEWER_IS_DUAL_FUSE_MODE" + o.getSerialNumber(), false, 2, null)
    fun p0(serialNumber: String, json: String) { l2.k.m("scene_mode_data$serialNumber", json) }
    fun q(): Boolean? = e
    fun q0(value: Boolean) { l2.k.j("VIEWER_SHOW_VIS_VIEW" + u5.B.a.k().getSerialNumber(), value) }
    fun r(): UsbModuleType = g
    fun r0(tsrState: Int) { l2.k.l("TSR_CTRL_" + o.getSerialNumber(), tsrState) }
    fun s(): Boolean = h
    fun s0(value: Boolean) { K = value }
    fun t(): Boolean = k
    fun t0(value: String) { I = value }
    fun u(): Int = J
    fun u0(value: Boolean) { H = value }
    fun v(): Boolean = c
    fun v0(value: Boolean) { n = value }
    fun w(serialNo: String): Int = l2.k.f("ROTATE_DEGREE_$serialNo", 0, 2, null)
    fun w0(serialNumber: String, value: Boolean) { l2.k.j("customPseudoColorEnable$serialNumber", value) }
    fun x(serialNo: String, defaultValue: Boolean): Boolean = l2.k.a("PREVIEW_ZOOM_$serialNo", defaultValue)
    fun x0(value: Boolean) { l2.k.j("customPseudoColorEnable" + o.getSerialNumber(), value) }
    fun y(): Boolean = b
    fun y0(value: Int) { l2.k.l("VIEWER_DUAL_FUSE_DISTANCE" + o.getSerialNumber(), value) }
    fun z(): List<SceneModeBean> = O
    fun z0(value: String) { z = value }

    companion object {
        @JvmField val a: g = g()
        @JvmStatic fun b(self: g, updateCache: Boolean = true, mask: Int = 0, unused: Any? = null): UsbModuleType = self.a(if (mask and 1 != 0) true else updateCache)
        private var b: Boolean = false
        private var c: Boolean = false
        private var d: Boolean = false
        private var e: Boolean? = null
        private var f: UsbModuleType = UsbModuleType.NONE
        private var g: UsbModuleType = UsbModuleType.NONE
        private var h: Boolean = false
        private var i: Boolean = false
        private var j: Boolean = false
        private var k: Boolean = false
        private var l: Boolean = false
        private var m: Boolean = false
        private var n: Boolean = false
        private var o: UsbModuleInfo = UsbModuleInfo()
        private var p: Boolean = false
        private var q: String = ""
        private var r: String = ""
        private var s: String = ""
        private var t: String = ""
        private var u: String = ""
        private var v: String = ""
        private var w: String = ""
        private var x: String = ""
        private var y: String = ""
        private var z: String = ""
        private var A: String = ""
        private var B: List<Any> = ArrayList()
        private var C: ThermometryBasicBean = ThermometryBasicBean()
        private var D: Size = Size(0, 0)
        private var E: h3.a? = null
        private var F: ByteArray = ByteArray(0)
        private var G: Int = 0
        private var H: Boolean = false
        private var I: String = "80"
        private var J: Int = 0
        private var K: Boolean = false
        private var L: Int = 0
        private val M: MutableList<SceneModeBean> = ArrayList()
        private val N: MutableList<SceneModeBean> = ArrayList()
        private val O: MutableList<SceneModeBean> = ArrayList()

        internal fun restoreSceneModes(
            persistedJson: String,
            defaults: List<SceneModeBean>,
        ): List<SceneModeBean> {
            val persisted: List<SceneModeBean> = if (persistedJson.isNotEmpty()) {
                Gson().fromJson(
                    persistedJson,
                    object : TypeToken<List<SceneModeBean>>() {}.type,
                )
            } else {
                emptyList()
            }
            return if (persisted.isNotEmpty()) persisted else defaults.map { it.copy() }
        }
    }
}
