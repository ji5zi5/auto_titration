package g007

import com.hcusbsdk.Interface.FStreamCallBack
import com.hik.f1module.hcusbcamerasdk.callback.IStreamCallback
import com.hik.viewer.manager.PreviewManagerII
import android.graphics.RectF
import java.io.File
import java.lang.reflect.Modifier
import java.util.Comparator
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class G007PreviewManagerIIJavapAbiTest {
    @Test fun d0DescriptorAndStaticInitializationMatchOfficialCompanionMarker() {
        val d0 = PreviewManagerII::class.java.getDeclaredField("D0")
        assertTrue(Modifier.isStatic(d0.modifiers))
        assertTrue(Modifier.isFinal(d0.modifiers))
        assertEquals("com.hik.viewer.manager.PreviewManagerII\$a", d0.type.name)
        assertEquals(d0.type, d0.get(null).javaClass)

        val outer = javap("com.hik.viewer.manager.PreviewManagerII")
        assertTrue(outer.contains("public static final com.hik.viewer.manager.PreviewManagerII\$a D0;"))
        val outerCode = javap("-c", "com.hik.viewer.manager.PreviewManagerII")
        assertTrue(outerCode.contains("new           #") && outerCode.contains("PreviewManagerII\$a"))
        assertTrue(outerCode.contains("putstatic") && outerCode.contains("// Field D0:Lcom/hik/viewer/manager/PreviewManagerII\$a;"))
    }

    @Test fun nestedClassIdentitiesMatchOfficialDescriptors() {
        val marker = Class.forName("com.hik.viewer.manager.PreviewManagerII\$a")
        assertSame(Any::class.java, marker.superclass)
        assertTrue(marker.declaredConstructors.any { Modifier.isPrivate(it.modifiers) && it.parameterTypes.isEmpty() })
        assertTrue(marker.declaredConstructors.any { descriptor(it.parameterTypes) == "(Lkotlin/jvm/internal/DefaultConstructorMarker;)" })

        val typeToken = Class.forName("com.hik.viewer.manager.PreviewManagerII\$b")
        assertEquals("com.google.gson.reflect.TypeToken", typeToken.superclass.name)
        val typeTokenVerbose = javap("-v", "com.hik.viewer.manager.PreviewManagerII\$b")
        assertTrue(typeTokenVerbose.contains("Lcom/google/gson/reflect/TypeToken<Ljava/util/Stack<LQ2/k;>;>;"))

        val comparator = Class.forName("com.hik.viewer.manager.PreviewManagerII\$c")
        assertTrue(Comparator::class.java.isAssignableFrom(comparator))
        assertSame(Any::class.java, comparator.superclass)
        val comparatorCode = javap("-c", "com.hik.viewer.manager.PreviewManagerII\$c")
        assertTrue(comparatorCode.contains("checkcast") && comparatorCode.contains("// class Q2/k"))
        assertTrue(comparatorCode.contains("invokevirtual") && comparatorCode.contains("// Method Q2/k.c:()F"))
        assertFalse(comparatorCode.contains("java/lang/reflect"))
        @Suppress("UNCHECKED_CAST")
        val instance = comparator.getDeclaredConstructor().newInstance() as Comparator<Any>
        assertTrue(instance.compare(Q2.k(0.1f, RectF(), 0, false, true), Q2.k(0.9f, RectF(), 0, false, true)) < 0)

        assertTrue(FStreamCallBack::class.java.isAssignableFrom(Class.forName("com.hik.viewer.manager.PreviewManagerII\$d")))
        assertTrue(IStreamCallback::class.java.isAssignableFrom(Class.forName("com.hik.viewer.manager.PreviewManagerII\$e")))
        assertTrue(com.hik.library.player.b::class.java.isAssignableFrom(Class.forName("com.hik.viewer.manager.PreviewManagerII\$f")))
        assertTrue(android.view.SurfaceHolder.Callback::class.java.isAssignableFrom(Class.forName("com.hik.viewer.manager.PreviewManagerII\$g")))
        assertTrue(androidx.lifecycle.DefaultLifecycleObserver::class.java.isAssignableFrom(Class.forName("com.hik.viewer.manager.PreviewManagerII\$defaultLifecycleObserver\$1")))
    }

    @Test fun q2kDirectSupportDescriptorMatchesOfficialDexShape() {
        val q2 = Class.forName("Q2.k")
        assertTrue(Modifier.isPublic(q2.modifiers))
        assertTrue(Modifier.isFinal(q2.modifiers))
        assertEquals("(FLandroid/graphics/RectF;IZZ)", descriptor(q2.declaredConstructors.single { Modifier.isPublic(it.modifiers) }.parameterTypes))
        assertEquals(listOf("a:float", "b:RectF", "c:int", "d:boolean", "e:boolean"), q2.declaredFields.map { it.name + ":" + it.type.simpleName })
        listOf("a", "e").forEach { assertEquals(Boolean::class.javaPrimitiveType, q2.getDeclaredMethod(it).returnType) }
        assertEquals(Integer.TYPE, q2.getDeclaredMethod("b").returnType)
        assertEquals(java.lang.Float.TYPE, q2.getDeclaredMethod("c").returnType)
        assertEquals(RectF::class.java, q2.getDeclaredMethod("d").returnType)
        assertEquals(Void.TYPE, q2.getDeclaredMethod("f", Integer.TYPE).returnType)
        assertEquals(Void.TYPE, q2.getDeclaredMethod("g", java.lang.Float.TYPE).returnType)
        assertEquals(Void.TYPE, q2.getDeclaredMethod("h", RectF::class.java).returnType)
        assertEquals(Void.TYPE, q2.getDeclaredMethod("i", Boolean::class.javaPrimitiveType).returnType)
        val code = javap("-c", "Q2.k")
        assertTrue(code.contains("public final float c();") && code.contains("// Field a:F"))
    }

    @Test fun constructorDefaultsAndRUAreConstructorCreatedDirectFields() {
        val manager = PreviewManagerII(null, false, false)
        assertEquals(FStreamCallBack::class.java, PreviewManagerII::class.java.getDeclaredMethod("R").returnType)
        assertEquals(IStreamCallback::class.java, PreviewManagerII::class.java.getDeclaredMethod("U").returnType)
        assertEquals("com.hik.viewer.manager.PreviewManagerII\$d", manager.R().javaClass.name)
        assertEquals("com.hik.viewer.manager.PreviewManagerII\$e", manager.U().javaClass.name)
        assertSame(manager.R(), manager.R())
        assertSame(manager.U(), manager.U())
        assertEquals(0, bytes(manager, "r0").size)
        assertEquals(0, bytes(manager, "s0").size)
        assertEquals(0, bytes(manager, "j0").size)
        assertEquals(0, bytes(manager, "A0").size)
        assertEquals("", field(manager, "y0"))
        assertEquals("", field(manager, "z0"))
        assertEquals(true, field(manager, "F"))
        assertEquals(true, field(manager, "L"))
        assertEquals(true, field(manager, "S"))
        assertEquals(true, field(manager, "l0"))

        val code = javap("-c", "com.hik.viewer.manager.PreviewManagerII")
        val rBody = code.substringAfter("public final com.hcusbsdk.Interface.FStreamCallBack R();").substringBefore("public final")
        val uBody = code.substringAfter("public final com.hik.f1module.hcusbcamerasdk.callback.IStreamCallback U();").substringBefore("public final")
        assertTrue(rBody.contains("getfield") && rBody.contains("// Field C0:Lcom/hcusbsdk/Interface/FStreamCallBack;"))
        assertFalse(rBody.contains("new"))
        assertTrue(uBody.contains("getfield") && uBody.contains("// Field B0:Lcom/hik/f1module/hcusbcamerasdk/callback/IStreamCallback;"))
        assertFalse(uBody.contains("new"))
    }

    @Test fun officialBoundaryDoesNotPublishKnownAppHelperAbi() {
        val methods = PreviewManagerII::class.java.declaredMethods.map { it.name }.toSet()
        assertFalse(methods.contains("createF2ModuleStreamCallback"))
        listOf(
            "com.hik.viewer.manager.PreviewManagerII\$Companion",
            "com.hik.viewer.manager.PreviewManagerII\$OfficialF2StreamCallback",
            "com.hik.viewer.manager.PreviewManagerII\$BufferedF2Packet",
            "com.hik.viewer.manager.PreviewManagerIIKt",
        ).forEach { name -> assertFalse("unexpected class artifact $name", runCatching { Class.forName(name) }.isSuccess) }
        assertFalse(PreviewManagerII::class.java.declaredFields.any { it.name == "INSTANCE" || it.name == "Companion" })
    }

    private fun bytes(target: Any, name: String) = field(target, name) as ByteArray

    private fun field(target: Any, name: String): Any? = target.javaClass.getDeclaredField(name).let {
        it.isAccessible = true
        it.get(target)
    }

    private fun descriptor(parameterTypes: Array<Class<*>>) = parameterTypes.joinToString(separator = "", prefix = "(", postfix = ")") { type ->
        when {
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
            type.isArray -> type.name.replace('.', '/')
            else -> "L${type.name.replace('.', '/')};"
        }
    }

    private fun javap(vararg args: String): String {
        val javap = File(System.getProperty("java.home"), "bin/javap").absolutePath
        val process = ProcessBuilder(listOf(javap, "-classpath", System.getProperty("java.class.path")) + args)
            .redirectErrorStream(true)
            .start()
        val output = process.inputStream.bufferedReader().readText()
        assertEquals(output, 0, process.waitFor())
        return output
    }
}
