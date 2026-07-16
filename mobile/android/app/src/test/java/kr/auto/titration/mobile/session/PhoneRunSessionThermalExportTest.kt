package kr.auto.titration.mobile.session

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kr.auto.titration.mobile.data.CsvFeatureRow
import kr.auto.titration.mobile.data.CsvSchema
import kr.auto.titration.mobile.data.ExperimentConfig
import kr.auto.titration.mobile.data.StandaloneFeatureFrame
import kr.auto.titration.mobile.export.SessionExporter
import kr.auto.titration.mobile.thermal.MatrixSummary
import kr.auto.titration.mobile.thermal.ThermalRawFrameSummary
import kr.auto.titration.mobile.thermal.ThermalStatus
import kr.auto.titration.mobile.vision.RoiMask
import org.json.JSONObject

class PhoneRunSessionThermalExportTest {
    @Test
    fun csvPreservesRawStreamProfilePacketAndValidationWithoutFakeCelsius() {
        val config = ExperimentConfig(experimentId = "g004-test")
        val row = CsvFeatureRow(
            schemaVersion = CsvSchema.SCHEMA_VERSION,
            experimentId = "g004-test",
            frameId = 1L,
            timeS = 0.5,
            visibleTimeS = null,
            thermalTimeS = null,
            syncOffsetMs = null,
            syncQuality = "phone_single_clock_pending_thermal",
            injectedVolumeMl = 0.05,
            distanceToEquivalenceMl = null,
            pumpState = "running",
            pumpRateMlPerS = 0.1,
            visibleRMean = null,
            visibleGMean = null,
            visibleBMean = null,
            visibleHMean = null,
            visibleSMean = null,
            visibleVMean = null,
            visibleHsvDelta = null,
            visibleColorDelta = null,
            thermalCalibrated = false,
            thermalConversionModel = "android_raw_unverified",
            thermalStatusRawJson = "{\"temperature_avg_c\":null,\"celsius_allowed\":false}",
            thermalRawPacketClassification = "fixture_raw16_plane",
            thermalRawPacketStatus = "parsed_raw_matrix_unvalidated_celsius",
            thermalRawPacketSizeBytes = 98304,
            thermalSelectedProfileName = "f3.h",
            thermalSelectedProfileSize = "256x344",
            thermalSelectedProfileFps = 25,
            thermalSelectedProfileCoding = 12,
            thermalSelectedProfileStreamingNew = true,
            thermalSelectedProfileAllowedSizes = "101320;183496;98304",
            thermalConverterProfileStatus = "unresolved_fixture_or_live_stream_validation_missing",
            thermalConverterValidationState = "{\"may_emit_celsius\":false}",
            thermalCelsiusAllowed = false,
        )
        val csvMap = row.toCsvMap(config)

        assertEquals("fixture_raw16_plane", csvMap["thermal_raw_packet_classification"])
        assertEquals("parsed_raw_matrix_unvalidated_celsius", csvMap["thermal_raw_packet_status"])
        assertEquals("98304", csvMap["thermal_raw_packet_size_bytes"])
        assertEquals("f3.h", csvMap["thermal_selected_profile_name"])
        assertEquals("256x344", csvMap["thermal_selected_profile_size"])
        assertEquals("25", csvMap["thermal_selected_profile_fps"])
        assertEquals("12", csvMap["thermal_selected_profile_coding"])
        assertEquals("true", csvMap["thermal_selected_profile_streaming_new"])
        assertEquals("101320;183496;98304", csvMap["thermal_selected_profile_allowed_sizes"])
        assertEquals("false", csvMap["thermal_celsius_allowed"])
        assertEquals("false", csvMap["thermal_device_global_celsius_allowed"])
        assertEquals("", csvMap["thermal_device_global_avg_c"])
        assertEquals("", csvMap["thermal_roi_avg"])
        assertFalse("unavailable Celsius must not be coerced to 0.0", csvMap["thermal_status_raw_json"].orEmpty().contains("0.0"))

        val csv = SessionExporter.buildCsv(config, listOf(row))
        val header = csv.lines().first()
        assertTrue(header.contains("thermal_raw_packet_classification"))
        assertTrue(header.contains("thermal_device_global_avg_c"))
        assertTrue(csv.contains("fixture_raw16_plane"))
    }

