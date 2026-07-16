package kr.auto.titration.mobile.thermal

import org.json.JSONArray
import org.json.JSONObject

/**
 * Device-reported temperature summary that is allowed to reach UI status.
 *
 * This is deliberately a summary, not a full-frame/matrix conversion. The only
 * accepted scope/provenance for UI temperature is the validated global summary
 * embedded in the exact official OFFLINE_UPLOAD_HEADER.
 */
data class Mini2DeviceTemperatureSummary(
    val avgC: Double,
    val minC: Double,
    val maxC: Double,
    val requestedDisplayUnit: String,
    val requestedDisplayUnitCode: Int,
    val provenance: String = "device_global_summary",
    val scope: String = "device_global_summary",
) {
    init {
        require(provenance == "device_global_summary" && scope == "device_global_summary") {
            "Mini2DeviceTemperatureSummary may only represent provenance/scope=device_global_summary"
        }
    }

    // Backward-compatible aliases only: enumTempUnit is a requested display unit,
    // not evidence that packet summary floats are stored in that unit.
    val nativeUnit: String get() = requestedDisplayUnit
    val nativeUnitCode: Int get() = requestedDisplayUnitCode

    fun toJson(): JSONObject = JSONObject()
        .put("avg_c", avgC)
        .put("min_c", minC)
        .put("max_c", maxC)
        .put("requested_display_unit", requestedDisplayUnit)
        .put("requested_display_unit_code", requestedDisplayUnitCode)
        .put("native_unit", requestedDisplayUnit)
        .put("native_unit_code", requestedDisplayUnitCode)
        .put("native_unit_semantics", "backward_compatible_alias_for_requested_display_unit")
        .put("provenance", provenance)
        .put("scope", scope)
        .put("celsius_allowed", true)
        .put("full_matrix_celsius_allowed", false)
}

/**
 * Honest raw-stream status for the Android Mini2 path.
 *
 * The only Celsius values this model may expose are validated device-reported
 * summary values. Full-matrix/local raw-to-Celsius conversion remains blocked
 * unless independently proved; summary values must never be represented as a
 * matrix.
 */
data class Mini2InvalidPacketDiagnostic(
    val observedPacketSize: Int,
    val elapsedMs: Long,
    val allowedPacketSizes: Set<Int>,
    val userId: Int,
    val channel: Int,
    val fd: Int,
    val profileClass: String,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("observed_packet_size", observedPacketSize)
        .put("elapsed_ms", elapsedMs)
        .put("allowed_packet_sizes", JSONArray(allowedPacketSizes.toList()))
        .put("userId", userId)
        .put("user_id", userId)
        .put("channel", channel)
        .put("fd", fd)
        .put("profile_class", profileClass)
}

