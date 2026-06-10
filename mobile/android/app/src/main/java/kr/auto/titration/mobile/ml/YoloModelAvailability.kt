package kr.auto.titration.mobile.ml

data class YoloModelAvailability(
    val available: Boolean,
    val reason: String,
    val detail: String,
) {
    companion object {
        fun available(detail: String): YoloModelAvailability = YoloModelAvailability(
            available = true,
            reason = "yolo_model_available",
            detail = detail,
        )

        fun unavailable(reason: String, detail: String): YoloModelAvailability = YoloModelAvailability(
            available = false,
            reason = reason,
            detail = detail,
        )
    }
}
