package V2

import android.graphics.Bitmap
import android.util.Size
import android.view.SurfaceView
import com.hik.library.player.b
import com.hik.library.player.d
import com.hikmicro.pm_hrl_bussinesscmp.model.FrameInfo
import h3.b as PrivateStreamInfo
import h3.c as UploadStreamInfo

/** Official PM-HRL renderer. Surface initialization is owned by z3, not construction. */
class e(private val surfaceView: SurfaceView) : f {
    override fun a(): Boolean = z3.c.a.z()
    override fun b(listener: b) = Unit
    override fun c() = Unit
    override fun d(picSize: Size, filePath: String): Boolean = z3.c.a.y(filePath)
    override fun e(picSize: Size): ByteArray? = z3.c.a.d().getByteArray()
    override fun f(picSize: Size): d { val frame = z3.c.a.d(); return d(frame.getTime(), frame.getByteArray()) }
    override fun g(first: Boolean, second: Boolean, third: Boolean, fourth: Boolean, mode: Int, firstScale: Float, secondScale: Float) = Unit
    override fun h(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int) {
        val privateBytes = l(rawData, nv12Data, yuvImgSize, frameNumStamp) ?: return
        val info = com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO()
        k3.b.d(k3.b.a, info, privateBytes, null, 4, null)
        z3.c.a.A(FrameInfo(nv12Data, yuvImgSize, Z2.g.a.w(Z2.g.a.U().getSerialNumber()), info, Z2.a.a.p().k(), frameNumStamp))
    }
    override fun i(showSize: Size) = Unit
    override fun j(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int, overlays: List<*>?, overlayBitmap: Bitmap?) { l(rawData, nv12Data, yuvImgSize, frameNumStamp) }
    override fun k(value: Int) = Unit
    fun l(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int): ByteArray? {
        val state = Z2.g.a
        val serialNumber = state.U().getSerialNumber()
        val degree = state.w(serialNumber)
        return when (val streamInfo = state.o()) {
            is PrivateStreamInfo -> {
                val transformed = d3.i.a.m(
                    streamInfo.a(),
                    state.v(),
                    state.i(serialNumber, if (state.f()) 1 else 0),
                    state.g(serialNumber, state.e()),
                    state.h(serialNumber),
                    state.u(),
                    degree,
                )
                transformed.privateInfo_header.dsp_std_stamp = frameNumStamp
                val info = if (state.v()) transformed else com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO()
                k3.b.b(k3.b.a, info, null, 2, null)
            }
            is UploadStreamInfo -> {
                if (state.n() == 98_304 || state.n() == 221_184) {
                    z3.c.a.A(
                        FrameInfo(
                            state.j(),
                            yuvImgSize,
                            degree,
                            com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO(),
                            Z2.a.a.p().k(),
                            frameNumStamp,
                        ),
                    )
                    null
                } else {
                    val basic = state.K()
                    val info = d3.i.a.k(
                        streamInfo.a(),
                        basic.getEnableCenterTem(),
                        basic.getEnableHighTem(),
                        basic.getEnableLowTem(),
                        state.L(),
                        true,
                        state.i(serialNumber, if (state.f()) 1 else 0),
                        state.g(serialNumber, state.e()),
                        state.h(serialNumber),
                        state.u(),
                        state.M(),
                        d3.c.a.a(state.U().getModuleID()),
                        degree,
                    )
                    info.privateInfo_header.dsp_std_stamp = frameNumStamp
                    k3.b.b(k3.b.a, info, null, 2, null)
                }
            }
            else -> null
        }
    }
    override fun release() = Unit
    override fun start() = Unit
    override fun stop() = Unit
}
