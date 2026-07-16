from pathlib import Path
import unittest


MAIN_ROOT = Path("mobile/android/app/src/main/java")


def kotlin_sources():
    return sorted(path for path in MAIN_ROOT.rglob("*.kt") if "build" not in path.parts and "generated" not in path.parts)


class G007F2ArchitectureContractTests(unittest.TestCase):
    def test_production_no_longer_contains_surrogate_official_claims_or_custom_parser_dependency(self):
        offenders = []
        banned_tokens = {
            "Minimal official-shaped": "surrogate implementation must not describe itself as official-shaped",
            "official_wrapper_parity_ok": "runtime status must not self-assert wrapper parity",
            "HikmicroF2PacketParser": "production F2 path must not depend on repo-owned custom packet parser",
        }
        for path in kotlin_sources():
            text = path.read_text(encoding="utf-8")
            for token, reason in banned_tokens.items():
                if token in text:
                    offenders.append(f"{path}:{token}: {reason}")

        self.assertEqual([], offenders)

    def test_official_f2_production_path_is_centered_on_viewer_api_and_callback_packages(self):
        api = MAIN_ROOT / "com/hik/f2module/F2UsbModuleApi.kt"
        helper = MAIN_ROOT / "com/hik/f2module/F2UsbModuleHelper.kt"
        preview = MAIN_ROOT / "com/hik/viewer/manager/PreviewManagerII.java"
        callback = MAIN_ROOT / "com/hik/viewercommon/data/device/api/callback/F2ModuleStreamCallback.kt"
        for path in (api, helper, preview, callback):
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"missing official-package production file {path}")

        combined = "\n".join(path.read_text(encoding="utf-8") for path in (api, helper, preview, callback))
        self.assertIn("F2ModuleStreamCallback", combined)
        self.assertIn("USB_StartStreamCallback", combined)
        self.assertIn("dwBufSize", combined)
        self.assertIn("officialF2KnownPacketSizes", combined)
        self.assertNotIn("HikmicroF2PacketParser.parse", combined)


class G007F2CallbackSchedulerClosureTests(unittest.TestCase):
    def test_official_packet_gate_removes_unproven_98304_and_221184_sizes(self):
        preview = (MAIN_ROOT / "com/hik/viewer/manager/PreviewManagerII.java").read_text(encoding="utf-8")
        official_set = preview.split("officialF2KnownPacketSizes: Set<Int> = setOf(", 1)[1].split(")", 1)[0]
        self.assertNotIn("98_304", official_set)
        self.assertNotIn("221_184", official_set)
        for size in ["41_160", "61_384", "101_320", "183_496", "193_480", "203_720", "400_584"]:
            self.assertIn(size, official_set)

    def test_preview_scheduler_and_processor_callback_installation_match_g007_dex_shape(self):
        preview = (MAIN_ROOT / "com/hik/viewer/manager/PreviewManagerII.java").read_text(encoding="utf-8")
        self.assertIn("private const val F2_CONSUMER_PERIOD_MS = 20L", preview)
        self.assertIn("scheduleAtFixedRate(", preview)
        self.assertIn("F2_CONSUMER_PERIOD_MS", preview)
        self.assertIn("Executors.newSingleThreadScheduledExecutor()", preview)
        callback_install = preview[preview.index("processor.j("):preview.index("        if (processor is G3DProcessor)")]
        expected_callback_order = [
            "OfficialFreezeCallback(",
            "K2.f(",
            "OfficialMetadataCallback(",
            "OfficialOverlayCallback(",
            "K2.g(",
        ]
        positions = [callback_install.index(token) for token in expected_callback_order]
        self.assertEqual(sorted(positions), positions)
        self.assertIn("processor.o(K2.h(", preview)
        self.assertIn("Arrays.hashCode", preview)
        self.assertIn("noChangeCounter % 100", preview)

    def test_fstream_callback_matches_official_timer_copy_count_and_size_publish_order(self):
        preview = (MAIN_ROOT / "com/hik/viewer/manager/PreviewManagerII.java").read_text(encoding="utf-8")
        callback = preview[preview.index("override fun fStreamCallback"):preview.index("private fun onUnsupportedPacketSizeLocked")]

        expected_order = [
            "frameCounter += 1L",
            "if (invalidPacketStartMs == 0L)",
            "val copiedSize = frameInfo.dwBufSize",
            "val copied = Arrays.copyOf(frameInfo.pBuf, copiedSize)",
            "Z2.g.a.A0(copiedSize)",
            "if (copiedSize !in allowedPacketSizes)",
        ]
        positions = [callback.index(token) for token in expected_order]
        self.assertEqual(sorted(positions), positions)
        self.assertNotIn("coerceAtLeast", callback)
        self.assertNotIn("coerceAtMost", callback)
        self.assertNotIn("invalidPacketStartMs = 0L", callback)

        unsupported = preview[preview.index("private fun onUnsupportedPacketSizeLocked"):preview.index("private data class BufferedF2Packet")]
        self.assertIn("elapsedMs > invalidPacketErrorDelayMs", unsupported)
        self.assertLess(unsupported.index("onInvalidPacketSizeTimeout?.invoke(packetSize, elapsedMs)"), unsupported.index("invalidPacketStartMs = 0L"))

    def test_g3a_callback_slots_are_not_noop_and_are_cleared_by_k(self):
        g3a = (MAIN_ROOT / "g3/a.java").read_text(encoding="utf-8")
        g3d = (MAIN_ROOT / "g3/d.java").read_text(encoding="utf-8")
        for token in [
            "private Function1 a",
            "private Function1 b",
            "private Function1 c",
            "private Function5 d",
            "private Function1 e",
            "public final void j(Function1 callback1",
            "this.a = callback1",
            "this.b = callback2",
            "this.c = callback3",
            "this.d = callback4",
            "this.e = callback5",
            "public final void k()",
            "this.a = null",
        ]:
            self.assertIn(token, g3a)
        for token in [
            "a(isFreezeData, e(), f())",
            "b(result.getIStreamInfo(), resultPreviewInfo, i(), h())",
            "c(result.getIStreamInfo(), resultPreviewInfo.getByteArrRawAppendData(), g())",
        ]:
            self.assertIn(token, g3d)


if __name__ == "__main__":
    unittest.main()
