package kr.auto.titration.mobile.vision

import org.json.JSONObject

/** Windows RoiDetectionResult-equivalent result object for Android bridge parity. */
data class RoiDetectionResult(
    val ok: Boolean,
    val target: String,
    val appliedNow: Boolean,
    val reason: String,
    val confidence: Double? = null,
    val visibleMask: RoiMask? = null,
    val thermalMask: RoiMask? = null,
    val pendingRequests: Int = 0,
    val pendingTarget: String = "",
    val status: String = if (ok) "applied" else "failed",
) {
    val primaryMask: RoiMask? get() = visibleMask ?: thermalMask

    fun toBridgeJson(): JSONObject {
        val roiJson = JSONObject()
            .put("pending_auto_candidate_requests", pendingRequests)
            .put("pending_auto_candidate_target", pendingTarget)
            .put("auto_roi_result_status", status)
            .put("auto_roi_result_reason", reason)
            .put("visible_roi_shape", visibleMask?.shape ?: "rectangle")
            .put("thermal_roi_shape", thermalMask?.shape ?: "rectangle")
            .put("visible_mask_source", visibleMask?.source ?: "")
            .put("thermal_mask_source", thermalMask?.source ?: "")
            .put("visible_mask_area_px", visibleMask?.areaPx ?: JSONObject.NULL)
            .put("thermal_mask_area_px", thermalMask?.areaPx ?: JSONObject.NULL)
            .put("mask_bbox", primaryMask?.bboxCsvString() ?: "")
            .put("mask_confidence", primaryMask?.confidence ?: JSONObject.NULL)
            .put("mask_component_count", primaryMask?.componentCount ?: JSONObject.NULL)
            .put("mask_stability", primaryMask?.stability ?: "")
        visibleMask?.let { mask ->
            roiJson
                .put("visible_mask_bbox", mask.bboxCsvString())
                .put("visible_mask_confidence", mask.confidence)
                .put("visible_mask_component_count", mask.componentCount)
                .put("visible_mask_stability", mask.stability)
        }
        thermalMask?.let { mask ->
            roiJson
                .put("thermal_mask_bbox", mask.bboxCsvString())
                .put("thermal_mask_confidence", mask.confidence)
                .put("thermal_mask_component_count", mask.componentCount)
                .put("thermal_mask_stability", mask.stability)
        }
        return JSONObject()
            .put("ok", ok)
            .put("target", target)
            .put("applied_now", appliedNow)
            .put("reason", reason)
            .put("confidence", confidence ?: JSONObject.NULL)
            .put("roi", roiJson)
    }
}

data class AutoRoiSettingsSnapshot(
    val generation: Long,
    val target: String,
    val visibleFrameId: Long,
    val thermalFrameId: Long = 0L,
    val requestedAtMs: Long,
)

data class AutoRoiWorkerResult(
    val settings: AutoRoiSettingsSnapshot,
    val detection: RoiDetectionResult,
    val completedAtMs: Long,
    val droppedPending: Int = 0,
)
