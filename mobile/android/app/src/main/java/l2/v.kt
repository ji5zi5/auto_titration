package l2

import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.util.Size
import java.io.ByteArrayOutputStream

/** Official YUV-to-JPEG helper with Kotlin-default bridge shape. */
class v private constructor() {
    fun a(yuvImageData: ByteArray, yuvImgSize: Size, format: Int, quality: Int): ByteArray {
        val output = ByteArrayOutputStream()
        return try {
            YuvImage(yuvImageData, format, yuvImgSize.width, yuvImgSize.height, null)
                .compressToJpeg(Rect(0, 0, yuvImgSize.width, yuvImgSize.height), quality, output)
            output.flush()
            output.toByteArray()
        } finally {
            output.close()
        }
    }
    companion object {
        @JvmField val a: v = v()
        @JvmStatic fun b(self: v, data: ByteArray, size: Size, format: Int, quality: Int, mask: Int, unused: Any?): ByteArray =
            self.a(data, size, if (mask and 4 != 0) ImageFormat.NV21 else format, if (mask and 8 != 0) 100 else quality)
    }
}
