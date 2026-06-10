from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt"
BRIDGE = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/AndroidBridge.kt"
ADAPTER = ROOT / "website/android-webview.js"


class AndroidMobileFrameRoiRegressionTests(unittest.TestCase):
    def test_android_preview_tracks_encoded_image_size_separately_from_sensor_size(self):
        main = MAIN.read_text(encoding="utf-8")

        self.assertIn("data class VisiblePreviewPayload", main)
        self.assertIn("latestVisiblePreviewImageWidth", main)
        self.assertIn("latestVisiblePreviewImageHeight", main)
        self.assertIn("visible_display_frame_width", main)
        self.assertIn("visible_display_frame_height", main)

    def test_android_visible_roi_sent_to_webview_uses_preview_image_coordinates(self):
        main = MAIN.read_text(encoding="utf-8")

        self.assertIn("sensorRoiToPreviewRoi", main)
        self.assertIn("previewRoiToSensorRoi", main)
        self.assertIn("latestVisiblePreviewImageWidth", main)
        self.assertLess(
            main.index("val previewRoi = effectiveRoi.let"),
            main.index(".put(\"visible_roi\", previewRoi.toCsvString())"),
        )

    def test_android_roi_drag_payload_stays_normalized_to_preview_image(self):
        adapter = ADAPTER.read_text(encoding="utf-8")

        self.assertIn("sendAndroidVisibleRoi", adapter)
        self.assertIn("normalized: true", adapter)
        self.assertIn("normalizeImageRect(image, rect)", adapter)
        self.assertIn("image.naturalWidth", adapter)

    def test_android_preview_uses_lightweight_push_channel_instead_of_full_status_every_fifth_frame(self):
        main = MAIN.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")

        self.assertIn("private const val VISIBLE_PREVIEW_MIN_INTERVAL_MS = 40L", main)
        self.assertIn("notifyWebPreview", main)
        self.assertIn("visible_preview_frame_id", main)
        self.assertIn("AutoTitrationAndroidOnPreview", main)
        self.assertIn("AutoTitrationAndroidOnPreview", adapter)
        self.assertNotIn("id % 5L", main)
        preview_function = main[main.index("private fun notifyWebPreview"):main.index("private fun notifyWebStatus")]
        self.assertNotIn("safeBuildStatusJson", preview_function)
        self.assertNotIn("buildStatusJson", preview_function)

    def test_android_preview_push_includes_latest_thermal_frame_without_waiting_for_status_poll(self):
        main = MAIN.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")
        mini2_probe = (ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt").read_text(encoding="utf-8")

        preview_function = main[main.index("private fun notifyWebPreview"):main.index("private fun notifyWebStatus")]
        self.assertIn("appendLatestThermalPreview(live)", preview_function)
        self.assertIn("thermal_preview_data_url", main)
        self.assertIn("thermal_frame_counter", main)
        self.assertIn("latestRawStreamStatus", mini2_probe)
        self.assertIn("peekActiveStatus", mini2_probe)
        self.assertIn("latestAndroidThermalFrameId", adapter)
        preview_callback = adapter[adapter.index("window.AutoTitrationAndroidOnPreview"):adapter.index("window.AutoTitrationAndroidOnStatus")]
        self.assertIn("applyAndroidThermalPreviewFrame(live)", preview_callback)

    def test_android_preview_js_uses_frame_id_not_big_data_url_string_compare(self):
        adapter = ADAPTER.read_text(encoding="utf-8")

        self.assertIn("latestAndroidPreviewFrameId", adapter)
        self.assertIn("visible_preview_frame_id", adapter)
        self.assertIn("frameId <= latestAndroidPreviewFrameId", adapter)
        self.assertNotIn("visible.src !== dataUrl", adapter)

    def test_android_roi_drag_blocks_stale_overlay_refresh_until_commit_revision_is_current(self):
        main = MAIN.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")
        app = (ROOT / "website/app.js").read_text(encoding="utf-8")

        self.assertIn("visibleRoiRevision", main)
        self.assertIn("visible_roi_revision", main)
        self.assertIn("AutoTitrationRoiDraftActive", adapter)
        self.assertIn("AutoTitrationShouldIgnoreRoiStatus", adapter)
        self.assertIn("latestAndroidRoiRevision", adapter)
        self.assertIn("roiStatusIsDrafting", app)
        self.assertIn("if (roiStatusIsDrafting()) return", app)

    def test_live_metadata_strips_stale_android_roi_before_merging_metadata(self):
        app = (ROOT / "website/app.js").read_text(encoding="utf-8")

        self.assertIn("withoutRoiGeometry", app)
        self.assertIn("ignoreRoiStatus", app)
        self.assertLess(
            app.index("const ignoreRoiStatus"),
            app.index("latestLiveMetadata = { ...latestLiveMetadata, ...effectiveData }")
        )
        self.assertIn("delete clone.visible_roi", app)
        self.assertIn("applyRoiStatus(effectiveData);", app)

    def test_stale_android_live_metadata_does_not_clear_current_roi_lock_flags(self):
        app = (ROOT / "website/app.js").read_text(encoding="utf-8")
        stale_start = app.index("function applyLiveMetadata")
        stale_section = app[stale_start:app.index("  const hasCelsius", stale_start)]

        self.assertIn("if (!ignoreRoiStatus) {", stale_section)
        self.assertIn("latestRoiLocked = Boolean(effectiveData.roi_locked)", stale_section)
        self.assertLess(stale_section.index("if (!ignoreRoiStatus) {"), stale_section.index("latestRoiLocked = Boolean(effectiveData.roi_locked)"))

    def test_manual_android_roi_clears_stale_yolo_mask_metadata(self):
        main = MAIN.read_text(encoding="utf-8")
        set_fn = main[main.index("fun setVisibleRoiFromBridge"):main.index("private val AUTO_ROI_RESPONSE_KEYS_FOR_WINDOWS_PARITY")]

        self.assertIn('shape = "android_webview_rect"', set_fn)
        self.assertIn("latestVisibleRoiMask = null", set_fn)
        self.assertLess(set_fn.index("lockedVisibleRoi = sensorRoi.copy"), set_fn.index("latestVisibleRoiMask = null"))

    def test_android_webview_recording_requires_verified_roi_not_default_center(self):
        main = MAIN.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")

        self.assertIn("androidRoiReadyForRecording", main)
        self.assertIn('put("roi_recordable", androidRoiReadyForRecording', main)
        self.assertIn("visibleRoiEvidence", main)
        self.assertIn("default_unverified_visible_roi", main)
        self.assertIn("verified ROI required", main)
        self.assertNotIn('put("roi_complete", true)', main)
        self.assertNotIn('put("thermal_roi_ready", true)', main)
        self.assertNotIn("lockedVisibleRoi = defaultVisibleSensorRoi()", main)
        self.assertNotIn('roi != null && runSession.state == SessionState.ROI_LOCKED', main)

        start_fn = main[main.index("fun startRecordingFromBridge"):main.index("fun stopRecordingFromBridge")]
        self.assertIn("if (!androidRoiReadyForRecording(lockedVisibleRoi))", start_fn)
        self.assertLess(
            start_fn.index("if (!androidRoiReadyForRecording(lockedVisibleRoi))"),
            start_fn.index("PumpCommand.Reset"),
            "startRecording must re-check verified ROI even when state is already ROI_LOCKED before pump commands",
        )

        lock_fn = main[main.index("fun lockRoiFromBridge"):main.index("fun setVisibleRoiFromBridge")]
        self.assertNotIn("center_rect_pending_frame", lock_fn)
        self.assertIn("roi_lock_blocked", lock_fn)
        self.assertIn("verified ROI required", lock_fn)

        self.assertIn("simplifyAndroidRoiControls", adapter)
        self.assertIn("roiLockButton", adapter)
        self.assertIn("lockButton.hidden = true", adapter)
        enable_fn = adapter[adapter.index("function enableAndroidButtons"):adapter.index("function applyAndroidVisiblePreview")]
        self.assertNotIn("'csvStartButton'", enable_fn)
        self.assertNotIn("'roiLockButton'", enable_fn)
        self.assertIn("ROI 자동추적", adapter)
        self.assertIn("ROI 후보 요청", adapter)
        self.assertIn("ROI 후보 모드", adapter)


    def test_android_roi_candidate_button_requests_shaped_native_candidate_payload(self):
        main = MAIN.read_text(encoding="utf-8")
        bridge = BRIDGE.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")

        missing = [
            label
            for label, token, haystack in [
                ("AndroidBridge.requestAutoRoiCandidate", "requestAutoRoiCandidate", bridge),
                ("MainActivity.requestAutoRoiCandidateFromBridge", "requestAutoRoiCandidateFromBridge", main),
                ("RoiAutoCandidateResponse", "RoiAutoCandidateResponse", main),
                (
                    "WebView readBridgeJson('requestAutoRoiCandidate')",
                    "readBridgeJson('requestAutoRoiCandidate'",
                    adapter,
                ),
            ]
            if token not in haystack
        ]
        self.assertEqual([], missing, "Android ROI button must use shaped native candidate payload")
        roi_button = adapter[adapter.index("replaceButtonHandler('roiCandidateButton'"):adapter.index("replaceButtonHandler('roiLockButton'")]
        self.assertNotIn("pollAndroidStatus();", roi_button)
        self.assertNotIn("readBridgeJson('autoSetRoi')", roi_button)
        missing_keys = [key for key in ["ok", "target", "applied_now", "reason", "confidence", "roi"] if f'"{key}"' not in main]
        self.assertEqual([], missing_keys, "native auto ROI response shape is incomplete")
        self.assertIn("Android WebView: ROI 후보 요청", adapter)

    def test_android_roi_auto_candidate_does_not_report_luma_or_center_fallback_as_success(self):
        main = MAIN.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")
        all_kotlin = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile").rglob("*.kt")
        )

        prerequisite_missing = [
            label
            for label, token, haystack in [
                ("MainActivity.requestAutoRoiCandidateFromBridge", "fun requestAutoRoiCandidateFromBridge", main),
                ("WebView.showAndroidAutoRoiCandidateResult", "showAndroidAutoRoiCandidateResult", adapter),
            ]
            if token not in haystack
        ]
        self.assertEqual([], prerequisite_missing, "auto ROI candidate request/result API is missing")
        auto_function = main[main.index("fun requestAutoRoiCandidateFromBridge"):main.index("fun rotateThermalPreviewFromBridge")]
        unexpected = [
            token
            for token, haystack in [
                ("detectVisibleRoiCandidate", main),
                ("android_auto_luma_candidate", all_kotlin),
                ("defaultVisibleSensorRoi()", auto_function),
                ("중앙 ROI 적용", auto_function),
            ]
            if token in haystack
        ]
        self.assertEqual([], unexpected, "auto ROI candidate must not report luma/center fallback as success")
        missing = [token for token in ["yolo_model_unavailable", "no_yolo_visible_candidate"] if token not in all_kotlin]
        if "applied_now" not in auto_function:
            missing.append("applied_now")
        if "showAndroidAutoRoiCandidateResult" not in adapter:
            missing.append("showAndroidAutoRoiCandidateResult")
        self.assertEqual([], missing, "auto ROI candidate must expose honest failure/success reasons")

    def test_failed_android_roi_candidate_does_not_apply_stale_prior_mask(self):
        main = MAIN.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")
        auto_function = main[main.index("fun requestAutoRoiCandidateFromBridge"):main.index("fun autoSetRoiFromBridge")]
        show_function = adapter[adapter.index("function showAndroidAutoRoiCandidateResult"):adapter.index("function applyBridgePayload")]
        bridge_apply = adapter[adapter.index("function applyBridgePayload"):adapter.index("function replaceButtonHandler")]

        self.assertIn("RoiAutoCandidateResponse.fromDetection(merged).toJson()", auto_function)
        self.assertNotIn('status.optJSONObject("roi") ?: JSONObject()', auto_function)
        self.assertIn("applied && payload?.roi", show_function)
        self.assertIn("candidateResponse", bridge_apply)
        self.assertIn("payload.applied_now === true", bridge_apply)


if __name__ == "__main__":
    unittest.main()
