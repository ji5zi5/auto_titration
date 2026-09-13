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
        self.assertIn("dwBufSize", (MAIN_ROOT / "com/hik/viewer/manager/PreviewManagerII$d.java").read_text(encoding="utf-8"))
        self.assertNotIn("HikmicroF2PacketParser.parse", combined)


class G007F2CallbackSchedulerClosureTests(unittest.TestCase):
    def test_official_packet_gate_removes_unproven_98304_and_221184_sizes(self):
        callback = (MAIN_ROOT / "com/hik/viewer/manager/PreviewManagerII$d.java").read_text(encoding="utf-8")
        self.assertNotIn("98304", callback)
        self.assertNotIn("221184", callback)
        self.assertIn("callbackEntry.acceptsPacketSize(size)", callback)
        self.assertIn("callbackEntry.isCoding12()", callback)
        self.assertNotIn("Z2.a.a.p()", callback)
        for size in ["41160", "183496", "400584"]:
            self.assertIn(size, callback)

    def test_preview_scheduler_and_processor_callback_installation_match_g007_dex_shape(self):
        preview = (MAIN_ROOT / "com/hik/viewer/manager/PreviewManagerII.java").read_text(encoding="utf-8")
        self.assertIn("Executors.newSingleThreadScheduledExecutor()", preview)
        self.assertIn("final long schedulerEpoch = processingEpoch", preview)
        self.assertIn("scheduleWithFixedDelay(", preview)
        self.assertIn("if (isProcessingEpochCurrent(schedulerEpoch)) new K2.e(this).run()", preview)
        self.assertIn("0L,\n                20L,\n                TimeUnit.MILLISECONDS", preview)
        callback_install = preview[preview.index("processor.j("):preview.index("        if (processor instanceof g3.d)")]
        expected_callback_order = ["X", "new K2.f(this)", "c0", "h0", "new K2.g(this)"]
        positions = [callback_install.index(token) for token in expected_callback_order]
        self.assertEqual(sorted(positions), positions)
        self.assertIn(
            "((g3.d) processor).o(new K2.h(this, frame.processingEpoch))",
            preview,
        )
        self.assertIn(
            "if (!isProcessingEpochCurrentLocked(frame.processingEpoch)) return",
            preview,
        )
        self.assertIn("Arrays.hashCode", preview)
        self.assertIn("u0 % 100", preview)

    def test_fstream_callback_matches_official_timer_copy_count_and_size_publish_order(self):
        callback = (MAIN_ROOT / "com/hik/viewer/manager/PreviewManagerII$d.java").read_text(encoding="utf-8")
        expected_order = [
            "int size = frameInfo.dwBufSize",
            "if (frameInfo.pBuf == null || size < 0 || size > frameInfo.pBuf.length)",
            "PreviewManagerII.beginCallback(b, c, this, userId, frameInfo)",
            "if (callbackEntry == null) return",
            "byte[] copied = Arrays.copyOf(frameInfo.pBuf, size)",
            "Z2.g.a.A0(size)",
            "PreviewManagerII.frameEnvelope(",
            "callbackEntry.frameNumber",
            "callbackEntry.processingEpoch",
            "if (callbackEntry.acceptsPacketSize(size))",
            "b.recordPacketSizeNotAllowed(",
        ]
        positions = [callback.index(token) for token in expected_order]
        self.assertEqual(sorted(positions), positions)
        self.assertIn("PreviewManagerII.v(b, envelope)", callback)
        self.assertIn("PreviewManagerII.u(b, envelope)", callback)
        self.assertNotIn("coerce", callback)
        invalid_packet_order = [
            "b.recordPacketSizeNotAllowed(",
            "b.consumeInvalidPacketCallbacks(",
            "callbackEntry.processingEpoch,\n                            this",
            "if (callbacks == null) return",
            "if (callbacks.diagnosticCallback != null",
            "callbacks.callbackIdentity))",
            "callbacks.diagnosticCallback.accept(size, callbacks.elapsedMs)",
            "if (callbacks.legacyCallback != null",
            "callbacks.callbackIdentity))",
            "callbacks.legacyCallback.invoke()",
        ]
        positions = []
        cursor = 0
        for token in invalid_packet_order:
            cursor = callback.index(token, cursor)
            positions.append(cursor)
            cursor += len(token)
        self.assertEqual(sorted(positions), positions)
        self.assertNotIn("invalidPacketCallbacksForEpoch", callback)
        self.assertNotIn("resetInvalidPacketTimeoutForEpoch", callback)
        self.assertIn("catch (RuntimeException | LinkageError error)", callback)

        preview = (MAIN_ROOT / "com/hik/viewer/manager/PreviewManagerII.java").read_text(encoding="utf-8")
        consume = preview[
            preview.index("    InvalidPacketCallbacks consumeInvalidPacketCallbacks("):
            preview.index("    boolean isCallbackCurrent(", preview.index("    InvalidPacketCallbacks consumeInvalidPacketCallbacks("))
        ]
        consume_order = [
            "synchronized (lifecycleLock)",
            "!isProcessingEpochCurrentLocked(expectedEpoch)",
            "callbackIdentity != C0",
            "if ((now - startMs) <= 40000L || M() != 0) return null",
            "firstCallbackAtMs = 0L",
            "return new InvalidPacketCallbacks(",
            "callbackIdentity",
            "invalidPacketSizeTimeoutCallback",
            "a0",
        ]
        positions = []
        cursor = 0
        for token in consume_order:
            cursor = consume.index(token, cursor)
            positions.append(cursor)
            cursor += len(token)
        self.assertEqual(sorted(positions), positions)

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
