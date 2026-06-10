package kr.auto.titration.mobile.thermal

data class MatrixSummary(
    val avg: Double,
    val min: Double,
    val max: Double,
    val p50: Double? = null,
    val p95: Double? = null,
)

data class ThermalRawFrameSummary(
    val frameWidth: Int,
    val frameHeight: Int,
    val rawRoi: MatrixSummary? = null,
    val rawMatrix: MatrixSummary? = null,
    val rawValues: IntArray? = null,
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is ThermalRawFrameSummary) return false
        return frameWidth == other.frameWidth &&
            frameHeight == other.frameHeight &&
            rawRoi == other.rawRoi &&
            rawMatrix == other.rawMatrix &&
            if (rawValues == null) other.rawValues == null else other.rawValues?.let { rawValues.contentEquals(it) } == true
    }

    override fun hashCode(): Int {
        var result = frameWidth
        result = 31 * result + frameHeight
        result = 31 * result + (rawRoi?.hashCode() ?: 0)
        result = 31 * result + (rawMatrix?.hashCode() ?: 0)
        result = 31 * result + (rawValues?.contentHashCode() ?: 0)
        return result
    }
}

data class ThermalFeatureFrame(
    val frameWidth: Int,
    val frameHeight: Int,
    val status: ThermalStatus,
    val validationEvidence: Mini2ValidationEvidence,
    val rawRoi: MatrixSummary? = null,
    val rawMatrix: MatrixSummary? = null,
    val celsiusRoi: MatrixSummary? = null,
    val celsiusMatrix: MatrixSummary? = null,
) {
    init {
        require(frameWidth > 0 && frameHeight > 0) { "thermal frame size must be positive" }
        if (celsiusRoi != null || celsiusMatrix != null) {
            NoFakeCelsiusGuard.requireCelsiusAllowed(status, validationEvidence)
        }
    }

    fun toCsvMap(): Map<String, String> {
        val values = mutableMapOf<String, String>()
        values["thermal_calibrated"] = status.calibrated.toString()
        values["thermal_conversion_model"] = status.conversionModel
        values["thermal_matrix_shape"] = "${frameHeight}x${frameWidth}"
        rawRoi?.let {
            values["thermal_raw_roi_avg"] = it.avg.toString()
            values["thermal_raw_roi_min"] = it.min.toString()
            values["thermal_raw_roi_max"] = it.max.toString()
        }
        rawMatrix?.let {
            values["thermal_raw_mean"] = it.avg.toString()
            values["thermal_raw_min"] = it.min.toString()
            values["thermal_raw_max"] = it.max.toString()
        }
        if (status.calibrated && validationEvidence.mayEmitCelsius) {
            celsiusRoi?.let {
                values["thermal_roi_avg"] = it.avg.toString()
                values["thermal_roi_min"] = it.min.toString()
                values["thermal_roi_max"] = it.max.toString()
            }
            celsiusMatrix?.let {
                values["thermal_matrix_avg"] = it.avg.toString()
                values["thermal_matrix_min"] = it.min.toString()
                values["thermal_matrix_max"] = it.max.toString()
            }
        }
        return values
    }
}
