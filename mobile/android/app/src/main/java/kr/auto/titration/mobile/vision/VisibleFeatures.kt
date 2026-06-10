package kr.auto.titration.mobile.vision

data class VisibleFeatures(
    val frameWidth: Int,
    val frameHeight: Int,
    val roi: Roi?,
    val rMean: Double? = null,
    val gMean: Double? = null,
    val bMean: Double? = null,
    val hMean: Double? = null,
    val sMean: Double? = null,
    val vMean: Double? = null,
    val hsvDelta: Double? = null,
    val colorDelta: Double? = null,
)
