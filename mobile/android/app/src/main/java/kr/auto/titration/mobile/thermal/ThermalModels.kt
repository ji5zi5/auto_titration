package kr.auto.titration.mobile.thermal

enum class ThermalCalibrationState {
    CALIBRATED,
    RAW_UNVERIFIED,
    BLOCKED,
}

data class ThermalStatus(
    val state: ThermalCalibrationState,
    val calibrated: Boolean,
    val reason: String,
    val conversionModel: String = "none",
    val backendName: String = "none",
) {
    companion object {
        fun blocked(reason: String) = ThermalStatus(
            state = ThermalCalibrationState.BLOCKED,
            calibrated = false,
            reason = reason,
        )

        fun rawUnverified(
            reason: String,
            conversionModel: String = "android_raw_unverified",
            backendName: String = "mini2_usb_probe",
        ) = ThermalStatus(
            state = ThermalCalibrationState.RAW_UNVERIFIED,
            calibrated = false,
            reason = reason,
            conversionModel = conversionModel,
            backendName = backendName,
        )

        fun calibrated(reason: String, conversionModel: String, backendName: String) = ThermalStatus(
            state = ThermalCalibrationState.CALIBRATED,
            calibrated = true,
            reason = reason,
            conversionModel = conversionModel,
            backendName = backendName,
        )
    }
}

/** Interface every Mini2 backend must satisfy before it can provide Celsius values. */
interface Mini2ThermalBackend {
    val status: ThermalStatus
    val validationEvidence: Mini2ValidationEvidence

    /** A backend may return true only after fixture + live validation gates pass. */
    fun isValidatedForCelsius(): Boolean = status.calibrated && validationEvidence.mayEmitCelsius
}
