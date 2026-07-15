package V2

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Rect
import android.util.Size
import android.view.SurfaceHolder
import android.view.SurfaceView
import com.hik.library.player.b
import com.hik.library.player.d
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.CopyOnWriteArrayList

/**
 * Surface-backed implementation used by the recovered V2 renderer identities.
 *
 * The official non-M4 V2.a/V2.c route performs the same NV12 -> NV21 conversion
 * before handing the bitmap to its SurfaceHolder drawer. The M4 identities keep
 * the same public graph here while the bundled native player remains behind the
 * renderer boundary rather than the app/WebView adapter.
 */
open class SurfaceHolderRenderer(
    private val surfaceHolder: SurfaceHolder,
) : f {
    private val listeners = CopyOnWriteArrayList<b>()
    private val lock = Any()
    private var latestBitmap: Bitmap? = null
    private var latestFrameTime: Int = -1

    override fun a(): Boolean = false

    override fun b(listener: b) {
        listeners.addIfAbsent(listener)
    }

    override fun c() {
        listeners.clear()
    }

    override fun d(picSize: Size, filePath: String): Boolean {
        val bytes = e(picSize) ?: return false
        return runCatching {
            File(filePath).parentFile?.mkdirs()
            FileOutputStream(filePath).use { it.write(bytes) }
            true
        }.getOrDefault(false)
    }

    override fun e(picSize: Size): ByteArray? = synchronized(lock) {
        val bitmap = latestBitmap ?: return@synchronized null
        val scaled = if (picSize.width > 0 && picSize.height > 0 &&
            (bitmap.width != picSize.width || bitmap.height != picSize.height)
        ) {
            Bitmap.createScaledBitmap(bitmap, picSize.width, picSize.height, true)
        } else {
            bitmap
        }
        try {
            ByteArrayOutputStream().use { output ->
                scaled.compress(Bitmap.CompressFormat.JPEG, 100, output)
                output.toByteArray()
            }
        } finally {
            if (scaled !== bitmap) scaled.recycle()
        }
    }

    override fun f(picSize: Size): d = d(latestFrameTime, e(picSize))

    override fun g(
        first: Boolean,
        second: Boolean,
        third: Boolean,
        fourth: Boolean,
        mode: Int,
        firstScale: Float,
        secondScale: Float,
    ) = Unit

    override fun h(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int) {
        updateNv12(nv12Data, yuvImgSize, frameNumStamp)
    }

    override fun i(showSize: Size) = Unit

    override fun j(
        rawData: ByteArray?,
        nv12Data: ByteArray,
        yuvImgSize: Size,
        frameNumStamp: Int,
        overlays: List<*>?,
        overlayBitmap: Bitmap?,
    ) {
        updateNv12(nv12Data, yuvImgSize, frameNumStamp)
    }

    override fun k(value: Int) = Unit

    override fun release() {
        synchronized(lock) {
            latestBitmap?.recycle()
            latestBitmap = null
            latestFrameTime = -1
        }
        c()
    }

    override fun start() {
        listeners.forEach { it.onStart() }
    }

    override fun stop() {
        listeners.forEach { it.onStop() }
    }

    private fun updateNv12(nv12Data: ByteArray, size: Size, frameNumStamp: Int) {
        require(size.width > 0 && size.height > 0)
        require(nv12Data.size >= size.width * size.height * 3 / 2)
        val nv21 = k3.a.a.g(nv12Data, size)
        val bitmap = k3.a.a.a(nv21, size.width, size.height)
        synchronized(lock) {
            latestBitmap?.recycle()
            latestBitmap = bitmap
            latestFrameTime = frameNumStamp
        }
        draw(bitmap)
    }

    private fun draw(bitmap: Bitmap) {
        val surface = surfaceHolder.surface
        if (!surface.isValid) return
        var canvas: Canvas? = null
        try {
            canvas = surfaceHolder.lockCanvas()
            if (canvas != null) {
                canvas.drawColor(Color.BLACK)
                canvas.drawBitmap(bitmap, null, fitCenter(bitmap, canvas), null)
            }
        } finally {
            if (canvas != null) surfaceHolder.unlockCanvasAndPost(canvas)
        }
    }

    private fun fitCenter(bitmap: Bitmap, canvas: Canvas): Rect {
        val scale = minOf(
            canvas.width.toFloat() / bitmap.width,
            canvas.height.toFloat() / bitmap.height,
        )
        val width = (bitmap.width * scale).toInt()
        val height = (bitmap.height * scale).toInt()
        val left = (canvas.width - width) / 2
        val top = (canvas.height - height) / 2
        return Rect(left, top, left + width, top + height)
    }
}
