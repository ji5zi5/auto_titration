package com.hcusbsdk.Interface

import com.sun.jna.Callback

fun interface FStreamCallBack : Callback {
    fun invoke(userId: Int, frameInfo: USB_FRAME_INFO?)
}
