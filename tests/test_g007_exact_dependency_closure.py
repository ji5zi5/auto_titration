from pathlib import Path
import hashlib
import json
import unittest

ROOT = Path("mobile/android/app/src/main/java")
APK = Path(".omx/goals/autoresearch/hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti/evidence/xapk/com.hikvision.thermalGoogle.apk")
MANIFEST = Path("_workspace/hikmicro-parity-20260715/g007-closure/lib/libgyuv-extraction.json")


class G007ExactDependencyClosureTests(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_extraction_target_set_contains_post_callback_dependencies(self):
        script = Path("tools/analysis/extract_g007_dex_bodies.py").read_text(encoding="utf-8")
        for token in ["Li3/", "Lk3/", "Ll2/", "LK2/", "LO2/", "Lz2/", "Lz3/", "Lcom/hik/f2module/IFR_INFO", "Lcom/hik/f1module/hcusbcamerasdk/jna/HCUSBCameraSDKBy", "Lf3/j;", "Lcom/louisgeek/gyuv/GYUV;"]:
            self.assertIn(token, script)

    def test_libgyuv_is_exact_official_arm64_entry(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        lib = Path("mobile/android/app/src/main/jniLibs/arm64-v8a/libgyuv.so")
        self.assertTrue(lib.is_file())
        self.assertEqual("lib/arm64-v8a/libgyuv.so", manifest["entry"])
        self.assertEqual(manifest["sha256"], hashlib.sha256(lib.read_bytes()).hexdigest())
        self.assertEqual("b1a5876fd7091927423aa5002eb56ca4d6b00c3571f5939a0768a247b865402f", manifest["sha256"])
        self.assertTrue(lib.read_bytes().startswith(b"\x7fELF\x02\x01\x01"))

    def test_exact_wrapper_types_replace_nullable_h3_standins(self):
        h3 = self.read("h3/StreamInfo.kt")
        self.assertIn("HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO", h3)
        self.assertIn("IFR_INFO.IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO", h3)
        self.assertNotIn("HikmicroF2TemperatureMetadata?", h3)
        self.assertNotIn("null)", h3)

    def test_g3_materializes_official_structs_and_uses_k3_gyuv_path(self):
        g3d = self.read("g3/d.java")
        g3e = self.read("g3/e.java")
        g3c = self.read("g3/c.java")
        g3f = self.read("g3/f.java")
        for text in (g3d, g3e, g3c, g3f):
            self.assertIn("k3.b.d(k3.b.a", text)
        self.assertIn("IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE", g3d)
        self.assertIn("HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO", g3d)
        self.assertIn("IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE", g3e)
        self.assertIn("HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO", g3e)
        self.assertIn("k3.a.a.c(yuv", g3d)
        self.assertIn("k3.a.a.i(yuy2", g3c)
        self.assertIn("k3.a.a.i(yuy2", g3f)
        combined = g3d + g3e + g3c + g3f
        self.assertNotIn("native/image closure is not available", combined)
        self.assertNotIn("OfficialPacketProcessor", combined)

    def test_f3j_and_gyuv_descriptors_are_recovered(self):
        f3j = self.read("f3/j.kt")
        self.assertIn("203720", f3j)
        self.assertIn("183496", f3j)
        gyuv = self.read("com/louisgeek/gyuv/GYUV.kt")
        for name in ["gyuv420pTo422p", "gyuv422pToNV16", "gyuvI420Mirror", "gyuvI420Rotate", "gyuvI420Scale", "gyuvI420ToNV12", "gyuvI420ToNV21", "gyuvNV12ToI420", "gyuvNV16ToNV12", "gyuvNV21ToI420", "gyuvYUY2ToI420"]:
            self.assertIn(f"external fun {name}", gyuv)
        self.assertIn('System.loadLibrary("gyuv")', gyuv)


if __name__ == "__main__":
    unittest.main()
