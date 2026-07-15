package com.hik.viewer.manager

import android.graphics.Bitmap
import android.util.Size
import android.view.SurfaceView
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OfficialRendererGraphTest {
    @Test
    fun recoveredV2RendererAbiMatchesOfficialDescriptors() {
        val methods = V2.f::class.java.declaredMethods.associateBy { it.name }

        assertEquals(Boolean::class.javaPrimitiveType, methods.getValue("a").returnType)
        assertEquals(listOf(com.hik.library.player.b::class.java), methods.getValue("b").parameterTypes.toList())
        assertEquals(listOf(Size::class.java), methods.getValue("e").parameterTypes.toList())
        assertEquals(ByteArray::class.java, methods.getValue("e").returnType)
        assertEquals(com.hik.library.player.d::class.java, methods.getValue("f").returnType)
        assertEquals(
            listOf(ByteArray::class.java, ByteArray::class.java, Size::class.java, Int::class.javaPrimitiveType),
            methods.getValue("h").parameterTypes.toList(),
        )
        assertEquals(
            listOf(
                ByteArray::class.java,
                ByteArray::class.java,
                Size::class.java,
                Int::class.javaPrimitiveType,
                List::class.java,
                Bitmap::class.java,
            ),
            methods.getValue("j").parameterTypes.toList(),
        )
        assertTrue(methods.keys.containsAll(listOf("c", "d", "g", "i", "k", "release", "start", "stop")))
    }

    @Test
    fun recoveredX2FactoriesExposeExactSurfaceViewGraph() {
        for (factory in listOf(X2.a::class.java, X2.c::class.java)) {
            assertTrue(X2.b::class.java.isAssignableFrom(factory))
            for (methodName in listOf("a", "b", "c")) {
                val method = factory.getDeclaredMethod(methodName, SurfaceView::class.java)
                assertEquals(V2.f::class.java, method.returnType)
            }
        }

        assertFalse(V2.f::class.java.isAssignableFrom(X2.b::class.java))
    }

    @Test
    fun processorIdentityComesFromActualOfficialFactoryResultForEveryBucket() {
        val factory = g3.b.a
        assertEquals("g3.f", factory.a(8, false).javaClass.name)
        assertEquals("g3.g", factory.a(9, false).javaClass.name)
        assertEquals("g3.g", factory.a(10, true).javaClass.name)
        assertEquals("g3.c", factory.a(11, false).javaClass.name)
        assertEquals("g3.d", factory.a(12, false).javaClass.name)
        assertEquals("g3.e", factory.a(12, true).javaClass.name)
        assertEquals("g3.g", factory.a(Int.MIN_VALUE, false).javaClass.name)
    }
}
