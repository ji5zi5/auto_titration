package kr.auto.titration.mobile.thermal

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import com.hik.viewer.manager.PreviewManagerII
import com.hik.viewercommon.data.bean.PreviewInfoDataBean
import com.hik.viewercommon.data.bean.PreviewStreamInfo
import java.lang.reflect.InvocationTargetException
import java.lang.reflect.Modifier
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class PreviewManagerIILifecycleBindingTest {
    @After
    fun tearDown() {
        resetPreviewBinding()
    }

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
        val bindingSource = source("app/src/main/java/kr/auto/titration/mobile/thermal/PreviewManagerIIAppBinding.java")
        assertFalse(bindingSource.contains("isLegacyLocalPreviewManagerParityTest"))
        assertFalse(bindingSource.contains("ClosedLocalUnitTestLifecycle"))
        assertFalse(bindingSource.contains("getStackTrace()"))
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
        PreviewManagerIIAppBinding.bind(firstManager) { }
        val secondManager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())

        assertTrue("replacement should create one current manager, not keep dual live managers", firstManager !== secondManager)
        assertSame(secondManager, PreviewManagerIIAppBinding.manager())
        assertTrue("lifecycle replacement must use closePreviewCallback, not renderer-only u0", booleanField(firstManager, "streamClosed"))
        assertTrue(Modifier.isVolatile(PreviewManagerII::class.java.getDeclaredField("streamClosed").modifiers))
        assertNull("full replacement close must clear the native callback", field(firstManager, "C0"))

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
    fun officialGPassesC0AndLateGAfterU0CannotReviveParserOrHandoffFrame() {
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        val handoffCount = AtomicInteger(0)
        PreviewManagerIIAppBinding.bind(manager) { handoffCount.incrementAndGet() }
        val processor = RecordingProcessor()
        val metadataCallback: (Any?) -> Unit = { }
        manager.K0(metadataCallback)
        assertSame(metadataCallback, field(manager, "c0"))
        setField(manager, "D", processor)
        setField(manager, "lastFrameNumber", 1L)

        val localAndroidStubFailure = runCatching {
            invokeOfficialG(manager, ByteArray(8) { 0x21 })
        }.exceptionOrNull()

        assertEquals(1, processor.processCount)
        assertTrue(localAndroidStubFailure is InvocationTargetException)
        assertTrue(localAndroidStubFailure!!.cause!!.message!!.contains("android.util.Size"))
        assertSame(metadataCallback, field(processor, "c", g3.a::class.java))
        assertEquals(0, handoffCount.get())

        PreviewManagerIIAppBinding.afterOfficialG(
            manager,
            7,
            1L,
            256,
            192,
            0,
            0,
            103,
            ByteArray(8),
            0,
            0,
            PreviewStreamInfo(PreviewInfoDataBean(), null),
            false,
            processor.javaClass.name,
        )
        assertEquals(1, handoffCount.get())
        assertNotNull(PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 1L))

        manager.u0()
        assertNull(field(manager, "D"))
        setField(manager, "lastFrameNumber", 2L)
        invokeOfficialG(manager, ByteArray(8) { 0x22 })

        assertEquals("late G must not process after u0", 1, processor.processCount)
        assertEquals("late G must not hand a frame to the app observer", 1, handoffCount.get())
        assertNull("late G must not recreate the official parser", field(manager, "D"))
        assertNull(PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 2L))

        PreviewManagerIIAppBinding.unbind(manager)
        PreviewManagerIIAppBinding.unbind(manager)
        PreviewManagerIIAppBinding.afterOfficialG(
            manager,
            7,
            3L,
            256,
            192,
            0,
            0,
            103,
            ByteArray(8),
            0,
            0,
            PreviewStreamInfo(PreviewInfoDataBean(), null),
            false,
            "closed",
        )
        assertEquals("final unbind must suppress late native handoff", 1, handoffCount.get())
        assertNull(PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 3L))

        val previewSource = source("app/src/main/java/com/hik/viewer/manager/PreviewManagerII.java")
        val gBody = previewSource.substringAfter("    void G(byte[] packet) {")
            .substringBefore("    private void handOffOfficialFrame")
        assertTrue(gBody.contains("if (processor == null) return;"))
        assertFalse(gBody.contains("g3.b.a.a("))
        assertTrue(gBody.indexOf("processor.j(X, new K2.f(this), c0, h0, new K2.g(this))") < gBody.indexOf("processor.d(packet)"))
        assertTrue(gBody.indexOf("processor.d(packet)") < gBody.indexOf("handOffOfficialFrame(streamInfo, packet)"))
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

    private fun invokeOfficialG(manager: PreviewManagerII, packet: ByteArray) {
        PreviewManagerII::class.java.getDeclaredMethod("G", ByteArray::class.java)
            .apply { isAccessible = true }
            .invoke(manager, packet)
    }

    private fun setField(target: Any, name: String, value: Any?) {
        target.javaClass.getDeclaredField(name).apply { isAccessible = true }.set(target, value)
    }

    private fun field(target: Any, name: String, owner: Class<*> = target.javaClass): Any? =
        owner.getDeclaredField(name).apply { isAccessible = true }.get(target)

    private fun booleanField(target: Any, name: String): Boolean = field(target, name) as Boolean

    private fun resetPreviewBinding() {
        val managerField = PreviewManagerIIAppBinding::class.java.getDeclaredField("manager").apply { isAccessible = true }
        (managerField.get(null) as? PreviewManagerII)?.closePreviewCallback()
        managerField.set(null, null)
        PreviewManagerIIAppBinding::class.java.getDeclaredField("installedLifecycle").apply { isAccessible = true }.set(null, null)
        val callbacks = PreviewManagerIIAppBinding::class.java.getDeclaredField("callbacks").apply { isAccessible = true }.get(null) as MutableMap<*, *>
        callbacks.clear()
        val latestFrames = PreviewManagerIIAppBinding::class.java.getDeclaredField("latestFrames").apply { isAccessible = true }.get(null) as MutableMap<*, *>
        latestFrames.clear()
    }

    private class RecordingProcessor : g3.a() {
        var processCount: Int = 0

        override fun d(frameInfoData: ByteArray): PreviewStreamInfo {
            processCount += 1
            return PreviewStreamInfo(PreviewInfoDataBean(), null)
        }
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
