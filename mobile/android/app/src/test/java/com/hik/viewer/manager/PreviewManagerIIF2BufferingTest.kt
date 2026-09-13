package com.hik.viewer.manager

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.Interface.USB_FRAME_INFO
import com.hcusbsdk.Interface.USB_STREAM_CALLBACK_PARAM
import com.hik.f2module.F2OpenResult
import com.hik.f2module.F2UsbModuleApi
import com.hik.viewercommon.data.bean.UsbModuleType
import com.hik.viewercommon.data.bean.PreviewInfoDataBean
import com.hik.viewercommon.data.bean.PreviewStreamInfo
import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolver
import kr.auto.titration.mobile.thermal.PreviewManagerIIAppBinding
import java.util.Arrays
import java.io.File
import java.lang.reflect.Proxy
import java.util.concurrent.CountDownLatch
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Ignore
import org.junit.Test

class PreviewManagerIIF2BufferingTest {
    private fun newManager() = PreviewManagerII(testLifecycle(), false, false)

    @Test fun previewSchedulerUsesEpochAwareFixedDelayWithoutFixedRateCatchUp() {
        val sourceRoot = sequenceOf(
            File("src/main/java/com/hik/viewer/manager/PreviewManagerII.java"),
            File("app/src/main/java/com/hik/viewer/manager/PreviewManagerII.java"),
            File("mobile/android/app/src/main/java/com/hik/viewer/manager/PreviewManagerII.java"),
        )
            .first { it.isFile }
        val source = sourceRoot.readText()

        assertTrue(source.contains("scheduleWithFixedDelay("))
        assertFalse(source.contains("scheduleAtFixedRate("))
        assertTrue(source.contains("final long schedulerEpoch = processingEpoch;"))
        assertTrue(source.contains("isProcessingEpochCurrent(schedulerEpoch)"))
    }

    @Test fun officialRRejectsDeclaredLengthBeyondAvailableBytesWithoutMutatingMailboxes() {
        val manager = newManager()
        Z2.a.a.u(f3.j().apply { d(12) })
        val callback = manager.R()
        assertNotNull(callback)
        val source = ByteArray(NORMAL_SIZE - 7) { (it % 127).toByte() }
        val acceptedSizeBefore = Z2.g.a.n()
        val frameCounterBefore = longField(manager, "frameCounter")
        val firstCallbackAtMsBefore = longField(manager, "firstCallbackAtMs")
        val lastCallbackAtMsBefore = longField(manager, "lastCallbackAtMs")
        callback.invoke(1, frameInfo(NORMAL_SIZE, source, 1))
        val s0 = PreviewManagerII::class.java.getDeclaredField("s0").apply { isAccessible = true }.get(manager) as ByteArray
        val r0 = PreviewManagerII::class.java.getDeclaredField("r0").apply { isAccessible = true }.get(manager) as ByteArray
        assertEquals(0, s0.size)
        assertEquals(0, r0.size)
        assertEquals(acceptedSizeBefore, Z2.g.a.n())
        assertEquals(frameCounterBefore, longField(manager, "frameCounter"))
        assertEquals(firstCallbackAtMsBefore, longField(manager, "firstCallbackAtMs"))
        assertEquals(lastCallbackAtMsBefore, longField(manager, "lastCallbackAtMs"))
        manager.closePreviewCallback()
    }

    private fun longField(manager: PreviewManagerII, name: String): Long =
        PreviewManagerII::class.java.getDeclaredField(name)
            .apply { isAccessible = true }
            .getLong(manager)

