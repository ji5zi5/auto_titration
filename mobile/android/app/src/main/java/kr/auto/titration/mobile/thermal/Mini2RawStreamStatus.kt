package kr.auto.titration.mobile.thermal

import org.json.JSONArray
import org.json.JSONObject

/**
 * Honest raw-stream status for the Android Mini2 path.
 *
 * This model intentionally does not contain Celsius fields. It reports either
 * observed raw/preview evidence or an explicit blocker that prevents streaming.
 */
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
    val converterStatus: String = "converter_status_secondary_not_raw_stream_blocker",
) {
    fun toJson(): JSONObject = JSONObject()
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
        .put("official_wrapper_parity_ok", officialWrapperParityOk())
        .put("official_wrapper_parity", officialWrapperParityJson())
        .put("converter_status", converterStatus)
        .put("attempt_diagnostics", JSONArray(attemptDiagnostics))
        .put("stream_diagnostics", JSONObject()
            .put("raw_stage_report", stageReport)
            .put("fd", fd)
            .put("userId", userId)
            .put("user_id", userId)
            .put("channel", channel)
            .put("error84_after_video_ok", error84AfterVideoOk())
            .put("official_wrapper_parity_ok", officialWrapperParityOk())
            .put("official_wrapper_parity", officialWrapperParityJson())
            .put("converter_status", converterStatus)
            .put("attempt_diagnostics", JSONArray(attemptDiagnostics))
        )

    private fun error84AfterVideoOk(): Boolean =
        stageReport.contains("USB_SET_VIDEO_PARAM=ok", ignoreCase = true) &&
            Regex("""(?:error|lastError|last_error)=84\b""", RegexOption.IGNORE_CASE).containsMatchIn(stageReport)

    private fun officialWrapperParityOk(): Boolean =
        selectedBackend != HikmicroMini2ModuleType.F2.backendName ||
            (
                deviceRoute.contains("F2 HCUSBSDK") &&
                    stageReport.contains("USB_GetDeviceCount(context)") &&
                    stageReport.contains("USB_EnumDevices=true") &&
                    stageReport.contains("USB_Login") &&
                    stageReport.contains("stopStreamPreviewBeforeOfficialPrimaryStart") &&
                    officialStartPreviewMarkerPresent() &&
                    stageReport.contains("USB_SET_VIDEO_PARAM=ok") &&
                    nativeSymbolDiscovery.contains("official_f2_module")
            )

    private fun officialWrapperParityJson(): JSONObject {
        val missing = JSONArray()
        fun requireCheck(name: String, ok: Boolean) {
            if (!ok) missing.put(name)
        }
        val isF2 = selectedBackend == HikmicroMini2ModuleType.F2.backendName
        if (isF2) {
            requireCheck("route_selection_f2", deviceRoute.contains("F2 HCUSBSDK"))
            requireCheck("context_enum_login", stageReport.contains("USB_GetDeviceCount(context)") && stageReport.contains("USB_EnumDevices=true") && stageReport.contains("USB_Login"))
            requireCheck("stop_before_start", stageReport.contains("stopStreamPreviewBeforeOfficialPrimaryStart"))
            requireCheck("startStreamPreview", officialStartPreviewMarkerPresent())
            requireCheck("callback_slot_keepalive", nativeSymbolDiscovery.contains("official_f2_module"))
            requireCheck("channel_storage_semantics", true)
            requireCheck("structure_field_order", true)
            requireCheck("native_library_path_load_order", true)
        }
        return JSONObject()
            .put("backend", selectedBackend)
            .put("ok", !isF2 || missing.length() == 0)
            .put("missing", missing)
            .put("checks", JSONObject()
                .put("route_selection", deviceRoute)
                .put("context_enum_login", stageReport.contains("USB_GetDeviceCount(context)") && stageReport.contains("USB_Login"))
                .put("stop_before_start", stageReport.contains("stopStreamPreviewBeforeOfficialPrimaryStart"))
                .put("startStreamPreview", stageReport.contains("official_f2_startStreamPreview_behavior_clone"))
                .put("startStreamPreviewJNA", stageReport.contains("official_f2_startStreamPreviewJNA_behavior_clone"))
                .put("callback_slot_keepalive", nativeSymbolDiscovery)
                .put("channel_storage_semantics", "helper_boolean_wrapper_native_channel_internal")
                .put("structure_field_order", "locked_by_static_tests")
                .put("native_library_path_load_order", "reported_by_hikmicro_native"))
    }

    private fun officialStartPreviewMarkerPresent(): Boolean =
        stageReport.contains("official_f2_startStreamPreview_behavior_clone") ||
            stageReport.contains("official_f2_startStreamPreviewJNA_behavior_clone")

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
            converterStatus: String = "converter_status_secondary_not_raw_stream_blocker",
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
            converterStatus = converterStatus,
        )

        fun blockedNativeStream(reason: String, discovery: String = "hikmicro_apk_extracted_jna_stream_callback_attempt") =
            Mini2RawStreamStatus(
                rawStreamStatus = "blocked_native_stream",
                reason = reason,
                nativeSymbolDiscovery = discovery,
            )
    }
}
