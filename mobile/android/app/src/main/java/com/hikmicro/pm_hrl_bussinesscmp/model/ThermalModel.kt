package com.hikmicro.pm_hrl_bussinesscmp.model

import android.graphics.Bitmap

/** Official thermal model dependency emitted by z3.c.A. */
data class ThermalModel(
    private var nv12: ByteArray = ByteArray(0),
    private var width: Int = -1,
    private var height: Int = -1,
    private var bitmap: Bitmap = Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888),
    private var frameNumStamp: Int = 0,
) {
    fun getNv12(): ByteArray = nv12
    fun getWidth(): Int = width
    fun getHeight(): Int = height
    fun getBitmap(): Bitmap = bitmap
    fun getFrameNumStamp(): Int = frameNumStamp

    fun setNv12(value: ByteArray) { nv12 = value }
    fun setWidth(value: Int) { width = value }
    fun setHeight(value: Int) { height = value }
    fun setBitmap(value: Bitmap) { bitmap = value }
    fun setFrameNumStamp(value: Int) { frameNumStamp = value }
}
