from pathlib import Path
import unittest


class V4l2Mini2ProbeTests(unittest.TestCase):
    def test_probe_script_records_v4l2_formats_and_frame_stats(self):
        text = Path("tools/v4l2_mini2_probe.py").read_text(encoding="utf-8")

        for expected in [
            "ffmpeg",
            "-list_formats",
            "cv2.VideoCapture",
            "v4l2_probe.csv",
            "probably_temperature_raw",
            "frame_mean",
            "frame_std",
            "read_error",
            "cv2.error",
            "raw_capture_error",
            "raw_capture_bytes",
            "exists_before",
            "exists_after",
            "-f",
            "rawvideo",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_wsl_runner_handles_video_permissions(self):
        text = Path("tools/run_v4l2_mini2_probe_wsl.sh").read_text(encoding="utf-8")

        for expected in [
            "/dev/video",
            "chmod a+rw",
            "uvcvideo",
            "bind",
            "modprobe uvcvideo",
            "HIK USB",
            "No /dev/video nodes",
            "python -m pip install",
            "tools/v4l2_mini2_probe.py",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_windows_v4l2_probe_launcher_is_retired(self):
        self.assertFalse(Path("launchers/windows/11_mini2_v4l2_probe_wsl.bat").exists())

    def test_auto_attach_script_targets_hik_vendor_without_admin_prompt(self):
        text = Path("tools/wsl_usb_auto_attach_mini2.ps1").read_text(encoding="utf-8")

        for expected in [
            "usbipd list",
            "2bdf:",
            "usbipd attach --wsl --busid",
            "Not shared",
            "Already attached",
            "wsl_usb_auto_attach_last.log",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
