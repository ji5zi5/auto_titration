package g3

import com.hik.viewercommon.data.bean.PreviewInfoDataBean
import h3.a as StreamInfo
import i3.a as StreamInfoDeal
import java.lang.reflect.Modifier
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class G007OfficialPacketProcessorParityTest {
    @Test
    fun officialG3ClassBoundaryAndFactoryAreMaterializedWithoutProcessorSubstitute() {
        assertSame(a::class.java, d::class.java.superclass)
        assertSame(d::class.java, e::class.java.superclass)
        assertSame(a::class.java, c::class.java.superclass)
        assertSame(a::class.java, f::class.java.superclass)
        assertSame(a::class.java, g::class.java.superclass)

        assertTrue(b.a.a(8, false) is f)
        assertTrue(b.a.a(9, false) is g)
        assertTrue(b.a.a(10, false) is g)
        assertTrue(b.a.a(11, false) is c)
        assertEquals(d::class.java, b.a.a(12, false)::class.java)
        assertTrue(b.a.a(12, true) is e)
        assertTrue(b.a.a(Int.MIN_VALUE, false) is g)

        assertFalse(runCatching { Class.forName("g3.OfficialPacketProcessor") }.isSuccess)
    }

    @Test
    fun officialG3DAndEExposeDexFieldsAndMethods() {
        assertTrue(Modifier.isStatic(d::class.java.getDeclaredField("h").modifiers))
        assertEquals(i3.a::class.java, d::class.java.getDeclaredField("f").type)
        assertEquals(kotlin.jvm.functions.Function1::class.java, d::class.java.getDeclaredField("g").type)
        listOf("d", "m", "n", "l", "o").forEach { name ->
            assertTrue("missing d.$name", d::class.java.declaredMethods.any { it.name == name })
        }
        assertTrue(Modifier.isStatic(e::class.java.getDeclaredField("j").modifiers))
        assertEquals(i3.a::class.java, e::class.java.getDeclaredField("i").type)
        assertTrue(e::class.java.declaredMethods.any { it.name == "d" })
        assertTrue(e::class.java.declaredMethods.any { it.name == "n" })
    }

    @Test
    fun callbackSlotsStoreClearAndUnsupportedPacketsDispatchFailClosed() {
        val deal = RecordingStreamInfoDeal()
        val processor = d(deal)
        val freezeCallback: (Boolean) -> Unit = {}
        val thawCallback: (Boolean) -> Unit = {}
        val metadataCallback: (Any?) -> Unit = {}
        val overlayCallback: (Any?, Any?, Any?, Any?, Any?) -> Unit = { _, _, _, _, _ -> }
        val osdCallback: (Any?) -> Unit = {}

        processor.j(freezeCallback, thawCallback, metadataCallback, overlayCallback, osdCallback)
        assertSame(freezeCallback, processor.slot("a"))
        assertSame(thawCallback, processor.slot("b"))
        assertSame(metadataCallback, processor.slot("c"))
        assertSame(overlayCallback, processor.slot("d"))
        assertSame(osdCallback, processor.slot("e"))

        val result = processor.d(ByteArray(17))
        assertEquals(listOf(false), deal.freezeStates)
        assertEquals(1, deal.metadataCalls)
        assertEquals(1, deal.osdCalls)
        assertNull(result.getIStreamInfo())
        assertEquals(0, result.getPreviewInfoData().getByteArrSrc().size)

        processor.k()
        listOf("a", "b", "c", "d", "e").forEach { assertNull(processor.slot(it)) }
    }

    private fun a.slot(name: String): Any? {
        val field = a::class.java.getDeclaredField(name)
        field.isAccessible = true
        return field.get(this)
    }

    private class RecordingStreamInfoDeal : StreamInfoDeal {
        val freezeStates = mutableListOf<Boolean>()
        var metadataCalls = 0
        var osdCalls = 0

        override fun a(isFreezeData: Boolean, freezeCallback: ((Boolean) -> Unit)?, thawCallback: ((Boolean) -> Unit)?) {
            freezeStates += isFreezeData
        }

        override fun b(streamInfo: StreamInfo?, previewInfoData: PreviewInfoDataBean, metadataCallback: ((Any?) -> Unit)?, overlayCallback: ((Any?, Any?, Any?, Any?, Any?) -> Unit)?) {
            metadataCalls += 1
        }

        override fun c(streamInfo: StreamInfo?, rawAppendData: ByteArray, callback: ((ByteArray) -> Unit)?) {
            osdCalls += 1
        }
    }
}