    @Test
    fun validDeviceGlobalSummaryExportsExplicitCelsiusColumnsWithoutFillingRoiOrMatrixCelsius() {
        val session = recordingSession()
        session.updateThermalStreamSnapshot(fakeJson(
            "packet_classification" to "fixture_raw16_plane",
            "packet_status" to "parsed_raw_matrix_with_device_summary",
            "celsius_allowed" to true,
            "temperature_avg_c" to 23.75,
            "temperature_min_c" to 22.5,
            "temperature_max_c" to 25.0,
            "temperature_provenance" to "device_global_summary",
            "temperature_scope" to "device_global_summary",
            "temperature_requested_display_unit" to "Celsius",
            "temperature_requested_display_unit_code" to 0,
            "full_matrix_celsius_allowed" to false,
        ))

        val row = requireNotNull(session.recordFrame(rawFrame()))
        val csvMap = row.toCsvMap(session.config)

        assertEquals("true", csvMap["thermal_celsius_allowed"])
        assertEquals("23.750000", csvMap["thermal_device_global_avg_c"])
        assertEquals("22.500000", csvMap["thermal_device_global_min_c"])
        assertEquals("25.000000", csvMap["thermal_device_global_max_c"])
        assertEquals("true", csvMap["thermal_device_global_celsius_allowed"])
        assertEquals("device_global_summary", csvMap["thermal_device_global_provenance"])
        assertEquals("device_global_summary", csvMap["thermal_device_global_scope"])
        assertEquals("Celsius", csvMap["thermal_device_global_requested_display_unit"])
        assertEquals("0", csvMap["thermal_device_global_requested_display_unit_code"])
        assertEquals("false", csvMap["thermal_full_matrix_celsius_allowed"])
        assertEquals("", csvMap["thermal_roi_avg"])
        assertEquals("", csvMap["thermal_roi_min"])
        assertEquals("", csvMap["thermal_roi_max"])
        assertEquals("", csvMap["thermal_matrix_avg"])
    }

    @Test
    fun blockedOrInvalidDeviceSummaryExportsBlankSummaryFieldsAndFalseBooleans() {
        val session = recordingSession()
        session.updateThermalStreamSnapshot(fakeJson(
            "celsius_allowed" to true,
            "temperature_avg_c" to 0.0,
            "temperature_min_c" to 0.0,
            "temperature_max_c" to 0.0,
            "temperature_provenance" to "private_unvalidated_payload",
            "temperature_scope" to "private_unvalidated_payload",
            "temperature_requested_display_unit" to "Celsius",
            "temperature_requested_display_unit_code" to 0,
            "full_matrix_celsius_allowed" to false,
        ))

        val csvMap = requireNotNull(session.recordFrame(rawFrame())).toCsvMap(session.config)

        assertEquals("false", csvMap["thermal_celsius_allowed"])
        assertEquals("false", csvMap["thermal_device_global_celsius_allowed"])
        assertEquals("", csvMap["thermal_device_global_avg_c"])
        assertEquals("", csvMap["thermal_device_global_min_c"])
        assertEquals("", csvMap["thermal_device_global_max_c"])
        assertEquals("", csvMap["thermal_device_global_provenance"])
        assertEquals("", csvMap["thermal_device_global_scope"])
        assertEquals("", csvMap["thermal_device_global_requested_display_unit"])
        assertEquals("", csvMap["thermal_device_global_requested_display_unit_code"])
        assertEquals("false", csvMap["thermal_full_matrix_celsius_allowed"])
    }