    @Test fun officialOfflineMailboxGateRequiresCoding12AndUsesR0() {
        val manager = newManager()
        val previous = Z2.a.a.p()
        try {
            val profile = f3.j().apply { d(12) }
            Z2.a.a.u(profile)
            captureProcessorProfile(manager, profile)
            manager.R().invoke(1, frameInfo(OFFLINE_SIZE, ByteArray(OFFLINE_SIZE) { 3 }, 3))
            val r0 = PreviewManagerII::class.java.getDeclaredField("r0").apply { isAccessible = true }.get(manager) as ByteArray
            assertEquals(OFFLINE_SIZE, r0.size)
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previous)
        }
    }

    @Test fun officialMailboxStoresLatestNormalAndOfflineSlotsBeforeK2Processing() {
        val manager = newManager()
        val previous = Z2.a.a.p()
        try {
            val profile = f3.j().apply { d(12) }
            Z2.a.a.u(profile)
            captureProcessorProfile(manager, profile)
            manager.R().invoke(1, frameInfo(NORMAL_SIZE, ByteArray(NORMAL_SIZE) { 1 }, 1))
            manager.R().invoke(1, frameInfo(OFFLINE_SIZE, ByteArray(OFFLINE_SIZE) { 2 }, 3))
            val s0 = PreviewManagerII::class.java.getDeclaredField("s0").apply { isAccessible = true }.get(manager) as ByteArray
            val r0 = PreviewManagerII::class.java.getDeclaredField("r0").apply { isAccessible = true }.get(manager) as ByteArray
            assertEquals(NORMAL_SIZE, s0.size)
            assertEquals(OFFLINE_SIZE, r0.size)
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previous)
        }
    }

    @Test fun invalidPacketSizeTimeoutCallbackReceivesRejectedPacketEvidence() {
        val manager = newManager()
        val previous = Z2.a.a.p()
        val packetSize = 102_944
        val observedSize = AtomicInteger(-1)
        val observedElapsed = AtomicLong(-1L)
        try {
            Z2.a.a.u(f3.j().apply { d(12) })
            manager.setInvalidPacketSizeTimeoutCallback { size, elapsedMs ->
                observedSize.set(size)
                observedElapsed.set(elapsedMs)
            }
            manager.P0(System.currentTimeMillis() - 40_001L)

            manager.R().invoke(1, frameInfo(packetSize, ByteArray(packetSize) { 4 }, 9))

            assertEquals(packetSize, observedSize.get())
            assertTrue("invalid packet timeout should preserve elapsed evidence", observedElapsed.get() >= 40_000L)
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previous)
        }
    }

    @Test fun invalidPacketTimeoutIsConsumedBeforeRecursiveSynchronousReentry() {
        val manager = newManager()
        val previous = Z2.a.a.p()
        val timeoutCount = AtomicInteger(0)
        try {
            Z2.a.a.u(f3.j().apply { d(12) })
            captureProcessorProfile(manager, Z2.a.a.p())
            val rejected = frameInfo(102_944, ByteArray(102_944), 129, streamType = 103)
            lateinit var callback: com.hcusbsdk.Interface.FStreamCallBack
            callback = manager.R()
            manager.setInvalidPacketSizeTimeoutCallback { _, _ ->
                timeoutCount.incrementAndGet()
                callback.invoke(6, rejected)
            }
            manager.P0(System.currentTimeMillis() - 40_001L)

            callback.invoke(6, rejected)

            assertEquals(
                "recursive synchronous ingress must observe the timeout as already consumed",
                1,
                timeoutCount.get(),
            )
            assertTrue(
                "recursive ingress starts a fresh 40-second baseline instead of redispatching",
                longField(manager, "firstCallbackAtMs") > System.currentTimeMillis() - 5_000L,
            )
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previous)
        }
    }

    @Test fun throwingInvalidPacketCallbackStaysContainedAndTimeoutRemainsDisarmed() {
        val manager = newManager()
        val previous = Z2.a.a.p()
        val timeoutCount = AtomicInteger(0)
        try {
            Z2.a.a.u(f3.j().apply { d(12) })
            captureProcessorProfile(manager, Z2.a.a.p())
            manager.setInvalidPacketSizeTimeoutCallback { _, _ ->
                timeoutCount.incrementAndGet()
                throw IllegalStateException("diagnostic boom")
            }
            manager.P0(System.currentTimeMillis() - 40_001L)
            val rejected = frameInfo(102_944, ByteArray(102_944), 129, streamType = 103)

            manager.R().invoke(6, rejected)
            manager.R().invoke(6, rejected)

            assertEquals(1, timeoutCount.get())
            assertTrue(
                manager.lastStreamProcessingFailure.startsWith(
                    "invalid_packet_callback_failure=IllegalStateException:diagnostic boom",
                ),
            )
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previous)
        }
    }

    @Test fun fullCloseAndNormalReopenCannotReusePriorSessionTimeoutBaseline() {
        val manager = newManager()
        val previous = Z2.a.a.p()
        val timeoutCount = AtomicInteger(0)
        try {
            Z2.a.a.u(f3.j().apply { d(12) })
            captureProcessorProfile(manager, Z2.a.a.p())
            manager.P0(System.currentTimeMillis() - 80_000L)

            manager.closePreviewCallback()
            manager.openPreviewCallback()
            captureProcessorProfile(manager, Z2.a.a.p())
            manager.setInvalidPacketSizeTimeoutCallback { _, _ -> timeoutCount.incrementAndGet() }
            manager.R().invoke(
                6,
                frameInfo(102_944, ByteArray(102_944), 129, streamType = 103),
            )

            assertEquals(
                "the first invalid packet in a new epoch must start, not inherit, the 40-second window",
                0,
                timeoutCount.get(),
            )
            assertTrue(longField(manager, "firstCallbackAtMs") > System.currentTimeMillis() - 5_000L)
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previous)
        }
    }

    @Test fun lateGraphInitializationPreservesRegisteredCallbackEpochAndAcceptsExactF2Tuple() {
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        val previousDetectedType = Z2.g.a.V()
        val previousCachedType = Z2.g.a.r()
        val javaInterface = JavaInterface.getInstance()
        val manager = installBoundManager()
        val appContextField = d2.a::class.java.getDeclaredField("b").apply { isAccessible = true }
        val previousAppContext = appContextField.get(null)
        try {
            val profile = f3.j().apply { d(12) }
            Z2.a.a.u(profile)
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = ""))
            Z2.g.a.d1(UsbModuleType.NONE)
            Z2.g.a.D0(UsbModuleType.NONE)
            manager.P0(System.currentTimeMillis() - 80_000L)
            PreviewManagerIIAppBinding.bind(manager) { }
            captureProcessorProfile(manager, profile)

            val registeredCallback = manager.R()
            val callbackEpoch = manager.currentProcessingEpoch()
            assertEquals(
                "a non-resume bind/open boundary must reset the prior timeout baseline",
                0L,
                longField(manager, "firstCallbackAtMs"),
            )
            javaInterface.resetStreamCallbackRegistrationsForTest()
            javaInterface.jniStartStreamCallbackInvoker =
                JavaInterface.JniStartStreamCallbackInvoker { _, _, _ -> 0 }
            assertEquals(
                0,
                javaInterface.USB_StartStreamCallback(
                    6,
                    USB_STREAM_CALLBACK_PARAM().apply {
                        dwStreamType = 103
                        fnStreamCallBack = registeredCallback
                    },
                ),
            )

            val renderer = Proxy.newProxyInstance(
                V2.f::class.java.classLoader,
                arrayOf(V2.f::class.java),
            ) { _, method, _ ->
                if (method.returnType == java.lang.Boolean.TYPE) false else null
            } as V2.f
            val factory = Proxy.newProxyInstance(
                X2.b::class.java.classLoader,
                arrayOf(X2.b::class.java),
            ) { _, _, _ -> renderer } as X2.b
            val preferences = Proxy.newProxyInstance(
                android.content.SharedPreferences::class.java.classLoader,
                arrayOf(android.content.SharedPreferences::class.java),
            ) { _, method, args ->
                when (method.name) {
                    "getBoolean", "getFloat", "getInt", "getLong", "getString" -> args!![1]
                    "getAll" -> emptyMap<String, Any>()
                    "contains" -> false
                    else -> null
                }
            } as android.content.SharedPreferences
            val context = object : android.content.ContextWrapper(null) {
                override fun getApplicationContext(): android.content.Context = this
                override fun getSystemService(name: String): Any? = null
                override fun getSharedPreferences(
                    name: String,
                    mode: Int,
                ): android.content.SharedPreferences = preferences
            }
            d2.a.b(context)
            PreviewManagerII::class.java.getDeclaredField("rendererFactoryOverride")
                .apply { isAccessible = true }
                .set(manager, factory)

            val localAndroidStubFailure =
                runCatching {
                    manager.l0(null, null, null, null, null, null, null, null)
                }.exceptionOrNull()
            assertTrue(
                "local JVM l0 may stop only at an Android framework stub after graph attachment",
                generateSequence(localAndroidStubFailure) { it.cause }
                    .any { it.message?.contains("not mocked") == true },
            )

            assertTrue("late graph initialization must retain the registered callback", manager.R() === registeredCallback)
            assertEquals(
                "late graph initialization is not a callback/session epoch boundary",
                callbackEpoch,
                manager.currentProcessingEpoch(),
            )
            registeredCallback.invoke(
                6,
                frameInfo(
                    size = NORMAL_SIZE,
                    bytes = ByteArray(NORMAL_SIZE) { 0x29 },
                    frameNum = 129,
                    streamType = 103,
                ),
            )

            val diagnostic = manager.streamIngressDiagnostic
            assertEquals("mailbox_accepted", diagnostic.reason)
            assertEquals(6, diagnostic.userId)
            assertEquals(NORMAL_SIZE, diagnostic.packetSize)
            assertEquals(103, diagnostic.streamType)
            assertEquals(129L, diagnostic.frameNumber)
            assertEquals(1L, diagnostic.mailboxAcceptedCount)
            assertTrue(
                "the retained callback must start a fresh timeout baseline after the bind/open boundary",
                longField(manager, "firstCallbackAtMs") > System.currentTimeMillis() - 5_000L,
            )
        } finally {
            javaInterface.invalidateStreamCallbackRegistration(6)
            javaInterface.resetJniStartStreamCallbackInvokerForTest()
            PreviewManagerIIAppBinding.unbind(manager)
            appContextField.set(null, previousAppContext)
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
            Z2.g.a.d1(previousDetectedType)
            Z2.g.a.D0(previousCachedType)
        }
    }

    @Test fun wrongProfilePacketSizeRecordsExplicitFailClosedIngressReasonAndAllowedSizes() {
        val manager = newManager()
        val previous = Z2.a.a.p()
        try {
            val profile = f3.j().apply { d(12) }
            Z2.a.a.u(profile)
            captureProcessorProfile(manager, profile)

            manager.R().invoke(
                6,
                frameInfo(
                    size = 101_320,
                    bytes = ByteArray(101_320),
                    frameNum = 129,
                    streamType = 103,
                ),
            )

            val diagnostic = manager.streamIngressDiagnostic
            assertEquals("packet_size_not_allowed", diagnostic.reason)
            assertEquals(6, diagnostic.userId)
            assertEquals(101_320, diagnostic.packetSize)
            assertEquals(103, diagnostic.streamType)
            assertEquals(129L, diagnostic.frameNumber)
            assertEquals(setOf(NORMAL_SIZE, OFFLINE_SIZE), diagnostic.allowedPacketSizes.toSet())
            assertEquals(1L, diagnostic.packetSizeNotAllowedCount)
            assertEquals(0L, diagnostic.mailboxAcceptedCount)
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previous)
        }
    }

    @Test fun retainedCallbackFromClosedEpochCannotRelabelIngressAfterReopen() {
        val manager = newManager()
        val callback = manager.R()
        manager.closePreviewCallback()
        manager.openPreviewCallback()

        callback.invoke(
            6,
            frameInfo(
                size = NORMAL_SIZE,
                bytes = ByteArray(NORMAL_SIZE),
                frameNum = 129,
                streamType = 103,
            ),
        )

        val diagnostic = manager.streamIngressDiagnostic
        assertEquals("not_observed", diagnostic.reason)
        assertEquals(0L, diagnostic.streamClosedCount)
        assertEquals(0L, diagnostic.packetSizeNotAllowedCount)
        assertEquals(0L, diagnostic.mailboxAcceptedCount)
        manager.closePreviewCallback()
    }

    @Test fun staleInvalidPacketCannotRecordOrInvokeNewSessionTimeoutAfterReopen() {
        val manager = newManager()
        val staleCallback = manager.R()
        val timeoutCount = AtomicInteger(0)
        manager.closePreviewCallback()
        manager.openPreviewCallback()
        manager.setInvalidPacketSizeTimeoutCallback { _, _ -> timeoutCount.incrementAndGet() }
        manager.P0(System.currentTimeMillis() - 40_001L)

        staleCallback.invoke(
            6,
            frameInfo(
                size = 102_944,
                bytes = ByteArray(102_944),
                frameNum = 129,
                streamType = 103,
            ),
        )

        assertEquals(0, timeoutCount.get())
        assertEquals("not_observed", manager.streamIngressDiagnostic.reason)
        manager.closePreviewCallback()
    }

    @Test fun invalidPacketDiagnosticRuntimeExceptionIsContainedAtNativeBoundary() {
        val manager = newManager()
        val previous = Z2.a.a.p()
        try {
            val profile = f3.j().apply { d(12) }
            Z2.a.a.u(profile)
            captureProcessorProfile(manager, profile)
            manager.setInvalidPacketSizeTimeoutCallback { _, _ ->
                throw IllegalStateException("diagnostic boom")
            }
            manager.P0(System.currentTimeMillis() - 40_001L)

            manager.R().invoke(
                6,
                frameInfo(102_944, ByteArray(102_944), 129, streamType = 103),
            )

            assertTrue(
                manager.lastStreamProcessingFailure.startsWith(
                    "invalid_packet_callback_failure=IllegalStateException:diagnostic boom",
                ),
            )
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previous)
        }
    }

    @Test fun invalidPacketLegacyLinkageErrorIsContainedAtNativeBoundary() {
        val manager = newManager()
        val previous = Z2.a.a.p()
        try {
            val profile = f3.j().apply { d(12) }
            Z2.a.a.u(profile)
            captureProcessorProfile(manager, profile)
            PreviewManagerII::class.java.getDeclaredField("a0")
                .apply { isAccessible = true }
                .set(manager, {
                    throw UnsatisfiedLinkError("legacy boom")
                })
            manager.P0(System.currentTimeMillis() - 40_001L)

            manager.R().invoke(
                6,
                frameInfo(102_944, ByteArray(102_944), 129, streamType = 103),
            )

            assertTrue(
                manager.lastStreamProcessingFailure.startsWith(
                    "invalid_packet_callback_failure=UnsatisfiedLinkError:legacy boom",
                ),
            )
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previous)
        }
    }

    @Test fun closePreviewCallbackClearsInvalidPacketTimeoutCallbackForRetryCleanup() {
        val manager = newManager()
        val previous = Z2.a.a.p()
        val timeoutCount = AtomicInteger(0)
        try {
            Z2.a.a.u(f3.j().apply { d(12) })
            manager.setInvalidPacketSizeTimeoutCallback { _, _ -> timeoutCount.incrementAndGet() }
            manager.closePreviewCallback()
            manager.openPreviewCallback()
            manager.P0(System.currentTimeMillis() - 40_001L)

            manager.R().invoke(1, frameInfo(102_944, ByteArray(102_944) { 5 }, 10))

            assertEquals("retry cleanup must not retain stale timeout callbacks", 0, timeoutCount.get())
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previous)
        }
    }

    @Test fun ingressFrameFromClosedEpochCannotBeRelabeledIntoReopenedSession() {
        val manager = newManager()
        val source = ByteArray(NORMAL_SIZE) { 0x2a }
        val info = frameInfo(NORMAL_SIZE, source, 15)
        val entry = PreviewManagerII.beginCallback(manager)
        assertNotNull(entry)
        val stale = PreviewManagerII.frameEnvelope(
            6,
            info,
            entry!!.frameNumber,
            entry.processingEpoch,
            source,
        )

        manager.closePreviewCallback()
        manager.openPreviewCallback()
        PreviewManagerII.u(manager, stale)

        val mailbox = PreviewManagerII::class.java.getDeclaredField("s0")
            .apply { isAccessible = true }
            .get(manager) as ByteArray
        assertEquals("old callback ingress must not populate the reopened mailbox", 0, mailbox.size)
        assertTrue(manager.currentProcessingEpoch() != entry.processingEpoch)
        manager.closePreviewCallback()
    }

    @Test fun lateF2ProfileActivationInitializesProcessorAndDelivers203720Callback() {
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        val previousDetectedType = Z2.g.a.V()
        val previousCachedType = Z2.g.a.r()
        val manager = installBoundManager()
        val delivered = CountDownLatch(1)
        val deliveredCount = AtomicInteger(0)
        val processedCount = AtomicInteger(0)
        try {
            Z2.a.a.u(f3.a())
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = ""))
            Z2.g.a.d1(UsbModuleType.NONE)
            Z2.g.a.D0(UsbModuleType.NONE)
            PreviewManagerIIAppBinding.bind(manager) {
                deliveredCount.incrementAndGet()
                delivered.countDown()
            }
            assertEquals(null, processor(manager))

            val resolution = HikmicroF2ProfileResolver.resolve(
                "0953060001",
                "APP_010203_20240101",
            )
            val openResult = F2OpenResult(
                ok = true,
                userId = 7,
                deviceInfo = null,
                reason = "open_ok",
                stageReport = "USB_Login=ok",
                profileResolution = resolution,
            )
            val activated = F2UsbModuleApi.synchronizeRuntimeAfterOpen(openResult)

            assertTrue(activated.ok)
            assertTrue(Z2.a.a.p() is f3.j)
            assertEquals(setOf(NORMAL_SIZE, OFFLINE_SIZE), Z2.a.a.p().e().toSet())
            assertEquals("0953060001", Z2.g.a.U().getModuleID())
            assertEquals(UsbModuleType.F2, Z2.g.a.V())
            assertEquals(UsbModuleType.F2, Z2.g.a.r())
            assertTrue(processor(manager) is g3.e)
            val activatedProfile = Z2.a.a.p()
            val activatedProcessor = processor(manager)

            val repeated = F2UsbModuleApi.synchronizeRuntimeAfterOpen(openResult)

            assertTrue(repeated.ok)
            assertTrue("repeated activation should preserve the selected runtime profile", Z2.a.a.p() === activatedProfile)
            assertTrue("repeated activation should preserve the initialized processor", processor(manager) === activatedProcessor)
            setProcessor(manager, object : g3.a() {
                override fun d(frameInfoData: ByteArray): PreviewStreamInfo {
                    assertEquals(NORMAL_SIZE, frameInfoData.size)
                    processedCount.incrementAndGet()
                    return PreviewStreamInfo(PreviewInfoDataBean(), null)
                }
            })
            Z2.a.a.u(f3.g())

            manager.R().invoke(7, frameInfo(NORMAL_SIZE, ByteArray(NORMAL_SIZE), 17))

            assertTrue(
                "the callback generation must retain the activated f3.j packet contract even if the mutable global changes",
                delivered.await(2, TimeUnit.SECONDS),
            )
            assertEquals(1, processedCount.get())
            assertEquals(1, deliveredCount.get())
        } finally {
            PreviewManagerIIAppBinding.unbind(manager)
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
            Z2.g.a.d1(previousDetectedType)
            Z2.g.a.D0(previousCachedType)
        }
    }

    @Test fun acceptedOfficialJniCallbackTraversesWrapperProcessorAndAppBinding() {
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        val previousDetectedType = Z2.g.a.V()
        val previousCachedType = Z2.g.a.r()
        val javaInterface = JavaInterface.getInstance()
        val manager = installBoundManager()
        val delivered = CountDownLatch(1)
        val callbackFrames = CopyOnWriteArrayList<com.hik.f2module.F2StreamFrame>()
        var nativeWrapper: com.hcusbsdk.jni.StreamCallBack_JNI? = null
        try {
            javaInterface.resetStreamCallbackRegistrationsForTest()
            javaInterface.jniStartStreamCallbackInvoker =
                JavaInterface.JniStartStreamCallbackInvoker { _, _, callback ->
                    nativeWrapper = callback
                    0
                }
            Z2.a.a.u(f3.j().apply { d(12) })
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = "0953060001"))
            Z2.g.a.d1(UsbModuleType.F2)
            Z2.g.a.D0(UsbModuleType.F2)
            PreviewManagerIIAppBinding.bind(manager) {
                callbackFrames += it
                delivered.countDown()
            }
            assertTrue(manager.refreshF2ProcessorFromRuntimeProfile())
            stopScheduler(manager)
            setProcessor(manager, object : g3.a() {
                override fun d(frameInfoData: ByteArray): PreviewStreamInfo =
                    PreviewStreamInfo(PreviewInfoDataBean(), null)
            })
            assertEquals(
                0,
                javaInterface.USB_StartStreamCallback(
                    6,
                    USB_STREAM_CALLBACK_PARAM().apply {
                        dwStreamType = 103
                        fnStreamCallBack = manager.R()
                    },
                ),
            )

            repeat(129) { index ->
                nativeWrapper!!.fStreamCallback_JNI(
                    6,
                    com.hcusbsdk.jni.USB_FRAME_INFO().apply {
                        dwBufSize = NORMAL_SIZE
                        pBuf.fill((index and 0xff).toByte())
                        dwWidth = 256
                        dwHeight = 344
                        dwFrameType = 0
                        dwDataType = 0
                        dwStreamType = 103
                        nFrameNum = index + 1
                    },
                )
                PreviewManagerII.g(manager)
            }

            assertTrue(
                "an accepted JNI callback must reach the app binding instead of remaining at frame_counter=0",
                delivered.await(2, TimeUnit.SECONDS),
            )
            assertTrue(javaInterface.lastStreamCallbackEntryDetail.contains("disposition=dispatched"))
            assertEquals(129L, javaInterface.streamCallbackEntryCount)
            assertEquals(0L, javaInterface.streamCallbackRejectedEntryCount)
            assertTrue(javaInterface.lastStreamCallbackEntryDetail.contains("dispatchedCount=129"))
            assertEquals(129, callbackFrames.size)
            assertEquals(6, callbackFrames.last().callbackUserId)
            assertEquals(129L, callbackFrames.last().frameCounter)
            assertEquals(103, callbackFrames.last().streamType)
            assertEquals(NORMAL_SIZE, callbackFrames.last().bytes.size)
            assertEquals("app_handoff", manager.streamIngressDiagnostic.reason)
            assertEquals(129L, manager.streamIngressDiagnostic.mailboxAcceptedCount)
            assertEquals(129L, manager.streamIngressDiagnostic.processorAcceptedCount)
            assertEquals(129L, manager.streamIngressDiagnostic.appHandoffCount)
        } finally {
            javaInterface.invalidateStreamCallbackRegistration(6)
            javaInterface.resetJniStartStreamCallbackInvokerForTest()
            PreviewManagerIIAppBinding.unbind(manager)
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
            Z2.g.a.d1(previousDetectedType)
            Z2.g.a.D0(previousCachedType)
        }
    }

    @Ignore("Requires Android runtime: g3.e executes android.util.Size.getWidth/getHeight")
    @Test fun actualStreamingNewProcessorTransforms203720PacketAndPublishesFrame() {
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        val previousDetectedType = Z2.g.a.V()
        val previousCachedType = Z2.g.a.r()
        val manager = installBoundManager()
        val callbackFrames = CopyOnWriteArrayList<com.hik.f2module.F2StreamFrame>()
        try {
            Z2.a.a.u(f3.j().apply { d(12) })
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = "0953060001"))
            Z2.g.a.d1(UsbModuleType.F2)
            Z2.g.a.D0(UsbModuleType.F2)
            PreviewManagerIIAppBinding.bind(manager) { callbackFrames += it }

            assertTrue(manager.refreshF2ProcessorFromRuntimeProfile())
            assertTrue(processor(manager) is g3.e)
            stopScheduler(manager)

            val packet = ByteArray(NORMAL_SIZE) { index -> (index and 0xff).toByte() }
            manager.R().invoke(
                6,
                frameInfo(
                    size = NORMAL_SIZE,
                    bytes = packet,
                    frameNum = 129,
                    width = 256,
                    height = 344,
                    frameType = 0,
                    dataType = 0,
                    streamType = 103,
                ),
            )
            PreviewManagerII.g(manager)

            assertEquals(
                "processorFailure=${manager.lastStreamProcessingFailure}; ingress=${manager.streamIngressDiagnostic}",
                1,
                callbackFrames.size,
            )
            val processed = PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 129L)
            assertNotNull(processed)
            val preview = processed!!.previewStreamInfo.previewInfoData
            assertEquals(NORMAL_SIZE, preview.getByteArrSrc().size)
            assertEquals(73_728, preview.getByteArrDst().size)
            assertEquals(27_592, preview.getByteArrHead().size)
            assertEquals(98_304, preview.getByteArrRawData().size)
            assertEquals(2_048, preview.getByteArrRawAppendData().size)
            assertEquals(2_048, preview.getByteArrYuvAppendData().size)
            assertEquals(512, preview.getByteArrRawAppendLine2().size)
            assertEquals(98_304, preview.getOffByteArrRawData().size)
            assertEquals(768, preview.getOffByteArrRawAppendData().size)
            assertTrue(processed.previewStreamInfo.iStreamInfo is h3.b)
            assertEquals("app_handoff", manager.streamIngressDiagnostic.reason)
            assertEquals(1L, manager.streamIngressDiagnostic.processorAcceptedCount)
            assertEquals(1L, manager.streamIngressDiagnostic.appHandoffCount)
            assertTrue(manager.lastStreamProcessingFailure == null)
        } finally {
            PreviewManagerIIAppBinding.unbind(manager)
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
            Z2.g.a.d1(previousDetectedType)
            Z2.g.a.D0(previousCachedType)
        }
    }

    @Test fun unresolvedOpenResultDoesNotPartiallyReplaceRuntimeProfileOrIdentity() {
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        try {
            val sentinelProfile = f3.j()
            Z2.a.a.u(sentinelProfile)
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = "existing-module"))
            val unresolved = HikmicroF2ProfileResolver.resolve(
                "unsupported",
                "APP_010203_20240101",
            )

            val result = F2UsbModuleApi.synchronizeRuntimeAfterOpen(
                F2OpenResult(
                    ok = true,
                    userId = 8,
                    deviceInfo = null,
                    reason = "profile_unresolved",
                    stageReport = "USB_Login=ok",
                    profileResolution = unresolved,
                ),
            )

            assertTrue(result.ok)
            assertTrue(result.stageReport.contains("runtimeProfile=not_applied"))
            assertTrue(Z2.a.a.p() === sentinelProfile)
            assertEquals("existing-module", Z2.g.a.U().getModuleID())
        } finally {
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
        }
    }

    @Test fun synchronizationReplacesStaleLegacyProcessorForStreamingNewProfile() {
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        val previousDetectedType = Z2.g.a.V()
        val previousCachedType = Z2.g.a.r()
        val manager = installBoundManager()
        try {
            val profile = f3.j().apply { d(12) }
            val staleProcessor = g3.d(i3.b())
            Z2.a.a.u(profile)
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = "0953060001"))
            Z2.g.a.d1(UsbModuleType.F2)
            Z2.g.a.D0(UsbModuleType.F2)
            setProcessor(manager, staleProcessor)
            setProcessorProfile(manager, profile)

            val resolution = HikmicroF2ProfileResolver.resolve(
                "0953060001",
                "APP_020005_BUILD_20250522",
            )
            val result = F2UsbModuleApi.synchronizeRuntimeAfterOpen(
                F2OpenResult(
                    ok = true,
                    userId = 9,
                    deviceInfo = null,
                    reason = "open_ok",
                    stageReport = "USB_Login=ok",
                    profileResolution = resolution,
                ),
            )

            assertTrue(result.ok)
            assertTrue("streaming-new f3.j must use the 203720-capable processor", processor(manager) is g3.e)
            assertFalse("stale g3.d processor must not survive synchronization", processor(manager) === staleProcessor)
        } finally {
            PreviewManagerIIAppBinding.unbind(manager)
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
            Z2.g.a.d1(previousDetectedType)
            Z2.g.a.D0(previousCachedType)
        }
    }

    @Test fun runtimeActivationRebindAndRefreshRestores203720AppHandoff() {
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        val previousDetectedType = Z2.g.a.V()
        val previousCachedType = Z2.g.a.r()
        val manager = installBoundManager()
        val delivered = CountDownLatch(1)
        val processedCount = AtomicInteger(0)
        try {
            val profile = f3.j().apply { d(12) }
            Z2.a.a.u(profile)
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = "0953060001"))
            Z2.g.a.d1(UsbModuleType.F2)
            Z2.g.a.D0(UsbModuleType.F2)

            PreviewManagerIIAppBinding.bind(manager) { }
            assertTrue(manager.refreshF2ProcessorFromRuntimeProfile())
            assertTrue(processor(manager) is g3.e)

            manager.prepareF2RuntimeActivation()
            assertEquals(null, processor(manager))

            PreviewManagerIIAppBinding.bind(manager) { delivered.countDown() }
            assertEquals(null, processor(manager))
            assertTrue(manager.refreshF2ProcessorFromRuntimeProfile())
            assertTrue("rebind refresh must recreate the streaming-new processor", processor(manager) is g3.e)
            setProcessor(manager, object : g3.a() {
                override fun d(frameInfoData: ByteArray): PreviewStreamInfo {
                    assertEquals(NORMAL_SIZE, frameInfoData.size)
                    processedCount.incrementAndGet()
                    return PreviewStreamInfo(PreviewInfoDataBean(), null)
                }
            })

            manager.R().invoke(7, frameInfo(NORMAL_SIZE, ByteArray(NORMAL_SIZE), 18))

            assertTrue(
                "203720 packet must reach the app callback after close/rebind/refresh",
                delivered.await(2, TimeUnit.SECONDS),
            )
            assertEquals(1, processedCount.get())
        } finally {
            PreviewManagerIIAppBinding.unbind(manager)
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
            Z2.g.a.d1(previousDetectedType)
            Z2.g.a.D0(previousCachedType)
        }
    }

    @Test fun handoffFailureStillPublishesRawFrameAndDoesNotEscapeSchedulerPath() {
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        val previousDetectedType = Z2.g.a.V()
        val previousCachedType = Z2.g.a.r()
        val manager = installBoundManager()
        val delivered = CountDownLatch(1)
        try {
            Z2.a.a.u(f3.j().apply { d(12) })
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = "0953060001"))
            Z2.g.a.d1(UsbModuleType.F2)
            Z2.g.a.D0(UsbModuleType.F2)
            PreviewManagerIIAppBinding.bind(manager) { delivered.countDown() }
            assertTrue(manager.refreshF2ProcessorFromRuntimeProfile())
            setProcessor(manager, object : g3.a() {
                override fun d(frameInfoData: ByteArray): PreviewStreamInfo = PreviewStreamInfo(
                    PreviewInfoDataBean(
                        byteArrSrc = frameInfoData,
                        byteArrDst = ByteArray(192 * 256 * 3 / 2),
                        byteArrYuvAppendData = ByteArray(40),
                    ),
                    null,
                )
            })
            manager.R().invoke(7, frameInfo(NORMAL_SIZE, ByteArray(NORMAL_SIZE), 19))

            assertTrue(
                "handoff failure must not suppress app-side raw packet publication",
                delivered.await(2, TimeUnit.SECONDS),
            )
            val processingFailure = manager.lastStreamProcessingFailure
            assertTrue(
                "expected the handoff exception to be retained, actual=$processingFailure",
                processingFailure.startsWith("handoff_failure="),
            )
        } finally {
            PreviewManagerIIAppBinding.unbind(manager)
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
            Z2.g.a.d1(previousDetectedType)
            Z2.g.a.D0(previousCachedType)
        }
    }

    @Test fun scheduledPacketKeepsItsOwnBytesAndCallbackIdentityWhenNextPacketArrives() {
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        val previousDetectedType = Z2.g.a.V()
        val previousCachedType = Z2.g.a.r()
        val manager = installBoundManager()
        val processorEntered = CountDownLatch(1)
        val releaseProcessor = CountDownLatch(1)
        val callbackFrames = CopyOnWriteArrayList<com.hik.f2module.F2StreamFrame>()
        try {
            Z2.a.a.u(f3.j().apply { d(12) })
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = "0953060001"))
            Z2.g.a.d1(UsbModuleType.F2)
            Z2.g.a.D0(UsbModuleType.F2)
            PreviewManagerIIAppBinding.bind(manager) { callbackFrames += it }
            assertTrue(manager.refreshF2ProcessorFromRuntimeProfile())
            stopScheduler(manager)
            val processCount = AtomicInteger(0)
            setProcessor(manager, object : g3.a() {
                override fun d(frameInfoData: ByteArray): PreviewStreamInfo {
                    if (processCount.incrementAndGet() == 1) {
                        processorEntered.countDown()
                        assertTrue(releaseProcessor.await(2, TimeUnit.SECONDS))
                    }
                    return PreviewStreamInfo(PreviewInfoDataBean(), null)
                }
            })

            val firstBytes = ByteArray(NORMAL_SIZE) { 0x11 }
            val secondBytes = ByteArray(NORMAL_SIZE) { 0x22 }
            manager.R().invoke(
                71,
                frameInfo(
                    NORMAL_SIZE,
                    firstBytes,
                    frameNum = 101,
                    width = 192,
                    height = 256,
                    frameType = 11,
                    dataType = 12,
                    streamType = 13,
                ),
            )
            val processingThread = Thread { PreviewManagerII.g(manager) }
            processingThread.start()
            assertTrue(processorEntered.await(2, TimeUnit.SECONDS))

            val secondCallbackStarted = CountDownLatch(1)
            val secondCallbackThread = Thread {
                secondCallbackStarted.countDown()
                manager.R().invoke(
                    72,
                    frameInfo(
                        NORMAL_SIZE,
                        secondBytes,
                        frameNum = 202,
                        width = 288,
                        height = 384,
                        frameType = 21,
                        dataType = 22,
                        streamType = 23,
                    ),
                )
            }
            secondCallbackThread.start()
            assertTrue(secondCallbackStarted.await(2, TimeUnit.SECONDS))
            releaseProcessor.countDown()
            processingThread.join(2_000)
            secondCallbackThread.join(2_000)

            assertEquals(1, callbackFrames.size)
            callbackFrames.single().also { frame ->
                assertEquals(71, frame.callbackUserId)
                assertEquals(101L, frame.frameCounter)
                assertEquals(192, frame.width)
                assertEquals(256, frame.height)
                assertEquals(11, frame.frameType)
                assertEquals(12, frame.dataType)
                assertEquals(13, frame.streamType)
                assertArrayEquals(firstBytes, frame.bytes)
            }

            PreviewManagerII.g(manager)

            assertEquals(2, callbackFrames.size)
            callbackFrames[1].also { frame ->
                assertEquals(72, frame.callbackUserId)
                assertEquals(202L, frame.frameCounter)
                assertEquals(288, frame.width)
                assertEquals(384, frame.height)
                assertEquals(21, frame.frameType)
                assertEquals(22, frame.dataType)
                assertEquals(23, frame.streamType)
                assertArrayEquals(secondBytes, frame.bytes)
            }
        } finally {
            releaseProcessor.countDown()
            PreviewManagerIIAppBinding.unbind(manager)
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
            Z2.g.a.d1(previousDetectedType)
            Z2.g.a.D0(previousCachedType)
        }
    }

    @Test fun processorRuntimeAndLinkageFailuresDoNotPublishFreshAcceptedFrames() {
        val previousProfile = Z2.a.a.p()
        val previousModuleInfo = Z2.g.a.U()
        val previousDetectedType = Z2.g.a.V()
        val previousCachedType = Z2.g.a.r()
        val manager = installBoundManager()
        val callbackCount = AtomicInteger(0)
        try {
            Z2.a.a.u(f3.j().apply { d(12) })
            Z2.g.a.c1(previousModuleInfo.copy(moduleID = "0953060001"))
            Z2.g.a.d1(UsbModuleType.F2)
            Z2.g.a.D0(UsbModuleType.F2)
            PreviewManagerIIAppBinding.bind(manager) { callbackCount.incrementAndGet() }
            assertTrue(manager.refreshF2ProcessorFromRuntimeProfile())
            stopScheduler(manager)
            val processCount = AtomicInteger(0)
            setProcessor(manager, object : g3.a() {
                override fun d(frameInfoData: ByteArray): PreviewStreamInfo = when (processCount.incrementAndGet()) {
                    1 -> PreviewStreamInfo(PreviewInfoDataBean(), null)
                    2 -> throw IllegalStateException("deterministic processor runtime failure")
                    else -> throw LinkageError("deterministic processor linkage failure")
                }
            })

            manager.R().invoke(7, frameInfo(NORMAL_SIZE, ByteArray(NORMAL_SIZE) { 1 }, 301))
            PreviewManagerII.g(manager)
            assertEquals(1, callbackCount.get())
            assertNotNull(PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 301L))

            manager.R().invoke(8, frameInfo(NORMAL_SIZE, ByteArray(NORMAL_SIZE) { 2 }, 302))
            PreviewManagerII.g(manager)
            assertEquals("RuntimeException must not publish an accepted frame", 1, callbackCount.get())
            assertEquals(null, PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 302L))
            assertTrue(manager.lastStreamProcessingFailure.contains("IllegalStateException"))

            manager.R().invoke(9, frameInfo(NORMAL_SIZE, ByteArray(NORMAL_SIZE) { 3 }, 303))
            PreviewManagerII.g(manager)
            assertEquals("LinkageError must not publish an accepted frame", 1, callbackCount.get())
            assertEquals(null, PreviewManagerIIAppBinding.latestOfficialProcessedFrame(manager, 303L))
            assertTrue(manager.lastStreamProcessingFailure.contains("LinkageError"))
        } finally {
            PreviewManagerIIAppBinding.unbind(manager)
            Z2.a.a.u(previousProfile)
            Z2.g.a.c1(previousModuleInfo)
            Z2.g.a.d1(previousDetectedType)
            Z2.g.a.D0(previousCachedType)
        }
    }

    @Test fun officialClassSetDoesNotContainKotlinOrAppCallbackArtifacts() {
        assertFalse(PreviewManagerII::class.java.declaredClasses.any { it.simpleName.contains("Companion") })
        assertFalse(PreviewManagerII::class.java.declaredMethods.any { it.name == "createF2ModuleStreamCallback" })
        assertTrue(PreviewManagerII::class.java.declaredMethods.any { it.name == "R" })
        assertTrue(PreviewManagerII::class.java.declaredMethods.any { it.name == "U" })
    }

    private fun waitUntil(predicate: () -> Boolean) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(1)
        while (System.nanoTime() < deadline) {
            if (predicate()) return
            Thread.sleep(5)
        }
    }

    private fun installBoundManager(): PreviewManagerII {
        val method = PreviewManagerIIAppBinding::class.java.getDeclaredMethod(
            "installLifecycle",
            Lifecycle::class.java,
        ).apply { isAccessible = true }
        return method.invoke(null, testLifecycle()) as PreviewManagerII
    }

    private fun processor(manager: PreviewManagerII): Any? =
        PreviewManagerII::class.java.getDeclaredField("D").apply { isAccessible = true }.get(manager)

    private fun setProcessor(manager: PreviewManagerII, processor: g3.a) {
        PreviewManagerII::class.java.getDeclaredField("D").apply { isAccessible = true }.set(manager, processor)
    }

    private fun setProcessorProfile(manager: PreviewManagerII, profile: f3.k) {
        PreviewManagerII::class.java.getDeclaredField("processorProfile")
            .apply { isAccessible = true }
            .set(manager, profile)
    }

    private fun captureProcessorProfile(manager: PreviewManagerII, profile: f3.k) {
        PreviewManagerII::class.java.getDeclaredMethod("captureProcessorProfile", f3.k::class.java)
            .apply { isAccessible = true }
            .invoke(manager, profile)
    }

    private fun stopScheduler(manager: PreviewManagerII) {
        PreviewManagerII::class.java.getDeclaredMethod("e1")
            .apply { isAccessible = true }
            .invoke(manager)
    }

    private fun frameInfo(
        size: Int,
        bytes: ByteArray,
        frameNum: Int,
        width: Int = 0,
        height: Int = 0,
        frameType: Int = 5,
        dataType: Int = 6,
        streamType: Int = 7,
    ): USB_FRAME_INFO = USB_FRAME_INFO().apply {
        dwBufSize = size
        pBuf = bytes
        nFrameNum = frameNum
        dwWidth = width
        dwHeight = height
        dwFrameType = frameType
        dwDataType = dataType
        dwStreamType = streamType
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

    private companion object {
        private const val NORMAL_SIZE = 203_720
        private const val OFFLINE_SIZE = 183_496
    }

}
