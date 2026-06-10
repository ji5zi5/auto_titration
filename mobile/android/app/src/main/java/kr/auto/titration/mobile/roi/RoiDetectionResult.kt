package kr.auto.titration.mobile.roi

import kr.auto.titration.mobile.vision.Roi
import kr.auto.titration.mobile.vision.RoiDetectionResult as VisionRoiDetectionResult

/** Runtime-capable contract mirror of Windows RoiDetectionResult. */
data class RoiDetectionResult(
    val roi: Roi?,
    val reason: String,
    val mask: RoiMask?,
    val ok: Boolean,
    val confidence: Double?,
    val target: String = "visible",
    val appliedNow: Boolean = ok,
    val status: String = if (ok) "applied" else "failed",
    val visibleMask: RoiMask? = if (target == "visible") mask else null,
    val thermalMask: RoiMask? = if (target == "thermal") mask else null,
)
{
    companion object {
        fun fromVision(result: VisionRoiDetectionResult): RoiDetectionResult {
            val primaryMask = result.visibleMask ?: result.thermalMask
            return RoiDetectionResult(
                roi = primaryMask?.bbox,
                reason = result.reason,
                mask = primaryMask?.let { RoiMask.fromVision(it) },
                ok = result.ok,
                confidence = result.confidence,
                target = result.target,
                appliedNow = result.appliedNow,
                status = result.status,
                visibleMask = result.visibleMask?.let { RoiMask.fromVision(it) },
                thermalMask = result.thermalMask?.let { RoiMask.fromVision(it) },
            )
        }
    }
}
