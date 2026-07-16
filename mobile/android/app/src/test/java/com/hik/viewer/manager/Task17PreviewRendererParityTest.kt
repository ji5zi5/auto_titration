package com.hik.viewer.manager

import android.graphics.Bitmap
import android.util.Size
import android.view.Gravity
import android.view.SurfaceView
import android.view.View
import android.widget.TextView
import com.hik.library.player.b
import com.hik.library.player.d
import com.hik.viewer.bean.DiagnoseBean
import com.hik.viewercommon.data.bean.SceneModeBean
import hik.common.yyrj.uicommon.widget.FloatTextureView
import hik.common.yyrj.uicommon.widget.officialFloatTexturePosition
import kotlin.jvm.functions.Function1
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Test

class Task17PreviewRendererParityTest {
    @Test
    fun l0KeepsTheOfficialDescriptorAndTypedFunctionChannels() {
        val method = PreviewManagerII::class.java.getDeclaredMethod(
            "l0",
            View::class.java,
            SurfaceView::class.java,
            TextView::class.java,
            FloatTextureView::class.java,
            SceneModeBean::class.java,
            Function1::class.java,
            Function1::class.java,
            Function1::class.java,
        )

        assertEquals(Void.TYPE, method.returnType)
        assertEquals(true, method.genericParameterTypes[5].typeName.contains("java.lang.Boolean"))
        assertEquals(true, method.genericParameterTypes[6].typeName.contains("java.lang.Boolean"))
        assertEquals(true, method.genericParameterTypes[7].typeName.contains("java.lang.Integer"))
        assertEquals(true, field("X").genericType.typeName.contains("java.lang.Boolean"))
        assertEquals(true, field("Q").genericType.typeName.contains("java.lang.Boolean"))
        assertEquals(true, field("T").genericType.typeName.contains("java.lang.Integer"))
    }

    @Test
    fun floatTextureGravityUsesTheFourOfficialDexPositions() {
        assertEquals(0f to 0f, position(Gravity.START or Gravity.TOP))
        assertEquals(240f to 0f, position(Gravity.END or Gravity.TOP))
        assertEquals(0f to 160f, position(Gravity.START or Gravity.BOTTOM))
        assertEquals(240f to 160f, position(Gravity.END or Gravity.BOTTOM))
        assertEquals(0f to 0f, position(Gravity.CENTER))
    }

    @Test
    fun playerListenerDoesNotRouteL0CallbacksToGuessedLifecycleEvents() {
        val manager = PreviewManagerII.INSTANCE
        var freezeCalls = 0
        var overlayCalls = 0
        var frameCalls = 0
        var diagnoses = 0
        setField(manager, "X", { _: Boolean -> freezeCalls += 1 })
        setField(manager, "Q", { _: Boolean -> overlayCalls += 1 })
        setField(manager, "T", { _: Int -> frameCalls += 1 })
        manager.D0 { diagnoses += 1 }

        val listener = PreviewManagerII::class.java.declaredClasses
            .single { it.simpleName == "OfficialPlaybackListener" }
            .getDeclaredConstructor(PreviewManagerII::class.java)
            .apply { isAccessible = true }
            .newInstance(manager) as b

        listener.a()
        listener.b()
        listener.onError("error")
        listener.onPause()
        listener.onResume()
        listener.onStart()
        listener.onStop()

        assertEquals(0, freezeCalls)
        assertEquals(0, overlayCalls)
        assertEquals(0, frameCalls)
        assertEquals(3, diagnoses)
        manager.D0(null)
        setField(manager, "X", null)
        setField(manager, "Q", null)
        setField(manager, "T", null)
    }

    @Test
    fun teardownStopsThenReleasesRendererAndRetainsOfficialL0State() {
        val manager = PreviewManagerII.INSTANCE
        val calls = mutableListOf<String>()
        val renderer = RecordingRenderer(calls)
        val scene = SceneModeBean()
        val overlayCallback: (Boolean) -> Unit = {}
        val frameCallback: (Int) -> Unit = {}
        val diagnoseCallback: (DiagnoseBean) -> Unit = {}
        setField(manager, "E", renderer)
        setField(manager, "X", { _: Boolean -> })
        setField(manager, "Q", overlayCallback)
        setField(manager, "T", frameCallback)
        setField(manager, "O", scene)
        manager.D0(diagnoseCallback)

        manager.closePreviewCallback()

        assertEquals(listOf("c", "release"), calls)
        assertNull(field("E").get(manager))
        assertNull(field("X").get(manager))
        assertSame(overlayCallback, field("Q").get(manager))
        assertSame(frameCallback, field("T").get(manager))
        assertSame(scene, field("O").get(manager))
        assertSame(diagnoseCallback, field("z").get(manager))
        setField(manager, "Q", null)
        setField(manager, "T", null)
        setField(manager, "O", null)
        manager.D0(null)
        manager.openPreviewCallback()
    }

    private fun position(gravity: Int): Pair<Float, Float> = officialFloatTexturePosition(
        gravity = gravity,
        availableWidth = 320,
        availableHeight = 240,
        childWidth = 80,
        childHeight = 80,
    )

    private fun field(name: String) = PreviewManagerII::class.java.getDeclaredField(name).apply {
        isAccessible = true
    }

    private fun setField(instance: Any, name: String, value: Any?) {
        field(name).set(instance, value)
    }

    private class RecordingRenderer(private val calls: MutableList<String>) : V2.f {
        override fun a(): Boolean = false
        override fun b(listener: b) = Unit
        override fun c() { calls += "c" }
        override fun d(picSize: Size, filePath: String): Boolean = false
        override fun e(picSize: Size): ByteArray? = null
        override fun f(picSize: Size): d = d(-1, null)
        override fun g(
            first: Boolean,
            second: Boolean,
            third: Boolean,
            fourth: Boolean,
            mode: Int,
            firstScale: Float,
            secondScale: Float,
        ) = Unit
        override fun h(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int) = Unit
        override fun i(showSize: Size) = Unit
        override fun j(
            rawData: ByteArray?,
            nv12Data: ByteArray,
            yuvImgSize: Size,
            frameNumStamp: Int,
            overlays: List<*>?,
            overlayBitmap: Bitmap?,
        ) = Unit
        override fun k(value: Int) = Unit
        override fun release() { calls += "release" }
        override fun start() = Unit
        override fun stop() = Unit
    }
}
