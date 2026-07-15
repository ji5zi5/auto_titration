package com.hik.library.player

/** Exact Viewer PicDataBean value shape. */
data class d(
    private var frameTime: Int,
    private var picData: ByteArray?,
) {
    fun a(): Int = frameTime
    fun b(): ByteArray? = picData
}
