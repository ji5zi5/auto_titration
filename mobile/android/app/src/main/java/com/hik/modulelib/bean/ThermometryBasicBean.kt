package com.hik.modulelib.bean

data class ThermometryBasicBean(
    private var enableCenterTem: Boolean = false,
    private var enableHighTem: Boolean = false,
    private var enableLowTem: Boolean = false,
    private var enableAvgTem: Boolean = false,
    private var reflectiveTemp: String = "0.00",
    private var reflectiveEnable: Boolean = false,
    private var temperatureRange: Int = 0,
    private var temperatureUnit: Int = 0,
    private var emissivity: String = "0.00",
    private var distance: String = "0.00",
    private var alert: String = "0.00",
    private var alarm: String = "0.00",
    private var alarmEnable: Boolean = false,
    private var externalOpticsTransmit: Int = 0,
    private var externalOpticsWindowCorrection: Int = 1100,
    private var calibrationCoefficientEnabled: Boolean = false,
    private var calibrationCoefficient: Int = 2,
    private var thermometryStreamOverlay: Int = 0,
    private var thermometryInfoDisplayPosition: Int = 0,
) {
    fun getEnableCenterTem(): Boolean = enableCenterTem
    fun getEnableHighTem(): Boolean = enableHighTem
    fun getEnableLowTem(): Boolean = enableLowTem
    fun getEnableAvgTem(): Boolean = enableAvgTem
}
