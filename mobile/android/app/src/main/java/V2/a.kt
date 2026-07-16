package V2

import android.graphics.Bitmap
import android.util.Size
import android.view.SurfaceHolder
import com.hik.library.player.b
import com.hik.library.player.d

/** Exact non-M4 F1 renderer recovered from Viewer 2.6.0. */
class a(private val holder: SurfaceHolder) : f {
    private val drawer = W2.a(holder)

    override fun a(): Boolean = false
    override fun b(listener: b) = Unit
    override fun c() = Unit
    override fun d(picSize: Size, filePath: String): Boolean = false
    override fun e(picSize: Size): ByteArray? = null
    override fun f(picSize: Size): d = d(-1, null)
    override fun g(first: Boolean, second: Boolean, third: Boolean, fourth: Boolean, mode: Int, firstScale: Float, secondScale: Float) = Unit
    override fun h(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int) {
        val i420 = ByteArray(yuvImgSize.width * yuvImgSize.height * 3 / 2)
        com.louisgeek.gyuv.GYUV.a.gyuvNV12ToI420(nv12Data, yuvImgSize.width, yuvImgSize.height, i420)
        val nv21 = ByteArray(i420.size)
        com.louisgeek.gyuv.GYUV.a.gyuvI420ToNV21(i420, yuvImgSize.width, yuvImgSize.height, nv21)
        drawer.a(l2.v.b(l2.v.a, nv21, yuvImgSize, 0, 0, 12, null))
    }
    override fun i(showSize: Size) = Unit
    override fun j(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int, overlays: List<*>?, overlayBitmap: Bitmap?) {
        throw NotImplementedError("Not yet implemented")
    }
    override fun k(value: Int) = Unit
    override fun release() = Unit
    override fun start() { com.hik.f1module.F1UsbModuleHelper.USB_SetPreviewEnable(true) }
    override fun stop() { com.hik.f1module.F1UsbModuleHelper.USB_SetPreviewEnable(false) }
}
