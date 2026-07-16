package com.hik.viewer.bean

/** Exact eight-field diagnostic payload shape used by PreviewManagerII and its player listener. */
data class DiagnoseBean(
    val success: Boolean = false,
    val count: Int = 0,
    val src: ByteArray? = null,
    val dst: ByteArray? = null,
    val head: ByteArray? = null,
    val allData: ByteArray? = null,
    val srcFormat: String? = null,
    val dstFormat: String? = null,
)
