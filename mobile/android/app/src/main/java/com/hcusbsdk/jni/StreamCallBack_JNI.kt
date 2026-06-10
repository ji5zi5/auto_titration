package com.hcusbsdk.jni

fun interface StreamCallBack_JNI {
    fun fStreamCallback_JNI(userId: Int, frameInfo: USB_FRAME_INFO?)
}
