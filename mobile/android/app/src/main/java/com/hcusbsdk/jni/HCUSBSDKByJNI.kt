package com.hcusbsdk.jni

/**
 * Minimal official-package JNI shim for libHCUSBSDK.so. The original Viewer APK
 * routes JavaInterface.USB_StartStreamCallback through this class, so the app can
 * try the same callback wrapper after direct JNA fails.
 */
class HCUSBSDKByJNI private constructor() {
    external fun USB_StartStreamCallback(
        userId: Int,
        callbackParam: USB_STREAM_CALLBACK_PARAM,
        callback: StreamCallBack_JNI,
    ): Int

    external fun USB_StopChannel(userId: Int, channel: Int): Boolean

    companion object {
        @JvmField
        val UsbSdk: HCUSBSDKByJNI = HCUSBSDKByJNI()

        @JvmStatic
        fun getInstance(): HCUSBSDKByJNI = UsbSdk
    }
}
