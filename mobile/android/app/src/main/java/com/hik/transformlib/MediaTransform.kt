package com.hik.transformlib

/** Exact native MediaTransform descriptors from Viewer 2.6.0. */
object MediaTransform {
    init { System.loadLibrary("MediaTransform") }
    @JvmStatic external fun startAudioTransform(data: ByteArray, timestamp: Long, length: Int): Int
    @JvmStatic external fun startVideoTransform(data: ByteArray, timestamp: Long, length: Int, width: Int, height: Int): Int
    @JvmStatic external fun stopTransform(): Int
    @JvmStatic external fun transformInit(filePath: String): Int
}