data class Mini2RawStreamStatus(
    val rawStreamStatus: String,
    val reason: String,
    val frameCounter: Long = 0,
    val frameWidth: Int = 0,
    val frameHeight: Int = 0,
    val transportFrameWidth: Int = 0,
    val transportFrameHeight: Int = 0,
    val previewRotationDegrees: Int = 0,
    val frameFormat: String = "unknown",
    val thermalPreviewDataUrl: String = "",
    val rawAvg: Double? = null,
    val rawMin: Int? = null,
    val rawMax: Int? = null,
    val nativeSymbolDiscovery: String = "not_run",
    val selectedBackend: String = "",
    val stageReport: String = "",
    val deviceRoute: String = "",
    val fd: Int = -1,
    val userId: Int = -1,
    val channel: Int = -1,
    val attemptDiagnostics: List<JSONObject> = emptyList(),
    val callbackEntryCount: Long = 0L,
    val callbackEntryDetail: String = "no_callback_entry",
    val invalidPacketDiagnostic: Mini2InvalidPacketDiagnostic? = null,
    val converterStatus: String = "converter_status_secondary_not_raw_stream_blocker",
    val deviceTemperatureSummary: Mini2DeviceTemperatureSummary? = null,
) {
    private fun allowedDeviceGlobalSummary(): Mini2DeviceTemperatureSummary? =
        deviceTemperatureSummary?.takeIf {
            it.provenance == "device_global_summary" && it.scope == "device_global_summary"
        }

    fun toJson(): JSONObject {
        val summary = allowedDeviceGlobalSummary()
        return JSONObject()
        .put("raw_stream_status", rawStreamStatus)
        .put("raw_frame_status", rawStreamStatus)
        .put("reason", reason)
        .put("frame_counter", frameCounter)
        .put("frame_width", frameWidth)
        .put("frame_height", frameHeight)
        .put("transport_frame_width", transportFrameWidth)
        .put("transport_frame_height", transportFrameHeight)
        .put("preview_rotation_degrees", previewRotationDegrees)
        .put("frame_format", frameFormat)
        .put("thermal_preview_data_url", thermalPreviewDataUrl)
        .put("raw_avg", rawAvg ?: JSONObject.NULL)
        .put("raw_min", rawMin ?: JSONObject.NULL)
        .put("raw_max", rawMax ?: JSONObject.NULL)
        .put("raw_delta", if (rawMin != null && rawMax != null) rawMax - rawMin else JSONObject.NULL)
        .put("celsius_allowed", summary != null)
        .put("temperature_avg_c", summary?.avgC ?: JSONObject.NULL)
        .put("temperature_min_c", summary?.minC ?: JSONObject.NULL)
        .put("temperature_max_c", summary?.maxC ?: JSONObject.NULL)
        .put("temperature_provenance", summary?.provenance ?: JSONObject.NULL)
        .put("temperature_scope", summary?.scope ?: JSONObject.NULL)
        .put("temperature_requested_display_unit", summary?.requestedDisplayUnit ?: JSONObject.NULL)
        .put("temperature_requested_display_unit_code", summary?.requestedDisplayUnitCode ?: JSONObject.NULL)
        .put("temperature_native_unit", summary?.requestedDisplayUnit ?: JSONObject.NULL)
        .put("temperature_native_unit_code", summary?.requestedDisplayUnitCode ?: JSONObject.NULL)
        .put("temperature_native_unit_semantics", if (summary != null) "backward_compatible_alias_for_requested_display_unit" else JSONObject.NULL)
        .put("temperature_summary", summary?.toJson() ?: JSONObject.NULL)
        .put("full_matrix_celsius_allowed", false)
        .put("full_matrix_temperature_status", "unproved_not_emitted")
        .put("converter_profile_status", "device_summary_allowed_when_validated_full_matrix_conversion_unproved")
        .put("native_symbol_discovery", nativeSymbolDiscovery)
        .put("selected_backend", selectedBackend)
        .put("stage_report", stageReport)
        .put("device_route", deviceRoute)
        .put("raw_stage_report", stageReport)
        .put("fd", fd)
        .put("userId", userId)
        .put("user_id", userId)
        .put("channel", channel)
        .put("error84_after_video_ok", error84AfterVideoOk())
        .put("observed_stream_facts", observedStreamFactsJson())
        .put("converter_status", converterStatus)
        .put("attempt_diagnostics", JSONArray(attemptDiagnostics))
        .put("java_interface_callback_entry_count", callbackEntryCount)
        .put("java_interface_callback_entry_detail", callbackEntryDetail)
        .put("invalid_packet_size_timeout", invalidPacketDiagnostic?.toJson() ?: JSONObject.NULL)
        .put("stream_diagnostics", JSONObject()
            .put("raw_stage_report", stageReport)
            .put("fd", fd)
            .put("userId", userId)
            .put("user_id", userId)
            .put("channel", channel)
            .put("error84_after_video_ok", error84AfterVideoOk())
            .put("observed_stream_facts", observedStreamFactsJson())
            .put("converter_status", converterStatus)
            .put("temperature_summary", summary?.toJson() ?: JSONObject.NULL)
            .put("temperature_provenance", summary?.provenance ?: JSONObject.NULL)
            .put("temperature_scope", summary?.scope ?: JSONObject.NULL)
            .put("temperature_requested_display_unit", summary?.requestedDisplayUnit ?: JSONObject.NULL)
            .put("temperature_requested_display_unit_code", summary?.requestedDisplayUnitCode ?: JSONObject.NULL)
            .put("temperature_native_unit", summary?.requestedDisplayUnit ?: JSONObject.NULL)
            .put("temperature_native_unit_code", summary?.requestedDisplayUnitCode ?: JSONObject.NULL)
            .put("temperature_native_unit_semantics", if (summary != null) "backward_compatible_alias_for_requested_display_unit" else JSONObject.NULL)
            .put("full_matrix_celsius_allowed", false)
            .put("full_matrix_temperature_status", "unproved_not_emitted")
            .put("attempt_diagnostics", JSONArray(attemptDiagnostics))
            .put("java_interface_callback_entry_count", callbackEntryCount)
            .put("java_interface_callback_entry_detail", callbackEntryDetail)
            .put("invalid_packet_size_timeout", invalidPacketDiagnostic?.toJson() ?: JSONObject.NULL)
        )
    }


    internal fun toJsonTemperatureFieldsForTest(): Map<String, Any?> {
        val summary = allowedDeviceGlobalSummary()
        return mapOf(
            "celsius_allowed" to (summary != null),
            "temperature_avg_c" to summary?.avgC,
            "temperature_min_c" to summary?.minC,
            "temperature_max_c" to summary?.maxC,
            "temperature_provenance" to summary?.provenance,
            "temperature_scope" to summary?.scope,
            "temperature_requested_display_unit" to summary?.requestedDisplayUnit,
            "temperature_requested_display_unit_code" to summary?.requestedDisplayUnitCode,
            "temperature_native_unit" to summary?.requestedDisplayUnit,
            "temperature_native_unit_code" to summary?.requestedDisplayUnitCode,
            "temperature_native_unit_semantics" to if (summary != null) "backward_compatible_alias_for_requested_display_unit" else null,
            "full_matrix_celsius_allowed" to false,
            "full_matrix_temperature_status" to "unproved_not_emitted",
        )
    }

    private fun error84AfterVideoOk(): Boolean =
        stageReport.contains("USB_SET_VIDEO_PARAM=ok", ignoreCase = true) &&
            Regex("""(?:error|lastError|last_error)=84\b""", RegexOption.IGNORE_CASE).containsMatchIn(stageReport)

    private fun observedStreamFactsJson(): JSONObject = JSONObject()
        .put("backend", selectedBackend)
        .put("route", deviceRoute)
        .put("raw_stream_status", rawStreamStatus)
        .put("start_result", observedStartResult())
        .put("frame_counter", frameCounter)

    private fun observedStartResult(): String = when {
        stageReport.contains("USB_StartStreamCallback=ok", ignoreCase = true) -> "USB_StartStreamCallback=ok"
        stageReport.contains("startStream=failed", ignoreCase = true) -> "startStream=failed"
        stageReport.contains("USB_StartStreamCallback=not_run", ignoreCase = true) -> "USB_StartStreamCallback=not_run"
        stageReport.isBlank() -> "not_reported"
        else -> "unknown"
    }

    companion object {
        fun blockedNoStreamEntrypoint(reason: String, discovery: String = "native_symbol_discovery_required") =
            Mini2RawStreamStatus(
                rawStreamStatus = "blocked_no_stream_entrypoint",
                reason = reason,
                nativeSymbolDiscovery = discovery,
            )

        fun blockedNativeUsbLibrary(reason: String, discovery: String = "native_symbol_discovery_required") =
            Mini2RawStreamStatus(
                rawStreamStatus = "blocked_native_usb_library",
                reason = reason,
                nativeSymbolDiscovery = discovery,
            )

        fun blockedUsbPermission(reason: String) = Mini2RawStreamStatus(
            rawStreamStatus = "blocked_usb_permission",
            reason = reason,
            nativeSymbolDiscovery = "permission_required_before_stream_discovery",
        )

        fun streamAttemptStarted(
            reason: String,
            frameCounter: Long = 0,
            frameWidth: Int = 0,
            frameHeight: Int = 0,
            transportFrameWidth: Int = 0,
            transportFrameHeight: Int = 0,
            previewRotationDegrees: Int = 0,
            frameFormat: String = "unknown",
            thermalPreviewDataUrl: String = "",
            rawAvg: Double? = null,
            rawMin: Int? = null,
            rawMax: Int? = null,
            discovery: String = "hikmicro_apk_extracted_jna_stream_callback_attempt",
            selectedBackend: String = "",
            stageReport: String = "",
            deviceRoute: String = "",
            fd: Int = -1,
            userId: Int = -1,
            channel: Int = -1,
            attemptDiagnostics: List<JSONObject> = emptyList(),
            callbackEntryCount: Long = 0L,
            callbackEntryDetail: String = "no_callback_entry",
            invalidPacketDiagnostic: Mini2InvalidPacketDiagnostic? = null,
            converterStatus: String = "converter_status_secondary_not_raw_stream_blocker",
            deviceTemperatureSummary: Mini2DeviceTemperatureSummary? = null,
        ) = Mini2RawStreamStatus(
            rawStreamStatus = if (frameCounter > 0) "raw_streaming_unverified" else "stream_attempt_started",
            reason = reason,
            frameCounter = frameCounter,
            frameWidth = frameWidth,
            frameHeight = frameHeight,
            transportFrameWidth = transportFrameWidth,
            transportFrameHeight = transportFrameHeight,
            previewRotationDegrees = previewRotationDegrees,
            frameFormat = frameFormat,
            thermalPreviewDataUrl = thermalPreviewDataUrl,
            rawAvg = rawAvg,
            rawMin = rawMin,
            rawMax = rawMax,
            nativeSymbolDiscovery = discovery,
            selectedBackend = selectedBackend,
            stageReport = stageReport,
            deviceRoute = deviceRoute,
            fd = fd,
            userId = userId,
            channel = channel,
            attemptDiagnostics = attemptDiagnostics,
            callbackEntryCount = callbackEntryCount,
            callbackEntryDetail = callbackEntryDetail,
            invalidPacketDiagnostic = invalidPacketDiagnostic,
            converterStatus = converterStatus,
            deviceTemperatureSummary = deviceTemperatureSummary,
        )

        fun blockedNativeStream(reason: String, discovery: String = "hikmicro_apk_extracted_jna_stream_callback_attempt") =
            Mini2RawStreamStatus(
                rawStreamStatus = "blocked_native_stream",
                reason = reason,
                nativeSymbolDiscovery = discovery,
            )
    }
}
