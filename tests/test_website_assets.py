from pathlib import Path
import subprocess
import unittest


class WebsiteAssetTests(unittest.TestCase):
    def test_permanent_view_navigation_and_responsive_console_contract(self):
        html = Path("website/index.html").read_text(encoding="utf-8")
        css = Path("website/styles.css").read_text(encoding="utf-8")
        header = html[html.index('<header class="console-header">'):html.index("</header>")]
        self.assertIn('id="viewFullLink"', header)
        self.assertIn('id="viewCompactLink"', header)
        self.assertNotIn("remote-only", header)
        self.assertLess(html.index('id="viewCompactLink"'), html.index('class="settings-drawer'))
        self.assertIn("a:focus-visible", css)
        self.assertIn('body.remote-controller-mode #pumpTimelineForm', css)
        self.assertIn('body.remote-controller-mode #chemistryModelForm', css)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn("font-variant-numeric: tabular-nums", css)
        self.assertIn('width: 100%; aspect-ratio: 4 / 3', css)
        self.assertNotIn('height: clamp(200px, 30vh, 320px)', css)
        self.assertIn('object-fit: contain', css)
        self.assertIn('<option value="strong_acid_strong_base" selected>', html)
        self.assertIn('<option value="hydrochloric acid" selected>', html)
        self.assertRegex(html, r'id="sampleVolumeInput"[^>]*value="20.00"')
        self.assertRegex(html, r'id="standardConcentrationInput"[^>]*value="0.100"')

    def test_static_website_is_camera_temperature_live_view_not_explainer_dashboard(self):
        html = Path("website/index.html").read_text(encoding="utf-8")
        js = Path("website/app.js").read_text(encoding="utf-8")
        css = Path("website/styles.css").read_text(encoding="utf-8")

        for expected in [
            "자동 적정",
            "카메라",
            "적외선",
            "visiblePreview",
            "thermalPreview",
            "temperatureValue",
            "temperatureUnit",
            "temperatureMin",
            "temperatureMax",
            "temperatureDelta",
            "thermalRoiLabel",
            "visibleRoiLabel",
            "rgbRValue",
            "rgbGValue",
            "rgbBValue",
            "hsvHValue",
            "hsvSValue",
            "hsvVValue",
            "hsvDeltaValue",
            "rgbDeltaValue",
            "csvPanel",
            "csvRowCount",
            "csvRowsPerSecondValue",
            "csvDownloadLink",
            "csvStartButton",
            "csvStopButton",
            "serialPumpRetractButton",
            "serialPumpStopButton",
            "pumpCommandStatus",
            "csvStateLabel",
            "pumpRateInput",
            "theoryEquivalenceInput",
            'value="20.00"',
            "equivalenceWindowInput",
            "autoStopEnabledInput",
            "autoStopStatus",
            "chemistryModelForm",
            "titrationTypeSelect",
            "sampleSubstanceInput",
            "standardSolutionNameInput",
            "standardConcentrationInput",
            "indicatorSelect",
            "아세트산",
            "염산",
            "수산화나트륨",
            "암모니아",
            "표준 농도(M)",
            "pumpVolumeValue",
            "시작",
            "펌프 주입",
            "종료",
            "펌프 되감기",
            "정지",
            "CSV",
            "roiSetupButton",
            "ROI 선택",
            "roiLockButton",
            "ROI 고정",
            "visibleRoiOverlay",
            "thermalRoiOverlay",
            "visibleCandidateNotice",
            "toast-notice",
            "visibleCandidateNoticeTitle",
            "visibleCandidateNoticeBody",
            "previewStatus",
            "app-shell",
            "live-view",
            "action-panel",
            "main-actions",
            "status-strip",
            "sensor-grid",
            "camera-panel",
            "temperature-panel",
            "details-panel",
            "색상",
            "온도",
            "compact-stats",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, html)
        self.assertIn(
            'id="pumpRateInput" type="number" inputmode="decimal" min="0" step="0.01" value="0.99"',
            html,
        )
        self.assertNotIn("<br", html)
        self.assertNotIn('src="http://127.0.0.1:8766', html)
        self.assertNotIn('href="http://127.0.0.1:8766', html)
        self.assertNotIn("app-topbar", html + css)
        self.assertNotIn("app-brand", html + css)

        for removed in [
            "시연 순서",
            "Core idea",
            "Live run",
            "카메라 + Mini2 수집",
            "자동 인식 없이",
            "네모 ROI를 직접 드래그",
            "펌프 정지는 사람이 직접 판단합니다",
            "CSV 수집 모드",
            "농도계산 모드",
            "녹화 종료 후 예측 당량점으로 농도와 pH를 자동 계산합니다.",
            "실행은 BAT 파일 중심으로",
            "Mini2는 브라우저에서 직접 시작하지 않습니다",
            "파일 역할",
            "전람회 발표 포인트",
            "전람회 대시보드",
            "최근 수집 파일 찾기",
            "API 상태 확인",
            "실시간 모니터 시작",
            "모니터 정지",
            "csvFileList",
            "apiCsvPath",
            "농도 계산",
            "계산된 미지 농도",
            "apiChart",
            "visibleChart",
            "thermalChart",
            "volumeChart",
            "calculator-grid",
            "visibleDetectorSelect",
            "빠른 RGB/윤곽",
            "고급 설정 / 진단",
            "백엔드 주소",
            "실전 사용 상태 점검",
            "생산 age",
            "ROI result age",
            "roiAutoCandidateButton",
            "roiThermalCandidateButton",
            "일반캠 후보",
            "열화상 후보",
            "roiSettingsForm",
            "autoModeSelect",
            "roiUnlockButton",
            "roiSourceLabel",
            "roiCandidateButton",
            "ROI 자동추적",
            "후보 새로고침",
            "visibleLassoOverlay",
            "thermalLassoOverlay",
            "lasso-overlay",
            "경계 보정",
            "csvPathLabel",
            "volumeSourceSelect",
            "manualVolumeControls",
            "manualVolumeSetInput",
            "manualVolumeSetButton",
            "manualVolumePlus01",
            "manualVolumePlus02",
            "manualVolumePlus05",
            "manualVolumePlus10",
            "manualVolumeStatus",
            "수동 적정 입력",
            "수동 부피",
            "부피 기록",
            "부피 입력 방식",
            "pKa 후보",
            "상온 자동",
            "constantsLookupStatus",
            "indicatorModelLabel",
            "activityWarningLabel",
            "equivalenceLabelValue",
            "visibleState",
            "syncQuality",
            "라벨",
            "활동도",
            "당량점 창 mL",
        ]:
            with self.subTest(removed=removed):
                self.assertNotIn(removed, html)

        self.assertIn("connectLiveStream", js)
        self.assertIn("AUTO_TITRATION_STREAM_BASE", js)
        self.assertIn("localStorage", js)
        self.assertIn("normalizeBackendBase", js)
        self.assertIn("setPreviewSources", js)
        self.assertIn("saveBackendBase", js)
        self.assertIn("migrateStoredBackendBase", js)
        self.assertIn("scheduleLocalBackendFailover", js)
        self.assertIn("function proxyBackendBase", js)
        self.assertIn("isDashboardProxyOrigin", js)
        self.assertIn("window.location.port === '8765'", js)
        self.assertIn("window.AUTO_TITRATION_STREAM_BASE", js)
        self.assertIn("addStreamErrorHandlers", js)
        self.assertIn("const LOCAL_COLLECTOR_BACKEND = 'http://127.0.0.1:8766'", js)
        self.assertIn("return LOCAL_COLLECTOR_BACKEND", js)
        self.assertIn("liveStreamBase = proxyBackendBase()", js)
        self.assertIn("127.0.0.1:8765", js)
        self.assertIn("backendBaseInput", js)
        self.assertIn("backendBaseStatus", js)
        self.assertIn("endpoint('/stream/events')", js)
        self.assertIn("EventSource", js)
        self.assertIn("stream/events", js)
        self.assertIn("stream/thermal.mjpg", js)
        self.assertIn("stream/visible.mjpg", js)
        self.assertIn("/api/roi-rect", js)
        self.assertIn("/api/roi-lock", js)
        self.assertIn("/api/roi-unlock", js)
        self.assertIn("/api/settings", js)
        self.assertIn("applyRoiSettings", js)
        self.assertIn("visible_R_mean", js)
        self.assertIn("visible_H_mean", js)
        self.assertIn("visible_S_mean", js)
        self.assertIn("visible_V_mean", js)
        self.assertIn("visible_H_delta", js)
        self.assertIn("visible_S_delta", js)
        self.assertIn("visible_V_delta", js)
        self.assertIn("visible_HSV_delta", js)
        self.assertIn("hsvHValue", js)
        self.assertIn("hsvSValue", js)
        self.assertIn("hsvVValue", js)
        self.assertIn("hsvDeltaValue", js)
        self.assertIn("visible_color_delta", js)
        self.assertIn("stream_updated_epoch_s", js)
        self.assertIn("latency_mini2_age_ms", js)
        self.assertIn("latency_visible_age_ms", js)
        self.assertIn("latency_sync_offset_ms", js)
        self.assertIn("roi_result_age_ms", js)
        self.assertNotIn("auto_roi_result_status", js)
        self.assertIn("latencyOverallValue", js)
        self.assertIn("/api/csv", js)
        self.assertIn("/api/csv/status", js)
        self.assertIn("/api/csv/start", js)
        self.assertIn("/api/csv/stop", js)
        self.assertIn("auto_stop_confirmation_delay_s", js)
        self.assertIn("persistent_color_change", js)
        self.assertIn("pulse_control_failed", js)
        self.assertIn("미세 주입 제어 오류 정지", js)
        self.assertIn("maximum_volume", js)
        self.assertNotIn("auto_stop_guard_fraction", js)
        self.assertIn("/api/pump/dispense", js)
        self.assertIn("/api/pump/retract", js)
        self.assertIn("/api/pump/stop", js)
        self.assertIn("sendPumpCommand", js)
        self.assertIn("pumpCommandStatus", js)
        self.assertIn("녹화 시작 → b", js)
        self.assertIn("녹화 종료 → c", js)
        self.assertIn("펌프 주입 → b", js)
        self.assertIn("펌프 되감기 → a", js)
        self.assertIn("serialPumpDispenseButton", html)
        self.assertNotIn("/api/csv/label", js)
        self.assertNotIn("setCsvManualLabel", js)
        self.assertNotIn("manual_label", js)
        self.assertNotIn("manualLabelSelect", html)
        self.assertNotIn("csvMarkButton", html)
        self.assertIn("csv_recording_elapsed_s", js)
        self.assertIn("csv_rows_per_s", js)
        self.assertIn("/api/chemistry/constants/lookup", js)
        self.assertIn("pump_rate_ml_per_s", js)
        self.assertIn("function buildPumpSafetyPayload()", js)
        self.assertIn("maximum_pump_rate_ml_per_s", js)
        self.assertIn("absolute_maximum_volume_ml", js)
        self.assertIn("absolute_maximum_run_time_s", js)
        self.assertIn("pulse_ml_per_step_upper_bound", js)
        self.assertIn("auto_stop_slow_stage_enabled", js)
        self.assertIn("auto_stop_slow_onset_score", js)
        self.assertIn("auto_stop_slow_onset_duration_s", js)
        self.assertIn("auto_stop_slow_rate_steps_per_s", js)
        self.assertIn('id="slowStageEnabledInput" type="checkbox"', html)
        self.assertIn('id="slowRateStepsInput"', html)
        self.assertIn("보정 유량이 아닌 명목값", html)
        self.assertIn("JSON.stringify(safetyPayload)", js)
        self.assertNotIn("body: '{}'", js)
        self.assertIn("buildChemistryMetadataPayload", js)
        self.assertIn("lookupChemistryConstants", js)
        self.assertIn("scheduleChemistryConstantsLookup", js)
        self.assertIn("TITRATION_SUBSTANCE_PRESETS", js)
        self.assertIn("applyTitrationTypePreset", js)
        self.assertIn("strong_acid_strong_base", js)
        self.assertIn("weak_acid_strong_base", js)
        self.assertIn("strong_acid_weak_base", js)
        self.assertIn("weak_acid_weak_base", js)
        self.assertIn("sample: 'hydrochloric acid'", js)
        self.assertIn("sample: 'acetic acid'", js)
        self.assertIn("standard: 'sodium hydroxide'", js)
        self.assertIn("standard: 'ammonia'", js)
        self.assertIn("indicator: 'phenolphthalein'", js)
        self.assertIn("indicator: 'methyl_orange'", js)
        self.assertIn("indicator: 'bromothymol_blue'", js)
        self.assertIn("setSelectValueIfPresent('indicatorSelect', preset.indicator)", js)
        self.assertIn("titrationSelect.addEventListener('change'", js)
        self.assertIn("autoSelectRoomTemperatureCandidate", js)
        self.assertIn("populateConstantsCandidateSelect", js)
        self.assertIn("selectConstantsCandidate", js)
        self.assertIn("standard_solution_uncertainty_note", js)
        self.assertIn("constants_confirmation_status", js)
        self.assertIn("confirmed_by_user", js)
        self.assertIn("unconfirmed_ambiguous", js)
        self.assertIn("auto_selected_room_temperature", js)
        self.assertIn("selected_pka_value", js)
        self.assertIn("titrant_concentration_M", js)
        self.assertIn("indicatorSelect", js)
        self.assertNotIn("constantsLookupButton", html + js)
        self.assertNotIn("IUPAC 상수 조회", html)
        self.assertNotIn("volume_source", js)
        self.assertNotIn("manual_initial_volume_ml", js)
        self.assertNotIn("/api/manual-volume", js)
        self.assertNotIn("setManualVolume", js)
        self.assertNotIn("incrementManualVolume", js)
        self.assertIn("theoretical_equivalence_volume_ml", js)
        self.assertIn("equivalence_window_ml", js)
        self.assertIn("pump_elapsed_s", js)
        self.assertIn("distance_to_equivalence_ml", js)
        self.assertIn("equivalence_window_label", js)
        self.assertIn("csv_row_count", js)
        self.assertIn("csv_recording", js)
        self.assertIn("startCsvRecording", js)
        self.assertIn("stopCsvRecording", js)
        self.assertIn("csvDownloadLink", js)
        self.assertIn("calcCsvDownloadLink", html)
        self.assertIn("updateCsvDownloadLinks", js)
        self.assertIn("triggerCsvAutoDownload", js)
        self.assertIn("CSV 자동 다운로드 시작", js)
        self.assertIn("triggerCsvAutoDownload();", js)
        self.assertIn("refreshCsvStatus", js)
        self.assertIn("sendRoiRect", js)
        self.assertIn("enterRoiSetupMode", js)
        self.assertIn("ROI 선택 · 두 화면에서 드래그", js)
        self.assertIn("ROI 저장 중", js)
        self.assertIn("setRoiAutoTracking('off',", js)
        self.assertIn("toggleMini2Rotation", js)

        self.assertIn("thermal_rotation_degrees", js)
        self.assertIn("적외선 180° 회전", js)
        self.assertIn('class="frame-icon-button thermal-rotate-button"', html)
        self.assertIn('<svg aria-hidden="true" viewBox="0 0 24 24"', html)
        self.assertIn("data-rotate-label", html)
        self.assertIn('id="mini2CopyDiagnosticButton" class="inline-utility-button"', html)
        self.assertIn("진단 복사", html)
        self.assertIn(".inline-utility-button", css)
        self.assertIn(".diagnostic-metric", css)
        self.assertIn("button.querySelector('[data-rotate-label]')", js)
        self.assertIn("rotateButton.addEventListener('pointerdown'", js)
        self.assertIn("event.stopPropagation()", js)
        self.assertIn("자동추적 off", js)
        self.assertNotIn("sendRoiClick", js)
        self.assertNotIn("sendRoiPolygon", js)
        self.assertNotIn("/api/roi-click", js)
        self.assertNotIn("/api/roi-polygon", js)
        self.assertIn("/api/roi-auto-candidate", js)
        self.assertIn('id="roiAutoSetupButton"', html)
        self.assertIn("let autoRoiSetupEnabled = false", js)
        self.assertIn("stopAutoRoiSetup();", js)
        self.assertNotIn("lassoPoints", js)
        self.assertNotIn("updateLassoOverlay", js)
        self.assertNotIn("manual_lasso", js)
        self.assertNotIn("requestAutoCandidate", js)
        self.assertNotIn("setRoiAutoTracking('both'", js)
        self.assertNotIn("ROI 자동추적 중", js)
        self.assertNotIn("먼저 ROI 자동추적", js)
        self.assertIn("showVisibleCandidateNotice", js)
        self.assertIn("hideVisibleCandidateNotice", js)
        self.assertIn("카메라 ROI 저장 중", js)
        self.assertIn("카메라 ROI 저장", js)
        self.assertNotIn("일반카메라 화면 아래", js)
        self.assertIn("candidateNoticeTimer", js)
        self.assertIn("window.setTimeout(() => hideVisibleCandidateNotice(), 5000)", js)
        self.assertNotIn("payload.applied_now === true", js)
        self.assertNotIn("YOLO 후보", js)
        self.assertIn("image.closest('.camera-frame') || image", js)
        self.assertIn("hideRoiOverlay", js)
        self.assertIn("visible_roi_shape", js)
        self.assertNotIn("data.visible_roi_shape === 'mask'", js)
        self.assertNotIn("data.thermal_roi_shape === 'mask'", js)
        self.assertIn("ROI 선택 버튼", js)
        self.assertIn("ROI가 너무 작습니다", js)
        self.assertNotIn("setup_candidate_applied", js)
        self.assertNotIn("setup_candidate_not_found", js)
        self.assertNotIn("yolo_runtime_unavailable", js)
        self.assertNotIn("yolo_tensor_contract_mismatch", js)
        self.assertNotIn("thermal_raw_contrast_flat", js)
        self.assertNotIn("flat_thermal_matrix", js)
        self.assertNotIn("not_enough_thermal_contrast", js)
        self.assertNotIn("no_thermal_candidate", js)
        self.assertIn("addRoiDragHandler('visiblePreview', 'visibleRoiOverlay', 'visible')", js)
        self.assertIn("addRoiDragHandler('thermalPreview', 'thermalRoiOverlay', 'thermal')", js)
        self.assertIn("mini2RotateButton", js)
        self.assertIn("ROI 고정 필요", js)
        self.assertIn("roi_locked", js)
        self.assertIn("roi_session_id", js)
        self.assertIn("naturalWidth", js)
        self.assertIn("naturalHeight", js)
        self.assertIn("temperatureValue", js)
        self.assertIn("temperatureUnit", js)
        self.assertIn("thermal_roi", js)
        self.assertIn("visible_roi", js)
        self.assertIn("roi_source", js)
        self.assertIn("roi_shape", js)
        self.assertIn("visible_roi_shape", js)
        self.assertIn("thermal_roi_shape", js)
        self.assertNotIn("mask_stability", js)
        self.assertNotIn("visible_mask_source", js)
        self.assertNotIn("thermal_mask_source", js)
        self.assertIn("visiblePreview", js)
        self.assertIn("thermalPreview", js)
        self.assertNotIn("PREVIEW_REFRESH_MS = 40", js)
        self.assertNotIn("setInterval(refreshPreview", js)
        self.assertNotIn("live/thermal.bmp", html + js)
        self.assertNotIn("live/visible.bmp", html + js)
        self.assertIn("프레임 멈춤", js)
        self.assertIn("preview_visible_latency_ms", js)
        self.assertNotIn("정확한 브라우저 표시 지연", html + js)
        for forbidden in [
            "function parseCsv",
            "loadFile",
            "FileReader",
            "readAsText",
            "getDisplayMedia",
            "navigator.mediaDevices",
            "downloadLiveCsv",
            "drawLines",
            "calculateChemistryCard",
            "csvInput",
            "dropZone",
            "startApiPoll",
            "stopApiPoll",
            "checkApiHealth",
            "findLatestCsv",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, html + js)

        self.assertIn(".sensor-grid", css)
        self.assertIn(".camera-panel", css)
        self.assertIn(".candidate-notice", css)
        self.assertIn(".candidate-notice.is-error", css)
        self.assertIn(".candidate-notice.is-success", css)
        self.assertIn(".candidate-notice.is-waiting", css)
        self.assertIn(".toast-notice", css)
        self.assertIn("position: fixed", css)
        self.assertIn(".temperature-panel", css)
        self.assertIn(".temperature-value", css)
        self.assertIn(".details-panel", css)
        self.assertIn(".details-panel[open]", css)
        self.assertIn("touch-action: none", css)
        self.assertIn("-webkit-user-drag: none", css)
        self.assertIn("@font-face", css)
        self.assertIn("PretendardVariable.woff2", css)
        self.assertIn("#0066cc", css)
        self.assertNotIn("radial-gradient", css)

        self.assertTrue(Path("website/assets/fonts/PretendardVariable.woff2").is_file())

    def test_titration_type_preset_records_btb_for_weak_acid_weak_base(self):
        js = Path("website/app.js").read_text(encoding="utf-8")
        preset_source = js[
            js.index("const TITRATION_SUBSTANCE_PRESETS") : js.index("function setText")
        ]
        helper_source = js[
            js.index("function setSelectValueIfPresent") : js.index("function indicatorTransitionRange")
        ]
        script = f"""
const assert = require('assert');
const elements = {{
  titrationTypeSelect: {{ value: 'weak_acid_weak_base' }},
  sampleSubstanceInput: {{ value: '', options: [{{value:'hydrochloric acid'}}, {{value:'acetic acid'}}] }},
  standardSolutionNameInput: {{ value: '', options: [{{value:'sodium hydroxide'}}, {{value:'ammonia'}}] }},
  indicatorSelect: {{ value: '', options: [{{value:'phenolphthalein'}}, {{value:'methyl_orange'}}, {{value:'bromothymol_blue'}}] }},
}};
const $ = (id) => elements[id];
function updateConcentrationCalculationPreview() {{}}
function scheduleChemistryConstantsLookup() {{}}
{preset_source}
{helper_source}
applyTitrationTypePreset({{lookup: false}});
assert.strictEqual(elements.sampleSubstanceInput.value, 'acetic acid');
assert.strictEqual(elements.standardSolutionNameInput.value, 'ammonia');
assert.strictEqual(elements.indicatorSelect.value, 'bromothymol_blue');
elements.titrationTypeSelect.value = 'strong_acid_weak_base';
applyTitrationTypePreset({{lookup: false}});
assert.strictEqual(elements.indicatorSelect.value, 'methyl_orange');
"""
        subprocess.run(["node", "-e", script], check=True)


    def test_website_has_demo_stage_graphs_and_single_result_surface(self):
        html = Path("website/index.html").read_text(encoding="utf-8")
        js = Path("website/app.js").read_text(encoding="utf-8")
        css = Path("website/styles.css").read_text(encoding="utf-8")

        for expected in [
            "녹화",
            "결과",
            "csvCollectionModeButton",
            "concentrationCalculationModeButton",
            "csvCollectionControls",
            "calcSampleConcentrationValue",
            "calcFinalVolumeValue",
            "calcPredictedEquivalenceValue",
            "calcCsvDownloadLink",
            "calcModeStatus",
            "sensorGrid",
            "미지 시료 농도",
            "현재 상태",
            "colorTrendCanvas",
            "thermalTrendCanvas",
            "demoOutcomeBadge",
            "펌프 정지",
            "녹화 종료 후 계산 결과 표시",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, html)

        for pattern in [
            r'<div id="csvStatusStrip"[^>]*class="status-strip csv-mode-only"[^>]*aria-label="현재 상태"[^>]*>',
            r'<span id="previewStatus"[^>]*class="pill"[^>]*role="status"[^>]*aria-live="polite"[^>]*>',
            r'<p id="calcModeStatus"[^>]*class="result-status"[^>]*role="status"[^>]*aria-live="polite"[^>]*>',
            r'<button id="csvStartButton"[^>]*class="[^"]*\brecord-button\b[^"]*\bstart-button\b[^"]*"',
            r'<button id="serialPumpDispenseButton"[^>]*class="[^"]*\bpump-button\b[^"]*"',
            r'<button id="serialPumpRetractButton"[^>]*class="[^"]*\bpump-button\b[^"]*"',
            r'<button id="serialPumpStopButton"[^>]*class="[^"]*\bpump-button\b[^"]*\bpump-stop-button\b[^"]*"',
        ]:
            with self.subTest(pattern=pattern):
                self.assertRegex(html, pattern)
        self.assertNotRegex(
            html,
            r'<div id="csvStatusStrip"[^>]*(?:role="status"|aria-live="polite")',
        )
        self.assertNotRegex(
            html,
            r'<div id="visibleCandidateNotice"[^>]*(?:role="status"|aria-live="polite")',
        )
        self.assertNotIn("pH", html)
        self.assertNotIn("예측 당량점", html)
        self.assertRegex(html, r'id="theoryEquivalenceInput" type="hidden"')
        self.assertRegex(html, r'id="equivalenceWindowInput" type="hidden"')
        self.assertGreater(html.index('class="demo-stage"'), html.index('id="csvPanel"'))
        self.assertIn('serialPumpStopButton', html[html.index('id="csvCollectionControls"'):html.index('<details class="settings-drawer')])
        self.assertIn('class="control-row pump-controls"', html)
        self.assertNotIn('class="main-actions csv-mode-only"', html)
        self.assertLess(html.index('id="resultsView"'), html.index('class="trend-grid"'))
        self.assertLess(html.index('class="final-results"'), html.index('class="trend-grid"'))

        for expected_css in [
            ".main-actions .start-button { background: var(--blue);",
            ".main-actions .stop-button { background: #fff5f5;",
            ".pump-button { background: white;",
            ".pump-stop-button { color: var(--red);",
            "min-height: 2.75rem",
        ]:
            with self.subTest(expected_css=expected_css):
                self.assertIn(expected_css, css)
        self.assertNotIn("min-height: 2.65rem", css)

        for forbidden in [
            "concentrationCalculatorForm",
            "observedEquivalenceInput",
            "sampleValenceInput",
            "titrantValenceInput",
            "calcUseTheoryButton",
            "calcTheoreticalEquivalenceValue",
            "calcTitrantConcentrationValue",
            "calcFormulaValue",
            "calcConcentrationErrorValue",
            "계산식",
            "calcResultSourceValue",
            "concentrationSourceLabel",
            "기준 <strong",
            "결과 기준",
            "CSV 수집",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, html)

        for expected in [
            "let currentAppMode = 'csv'",
            "let latestCsvStatus = null",
            "parseFiniteNumber",
            "isLikelyInvalidMini2ZeroCelsius",
            "celsiusSummaryLooksAllZero",
            "Number.isFinite(avg)",
            "updateConcentrationModePreview",
            "calculateTheoreticalEquivalencePh",
            "predictedEquivalencePhFromCsv",
            "currentTheoreticalEquivalencePh",
            "setAppMode",
            "addModeHandlers",
            "document.querySelectorAll('.csv-mode-only')",
            "sensorGrid",
            "predicted_equivalence_pH",
            "sample_concentration_from_predicted_equivalence_M",
            "predicted_equivalence_volume_ml",
            "thermal_conversion_status",
            "if (csv?.state === 'stopped') {",
            "triggerCsvAutoDownload();",
            "setAppMode('calculator');",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, js)

        for forbidden in [
            "observedEquivalenceManual",
            "calculateTitrantConcentrationM",
            "calcFormulaValue",
            "calcConcentrationErrorValue",
            "Number.isFinite(Number(data.temperature_avg_c))",
            "Cs = Ct × Vt",
            "Ct = Cs × Vs",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, js)

        for expected in [
            ".mode-switcher",
            ".mode-button.is-active",
            ".mode-hidden",
            ".demo-stage",
            ".trend-grid",
            ".final-result-grid",
            ".result-status",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, css)

    def test_concentration_calculator_can_compute_theoretical_ph_without_csv(self):
        js = Path("website/app.js").read_text(encoding="utf-8")
        start = js.index("function parseFiniteNumber")
        end = js.index("function readNumericInput")
        helper_source = js[start:end]
        script = f"""
const assert = require('assert');
{helper_source}
const base = {{
  sampleConcentrationM: 0.1,
  sampleVolumeMl: 10,
  sampleValence: 1,
  titrantConcentrationM: 0.1,
  titrantValence: 1,
}};
assert.strictEqual(calculateTheoreticalEquivalencePh({{...base, titrationType: 'strong_acid_strong_base'}}).toFixed(2), '7.00');
assert.ok(calculateTheoreticalEquivalencePh({{...base, titrationType: 'weak_acid_strong_base', samplePka: 4.76}}) > 8.0);
assert.ok(calculateTheoreticalEquivalencePh({{...base, titrationType: 'strong_acid_weak_base', titrantPkb: 4.75}}) < 6.0);
assert.strictEqual(calculateTheoreticalEquivalencePh({{...base, titrationType: 'weak_acid_weak_base', samplePka: 4.76, titrantPkb: 4.75}}).toFixed(2), '7.00');
"""
        subprocess.run(["node", "-e", script], check=True)

    def test_result_ph_uses_prediction_not_theory_fallback(self):
        js = Path("website/app.js").read_text(encoding="utf-8")
        start = js.index("function parseFiniteNumber")
        end = js.index("function readNumericInput")
        helper_source = js[start:end]
        script = f"""
const assert = require('assert');
{helper_source}
function currentChemistryNumbers() {{
  return {{
    sampleConcentrationM: 0.1,
    sampleVolumeMl: 10,
    sampleValence: 1,
    titrantConcentrationM: 0.1,
    titrantValence: 1,
  }};
}}
assert.ok(Number.isNaN(predictedEquivalencePhFromCsv({{theoretical_equivalence_pH: 8.72}})));
assert.strictEqual(predictedEquivalencePhFromCsv({{predicted_equivalence_pH: 8.88}}).toFixed(2), '8.88');
assert.ok(predictedEquivalencePhFromCsv({{
  sample_concentration_from_predicted_equivalence_M: 0.1,
  sample_volume_ml: 10,
  sample_valence: 1,
  titrant_concentration_M: 0.1,
  titrant_valence: 1,
  titration_type: 'weak_acid_strong_base',
  selected_pka_value: 4.76,
}}) > 8.0);
"""
        subprocess.run(["node", "-e", script], check=True)

    def test_mini2_zero_celsius_guard_uses_backend_status_and_all_zero_summary(self):
        js = Path("website/app.js").read_text(encoding="utf-8")
        start = js.index("function parseFiniteNumber")
        end = js.index("function formatNumber")
        helper_source = js[start:end]
        script = f"""
const assert = require('assert');
{helper_source}
assert.strictEqual(isLikelyInvalidMini2ZeroCelsius({{
  temperature_avg_c: 25,
  thermal_conversion_status: 'non_finite',
}}), true);
assert.strictEqual(isLikelyInvalidMini2ZeroCelsius({{
  temperature_avg_c: 0,
  raw_avg: 5000,
  thermal_mode: 'mini2_uvc_raw_official_roi_celsius',
  thermal_conversion_status: 'ok',
  thermal_warning: 'legacy warning',
}}), false);
assert.strictEqual(isLikelyInvalidMini2ZeroCelsius({{
  temperature_avg_c: 0,
  raw_avg: 5000,
  thermal_mode: 'mini2_uvc_raw_official_roi_celsius',
  thermal_conversion_status: 'suspect_all_zero',
}}), true);
assert.strictEqual(isLikelyInvalidMini2ZeroCelsius({{
  temperature_avg_c: 0,
  raw_avg: 5000,
  thermal_mode: 'mini2_uvc_raw_official_roi_celsius',
  thermal_conversion_status: 'ok',
  temperature_min_c: 0,
  temperature_max_c: 0,
}}), false);
assert.strictEqual(isLikelyInvalidMini2ZeroCelsius({{
  temperature_avg_c: 0,
  raw_avg: 5000,
  thermal_mode: 'mini2_uvc_raw_official_roi_celsius',
  temperature_min_c: -0.4,
  temperature_max_c: 0.3,
  temperature_std_c: 0.1,
}}), false);
assert.strictEqual(isLikelyInvalidMini2ZeroCelsius({{
  temperature_avg_c: 0,
  raw_avg: 5000,
  thermal_mode: 'mini2_uvc_raw_official_roi_celsius',
  temperature_min_c: 0,
  temperature_max_c: 0,
  temperature_std_c: 0,
}}), true);
assert.strictEqual(hasTrustedCelsiusTemperature({{
  celsius_allowed: true,
  temperature_avg_c: 0,
  temperature_min_c: -0.2,
  temperature_max_c: 0.3,
  temperature_provenance: 'device_global_summary',
  temperature_scope: 'device_global_summary',
  full_matrix_celsius_allowed: false,
}}), true);
assert.strictEqual(hasTrustedCelsiusTemperature({{
  celsius_allowed: true,
  temperature_avg_c: 0,
  temperature_min_c: 0,
  temperature_max_c: 0,
  raw_avg: 5000,
  temperature_provenance: 'device_global_summary',
  temperature_scope: 'device_global_summary',
  full_matrix_celsius_allowed: false,
}}), false);
assert.strictEqual(hasTrustedCelsiusTemperature({{
  celsius_allowed: false,
  temperature_avg_c: 0,
  temperature_provenance: 'device_global_summary',
  temperature_scope: 'device_global_summary',
}}), false);
assert.strictEqual(hasTrustedCelsiusTemperature({{
  celsius_allowed: true,
  temperature_avg_c: 0,
  temperature_provenance: 'roi_matrix',
  temperature_scope: 'roi_matrix',
  full_matrix_celsius_allowed: true,
}}), false);
assert.strictEqual(hasTrustedCelsiusTemperature({{
  temperature_avg_c: 22.5,
}}), false);
assert.strictEqual(hasTrustedCelsiusTemperature({{
  celsius_allowed: true,
  full_matrix_celsius_allowed: false,
  temperature_avg_c: 22.5,
  temperature_min_c: 22.0,
  temperature_max_c: 23.0,
}}), false);
assert.strictEqual(hasTrustedCelsiusTemperature({{
  celsius_allowed: true,
  full_matrix_celsius_allowed: false,
  temperature_avg_c: 22.5,
  temperature_min_c: 22.0,
  temperature_max_c: 23.0,
  temperature_provenance: 'windows_official_mini2_roi_scalar',
  temperature_scope: 'thermal_roi',
}}), true);
assert.strictEqual(hasTrustedCelsiusTemperature({{
  celsius_allowed: true,
  full_matrix_celsius_allowed: false,
  temperature_avg_c: 23.5,
  temperature_min_c: 22.0,
  temperature_max_c: 23.0,
  temperature_provenance: 'windows_official_mini2_roi_scalar',
  temperature_scope: 'thermal_roi',
}}), false);
assert.strictEqual(hasTrustedCelsiusTemperature({{
  celsius_allowed: true,
  full_matrix_celsius_allowed: false,
  temperature_avg_c: 22.5,
  temperature_min_c: 22.0,
  temperature_max_c: 23.0,
  temperature_scope: 'thermal_roi',
}}), false);
"""
        subprocess.run(["node", "-e", script], check=True)

    def test_windows_bat_launchers_are_minimal_for_demo(self):
        launchers = sorted(path.name for path in Path("launchers/windows").glob("*.bat"))

        self.assertEqual(launchers, ["20_windows_live_collect.bat", "21_open_dashboard_server.bat"])
        dashboard = Path("launchers/windows/21_open_dashboard_server.bat").read_text(encoding="utf-8")
        collector = Path("launchers/windows/20_windows_live_collect.bat").read_text(encoding="utf-8")
        self.assertIn("tools\\dashboard_server.py", dashboard)
        self.assertIn("20_windows_live_collect.bat", dashboard)
        self.assertIn("tools\\windows_live_collect.py", collector)
        self.assertIn("--live-stream-base", dashboard)
        self.assertIn("Get-NetTCPConnection", dashboard)
        self.assertIn("/api/health", dashboard)
        self.assertIn("auto_titration_dashboard", dashboard)
        self.assertIn("OPEN_BROWSER", dashboard)
        self.assertIn('set "FRAMES=999999"', collector)
        self.assertIn('set "ROI_AUTO_DETECT=off"', collector)
        self.assertIn('set "AUTO_INSTALL_YOLO=0"', collector)
        self.assertIn('set "PUMP_START_COMMAND=b"', collector)
        self.assertIn('set "PUMP_RETRACT_COMMAND=a"', collector)
        self.assertIn('set "PUMP_PULSE_DIRECTION=b"', collector)
        self.assertNotIn("Stop-Process", collector)
        self.assertNotIn("tools\\windows_live_collect.py|20_windows_live_collect.bat", dashboard)
        self.assertNotIn("call :find_python", dashboard + collector)
        self.assertNotIn(":find_python", dashboard + collector)

    def test_website_exposes_practical_run_health_panel(self):
        html = Path("website/index.html").read_text(encoding="utf-8")
        js = Path("website/app.js").read_text(encoding="utf-8")

        for removed in [
            "실전 사용 상태 점검",
            "healthCollectorValue",
            "healthVisibleValue",
            "healthThermalValue",
            "healthCsvValue",
            "healthActionValue",
        ]:
            self.assertNotIn(removed, html)
        self.assertIn("/api/collector-health", js)
        self.assertIn("Collector 창/포트 8766 확인", js)
        self.assertIn("mini2_reconnect_count", js)

    def test_website_does_not_offer_browser_mini2_manual_upload_or_explainer_sections(self):
        html = Path("website/index.html").read_text(encoding="utf-8")
        js = Path("website/app.js").read_text(encoding="utf-8")

        for forbidden in [
            "Mini2 시작",
            "Mini2 화면공유",
            "CSV 파일 선택 또는 드래그",
            "getDisplayMedia",
            "navigator.mediaDevices",
            "csvInput",
            "dropZone",
            "FileReader",
            "readAsText",
            "parseCsv",
            "downloadLiveCsv",
            "liveColumns",
            "시연 순서",
            "전람회 발표 포인트",
            "파일 역할",
            "실시간 모니터 시작",
            "API 상태 확인",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, html + js)


    def test_static_website_omits_android_pairing_and_bluetooth_pump_controls(self):
        html = Path("website/index.html").read_text(encoding="utf-8")
        js = Path("website/app.js").read_text(encoding="utf-8")
        css = Path("website/styles.css").read_text(encoding="utf-8")

        for forbidden in [
            "mobileSourceValue",
            "mobilePairButton",
            "mobilePairStatus",
            "mobileRoiStatus",
            "Android 연결",
            "모바일 ROI",
            "crashDownloadLink",
            "auto-titration-android-crash.txt",
            "pumpBluetoothButton",
            "pumpRightButton",
            "pumpStopButton",
            "pumpResetButton",
            "Bluetooth 펌프",
            "펌프 BT 상태",
            "펌프 시작(b)",
            "펌프 정지(c)",
            "카운터 리셋(r)",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, html)
        for forbidden in [
            "/api/mobile/status",
            "/api/mobile/pair",
            "refreshMobileStatus",
            "pairMobileDevice",
            "applyMobileStatus",
            "addMobileSourceHandlers",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, js)
        self.assertNotIn("source-panel", css)

    def test_roi_setup_keeps_manual_rectangle_and_optional_setup_only_auto_roi(self):
        js = Path("website/app.js").read_text(encoding="utf-8")
        html = Path("website/index.html").read_text(encoding="utf-8")

        self.assertIn("ROI 선택", html)
        self.assertIn("sendRoiRect(target, rect)", js)
        self.assertIn("updateRoiOverlay(imageId, overlayId, rect, { draft: true })", js)
        self.assertIn("let roiSetupMode = true", js)
        self.assertNotIn("kickstartRoiAutoTracking", js)
        self.assertNotIn("kickstartSingleRoiCandidate", js)
        self.assertIn('id="roiAutoSetupButton" class="inline-utility-button csv-mode-only" type="button" aria-pressed="false">자동 ROI OFF</button>', html)
        self.assertGreater(html.index('id="roiAutoSetupButton"'), html.index('<details class="settings-drawer'))
        self.assertIn('id="roiResetButton"', html)
        self.assertIn("postRoiAction('/api/roi-auto-candidate'", js)
        self.assertIn("autoSetupButton.addEventListener('click', toggleAutoRoiSetup)", js)
        self.assertIn("if (latestRoiLocked || data.roi_state === 'recording') stopAutoRoiSetup();", js)
        self.assertNotIn("roi_auto_detect: requestedMode", js)
        self.assertIn("setRoiAutoTracking('off',", js)

    def test_lasso_ui_is_removed_for_rectangle_only_roi(self):
        js = Path("website/app.js").read_text(encoding="utf-8")
        html = Path("website/index.html").read_text(encoding="utf-8")
        css = Path("website/styles.css").read_text(encoding="utf-8")

        self.assertNotIn("Lasso", html + js)
        self.assertNotIn("lasso", html + js + css)
        self.assertNotIn("roi-polygon", js)
        self.assertNotIn("boundary_refine", js)
        self.assertNotIn("is-saved", css)


if __name__ == "__main__":
    unittest.main()
