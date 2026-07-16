package com.hikmicro.pm_hrl_bussinesscmp.model

import android.util.Size
import com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy

/** Official frame-info dependency passed to z3.c.A. */
data class FrameInfo(
    private val nv12ByteArray: ByteArray,
    private val yuvSize: Size,
    private val degree: Int,
    private val thermalPrivateInfo: HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO,
    private val type: Int = 12,
    private val frameNumStamp: Int = -1,
) {
    fun getNv12ByteArray(): ByteArray = nv12ByteArray
    fun getYuvSize(): Size = yuvSize
    fun getDegree(): Int = degree
    fun getThermalPrivateInfo(): HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO = thermalPrivateInfo
    fun getType(): Int = type
    fun getFrameNumStamp(): Int = frameNumStamp

    fun convertBitmap(bitmap: android.graphics.Bitmap): android.graphics.Bitmap {
        return if (degree == 90 || degree == 270) {
            if (bitmap.width < bitmap.height) {
                android.graphics.Bitmap.createScaledBitmap(bitmap, bitmap.height, bitmap.width, true)
            } else {
                bitmap
            }
        } else if (bitmap.width > bitmap.height) {
            android.graphics.Bitmap.createScaledBitmap(bitmap, bitmap.height, bitmap.width, true)
        } else {
            bitmap
        }
    }
}
