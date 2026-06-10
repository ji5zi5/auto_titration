from pathlib import Path
import unittest


class RetiredProbePathTests(unittest.TestCase):
    def test_old_package_probe_files_are_not_active(self):
        retired = [
            Path("09_" + "py" + "thermal" + "_temperature_probe_wsl.bat"),
            Path("tools") / ("py" + "thermal" + "_temperature_probe.py"),
            Path("tools") / ("run_" + "py" + "thermal" + "_probe_wsl.sh"),
            *[Path("launchers/windows") / name for name in [
                "05_open_website.bat",
                "06_mini2_direct_probe.bat",
                "07_mini2_live_preview.bat",
                "08_mini2_raw_read_preview.bat",
                "10_wsl_usb_attach_helper.bat",
                "11_mini2_v4l2_probe_wsl.bat",
                "12_mini2_uvc_matrix_probe_wsl.bat",
                "13_mini2_detailed_raw_test_wsl.bat",
                "14_mini2_formula_research_wsl.bat",
                "15_mini2_roi_calibration_wsl.bat",
                "16_hik_analyzer_sdk_trace.bat",
                "17_trace_running_hik_export_click.bat",
                "18_trace_spawn_analyzer_then_export.bat",
                "19_mini2_live_temperature_matrix_wsl.bat",
            ]],
        ]

        for path in retired:
            with self.subTest(path=str(path)):
                self.assertFalse(path.exists(), f"retired probe path is still active: {path}")

    def test_mini2_wsl_runners_use_generic_environment_name(self):
        runners = [
            Path("tools/run_v4l2_mini2_probe_wsl.sh"),
            Path("tools/run_mini2_uvc_matrix_probe_wsl.sh"),
            Path("tools/run_mini2_detailed_raw_test_wsl.sh"),
            Path("tools/run_mini2_formula_research_wsl.sh"),
            Path("tools/run_mini2_roi_calibration_wsl.sh"),
        ]
        retired_env = ".venv-" + "py" + "thermal"

        for runner in runners:
            text = runner.read_text(encoding="utf-8")
            with self.subTest(runner=str(runner)):
                self.assertIn(".venv-mini2", text)
                self.assertNotIn(retired_env, text)

    def test_user_docs_do_not_recommend_retired_package_probe(self):
        retired_word = "py" + "thermal"
        for path in [Path("README.md"), Path("docs/README_WINDOWS_CLICK_ME.txt")]:
            text = path.read_text(encoding="utf-8").lower()
            with self.subTest(path=str(path)):
                self.assertNotIn(retired_word, text)
                self.assertIn("mini2", text)

        windows_text = Path("docs/README_WINDOWS_CLICK_ME.txt").read_text(encoding="utf-8")
        self.assertNotIn("launchers/windows/12_mini2_uvc_matrix_probe_wsl.bat", windows_text)
        self.assertIn("21_open_dashboard_server.bat", windows_text)
        self.assertIn("256x192", windows_text)


if __name__ == "__main__":
    unittest.main()
