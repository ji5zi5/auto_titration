package com.hcusbsdk.jni

private const val MAX_FRAME_SIZE = 10 * 1024 * 1024

class USB_FRAME_INFO {
    @JvmField var nStamp: Int = 0
    @JvmField var dwStreamType: Int = 0
    @JvmField var dwWidth: Int = 0
    @JvmField var dwHeight: Int = 0
    @JvmField var dwFrameRate: Int = 0
    @JvmField var dwFrameType: Int = 0
    @JvmField var dwDataType: Int = 0
    @JvmField var nFrameNum: Int = 0
    @JvmField var pBuf: ByteArray = ByteArray(MAX_FRAME_SIZE)
    @JvmField var dwBufSize: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(128)
}
