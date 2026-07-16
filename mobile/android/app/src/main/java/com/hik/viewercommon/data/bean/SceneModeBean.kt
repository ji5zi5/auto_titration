package com.hik.viewercommon.data.bean

/** Official scene-mode value shape; defaults mirror the recovered Kotlin data-class contract. */
data class SceneModeBean(
    private val id: Int = 0,
    private val mode: Int = 0,
    private val name: String = "",
    private val emissivity: String = "",
    private val distance: String = "",
    private val reflectiveTemp: String = "",
    private val reflectiveEnable: Boolean = false,
    private val temperatureRange: Int = 0,
    private val temperatureUnit: Int = 0,
    private val alert: String = "",
    private val alarm: String = "",
    private val alarmEnable: Boolean = false,
    private val externalOpticsTransmit: Int = 0,
    private val externalOpticsWindowCorrection: Int = 1100,
    private val calibrationCoefficientEnabled: Boolean = false,
    private val calibrationCoefficient: Int = 2,
)
