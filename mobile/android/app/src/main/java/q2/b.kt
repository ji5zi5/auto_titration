package q2

import com.hik.transformlib.MediaTransform
import java.nio.ByteBuffer

/** Official video/audio transform clock used by ThermalPlayer's frame callback. */
class b {
    @Volatile private var transforming = false
    private var frameCount = 0

    fun c(data: ByteArray, length: Int) {
        if (transforming && frameCount > 2) {
            d(1, data, System.currentTimeMillis() - EPOCH_OFFSET_MS, length, 0, 0)
        }
    }

    @Synchronized
    fun d(type: Int, data: ByteArray, timestamp: Long, length: Int, width: Int, height: Int) {
        when (type) {
            1 -> MediaTransform.startAudioTransform(data, timestamp, length)
            2 -> MediaTransform.startVideoTransform(data, timestamp, length, width, height)
        }
    }

    fun e(filePath: String) {
        transforming = true
        frameCount = 0
        MediaTransform.transformInit(filePath)
    }

    fun f(): Int {
        transforming = false
        frameCount = 0
        return MediaTransform.stopTransform()
    }

    fun g(byteBuffer: ByteBuffer, width: Int, height: Int, timestamp: Long) {
        if (!transforming) return
        frameCount += 1
        val origin = if (frameCount > 2 || frameCount != 1) EPOCH_OFFSET_MS else System.currentTimeMillis()
        val data = ByteArray(byteBuffer.remaining())
        byteBuffer.get(data, 0, byteBuffer.remaining())
        d(2, data, System.currentTimeMillis() - origin, data.size, width, height)
    }

    companion object {
        private const val EPOCH_OFFSET_MS = 1_636_184_000_000L
        @Volatile private var instance: b? = null
        @JvmStatic fun a(): b {
            if (instance == null) instance = b()
            return instance!!
        }
    }
}
