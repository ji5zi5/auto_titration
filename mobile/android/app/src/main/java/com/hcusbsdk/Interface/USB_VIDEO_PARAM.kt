package com.hcusbsdk.Interface

class USB_VIDEO_PARAM {
    @JvmField var dwVideoFormat: Int = 0
    @JvmField var dwWidth: Int = 0
    @JvmField var dwHeight: Int = 0
    @JvmField var dwFramerate: Int = 0
    @JvmField var dwBitrate: Int = 0
    @JvmField var dwParamType: Int = 0
    @JvmField var dwValue: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(128)
}
