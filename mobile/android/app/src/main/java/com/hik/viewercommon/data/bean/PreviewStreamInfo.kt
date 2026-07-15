package com.hik.viewercommon.data.bean

/** Official-package pair returned by g3.d/g3.e packet processors. */
data class PreviewStreamInfo(
    var previewInfoData: PreviewInfoDataBean,
    var iStreamInfo: h3.a? = null,
) {
    @JvmName("getPreviewInfoDataCompat")
    fun getPreviewInfoData(): PreviewInfoDataBean = previewInfoData
    @JvmName("getIStreamInfoCompat")
    fun getIStreamInfo(): h3.a? = iStreamInfo
}
