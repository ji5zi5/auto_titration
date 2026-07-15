package g007

import Z2.g
import com.hik.viewercommon.data.bean.SceneModeBean
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import w3.f

class G007StatefulSubstitutesTest {
    @Test
    fun q0AliasesTheOfficialListInsteadOfCopyingIt() {
        val values = mutableListOf<Any>("first")
        g.a.Q0(values)
        assertSame(values, g.a.L())
        values += "second"
        assertEquals(listOf("first", "second"), g.a.L())
    }

    @Test
    fun sceneModeRestorePrefersPersistedJsonAndCopiesDefaultsOnlyAsFallback() {
        val persisted = g.restoreSceneModes("""[{"id":7,"name":"lab","alarmEnable":true}]""", emptyList())
        assertEquals(1, persisted.size)
        assertEquals(
            SceneModeBean(id = 7, name = "lab", alarmEnable = true),
            persisted.single(),
        )

        val default = SceneModeBean()
        val fallback = g.restoreSceneModes("", listOf(default))
        assertEquals(1, fallback.size)
        assertNotSame(default, fallback.single())
        assertEquals(default, fallback.single())
    }

    @Test
    fun rendererRetainsOfficialModeDrawerCallbackAndPresentationState() {
        val renderer = x3.a()
        val drawer = object : f {}
        renderer.l(x3.a.b.b)
        renderer.i(drawer)
        renderer.o(
            object : kotlin.jvm.functions.Function2<Int, Int, kotlin.Unit> {
                override fun invoke(width: Int, height: Int) = kotlin.Unit
            },
        )
        renderer.k(1234L)

        assertEquals(x3.a.b.b, field(renderer, "mode"))
        assertEquals(listOf(drawer), field(renderer, "drawers"))
        assertTrue(field<Any?>(renderer, "sizeCallback") != null)
        assertEquals(1234L, field(renderer, "lastPresentationTime"))
    }

    @Test
    fun recorderRetainsOfficialDimensionsSessionAndFrameSubmissionState() {
        val recorder = y3.b(null)
        val drawer = object : f {}
        recorder.t(1280, 720)
        recorder.u(1.0f, "/tmp/out.mp4")
        recorder.r(99L, listOf(drawer))

        assertTrue(recorder.recording)
        assertEquals(1280, field(recorder, "width"))
        assertEquals(720, field(recorder, "height"))
        assertEquals("/tmp/out.mp4", field(recorder, "path"))
        assertEquals(1.0f, field<Float>(recorder, "scale"))
        assertEquals(99L, field(recorder, "lastPresentationTimeNs"))
        assertEquals(listOf(drawer), field(recorder, "lastDrawers"))

        recorder.v()
        assertFalse(recorder.recording)
    }

    @Test
    fun recordingDimensionsKeep720OnTheShortEdge() {
        z3.c.a(1920, 1080)
        assertEquals(1280, staticField<Int>(z3.c::class.java, "u"))
        assertEquals(720, staticField<Int>(z3.c::class.java, "v"))

        z3.c.a(1080, 1920)
        assertEquals(720, staticField<Int>(z3.c::class.java, "u"))
        assertEquals(1280, staticField<Int>(z3.c::class.java, "v"))
    }

    @Suppress("UNCHECKED_CAST")
    private fun <T> field(target: Any, name: String): T =
        target.javaClass.getDeclaredField(name).run {
            isAccessible = true
            get(target) as T
        }

    @Suppress("UNCHECKED_CAST")
    private fun <T> staticField(type: Class<*>, name: String): T =
        type.getDeclaredField(name).run {
            isAccessible = true
            get(null) as T
        }
}
