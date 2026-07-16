package com.hik.f1module.hcusbcamerasdk.callback

import com.sun.jna.Callback
import com.sun.jna.Pointer

fun interface IStreamCallback : Callback {
    fun invoke(data: Pointer?, length: Int): Int
}
