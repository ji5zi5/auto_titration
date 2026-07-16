package W2

import android.graphics.BitmapFactory
import android.graphics.Rect
import android.view.SurfaceHolder

/** Official JPEG-to-SurfaceHolder drawer used by V2.a and V2.c. */
class a(private val surfaceHolder: SurfaceHolder) {
    fun a(jpegData: ByteArray) {
        val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(jpegData, 0, jpegData.size, options)
        val targetWidth = l2.l.a.b()
        val target = Rect(0, 0, targetWidth, (options.outHeight.toFloat() / (options.outWidth.toFloat() / targetWidth)).toInt())
        val canvas = surfaceHolder.lockCanvas()
        val bitmap = BitmapFactory.decodeByteArray(jpegData, 0, jpegData.size)
        if (canvas != null) canvas.drawBitmap(bitmap, null, target, null)
        surfaceHolder.unlockCanvasAndPost(canvas)
    }
}
