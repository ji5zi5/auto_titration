package g007

import java.nio.ByteOrder
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class G007U4CodecTest {
    @Test fun roundTripOfficialFixtureStructLittleEndianWithNestedArray() {
        val src = U4ParityFixtures.Header().apply {
            magic = 0x01020304
            version = 0x1122
            flags = 0x7f
            temp = 36.5f
            child.x = 0x3344
            child.y = 0x55667788
            count = 3
            values = intArrayOf(10, 20, 30)
            tail = byteArrayOf(1, 2, 3)
        }
        val bytes = U4.c.a(src, ByteOrder.LITTLE_ENDIAN)
        assertArrayEquals(byteArrayOf(0x04, 0x03, 0x02, 0x01), bytes.copyOfRange(0, 4))
        assertEquals(4 + 2 + 1 + 4 + 2 + 4 + 4 + 12 + 3, bytes.size)
        val dst = U4ParityFixtures.Header()
        U4.c.b(dst, bytes, ByteOrder.LITTLE_ENDIAN)
        assertEquals(src.magic, dst.magic)
        assertEquals(src.version, dst.version)
        assertEquals(src.flags, dst.flags)
        assertEquals(src.temp, dst.temp)
        assertEquals(src.child.x, dst.child.x)
        assertEquals(src.child.y, dst.child.y)
        assertEquals(src.count, dst.count)
        assertArrayEquals(src.values, dst.values)
        assertArrayEquals(src.tail, dst.tail)
    }

    @Test fun bigEndianUsesDataStreamsAndLittleEndianUsesOfficialWrappers() {
        val src = U4ParityFixtures.PrivatePrimitive().apply { value = 0x01020304 }
        assertArrayEquals(byteArrayOf(0x01, 0x02, 0x03, 0x04), U4.c.a(src, ByteOrder.BIG_ENDIAN))
        assertArrayEquals(byteArrayOf(0x04, 0x03, 0x02, 0x01), U4.c.a(src, ByteOrder.LITTLE_ENDIAN))
    }

    @Test fun getterSetterLengthMarkerAllocatesArraysAndUsesBooleanIsGetter() {
        val src = U4ParityFixtures.AccessorLength().apply {
            count = 2
            values = intArrayOf(0x01020304, 0x05060708)
            isActive = true
        }
        val bytes = U4.c.a(src, ByteOrder.LITTLE_ENDIAN)
        assertEquals(4 + 8 + 1, bytes.size)
        val dst = U4ParityFixtures.AccessorLength()
        U4.c.b(dst, bytes, ByteOrder.LITTLE_ENDIAN)
        assertEquals(2, dst.count)
        assertArrayEquals(intArrayOf(0x01020304, 0x05060708), dst.values)
        assertTrue(dst.isActive)
    }

    @Test fun objectArraysAreInstantiatedFromLengthMarkerOnRead() {
        val src = U4ParityFixtures.ObjectArrayHolder().apply {
            count = 2
            children = arrayOf(
                U4ParityFixtures.Child().apply { x = 1; y = 2 },
                U4ParityFixtures.Child().apply { x = 3; y = 4 },
            )
        }
        val bytes = U4.c.a(src, ByteOrder.LITTLE_ENDIAN)
        val dst = U4ParityFixtures.ObjectArrayHolder()
        U4.c.b(dst, bytes, ByteOrder.LITTLE_ENDIAN)
        assertEquals(2, dst.count)
        assertEquals(2, dst.children.size)
        assertEquals(1, dst.children[0].x.toInt())
        assertEquals(2, dst.children[0].y)
        assertEquals(3, dst.children[1].x.toInt())
        assertEquals(4, dst.children[1].y)
    }

    @Test fun nullStructAndArrayErrorsMatchOfficialMessages() {
        val nullObjectError = runCatching { U4.c.a(U4ParityFixtures.NullObjectHolder(), ByteOrder.LITTLE_ENDIAN) }.exceptionOrNull()
        assertEquals("Struct classes cant be null. ", nullObjectError?.message)

        val nullArrayError = runCatching { U4.c.b(U4ParityFixtures.NullArrayHolder(), byteArrayOf(1), ByteOrder.LITTLE_ENDIAN) }.exceptionOrNull()
        assertEquals("Arrays can not be null. : bytes", nullArrayError?.message)
    }

    @Test fun inheritedFieldsAreNotIncludedBecauseOfficialUsesDeclaredFieldsOnly() {
        val src = U4ParityFixtures.ChildWithInheritedField().apply {
            parentValue = 0x11111111
            childValue = 0x22222222
        }
        assertArrayEquals(byteArrayOf(0x22, 0x22, 0x22, 0x22), U4.c.a(src, ByteOrder.LITTLE_ENDIAN))
    }

    @Test fun k3bDelegatesAndCatchesCodecErrorsLikeOfficialKotlinFacade() {
        val bytes = k3.b.a.a(U4ParityFixtures.Header().apply { count = 0; tail = byteArrayOf(9, 8, 7) }, ByteOrder.LITTLE_ENDIAN)
        assertNotNull(bytes)
        assertNull(k3.b.a.a(Any(), ByteOrder.LITTLE_ENDIAN))
    }
}
