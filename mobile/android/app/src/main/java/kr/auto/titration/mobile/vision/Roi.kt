package kr.auto.titration.mobile.vision

data class Roi(
    val x: Int,
    val y: Int,
    val width: Int,
    val height: Int,
    val shape: String = "rectangle",
) {
    init {
        require(x >= 0 && y >= 0) { "ROI origin must be non-negative" }
        require(width > 0 && height > 0) { "ROI size must be positive" }
    }
}
