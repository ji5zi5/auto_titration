package k3

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Rect
import android.graphics.YuvImage
import android.util.Size
import com.louisgeek.gyuv.GYUV
import java.io.ByteArrayOutputStream

class a private constructor() {
    companion object {
        @JvmField val a: k3.a = a()
        @JvmStatic fun f(self: k3.a, nv12: ByteArray, yuvSize: Size, yuvScaledSize: Size, rot: Int, mirror: Boolean, mask: Int, unused: Any?): ByteArray =
            self.e(nv12, yuvSize, yuvScaledSize, rot, if (mask and 16 != 0) false else mirror)
    }

    fun a(nv21Data: ByteArray, width: Int, height: Int): Bitmap {
        val image = YuvImage(nv21Data, 17, width, height, null)
        val stream = ByteArrayOutputStream()
        image.compressToJpeg(Rect(0, 0, width, height), 100, stream)
        val bytes = stream.toByteArray()
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
    }

    fun b(i420: ByteArray, yuvSize: Size): ByteArray {
        val i422 = ByteArray(yuvSize.width * yuvSize.height * 2)
        val gyuv = GYUV.a
        gyuv.gyuv420pTo422p(i420, yuvSize.width, yuvSize.height, i422)
        val nv16 = ByteArray(yuvSize.width * yuvSize.height * 2)
        gyuv.gyuv422pToNV16(i422, yuvSize.width, yuvSize.height, nv16)
        return nv16
    }

    fun c(nv12: ByteArray, yuvSize: Size, yuvRotateSize: Size, rot: Int): ByteArray {
        val i420 = ByteArray(yuvSize.width * yuvSize.height * 3 / 2)
        val gyuv = GYUV.a
        gyuv.gyuvNV12ToI420(nv12, yuvSize.width, yuvSize.height, i420)
        val rotateSize = Size(yuvRotateSize.height, yuvRotateSize.width)
        val rotated = ByteArray(rotateSize.width * rotateSize.height * 3 / 2)
        gyuv.gyuvI420Rotate(i420, rotateSize.width, rotateSize.height, rotated, rot)
        val out = ByteArray(rotateSize.width * rotateSize.height * 3 / 2)
        gyuv.gyuvI420ToNV12(rotated, rotateSize.width, rotateSize.height, out)
        return out
    }

    fun d(nv12: ByteArray, yuvSize: Size, yuvScaledSize: Size): ByteArray {
        val i420 = ByteArray(yuvSize.width * yuvSize.height * 3 / 2)
        val gyuv = GYUV.a
        gyuv.gyuvNV12ToI420(nv12, yuvSize.width, yuvSize.height, i420)
        val scaled = ByteArray(yuvScaledSize.width * yuvScaledSize.height * 3 / 2)
        gyuv.gyuvI420Scale(i420, yuvSize.width, yuvSize.height, scaled, yuvScaledSize.width, yuvScaledSize.height, 3)
        val out = ByteArray(yuvScaledSize.width * yuvScaledSize.height * 3 / 2)
        gyuv.gyuvI420ToNV12(scaled, yuvScaledSize.width, yuvScaledSize.height, out)
        return out
    }

    fun e(nv12: ByteArray, yuvSize: Size, yuvScaledSize: Size, rot: Int, mirror: Boolean): ByteArray {
        val i420 = ByteArray(yuvSize.width * yuvSize.height * 3 / 2)
        val gyuv = GYUV.a
        gyuv.gyuvNV12ToI420(nv12, yuvSize.width, yuvSize.height, i420)
        val scaleSource = if (mirror) {
            val mirrored = ByteArray(yuvSize.width * yuvSize.height * 3 / 2)
            gyuv.gyuvI420Mirror(i420, yuvSize.width, -yuvSize.height, mirrored)
            StringBuilder().append("yuvNV12ScaleAndRotate: i420Mirrored=").append(mirrored).toString()
            mirrored
        } else {
            i420
        }
        val scaled = ByteArray(yuvScaledSize.width * yuvScaledSize.height * 3 / 2)
        gyuv.gyuvI420Scale(scaleSource, yuvSize.width, yuvSize.height, scaled, yuvScaledSize.width, yuvScaledSize.height, 3)
        val rotateSize = Size(yuvScaledSize.height, yuvScaledSize.width)
        val rotated = ByteArray(rotateSize.width * rotateSize.height * 3 / 2)
        gyuv.gyuvI420Rotate(scaled, yuvScaledSize.width, yuvScaledSize.height, rotated, rot)
        val out = ByteArray(rotateSize.width * rotateSize.height * 3 / 2)
        gyuv.gyuvI420ToNV12(rotated, rotateSize.width, rotateSize.height, out)
        return out
    }

    fun g(nv12: ByteArray, yuvSize: Size): ByteArray {
        val i420 = ByteArray(yuvSize.width * yuvSize.height * 3 / 2)
        val gyuv = GYUV.a
        gyuv.gyuvNV12ToI420(nv12, yuvSize.width, yuvSize.height, i420)
        val out = ByteArray(yuvSize.width * yuvSize.height * 3 / 2)
        gyuv.gyuvI420ToNV21(i420, yuvSize.width, yuvSize.height, out)
        return out
    }

    fun h(nv21: ByteArray, yuvSize: Size, yuvRotateSize: Size, rot: Int): ByteArray {
        val i420 = ByteArray(yuvSize.width * yuvSize.height * 3 / 2)
        val gyuv = GYUV.a
        gyuv.gyuvNV21ToI420(nv21, yuvSize.width, yuvSize.height, i420)
        val rotated = ByteArray(yuvRotateSize.width * yuvRotateSize.height * 3 / 2)
        gyuv.gyuvI420Rotate(i420, yuvSize.width, yuvSize.height, rotated, rot)
        val out = ByteArray(yuvRotateSize.width * yuvRotateSize.height * 3 / 2)
        gyuv.gyuvI420ToNV21(rotated, yuvRotateSize.width, yuvRotateSize.height, out)
        return out
    }

    fun i(yuy2: ByteArray, yuvSize: Size): ByteArray {
        val i420 = ByteArray(yuvSize.width * yuvSize.height * 3 / 2)
        val gyuv = GYUV.a
        gyuv.gyuvYUY2ToI420(yuy2, yuvSize.width, yuvSize.height, i420, 0)
        val out = ByteArray(yuvSize.width * yuvSize.height * 3 / 2)
        gyuv.gyuvI420ToNV12(i420, yuvSize.width, yuvSize.height, out)
        return out
    }
}
