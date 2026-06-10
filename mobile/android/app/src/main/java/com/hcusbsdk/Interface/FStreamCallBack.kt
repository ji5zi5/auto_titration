package com.hcusbsdk.Interface

fun interface FStreamCallBack {
    fun fStreamCallback(userId: Int, frameInfo: USB_FRAME_INFO?)
}
