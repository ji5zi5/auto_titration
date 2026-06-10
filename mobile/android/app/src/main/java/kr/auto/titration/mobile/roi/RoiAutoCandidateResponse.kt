package kr.auto.titration.mobile.roi

import kr.auto.titration.mobile.vision.RoiDetectionResult as VisionRoiDetectionResult
import org.json.JSONObject

/** Windows /api/roi-auto-candidate shaped Android bridge response. */
data class RoiAutoCandidateResponse(
    val ok: Boolean,
    val target: String,
    val appliedNow: Boolean,
    val reason: String,
    val confidence: Double?,
    val roi: JSONObject,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("ok", ok)
        .put("target", target)
        .put("applied_now", appliedNow)
        .put("reason", reason)
        .put("confidence", confidence ?: JSONObject.NULL)
        .put("roi", roi)

    companion object {
        fun fromDetection(
            result: VisionRoiDetectionResult,
            roiStatus: JSONObject = result.toBridgeJson().optJSONObject("roi") ?: JSONObject(),
        ): RoiAutoCandidateResponse = RoiAutoCandidateResponse(
            ok = result.ok,
            target = result.target,
            appliedNow = result.appliedNow,
            reason = result.reason,
            confidence = result.confidence,
            roi = roiStatus,
        )
    }
}
