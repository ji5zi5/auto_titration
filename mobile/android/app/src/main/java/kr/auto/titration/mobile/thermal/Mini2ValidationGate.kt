package kr.auto.titration.mobile.thermal

import org.json.JSONObject

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

    val converterProfileStatus: String
        get() = if (mayEmitCelsius) "validated" else "unresolved_fixture_or_live_stream_validation_missing"

    fun toJson(): JSONObject = JSONObject()
        .put("abi_loaded", abiLoaded)
        .put("fixture_compared", fixtureCompared)
        .put("live_stream_observed", liveStreamObserved)
        .put("mean_error_c", meanErrorC ?: JSONObject.NULL)
        .put("max_pixel_error_c", maxPixelErrorC ?: JSONObject.NULL)
        .put("max_mean_error_c_tolerance", tolerance.maxMeanErrorC)
        .put("max_pixel_error_c_tolerance", tolerance.maxPixelErrorC)
        .put("license_allows_redistribution", licenseAllowsRedistribution)
        .put("passes_technical_gate", passesTechnicalGate)
        .put("passes_public_release_gate", passesPublicReleaseGate)
        .put("may_emit_celsius", mayEmitCelsius)
        .put("converter_profile_status", converterProfileStatus)
        .put("note", note)
}

object NoFakeCelsiusGuard {
    fun requireCelsiusAllowed(status: ThermalStatus, evidence: Mini2ValidationEvidence) {
        require(status.calibrated && evidence.mayEmitCelsius) {
            "Celsius thermal fields require calibrated status and passing Mini2 validation evidence"
        }
    }

    fun nullableCelsius(value: Double?, status: ThermalStatus, evidence: Mini2ValidationEvidence): Double? {
        return if (value != null && status.calibrated && evidence.mayEmitCelsius) value else null
    }
}
