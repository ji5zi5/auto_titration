from pathlib import Path
import re
import unittest

ROOT = Path("mobile/android/app/src/main/java")
EXTRACTED = Path("_workspace/hikmicro-parity-20260715/g007-codec-gyuv/extracted")


class G007CodecGyuvContractTests(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_extraction_now_includes_exact_u4_closure(self):
        script = Path("tools/analysis/extract_g007_dex_bodies.py").read_text(encoding="utf-8")
        self.assertIn('"LU4/"', script)
        for name in ["U4_c.java", "U4_m.java", "U4_n.java", "U4_a.java", "U4_f.java", "U4_i.java"]:
            self.assertTrue((EXTRACTED / name).is_file(), name)

    def test_k3b_delegates_to_u4c_and_no_empty_custom_serializer(self):
        text = self.read("k3/b.kt")
        self.assertIn("U4.c.a(beanObject, byteOrder)", text)
        self.assertIn("U4.c.b(beanObject, buffer, byteOrder)", text)
        self.assertNotIn("ByteArray(0)", text)
        self.assertNotIn("readObject", text)
        self.assertNotIn("OfficialFieldOrder", text)

    def test_u4_codec_uses_runtime_struct_order_annotations_nested_arrays_and_byte_order(self):
        text = self.read("U4/c.kt")
        annotations = self.read("U4/Annotations.kt")
        self.assertIn("AnnotationRetention.RUNTIME", annotations)
        self.assertIn("annotation class f", annotations)
        self.assertIn("annotation class i", annotations)
        self.assertIn("annotation class a", annotations)
        for token in ["getAnnotation(f::class.java)", "getAnnotation(i::class.java)", "getAnnotation(a::class.java)", "Order error for annotated fields", "ByteOrder.LITTLE_ENDIAN", "k0(value)", "i0(child)"]:
            self.assertIn(token, text)
        self.assertRegex(text, r"fun a\(beanObject: Any, byteOrder: ByteOrder\): ByteArray = m\(byteOrder\)\.p0\(beanObject\)")
        self.assertRegex(text, r"fun b\(beanObject: Any, buffer: ByteArray, byteOrder: ByteOrder\) \{ n\(buffer, byteOrder\)\.m0\(beanObject\) \}")

    def test_k3a_matches_dex_observable_sizes_mirror_and_rotate_dimensions(self):
        text = self.read("k3/a.kt")
        self.assertNotIn("nativeOrCopy", text)
        self.assertNotIn("copyOf", text)
        self.assertIn("ByteArray(yuvSize.width * yuvSize.height * 2)", text)
        self.assertIn("gyuvI420Mirror(i420, yuvSize.width, -yuvSize.height, mirrored)", text)
        self.assertIn("Size(yuvRotateSize.height, yuvRotateSize.width)", text)
        self.assertIn("gyuvI420Rotate(i420, rotateSize.width, rotateSize.height, rotated, rot)", text)
        self.assertIn("Size(yuvScaledSize.height, yuvScaledSize.width)", text)
        self.assertIn("gyuvI420Rotate(scaled, yuvScaledSize.width, yuvScaledSize.height, rotated, rot)", text)

    def test_gyuv_unconditional_class_load_contract_and_exact_signatures(self):
        text = self.read("com/louisgeek/gyuv/GYUV.kt")
        self.assertIn('init { System.loadLibrary("gyuv") }', text)
        self.assertNotIn("runCatching", text)
        self.assertNotIn("nativeLoadError", text)
        official = (EXTRACTED / "com_louisgeek_gyuv_GYUV.dex.txt").read_text(encoding="utf-8")
        for name, desc in re.findall(r"native (gyuv\w+)\(([^)]*)\)", official):
            self.assertIn(f"external fun {name}", text)


if __name__ == "__main__":
    unittest.main()
