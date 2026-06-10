import unittest

from auto_titrator.camera import CameraConfig, UsbCamera


class CameraConfigTests(unittest.TestCase):
    def test_backend_is_optional_for_auto_capture(self):
        config = CameraConfig(device_index=1, backend=None)

        self.assertEqual(config.device_index, 1)
        self.assertIsNone(config.backend)

    def test_backend_value_maps_windows_backends(self):
        class FakeCv2:
            CAP_MSMF = 1400
            CAP_DSHOW = 700

        self.assertEqual(UsbCamera._backend_value(FakeCv2, "msmf"), 1400)
        self.assertEqual(UsbCamera._backend_value(FakeCv2, "dshow"), 700)
        self.assertIsNone(UsbCamera._backend_value(FakeCv2, "any"))

    def test_backend_value_rejects_unknown_backend(self):
        class FakeCv2:
            CAP_MSMF = 1400
            CAP_DSHOW = 700

        with self.assertRaises(ValueError):
            UsbCamera._backend_value(FakeCv2, "unknown")


if __name__ == "__main__":
    unittest.main()
