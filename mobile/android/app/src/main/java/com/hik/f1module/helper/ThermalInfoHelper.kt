package com.hik.f1module.helper

import android.util.Size
import com.sun.jna.Memory
import com.sun.jna.Native

/** Exact pointer-bearing frame layouts consumed synchronously by ThermalPlayer. */
class ThermalInfoHelper private constructor() {
    private var frameMemory: Memory? = null
    private var yuvMemory: Memory? = null

    fun getThermalDataInfo(privateInfoData: ByteArray, yuvData: ByteArray, yuvSize: Size, totalLength: Int = 0): ByteArray? =
        build(yuvData, yuvSize, privateInfoData, if (totalLength <= 0) yuvData.size else totalLength)

    fun getYuvThermalDataInfo(yuvData: ByteArray, yuvSize: Size): ByteArray? = build(yuvData, yuvSize, null, yuvData.size)

    private fun build(yuv: ByteArray, size: Size, privateInfo: ByteArray?, totalLength: Int): ByteArray? = runCatching {
        val yuvMem = Memory(yuv.size.toLong()).also { it.write(0, yuv, 0, yuv.size) }
        val length = maxOf(totalLength, YUV_INFO_SIZE + (privateInfo?.size ?: 0))
        val frame = Memory(length.toLong()).apply { clear() }
        frame.setPointer(0, yuvMem)
        val pointerSize = Native.POINTER_SIZE
        frame.setInt(pointerSize.toLong(), yuv.size)
        frame.setInt((pointerSize + 4).toLong(), 0)
        frame.setInt((pointerSize + 8).toLong(), size.width)
        frame.setInt((pointerSize + 12).toLong(), size.height)
        frame.setInt((pointerSize + 16).toLong(), 0)
        privateInfo?.let { frame.write(YUV_INFO_SIZE.toLong(), it, 0, minOf(it.size, length - YUV_INFO_SIZE)) }
        yuvMemory = yuvMem
        frameMemory = frame
        frame.getByteArray(0, length)
    }.getOrNull()

    fun release() { yuvMemory = null; frameMemory = null }
    companion object {
        private const val YUV_INFO_SIZE = 48
        @JvmField val INSTANCE = ThermalInfoHelper()
    }
}
