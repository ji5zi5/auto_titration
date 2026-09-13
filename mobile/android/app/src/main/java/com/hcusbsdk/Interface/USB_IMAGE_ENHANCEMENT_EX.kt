package com.hcusbsdk.Interface

class USB_IMAGE_ENHANCEMENT_EX {
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

    fun copyFrom(other: USB_IMAGE_ENHANCEMENT_EX) {
        struImageEnhancement.copyFrom(other.struImageEnhancement)
        bySkyAreaCullLevel = other.bySkyAreaCullLevel
        byAGCMode = other.byAGCMode
        byGaussianFilterEnabled = other.byGaussianFilterEnabled
        byEdgePreservingFilterEnabled = other.byEdgePreservingFilterEnabled
        dwGaussianFilterCenterPoint = other.dwGaussianFilterCenterPoint
        dwBilateralFilterRadius = other.dwBilateralFilterRadius
        dwBilateralFilterEdgeThreshold = other.dwBilateralFilterEdgeThreshold
        byBurnPreventionEnabled = other.byBurnPreventionEnabled
        byBurnPreventionMode = other.byBurnPreventionMode
        byRelativeHumidityThreshold = other.byRelativeHumidityThreshold
        bySharpenBoost = other.bySharpenBoost
        dwBurnPreventionShutterCloseTime = other.dwBurnPreventionShutterCloseTime
        byBurnPreventionShutterControl = other.byBurnPreventionShutterControl
        byBurnPreventionRecovery = other.byBurnPreventionRecovery
        byIsothermEnabled = other.byIsothermEnabled
        byRawDataNoiseReduceEnabled = other.byRawDataNoiseReduceEnabled
        dwIsothermalUpperThreshold = other.dwIsothermalUpperThreshold
        dwIsothermalLowerThreshold = other.dwIsothermalLowerThreshold
        byIsothermalType = other.byIsothermalType
        byColorAlarmType = other.byColorAlarmType
        dwColorAlarmUpperLimit = other.dwColorAlarmUpperLimit
        dwColorAlarmLowerLimit = other.dwColorAlarmLowerLimit
        dwRelativeHumidity = other.dwRelativeHumidity
        dwAtmosphericTemperature = other.dwAtmosphericTemperature
        byAutoShutEnabled = other.byAutoShutEnabled
        byGeneralLevelDefault = other.byGeneralLevelDefault
        byGeneralLevelMin = other.byGeneralLevelMin
        byGeneralLevelMax = other.byGeneralLevelMax
    }
}
