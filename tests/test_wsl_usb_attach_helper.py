from pathlib import Path
import unittest


class WslUsbAttachHelperTests(unittest.TestCase):
    def test_windows_usb_attach_launcher_is_retired(self):
        self.assertFalse(Path("launchers/windows/10_wsl_usb_attach_helper.bat").exists())

    def test_powershell_helper_installs_usbipd_and_attaches_busid(self):
        text = Path("tools/wsl_usb_attach_mini2.ps1").read_text(encoding="utf-8")

        for expected in [
            "dorssel.usbipd-win",
            "usbipd list",
            "usbipd bind --busid",
            "usbipd attach --wsl --busid",
            "2bdf:",
            "Auto-detected",
            "Already shared",
            "Mini2",
            "/dev/bus/usb",
            "WSL V4L2 probe shell script",
            "OutputEncoding",
            "Start-Transcript",
            "usb_attach_last.log",
            "Press Enter to close",
            "try {",
            "catch {",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_readme_no_longer_points_users_to_wsl_launcher_sequence(self):
        text = Path("README.md").read_text(encoding="utf-8")

        self.assertNotIn("launchers/windows/10_wsl_usb_attach_helper.bat", text)
        self.assertIn("Windows-native", text)


if __name__ == "__main__":
    unittest.main()
