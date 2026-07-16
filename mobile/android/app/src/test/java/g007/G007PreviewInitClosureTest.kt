package g007

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class G007PreviewInitClosureTest {
    private val root: File = generateSequence(File(requireNotNull(System.getProperty("user.dir")))) { it.parentFile }
        .flatMap { sequenceOf(it, File(it, "mobile/android")) }
        .first { File(it, "app/src/main/java/com/hik/viewer/manager/PreviewManagerII.java").exists() }

    private val preview: String = source("com/hik/viewer/manager/PreviewManagerII.java")

    @Test
    fun l0UsesTheOfficialPredicatesAndCompleteF2InitializationChain() {
        val l0 = body(preview, "    public final void l0(View viewerRootView", "    private V2.f bindOfficialRenderer")
        assertTrue(l0.contains("if (s0())"))
        assertTrue(l0.contains("} else if (r0())"))
        assertFalse(l0.contains("Z2.g.a.a(true)"))
        assertOrdered(l0, "if (O != null && (t0() || q0()))", "n0(n)", "p0()", "b1()")
        assertTrue(l0.contains("D = g3.b.a.a(Z2.a.a.p().k(), t0());"))
        assertTrue(l0.contains("S = u5.B.a.L() == 1;"))
        assertTrue(l0.contains("g1(this, false, 1, null);"))
    }

    @Test
    fun l0UsesDirectSupportApisAndRegistersLifecycleAfterPlaybackListener() {
        val l0 = body(preview, "    public final void l0(View viewerRootView", "    private V2.f bindOfficialRenderer")
        assertTrue(l0.contains("F1UsbModuleHelper.INSTANCE.USB_SetYuvSize(t);"))
        assertOrdered(l0, "E.b(new PreviewManagerII\$f(this))", "a.addObserver(B)")
        val playbackListener = source("com/hik/viewer/manager/PreviewManagerII\$f.java")
        assertTrue(playbackListener.contains("implements com.hik.library.player.b"))
        assertTrue(playbackListener.contains("@Override public void a(){}"))
        assertTrue(playbackListener.contains("@Override public void b(){}"))
        assertTrue(playbackListener.contains("@Override public void onError(String message){}"))
        assertTrue(playbackListener.contains("@Override public void onPause(){}"))
        assertTrue(playbackListener.contains("@Override public void onResume(){}"))
        assertTrue(playbackListener.contains("@Override public void onStart(){ if(u5.B.a.d0()) a.G0(null);}"))
        assertTrue(playbackListener.contains("@Override public void onStop(){}"))
        val reachable = preview.substringBefore("    private void recordOfficialPacket")
        listOf("Class.forName", "getDeclaredMethod", ".getMethod(").forEach {
            assertFalse("l0-reachable source contains $it", reachable.contains(it))
        }
        assertTrue(preview.contains("u5.B.a.h0()"))
        assertTrue(playbackListener.contains("u5.B.a.d0()"))
        assertTrue(preview.contains("businesscommon.b.x("))
    }

    @Test
    fun rendererFactoryBranchUsesOnlyTheDexPredicates() {
        val renderer = body(preview, "    private V2.f bindOfficialRenderer", "    private String X()")
        assertTrue(renderer.contains("if (!s0()) selected = factory.a(viewerSurfaceView);"))
        assertTrue(renderer.contains("else if (Z2.a.a.t()) selected = factory.c(viewerSurfaceView);"))
        assertTrue(renderer.contains("else selected = factory.b(viewerSurfaceView);"))
        listOf("isF2Module", "useNonF1Processing", "surrogate").forEach {
            assertFalse(renderer.contains(it))
        }
    }

    @Test
    fun u0KeepsTheOfficialReleaseAndStateClearingOrder() {
        val u0 = body(preview, "    public final void u0()", "    void G(byte[] packet)")
        assertOrdered(
            u0,
            "if (E != null) E.c();",
            "if (E != null) E.release();",
            "E = null;",
            "B0 = null",
            "C0 = null",
            "X = null",
            "Y = null",
            "Z = null",
            "a0 = null",
            "b0 = null",
            "c0 = null",
            "d0 = null",
            "e0 = null",
            "f0 = null",
            "h0 = null",
            "if (D != null) D.k();",
            "D = null;",
            "if (C != null) C.shutdownNow();",
            "C = null;",
            "e1();",
            "q0 = true;",
            "m0 = true;",
            "G = null",
            "H = null",
            "I = null",
            "J = null",
            "K.removeCallbacksAndMessages(null);",
        )
    }

    @Test
    fun floatTextureAndRawRendererHandoffsExcludePriorSubstitutes() {
        val floatView = source("hik/common/yyrj/uicommon/widget/FloatTextureView.kt")
        listOf("officialFloatTexturePosition", "moveBy", "moveTo", "updateParentBounds", "currentGravity(): Int").forEach {
            assertFalse(floatView.contains(it))
        }
        assertEquals(1, Regex("rendererOrNullJ\\(renderer, transformedNv12,").findAll(preview).count())
        assertEquals(1, Regex("renderer\\.h\\(null, transformedNv12,").findAll(preview).count())
    }

    @Test
    fun directSupportClassesExposeTheRecoveredNarrowBehavior() {
        val state = source("u5/B.java")
        assertTrue(state.contains("public final int L(){return l2.k.e(\"PERFORMANCE_F22X\",-1);}"))
        assertTrue(state.contains("public final boolean d0(){return O;}"))
        assertTrue(state.contains("public final boolean h0(){return Intrinsics.areEqual(m, \"ThgStart\");}"))
        val preferences = source("hik/common/yyrj/businesscommon/b.java")
        assertTrue(preferences.contains("preview_logo_visible"))
        assertTrue(preferences.contains("return true;"))
        val f1 = source("com/hik/f1module/F1UsbModuleHelper.kt")
        assertOrdered(f1, "type = 0x14", "len = 8", "thermal_function_set_msg(config.pointer)")
    }

    private fun source(relative: String): String = File(root, "app/src/main/java/$relative").readText()

    private fun body(text: String, start: String, end: String): String =
        text.substringAfter(start).substringBefore(end)

    private fun assertOrdered(text: String, vararg tokens: String) {
        var cursor = -1
        tokens.forEach { token ->
            val next = text.indexOf(token, cursor + 1)
            assertTrue("missing or out-of-order token: $token", next > cursor)
            cursor = next
        }
    }
}
