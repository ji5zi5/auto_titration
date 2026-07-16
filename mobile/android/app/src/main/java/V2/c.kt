package V2

import android.graphics.Bitmap
import android.util.Size
import android.view.SurfaceHolder
import com.hik.library.player.b
import com.hik.library.player.d

/** Exact non-M4 F2 renderer recovered from Viewer 2.6.0. */
class c(private val holder: SurfaceHolder) : f {
    private val drawer = W2.a(holder)
    override fun a(): Boolean = false
    override fun b(listener: b) = Unit
    override fun c() = Unit
    override fun d(picSize: Size, filePath: String): Boolean = false
    override fun e(picSize: Size): ByteArray? = null
    override fun f(picSize: Size): d = d(-1, null)
    override fun g(first: Boolean, second: Boolean, third: Boolean, fourth: Boolean, mode: Int, firstScale: Float, secondScale: Float) = Unit
    override fun h(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int) {
        drawer.a(l2.v.b(l2.v.a, k3.a.a.g(nv12Data, yuvImgSize), yuvImgSize, 0, 0, 12, null))
    }
    override fun i(showSize: Size) = Unit
    override fun j(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int, overlays: List<*>?, overlayBitmap: Bitmap?) = Unit
    override fun k(value: Int) = Unit
    override fun release() = Unit
    override fun start() = Unit
    override fun stop() = Unit
}
