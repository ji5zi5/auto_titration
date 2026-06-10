package kr.auto.titration.mobile.thermal

import org.json.JSONArray
import org.json.JSONObject

/** Honest status object for the Android Mini2 raw/temperature path. */
data class HikmicroConversionAttempt(
    val rawFrameStatus: String,
    val temperatureStatus: String,
    val celsiusAllowed: Boolean,
    val note: String,
    val symbols: List<String>,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("raw_frame_status", rawFrameStatus)
        .put("temperature_status", temperatureStatus)
        .put("celsius_allowed", celsiusAllowed)
        .put("note", note)
        .put("symbols", JSONArray(symbols))
}

/**
 * Gate for Android-side Mini2 raw/preview and raw-to-Celsius conversion.
 *
 * The analyzed vendor libraries expose candidates such as `MT_Gray2Temp`,
 * `MT_GetGray2TempTable`, `grayToTemperature`, `HC_USBCamera_StartPreview`, and
 * `USB_StartStreamCallback`. That proves a plausible path, not a validated
 * measurement. Therefore this object reports raw_unverified until both live USB
 * frames and fixture-vs-official Celsius comparison pass.
 */
object HikmicroTemperatureConversionAttempt {
    val candidateSymbols = listOf(
        "HC_USBCamera_StartPreview",
        "USB_StartStreamCallback",
        "JNI_GetJpegpicWithAppendData",
        "thermal_function_stream_realtime_init",
        "MT_Gray2Temp",
        "MT_GetGray2TempTable",
        "grayToTemperature",
    )

    fun describe(
        loadReport: NativeLibraryLoadReport,
        usbPermissionGranted: Boolean,
    ): HikmicroConversionAttempt {
        val evidence = Mini2ValidationEvidence(
            abiLoaded = loadReport.coreUsbLoaded || loadReport.coreTemperatureLoaded,
            fixtureCompared = false,
            liveStreamObserved = false,
            meanErrorC = null,
            maxPixelErrorC = null,
            licenseAllowsRedistribution = false,
            note = "Android converter is load-gated only; no live Mini2 frame fixture comparison has been run on this phone.",
        )
        val celsiusAllowed = evidence.mayEmitCelsius
        val rawStatus = when {
            !usbPermissionGranted -> "blocked_usb_permission"
            !loadReport.coreUsbLoaded -> "blocked_native_usb_library"
            else -> "raw_unverified"
        }
        val tempStatus = if (celsiusAllowed) {
            "calibrated"
        } else {
            "blocked_no_fake_celsius"
        }
        return HikmicroConversionAttempt(
            rawFrameStatus = rawStatus,
            temperatureStatus = tempStatus,
            celsiusAllowed = celsiusAllowed,
            note = "NoFakeCelsiusGuard blocks Celsius until fixtureCompared and liveStreamObserved are true; raw/preview remains raw_unverified.",
            symbols = candidateSymbols,
        )
    }

    @Suppress("unused")
    fun requireBeforePublishingCelsius(status: ThermalStatus, evidence: Mini2ValidationEvidence) {
        NoFakeCelsiusGuard.requireCelsiusAllowed(status, evidence)
    }
}
