package kr.auto.titration.mobile.data

import kr.auto.titration.mobile.thermal.ThermalStatus
import kr.auto.titration.mobile.thermal.ThermalRawFrameSummary
import kr.auto.titration.mobile.vision.VisibleFeatures
import kr.auto.titration.mobile.vision.RoiMask

/** One phone-local sensor feature row before CSV serialization. */
data class StandaloneFeatureFrame(
    val runId: String,
    val frameId: Long,
    val capturedElapsedNanos: Long,
    val visible: VisibleFeatures?,
    val thermalStatus: ThermalStatus,
    val thermalRawFrame: ThermalRawFrameSummary? = null,
    val visibleMask: RoiMask? = null,
    val thermalMask: RoiMask? = null,
    val autoRoiResultStatus: String = "",
    val autoRoiResultReason: String = "",
    val autoRoiDroppedPending: Int = 0,
    val pendingAutoCandidateRequests: Int = 0,
    val pendingAutoCandidateTarget: String = "",
) {
    val timeS: Double = capturedElapsedNanos / 1_000_000_000.0
}
