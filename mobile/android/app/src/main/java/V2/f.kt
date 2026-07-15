package V2

import android.graphics.Bitmap
import android.util.Size
import com.hik.library.player.b
import com.hik.library.player.d

/** Exact renderer ABI recovered from Viewer 2.6.0 classes3.dex. */
interface f {
    fun a(): Boolean
    fun b(listener: b)
    fun c()
    fun d(picSize: Size, filePath: String): Boolean
    fun e(picSize: Size): ByteArray?
    fun f(picSize: Size): d
    fun g(
        first: Boolean,
        second: Boolean,
        third: Boolean,
        fourth: Boolean,
        mode: Int,
        firstScale: Float,
        secondScale: Float,
    )
    fun h(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int)
    fun i(showSize: Size)
    fun j(
        rawData: ByteArray?,
        nv12Data: ByteArray,
        yuvImgSize: Size,
        frameNumStamp: Int,
        overlays: List<*>?,
        overlayBitmap: Bitmap?,
    )
    fun k(value: Int)
    fun release()
    fun start()
    fun stop()
}
