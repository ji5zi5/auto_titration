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
import kr.auto.titration.mobile.enrichedThermalRawStreamSnapshotForSession
import kr.auto.titration.mobile.thermal.MatrixSummary
import kr.auto.titration.mobile.thermal.OfficialF2ScalarMeasurementState
import kr.auto.titration.mobile.thermal.OfficialF2ScalarMeasurementStatus
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
    fun deviceGlobalSummaryExportsDiagnosticColumnsWithoutGrantingGenericCelsius() {
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

        assertEquals("false", csvMap["thermal_celsius_allowed"])
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
    fun unorderedDeviceSummaryFailsClosedAtCsvBoundary() {
        val session = recordingSession()
        session.updateThermalStreamSnapshot(fakeJson(
            "celsius_allowed" to true,
            "temperature_avg_c" to 35.0,
            "temperature_min_c" to 20.0,
            "temperature_max_c" to 30.0,
            "temperature_provenance" to "device_global_summary",
            "temperature_scope" to "device_global_summary",
            "full_matrix_celsius_allowed" to false,
        ))

        val csvMap = requireNotNull(session.recordFrame(rawFrame())).toCsvMap(session.config)

        assertEquals("false", csvMap["thermal_celsius_allowed"])
        assertEquals("false", csvMap["thermal_device_global_celsius_allowed"])
        assertEquals("", csvMap["thermal_device_global_avg_c"])
        assertEquals("", csvMap["thermal_device_global_min_c"])
        assertEquals("", csvMap["thermal_device_global_max_c"])
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


    @Test
    fun matchingOfficialMeasurementExportsValidatedCurrentFrameMetadataWithoutTouchingDeviceGlobalSummary() {
        val session = recordingSession()
        session.updateThermalStreamSnapshot(fakeJson(
            "frame_counter" to 77L,
            "celsius_allowed" to false,
            "official_measurement_status" to "READY",
            "official_measurement_reason" to "official_f2_scalar_measurement_ready",
            "official_measurement_frame_counter" to 77L,
            "official_temperature_avg_c" to 24.125,
            "official_temperature_min_c" to 20.5,
            "official_temperature_max_c" to 29.75,
            "official_temperature_center_c" to 25.0,
            "official_temperature_provenance" to "official_f2_analyzer_measurement_stats",
            "official_temperature_scope" to "rectangle",
            "official_measurement_matches_current_frame" to true,
            "official_measurement_temporal_scope" to "current_frame",
            "official_measurement_age_frames" to 0L,
            "official_full_matrix_celsius_allowed" to false,
            "temperature_avg_c" to 99.0,
            "temperature_provenance" to "private_unvalidated_payload",
        ))

        val csvMap = requireNotNull(session.recordFrame(rawFrame())).toCsvMap(session.config)

        assertEquals("READY", csvMap["official_measurement_status"])
        assertEquals("official_f2_scalar_measurement_ready", csvMap["official_measurement_reason"])
        assertEquals("77", csvMap["official_measurement_frame_counter"])
        assertEquals("24.125000", csvMap["official_temperature_avg_c"])
        assertEquals("20.500000", csvMap["official_temperature_min_c"])
        assertEquals("29.750000", csvMap["official_temperature_max_c"])
        assertEquals("25.000000", csvMap["official_temperature_center_c"])
        assertEquals("official_f2_analyzer_measurement_stats", csvMap["official_temperature_provenance"])
        assertEquals("rectangle", csvMap["official_temperature_scope"])
        assertEquals("true", csvMap["official_measurement_matches_current_frame"])
        assertEquals("current_frame", csvMap["official_measurement_temporal_scope"])
        assertEquals("0", csvMap["official_measurement_age_frames"])
        assertEquals("false", csvMap["official_full_matrix_celsius_allowed"])
        assertEquals("true", csvMap["thermal_celsius_allowed"])
        assertEquals("false", csvMap["thermal_device_global_celsius_allowed"])
        assertEquals("", csvMap["thermal_device_global_avg_c"])
        assertEquals("", csvMap["thermal_roi_avg"])
        assertEquals("", csvMap["thermal_matrix_avg"])
    }

    @Test
    fun staleOfficialMeasurementRetainsFiniteStatsAndExportsComputedPositiveAge() {
        val session = recordingSession()
        session.updateThermalStreamSnapshot(officialMeasurementJson(
            currentFrameCounter = 80L,
            measurementFrameCounter = 77L,
            publishedMatchesCurrentFrame = false,
            publishedTemporalScope = "last_completed_measurement",
            publishedAgeFrames = 3L,
        ))

        val csvMap = requireNotNull(session.recordFrame(rawFrame())).toCsvMap(session.config)

        assertEquals("READY", csvMap["official_measurement_status"])
        assertEquals("77", csvMap["official_measurement_frame_counter"])
        assertEquals("24.125000", csvMap["official_temperature_avg_c"])
        assertEquals("false", csvMap["official_measurement_matches_current_frame"])
        assertEquals("last_completed_measurement", csvMap["official_measurement_temporal_scope"])
        assertEquals("3", csvMap["official_measurement_age_frames"])
        assertEquals("false", csvMap["official_full_matrix_celsius_allowed"])
        assertEquals("false", csvMap["thermal_celsius_allowed"])
        assertEquals("false", csvMap["thermal_device_global_celsius_allowed"])
        assertEquals("", csvMap["thermal_device_global_avg_c"])
    }

    @Test
    fun malformedCounterAndInconsistentPublishedMetadataFailClosedForCurrentPromotion() {
        val malformedCounterSession = recordingSession()
        malformedCounterSession.updateThermalStreamSnapshot(officialMeasurementJson(
            currentFrameCounter = "not-a-counter",
            measurementFrameCounter = 77L,
            publishedMatchesCurrentFrame = true,
            publishedTemporalScope = "current_frame",
            publishedAgeFrames = 0L,
        ))

        val malformedCsvMap = requireNotNull(malformedCounterSession.recordFrame(rawFrame()))
            .toCsvMap(malformedCounterSession.config)

        assertEquals("", malformedCsvMap["official_temperature_avg_c"])
        assertEquals("", malformedCsvMap["official_temperature_provenance"])
        assertEquals("", malformedCsvMap["official_measurement_matches_current_frame"])
        assertEquals("", malformedCsvMap["official_measurement_temporal_scope"])
        assertEquals("", malformedCsvMap["official_measurement_age_frames"])

        val inconsistentMetadataSession = recordingSession()
        inconsistentMetadataSession.updateThermalStreamSnapshot(officialMeasurementJson(
            currentFrameCounter = 77L,
            measurementFrameCounter = 77L,
            publishedMatchesCurrentFrame = true,
            publishedTemporalScope = "last_completed_measurement",
            publishedAgeFrames = 0L,
        ))

        val inconsistentCsvMap = requireNotNull(inconsistentMetadataSession.recordFrame(rawFrame()))
            .toCsvMap(inconsistentMetadataSession.config)

        assertEquals("24.125000", inconsistentCsvMap["official_temperature_avg_c"])
        assertEquals("false", inconsistentCsvMap["official_measurement_matches_current_frame"])
        assertEquals("last_completed_measurement", inconsistentCsvMap["official_measurement_temporal_scope"])
        assertEquals("0", inconsistentCsvMap["official_measurement_age_frames"])
        assertEquals("false", inconsistentCsvMap["official_full_matrix_celsius_allowed"])
    }

    @Test
    fun unorderedOrOutOfRangeOfficialMeasurementFailsClosedAtCsvBoundary() {
        val unordered = officialMeasurementJson(
            currentFrameCounter = 77L,
            measurementFrameCounter = 77L,
            publishedMatchesCurrentFrame = true,
            publishedTemporalScope = "current_frame",
            publishedAgeFrames = 0L,
        ).put("official_temperature_avg_c", 35.0)
        val unorderedSession = recordingSession()
        unorderedSession.updateThermalStreamSnapshot(unordered)
        val unorderedCsv =
            requireNotNull(unorderedSession.recordFrame(rawFrame())).toCsvMap(unorderedSession.config)
        assertEquals("", unorderedCsv["official_temperature_avg_c"])
        assertEquals("", unorderedCsv["official_temperature_provenance"])

        val centerOutOfRange = officialMeasurementJson(
            currentFrameCounter = 77L,
            measurementFrameCounter = 77L,
            publishedMatchesCurrentFrame = true,
            publishedTemporalScope = "current_frame",
            publishedAgeFrames = 0L,
        ).put("official_temperature_center_c", 40.0)
        val centerSession = recordingSession()
        centerSession.updateThermalStreamSnapshot(centerOutOfRange)
        val centerCsv =
            requireNotNull(centerSession.recordFrame(rawFrame())).toCsvMap(centerSession.config)
        assertEquals("", centerCsv["official_temperature_avg_c"])
        assertEquals("", centerCsv["official_temperature_center_c"])
    }

    @Test
    fun futureOfficialMeasurementCannotAttachToOlderRawFrameOrCsvRow() {
        val session = recordingSession()
        session.updateThermalStreamSnapshot(officialMeasurementJson(
            currentFrameCounter = 76L,
            measurementFrameCounter = 77L,
            publishedMatchesCurrentFrame = false,
            publishedTemporalScope = "last_completed_measurement",
            publishedAgeFrames = null,
        ))

        val csvMap = requireNotNull(session.recordFrame(rawFrame())).toCsvMap(session.config)

        assertEquals("", csvMap["official_measurement_status"])
        assertEquals("", csvMap["official_measurement_frame_counter"])
        assertEquals("", csvMap["official_temperature_avg_c"])
        assertEquals("", csvMap["official_temperature_min_c"])
        assertEquals("", csvMap["official_temperature_max_c"])
        assertEquals("", csvMap["official_temperature_provenance"])
        assertEquals("", csvMap["official_temperature_scope"])
        assertEquals("", csvMap["official_measurement_matches_current_frame"])
        assertEquals("", csvMap["official_measurement_temporal_scope"])
        assertEquals("", csvMap["official_measurement_age_frames"])
        assertEquals("false", csvMap["thermal_celsius_allowed"])
    }

    @Test
    fun pendingFailedAndMalformedOfficialMeasurementsCannotGrantGenericCelsius() {
        val cases = listOf(
            "pending" to officialMeasurementJson(77L, 77L, true, "current_frame", 0L)
                .put("official_measurement_status", "PENDING"),
            "failed" to officialMeasurementJson(77L, 77L, true, "current_frame", 0L)
                .put("official_measurement_status", "FAILED"),
            "unordered" to officialMeasurementJson(77L, 77L, true, "current_frame", 0L)
                .put("official_temperature_avg_c", 40.0),
            "center_out_of_range" to officialMeasurementJson(77L, 77L, true, "current_frame", 0L)
                .put("official_temperature_center_c", 40.0),
        )

        cases.forEach { (name, payload) ->
            val session = recordingSession()
            session.updateThermalStreamSnapshot(payload)
            val csvMap = requireNotNull(session.recordFrame(rawFrame())).toCsvMap(session.config)
            assertEquals(name, "false", csvMap["thermal_celsius_allowed"])
        }
    }

    @Test
    fun productionSnapshotEnrichmentFeedsRecordingAndFailsClosedForInvalidTemporalCounters() {
        data class Case(
            val name: String,
            val currentFrameCounter: Long?,
            val measurementFrameCounter: Long?,
            val expectedAverage: String,
            val expectedScope: String,
            val expectedAge: String,
        )
        val cases = listOf(
            Case("current", 77L, 77L, "24.125000", "current_frame", "0"),
            Case("stale", 80L, 77L, "24.125000", "last_completed_measurement", "3"),
            Case("future", 76L, 77L, "", "", ""),
            Case("missing_current", null, 77L, "", "", ""),
            Case("negative_current", -1L, 77L, "", "", ""),
            Case("negative_measurement", 77L, -1L, "", "", ""),
        )

        cases.forEach { case ->
            val rawStream = mutableFakeJson(
                *listOfNotNull(
                    case.currentFrameCounter?.let { "frame_counter" to it },
                    "celsius_allowed" to false,
                ).toTypedArray(),
            )
            val enriched = enrichedThermalRawStreamSnapshotForSession(
                rawStream,
                readyMeasurementState(case.measurementFrameCounter),
            )
            val session = recordingSession()
            session.updateThermalStreamSnapshot(enriched)

            val csvMap = requireNotNull(session.recordFrame(rawFrame())).toCsvMap(session.config)

            assertEquals(case.name, case.expectedAverage, csvMap["official_temperature_avg_c"])
            assertEquals(case.name, case.expectedScope, csvMap["official_measurement_temporal_scope"])
            assertEquals(case.name, case.expectedAge, csvMap["official_measurement_age_frames"])
        }
    }

    private fun officialMeasurementJson(
        currentFrameCounter: Any?,
        measurementFrameCounter: Any?,
        publishedMatchesCurrentFrame: Any?,
        publishedTemporalScope: Any?,
        publishedAgeFrames: Any?,
    ): JSONObject = mutableFakeJson(
        "frame_counter" to currentFrameCounter,
        "celsius_allowed" to false,
        "official_measurement_status" to "READY",
        "official_measurement_reason" to "official_f2_scalar_measurement_ready",
        "official_measurement_frame_counter" to measurementFrameCounter,
        "official_temperature_avg_c" to 24.125,
        "official_temperature_min_c" to 20.5,
        "official_temperature_max_c" to 29.75,
        "official_temperature_center_c" to 25.0,
        "official_temperature_provenance" to "official_f2_analyzer_measurement_stats",
        "official_temperature_scope" to "rectangle",
        "official_measurement_matches_current_frame" to publishedMatchesCurrentFrame,
        "official_measurement_temporal_scope" to publishedTemporalScope,
        "official_measurement_age_frames" to publishedAgeFrames,
        "official_full_matrix_celsius_allowed" to false,
    )

    private fun fakeJson(vararg entries: Pair<String, Any?>): JSONObject = FakeJSONObject(mapOf(*entries))

    private fun mutableFakeJson(vararg entries: Pair<String, Any?>): JSONObject =
        MutableFakeJSONObject(mutableMapOf(*entries))

    private fun readyMeasurementState(frameCounter: Long?): OfficialF2ScalarMeasurementState =
        OfficialF2ScalarMeasurementState.idle().copy(
            status = OfficialF2ScalarMeasurementStatus.READY,
            reason = "official_f2_scalar_measurement_ready",
            frameCounter = frameCounter,
            measuredScope = "rectangle",
            averageCelsius = 24.125f,
            minCelsius = 20.5f,
            maxCelsius = 29.75f,
            centerCelsius = 25.0f,
        )

    private class MutableFakeJSONObject(
        private val values: MutableMap<String, Any?>,
    ) : JSONObject() {
        override fun put(name: String, value: Any?): JSONObject = putValue(name, value)
        override fun put(name: String, value: Boolean): JSONObject = putValue(name, value)
        override fun put(name: String, value: Double): JSONObject = putValue(name, value)
        override fun put(name: String, value: Int): JSONObject = putValue(name, value)
        override fun put(name: String, value: Long): JSONObject = putValue(name, value)

        private fun putValue(name: String, value: Any?): JSONObject {
            values[name] = if (value === NULL) null else value
            return this
        }

        override fun has(name: String?): Boolean = values.containsKey(name.orEmpty())
        override fun isNull(name: String?): Boolean = values[name.orEmpty()] == null
        override fun opt(name: String?): Any? = values[name.orEmpty()]
        override fun optBoolean(name: String?, fallback: Boolean): Boolean =
            values[name.orEmpty()] as? Boolean ?: fallback
        override fun optString(name: String?): String = values[name.orEmpty()]?.toString().orEmpty()
        override fun optInt(name: String?): Int = (values[name.orEmpty()] as? Number)?.toInt() ?: 0
        override fun optLong(name: String?): Long = (values[name.orEmpty()] as? Number)?.toLong() ?: 0L
        override fun optLong(name: String?, fallback: Long): Long =
            (values[name.orEmpty()] as? Number)?.toLong() ?: fallback
        override fun optDouble(name: String?): Double =
            (values[name.orEmpty()] as? Number)?.toDouble() ?: Double.NaN
        override fun optJSONObject(name: String?): JSONObject? = values[name.orEmpty()] as? JSONObject
        override fun optJSONArray(name: String?): org.json.JSONArray? =
            values[name.orEmpty()] as? org.json.JSONArray
        override fun toString(): String = values.toString()
    }

    private class FakeJSONObject(private val values: Map<String, Any?>) : JSONObject() {
        override fun has(name: String?): Boolean = values.containsKey(name.orEmpty())

        override fun isNull(name: String?): Boolean = values[name.orEmpty()] == null

        override fun opt(name: String?): Any? = values[name.orEmpty()]

        override fun optBoolean(name: String?, fallback: Boolean): Boolean = values[name.orEmpty()] as? Boolean ?: fallback

        override fun optString(name: String?): String = values[name.orEmpty()]?.toString().orEmpty()

        override fun optInt(name: String?): Int = when (val value = values[name.orEmpty()]) {
            is Number -> value.toInt()
            is String -> value.toIntOrNull() ?: 0
            else -> 0
        }

        override fun optLong(name: String?): Long = when (val value = values[name.orEmpty()]) {
            is Number -> value.toLong()
            is String -> value.toLongOrNull() ?: 0L
            else -> 0L
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
