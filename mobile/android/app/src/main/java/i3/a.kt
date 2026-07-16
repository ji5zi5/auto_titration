package i3

import com.hik.viewercommon.data.bean.PreviewInfoDataBean
import h3.a as StreamInfo

interface a {
    fun a(isFreezeData: Boolean, freezeCallback: ((Boolean) -> Unit)?, thawCallback: ((Boolean) -> Unit)?)
    fun b(streamInfo: StreamInfo?, previewInfoData: PreviewInfoDataBean, metadataCallback: ((Any?) -> Unit)?, overlayCallback: ((Any?, Any?, Any?, Any?, Any?) -> Unit)?)
    fun c(streamInfo: StreamInfo?, rawAppendData: ByteArray, callback: ((ByteArray) -> Unit)?)
}
