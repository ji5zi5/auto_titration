package kr.auto.titration.mobile.thermal

data class FixtureTolerance(
    val maxMeanErrorC: Double = 0.10,
    val maxPixelErrorC: Double = 0.50,
) {
    init {
        require(maxMeanErrorC >= 0.0) { "mean tolerance must be non-negative" }
        require(maxPixelErrorC >= 0.0) { "pixel tolerance must be non-negative" }
    }
}

data class Mini2ValidationEvidence(
    val abiLoaded: Boolean = false,
    val fixtureCompared: Boolean = false,
    val liveStreamObserved: Boolean = false,
    val meanErrorC: Double? = null,
    val maxPixelErrorC: Double? = null,
    val tolerance: FixtureTolerance = FixtureTolerance(),
    val licenseAllowsRedistribution: Boolean = false,
    val note: String = "",
) {
    val passesTechnicalGate: Boolean
        get() = abiLoaded &&
            fixtureCompared &&
            liveStreamObserved &&
            meanErrorC != null &&
            maxPixelErrorC != null &&
            meanErrorC <= tolerance.maxMeanErrorC &&
            maxPixelErrorC <= tolerance.maxPixelErrorC

    val passesPublicReleaseGate: Boolean
        get() = licenseAllowsRedistribution

    val mayEmitCelsius: Boolean
        get() = passesTechnicalGate
}

object NoFakeCelsiusGuard {
    fun requireCelsiusAllowed(status: ThermalStatus, evidence: Mini2ValidationEvidence) {
        require(status.calibrated && evidence.mayEmitCelsius) {
            "Celsius thermal fields require calibrated status and passing Mini2 validation evidence"
        }
    }
}
