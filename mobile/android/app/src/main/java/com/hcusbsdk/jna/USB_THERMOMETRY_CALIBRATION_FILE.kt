package com.hcusbsdk.jna

import com.sun.jna.Pointer
import com.sun.jna.Structure

@Structure.FieldOrder("pCalibrationFile", "dwFileLenth")
class USB_THERMOMETRY_CALIBRATION_FILE : Structure() {
    @JvmField var pCalibrationFile: Pointer? = null
    @JvmField var dwFileLenth: Int = 0
}
