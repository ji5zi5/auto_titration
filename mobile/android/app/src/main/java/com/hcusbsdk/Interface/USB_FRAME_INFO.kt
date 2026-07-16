package com.hcusbsdk.Interface

private const val MAX_FRAME_SIZE = 10 * 1024 * 1024

/**
 * Official public frame DTO used by com.hcusbsdk.Interface.FStreamCallBack.
 *
 * The JNI/JNA callback wrappers copy their native frame objects into this
 * byte-array DTO before invoking the app callback. Keeping this class separate
 * from com.hcusbsdk.jni.USB_FRAME_INFO matches the Viewer APK package shape.
 */
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

    /**
     * Kotlin-source compatibility for local adapters. The official public DTO
     * has no Java-visible byRes field; native-only DTOs retain byRes[128].
     */
    var byRes: ByteArray
        get() = ByteArray(0)
        set(@Suppress("UNUSED_PARAMETER") value) = Unit
}
