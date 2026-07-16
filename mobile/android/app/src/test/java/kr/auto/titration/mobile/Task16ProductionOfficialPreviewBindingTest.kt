package kr.auto.titration.mobile

import android.view.SurfaceView
import android.view.View
import android.widget.TextView
import com.hik.viewer.manager.PreviewManagerII
import com.hik.viewercommon.data.bean.SceneModeBean
import hik.common.yyrj.uicommon.widget.FloatTextureView
import java.nio.file.Files
import java.nio.file.Path
import kotlin.jvm.functions.Function1
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Task16ProductionOfficialPreviewBindingTest {
    @Test
    fun mainActivityInstallsNativeOfficialPreviewRootAndKeepsWebViewAttached() {
        val source = source("app/src/main/java/kr/auto/titration/mobile/MainActivity.kt")

        assertTrue(source.contains("officialPreviewHost = OfficialPreviewHost(this)"))
        assertTrue(source.contains("officialPreviewHost.attachUserInterface(webView)"))
        assertTrue(source.contains("setContentView(officialPreviewHost.rootView)"))
        assertFalse("task16 must replace the WebView-only content root", source.contains("setContentView(webView)"))
        assertTrue("activity teardown must route through the native preview host", source.contains("officialPreviewHost.destroy()"))
    }

    @Test
    fun nativeHostSelectsTheOfficialSurfaceAndWaitsForARealValidHolder() {
        val source = source("app/src/main/java/kr/auto/titration/mobile/OfficialPreviewHost.kt")

        assertTrue(source.contains("SurfaceHolder.Callback"))
        assertTrue(source.contains("Z2.a.a.t()"))
        assertTrue(source.contains("z3.c.a.u(hrlSurfaceView)"))
        assertTrue(source.contains("selectedSurfaceView = hrlSurfaceView"))
        assertTrue(source.contains("selectedSurfaceView = viewerSurfaceView"))
        assertTrue(source.contains("holder.surface"))
        assertTrue(source.contains("surface.isValid"))
        assertTrue(source.contains("width <= 1 || height <= 1"))
        assertTrue(source.contains("selectedSurfaceView.visibility != View.VISIBLE"))
        assertTrue(source.contains("FrameLayout.LayoutParams.MATCH_PARENT"))
        assertFalse("the selected official surface must not be hidden with GONE", source.contains("View.GONE"))
    }

    @Test
    fun nativeHostIsIdempotentUntilSurfaceDestroyAndTeardownRunsOnce() {
        val source = source("app/src/main/java/kr/auto/titration/mobile/OfficialPreviewHost.kt")

        assertTrue("valid repeated layout/surfaceChanged callbacks must not rebind", source.contains("destroyed || bound || !holderCreated"))
        assertTrue(source.contains("override fun surfaceDestroyed"))
        assertTrue(source.contains("if (bound)"))
        assertEquals("host should have exactly one unbind call site for destroy and one for surfaceDestroyed", 2, Regex("unbindPreview\\(\\)").findAll(source).count())
        assertTrue(source.contains("selectedHolder?.removeCallback(this)"))
    }

    @Test
    fun sceneModeComesFromRecoveredOfficialHolderSemanticsNotBlankGuess() {
        val source = source("app/src/main/java/kr/auto/titration/mobile/OfficialPreviewHost.kt")

        assertTrue(source.contains("officialSceneModeHolderValue()"))
        assertTrue(source.contains("Z2.g.a.z().isEmpty()"))
        assertTrue(source.contains("Z2.g.a.X()"))
        assertTrue(source.contains("Z2.g.a.C()"))
        assertFalse("production binding must not pass a fresh blank SceneModeBean directly", source.contains("sceneMode = SceneModeBean(),"))
    }

    @Test
    fun streamUsesOfficialDefaultBridgeBoundaryAndTeardownBeforeRealRebind() {
        val source = source("app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt")
        val bindStart = source.indexOf("fun bindOfficialPreviewSurface(binding: OfficialPreviewBinding)")
        val u0 = source.indexOf("manager.u0()", bindStart)
        val m0 = source.indexOf("PreviewManagerII.m0", bindStart)

        assertTrue(bindStart >= 0)
        assertTrue("u0 must precede the next official m0/l0 bind on real rebind", u0 in bindStart until m0)
        assertTrue(source.contains("null as TextView?"))
        assertTrue(source.contains("binding.visibleLightView"))
        assertTrue(source.contains("binding.sceneMode"))
        assertTrue(source.contains("{ value: Boolean -> binding.freezeCallback(value); Unit }"))
        assertTrue(source.contains("{ value: Boolean -> binding.overlayAvailabilityCallback(value); Unit }"))
        assertTrue(source.contains("128,"))
    }

    @Test
    fun recoveredM0DescriptorStillMatchesOfficialEightArgumentL0DefaultBridge() {
        val method = PreviewManagerII::class.java.getDeclaredMethod(
            "m0",
            PreviewManagerII::class.java,
            View::class.java,
            SurfaceView::class.java,
            TextView::class.java,
            FloatTextureView::class.java,
            SceneModeBean::class.java,
            Function1::class.java,
            Function1::class.java,
            Function1::class.java,
            Int::class.javaPrimitiveType,
            Any::class.java,
        )

        assertEquals(Void.TYPE, method.returnType)
    }

    private fun source(relativePath: String): String {
        var root = Path.of("").toAbsolutePath()
        repeat(5) {
            val candidate = root.resolve(relativePath)
            if (Files.exists(candidate)) return String(Files.readAllBytes(candidate))
            val appCandidate = root.resolve("../").normalize().resolve(relativePath)
            if (Files.exists(appCandidate)) return String(Files.readAllBytes(appCandidate))
            root = root.parent ?: root
        }
        throw java.nio.file.NoSuchFileException(relativePath)
    }
}
