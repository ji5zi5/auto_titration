from pathlib import Path
import unittest


class AndroidScaffoldTests(unittest.TestCase):
    def test_android_project_contains_phone_standalone_foundation(self):
        root = Path("mobile/android")
        expected_files = [
            root / "settings.gradle.kts",
            root / "build.gradle.kts",
            root / "app/build.gradle.kts",
            root / "app/src/main/AndroidManifest.xml",
            root / "app/src/main/java/kr/auto/titration/mobile/MainActivity.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/MobileFeatureClient.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/session/PhoneRunSession.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/session/RecordingTimeline.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/data/CsvSchema.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/data/ExperimentConfig.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/data/CsvFeatureRow.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/data/LocalCsvWriter.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/data/StandaloneFeatureFrame.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/vision/VisibleFeatures.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/vision/VisibleFeatureExtractor.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/thermal/ThermalModels.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/thermal/Mini2ValidationGate.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/thermal/ThermalFrameModels.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/chemistry/TitrationPreset.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/chemistry/EquivalenceCalculator.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/chemistry/IndicatorModels.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/ml/ModelContracts.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/ml/EquivalenceJsonModel.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/ml/BaselineTrainer.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/pump/PumpCommandContract.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/pump/PumpModels.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/pump/ManualPumpController.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/pump/BluetoothPumpTransport.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/export/ExportManifest.kt",
            root / "app/src/main/java/kr/auto/titration/mobile/export/SessionExporter.kt",
            root / "app/src/main/res/xml/mini2_device_filter.xml",
            root / "README.md",
        ]
        for path in expected_files:
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"missing {path}")

        manifest = (root / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        main = (root / "app/src/main/java/kr/auto/titration/mobile/MainActivity.kt").read_text(encoding="utf-8")
        probe = (root / "app/src/main/java/kr/auto/titration/mobile/Mini2UsbProbe.kt").read_text(encoding="utf-8")
        client = (root / "app/src/main/java/kr/auto/titration/mobile/MobileFeatureClient.kt").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")

        self.assertIn("android.permission.CAMERA", manifest)
        self.assertIn("android.hardware.usb.host", manifest)
        self.assertIn("mini2_device_filter", manifest)
        self.assertNotIn("android.permission.INTERNET", manifest)
        self.assertIn("CameraX", main)
        self.assertIn("ImageAnalysis", main)
        self.assertIn("PhoneRunSession", main)
        self.assertIn("phone-local", main)
        self.assertIn("Android WebView", main)
        self.assertIn("file:///android_asset/index.html", main)
        self.assertIn("lockedVisibleRoi = null", main)
        self.assertIn("previousVisibleFeatures = null", main)
        self.assertNotIn("runCatching", main)
        self.assertNotIn("serverInput", main)
        self.assertNotIn("tokenInput", main)
        self.assertIn("mobile_feature_frame.v1", client)
        self.assertIn("/api/mobile/ingest", client)
        self.assertIn("UsbManager", probe)
        self.assertIn("0x2bdf", probe.lower())
        self.assertIn("0x0102", probe.lower())
        self.assertIn("calibrated", probe)
        self.assertIn("raw_unverified", probe)
        self.assertIn("blocked", probe)
        self.assertIn("requestPermissionOnce", probe)
        self.assertIn("permissionRequests", probe)
        self.assertIn("USB host", readme)
        self.assertIn("CameraX", readme)
        self.assertIn("Mini2", readme)
        self.assertIn("phone-only", readme)
        self.assertIn("Standalone", readme)

    def test_android_scaffold_does_not_claim_calibrated_celsius_without_validation(self):
        root = Path("mobile/android")
        text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.kt"))

        self.assertIn("thermal_calibrated", text)
        self.assertIn("raw_unverified", text)
        self.assertIn("isValidatedForCelsius", text)
        self.assertNotIn("temperatureCelsius = raw", text)
        self.assertNotIn("/ 64", text)

    def test_pump_contract_is_manual_only_in_android_foundation(self):
        pump = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile/pump/PumpCommandContract.kt").read_text(
            encoding="utf-8"
        )
        controller = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile/pump/ManualPumpController.kt").read_text(
            encoding="utf-8"
        )
        bluetooth = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile/pump/BluetoothPumpTransport.kt").read_text(
            encoding="utf-8"
        )
        manifest = Path("mobile/android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        bridge = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile/AndroidBridge.kt").read_text(
            encoding="utf-8"
        )
        adapter = Path("website/android-webview.js").read_text(encoding="utf-8")
        index = Path("website/index.html").read_text(encoding="utf-8")

        for command in ["a left/reverse", "b right/forward", "c stop", "s status", "r reset"]:
            self.assertIn(command, pump)
        self.assertIn("commandMayComeFromAutomation", pump)
        self.assertIn("false", pump)
        self.assertIn("supportedLetters", pump)
        self.assertIn("letter in supportedLetters", pump)
        self.assertNotIn("startsWith(verb)", pump)
        self.assertIn("ManualPumpController", controller)
        self.assertIn("sendUserCommand", controller)
        self.assertIn("USER_ACTION", controller)
        self.assertIn("ML_STATUS_AUTOMATION", controller)
        self.assertIn("cannot send pump command", controller)
        self.assertIn("PumpCommand", controller)
        self.assertIn("StartRight", controller)
        self.assertIn('letter = "b"', controller)
        self.assertIn("PumpStatusParser", controller)
        self.assertIn("STATUS steps=", controller)
        self.assertIn("BluetoothAdapter", bluetooth)
        self.assertIn("createRfcommSocketToServiceRecord", bluetooth)
        self.assertIn("00001101-0000-1000-8000-00805F9B34FB", bluetooth)
        self.assertIn("BLUETOOTH_CONNECT", manifest)
        self.assertIn("pumpStatus", bridge)
        self.assertIn("sendPumpCommand", bridge)
        self.assertIn("pumpBluetoothButton", index + adapter)
        self.assertIn("펌프 BT 상태", index + adapter)

    def test_android_recording_ui_exposes_complete_config_inputs(self):
        index = Path("website/index.html").read_text(encoding="utf-8")

        for element_id in [
            "titrationTypeSelect",
            "sampleSubstanceInput",
            "sampleConcentrationInput",
            "sampleVolumeInput",
            "standardSolutionNameInput",
            "standardConcentrationInput",
            "theoryEquivalenceInput",
            "pumpRateInput",
        ]:
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', index)

    def test_android_start_recording_passes_explicit_webview_config_payload(self):
        adapter = Path("website/android-webview.js").read_text(encoding="utf-8")
        app = Path("website/app.js").read_text(encoding="utf-8")

        self.assertIn("buildAndroidRecordingConfig", adapter)
        self.assertIn("buildPumpTimelineStartPayload", adapter)
        self.assertIn("readBridgeJson('startRecording', JSON.stringify(config))", adapter)
        for key in [
            "titration_type",
            "sample_name",
            "sample_concentration_M",
            "sample_volume_ml",
            "sample_valence",
            "titrant_name",
            "titrant_concentration_M",
            "titrant_valence",
            "equivalence_formula",
            "calculated_theoretical_equivalence_volume_ml",
            "sample_concentration_from_theoretical_equivalence_M",
            "theoretical_equivalence_volume_ml",
            "pump_rate_ml_per_s",
        ]:
            with self.subTest(key=key):
                self.assertIn(key, adapter)
                self.assertIn(key, app)
        self.assertIn("readRequiredTextInput('titrationTypeSelect'", app)
        self.assertIn("readRequiredTextInput('sampleSubstanceInput'", app)
        self.assertIn("readRequiredTextInput('standardSolutionNameInput'", app)
        self.assertNotIn("sample_name: sampleQuery ||", app)
        self.assertNotIn("titrantName = readTextInput('standardSolutionNameInput') ||", app)

    def test_android_js_config_failure_does_not_call_native_start_recording(self):
        adapter = Path("website/android-webview.js").read_text(encoding="utf-8")
        failure_branch = adapter[adapter.index("function startAndroidRecordingWithConfig"):]

        self.assertIn("catch (error)", failure_branch)
        self.assertIn("녹화 시작 차단", failure_branch)
        self.assertIn("return;", failure_branch)
        self.assertLess(
            failure_branch.index("return;"),
            failure_branch.index("readBridgeJson('startRecording', JSON.stringify(config))"),
            "config failure branch must return before native startRecording",
        )

    def test_android_bridge_and_config_parser_require_recording_json(self):
        root = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile")
        bridge = (root / "AndroidBridge.kt").read_text(encoding="utf-8")
        config = (root / "data/ExperimentConfig.kt").read_text(encoding="utf-8")

        self.assertIn("fun startRecording(configJson: String)", bridge)
        self.assertNotIn("fun startRecording(): String = safeJson", bridge)
        self.assertIn("fun fromJson(payloadJson: String)", config)
        self.assertIn("fun fromJson(payload: JSONObject)", config)
        self.assertIn("requireNonBlank", config)
        self.assertIn("requirePositiveDouble", config)
        self.assertIn("!value.isFinite() || value <= 0.0", config)
        for key in [
            "titration_type",
            "sample_name",
            "sample_concentration_M",
            "sample_volume_ml",
            "titrant_name",
            "titrant_concentration_M",
            "theoretical_equivalence_volume_ml",
            "pump_rate_ml_per_s",
        ]:
            with self.subTest(key=key):
                self.assertIn(key, config)

    def test_android_invalid_config_blocks_before_pump_commands(self):
        main = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt").read_text(
            encoding="utf-8"
        )

        self.assertIn("fun startRecordingFromBridge(configJson: String)", main)
        self.assertIn("ExperimentConfig.fromJson(configJson)", main)
        self.assertIn("recording_start_blocked", main)
        self.assertLess(main.index("ExperimentConfig.fromJson(configJson)"), main.index("PumpCommand.Reset"))
        self.assertLess(main.index("runSession.config = recordingConfig"), main.index("runSession.startRecording"))

    def test_android_recording_blocks_on_pump_bluetooth_error(self):
        main = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt").read_text(
            encoding="utf-8"
        )
        controller = Path(
            "mobile/android/app/src/main/java/kr/auto/titration/mobile/pump/ManualPumpController.kt"
        ).read_text(encoding="utf-8")
        start_fn = main[main.index("fun startRecordingFromBridge"):main.index("fun stopRecordingFromBridge")]

        self.assertIn("isPumpFailureResponse(resetResponse)", start_fn)
        self.assertIn("isPumpFailureResponse(startResponse)", start_fn)
        self.assertLess(start_fn.index("val resetResponse"), start_fn.index("isPumpFailureResponse(resetResponse)"))
        self.assertLess(start_fn.index("isPumpFailureResponse(resetResponse)"), start_fn.index("val startResponse"))
        self.assertIn("recording_start_blocked", start_fn)
        self.assertIn("trimStart().uppercase(Locale.US)", main)
        self.assertIn('startsWith("ERROR")', main)
        self.assertIn('startsWith("BLOCKED")', main)
        self.assertIn("command accepted/sent", main)
        self.assertIn("firmware STATUS observed", main)
        self.assertIn("trimStart().uppercase(Locale.US)", controller)

    def test_android_recording_does_not_poll_pump_status_from_frame_loop(self):
        main = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt").read_text(
            encoding="utf-8"
        )
        frame_loop = main[main.index("private fun analyzeVisibleFrame"):main.index("private fun currentThermalStatus")]

        self.assertNotIn("sendUserCommand(PumpCommand.Status)", frame_loop)
        self.assertNotIn("refreshPumpStatusIfDue", main)
        self.assertIn("refreshPumpStatusFromUserAction", main)
        self.assertIn("fun pumpStatusFromBridge", main)

    def test_phone_local_csv_session_skeleton_records_pump_volume_fields(self):
        root = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile")
        session = (root / "session/PhoneRunSession.kt").read_text(encoding="utf-8")
        timeline = (root / "session/RecordingTimeline.kt").read_text(encoding="utf-8")
        row = (root / "data/CsvFeatureRow.kt").read_text(encoding="utf-8")
        writer = (root / "data/LocalCsvWriter.kt").read_text(encoding="utf-8")
        exporter = (root / "export/SessionExporter.kt").read_text(encoding="utf-8")

        self.assertIn("startRecording", session)
        self.assertIn("recordFrame", session)
        self.assertIn("injectedVolumeMl", session)
        self.assertIn("distanceToEquivalenceMl", session)
        self.assertIn("pumpRateMlPerS", timeline)
        self.assertIn("injected_volume_ml", row)
        self.assertIn("distance_to_equivalence_ml", row)
        self.assertIn("pump_step_count", row)
        self.assertIn("pump_firmware_volume_ml", row)
        self.assertIn("pump_confirmed_step_count", row)
        self.assertIn("pump_last_status", row)
        self.assertIn("thermalRawRoiAvg", row)
        self.assertIn("thermal_raw_roi_avg", row)
        self.assertIn("thermalRawMean", row)
        self.assertIn("thermal_raw_mean", row)
        self.assertIn("thermalMatrixShape", row)
        self.assertIn("thermal_matrix_shape", row)
        self.assertIn("thermalRawFrame", (root / "data/StandaloneFeatureFrame.kt").read_text(encoding="utf-8"))
        self.assertIn("latestRawFrameSummary", (root / "Mini2UsbProbe.kt").read_text(encoding="utf-8"))
        self.assertIn("currentThermalRawFrame", (root / "MainActivity.kt").read_text(encoding="utf-8"))
        self.assertIn("thermal_raw_roi_avg", (root / "data/CsvSchema.kt").read_text(encoding="utf-8"))
        self.assertIn("updatePumpSnapshot", session)
        self.assertIn("phone_local_timeline", row)
        self.assertIn("injected_volume_timeline_estimate", session)
        self.assertIn("pump_firmware_volume_absent", session)
        self.assertIn("thermal_not_calibrated", session)
        self.assertIn("writeHeaderIfNeeded", writer)
        self.assertIn("appendRow", writer)
        self.assertIn("buildCsv", exporter)
        self.assertIn("metadataJson", exporter)

    def test_android_csv_status_exposes_selected_experiment_config(self):
        main = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile/MainActivity.kt").read_text(
            encoding="utf-8"
        )
        row = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile/data/CsvFeatureRow.kt").read_text(
            encoding="utf-8"
        )

        for token in [
            "runSession.config.titrationType",
            "runSession.config.sampleName",
            "runSession.config.sampleConcentrationM",
            "runSession.config.sampleVolumeMl",
            "runSession.config.sampleValence",
            "runSession.config.titrantName",
            "runSession.config.titrantConcentrationM",
            "runSession.config.titrantValence",
            "runSession.config.equivalenceFormula",
            "runSession.config.calculatedTheoreticalEquivalenceVolumeMl",
            "runSession.config.sampleConcentrationFromTheoreticalEquivalenceM",
            "runSession.config.theoreticalEquivalenceVolumeMl",
            "runSession.config.pumpRunRateMlPerS",
            '"sample_concentration_M" to format(config.sampleConcentrationM)',
            '"sample_volume_ml" to format(config.sampleVolumeMl)',
            '"sample_concentration_from_injected_M" to formatOptional(sampleConcentrationFromInjectedM)',
        ]:
            with self.subTest(token=token):
                self.assertIn(token, main + row)

    def test_android_native_crash_limit_is_user_visible(self):
        crash = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile/AndroidCrashLogStore.kt").read_text(
            encoding="utf-8"
        )

        self.assertIn("java_kotlin_uncaught_exception_only", crash)
        self.assertIn("native_crash_limit", crash)
        self.assertIn("native SIGSEGV/process crashes may require Android system logs/logcat", crash)

    def test_visible_camera_foundation_uses_roi_rgb_hsv_features(self):
        root = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile")
        main = (root / "MainActivity.kt").read_text(encoding="utf-8")
        extractor = (root / "vision/VisibleFeatureExtractor.kt").read_text(encoding="utf-8")
        row = (root / "data/CsvFeatureRow.kt").read_text(encoding="utf-8")

        self.assertIn("lockedVisibleRoi", main)
        self.assertIn("VisibleFeatureExtractor.extract", main)
        self.assertIn("defaultCenterRoi", extractor)
        self.assertIn("rgbToHsv", extractor)
        self.assertIn("yuvToRgb", extractor)
        self.assertIn("hsvDelta", extractor)
        for column in [
            "visible_R_mean",
            "visible_G_mean",
            "visible_B_mean",
            "visible_H_mean",
            "visible_S_mean",
            "visible_V_mean",
            "visible_HSV_delta",
            "visible_color_delta",
        ]:
            self.assertIn(column, row)

    def test_mini2_thermal_gate_requires_validation_before_celsius(self):
        root = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal")
        gate = (root / "Mini2ValidationGate.kt").read_text(encoding="utf-8")
        frame = (root / "ThermalFrameModels.kt").read_text(encoding="utf-8")
        models = (root / "ThermalModels.kt").read_text(encoding="utf-8")

        self.assertIn("FixtureTolerance", gate)
        self.assertIn("maxMeanErrorC", gate)
        self.assertIn("maxPixelErrorC", gate)
        self.assertIn("licenseAllowsRedistribution", gate)
        self.assertIn("mayEmitCelsius", gate)
        self.assertIn("NoFakeCelsiusGuard", gate)
        self.assertIn("requireCelsiusAllowed", frame)
        self.assertIn("celsiusRoi", frame)
        self.assertIn("thermal_roi_avg", frame)
        self.assertIn("thermal_calibrated", frame)
        self.assertIn("validationEvidence", models)
        self.assertIn("isValidatedForCelsius", models)

    def test_chemistry_and_ml_baseline_are_phone_local_and_honest(self):
        root = Path("mobile/android/app/src/main/java/kr/auto/titration/mobile")
        presets = (root / "chemistry/TitrationPreset.kt").read_text(encoding="utf-8")
        equivalence = (root / "chemistry/EquivalenceCalculator.kt").read_text(encoding="utf-8")
        indicators = (root / "chemistry/IndicatorModels.kt").read_text(encoding="utf-8")
        model = (root / "ml/EquivalenceJsonModel.kt").read_text(encoding="utf-8")
        model_contracts = (root / "ml/ModelContracts.kt").read_text(encoding="utf-8")
        trainer = (root / "ml/BaselineTrainer.kt").read_text(encoding="utf-8")
        model_sources = model + model_contracts

        for substance in ["Hydrochloric acid", "Sodium hydroxide", "Acetic acid", "Ammonia"]:
            self.assertIn(substance, presets)
        self.assertIn("equivalenceVolumeMl", equivalence)
        self.assertIn("stoichiometric", equivalence)
        self.assertIn("neutral point", equivalence)
        self.assertIn("Phenolphthalein", indicators)
        self.assertIn("constant_mean_v1", model_sources)
        self.assertIn("linear_regression_v1", model_sources)
        self.assertIn("feature_columns", model)
        self.assertIn("Sparse labeled data", trainer)
        self.assertIn("collect more runs", trainer)


if __name__ == "__main__":
    unittest.main()
