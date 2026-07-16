package com.hik.viewercommon.data.bean

/** Official Viewer data-class shape recovered from HIKMICRO Viewer 2.6.0 DEX. */
data class OsdBgCallbackBean(
    private val enableOsdBg: Boolean,
    private val enableCenterTem: Boolean,
    private val enableHighTem: Boolean,
    private val enableLowTem: Boolean,
    private val osdBgRectNum: Int,
    private val longestSize: Float,
    private val kLongestSize: Float,
) {
    fun getEnableOsdBg(): Boolean = enableOsdBg
    fun getEnableCenterTem(): Boolean = enableCenterTem
    fun getEnableHighTem(): Boolean = enableHighTem
    fun getEnableLowTem(): Boolean = enableLowTem
    fun getOsdBgRectNum(): Int = osdBgRectNum
    fun getLongestSize(): Float = longestSize
    fun getKLongestSize(): Float = kLongestSize
}
