from pathlib import Path
import unittest


README = Path("README.md")


class ReadmeDocumentationTests(unittest.TestCase):
    def test_readme_documents_stepper_wiring_and_calibration(self):
        text = README.read_text(encoding="utf-8")

        for expected in [
            "STEP_PIN",
            "DIR_PIN",
            "ENABLE_PIN",
            "Serial Monitor key",
            "`a`",
            "`b`",
            "`c`",
            "9600 baud",
            "delayMicroseconds(5000)",
            "does not stop the motor automatically",
            "configured pump timeline",
            "flow_rate_ml_per_s",
            "물 보정",
            "10 mL / 10.05 s",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)
        for removed in [
            "STATUS steps=",
            "ML_PER_STEP",
            "startLeft()",
            "startRight()",
            "STEP_INTERVAL_US",
        ]:
            with self.subTest(removed=removed):
                self.assertNotIn(removed, text)

    def test_readme_documents_science_fair_workflow_and_limitations(self):
        text = README.read_text(encoding="utf-8")

        for expected in [
            "strong_acid_strong_base",
            "weak_acid_strong_base",
            "strong_acid_weak_base",
            "weak_acid_weak_base",
            "equivalence point",
            "endpoint",
            "--dry-run-smoke",
            "ml_train",
            "ml_predict",
            "evaluation",
            "palette-color",
            "does not stop the motor automatically",
            "--thermal-backend msmf",
            "DSHOW=blank",
            "analyze-simulated",
            "status-only",
            "estimated equivalence",
            "full 25fps thermal matrix CSV",
            "raw→℃ converter",
            "21_open_dashboard_server.bat",
            "neutral point",
            "pH 7",
            "YOLO",
            "requirements-yolo.txt",
            "--visible-roi-detector yolo",
            "http://<laptop-ip>:8765",
            "same Wi-Fi",
            "LAN mode",
            "Windows Defender Firewall",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_readme_documents_sensor_synchronization(self):
        text = README.read_text(encoding="utf-8")

        for expected in [
            "센서 동기화",
            "공통 PC clock",
            "하드웨어 동기화",
            "sync_offset_ms",
            "sync_quality",
            "sync_warning",
            "20 ms",
            "1 mL/s",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_readme_documents_mobile_companion_scope(self):
        text = README.read_text(encoding="utf-8")

        for expected in [
            "Android companion",
            "mobile_feature_frame.v1",
            "/api/mobile/ingest",
            "CameraX ImageAnalysis",
            "Android USB host",
            "thermal_calibrated=false",
            "raw_unverified",
            "blocked",
            "Android 연결",
            "laptop remains the CSV/ML owner",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
