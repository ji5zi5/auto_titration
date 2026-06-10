from pathlib import Path
import unittest


class Mini2DirectProbeTests(unittest.TestCase):
    def test_probe_script_documents_vid_pid_and_opencv_capture(self):
        text = Path("tools/mini2_direct_probe.py").read_text(encoding="utf-8")

        for expected in [
            "VID_PID_RE",
            "Win32_PnPEntity",
            "cv2.VideoCapture",
            "opencv_capture_probe.csv",
            "vendor-specific",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_opencv_live_preview_uses_index_backend_and_roi_csv(self):
        text = Path("tools/opencv_live_preview.py").read_text(encoding="utf-8")

        for expected in [
            "cv2.VideoCapture",
            "--backend",
            "--display",
            "--intensity-channel",
            "--raw-read",
            "CAP_PROP_CONVERT_RGB",
            "cv2.imshow",
            "cv2.applyColorMap",
            "COLORMAP_INFERNO",
            "raw_ch0_mean",
            "raw_shape",
            "color_delta",
            "intensity_delta",
            'f"{args.source}_intensity_mean"',
            'f"{args.source}_R_mean"',
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_old_direct_probe_bat_launchers_are_retired(self):
        for retired in [
            "06_mini2_direct_probe.bat",
            "07_mini2_live_preview.bat",
            "08_mini2_raw_read_preview.bat",
        ]:
            with self.subTest(retired=retired):
                self.assertFalse(Path("launchers/windows", retired).exists())


if __name__ == "__main__":
    unittest.main()
