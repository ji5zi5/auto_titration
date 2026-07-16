package com.hcusbsdk.Interface

class USB_STREAM_CALLBACK_PARAM {
    @JvmField var dwStreamType: Int = 0
    @JvmField var fnStreamCallBack: FStreamCallBack? = null

    /**
     * Kotlin-source compatibility for older local callers that populated the
     * non-official field. The official Viewer DTO exposes no Java field for it.
     */
    var dwSize: Int
        get() = 0
        set(@Suppress("UNUSED_PARAMETER") value) = Unit
}
