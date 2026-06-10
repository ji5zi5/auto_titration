from pathlib import Path
import unittest


class NoAutoStopCouplingTests(unittest.TestCase):
    def test_pump_controller_does_not_import_camera_or_ml_prediction(self):
        source = Path("auto_titrator/pump_controller.py").read_text(encoding="utf-8")

        for forbidden in [
            "from .camera",
            "thermal_camera",
            "ml_predict",
            "endpoint_detector",
            "predict_equivalence_volume",
            "ColorFeatureExtractor",
            "ThermalPaletteAnalyzer",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_collection_entrypoint_does_not_use_ml_to_stop_pump(self):
        source = Path("auto_titrator/main.py").read_text(encoding="utf-8")

        for forbidden in [
            "from .pump_controller",
            "PumpController",
            ".run_rate(",
            ".stop(",
            "load_optional_model",
            "load_model(",
            "predict_equivalence_volume",
            "predicted_equivalence_volume_ml",
            "endpoint_detector",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_ml_prediction_layer_does_not_import_pump_controller(self):
        source = Path("auto_titrator/ml_predict.py").read_text(encoding="utf-8")

        self.assertNotIn("pump_controller", source)
        self.assertNotIn("PumpController", source)

    def test_analysis_and_history_layers_do_not_import_pump_controller(self):
        for path in [
            Path("auto_titrator/feature_history.py"),
            Path("auto_titrator/equivalence_analysis.py"),
            Path("auto_titrator/thermal_providers.py"),
            Path("auto_titrator/live_app.py"),
        ]:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=str(path)):
                self.assertNotIn("pump_controller", source)
                self.assertNotIn("PumpController", source)
                self.assertNotIn("RUN_RATE", source)
                self.assertNotIn("EMERGENCY_STOP", source)



if __name__ == "__main__":
    unittest.main()
