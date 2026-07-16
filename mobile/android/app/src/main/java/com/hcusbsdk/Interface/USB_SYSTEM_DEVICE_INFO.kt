package com.hcusbsdk.Interface

/** Official Java DTO for USB_GET_SYSTEM_DEVICE_INFO (command 2011). */
class USB_SYSTEM_DEVICE_INFO {
    @JvmField var byFirmwareVersion: String = ""
    @JvmField var byEncoderVersion: String = ""
    @JvmField var byHardwareVersion: String = ""
    @JvmField var byDeviceType: String = ""
    @JvmField var byProtocolVersion: String = ""
    @JvmField var bySerialNumber: String = ""
    @JvmField var bySecondHardwareVersion: String = ""
    @JvmField var byModuleID: String = ""
    @JvmField var byDeviceID: String = ""
    @JvmField var byDeviceAssembleType: Byte = 0
    @JvmField var byManufacturer: Byte = 0
    @JvmField var byLanguageType: Byte = 0
    @JvmField var byDeviceClass: Byte = 0
}
