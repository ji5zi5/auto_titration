package Z2

import android.util.Size
import com.hik.viewercommon.data.bean.UsbModuleType

/** Exact Viewer 2.6.0 Z2.a preview-profile singleton contract. */
class a private constructor() {
    fun a(): Size = size720x720
    fun b(): Size = size96x176
    fun c(): Size = size96x96
    fun d(): Size = size288x384Duplicate
    fun e(): Size = size384x288
    fun f(): Size = size288x776
    fun g(): Size = size384x512
    fun h(): Size = size288x384
    fun i(): Boolean = appendEnabled
    fun j(): Size = size720x960
    fun k(): Size = size192x256Duplicate
    fun l(): Size = size256x192
    fun m(): Size = size192x520
    fun n(): Size = size256x344
    fun o(): Size = size192x256
    fun p(): f3.k = previewProfile
    fun q(): Boolean = reservedFlag
    fun r(): Int = RECORD_SOURCE_I420
    fun s(): Int = RECORD_SOURCE_NV12
    fun t(): Boolean =
        Z2.g.b(Z2.g.a, false, 1, null) == UsbModuleType.F1 && appendEnabled
    fun u(profile: f3.k) { previewProfile = profile }

    companion object {
        @JvmField
        val a: a = a()

        private val size192x256 = Size(192, 256)
        private val size720x960 = Size(720, 960)
        private val size96x96 = Size(96, 96)
        private val size720x720 = Size(720, 720)
        private val size192x520 = Size(192, 520)
        private val size256x344 = Size(256, 344)
        private val size192x256Duplicate = Size(192, 256)
        private val size256x192 = Size(256, 192)
        private val size288x384 = Size(288, 384)
        private val size288x776 = Size(288, 776)
        private val size96x176 = Size(96, 176)
        private val size384x512 = Size(384, 512)
        private val size288x384Duplicate = Size(288, 384)
        private val size384x288 = Size(384, 288)
        private var previewProfile: f3.k = f3.a()
        private var appendEnabled: Boolean = true
        private var reservedFlag: Boolean = false

        // Extracted from classes4.dex:
        // org.Thermal.PlayM4.Player.RECORD_SOURCE_TYPE.
        private const val RECORD_SOURCE_NV12: Int = 1
        private const val RECORD_SOURCE_I420: Int = 2
    }
}
