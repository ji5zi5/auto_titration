package com.hcusbsdk.Interface

class USB_IMAGE_ENHANCEMENT {
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

    fun copyFrom(other: USB_IMAGE_ENHANCEMENT) {
        byNoiseReduceMode = other.byNoiseReduceMode
        byBirdWatchingMode = other.byBirdWatchingMode
        byHighLightMode = other.byHighLightMode
        byHighLightLevel = other.byHighLightLevel
        dwGeneralLevel = other.dwGeneralLevel
        dwFrameNoiseReduceLevel = other.dwFrameNoiseReduceLevel
        dwInterFrameNoiseReduceLevel = other.dwInterFrameNoiseReduceLevel
        byPaletteMode = other.byPaletteMode
        byLSEDetailEnabled = other.byLSEDetailEnabled
        byHookEdgeMode = other.byHookEdgeMode
        byHookEdgeLevel = other.byHookEdgeLevel
        dwLSEDetailLevel = other.dwLSEDetailLevel
        byWideTemperatureMode = other.byWideTemperatureMode
        byWideTemperatureWork = other.byWideTemperatureWork
        byIspAgcMode = other.byIspAgcMode
        byAISuperResolution = other.byAISuperResolution
        dwWideTemperatureUpThreshold = other.dwWideTemperatureUpThreshold
        dwWideTemperatureDownThreshold = other.dwWideTemperatureDownThreshold
    }
}
