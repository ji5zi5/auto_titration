package kr.auto.titration.mobile.pump

data class PumpCalibration(
    val mlPerStep: Double = 0.001,
    val maxVolumeMl: Double = 100.0,
    val maxRateMlPerS: Double = 1.0,
) {
    init {
        require(mlPerStep > 0.0) { "mlPerStep must be positive" }
        require(maxVolumeMl > 0.0) { "maxVolumeMl must be positive" }
        require(maxRateMlPerS > 0.0) { "maxRateMlPerS must be positive" }
    }
}

data class PumpSnapshot(
    val mode: String,
    val state: String,
    val runRateMlPerS: Double,
    val commandedStepCount: Long = 0,
    val confirmedStepCount: Long? = null,
    val firmwareVolumeMl: Double? = null,
    val lastStatusLine: String = "",
    val lastCommandResponse: String = "",
    val bluetoothDeviceName: String = "",
    val connected: Boolean = false,
    val warning: String = "",
)

data class PumpStatus(
    val steps: Long,
    val firmwareVolumeMl: Double,
    val rawLine: String,
)
