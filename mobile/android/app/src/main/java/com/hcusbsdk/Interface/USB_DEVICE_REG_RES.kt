package com.hcusbsdk.Interface

class USB_DEVICE_REG_RES {
    @JvmField var dwSize: Int = 0
    @JvmField var szDeviceName: String = ""
    @JvmField var szSerialNumber: String = ""
    @JvmField var dwSoftwareVersion: Int = 0
    @JvmField var wYear: Short = 0
    @JvmField var byMonth: Byte = 0
    @JvmField var byDay: Byte = 0
    @JvmField var byRetryLoginTimes: Byte = 0
    @JvmField var byRes1: ByteArray = ByteArray(3)
    @JvmField var dwSurplusLockTime: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(256)
}
