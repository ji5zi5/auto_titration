package com.hcusbsdk.Interface

class USB_STREAM_CALLBACK_PARAM {
    @JvmField var dwSize: Int = 0
    @JvmField var dwStreamType: Int = 0
    @JvmField var fnStreamCallBack: FStreamCallBack? = null
    @JvmField var byRes: ByteArray = ByteArray(128)
}
