from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt"
MAPPING = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/OfficialMeasurementBridgeMapping.kt"
SESSION = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/session/PhoneRunSession.kt"
CSV_SCHEMA = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/data/CsvSchema.kt"
CSV_ROW = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/data/CsvFeatureRow.kt"
WEBVIEW = ROOT / "website/android-webview.js"

FRESHNESS_FIELDS = [
    "official_measurement_matches_current_frame",
    "official_measurement_temporal_scope",
    "official_measurement_age_frames",
]
OFFICIAL_FIELDS = [
    "official_measurement_status",
    "official_measurement_reason",
    "official_measurement_frame_counter",
    "official_temperature_avg_c",
    "official_temperature_min_c",
    "official_temperature_max_c",
    "official_temperature_center_c",
    "official_temperature_provenance",
    "official_temperature_scope",
    *FRESHNESS_FIELDS,
    "official_full_matrix_celsius_allowed",
]


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class G010OfficialMeasurementPropagationTests(unittest.TestCase):
    def test_mainactivity_wires_explicit_raw_stream_counter_into_bridge_fields(self):
        src = text(MAIN)
        body = src[src.index("fun buildStatusJson()"):src.index("@Synchronized\n    fun startNewRunFromBridge", src.index("fun buildStatusJson()"))]
        self.assertIn("HikmicroJnaMini2Stream.scheduleLatestOfficialScalarMeasurement(this, rect)", body)
        self.assertNotIn("requestLatestOfficialScalarMeasurement", body)
        self.assertIn("officialMeasurementRectFromMaskForBridge", body)
        self.assertIn(
            "val sessionRawStream = enrichedThermalRawStreamSnapshotForSession(rawStream, latestOfficialMeasurement)",
            body,
        )
        self.assertIn(
            "val currentRawStreamFrameCounter = rawStreamFrameCounterForOfficialMeasurement(sessionRawStream)",
            body,
        )
        self.assertIn("runSession.updateThermalStreamSnapshot(sessionRawStream)", body)
        self.assertLess(
            body.index("enrichedThermalRawStreamSnapshotForSession(rawStream, latestOfficialMeasurement)"),
            body.index("runSession.updateThermalStreamSnapshot(sessionRawStream)"),
        )
        self.assertIn(
            "runSession.updateThermalStreamSnapshot(currentEnrichedThermalRawStreamJson())",
            src,
        )
        self.assertNotIn(
            "runSession.updateThermalStreamSnapshot(currentThermalRawStreamJson())",
            src,
        )
        self.assertRegex(
            src,
            r"fun appendOfficialMeasurementFieldsForBridge\(\s*target: JSONObject,\s*state: [^,]+,\s*currentRawStreamFrameCounter: Long\?,\s*\): JSONObject",
        )
        self.assertIn("val fields = officialMeasurementFieldsForBridge(state, currentRawStreamFrameCounter)", src)
        self.assertIn('target.put("official_measurement_matches_current_frame", fields.matchesCurrentFrame)', src)
        self.assertIn('target.put("official_measurement_temporal_scope", fields.temporalScope ?: JSONObject.NULL)', src)
        self.assertIn('target.put("official_measurement_age_frames", fields.ageFrames ?: JSONObject.NULL)', src)

    def test_official_contract_fields_are_separate_from_device_global_and_no_matrix_promotion(self):
        main_src = text(MAIN)
        mapping_src = text(MAPPING)
        combined = "\n".join(text(p) for p in [MAIN, MAPPING, SESSION, CSV_SCHEMA, CSV_ROW, WEBVIEW])
        for field in OFFICIAL_FIELDS:
            with self.subTest(field=field):
                self.assertIn(field, combined)
        for field in FRESHNESS_FIELDS:
            with self.subTest(csv_field=field):
                self.assertIn(field, text(CSV_SCHEMA))
                self.assertIn(field, text(CSV_ROW))
        self.assertIn("official_f2_analyzer_measurement_stats", combined)
        self.assertIn("device_global_summary", combined)
        self.assertIn("thermal_device_global_avg_c", text(CSV_SCHEMA))
        self.assertRegex(
            main_src,
            r'target\.put\("official_full_matrix_celsius_allowed",\s*fields\.fullMatrixCelsiusAllowed\)',
        )
        self.assertRegex(mapping_src, r"fullMatrixCelsiusAllowed\s*=\s*false")
        self.assertNotRegex(mapping_src, r"fullMatrixCelsiusAllowed\s*=\s*true")
        self.assertIn("full_matrix_temperature_status: 'unproved_not_emitted'", text(WEBVIEW))

    def test_freshness_contract_is_current_only_for_generic_temperature_promotion(self):
        mapping_src = text(MAPPING)
        session_src = text(SESSION)
        webview_src = text(WEBVIEW)
        self.assertIn("currentRawStreamFrameCounter: Long?", mapping_src)
        self.assertIn("measurementFrameCounter = state.frameCounter", mapping_src)
        self.assertIn(
            "requireNotNull(currentRawStreamFrameCounter) - requireNotNull(measurementFrameCounter)",
            mapping_src,
        )
        self.assertIn("official_measurement_temporal_counter_missing", mapping_src)
        self.assertIn("official_measurement_temporal_counter_invalid", mapping_src)
        self.assertIn("official_measurement_future_frame_mismatch", mapping_src)
        self.assertIn("measurementFrameCounter > currentRawStreamFrameCounter", mapping_src)
        self.assertIn("val publishableReady = readyFinite && temporalFailureReason == null", mapping_src)
        self.assertIn('matchesCurrentFrame -> "current_frame"', mapping_src)
        self.assertIn('else -> "last_completed_measurement"', mapping_src)
        self.assertIn("androidCurrentOfficialTemperatureSummaryFrom(live, live.thermal_frame_counter)", webview_src)
        self.assertIn("androidCurrentOfficialTemperatureSummaryFrom(rawStream, rawStream.frame_counter)", webview_src)
        self.assertIn("publishedMatchesCurrentFrame === true", webview_src)
        self.assertIn("publishedTemporalScope === 'current_frame'", webview_src)
        self.assertIn("publishedAgeFrames === 0", webview_src)
        self.assertIn("computedAgeFrames > 0", webview_src)
        self.assertIn("publishedMatchesCurrentFrame === false", webview_src)
        self.assertIn("publishedTemporalScope === 'last_completed_measurement'", webview_src)
        self.assertIn("publishedAgeFrames === computedAgeFrames", webview_src)
        self.assertIn("json.optStrictBoolean(\"official_measurement_matches_current_frame\") == true", session_src)
        self.assertIn("json.optCleanString(\"official_measurement_temporal_scope\") == \"current_frame\"", session_src)
        self.assertIn("json.optStrictLong(\"official_measurement_age_frames\") == 0L", session_src)
        self.assertIn('json.optStrictLong("frame_counter") ?: return null', session_src)
        self.assertIn(
            'json.optStrictLong("official_measurement_frame_counter") ?: return null',
            session_src,
        )
        self.assertIn("measurementFrameCounter > currentFrameCounter", session_src)

    def test_no_raw_to_celsius_formula_or_full_matrix_claim_for_official_measurement(self):
        combined = "\n".join(text(p) for p in [MAIN, MAPPING, SESSION, CSV_ROW, WEBVIEW])
        for token in [
            "official_temperature_avg_c = raw",
            "raw_avg *",
            "raw_avg /",
            "full_matrix_celsius_allowed: true",
            '"official_full_matrix_celsius_allowed" to true',
        ]:
            with self.subTest(token=token):
                self.assertNotIn(token, combined)


if __name__ == "__main__":
    unittest.main()
