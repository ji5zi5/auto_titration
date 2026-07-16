package com.hik.modulelib

data class UsbModuleInfo(
    private var firmwareVersion: String = "",
    private var hardwareVersion: String = "",
    private var deviceType: String = "",
    private var serialNumber: String = "",
    private var deviceName: String = "",
    private var devType: Int = 0,
    private var secondHardwareVersion: String = "",
    private var moduleID: String = "",
    private var deviceID: String = "",
    private var deviceAssembleType: Int = 0,
    private var manufacturer: Int = 0,
    private var languageType: Int = 0,
    private var deviceClass: Int = 0,
    private var firmwareCode: String = "",
) {
    fun getFirmwareVersion(): String = firmwareVersion
    fun getHardwareVersion(): String = hardwareVersion
    fun getDeviceType(): String = deviceType
    fun getSerialNumber(): String = serialNumber
    fun getDeviceName(): String = deviceName
    fun getDevType(): Int = devType
    fun getSecondHardwareVersion(): String = secondHardwareVersion
    fun getModuleID(): String = moduleID
    fun getDeviceID(): String = deviceID
    fun getDeviceAssembleType(): Int = deviceAssembleType
    fun getManufacturer(): Int = manufacturer
    fun getLanguageType(): Int = languageType
    fun getDeviceClass(): Int = deviceClass
    fun getFirmwareCode(): String = firmwareCode
}
