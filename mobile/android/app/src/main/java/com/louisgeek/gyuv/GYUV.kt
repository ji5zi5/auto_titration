package com.louisgeek.gyuv

/** Exact Viewer JNI surface for libgyuv.so. */
class GYUV private constructor() {
    companion object {
        @JvmField val a: GYUV = GYUV()
        init { System.loadLibrary("gyuv") }
    }

    external fun gyuv420pTo422p(src: ByteArray, width: Int, height: Int, dst: ByteArray)
    external fun gyuv422pToNV16(src: ByteArray, width: Int, height: Int, dst: ByteArray)
    external fun gyuvI420Mirror(src: ByteArray, width: Int, height: Int, dst: ByteArray)
    external fun gyuvI420Rotate(src: ByteArray, width: Int, height: Int, dst: ByteArray, degree: Int)
    external fun gyuvI420Scale(src: ByteArray, width: Int, height: Int, dst: ByteArray, dstWidth: Int, dstHeight: Int, mode: Int)
    external fun gyuvI420ToNV12(src: ByteArray, width: Int, height: Int, dst: ByteArray)
    external fun gyuvI420ToNV21(src: ByteArray, width: Int, height: Int, dst: ByteArray)
    external fun gyuvNV12ToI420(src: ByteArray, width: Int, height: Int, dst: ByteArray)
    external fun gyuvNV16ToNV12(src: ByteArray, width: Int, height: Int, dst: ByteArray)
    external fun gyuvNV21ToI420(src: ByteArray, width: Int, height: Int, dst: ByteArray)
    external fun gyuvYUY2ToI420(src: ByteArray, width: Int, height: Int, dst: ByteArray, mode: Int)
}
