package Z2

import f3.j
import f3.k
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class Z2ProfileModelTest {
    @After
    fun restoreOfficialDefault() {
        a.a.u(f3.a())
    }

    @Test
    fun officialDefaultIsNeutralKProfileAndJRemainsAssignableThroughK() {
        val repository = a.a
        repository.u(f3.a())
        val defaultProfile: k = repository.p()

        assertTrue(defaultProfile is f3.a)
        assertEquals(listOf(0), defaultProfile.e())
        assertFalse(repository.q())

        val f2Profile = j()
        repository.u(f2Profile)

        assertSame(f2Profile, repository.p())
        assertEquals(12, repository.p().k())
        assertEquals(listOf(203_720, 183_496), repository.p().e())
    }
}
