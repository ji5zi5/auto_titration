package kr.auto.titration.mobile.thermal

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import com.hik.viewer.manager.PreviewManagerII
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class PreviewManagerIILifecycleBindingTest {
    @Test
    fun managerFailsClosedUntilNonNullLifecycleIsInstalled() {
        resetPreviewBinding()

        val failure = runCatching { PreviewManagerIIAppBinding.manager() }.exceptionOrNull()
        assertTrue(failure is IllegalStateException)
        assertTrue(failure!!.message!!.contains("lifecycle is not installed"))

        val lifecycle = testLifecycle()
        val manager = PreviewManagerIIAppBinding.installLifecycle(lifecycle)

        assertSame(manager, PreviewManagerIIAppBinding.manager())
        assertSame(lifecycle, previewManagerLifecycle(manager))
        assertFalse(
            "app binding must not construct the official manager with a null lifecycle",
            source("app/src/main/java/kr/auto/titration/mobile/thermal/PreviewManagerIIAppBinding.java")
                .contains("new PreviewManagerII(null"),
        )
    }

    @Test
    fun officialHostInstallsComponentActivityLifecycleBeforeAnyManagerUse() {
        val hostSource = source("app/src/main/java/kr/auto/titration/mobile/OfficialPreviewHost.kt")
        val install = hostSource.indexOf("PreviewManagerIIAppBinding.installLifecycle(activity)")
        val holder = hostSource.indexOf("selectedHolder = selectedSurfaceView.holder")
        val bind = hostSource.indexOf("maybeBindOfficialPreview()")

        assertTrue("OfficialPreviewHost must install the ComponentActivity lifecycle", install >= 0)
        assertTrue("lifecycle install must happen before holder/bind paths can use the manager", install < holder)
        assertTrue("lifecycle install must happen before bind callbacks can use the manager", install < bind)
    }

    @Test
    fun callbackBindingRejectsStaleManagerAfterLifecycleReplacement() {
        resetPreviewBinding()
        val firstLifecycle = testLifecycle()
        val firstManager = PreviewManagerIIAppBinding.installLifecycle(firstLifecycle)
        val secondManager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())

        assertTrue("replacement should create one current manager, not keep dual live managers", firstManager !== secondManager)
        assertSame(secondManager, PreviewManagerIIAppBinding.manager())

        val staleFailure = runCatching {
            PreviewManagerIIAppBinding.bind(firstManager) { }
        }.exceptionOrNull()
        assertTrue(staleFailure is IllegalStateException)
        assertTrue(staleFailure!!.message!!.contains("stale PreviewManagerII"))

        PreviewManagerIIAppBinding.bind(secondManager) { }
        val callbacks = PreviewManagerIIAppBinding::class.java.getDeclaredField("callbacks").apply { isAccessible = true }
            .get(null) as MutableMap<*, *>
        assertEquals(1, callbacks.size)
        assertTrue(callbacks.containsKey(secondManager))
        assertFalse(callbacks.containsKey(firstManager))
    }

    @Test
    fun concurrentSameLifecycleInstallationReturnsOneManagerInstance() {
        resetPreviewBinding()
        val lifecycle = testLifecycle()
        val start = CountDownLatch(1)
        val first = AtomicReference<PreviewManagerII>()
        val second = AtomicReference<PreviewManagerII>()
        val firstThread = Thread {
            start.await(2, TimeUnit.SECONDS)
            first.set(PreviewManagerIIAppBinding.installLifecycle(lifecycle))
        }
        val secondThread = Thread {
            start.await(2, TimeUnit.SECONDS)
            second.set(PreviewManagerIIAppBinding.installLifecycle(lifecycle))
        }

        firstThread.start()
        secondThread.start()
        start.countDown()
        firstThread.join(2_000)
        secondThread.join(2_000)

        assertNotNull(first.get())
        assertNotNull(second.get())
        assertSame(first.get(), second.get())
        assertSame(first.get(), PreviewManagerIIAppBinding.manager())
    }

    private fun testLifecycle(): Lifecycle {
        lateinit var registry: LifecycleRegistry
        val owner = object : LifecycleOwner {
            override val lifecycle: Lifecycle
                get() = registry
        }
        registry = LifecycleRegistry(owner)
        return registry
    }

    private fun previewManagerLifecycle(manager: PreviewManagerII): Lifecycle =
        PreviewManagerII::class.java.getDeclaredField("a").apply { isAccessible = true }.get(manager) as Lifecycle

    private fun resetPreviewBinding() {
        val managerField = PreviewManagerIIAppBinding::class.java.getDeclaredField("manager").apply { isAccessible = true }
        (managerField.get(null) as? PreviewManagerII)?.u0()
        managerField.set(null, null)
        PreviewManagerIIAppBinding::class.java.getDeclaredField("installedLifecycle").apply { isAccessible = true }.set(null, null)
        val callbacks = PreviewManagerIIAppBinding::class.java.getDeclaredField("callbacks").apply { isAccessible = true }.get(null) as MutableMap<*, *>
        callbacks.clear()
        val latestFrames = PreviewManagerIIAppBinding::class.java.getDeclaredField("latestFrames").apply { isAccessible = true }.get(null) as MutableMap<*, *>
        latestFrames.clear()
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
