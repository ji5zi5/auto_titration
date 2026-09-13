package kr.auto.titration.mobile.thermal

import android.graphics.Bitmap
import android.util.Size
import android.view.SurfaceView
import android.view.View
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.Interface.USB_COMMON_COND
import com.hcusbsdk.Interface.USB_CTRL_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_DEVICE_INFO
import com.hcusbsdk.Interface.USB_DEVICE_REG_RES
import com.hcusbsdk.Interface.USB_SYSTEM_DEVICE_INFO
import com.hcusbsdk.Interface.USB_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_THERMOMETRY_CALIBRATION_FILE
import com.hcusbsdk.Interface.USB_USER_LOGIN_INFO
import com.hcusbsdk.Interface.USB_VIDEO_PARAM
import com.hcusbsdk.Interface.USB_FRAME_INFO
import com.hik.f2module.F2StreamCallback
import com.hik.f2module.F2StreamFrame
import com.hik.f2module.F2SessionCloseOutcome
import com.hik.f2module.F2StageResult
import com.hik.f2module.F2UsbModuleApi
import com.hik.f2module.F2UsbModuleHelper
import com.hik.f2module.IFR_INFO
import com.hik.library.player.d
import com.hik.viewer.manager.PreviewManagerII
import com.hik.viewercommon.data.bean.SceneModeBean
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
import hik.common.yyrj.uicommon.widget.FloatTextureView
import kr.auto.titration.mobile.OfficialPreviewBinding
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2PaletteSnapshot
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
        resetStreamSurfaceBinding()
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
    fun activeNativeChannelAndCurrentAppBindingAdoptExactManagerAndJniTupleTraverses() {
        resetPreviewBinding()
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        val firstLifecycle = RecordingLifecycle()
        val secondLifecycle = RecordingLifecycle()
        val manager = PreviewManagerIIAppBinding.installLifecycle(firstLifecycle)
        val delivered = CountDownLatch(1)
        val frames = mutableListOf<F2StreamFrame>()
        try {
            val profile = f3.j().apply { d(12) }
            Z2.a.a.u(profile)
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = "0953060001"))
            PreviewManagerIIAppBinding.bind(manager) {
                frames += it
                delivered.countDown()
            }
            assertTrue(manager.refreshF2ProcessorFromRuntimeProfile())
            setField(manager, "D", RecordingProcessor())
            F2UsbModuleHelper.userId = 6
            F2UsbModuleHelper.channel = 0
            val exactNativeCallback = manager.R()

            val adopted = PreviewManagerIIAppBinding.installLifecycle(secondLifecycle)

            assertSame(manager, adopted)
            assertSame(secondLifecycle, previewManagerLifecycle(manager))
            assertSame(exactNativeCallback, manager.R())
            assertSame(callbackFor(manager), callbackFor(adopted))

            exactNativeCallback.invoke(
                6,
                USB_FRAME_INFO().apply {
                    dwBufSize = 203_720
                    pBuf = ByteArray(203_720)
                    dwWidth = 256
                    dwHeight = 344
                    dwFrameType = 0
                    dwDataType = 0
                    dwStreamType = 103
                    nFrameNum = 129
                },
            )
            PreviewManagerII.g(manager)

            assertTrue(delivered.await(2, TimeUnit.SECONDS))
            assertEquals(1, frames.size)
            assertEquals(6, frames.single().callbackUserId)
            assertEquals(203_720, frames.single().bytes.size)
            assertEquals(103, frames.single().streamType)
            assertEquals(129L, frames.single().frameCounter)
            val diagnostic = manager.streamIngressDiagnostic
            assertEquals("app_handoff", diagnostic.reason)
            assertEquals(1L, diagnostic.mailboxAcceptedCount)
            assertEquals(1L, diagnostic.processorAcceptedCount)
            assertEquals(1L, diagnostic.appHandoffCount)
        } finally {
            F2UsbModuleHelper.userId = -1
            F2UsbModuleHelper.channel = -1
            PreviewManagerIIAppBinding.unbind(manager)
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
        }
    }

    @Test
    fun activeNativeChannelWithoutCurrentAppBindingStillReplacesAndCloses() {
        resetPreviewBinding()
        val first = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        F2UsbModuleHelper.userId = 6
        F2UsbModuleHelper.channel = 0
        try {
            val second = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())

            assertTrue(first !== second)
            assertTrue(booleanField(first, "streamClosed"))
            assertNull(field(first, "C0"))
            assertSame(second, PreviewManagerIIAppBinding.manager())
        } finally {
            F2UsbModuleHelper.userId = -1
            F2UsbModuleHelper.channel = -1
        }
    }

    @Test
    fun currentAppBindingWithoutActiveChannelStillReplacesAndCloses() {
        resetPreviewBinding()
        val first = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        PreviewManagerIIAppBinding.bind(first) { }
        F2UsbModuleHelper.userId = 6
        F2UsbModuleHelper.channel = -1
        try {
            val second = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())

            assertTrue(first !== second)
            assertTrue(booleanField(first, "streamClosed"))
            assertNull(field(first, "C0"))
            assertSame(second, PreviewManagerIIAppBinding.manager())
        } finally {
            F2UsbModuleHelper.userId = -1
            F2UsbModuleHelper.channel = -1
        }
    }

    @Test
    fun terminalCloseStopFailureRestoresExactAppBindingAndApiOwner() {
        resetPreviewBinding()
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        val originalLifecycle = RecordingLifecycle()
        val manager = PreviewManagerIIAppBinding.installLifecycle(originalLifecycle)
        val callback = F2StreamCallback { }
        val api = F2UsbModuleApi.INSTANCE
        val helper = F2UsbModuleHelper.INSTANCE
        val bridge = SessionCloseBridge()
        val retainedProcessor = RecordingProcessor()
        val replacementLifecycle = RecordingLifecycle()
        try {
            val activeProfile = f3.j()
            Z2.a.a.u(activeProfile)
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = "0953060001"))
            PreviewManagerIIAppBinding.bind(manager, callback)
            setField(manager, "D", retainedProcessor)
            setField(manager, "processorProfile", activeProfile)
            setField(manager, "previewGraphInitialized", true)
            originalLifecycle.addObserver(field(manager, "B") as LifecycleObserver)
            setField(api, "activeAppCallback", callback)
            F2UsbModuleHelper.userId = 41
            F2UsbModuleHelper.channel = 1
            JavaInterface.getInstance().configureNativeBridge(bridge)
            helper.installSessionCloseOperationsForTests(
                stopChannel = { _, _ -> false },
                logout = { true },
            )
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = ""))

            val result = api.closeSession()

            assertFalse(result.ok)
            assertEquals(F2SessionCloseOutcome.STREAM_PRESERVED, result.closeOutcome)
            assertTrue(result.summary.contains("session_preserved=true"))
            assertTrue(result.summary.contains("terminal_app_binding_restore=exact_prior_owner"))
            assertEquals(41, helper.activeUserId())
            assertEquals(1, helper.activeChannel())
            assertSame(callback, field(api, "activeAppCallback"))
            assertSame(callback, callbackFor(manager))
            assertFalse(booleanField(manager, "streamClosed"))
            assertSame(
                "failed stop must retain the exact processor even when mutable runtime profile reconstruction is impossible",
                retainedProcessor,
                field(manager, "D"),
            )
            assertTrue(PreviewManagerIIAppBinding.isManagerRetainedForTerminalCloseRetry(manager))

            PreviewManagerIIAppBinding.transferTerminalCloseRetryManagerToExternalOwner()
            assertNull(
                "the dying Activity lifecycle must no longer own the retained native session",
                field(manager, "a"),
            )
            originalLifecycle.destroy()
            assertSame(
                "Activity ON_DESTROY must not release the exact retained processor",
                retainedProcessor,
                field(manager, "D"),
            )
            assertSame(callback, callbackFor(manager))

            val adopted = PreviewManagerIIAppBinding.installLifecycle(replacementLifecycle)
            assertSame(
                "a replacement Activity must adopt the retained owner instead of destroying it",
                manager,
                adopted,
            )
            assertFalse(
                "replacement lifecycle adoption must revoke the old terminal retry ownership",
                PreviewManagerIIAppBinding.isManagerRetainedForTerminalCloseRetry(manager),
            )
            assertSame(replacementLifecycle, previewManagerLifecycle(manager))
            assertSame(callback, callbackFor(manager))

            helper.installSessionCloseOperationsForTests(
                stopChannel = { _, _ -> true },
                logout = { true },
            )
            val retried = api.closeSession()
            assertTrue(retried.ok)
            assertEquals(F2SessionCloseOutcome.CLOSED, retried.closeOutcome)
            assertFalse(PreviewManagerIIAppBinding.isManagerRetainedForTerminalCloseRetry(manager))
            val nextManager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
            assertTrue("after close commits, a later lifecycle gets a fresh owner", nextManager !== manager)
            assertEquals(listOf(0, 1, 0), bridge.thermalStreamControlValues)
        } finally {
            helper.installSessionCloseOperationsForTests(
                stopChannel = { _, _ -> true },
                logout = { true },
            )
            api.closeSession()
            helper.installSessionCloseOperationsForTests(null, null)
            F2UsbModuleHelper.userId = -1
            F2UsbModuleHelper.channel = -1
            setField(api, "activeAppCallback", null)
            setField(api, "activeInvalidPacketSizeTimeout", null)
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
        }
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
        assertTrue(gBody.contains("if (processor == null)"))
        assertTrue(gBody.contains("lastStreamProcessingFailure = \"preview_processor_unavailable\""))
        assertFalse(gBody.contains("g3.b.a.a("))
        assertTrue(gBody.indexOf("processor.j(X, new K2.f(this), c0, h0, new K2.g(this))") < gBody.indexOf("processor.d(packet)"))
        assertTrue(gBody.indexOf("processor.d(packet)") < gBody.indexOf("handOffOfficialFrame(streamInfo, frame, processorBucket)"))
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

    @Test
    fun lifecycleInstallNeverHoldsBindingMonitorWhileWaitingForManagerLifecycleLock() {
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        PreviewManagerIIAppBinding.bind(manager) { }
        F2UsbModuleHelper.userId = 6
        F2UsbModuleHelper.channel = 0
        val lifecycleLock = PreviewManagerII::class.java.getDeclaredField("lifecycleLock")
            .apply { isAccessible = true }
            .get(manager)
        val managerLockHeld = CountDownLatch(1)
        val probeBindingMonitor = CountDownLatch(1)
        val bindingMonitorAcquired = CountDownLatch(1)
        val releaseManagerLock = CountDownLatch(1)
        val installDone = CountDownLatch(1)
        val lockHolder = Thread {
            synchronized(lifecycleLock) {
                managerLockHeld.countDown()
                assertTrue(probeBindingMonitor.await(2, TimeUnit.SECONDS))
                synchronized(PreviewManagerIIAppBinding::class.java) {
                    bindingMonitorAcquired.countDown()
                }
                assertTrue(releaseManagerLock.await(2, TimeUnit.SECONDS))
            }
        }.apply { isDaemon = true }
        val installer = Thread {
            PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
            installDone.countDown()
        }.apply { isDaemon = true }
        try {
            lockHolder.start()
            assertTrue(managerLockHeld.await(2, TimeUnit.SECONDS))
            installer.start()
            val blockedDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2)
            while (installer.state != Thread.State.BLOCKED && System.nanoTime() < blockedDeadline) {
                Thread.yield()
            }
            assertEquals(
                "active-owner lifecycle adoption should be waiting on the held manager lock",
                Thread.State.BLOCKED,
                installer.state,
            )

            probeBindingMonitor.countDown()
            assertTrue(
                "AppBinding monitor must remain acquirable while adoption waits for lifecycleLock",
                bindingMonitorAcquired.await(2, TimeUnit.SECONDS),
            )
            releaseManagerLock.countDown()
            assertTrue(installDone.await(2, TimeUnit.SECONDS))
        } finally {
            probeBindingMonitor.countDown()
            releaseManagerLock.countDown()
            F2UsbModuleHelper.userId = -1
            F2UsbModuleHelper.channel = -1
            PreviewManagerIIAppBinding.unbind(manager)
        }
    }

    @Test
    fun lifecycleObserverRegistrationCanReenterBindingWithoutEitherInternalLockHeld() {
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(RecordingLifecycle())
        PreviewManagerIIAppBinding.bind(manager) { }
        F2UsbModuleHelper.userId = 6
        F2UsbModuleHelper.channel = 0
        setField(manager, "previewGraphInitialized", true)
        val lifecycleLock = PreviewManagerII::class.java.getDeclaredField("lifecycleLock")
            .apply { isAccessible = true }
            .get(manager)
        val reentryCount = AtomicInteger(0)
        val replacement = object : Lifecycle() {
            override val currentState: State
                get() = State.CREATED

            override fun addObserver(observer: LifecycleObserver) {
                assertFalse(Thread.holdsLock(lifecycleLock))
                assertFalse(Thread.holdsLock(PreviewManagerIIAppBinding::class.java))
                assertSame(manager, PreviewManagerIIAppBinding.manager())
                reentryCount.incrementAndGet()
            }

            override fun removeObserver(observer: LifecycleObserver) = Unit
        }
        try {
            assertSame(manager, PreviewManagerIIAppBinding.installLifecycle(replacement))
            assertEquals(1, reentryCount.get())
            assertSame(replacement, previewManagerLifecycle(manager))
        } finally {
            F2UsbModuleHelper.userId = -1
            F2UsbModuleHelper.channel = -1
            PreviewManagerIIAppBinding.unbind(manager)
        }
    }

    @Test
    fun officialFrameSnapshotIsCopiedAfterPacketProcessorCompletion() {
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        PreviewManagerIIAppBinding.bind(manager) { }
        val src = byteArrayOf(0x11, 0x22)
        val raw = byteArrayOf(0x33, 0x44)
        val info = PreviewInfoDataBean(
            byteArrSrc = src,
            byteArrRawData = raw,
        )

        PreviewManagerIIAppBinding.afterOfficialG(
            manager,
            7,
            44L,
            256,
            192,
            0,
            0,
            103,
            ByteArray(8),
            256,
            192,
            PreviewStreamInfo(info, null),
            false,
            "processor",
        )
        src[0] = 0x55
        raw[0] = 0x66

        val snapshot = PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 44L)
        assertNotNull(snapshot)
        assertEquals(0x11, snapshot!!.previewStreamInfo.getPreviewInfoData().getByteArrSrc()[0].toInt())
        assertEquals(0x33, snapshot.previewStreamInfo.getPreviewInfoData().getByteArrRawData()[0].toInt())
    }

    @Test
    fun paletteSnapshotUsesActualQPresentAndActualNullWithoutFabricatingAbsence() {
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        PreviewManagerIIAppBinding.bind(manager) { }

        handOffFrame(manager, 51L, 151)
        val absent = PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 51L)
        assertNotNull(absent)
        assertFalse(absent!!.paletteSnapshot.isPresent)
        assertEquals(
            OfficialF2PaletteSnapshot.AbsenceProof.PREVIEW_MANAGER_Q_RETURNED_NULL,
            absent.paletteSnapshot.absenceProof,
        )
        assertEquals("preview_manager_Q_returned_actual_null", absent.paletteSnapshotSource)

        val present = OfficialF2PaletteSnapshot.present(
            1,
            0,
            null,
            14,
            42f,
            -10f,
            7,
            4,
            35f,
            -25f,
            100,
            10,
            90,
            20,
            80,
            30,
            70,
            40,
        )
        setField(manager, "N", present)
        setField(manager, "paletteSnapshotFailure", null)
        handOffFrame(manager, 52L, 152)
        val capturedPresent = PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 52L)
        assertNotNull(capturedPresent)
        assertSame(present, capturedPresent!!.paletteSnapshot)
        assertEquals("preview_manager_Q_present_snapshot", capturedPresent.paletteSnapshotSource)

        setField(manager, "N", null)
        setField(manager, "paletteSnapshotFailure", "incomplete_palette_test")
        handOffFrame(manager, 53L, 153)
        val incomplete = PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 53L)
        assertNotNull(incomplete)
        assertNull("an incomplete reconstruction must not be mislabeled as actual Q null", incomplete!!.paletteSnapshot)
        assertTrue(incomplete.paletteSnapshotSource.contains("unavailable_fail_closed"))
        assertTrue(runCatching {
            OfficialF2MeasurementCoordinator.requireProvedPaletteSnapshot(incomplete.paletteSnapshot)
        }.isFailure)
    }

    @Test
    fun offlineCallbackIsScopedToManagerGenerationAndRequestedFrameStamp() {
        resetPreviewBinding()
        val firstManager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        PreviewManagerIIAppBinding.bind(firstManager) { }
        val firstInfo = previewInfoWithStamp(211)
        handOffFrame(firstManager, 61L, 211)
        val firstEpoch = firstManager.currentProcessingEpoch()
        val firstGeneration = managerGeneration(firstManager)
        assertTrue(
            PreviewManagerIIAppBinding.onOfflineCallback(
                firstManager,
                firstInfo,
                211,
                firstEpoch,
                firstGeneration,
            ),
        )
        val firstCapture = PreviewManagerIIAppBinding.latestOfficialProcessedFrameWithOfflineCaptureForTests(
            firstManager,
            61L,
            720,
            960,
        ) { d(211, jpeg(0x11)) }
        assertNotNull(firstCapture)
        assertEquals(211, firstCapture!!.offlineFrameNumStamp)
        assertEquals(211, firstCapture.rendererSelectedFrameNumStamp)
        assertEquals(
            OfficialProcessedF2Frame.RendererTimestampProvenance.EXACT,
            firstCapture.rendererTimestampProvenance,
        )

        val secondManager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        PreviewManagerIIAppBinding.bind(secondManager) { }
        handOffFrame(secondManager, 62L, 211)
        assertFalse(
            "late callback from replaced manager must be rejected",
            PreviewManagerIIAppBinding.onOfflineCallback(
                firstManager,
                firstInfo,
                211,
                firstEpoch,
                firstGeneration,
            ),
        )
        val rendererCalls = AtomicInteger(0)
        val noCrossSessionCapture =
            PreviewManagerIIAppBinding.latestOfficialProcessedFrameWithOfflineCaptureForTests(
                secondManager,
                62L,
                720,
                960,
            ) {
                rendererCalls.incrementAndGet()
                d(211, jpeg(0x22))
            }
        assertNotNull(noCrossSessionCapture)
        assertTrue(noCrossSessionCapture!!.rendererJpegSource.contains("missing_for_requested_frame"))
        assertEquals("renderer must not run without an associated callback", 0, rendererCalls.get())

        assertTrue(onCurrentOfflineCallback(secondManager, previewInfoWithStamp(211), 211))
        val secondCapture = PreviewManagerIIAppBinding.latestOfficialProcessedFrameWithOfflineCaptureForTests(
            secondManager,
            62L,
            720,
            960,
        ) { d(211, jpeg(0x33)) }
        assertNotNull(secondCapture)
        assertEquals(211, secondCapture!!.rendererSelectedFrameNumStamp)

        PreviewManagerIIAppBinding.unbind(secondManager)
        PreviewManagerIIAppBinding.bind(secondManager) { }
        handOffFrame(secondManager, 63L, 211)
        val postRebindRendererCalls = AtomicInteger(0)
        val postRebind = PreviewManagerIIAppBinding.latestOfficialProcessedFrameWithOfflineCaptureForTests(
            secondManager,
            63L,
            720,
            960,
        ) {
            postRebindRendererCalls.incrementAndGet()
            d(211, jpeg(0x44))
        }
        assertNotNull(postRebind)
        assertTrue(postRebind!!.rendererJpegSource.contains("missing_for_requested_frame"))
        assertEquals("unbind/rebind must clear the prior generation callback", 0, postRebindRendererCalls.get())
    }

    @Test
    fun callbackArrivingBeforeFrameIsAssociatedOnlyWhenItsExactStampArrives() {
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        PreviewManagerIIAppBinding.bind(manager) { }

        assertTrue(onCurrentOfflineCallback(manager, previewInfoWithStamp(312), 312))
        handOffFrame(manager, 71L, 313)
        val wrongFrameCalls = AtomicInteger(0)
        val wrongFrame = PreviewManagerIIAppBinding.latestOfficialProcessedFrameWithOfflineCaptureForTests(
            manager,
            71L,
            720,
            960,
        ) {
            wrongFrameCalls.incrementAndGet()
            d(313, jpeg(0x55))
        }
        assertNotNull(wrongFrame)
        assertTrue(wrongFrame!!.rendererJpegSource.contains("missing_for_requested_frame"))
        assertEquals(0, wrongFrameCalls.get())

        handOffFrame(manager, 72L, 312)
        val exactFrame = PreviewManagerIIAppBinding.latestOfficialProcessedFrameWithOfflineCaptureForTests(
            manager,
            72L,
            720,
            960,
        ) { d(312, jpeg(0x66)) }
        assertNotNull(exactFrame)
        assertEquals(312, exactFrame!!.offlineFrameNumStamp)
        assertEquals(
            OfficialProcessedF2Frame.RendererTimestampProvenance.EXACT,
            exactFrame.rendererTimestampProvenance,
        )

        val nearestFrame = PreviewManagerIIAppBinding.latestOfficialProcessedFrameWithOfflineCaptureForTests(
            manager,
            72L,
            720,
            960,
        ) { index ->
            if (index == 0) d(309, jpeg(0x67)) else d(400 + index, byteArrayOf(0x01, 0x02))
        }
        assertNotNull(nearestFrame)
        assertEquals(309, nearestFrame!!.rendererSelectedFrameNumStamp)
        assertEquals(
            OfficialProcessedF2Frame.RendererTimestampProvenance.NEAREST,
            nearestFrame.rendererTimestampProvenance,
        )
    }

    @Test
    fun hostMeasurementUsesExistingPreviewGraphAndTerminalTeardownChain() {
        val streamSource = source("app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt")
        val requestBody = streamSource.substringAfter("fun requestLatestOfficialScalarMeasurement")
            .substringBefore("fun latestOfficialScalarMeasurement")
        assertFalse(requestBody.contains("new PreviewManagerII"))
        assertFalse(requestBody.contains("PreviewManagerII("))
        assertTrue(requestBody.contains("currentOfficialPreviewSurface()"))
        assertTrue(requestBody.contains("isOfficialPreviewSurfaceCurrent("))
        assertTrue(requestBody.contains("latestOfficialProcessedFrameWithOfflineCapture("))

        val scheduleBody = streamSource.substringAfter("fun scheduleLatestOfficialScalarMeasurement")
            .substringBefore("fun requestLatestOfficialScalarMeasurement")
        assertTrue(scheduleBody.contains("officialScalarMeasurementScheduler.schedule"))
        assertTrue(scheduleBody.contains("requestLatestOfficialScalarMeasurementInternal("))

        val shutdownBody = streamSource.substringAfter("fun shutdownOfficialPreviewSession()")
            .substringBefore("private fun closeBoundOfficialPreviewLocked()")
        assertTrue(shutdownBody.contains("closeBoundOfficialPreviewLocked()"))
        assertTrue(shutdownBody.contains("resetOfficialMeasurementLifecycle()"))
        assertTrue(shutdownBody.contains("f2Api.closeSession()"))
        assertFalse(shutdownBody.contains("f2Helper.closeSession()"))
        assertTrue(
            shutdownBody.indexOf("f2Api.closeSession()") <
                shutdownBody.indexOf("closeBoundOfficialPreviewLocked()"),
        )
        assertTrue(
            shutdownBody.contains(
                "if (closeResult.closeOutcome == F2SessionCloseOutcome.STREAM_PRESERVED)",
            ),
        )
        assertTrue(
            shutdownBody.indexOf("return closeResult") <
                shutdownBody.indexOf("closeBoundOfficialPreviewLocked()"),
        )

        val resetBody = streamSource.substringAfter("private fun resetOfficialMeasurementLifecycle()")
            .substringBefore("internal fun officialF2DataDirectory")
        assertTrue(resetBody.contains("officialScalarMeasurementScheduler.resetLifecycle()"))
        assertTrue(resetBody.contains("OfficialF2MeasurementCoordinator.resetLifecycle()"))

        val ensureStreamingBody = streamSource.substringAfter("fun ensureStreaming(")
            .substringBefore("fun peekActiveStatus(")
        assertTrue(ensureStreamingBody.contains("resetOfficialMeasurementLifecycle()"))

        val hostSource = source("app/src/main/java/kr/auto/titration/mobile/OfficialPreviewHost.kt")
        val destroy = hostSource.indexOf("fun destroy()")
        val terminal = hostSource.indexOf("shutdownOfficialPreviewSessionWithRetryRegistration(", destroy)
        assertTrue(terminal > destroy)

        val bindingSource = source("app/src/main/java/kr/auto/titration/mobile/thermal/PreviewManagerIIAppBinding.java")
        val previewHandoffBody = bindingSource.substringAfter("    public static void afterOfficialG(")
            .substringBefore("    private static PaletteCapture capturePalette")
        assertFalse(previewHandoffBody.contains(".W("))
        assertFalse(previewHandoffBody.contains("Thread.sleep"))
        assertFalse(previewHandoffBody.contains("acquireThermometryCalibrationFileOnce"))
        assertFalse(previewHandoffBody.contains("renderAndMeasure"))
        assertFalse(previewHandoffBody.contains("USB_Get"))
        assertTrue(previewHandoffBody.contains("callback.onFrame"))

        val managerSource = source("app/src/main/java/com/hik/viewer/manager/PreviewManagerII.java")
        assertTrue(managerSource.contains("PreviewManagerIIAppBinding.onOfflineCallback("))
        assertTrue(managerSource.contains("processingEpoch"))
        assertTrue(managerSource.contains("lifecycleGeneration"))
    }

    @Test
    fun surfaceLifecycleAndFramePublicationUseOneWayLocksAndGenerationScopedSnapshots() {
        val streamSource = source("app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt")
        val surfaceLifecycleBody = streamSource
            .substringAfter("fun bindOfficialPreviewSurface(surfaceView: SurfaceView)")
            .substringBefore("fun ensureStreaming(")
        assertTrue(surfaceLifecycleBody.contains("synchronized(previewSurfaceLifecycleLock)"))
        assertFalse(
            "surface teardown must not hold the AppBinding class monitor while calling unbind",
            surfaceLifecycleBody.contains("synchronized(PreviewManagerIIAppBinding::class.java)"),
        )

        val captureBody = streamSource.substringAfter("private fun captureOfficialF2Frame(")
            .substringBefore("@Synchronized\n    internal fun onOfficialPreviewSuccess")
        assertTrue(captureBody.contains("lifecycleGeneration = frame.lifecycleGeneration"))
        assertTrue(captureBody.contains("synchronized(PreviewManagerIIAppBinding::class.java)"))
        assertTrue(captureBody.contains("isCurrentLifecycleGeneration(frame.lifecycleGeneration)"))
        assertTrue(
            captureBody.indexOf("isCurrentLifecycleGeneration(frame.lifecycleGeneration)")
                < captureBody.indexOf("latestFrameSnapshot = snapshot"),
        )

        val snapshotReaderBody = streamSource.substringAfter("private fun currentFrameSnapshotOrNull()")
            .substringBefore("@Synchronized\n    internal fun onOfficialPreviewSuccess")
        assertTrue(snapshotReaderBody.contains("isCurrentLifecycleGeneration(snapshot.lifecycleGeneration)"))
        assertTrue(snapshotReaderBody.contains("latestFrameSnapshot = null"))
        for ((reader, nextReader) in listOf(
            "fun ensureStreaming(" to "fun peekActiveStatus(",
            "fun peekActiveStatus(" to "fun latestRawFrameSummary(",
            "fun latestRawFrameSummary(" to "fun rotatePreviewClockwise(",
            "fun scheduleLatestOfficialScalarMeasurement(" to "fun requestLatestOfficialScalarMeasurement(",
            "private fun requestLatestOfficialScalarMeasurementInternal(" to "fun latestOfficialScalarMeasurement(",
        )) {
            val readerBody = streamSource.substringAfter(reader).substringBefore(nextReader)
            assertTrue(
                "$reader must reject stale lifecycle snapshots",
                readerBody.contains("currentFrameSnapshotOrNull()"),
            )
        }
        for ((reader, nextReader) in listOf(
            "fun ensureStreaming(" to "fun peekActiveStatus(",
            "fun peekActiveStatus(" to "fun latestRawFrameSummary(",
        )) {
            val readerBody = streamSource.substringAfter(reader).substringBefore(nextReader)
            assertTrue(readerBody.contains("clearFrameSnapshotIfSame(snapshot)"))
            assertTrue(readerBody.contains("currentSnapshot = currentFrameSnapshotOrNull()"))
        }
        val compareAndClearBody = streamSource.substringAfter("private fun clearFrameSnapshotIfSame(")
            .substringBefore("@Synchronized\n    internal fun onOfficialPreviewSuccess")
        assertTrue(compareAndClearBody.contains("latestFrameSnapshot !== snapshot"))
        assertTrue(compareAndClearBody.contains("latestFrameSnapshot = null"))

        val bindingSource = source("app/src/main/java/kr/auto/titration/mobile/thermal/PreviewManagerIIAppBinding.java")
        assertTrue(bindingSource.contains("private static final Object lifecycleOperationLock"))
        val bindBody = bindingSource.substringAfter("public static void bind(")
            .substringBefore("public static void unbind(")
        assertTrue(bindBody.contains("synchronized (lifecycleOperationLock)"))
        assertTrue(
            bindBody.indexOf("synchronized (PreviewManagerIIAppBinding.class)")
                < bindBody.indexOf("current.openPreviewCallback();"),
        )
        assertTrue(
            bindBody.indexOf("current.openPreviewCallback();")
                < bindBody.lastIndexOf("synchronized (PreviewManagerIIAppBinding.class)"),
        )
    }

    @Test
    fun replacementHostClaimWaitsForAdmittedRetryAndCancelsItsGeneration() {
        resetPreviewBinding()
        val retainedManager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        PreviewManagerIIAppBinding.bind(retainedManager) { }
        PreviewManagerIIAppBinding.retainManagerForTerminalCloseRetry(retainedManager)
        val failed = F2StageResult(
            false,
            "native stream preserved",
            F2SessionCloseOutcome.STREAM_PRESERVED,
        )
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val attemptDone = CountDownLatch(1)
        val claimDone = CountDownLatch(1)
        try {
            Thread {
                HikmicroJnaMini2Stream.shutdownOfficialPreviewSessionWithRetryRegistration(
                    shutdown = {
                        entered.countDown()
                        assertTrue(release.await(2, TimeUnit.SECONDS))
                        failed
                    },
                )
                attemptDone.countDown()
            }.start()
            assertTrue(entered.await(2, TimeUnit.SECONDS))

            Thread {
                HikmicroJnaMini2Stream.claimPendingTerminalShutdownRetryForReplacementHost()
                claimDone.countDown()
            }.start()
            assertFalse(
                "replacement claim must wait while a retry owns shutdown admission",
                claimDone.await(100, TimeUnit.MILLISECONDS),
            )

            release.countDown()
            assertTrue(attemptDone.await(2, TimeUnit.SECONDS))
            assertTrue(claimDone.await(2, TimeUnit.SECONDS))
            assertFalse(HikmicroJnaMini2Stream.isTerminalShutdownRetryPending())
            val unexpectedShutdowns = AtomicInteger(0)
            assertNull(
                "a cancelled retry generation must never close a replacement session",
                HikmicroJnaMini2Stream.runTerminalShutdownRetryAttempt {
                    unexpectedShutdowns.incrementAndGet()
                    F2StageResult(true, "unexpected", F2SessionCloseOutcome.CLOSED)
                },
            )
            assertEquals(0, unexpectedShutdowns.get())
        } finally {
            release.countDown()
            HikmicroJnaMini2Stream.claimPendingTerminalShutdownRetryForReplacementHost()
        }
    }

    @Test
    fun appHandoffDiagnosticRunsOutsideBindingMonitorAndConcurrentCloseCompletes() {
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        PreviewManagerIIAppBinding.bind(manager) { }
        val processingEpoch = manager.currentProcessingEpoch()
        val start = CountDownLatch(1)
        val handoffDone = CountDownLatch(1)
        val closeDone = CountDownLatch(1)

        val handoffThread = Thread {
            start.await()
            repeat(100) {
                PreviewManagerIIAppBinding.afterOfficialG(
                    manager,
                    processingEpoch,
                    6,
                    129L,
                    192,
                    256,
                    0,
                    0,
                    103,
                    ByteArray(203_720),
                    192,
                    256,
                    PreviewStreamInfo(PreviewInfoDataBean(), null),
                    false,
                    "processor",
                )
            }
            handoffDone.countDown()
        }
        val closeThread = Thread {
            start.await()
            manager.closePreviewCallback()
            closeDone.countDown()
        }
        handoffThread.start()
        closeThread.start()
        start.countDown()

        assertTrue("handoff must not deadlock against lifecycle close", handoffDone.await(2, TimeUnit.SECONDS))
        assertTrue("lifecycle close must not deadlock against app handoff", closeDone.await(2, TimeUnit.SECONDS))

        val source = source("app/src/main/java/kr/auto/titration/mobile/thermal/PreviewManagerIIAppBinding.java")
        val body = source.substringAfter("public static void afterOfficialG(\n            PreviewManagerII manager,\n            long processingEpoch,")
            .substringBefore("public static synchronized boolean isCurrentLifecycleGeneration")
        val firstBindingMonitor = body.indexOf("synchronized (PreviewManagerIIAppBinding.class)")
        val appHandoffDiagnostic = body.indexOf("manager.recordAppHandoff(")
        val secondBindingMonitor = body.indexOf(
            "synchronized (PreviewManagerIIAppBinding.class)",
            firstBindingMonitor + 1,
        )
        assertTrue(
            "manager diagnostic must be recorded only after leaving the AppBinding class monitor",
            firstBindingMonitor in 0 until appHandoffDiagnostic &&
                appHandoffDiagnostic in 0 until secondBindingMonitor,
        )
    }

    @Test
    fun replacementHostKeepsLoginOnlyRetryAndReceivesRebindCompletion() {
        resetPreviewBinding()
        val failed = F2StageResult(
            false,
            "stream stopped but logout retained",
            F2SessionCloseOutcome.STREAM_STOPPED_LOGIN_RETAINED,
        )
        val completionCount = AtomicInteger(0)
        try {
            val initial = HikmicroJnaMini2Stream.shutdownOfficialPreviewSessionWithRetryRegistration(
                shutdown = { failed },
            )
            assertEquals(F2SessionCloseOutcome.STREAM_STOPPED_LOGIN_RETAINED, initial.closeOutcome)

            assertFalse(
                "a replacement host cannot adopt or cancel a login-only native owner",
                HikmicroJnaMini2Stream.claimPendingTerminalShutdownRetryForReplacementHost {
                    completionCount.incrementAndGet()
                },
            )
            assertTrue(HikmicroJnaMini2Stream.isTerminalShutdownRetryPending())

            val closed = HikmicroJnaMini2Stream.runTerminalShutdownRetryAttempt {
                F2StageResult(true, "closed", F2SessionCloseOutcome.CLOSED)
            }
            assertEquals(F2SessionCloseOutcome.CLOSED, closed?.closeOutcome)
            assertFalse(HikmicroJnaMini2Stream.isTerminalShutdownRetryPending())
            assertEquals(1, completionCount.get())
        } finally {
            HikmicroJnaMini2Stream.claimPendingTerminalShutdownRetryForReplacementHost()
        }
    }

    @Test
    fun coalescedRetryRefreshesOwnerWhenPreservedStreamBecomesLoginOnly() {
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        PreviewManagerIIAppBinding.bind(manager) { }
        PreviewManagerIIAppBinding.retainManagerForTerminalCloseRetry(manager)
        val preserved = F2StageResult(
            false,
            "native stream preserved",
            F2SessionCloseOutcome.STREAM_PRESERVED,
        )
        val loginOnly = F2StageResult(
            false,
            "stream stopped but logout retained",
            F2SessionCloseOutcome.STREAM_STOPPED_LOGIN_RETAINED,
        )
        val completionCount = AtomicInteger(0)
        try {
            HikmicroJnaMini2Stream.shutdownOfficialPreviewSessionWithRetryRegistration(
                shutdown = { preserved },
            )
            assertTrue(HikmicroJnaMini2Stream.isTerminalShutdownRetryPending())

            HikmicroJnaMini2Stream.shutdownOfficialPreviewSessionWithRetryRegistration(
                shutdown = {
                    PreviewManagerIIAppBinding.releaseManagerFromTerminalCloseRetry(manager)
                    loginOnly
                },
            )

            assertFalse(
                "login-only cleanup cannot be cancelled as though a stream manager remained",
                HikmicroJnaMini2Stream.claimPendingTerminalShutdownRetryForReplacementHost {
                    completionCount.incrementAndGet()
                },
            )
            val closed = HikmicroJnaMini2Stream.runTerminalShutdownRetryAttempt {
                F2StageResult(true, "closed", F2SessionCloseOutcome.CLOSED)
            }
            assertEquals(F2SessionCloseOutcome.CLOSED, closed?.closeOutcome)
            assertEquals(1, completionCount.get())
        } finally {
            PreviewManagerIIAppBinding.releaseManagerFromTerminalCloseRetry(manager)
            HikmicroJnaMini2Stream.claimPendingTerminalShutdownRetryForReplacementHost()
        }
    }

    @Test
    fun passiveSurfaceDestroyCreatePreservesActiveCallbackGenerationAndProcessor() {
        resetStreamSurfaceBinding()
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        PreviewManagerIIAppBinding.bind(manager) { }
        val processor = RecordingProcessor()
        setField(manager, "D", processor)
        setField(manager, "previewGraphInitialized", true)
        val schedulerBeforeDestroy = field(manager, "x0")
        val callbackSchedulerBeforeDestroy = field(manager, "C")
        val firstRenderer = RecordingRenderer()
        val secondRenderer = RecordingRenderer()
        val rendererIndex = AtomicInteger(0)
        setField(manager, "rendererFactoryOverride", object : X2.b {
            override fun a(surfaceView: SurfaceView): V2.f =
                if (rendererIndex.getAndIncrement() == 0) firstRenderer else secondRenderer
            override fun b(surfaceView: SurfaceView): V2.f =
                if (rendererIndex.getAndIncrement() == 0) firstRenderer else secondRenderer
            override fun c(surfaceView: SurfaceView): V2.f =
                if (rendererIndex.getAndIncrement() == 0) firstRenderer else secondRenderer
        })
        val firstBinding = officialPreviewBinding()
        val secondBinding = officialPreviewBinding()

        HikmicroJnaMini2Stream.bindOfficialPreviewSurface(firstBinding)
        val generationBeforeDestroy = managerGeneration(manager)
        val callbackBeforeDestroy = callbackFor(manager)
        val nativeCallbackBeforeDestroy = field(manager, "C0")
        val epochBeforeDestroy = manager.currentProcessingEpoch()
        val rendererEpochBeforeDestroy = manager.currentRendererEpoch()
        assertSame(firstRenderer, field(manager, "E"))
        firstRenderer.calls.clear()

        HikmicroJnaMini2Stream.unbindOfficialPreviewSurface(firstBinding.selectedSurface)

        assertSame(manager, streamOfficialPreviewManager())
        assertFalse(streamOfficialPreviewSurfaceAttached())
        assertEquals(listOf("stop", "c", "release"), firstRenderer.calls)
        assertNull(field(manager, "E"))
        assertFalse("passive surface destroy must not close the active stream callback", booleanField(manager, "streamClosed"))
        assertSame(callbackBeforeDestroy, callbackFor(manager))
        assertEquals(generationBeforeDestroy, managerGeneration(manager))
        assertSame(processor, field(manager, "D"))
        assertSame(nativeCallbackBeforeDestroy, field(manager, "C0"))
        assertSame(schedulerBeforeDestroy, field(manager, "x0"))
        assertSame(callbackSchedulerBeforeDestroy, field(manager, "C"))
        assertEquals(epochBeforeDestroy, manager.currentProcessingEpoch())
        assertTrue(manager.currentRendererEpoch() > rendererEpochBeforeDestroy)
        assertFalse(manager.isOfficialRendererEpochCurrent(rendererEpochBeforeDestroy))

        HikmicroJnaMini2Stream.bindOfficialPreviewSurface(secondBinding)
        val reboundRendererEpoch = manager.currentRendererEpoch()
        assertTrue(streamOfficialPreviewSurfaceAttached())
        assertSame(secondRenderer, field(manager, "E"))
        assertTrue(reboundRendererEpoch > rendererEpochBeforeDestroy)
        assertTrue(manager.isOfficialRendererEpochCurrent(reboundRendererEpoch))
        assertEquals(2, rendererIndex.get())
        assertSame(callbackBeforeDestroy, callbackFor(manager))
        assertEquals(generationBeforeDestroy, managerGeneration(manager))
        assertSame(processor, field(manager, "D"))
        assertSame(nativeCallbackBeforeDestroy, field(manager, "C0"))
        assertSame(schedulerBeforeDestroy, field(manager, "x0"))
        assertSame(callbackSchedulerBeforeDestroy, field(manager, "C"))
        assertEquals(epochBeforeDestroy, manager.currentProcessingEpoch())
        secondRenderer.calls.clear()

        HikmicroJnaMini2Stream.bindOfficialPreviewSurface(secondBinding)
        HikmicroJnaMini2Stream.unbindOfficialPreviewSurface(firstBinding.selectedSurface)
        assertTrue(
            "a late surfaceDestroyed callback from the old Activity must not detach the new renderer",
            streamOfficialPreviewSurfaceAttached(),
        )
        assertSame(secondRenderer, field(manager, "E"))
        assertTrue(secondRenderer.calls.isEmpty())
        HikmicroJnaMini2Stream.unbindOfficialPreviewSurface(secondBinding.selectedSurface)
        HikmicroJnaMini2Stream.unbindOfficialPreviewSurface(secondBinding.selectedSurface)
        assertEquals("repeated create while attached must be idempotent", 2, rendererIndex.get())
        assertEquals(listOf("stop", "c", "release"), secondRenderer.calls)
        assertFalse("repeated destroy must be idempotent", streamOfficialPreviewSurfaceAttached())
        assertEquals(generationBeforeDestroy, managerGeneration(manager))
    }

    @Test
    fun malformedOptionalTemperatureMetadataCannotSuppressBaseFramePublication() {
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        val callbackResult = AtomicReference<Boolean>()
        val capture = HikmicroJnaMini2Stream::class.java.getDeclaredMethod(
            "captureOfficialF2Frame",
            F2StreamFrame::class.java,
        ).apply { isAccessible = true }
        PreviewManagerIIAppBinding.bind(manager) { frame ->
            callbackResult.set(capture.invoke(HikmicroJnaMini2Stream, frame) as Boolean)
        }
        val invalidMetadata = IFR_INFO.IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO().apply {
            enumTempUnit = 0
            fMinTmp = 30f
            fAvrTmp = 20f
            fMaxTmp = 10f
        }

        PreviewManagerIIAppBinding.afterOfficialG(
            manager,
            manager.currentProcessingEpoch(),
            6,
            129L,
            256,
            344,
            0,
            0,
            103,
            ByteArray(203_720),
            192,
            256,
            PreviewStreamInfo(PreviewInfoDataBean(), h3.c(invalidMetadata)),
            false,
            "processor",
        )

        assertEquals(true, callbackResult.get())
        val latestField = HikmicroJnaMini2Stream::class.java.getDeclaredField("latestFrameSnapshot")
            .apply { isAccessible = true }
        val latest = latestField.get(null)
        assertNotNull(latest)
        assertEquals(129L, field(latest!!, "frameCounter"))
        assertNull(field(latest, "deviceTemperatureSummary"))
        latestField.set(null, null)
    }

    @Test
    fun pausedOldEpochFrameCannotRenderOrPublishAfterFullTeardownAndRebind() {
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        val oldCallbackCount = AtomicInteger(0)
        PreviewManagerIIAppBinding.bind(manager) { oldCallbackCount.incrementAndGet() }
        val enteredProcessor = CountDownLatch(1)
        val releaseProcessor = CountDownLatch(1)
        val oldProcessor = BlockingProcessor(enteredProcessor, releaseProcessor)
        val oldRenderer = RecordingRenderer()
        setField(manager, "D", oldProcessor)
        setField(manager, "E", oldRenderer)

        val processingThread = Thread {
            invokeOfficialG(manager, byteArrayOf(0x31, 0x32, 0x33))
        }
        processingThread.start()
        assertTrue("old frame must pause inside the real processor path", enteredProcessor.await(2, TimeUnit.SECONDS))

        PreviewManagerIIAppBinding.unbind(manager)
        val newCallbackCount = AtomicInteger(0)
        PreviewManagerIIAppBinding.bind(manager) { newCallbackCount.incrementAndGet() }
        val newProcessor = RecordingProcessor()
        val newRenderer = RecordingRenderer()
        setField(manager, "D", newProcessor)
        setField(manager, "E", newRenderer)
        val newGeneration = managerGeneration(manager)

        releaseProcessor.countDown()
        processingThread.join(2_000)

        assertFalse("paused processor thread must finish after release", processingThread.isAlive)
        assertEquals(0, oldCallbackCount.get())
        assertEquals(0, newCallbackCount.get())
        assertTrue(newRenderer.calls.none { it == "h" || it == "j" })
        assertNull(PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 0L))
        assertEquals(newGeneration, managerGeneration(manager))
        assertSame(newProcessor, field(manager, "D"))
        assertSame(newRenderer, field(manager, "E"))
    }

    @Test
    fun staleSnapshotCleanupCannotEraseANewerPublishedSnapshot() {
        val streamClass = HikmicroJnaMini2Stream::class.java
        val snapshotClass = streamClass.declaredClasses.single { it.simpleName == "StreamFrameSnapshot" }
        val constructor = snapshotClass.declaredConstructors
            .filterNot { constructor ->
                constructor.parameterTypes.any { it.name == "kotlin.jvm.internal.DefaultConstructorMarker" }
            }
            .minBy { it.parameterCount }
            .apply { isAccessible = true }
        fun snapshot(): Any {
            val arguments = arrayOfNulls<Any>(constructor.parameterCount)
            constructor.parameterTypes.forEachIndexed { index, type ->
                arguments[index] = when {
                    type == java.lang.Long.TYPE -> 1L
                    type == java.lang.Integer.TYPE -> 1
                    type == String::class.java -> ""
                    type == IntArray::class.java -> null
                    type.name == "java.lang.Double" -> null
                    else -> null
                }
            }
            return constructor.newInstance(*arguments)
        }

        val oldSnapshot = snapshot()
        val newerSnapshot = snapshot()
        val latestField = streamClass.getDeclaredField("latestFrameSnapshot").apply { isAccessible = true }
        val clearIfSame = streamClass.getDeclaredMethod("clearFrameSnapshotIfSame", snapshotClass)
            .apply { isAccessible = true }
        try {
            latestField.set(null, newerSnapshot)
            assertFalse(clearIfSame.invoke(HikmicroJnaMini2Stream, oldSnapshot) as Boolean)
            assertSame(newerSnapshot, latestField.get(null))

            assertTrue(clearIfSame.invoke(HikmicroJnaMini2Stream, newerSnapshot) as Boolean)
            assertNull(latestField.get(null))
        } finally {
            latestField.set(null, null)
        }
    }

    @Test
    fun usbReopenPreparationInvalidatesTheOldGenerationBeforeOpenCanFail() {
        resetPreviewBinding()
        val manager = PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
        val handoffCount = AtomicInteger(0)
        PreviewManagerIIAppBinding.bind(manager) { handoffCount.incrementAndGet() }
        val generation = PreviewManagerIIAppBinding::class.java
            .getDeclaredField("managerGenerations")
            .apply { isAccessible = true }
            .get(null)
            .let { it as Map<*, *> }
            .get(manager) as Long

        handOffFrame(manager, frameCounter = 1L, stamp = 1)
        assertEquals(1, handoffCount.get())
        assertTrue(PreviewManagerIIAppBinding.isCurrentLifecycleGeneration(generation))

        PreviewManagerIIAppBinding.prepareForUsbReopen()

        assertFalse(PreviewManagerIIAppBinding.isCurrentLifecycleGeneration(generation))
        assertNull(PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 1L))
        handOffFrame(manager, frameCounter = 2L, stamp = 2)
        assertEquals(
            "an in-flight frame from the failed reopen's previous USB session must stay invalid",
            1,
            handoffCount.get(),
        )

        val bindingSource = source("app/src/main/java/kr/auto/titration/mobile/thermal/PreviewManagerIIAppBinding.java")
        val prepareBody = bindingSource.substringAfter("public static void prepareForUsbReopen()")
            .substringBefore("public static void unbind(")
        assertTrue(
            prepareBody.indexOf("clearManagerState(current)") <
                prepareBody.indexOf("current.suspendF2PublicationForUsbTransition()"),
        )

        val apiSource = source("app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt")
        val openBody = apiSource.substringAfter("fun openUsbModule(")
            .substringBefore("fun startStreamPreview(")
        assertTrue(
            openBody.indexOf("PreviewManagerIIAppBinding.prepareForUsbReopen()")
                < openBody.indexOf("helper.openUsbDevice("),
        )
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

    private class RecordingLifecycle : Lifecycle(), LifecycleOwner {
        private val observers = linkedSetOf<LifecycleObserver>()
        private var state = State.CREATED

        override val lifecycle: Lifecycle
            get() = this

        override val currentState: State
            get() = state

        override fun addObserver(observer: LifecycleObserver) {
            observers += observer
        }

        override fun removeObserver(observer: LifecycleObserver) {
            observers -= observer
        }

        fun destroy() {
            state = State.DESTROYED
            observers.toList().forEach { observer ->
                (observer as? DefaultLifecycleObserver)?.onDestroy(this)
            }
        }
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

    private fun managerGeneration(manager: PreviewManagerII): Long =
        PreviewManagerIIAppBinding::class.java.getDeclaredField("managerGenerations")
            .apply { isAccessible = true }
            .get(null)
            .let { it as Map<*, *> }
            .get(manager) as Long

    private fun onCurrentOfflineCallback(
        manager: PreviewManagerII,
        info: PreviewInfoDataBean,
        stamp: Int,
    ): Boolean = PreviewManagerIIAppBinding.onOfflineCallback(
        manager,
        info,
        stamp,
        manager.currentProcessingEpoch(),
        managerGeneration(manager),
    )

    private fun callbackFor(manager: PreviewManagerII): Any? =
        PreviewManagerIIAppBinding::class.java.getDeclaredField("callbacks")
            .apply { isAccessible = true }
            .get(null)
            .let { it as Map<*, *> }[manager]

    private fun streamOfficialPreviewManager(): PreviewManagerII? =
        HikmicroJnaMini2Stream::class.java.getDeclaredField("officialPreviewManager")
            .apply { isAccessible = true }
            .get(null) as? PreviewManagerII

    private fun streamOfficialPreviewSurfaceAttached(): Boolean =
        HikmicroJnaMini2Stream::class.java.getDeclaredField("officialPreviewSurfaceAttached")
            .apply { isAccessible = true }
            .getBoolean(null)

    private fun resetStreamSurfaceBinding() {
        HikmicroJnaMini2Stream::class.java.getDeclaredField("officialPreviewManager")
            .apply { isAccessible = true }
            .set(null, null)
        HikmicroJnaMini2Stream::class.java.getDeclaredField("officialPreviewSurfaceAttached")
            .apply { isAccessible = true }
            .setBoolean(null, false)
        HikmicroJnaMini2Stream::class.java.getDeclaredField("officialPreviewSurfaceView")
            .apply { isAccessible = true }
            .set(null, null)
    }

    private fun officialPreviewBinding(): OfficialPreviewBinding = OfficialPreviewBinding(
        root = unsafeAllocate(View::class.java),
        selectedSurface = unsafeAllocate(SurfaceView::class.java),
        visibleLightView = unsafeAllocate(FloatTextureView::class.java),
        sceneMode = SceneModeBean(),
        freezeCallback = {},
        overlayAvailabilityCallback = {},
    )

    private fun <T> unsafeAllocate(type: Class<T>): T {
        val unsafe = Class.forName("sun.misc.Unsafe").getDeclaredField("theUnsafe")
            .apply { isAccessible = true }
            .get(null)
        @Suppress("UNCHECKED_CAST")
        return unsafe.javaClass.getMethod("allocateInstance", Class::class.java)
            .invoke(unsafe, type) as T
    }

    private fun handOffFrame(manager: PreviewManagerII, frameCounter: Long, stamp: Int) {
        PreviewManagerIIAppBinding.afterOfficialG(
            manager,
            7,
            frameCounter,
            256,
            192,
            0,
            0,
            103,
            ByteArray(8),
            256,
            192,
            PreviewStreamInfo(previewInfoWithStamp(stamp), null),
            false,
            "processor",
        )
    }

    private fun previewInfoWithStamp(stamp: Int): PreviewInfoDataBean {
        val append = ByteArray(38)
        append[20] = (stamp and 0xff).toByte()
        append[21] = ((stamp ushr 8) and 0xff).toByte()
        return PreviewInfoDataBean(byteArrYuvAppendData = append)
    }

    private fun jpeg(marker: Int): ByteArray =
        byteArrayOf(0xff.toByte(), 0xd8.toByte(), marker.toByte())

    private fun resetPreviewBinding() {
        val managerField = PreviewManagerIIAppBinding::class.java.getDeclaredField("manager").apply { isAccessible = true }
        (managerField.get(null) as? PreviewManagerII)?.closePreviewCallback()
        managerField.set(null, null)
        PreviewManagerIIAppBinding::class.java.getDeclaredField("installedLifecycle").apply { isAccessible = true }.set(null, null)
        PreviewManagerIIAppBinding::class.java.getDeclaredField("terminalCloseRetryManager")
            .apply { isAccessible = true }
            .set(null, null)
        val callbacks = PreviewManagerIIAppBinding::class.java.getDeclaredField("callbacks").apply { isAccessible = true }.get(null) as MutableMap<*, *>
        callbacks.clear()
        val latestFrames = PreviewManagerIIAppBinding::class.java.getDeclaredField("latestFrames").apply { isAccessible = true }.get(null) as MutableMap<*, *>
        latestFrames.clear()
        val managerGenerations = PreviewManagerIIAppBinding::class.java.getDeclaredField("managerGenerations").apply { isAccessible = true }.get(null) as MutableMap<*, *>
        managerGenerations.clear()
        val offlineCallbacks = PreviewManagerIIAppBinding::class.java.getDeclaredField("offlineCallbacksByManager").apply { isAccessible = true }.get(null) as MutableMap<*, *>
        offlineCallbacks.clear()
        PreviewManagerIIAppBinding::class.java.getDeclaredField("nextLifecycleGeneration").apply { isAccessible = true }.setLong(null, 0L)
    }

    private class RecordingProcessor : g3.a() {
        var processCount: Int = 0

        override fun d(frameInfoData: ByteArray): PreviewStreamInfo {
            processCount += 1
            return PreviewStreamInfo(PreviewInfoDataBean(), null)
        }
    }

    private class BlockingProcessor(
        private val entered: CountDownLatch,
        private val release: CountDownLatch,
    ) : g3.a() {
        override fun d(frameInfoData: ByteArray): PreviewStreamInfo {
            entered.countDown()
            assertTrue(release.await(2, TimeUnit.SECONDS))
            return PreviewStreamInfo(PreviewInfoDataBean(), null)
        }
    }

    private class SessionCloseBridge : JavaInterface.NativeBridge {
        val thermalStreamControlValues = mutableListOf<Int>()

        override fun USB_Init(): Boolean = true
        override fun USB_Cleanup(): Boolean = true
        override fun USB_GetLastError(): Int = 84
        override fun USB_GetDeviceCount(): Int = 0
        override fun USB_EnumDevices_C(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean = false
        override fun USB_Login(loginInfo: USB_USER_LOGIN_INFO, deviceRegRes: USB_DEVICE_REG_RES): Int = -1
        override fun USB_GetSysTemDeviceInfo(userId: Int, info: USB_SYSTEM_DEVICE_INFO): Boolean = false
        override fun USB_GetThermometryCalibrationFile(
            userId: Int,
            cond: USB_COMMON_COND,
            out: USB_THERMOMETRY_CALIBRATION_FILE,
        ): Boolean = false

        override fun USB_SetVideoParam(userId: Int, param: USB_VIDEO_PARAM): Boolean = false
        override fun USB_SetThermalStreamParam(userId: Int, param: USB_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_GetThermalStreamCtrl(
            userId: Int,
            param: USB_CTRL_THERMAL_STREAM_PARAM,
        ): Boolean {
            param.byEnable = 0
            return true
        }

        override fun USB_SetThermalStreamCtrl(
            userId: Int,
            param: USB_CTRL_THERMAL_STREAM_PARAM,
        ): Boolean {
            thermalStreamControlValues += param.byEnable.toInt()
            return true
        }

        override fun USB_StopChannel(userId: Int, channel: Int): Boolean = false
        override fun USB_Logout(userId: Int): Boolean = true
    }

    private class RecordingRenderer : V2.f {
        val calls = mutableListOf<String>()

        override fun a(): Boolean = false
        override fun b(listener: com.hik.library.player.b) {
            calls += "b"
        }
        override fun c() {
            calls += "c"
        }
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
        override fun h(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int) {
            calls += "h"
        }
        override fun i(showSize: Size) = Unit
        override fun j(
            rawData: ByteArray?,
            nv12Data: ByteArray,
            yuvImgSize: Size,
            frameNumStamp: Int,
            overlays: List<*>?,
            overlayBitmap: Bitmap?,
        ) {
            calls += "j"
        }
        override fun k(value: Int) = Unit
        override fun release() {
            calls += "release"
        }
        override fun start() {
            calls += "start"
        }
        override fun stop() {
            calls += "stop"
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
