package com.hikmicro.pm_hrl_bussinesscmp.model

import android.graphics.Bitmap

/** Official rendered-frame snapshot returned by z3.c. */
data class Frame(private val time: Int, private val bitmap: Bitmap?) {
    fun getTime(): Int = time
    fun getBitmap(): Bitmap? = bitmap
    fun getByteArray(): ByteArray? = bitmap?.let(A3.f.a::a)
}
