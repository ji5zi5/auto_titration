from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ANDROID_ROOT = ROOT / "mobile/android"
JAVA_ROOT = ANDROID_ROOT / "app/src/main/java/kr/auto/titration/mobile"
ROI_ROOT = JAVA_ROOT / "roi"
WEBSITE_ROOT = ROOT / "website"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def all_kotlin() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in JAVA_ROOT.rglob("*.kt"))


class AndroidRoiParityContractTests(unittest.TestCase):
    def test_roi_mask_and_detection_result_domain_matches_windows_payload_semantics(self):
        """Android must carry mask-shaped ROI metadata instead of rectangle-only ROI parity."""
        roi_mask = ROI_ROOT / "RoiMask.kt"
        detector = ROI_ROOT / "RoiDetectionResult.kt"
        response = ROI_ROOT / "RoiAutoCandidateResponse.kt"

        missing = [str(path.relative_to(ROOT)) for path in [roi_mask, detector, response] if not path.is_file()]
        self.assertEqual([], missing, "missing Android ROI parity domain files")

        source = "\n".join(read(path) for path in [roi_mask, detector, response])
        expected_tokens = [
            "data class RoiMask",
            "val bbox: Roi",
            "val confidence: Double",
            "val source: String",
            'shape: String = "mask"',
            "val componentCount: Int",
            "val stability: String",
            "val areaPx",
            "val centroidX",
            "val centroidY",
            "val bboxString",
            "data class RoiDetectionResult",
            "val roi: Roi?",
            "val reason: String",
            "val mask: RoiMask?",
            "data class RoiAutoCandidateResponse",
            "appliedNow",
            "toJson",
            '"target"',
            '"applied_now"',
            '"reason"',
            '"confidence"',
            '"roi"',
        ]
        missing_tokens = [token for token in expected_tokens if token not in source]
        self.assertEqual([], missing_tokens, "ROI/mask payload contract is incomplete")

    def test_android_roi_reason_strings_are_honest_windows_parity_reasons(self):
        source = all_kotlin()

        expected_reasons = [
            "yolo_visible_candidate:cup",
            "no_yolo_visible_candidate",
            "yolo_model_unavailable",
            "yolo_runtime_unavailable",
            "yolo_tensor_contract_mismatch",
            "yolo_segmentation_mask_unavailable",
            "thermal_contrast_candidate",
            "thermal_raw_contrast_flat",
        ]
        missing_reasons = [reason for reason in expected_reasons if reason not in source]
        self.assertEqual([], missing_reasons, "Android ROI detector must expose honest Windows-parity reasons")
        self.assertNotIn("android_auto_luma_candidate", source)

    def test_litert_dependency_model_metadata_and_tensor_contract_are_locked(self):
        gradle = read(ANDROID_ROOT / "app/build.gradle.kts")
        source = all_kotlin()
        model_asset = ANDROID_ROOT / "app/src/main/assets/models/yolo11n-seg-256-fp32.tflite"
        metadata = ANDROID_ROOT / "app/src/main/assets/models/yolo11n-seg-256-fp32.metadata.json"
        cache_root = ROOT / ".gradle-cache/caches/modules-2/files-2.1"

        expected_gradle_tokens = [
            'val liteRtVersion = "2.1.5"',
            'com.google.ai.edge.litert:litert:2.1.5',
            "$liteRtVersion",
            "hikmicroRedistributionApproved",
            "Release/deliverable APK blocked",
        ]
        missing_gradle = [token for token in expected_gradle_tokens if token not in gradle]
        self.assertEqual([], missing_gradle, "Gradle must lock LiteRT 2.1.5 without dynamic versions")
        self.assertNotIn("com.google.ai.edge.litert:+", gradle)
        self.assertTrue(model_asset.is_file(), f"missing model asset {model_asset}")
        self.assertTrue(metadata.is_file(), f"missing model metadata doc {metadata}")
        cached_litert = list(cache_root.glob("**/com.google.ai.edge.litert*2.1.5*")) if cache_root.exists() else []
        self.assertTrue(cached_litert, "LiteRT 2.1.5 must be present in .gradle-cache for offline Android builds")
        metadata_text = read(metadata)
        expected_metadata_tokens = [
            '"asset_path": "models/yolo11n-seg-256-fp32.tflite"',
            '"sha256"',
            '"source_model"',
            '"export_command"',
            '"input_size"',
            '"accepted_classes"',
            '"output_tensor_contract"',
            '"runtime"',
            '"litert_version": "2.1.5"',
        ]
        missing_metadata = [token for token in expected_metadata_tokens if token not in metadata_text]
        self.assertEqual([], missing_metadata, "YOLO model metadata must document asset, SHA, and tensor contract")

        expected_runtime_tokens = [
            "LiteRtYoloSegmenter",
            "VisibleRoiModelMetadata",
            "YoloTensorContractValidator",
            "checkLiteRtDependencyCache",
            "validateTensorContract",
            "tensor_contract_fixture",
            "yolo_model_unavailable",
            "yolo_runtime_unavailable",
            "yolo_tensor_contract_mismatch",
        ]
        missing_runtime = [token for token in expected_runtime_tokens if token not in source]
        self.assertEqual([], missing_runtime, "LiteRT runtime/model contract implementation is missing")
        self.assertNotIn("detectOrUnavailable", source, "stale YOLO availability stub must not claim inference is unwired")

    def test_mainactivity_uses_latest_only_roi_worker_not_inline_luma_candidate(self):
        main = read(JAVA_ROOT / "MainActivity.kt")
        source = all_kotlin()

        expected_tokens = [
            ("LatestRoiDetectionState", source),
            ("submitVisibleFrame", main + source),
            ("latestAutoRoiDetectionResult", main + source),
            ("requestAutoRoiCandidateFromBridge", main),
        ]
        missing = [token for token, haystack in expected_tokens if token not in haystack]
        self.assertEqual([], missing, "Android ROI analysis must use latest-only detector state")
        self.assertNotIn("private fun detectVisibleRoiCandidate", main)
        self.assertNotIn("lumaAt(", main)
        self.assertNotIn("android_auto_luma_candidate", source)

    def test_android_visible_yolo_path_runs_litert_inference_and_decodes_masks(self):
        main = read(JAVA_ROOT / "MainActivity.kt")
        source = all_kotlin()

        expected_tokens = [
            ("YoloInputFrame", source),
            ("org.tensorflow.lite.Interpreter", source),
            ("runForMultipleInputsOutputs", source),
            ("decodeYoloOutputs", source),
            ("MASK_DIM = 32", source),
            ("COCO80_NAMES", source),
            ("buildVisibleYoloInputFrame", main),
            ("latestVisibleYoloInput", main),
            ("displayYoloMaskToSensorMask", main),
            ("autoRoiWorker.requestVisibleCandidate", main),
        ]
        missing = [token for token, haystack in expected_tokens if token not in haystack]
        self.assertEqual([], missing, "Android visible ROI path must use the real LiteRT YOLO mask pipeline")
        self.assertNotIn("yolo_segmentation_inference_not_started", source)

    def test_android_webview_bridge_uses_request_candidate_response_not_autoset_success(self):
        bridge = read(JAVA_ROOT / "AndroidBridge.kt")
        main = read(JAVA_ROOT / "MainActivity.kt")
        adapter = read(WEBSITE_ROOT / "android-webview.js")

        prerequisite_missing = [
            label
            for label, token, haystack in [
                ("AndroidBridge.requestAutoRoiCandidate", "fun requestAutoRoiCandidate", bridge),
                ("MainActivity.requestAutoRoiCandidateFromBridge", "fun requestAutoRoiCandidateFromBridge", main),
            ]
            if token not in haystack
        ]
        self.assertEqual([], prerequisite_missing, "Android bridge must expose candidate request API")
        roi_button = adapter[
            adapter.index("replaceButtonHandler('roiCandidateButton'"):
            adapter.index("replaceButtonHandler('roiLockButton'")
        ]
        self.assertIn("readBridgeJson('requestAutoRoiCandidate'", roi_button)
        self.assertIn("showAndroidAutoRoiCandidateResult", adapter)
        self.assertNotIn("readBridgeJson('autoSetRoi')", roi_button)
        auto_function = main[
            main.index("fun requestAutoRoiCandidateFromBridge"):
            main.index("fun autoSetRoiFromBridge")
        ]
        self.assertNotIn('status.optJSONObject("roi") ?: JSONObject()', auto_function)
        self.assertIn("RoiAutoCandidateResponse.fromDetection(merged).toJson()", auto_function)
        expected_keys = [
            "applied_now",
            "reason",
            "confidence",
            "visible_mask_area_px",
            "visible_mask_source",
            "thermal_mask_area_px",
            "thermal_mask_source",
        ]
        missing_keys = [key for key in expected_keys if key not in adapter + main]
        self.assertEqual([], missing_keys, "bridge candidate payload must preserve mask/candidate metadata")

    def test_phone_local_csv_schema_exports_mask_raw_candidate_and_pump_diagnostics(self):
        schema = read(JAVA_ROOT / "data/CsvSchema.kt")
        row = read(JAVA_ROOT / "data/CsvFeatureRow.kt")
        session = read(JAVA_ROOT / "session/PhoneRunSession.kt")
        exporter = read(JAVA_ROOT / "export/SessionExporter.kt")

        expected_fields = [
            "roi_shape",
            "mask_area_px",
            "mask_confidence",
            "mask_bbox",
            "mask_component_count",
            "mask_stability",
            "visible_roi_shape",
            "visible_mask_area_px",
            "visible_mask_confidence",
            "visible_mask_bbox",
            "visible_mask_source",
            "visible_mask_component_count",
            "visible_mask_stability",
            "thermal_roi_shape",
            "thermal_mask_area_px",
            "thermal_mask_confidence",
            "thermal_mask_bbox",
            "thermal_mask_source",
            "thermal_mask_component_count",
            "thermal_mask_stability",
            "thermal_raw_roi_std",
            "thermal_raw_roi_delta",
            "thermal_raw_roi_p50",
            "thermal_raw_roi_iqr",
            "thermal_raw_std",
            "csv_session_id",
            "csv_row_index",
            "csv_recording_started_epoch_s",
            "csv_recording_elapsed_s",
            "pump_elapsed_s",
            "theoretical_equivalence_time_s",
            "time_to_equivalence_s",
            "equivalence_window_ml",
            "equivalence_window_label",
            "equivalence_formula",
            "calculated_theoretical_equivalence_volume_ml",
            "sample_concentration_from_theoretical_equivalence_M",
            "sample_concentration_from_predicted_equivalence_M",
            "predicted_sample_concentration_error_percent",
            "sample_concentration_from_injected_M",
            "sample_concentration_error_percent",
            "auto_roi_worker_enabled",
            "auto_roi_result_status",
            "auto_roi_result_reason",
            "pending_auto_candidate_requests",
            "pending_auto_candidate_target",
        ]
        missing_schema = [field for field in expected_fields if field not in schema]
        missing_row = [field for field in expected_fields if field not in row]
        self.assertEqual([], missing_schema, "CSV schema missing Android parity diagnostic fields")
        self.assertEqual([], missing_row, "CSV feature row missing Android parity diagnostic fields")
        self.assertIn('"roi_shape"', schema, "CSV schema must expose a standalone ROI shape column")
        expected_session_tokens = [
            "computeRawStats",
            "thermalRawRoiStd = thermalMaskStats?.std",
            "thermalRawRoiDelta = thermalMaskStats?.delta",
            "thermalRawRoiP50 = thermalMaskStats?.p50",
            "thermalRawRoiIqr = thermalMaskStats?.iqr",
            "thermalRawStd = thermalMatrixStats?.std",
            "autoRoiDroppedPending = frame.autoRoiDroppedPending",
            "pendingAutoCandidateRequests = frame.pendingAutoCandidateRequests",
            "pendingAutoCandidateTarget = frame.pendingAutoCandidateTarget",
        ]
        missing_session = [token for token in expected_session_tokens if token not in session]
        self.assertEqual([], missing_session, "PhoneRunSession must populate raw/mask ROI diagnostics, not just declare columns")
        self.assertIn("roi_mask_metadata", exporter)


if __name__ == "__main__":
    unittest.main()
