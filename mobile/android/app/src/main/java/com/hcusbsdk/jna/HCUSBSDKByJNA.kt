package com.hcusbsdk.jna

import com.sun.jna.Callback
import com.sun.jna.Library
import com.sun.jna.Pointer
import com.sun.jna.Structure

interface HCUSBSDKByJNA : Library {
    fun interface FStreamCallBack : Callback {
        fun invoke(userId: Int, frameInfo: Pointer?, user: Pointer?)
    }

    fun USB_Init(): Boolean
    fun USB_Cleanup(): Boolean
    fun USB_GetLastError(): Int
    fun USB_GetDeviceCount(): Int
    fun USB_EnumDevices(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean
    fun USB_Login(loginInfo: Pointer, deviceRegRes: Pointer): Int
    fun USB_GetDeviceConfig(userId: Int, command: Int, inputInfo: Pointer, outputInfo: Pointer): Boolean
    fun USB_SetDeviceConfig(userId: Int, command: Int, inputInfo: Pointer, outputInfo: Pointer): Boolean
    fun USB_StartStreamCallback(userId: Int, callbackParam: Pointer): Int
    fun USB_StopChannel(userId: Int, channel: Int): Boolean
    fun USB_Logout(userId: Int): Boolean
}

@Structure.FieldOrder(
    "dwSize",
    "dwIndex",
    "dwVID",
    "dwPID",
    "szManufacturer",
    "szDeviceName",
    "szSerialNumber",
    "byHaveAudio",
    "byRes",
)
class USB_DEVICE_INFO : Structure() {
    @JvmField var dwSize: Int = 0
    @JvmField var dwIndex: Int = 0
    @JvmField var dwVID: Int = 0
    @JvmField var dwPID: Int = 0
    @JvmField var szManufacturer: ByteArray = ByteArray(32)
    @JvmField var szDeviceName: ByteArray = ByteArray(32)
    @JvmField var szSerialNumber: ByteArray = ByteArray(48)
    @JvmField var byHaveAudio: Byte = 0
    @JvmField var byRes: ByteArray = ByteArray(255)
}

@Structure.FieldOrder(
    "dwSize",
    "dwTimeout",
    "dwDevIndex",
    "dwVID",
    "dwPID",
    "szUserName",
    "szPassword",
    "szSerialNumber",
    "byLoginMode",
    "byRes2",
    "dwFd",
    "byRes",
)
class USB_USER_LOGIN_INFO : Structure() {
    @JvmField var dwSize: Int = 0
    @JvmField var dwTimeout: Int = 0
    @JvmField var dwDevIndex: Int = 0
    @JvmField var dwVID: Int = 0
    @JvmField var dwPID: Int = 0
    @JvmField var szUserName: ByteArray = ByteArray(32)
    @JvmField var szPassword: ByteArray = ByteArray(16)
    @JvmField var szSerialNumber: ByteArray = ByteArray(48)
    @JvmField var byLoginMode: Byte = 0
    @JvmField var byRes2: ByteArray = ByteArray(3)
    @JvmField var dwFd: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(248)
}

@Structure.FieldOrder(
    "dwSize",
    "szDeviceName",
    "szSerialNumber",
    "dwSoftwareVersion",
    "wYear",
    "byMonth",
    "byDay",
    "byRetryLoginTimes",
    "byRes1",
    "dwSurplusLockTime",
    "byRes",
)
class USB_DEVICE_REG_RES : Structure() {
    @JvmField var dwSize: Int = 0
    @JvmField var szDeviceName: ByteArray = ByteArray(32)
    @JvmField var szSerialNumber: ByteArray = ByteArray(48)
    @JvmField var dwSoftwareVersion: Int = 0
    @JvmField var wYear: Short = 0
    @JvmField var byMonth: Byte = 0
    @JvmField var byDay: Byte = 0
    @JvmField var byRetryLoginTimes: Byte = 0
    @JvmField var byRes1: ByteArray = ByteArray(3)
    @JvmField var dwSurplusLockTime: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(256)
}

@Structure.FieldOrder("dwSize", "dwStreamType", "fnStreamCallBack", "pUser", "byRes")
class USB_STREAM_CALLBACK_PARAM : Structure() {
    @JvmField var dwSize: Int = 0
    @JvmField var dwStreamType: Int = 0
    @JvmField var fnStreamCallBack: HCUSBSDKByJNA.FStreamCallBack? = null
    @JvmField var pUser: Pointer? = null
    @JvmField var byRes: ByteArray = ByteArray(128)
}

@Structure.FieldOrder("dwSize", "byChannelID", "bySID", "byRes")
class USB_COMMON_COND : Structure() {
    @JvmField var dwSize: Int = 0
    @JvmField var byChannelID: Byte = 0
    @JvmField var bySID: Byte = 0
    @JvmField var byRes: ByteArray = ByteArray(6)
}

@Structure.FieldOrder("lpCondBuffer", "dwCondBufferSize", "lpInBuffer", "dwInBufferSize", "byRes")
class USB_CONFIG_INPUT_INFO : Structure() {
    @JvmField var lpCondBuffer: Pointer? = null
    @JvmField var dwCondBufferSize: Int = 0
    @JvmField var lpInBuffer: Pointer? = null
    @JvmField var dwInBufferSize: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(48)
}

@Structure.FieldOrder("lpOutBuffer", "dwOutBufferSize", "byRes")
class USB_CONFIG_OUTPUT_INFO : Structure() {
    @JvmField var lpOutBuffer: Pointer? = null
    @JvmField var dwOutBufferSize: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(56)
}


@Structure.FieldOrder(
    "dwSize",
    "byFirmwareVersion",
    "byEncoderVersion",
    "byHardwareVersion",
    "byDeviceType",
    "byProtocolVersion",
    "bySerialNumber",
    "bySecondHardwareVersion",
    "byModuleID",
    "byDeviceID",
    "byDeviceAssembleType",
    "byManufacturer",
    "byLanguageType",
    "byDeviceClass",
    "byRes",
)
class USB_SYSTEM_DEVICE_INFO : Structure() {
    @JvmField var dwSize: Int = 0
    @JvmField var byFirmwareVersion: ByteArray = ByteArray(64)
    @JvmField var byEncoderVersion: ByteArray = ByteArray(64)
    @JvmField var byHardwareVersion: ByteArray = ByteArray(64)
    @JvmField var byDeviceType: ByteArray = ByteArray(64)
    @JvmField var byProtocolVersion: ByteArray = ByteArray(4)
    @JvmField var bySerialNumber: ByteArray = ByteArray(64)
    @JvmField var bySecondHardwareVersion: ByteArray = ByteArray(64)
    @JvmField var byModuleID: ByteArray = ByteArray(32)
    @JvmField var byDeviceID: ByteArray = ByteArray(64)
    @JvmField var byDeviceAssembleType: Byte = 0
    @JvmField var byManufacturer: Byte = 0
    @JvmField var byLanguageType: Byte = 0
    @JvmField var byDeviceClass: Byte = 0
    @JvmField var byRes: ByteArray = ByteArray(24)
}

@Structure.FieldOrder("dwVideoFormat", "dwWidth", "dwHeight", "dwFramerate", "dwBitrate", "dwParamType", "dwValue", "byRes")
class USB_VIDEO_PARAM : Structure() {
    @JvmField var dwVideoFormat: Int = 0
    @JvmField var dwWidth: Int = 0
    @JvmField var dwHeight: Int = 0
    @JvmField var dwFramerate: Int = 0
    @JvmField var dwBitrate: Int = 0
    @JvmField var dwParamType: Int = 0
    @JvmField var dwValue: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(128)
}

@Structure.FieldOrder("dwSize", "byVideoCodingType", "byRes")
class USB_THERMAL_STREAM_PARAM : Structure() {
    @JvmField var dwSize: Int = 0
    @JvmField var byVideoCodingType: Byte = 0
    @JvmField var byRes: ByteArray = ByteArray(15)
}

@Structure.FieldOrder("dwSize", "byEnable", "byRes")
class USB_CTRL_THERMAL_STREAM_PARAM : Structure() {
    @JvmField var dwSize: Int = 0
    @JvmField var byEnable: Byte = 0
    @JvmField var byRes: ByteArray = ByteArray(27)
}

@Structure.FieldOrder(
    "nStamp",
    "dwStreamType",
    "dwWidth",
    "dwHeight",
    "dwFrameRate",
    "dwFrameType",
    "dwDataType",
    "nFrameNum",
    "pBuf",
    "dwBufSize",
    "byRes",
)
class USB_FRAME_INFO(pointer: Pointer) : Structure(pointer) {
    @JvmField var nStamp: Int = 0
    @JvmField var dwStreamType: Int = 0
    @JvmField var dwWidth: Int = 0
    @JvmField var dwHeight: Int = 0
    @JvmField var dwFrameRate: Int = 0
    @JvmField var dwFrameType: Int = 0
    @JvmField var dwDataType: Int = 0
    @JvmField var nFrameNum: Int = 0
    @JvmField var pBuf: Pointer? = null
    @JvmField var dwBufSize: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(128)
}

@Structure.FieldOrder("dwSize", "dwBrightness", "byRes")
class USB_IMAGE_BRIGHTNESS : Structure() {
    @JvmField var dwSize: Int = 0
    @JvmField var dwBrightness: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(40)
}

@Structure.FieldOrder("dwSize", "dwContrast", "byRes")
class USB_IMAGE_CONTRAST : Structure() {
    @JvmField var dwSize: Int = 0
    @JvmField var dwContrast: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(40)
}

@Structure.FieldOrder(
    "dwSize",
    "byNoiseReduceMode",
    "byBirdWatchingMode",
    "byHighLightMode",
    "byHighLightLevel",
    "dwGeneralLevel",
    "dwFrameNoiseReduceLevel",
    "dwInterFrameNoiseReduceLevel",
    "byPaletteMode",
    "byLSEDetailEnabled",
    "byHookEdgeMode",
    "byHookEdgeLevel",
    "dwLSEDetailLevel",
    "byWideTemperatureMode",
    "byWideTemperatureWork",
    "byIspAgcMode",
    "byAISuperResolution",
    "dwWideTemperatureUpThreshold",
    "dwWideTemperatureDownThreshold",
    "byRes",
)
class USB_IMAGE_ENHANCEMENT : Structure() {
    @JvmField var dwSize: Int = 0
    @JvmField var byNoiseReduceMode: Byte = 0
    @JvmField var byBirdWatchingMode: Byte = 0
    @JvmField var byHighLightMode: Byte = 0
    @JvmField var byHighLightLevel: Byte = 0
    @JvmField var dwGeneralLevel: Int = 0
    @JvmField var dwFrameNoiseReduceLevel: Int = 0
    @JvmField var dwInterFrameNoiseReduceLevel: Int = 0
    @JvmField var byPaletteMode: Byte = 0
    @JvmField var byLSEDetailEnabled: Byte = 0
    @JvmField var byHookEdgeMode: Byte = 0
    @JvmField var byHookEdgeLevel: Byte = 0
    @JvmField var dwLSEDetailLevel: Int = 0
    @JvmField var byWideTemperatureMode: Byte = 0
    @JvmField var byWideTemperatureWork: Byte = 0
    @JvmField var byIspAgcMode: Byte = 0
    @JvmField var byAISuperResolution: Byte = 0
    @JvmField var dwWideTemperatureUpThreshold: Int = 0
    @JvmField var dwWideTemperatureDownThreshold: Int = 0
    @JvmField var byRes: ByteArray = ByteArray(40)
}

@Structure.FieldOrder(
    "struImageEnhancement",
    "bySkyAreaCullLevel",
    "byAGCMode",
    "byGaussianFilterEnabled",
    "byEdgePreservingFilterEnabled",
    "dwGaussianFilterCenterPoint",
    "dwBilateralFilterRadius",
    "dwBilateralFilterEdgeThreshold",
    "byBurnPreventionEnabled",
    "byBurnPreventionMode",
    "byRelativeHumidityThreshold",
    "bySharpenBoost",
    "dwBurnPreventionShutterCloseTime",
    "byBurnPreventionShutterControl",
    "byBurnPreventionRecovery",
    "byIsothermEnabled",
    "byRawDataNoiseReduceEnabled",
    "dwIsothermalUpperThreshold",
    "dwIsothermalLowerThreshold",
    "byIsothermalType",
    "byColorAlarmType",
    "dwColorAlarmUpperLimit",
    "dwColorAlarmLowerLimit",
    "dwRelativeHumidity",
    "dwAtmosphericTemperature",
    "byAutoShutEnabled",
    "byGeneralLevelDefault",
    "byGeneralLevelMin",
    "byGeneralLevelMax",
    "byRes",
)
class USB_IMAGE_ENHANCEMENT_EX : Structure() {
    @JvmField var struImageEnhancement: USB_IMAGE_ENHANCEMENT = USB_IMAGE_ENHANCEMENT()
    @JvmField var bySkyAreaCullLevel: Byte = 0
    @JvmField var byAGCMode: Byte = 0
    @JvmField var byGaussianFilterEnabled: Byte = 0
    @JvmField var byEdgePreservingFilterEnabled: Byte = 0
    @JvmField var dwGaussianFilterCenterPoint: Int = 0
    @JvmField var dwBilateralFilterRadius: Int = 0
    @JvmField var dwBilateralFilterEdgeThreshold: Int = 0
    @JvmField var byBurnPreventionEnabled: Byte = 0
    @JvmField var byBurnPreventionMode: Byte = 0
    @JvmField var byRelativeHumidityThreshold: Byte = 0
    @JvmField var bySharpenBoost: Byte = 0
    @JvmField var dwBurnPreventionShutterCloseTime: Int = 0
    @JvmField var byBurnPreventionShutterControl: Byte = 0
    @JvmField var byBurnPreventionRecovery: Byte = 0
    @JvmField var byIsothermEnabled: Byte = 0
    @JvmField var byRawDataNoiseReduceEnabled: Byte = 0
    @JvmField var dwIsothermalUpperThreshold: Int = 0
    @JvmField var dwIsothermalLowerThreshold: Int = 0
    @JvmField var byIsothermalType: Byte = 0
    @JvmField var byColorAlarmType: Byte = 0
    @JvmField var dwColorAlarmUpperLimit: Int = 0
    @JvmField var dwColorAlarmLowerLimit: Int = 0
    @JvmField var dwRelativeHumidity: Int = 0
    @JvmField var dwAtmosphericTemperature: Int = 0
    @JvmField var byAutoShutEnabled: Byte = 0
    @JvmField var byGeneralLevelDefault: Byte = 0
    @JvmField var byGeneralLevelMin: Byte = 0
    @JvmField var byGeneralLevelMax: Byte = 0
    @JvmField var byRes: ByteArray = ByteArray(902)
}
