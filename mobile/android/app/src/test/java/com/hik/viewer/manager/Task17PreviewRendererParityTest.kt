package com.hik.viewer.manager

import android.graphics.Bitmap
import android.util.Size
import android.view.SurfaceView
import android.view.View
import android.widget.TextView
import android.animation.TypeEvaluator
import com.hik.library.player.b
import com.hik.library.player.d
import com.hik.viewer.bean.DiagnoseBean
import com.hik.viewercommon.data.bean.SceneModeBean
import hik.common.yyrj.uicommon.widget.FloatTextureView
import kotlin.jvm.functions.Function1
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
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
    fun floatTextureViewRestoresTheOfficialFieldsMethodsAndEvaluator() {
        val type = FloatTextureView::class.java
        assertEquals(
            listOf("a:float", "b:float", "c:int", "d:int", "e:kotlin.jvm.functions.Function1"),
            listOf("a", "b", "c", "d", "e").map { name ->
                val field = type.getDeclaredField(name)
                "$name:${field.type.name}"
            },
        )
        assertEquals("hik.common.yyrj.uicommon.widget.FloatTextureView\$a", type.getField("f").type.name)
        assertTrue(type.declaredConstructors.any { it.parameterTypes.contentEquals(arrayOf(android.content.Context::class.java, android.util.AttributeSet::class.java)) })
        assertTrue(type.declaredConstructors.any { it.parameterTypes.contentEquals(arrayOf(android.content.Context::class.java, android.util.AttributeSet::class.java, Int::class.javaPrimitiveType)) })
        assertEquals(Int::class.javaPrimitiveType, type.getDeclaredMethod("b").returnType)
        assertEquals(Void.TYPE, type.getDeclaredMethod("c", Float::class.javaPrimitiveType, Float::class.javaPrimitiveType).returnType)
        assertEquals(Void.TYPE, type.getDeclaredMethod("g").returnType)
        assertEquals(Void.TYPE, type.getDeclaredMethod("h", Float::class.javaPrimitiveType, Float::class.javaPrimitiveType).returnType)
        assertEquals(Void.TYPE, type.getDeclaredMethod("d", Int::class.javaPrimitiveType, Boolean::class.javaPrimitiveType).returnType)
        assertEquals(
            Void.TYPE,
            type.getDeclaredMethod("f", Int::class.javaPrimitiveType, Boolean::class.javaPrimitiveType, Size::class.java, Size::class.java).returnType,
        )
        val evaluator = Class.forName("hik.common.yyrj.uicommon.widget.FloatTextureView\$b")
        assertTrue(TypeEvaluator::class.java.isAssignableFrom(evaluator))
        assertEquals(FloatTextureView::class.java, evaluator.getDeclaredField("a").type)
        assertFalse(type.declaredMethods.any { it.name.contains("officialFloatTexturePosition") })
    }

    @Test
    fun playerListenerDoesNotRouteL0CallbacksToGuessedLifecycleEvents() {
        val manager = kr.auto.titration.mobile.thermal.PreviewManagerIIAppBinding.manager()
        var freezeCalls = 0
        var overlayCalls = 0
        var frameCalls = 0
        var diagnoses = 0
        setField(manager, "X", { _: Boolean -> freezeCalls += 1 })
        setField(manager, "Q", { _: Boolean -> overlayCalls += 1 })
        setField(manager, "T", { _: Int -> frameCalls += 1 })
        manager.D0 { diagnoses += 1 }

        val listener = Class.forName("com.hik.viewer.manager.PreviewManagerII\$f")
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
        assertEquals(0, diagnoses)
        manager.D0(null)
        setField(manager, "X", null)
        setField(manager, "Q", null)
        setField(manager, "T", null)
    }

    @Test
    fun teardownStopsThenReleasesRendererAndRetainsOfficialL0State() {
        val manager = kr.auto.titration.mobile.thermal.PreviewManagerIIAppBinding.manager()
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
