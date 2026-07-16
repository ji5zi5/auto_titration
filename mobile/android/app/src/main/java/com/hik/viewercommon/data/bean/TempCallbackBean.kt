package com.hik.viewercommon.data.bean

/** Official Viewer data-class shape recovered from HIKMICRO Viewer 2.6.0 DEX. */
data class TempCallbackBean(
    private val tempMode: Int,
    private val max: Float,
    private val cen: Float,
    private val min: Float,
    private val maxChar: Char,
    private val cenChar: Char,
    private val minChar: Char,
    private var maxGrey: Int = 0,
    private var cenGrey: Int = 0,
    private var CAV: Int = 0,
    private var ShutterCav: Int = 0,
    private var Tec: Int = 0,
    private var Sens: Int = 0,
    private var Env: Int = 0,
    private var rawWithAppendData: ByteArray = ByteArray(0),
) {
    fun getTempMode(): Int = tempMode
    fun getMax(): Float = max
    fun getCen(): Float = cen
    fun getMin(): Float = min
    fun getMaxChar(): Char = maxChar
    fun getCenChar(): Char = cenChar
    fun getMinChar(): Char = minChar
    fun getMaxGrey(): Int = maxGrey
    fun getCenGrey(): Int = cenGrey
    fun getCAV(): Int = CAV
    fun getShutterCav(): Int = ShutterCav
    fun getTec(): Int = Tec
    fun getSens(): Int = Sens
    fun getEnv(): Int = Env
    fun getRawWithAppendData(): ByteArray = rawWithAppendData
}