    @Test
    fun deviceSummaryCoexistsWithRawMatrixAndRoiStats() {
        val session = recordingSession()
        session.updateThermalStreamSnapshot(fakeJson(
            "celsius_allowed" to true,
            "temperature_summary" to fakeJson(
                "avg_c" to 24.25,
                "min_c" to 23.0,
                "max_c" to 26.0,
                "provenance" to "device_global_summary",
                "scope" to "device_global_summary",
                "requested_display_unit" to "Celsius",
                "requested_display_unit_code" to 0,
            ),
            "full_matrix_celsius_allowed" to false,
        ))

        val csvMap = requireNotNull(session.recordFrame(rawFrame())).toCsvMap(session.config)

        assertEquals("24.250000", csvMap["thermal_device_global_avg_c"])
        assertEquals("150.000000", csvMap["thermal_raw_roi_avg"])
        assertEquals("100.000000", csvMap["thermal_raw_roi_min"])
        assertEquals("200.000000", csvMap["thermal_raw_roi_max"])
        assertEquals("250.000000", csvMap["thermal_raw_mean"])
        assertEquals("100.000000", csvMap["thermal_raw_min"])
        assertEquals("400.000000", csvMap["thermal_raw_max"])
        assertEquals("", csvMap["thermal_roi_avg"])
        assertEquals("", csvMap["thermal_matrix_avg"])
    }

    private fun fakeJson(vararg entries: Pair<String, Any?>): JSONObject = FakeJSONObject(mapOf(*entries))

    private class FakeJSONObject(private val values: Map<String, Any?>) : JSONObject() {
        override fun has(name: String?): Boolean = values.containsKey(name.orEmpty())

        override fun isNull(name: String?): Boolean = values[name.orEmpty()] == null

        override fun optBoolean(name: String?, fallback: Boolean): Boolean = values[name.orEmpty()] as? Boolean ?: fallback

        override fun optString(name: String?): String = values[name.orEmpty()]?.toString().orEmpty()

        override fun optInt(name: String?): Int = when (val value = values[name.orEmpty()]) {
            is Number -> value.toInt()
            is String -> value.toIntOrNull() ?: 0
            else -> 0
        }

        override fun optDouble(name: String?): Double = when (val value = values[name.orEmpty()]) {
            is Number -> value.toDouble()
            is String -> value.toDoubleOrNull() ?: Double.NaN
            else -> Double.NaN
        }

        override fun optJSONObject(name: String?): JSONObject? = values[name.orEmpty()] as? JSONObject

        override fun optJSONArray(name: String?): org.json.JSONArray? = values[name.orEmpty()] as? org.json.JSONArray

        override fun toString(): String = values.toString()
    }

    private fun recordingSession(): PhoneRunSession {
        val session = PhoneRunSession(ExperimentConfig(experimentId = "g004-test"))
        session.startSetup(session.config)
        session.markRoiLocked()
        session.startRecording(startedElapsedNanos = 0L, pumpRateMlPerS = 0.1)
        return session
    }

    private fun rawFrame(): StandaloneFeatureFrame = StandaloneFeatureFrame(
        runId = "g004-test",
        frameId = 1L,
        capturedElapsedNanos = 500_000_000L,
        visible = null,
        thermalStatus = ThermalStatus.rawUnverified("raw matrix only"),
        thermalRawFrame = ThermalRawFrameSummary(
            frameWidth = 2,
            frameHeight = 2,
            rawRoi = MatrixSummary(avg = 150.0, min = 100.0, max = 200.0),
            rawMatrix = MatrixSummary(avg = 250.0, min = 100.0, max = 400.0),
            rawValues = intArrayOf(100, 200, 300, 400),
        ),
        thermalMask = RoiMask(
            frameWidth = 2,
            frameHeight = 2,
            mask = booleanArrayOf(true, true, false, false),
            confidence = 0.9,
            source = "test_mask",
        ),
    )
}
