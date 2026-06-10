package com.hcusbsdk.Interface

class USB_THERMAL_STREAM_PARAM {
    @JvmField var dwSize: Int = 0
    @JvmField var byVideoCodingType: Byte = 0
    @JvmField var byRes: ByteArray = ByteArray(15)
}
