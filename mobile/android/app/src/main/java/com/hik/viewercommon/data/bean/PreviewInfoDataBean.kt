package com.hik.viewercommon.data.bean

/** Official-package F2 preview payload container recovered from Viewer 2.6.0 DEX. */
data class PreviewInfoDataBean(
    var byteArrSrc: ByteArray = ByteArray(0),
    var byteArrDst: ByteArray = ByteArray(0),
    var byteArrHead: ByteArray = ByteArray(0),
    var byteArrRawData: ByteArray = ByteArray(0),
    var byteArrRawAppendData: ByteArray = ByteArray(0),
    var byteArrYuvAppendData: ByteArray = ByteArray(0),
    var byteArrRawAppendLine2: ByteArray = ByteArray(0),
    var offByteArrRawData: ByteArray = ByteArray(0),
    var offByteArrRawAppendData: ByteArray = ByteArray(0),
) {
    @JvmName("getByteArrSrcCompat")
    fun getByteArrSrc(): ByteArray = byteArrSrc
    @JvmName("getByteArrDstCompat")
    fun getByteArrDst(): ByteArray = byteArrDst
    @JvmName("getByteArrHeadCompat")
    fun getByteArrHead(): ByteArray = byteArrHead
    @JvmName("getByteArrRawDataCompat")
    fun getByteArrRawData(): ByteArray = byteArrRawData
    @JvmName("getByteArrRawAppendDataCompat")
    fun getByteArrRawAppendData(): ByteArray = byteArrRawAppendData
    @JvmName("getByteArrYuvAppendDataCompat")
    fun getByteArrYuvAppendData(): ByteArray = byteArrYuvAppendData
    @JvmName("getByteArrRawAppendLine2Compat")
    fun getByteArrRawAppendLine2(): ByteArray = byteArrRawAppendLine2
    @JvmName("getOffByteArrRawDataCompat")
    fun getOffByteArrRawData(): ByteArray = offByteArrRawData
    @JvmName("getOffByteArrRawAppendDataCompat")
    fun getOffByteArrRawAppendData(): ByteArray = offByteArrRawAppendData

    override fun toString(): String = buildString {
        append("byteArrSrc ").append(byteArrSrc.size)
        append(" \n byteArrDst ").append(byteArrDst.size)
        append(" \n byteArrHead ").append(byteArrHead.size)
        append(" \n byteArrRawData ").append(byteArrRawData.size)
        append(" \n byteArrRawAppendData ").append(byteArrRawAppendData.size)
        append(" \n byteArrYuvAppendData ").append(byteArrYuvAppendData.size)
        append(" \n byteArrRawAppendLine2 ").append(byteArrRawAppendLine2.size)
        append(" \n offByteArrRawData ").append(offByteArrRawData.size)
        append(" \n offByteArrRawAppendData ").append(offByteArrRawAppendData.size)
        append(" \n ")
    }
}
