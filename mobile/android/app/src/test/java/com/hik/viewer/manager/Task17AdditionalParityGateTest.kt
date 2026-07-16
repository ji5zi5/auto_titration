package com.hik.viewer.manager

import android.util.Size
import android.view.SurfaceView
import android.view.View
import android.widget.TextView
import com.hik.viewercommon.data.bean.SceneModeBean
import hik.common.yyrj.uicommon.widget.FloatTextureView
import kotlin.jvm.functions.Function1
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Task17AdditionalParityGateTest {
    @Test
    fun officialConstructorNestedClassAndDefaultBridgeDescriptorsArePresent() {
        assertNotNull(
            PreviewManagerII::class.java.getConstructor(
                androidx.lifecycle.Lifecycle::class.java,
                Boolean::class.javaPrimitiveType,
                Boolean::class.javaPrimitiveType,
            ),
        )
        assertEquals(
            "com.hik.viewer.manager.PreviewManagerII\$g",
            Class.forName("com.hik.viewer.manager.PreviewManagerII\$g").name,
        )
        assertEquals(
            "com.hik.viewer.manager.PreviewManagerII\$defaultLifecycleObserver\$1",
            Class.forName("com.hik.viewer.manager.PreviewManagerII\$defaultLifecycleObserver\$1").name,
        )
        assertEquals(
            Void.TYPE,
            PreviewManagerII::class.java.getDeclaredMethod(
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
            ).returnType,
        )
    }

    @Test
    fun constructorInitializesOfficialFieldIdentities() {
        val fields = PreviewManagerII::class.java.declaredFields.associateBy { it.name }
        mapOf(
            "d" to Int::class.javaPrimitiveType,
            "m" to Size::class.java,
            "n" to Size::class.java,
            "p" to Size::class.java,
            "t" to Size::class.java,
            "q" to Float::class.javaPrimitiveType,
            "v" to ArrayList::class.java,
            "A" to Class.forName("com.hik.viewer.manager.PreviewManagerII\$g"),
            "B" to Class.forName("com.hik.viewer.manager.PreviewManagerII\$defaultLifecycleObserver\$1"),
            "C" to java.util.concurrent.ExecutorService::class.java,
            "F" to Boolean::class.javaPrimitiveType,
            "K" to android.os.Handler::class.java,
            "L" to Boolean::class.javaPrimitiveType,
            "S" to Boolean::class.javaPrimitiveType,
            "i0" to com.hik.viewercommon.data.bean.PreviewInfoDataBean::class.java,
            "j0" to ByteArray::class.java,
            "l0" to Boolean::class.javaPrimitiveType,
            "r0" to ByteArray::class.java,
            "s0" to ByteArray::class.java,
            "y0" to String::class.java,
            "z0" to String::class.java,
            "A0" to ByteArray::class.java,
        ).forEach { (name, type) ->
            assertEquals("$name descriptor", type, fields.getValue(name).type)
        }
    }

    @Test
    fun sharedSupportDescriptorsMatchTheDexInvocationsUsedByPreviewManager() {
        assertEquals(
            hik.common.yyrj.businesscommon.data.DeviceInfoModel::class.java,
            u5.B::class.java.getDeclaredMethod("k").returnType,
        )
        assertEquals(Int::class.javaPrimitiveType, u5.B::class.java.getDeclaredMethod("L").returnType)
        assertEquals(Boolean::class.javaPrimitiveType, u5.B::class.java.getDeclaredMethod("d0").returnType)
        assertEquals(Boolean::class.javaPrimitiveType, u5.B::class.java.getDeclaredMethod("h0").returnType)
        assertEquals(Boolean::class.javaPrimitiveType, Z2.a::class.java.getDeclaredMethod("t").returnType)
        assertEquals(
            android.content.Context::class.java,
            d2.a::class.java.getDeclaredMethod("a").returnType,
        )
        val d2Fields = d2.a::class.java.declaredFields.associateBy { it.name }
        assertEquals(d2.a::class.java, d2Fields.getValue("a").type)
        assertEquals(android.content.Context::class.java, d2Fields.getValue("b").type)
        assertFalse("official d2.a has no Companion field", d2Fields.containsKey("Companion"))
        assertFalse("official d2.a has no Companion nested class", d2.a::class.java.declaredClasses.any { it.simpleName == "Companion" })
    }


    @Test
    fun recoveredSupportClassesHaveOfficialFieldAbiAndNoKotlinCompanionArtifacts() {
        mapOf(
            d2.a::class.java to "d2_a.dex.txt",
            Z2.a::class.java to "Z2_a.dex.txt",
            u5.B::class.java to "u5_B.dex.txt",
            hik.common.yyrj.businesscommon.b::class.java to "hik_common_yyrj_businesscommon_b.dex.txt",
        ).forEach { (clazz, dexName) ->
            assertEquals("${clazz.name} fields", officialFields(dexName), reflectFields(clazz))
            assertFalse("${clazz.name} has Companion field", clazz.declaredFields.any { it.name == "Companion" })
            assertFalse("${clazz.name} has Companion nested class", clazz.declaredClasses.any { it.simpleName == "Companion" })
            assertFalse("${clazz.name} has Kotlin property accessors", clazz.declaredMethods.any { it.name.startsWith("access$") })
        }
    }

    @Test
    fun u5BH0ReadsOfficialProductFieldMViaOfficialSetter() {
        val state = u5.B.a
        state.O0("ThgStart")
        state.P0("NotThgStart")
        assertFalse("h0 must ignore field h/O0 and read official field m", state.h0())

        state.P0("ThgStart")
        assertTrue("h0 must compare official field m against ThgStart", state.h0())

        state.P0("google")
        state.O0("")
    }

    @Test
    fun sourceDoesNotContainTask17ForbiddenFallbacks() {
        val root = generateSequence(java.io.File(requireNotNull(System.getProperty("user.dir")))) { it.parentFile }
            .flatMap { sequenceOf(it, java.io.File(it, "mobile/android")) }
            .first { java.io.File(it, "app/src/main/java/com/hik/viewer/manager/PreviewManagerII.kt").exists() }
        val preview = java.io.File(root, "app/src/main/java/com/hik/viewer/manager/PreviewManagerII.kt").readText()
        val l0Reachable = preview.substringBefore("    private fun recordOfficialPacket")
        listOf("Class.forName", "getDeclaredMethod", ".getMethod(", "TODO", "NotImplemented", "surrogate").forEach {
            assertTrue("forbidden token present: $it", !l0Reachable.contains(it))
        }
    }

    private fun officialFields(name: String): Map<String, String> {
        val root = generateSequence(java.io.File(requireNotNull(System.getProperty("user.dir")))) { it.parentFile }
            .first { java.io.File(it, ".omx/analysis/task17-shared-support/$name").exists() }
        val text = java.io.File(root, ".omx/analysis/task17-shared-support/$name").readText()
        return text.substringAfter("FIELDS\n").substringBefore("METHODS").lineSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .associate { line ->
                val parts = line.split(Regex("\\s+"))
                parts[parts.size - 2] to parts.last()
            }
    }

    private fun reflectFields(clazz: Class<*>): Map<String, String> =
        clazz.declaredFields.associate { it.name to descriptor(it.type) }

    private fun descriptor(type: Class<*>): String = when {
        type.isArray -> type.name.replace('.', '/')
        type.isPrimitive -> when (type) {
            java.lang.Boolean.TYPE -> "Z"
            java.lang.Byte.TYPE -> "B"
            java.lang.Character.TYPE -> "C"
            java.lang.Short.TYPE -> "S"
            java.lang.Integer.TYPE -> "I"
            java.lang.Long.TYPE -> "J"
            java.lang.Float.TYPE -> "F"
            java.lang.Double.TYPE -> "D"
            java.lang.Void.TYPE -> "V"
            else -> error("unknown primitive $type")
        }
        else -> "L${type.name.replace('.', '/')};"
    }
}
