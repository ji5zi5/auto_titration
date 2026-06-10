package com.hcusbsdk.Interface

class USB_CTRL_THERMAL_STREAM_PARAM {
    @JvmField var dwSize: Int = 0
    @JvmField var byEnable: Byte = 0
    @JvmField var byRes: ByteArray = ByteArray(27)
}
