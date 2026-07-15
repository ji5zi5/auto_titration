package com.hcusbsdk.jni

class HCUSBSDKByJNI private constructor() {
    init {
        try {
            System.loadLibrary("HCUSBSDK")
        } catch (_: UnsatisfiedLinkError) {
            // The official wrapper keeps the singleton available when loading fails.
        }
    }

    external fun USB_GetDeviceConfig(
        userId: Int,
        command: Int,
        condition: USB_CONFIG?,
        input: USB_CONFIG?,
        output: USB_CONFIG?,
    ): Boolean

    external fun USB_StartStreamCallback(
        userId: Int,
        callbackParam: USB_STREAM_CALLBACK_PARAM,
        callback: StreamCallBack_JNI,
    ): Int

    external fun USB_StopChannel(userId: Int, channel: Int): Boolean

    companion object {
        const val MAX_CONFIG_COND_BUFFER_SIZE: Int = 1_024
        const val MAX_CONFIG_INPUT_BUFFER_SIZE: Int = 1_048_576
        const val MAX_CONFIG_OUTPUT_BUFFER_SIZE: Int = 1_048_576
        const val MAX_FRAME_SIZE: Int = 8_294_400
        const val MAX_ROI_REGIONS: Int = 10

        @JvmField
        var UsbSdk: HCUSBSDKByJNI? = null

        @JvmStatic
        @Synchronized
        fun getInstance(): HCUSBSDKByJNI {
            if (UsbSdk == null) UsbSdk = HCUSBSDKByJNI()
            return requireNotNull(UsbSdk)
        }
    }
}
