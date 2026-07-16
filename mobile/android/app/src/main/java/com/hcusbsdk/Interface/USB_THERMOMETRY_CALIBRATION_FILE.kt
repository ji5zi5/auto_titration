package com.hcusbsdk.Interface

const val USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES: Int = 1024 * 1024

/** Official public DTO for USB_GET_THERMOMETRY_CALIBRATION_FILE (command 2054). */
class USB_THERMOMETRY_CALIBRATION_FILE {
    @JvmField var pCalibrationFile: ByteArray = ByteArray(USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES)
    @JvmField var dwFileLenth: Int = USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES
}

/** Official common command condition DTO; 2054 requires byChannelID=1. */
class USB_COMMON_COND {
    @JvmField var byChannelID: Byte = 0
    @JvmField var byRes: ByteArray = ByteArray(63)
}
