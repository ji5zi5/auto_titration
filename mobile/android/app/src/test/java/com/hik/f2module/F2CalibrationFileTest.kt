package com.hik.f2module

import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.Interface.USB_COMMON_COND
import com.hcusbsdk.Interface.USB_CTRL_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_DEVICE_INFO
import com.hcusbsdk.Interface.USB_DEVICE_REG_RES
import com.hcusbsdk.Interface.USB_GET_THERMOMETRY_CALIBRATION_FILE
import com.hcusbsdk.Interface.USB_SYSTEM_DEVICE_INFO
import com.hcusbsdk.Interface.USB_STREAM_CALLBACK_PARAM
import com.hcusbsdk.Interface.USB_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_THERMOMETRY_CALIBRATION_FILE
import com.hcusbsdk.Interface.USB_USER_LOGIN_INFO
import com.hcusbsdk.Interface.USB_VIDEO_PARAM
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.security.MessageDigest
import java.util.concurrent.AbstractExecutorService
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class F2CalibrationFileTest {
    @get:Rule
    val tmp = TemporaryFolder()

    @Before
    fun resetSharedCalibrationStateBeforeTest() {
        F2UsbModuleHelper.INSTANCE.resetCalibrationAcquisitionStateForTests()
        F2UsbModuleHelper.INSTANCE.installSessionCloseOperationsForTests(null, null)
        F2UsbModuleHelper.INSTANCE.installCalibrationPrefetchExecutorFactoryForTests(null)
        F2UsbModuleHelper.INSTANCE.installBeforeCalibrationNativeCommandHookForTests(null)
        JavaInterface.getInstance().resetStreamCallbackRegistrationsForTest()
        JavaInterface.getInstance().resetJniStartStreamCallbackInvokerForTest()
        installCalibrationSession(-1, null, null)
    }

    @After
    fun resetSharedCalibrationState() {
        installCalibrationSession(-1, null, null)
        F2UsbModuleHelper.INSTANCE.resetCalibrationAcquisitionStateForTests()
        F2UsbModuleHelper.INSTANCE.installSessionCloseOperationsForTests(null, null)
        F2UsbModuleHelper.INSTANCE.installCalibrationPrefetchExecutorFactoryForTests(null)
        F2UsbModuleHelper.INSTANCE.installBeforeCalibrationNativeCommandHookForTests(null)
        JavaInterface.getInstance().resetStreamCallbackRegistrationsForTest()
        JavaInterface.getInstance().resetJniStartStreamCallbackInvokerForTest()
        JavaInterface.getInstance().configureNativeBridge(ResetNativeBridge)
    }

    @Test
    fun acquisitionRequiresLoggedInUserAndSelectedDevice() {
        val fake = FakeCalibrationBridge(byteArrayOf(1, 2, 3))
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(-1, null, null)

        val result = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(tmp.newFolder("cache"))

        assertFalse(result.ok)
        assertEquals("login_required_for_command_2054", result.reason)
        assertEquals(0, fake.calls)
    }

    @Test
    fun staleSessionTokenBlocksCalibrationAndMeasurementSettingCommands() {
        val fake = FakeCalibrationBridge(byteArrayOf(1, 2, 3))
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(41, device(serial = "TOKEN-OLD"), systemInfo())
        val token = requireNotNull(F2UsbModuleHelper.INSTANCE.activeSessionToken())

        F2UsbModuleHelper.INSTANCE.resetCalibrationAcquisitionStateForTests()

        assertFalse(F2UsbModuleHelper.INSTANCE.isSessionTokenCurrent(token))
        val calibration = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(
            tmp.newFolder("stale-token"),
            token,
        )
        val settings = F2UsbModuleHelper.INSTANCE.acquireOfficialF2MeasurementSettingsOnce(token)
        assertFalse(calibration.ok)
        assertEquals("stale_f2_session_before_command_2054", calibration.reason)
        assertFalse(settings.ok)
        assertEquals("stale_f2_session_before_commands_2018_2020_2080", settings.reason)
        assertEquals(0, fake.calls)
    }

    @Test
    fun explicitAcquisitionWritesOfficialVisibleFileNameAndProvenance() {
        val bytes = byteArrayOf(5, 4, 3, 2)
        val fake = FakeCalibrationBridge(bytes)
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(12, device(serial = "SER/IAL 1"), systemInfo())

        val result = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(tmp.newFolder("cache"))

        assertTrue(result.ok)
        val file = result.file
        assertNotNull(file)
        assertEquals("HM-Calibration_SER_IAL_1.dat", file!!.name)
        assertArrayEquals(bytes, file.readBytes())
        val provenance = result.provenance
        assertNotNull(provenance)
        assertEquals(bytes.size, provenance!!.length)
        assertEquals(USB_GET_THERMOMETRY_CALIBRATION_FILE, provenance.nativeCommand)
        assertEquals(F2CalibrationCacheState.FETCHED.state, provenance.cacheState)
        assertEquals(F2_CALIBRATION_FORMAT_STATE_UNVERIFIED_2054, provenance.formatState)
        assertEquals(1, fake.calls)
        assertEquals(12, fake.lastUserId)
        assertEquals(1, fake.lastCond?.byChannelID?.toInt())
    }

    @Test
    fun prefetchRunsOnlyAtExactTenthEligiblePreviewAndOnlyOncePerSession() {
        val fake = FakeCalibrationBridge(byteArrayOf(9, 9))
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(22, device(serial = "PREFETCH-EXACT"), systemInfo())
        val cache = tmp.newFolder("prefetch-exact")

        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(cache, 9L)
        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(cache, 10L, diagnoseMode = true)
        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(cache, 10L, previewPathEligible = false)
        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(cache, 11L)
        assertEquals(0, fake.calls)

        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(cache, 10L)
        val result = F2UsbModuleHelper.INSTANCE.awaitCalibrationPrefetchForTests()
        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(cache, 10L)

        assertTrue(result!!.ok)
        assertEquals(F2CalibrationCacheState.FETCHED.state, result.provenance?.cacheState)
        assertEquals(1, fake.calls)
        assertEquals(result, F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult())
    }

    @Test
    fun prefetchPublishesIdentityCacheHitWithoutNativeCallOrEnqueue() {
        val fake = FakeCalibrationBridge(byteArrayOf(4, 2))
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(23, device(serial = "CACHE/HIT"), systemInfo())
        val cache = tmp.newFolder("prefetch-cache-hit")
        val cached = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache).file!!
        assertEquals(1, fake.calls)
        F2UsbModuleHelper.INSTANCE.resetCalibrationAcquisitionStateForTests()
        fake.calls = 0

        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(cache, 10L)

        val result = F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult()
        assertTrue(result!!.ok)
        assertEquals(cached, result.file)
        assertEquals(F2CalibrationCacheState.HIT.state, result.provenance?.cacheState)
        assertEquals(0, fake.calls)
    }

    @Test
    fun synchronousAcquisitionRemainsW9MissingFileFallback() {
        val fake = FakeCalibrationBridge(byteArrayOf(4, 2))
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(24, device(serial = "W9-FALLBACK"), systemInfo())
        val cache = tmp.newFolder("w9-fallback")

        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(cache, 9L)
        assertEquals(0, fake.calls)

        val result = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)

        assertTrue(result.ok)
        assertEquals(F2CalibrationCacheState.FETCHED.state, result.provenance?.cacheState)
        assertEquals(1, fake.calls)
        assertEquals(result, F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult())
    }

    @Test
    fun measurementBoundaryAcquisitionUsesIdentityCacheAndDoesNotRefetchSameIdentity() {
        val bytes = byteArrayOf(8, 6, 7, 5)
        val fake = FakeCalibrationBridge(bytes)
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(70, device(serial = "CACHE-ID"), systemInfo())
        val cache = tmp.newFolder("identity-cache")

        val first = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)
        val second = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)

        assertTrue(first.ok)
        assertTrue(second.ok)
        assertEquals(F2CalibrationCacheState.FETCHED.state, first.provenance?.cacheState)
        assertEquals(F2CalibrationCacheState.HIT.state, second.provenance?.cacheState)
        assertEquals(first.provenance?.identityKey, second.provenance?.identityKey)
        assertEquals(bytes.size, second.provenance?.length)
        assertEquals(sha256Hex(bytes), second.provenance?.sha256)
        assertEquals(1, fake.calls)
        assertEquals(second, F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult())
    }

    @Test
    fun identityOnlyLegacySidecarWithChangedPayloadIsMissAndRefetched() {
        val original = FakeCalibrationBridge(byteArrayOf(1, 2, 3))
        JavaInterface.getInstance().configureNativeBridge(original)
        installCalibrationSession(71, device(serial = "STALE-SIDECAR"), systemInfo())
        val cache = tmp.newFolder("legacy-sidecar")
        val first = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)
        assertTrue(first.ok)

        val crashedPayload = byteArrayOf(9, 9, 9, 9)
        val file = first.file!!
        file.writeBytes(crashedPayload)
        sidecarFor(file).writeText(first.provenance!!.identityKey, Charsets.UTF_8)
        val refetch = FakeCalibrationBridge(byteArrayOf(7, 7))
        JavaInterface.getInstance().configureNativeBridge(refetch)

        val second = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)

        assertTrue(second.ok)
        assertEquals(F2CalibrationCacheState.FETCHED.state, second.provenance?.cacheState)
        assertArrayEquals(byteArrayOf(7, 7), second.file!!.readBytes())
        assertEquals(1, refetch.calls)
    }

    @Test
    fun missingSidecarWithExistingPayloadIsMissAndRefetched() {
        val original = FakeCalibrationBridge(byteArrayOf(6, 1, 6))
        JavaInterface.getInstance().configureNativeBridge(original)
        installCalibrationSession(75, device(serial = "MISSING-SIDECAR"), systemInfo())
        val cache = tmp.newFolder("missing-sidecar")
        val first = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)
        assertTrue(first.ok)
        assertTrue(sidecarFor(first.file!!).delete())
        val refetch = FakeCalibrationBridge(byteArrayOf(1, 6, 1))
        JavaInterface.getInstance().configureNativeBridge(refetch)

        val second = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)

        assertTrue(second.ok)
        assertEquals(F2CalibrationCacheState.FETCHED.state, second.provenance?.cacheState)
        assertArrayEquals(byteArrayOf(1, 6, 1), second.file!!.readBytes())
        assertEquals(1, refetch.calls)
    }

    @Test
    fun sidecarLengthMismatchIsMissAndRefetched() {
        val bytes = byteArrayOf(1, 3, 5)
        val fake = FakeCalibrationBridge(bytes)
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(72, device(serial = "LENGTH-MISMATCH"), systemInfo())
        val cache = tmp.newFolder("length-mismatch")
        val first = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)
        assertTrue(first.ok)
        sidecarFor(first.file!!).writeText(
            sidecarText(first.provenance!!.identityKey, length = bytes.size + 1, sha256 = sha256Hex(bytes)),
            Charsets.UTF_8,
        )
        val refetch = FakeCalibrationBridge(byteArrayOf(2, 4, 6, 8))
        JavaInterface.getInstance().configureNativeBridge(refetch)

        val second = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)

        assertTrue(second.ok)
        assertEquals(F2CalibrationCacheState.FETCHED.state, second.provenance?.cacheState)
        assertArrayEquals(byteArrayOf(2, 4, 6, 8), second.file!!.readBytes())
        assertEquals(1, refetch.calls)
    }

    @Test
    fun sidecarDigestMismatchIsMissAndRefetched() {
        val bytes = byteArrayOf(2, 3, 5, 7)
        val fake = FakeCalibrationBridge(bytes)
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(73, device(serial = "DIGEST-MISMATCH"), systemInfo())
        val cache = tmp.newFolder("digest-mismatch")
        val first = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)
        assertTrue(first.ok)
        sidecarFor(first.file!!).writeText(
            sidecarText(first.provenance!!.identityKey, length = bytes.size, sha256 = "0".repeat(64)),
            Charsets.UTF_8,
        )
        val refetch = FakeCalibrationBridge(byteArrayOf(8, 6, 4))
        JavaInterface.getInstance().configureNativeBridge(refetch)

        val second = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)

        assertTrue(second.ok)
        assertEquals(F2CalibrationCacheState.FETCHED.state, second.provenance?.cacheState)
        assertArrayEquals(byteArrayOf(8, 6, 4), second.file!!.readBytes())
        assertEquals(1, refetch.calls)
    }

    @Test
    fun malformedSidecarIsMissAndRefetched() {
        val bytes = byteArrayOf(4, 4)
        val fake = FakeCalibrationBridge(bytes)
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(74, device(serial = "MALFORMED-SIDECAR"), systemInfo())
        val cache = tmp.newFolder("malformed-sidecar")
        val first = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)
        assertTrue(first.ok)
        sidecarFor(first.file!!).writeText(
            sidecarText(first.provenance!!.identityKey, length = bytes.size, sha256 = "not-a-sha"),
            Charsets.UTF_8,
        )
        val refetch = FakeCalibrationBridge(byteArrayOf(5, 5, 5))
        JavaInterface.getInstance().configureNativeBridge(refetch)

        val second = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)

        assertTrue(second.ok)
        assertEquals(F2CalibrationCacheState.FETCHED.state, second.provenance?.cacheState)
        assertArrayEquals(byteArrayOf(5, 5, 5), second.file!!.readBytes())
        assertEquals(1, refetch.calls)
    }

    @Test
    fun zeroLengthIdentityCacheDoesNotSuppressMeasurementBoundaryFetch() {
        val bytes = byteArrayOf(2, 7)
        val fake = FakeCalibrationBridge(bytes)
        val cache = tmp.newFolder("empty-cache")
        val emptyCacheFile = cache.resolve("HM-Calibration_EMPTY.dat")
        emptyCacheFile.createNewFile()
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(25, device(serial = "EMPTY"), systemInfo())

        val result = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)

        assertTrue(result.ok)
        assertEquals(F2CalibrationCacheState.FETCHED.state, result.provenance?.cacheState)
        assertEquals(1, fake.calls)
        assertArrayEquals(bytes, emptyCacheFile.readBytes())
    }

    @Test
    fun measurementBoundaryAcquisitionRefetchesDifferentIdentity() {
        val fake = FakeCalibrationBridge(byteArrayOf(1, 2, 3))
        JavaInterface.getInstance().configureNativeBridge(fake)
        val cache = tmp.newFolder("different-identities")

        installCalibrationSession(80, device(serial = "FIRST-ID"), systemInfo())
        val first = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)
        installCalibrationSession(81, device(serial = "SECOND-ID"), systemInfo())
        val second = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)

        assertTrue(first.ok)
        assertTrue(second.ok)
        assertTrue(first.file!!.name.contains("FIRST-ID"))
        assertTrue(second.file!!.name.contains("SECOND-ID"))
        assertEquals(2, fake.calls)
    }

    @Test
    fun measurementBoundaryAcquisitionMissesCacheWhenSameSerialChangesFirmwareModuleOrDeviceId() {
        val fake = FakeCalibrationBridge(byteArrayOf(3, 1, 4))
        JavaInterface.getInstance().configureNativeBridge(fake)
        val cache = tmp.newFolder("same-serial-different-full-identity")
        val sameSerial = device(serial = "SAME-SERIAL")

        installCalibrationSession(82, sameSerial, systemInfo(module = "F2MOD-A", firmware = "V1_0203_240101", deviceId = "DEV-A"))
        val first = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)
        installCalibrationSession(83, sameSerial, systemInfo(module = "F2MOD-B", firmware = "V1_0203_250202", deviceId = "DEV-B"))
        val second = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)

        assertTrue(first.ok)
        assertTrue(second.ok)
        assertEquals("HM-Calibration_SAME-SERIAL.dat", first.file!!.name)
        assertEquals(first.file, second.file)
        assertEquals(F2CalibrationCacheState.FETCHED.state, first.provenance?.cacheState)
        assertEquals(F2CalibrationCacheState.FETCHED.state, second.provenance?.cacheState)
        assertTrue(first.provenance?.identityKey != second.provenance?.identityKey)
        assertEquals(2, fake.calls)
    }

    @Test
    fun measurementBoundaryAcquisitionMissesCacheWhenOnlyHardwareVersionChanges() {
        val fake = FakeCalibrationBridge(byteArrayOf(2, 7, 1, 8))
        JavaInterface.getInstance().configureNativeBridge(fake)
        val cache = tmp.newFolder("same-identity-different-hardware")
        val sameSerial = device(serial = "SAME-HARDWARE-SERIAL")

        installCalibrationSession(
            85,
            sameSerial,
            systemInfo(
                module = "F2MOD-SAME",
                firmware = "V1_0203_240101",
                hardware = "HW-A",
                deviceId = "DEV-SAME",
            ),
        )
        val first = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)
        installCalibrationSession(
            86,
            sameSerial,
            systemInfo(
                module = "F2MOD-SAME",
                firmware = "V1_0203_240101",
                hardware = "HW-B",
                deviceId = "DEV-SAME",
            ),
        )
        val second = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(cache)

        assertTrue(first.ok)
        assertTrue(second.ok)
        assertEquals("HM-Calibration_SAME-HARDWARE-SERIAL.dat", first.file!!.name)
        assertEquals(first.file, second.file)
        assertEquals(F2CalibrationCacheState.FETCHED.state, first.provenance?.cacheState)
        assertEquals(F2CalibrationCacheState.FETCHED.state, second.provenance?.cacheState)
        assertTrue(first.provenance?.identityKey?.contains("hardwareVersion=HW-A") == true)
        assertTrue(second.provenance?.identityKey?.contains("hardwareVersion=HW-B") == true)
        assertTrue(first.provenance?.identityKey != second.provenance?.identityKey)
        assertEquals(2, fake.calls)
    }

    @Test
    fun inFlightPrefetchBlockedBeforeCommand2054DoesNotCallNativeAfterLogoutBegins() {
        val events = mutableListOf<String>()
        val before2054 = CountDownLatch(1)
        val logoutStarted = CountDownLatch(1)
        val threadedExecutor = SingleThreadExecutorService(events)
        val fake = FakeCalibrationBridge(byteArrayOf(5, 5), events = events, onLogout = { logoutStarted.countDown() })
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCloseOperations(fake)
        F2UsbModuleHelper.INSTANCE.installCalibrationPrefetchExecutorFactoryForTests { threadedExecutor }
        F2UsbModuleHelper.INSTANCE.installBeforeCalibrationNativeCommandHookForTests {
            before2054.countDown()
            awaitUninterruptibly(logoutStarted, 2, TimeUnit.SECONDS)
        }
        installCalibrationSession(84, device(serial = "STALE-BLOCKED"), systemInfo())

        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(tmp.newFolder("stale-blocked"), 10L)
        assertTrue(before2054.await(2, TimeUnit.SECONDS))
        val closeThread = Thread { F2UsbModuleHelper.INSTANCE.closeSession() }
        closeThread.start()
        closeThread.join(2_000L)
        assertFalse(closeThread.isAlive)
        assertTrue(threadedExecutor.awaitTermination(2, TimeUnit.SECONDS))

        assertEquals(listOf("shutdownNow", "stop", "logout"), events)
        assertEquals(0, fake.calls)
        assertEquals(1, fake.stopCalls)
        assertEquals(1, fake.logoutCalls)
        assertEquals(null, F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult())
        assertEquals(-1, F2UsbModuleHelper.INSTANCE.activeUserId())
        assertEquals(-1, F2UsbModuleHelper.INSTANCE.activeChannel())
    }

    @Test
    fun resetClearsPublishedLatestCalibrationResult() {
        val fake = FakeCalibrationBridge(byteArrayOf(1, 1, 2, 3))
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(30, device(serial = "RESET-LATEST"), systemInfo())

        val result = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(tmp.newFolder("reset"))
        assertEquals(result, F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult())

        F2UsbModuleHelper.INSTANCE.resetCalibrationAcquisitionStateForTests()

        assertEquals(1, fake.calls)
        assertEquals(null, F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult())
    }

    @Test
    fun closeSessionClearsPublishedLatestCalibrationResult() {
        val fake = FakeCalibrationBridge(byteArrayOf(8, 8))
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCloseOperations(fake)
        installCalibrationSession(31, device(serial = "CLOSE-LATEST"), systemInfo())

        val result = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(tmp.newFolder("close"))
        assertEquals(result, F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult())

        F2UsbModuleHelper.INSTANCE.closeSession()

        assertEquals(1, fake.calls)
        assertEquals(1, fake.stopCalls)
        assertEquals(1, fake.logoutCalls)
        assertEquals(null, F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult())
        assertEquals(-1, F2UsbModuleHelper.INSTANCE.activeUserId())
        assertEquals(-1, F2UsbModuleHelper.INSTANCE.activeChannel())
    }

    @Test
    fun closeSessionStopFailurePreservesSessionAndCallbackRegistrationWithoutLogout() {
        val javaInterface = JavaInterface.getInstance()
        val fake = FakeCalibrationBridge(byteArrayOf(9, 9))
        javaInterface.configureNativeBridge(fake)
        val nativeWrappers = mutableListOf<com.hcusbsdk.jni.StreamCallBack_JNI>()
        javaInterface.jniStartStreamCallbackInvoker =
            JavaInterface.JniStartStreamCallbackInvoker { _, _, callback ->
                nativeWrappers += callback
                5
            }
        val selected = device(serial = "STOP-FAIL")
        installCalibrationSession(35, selected, systemInfo())
        var callbackHits = 0
        val callback = FStreamCallBack { _, _ -> callbackHits += 1 }
        assertEquals(
            5,
            javaInterface.USB_StartStreamCallback(
                35,
                USB_STREAM_CALLBACK_PARAM().apply { fnStreamCallBack = callback },
            ),
        )
        val registrationEpoch = javaInterface.activeStreamRegistrationEpochForTest(35)
        val validFrame = com.hcusbsdk.jni.USB_FRAME_INFO().apply {
            pBuf = byteArrayOf(1)
            dwBufSize = 1
        }
        F2UsbModuleHelper.INSTANCE.installSessionCloseOperationsForTests(
            stopChannel = { _, _ ->
                nativeWrappers.single().fStreamCallback_JNI(35, validFrame)
                false
            },
            logout = {
                fake.logoutCalls += 1
                true
            },
        )

        val result = F2UsbModuleHelper.INSTANCE.closeSession()

        assertFalse(result.ok)
        assertTrue(result.summary.contains("stage=USB_StopChannel"))
        assertTrue(result.summary.contains("session_preserved=true"))
        assertEquals(35, F2UsbModuleHelper.INSTANCE.activeUserId())
        assertEquals(1, F2UsbModuleHelper.INSTANCE.activeChannel())
        assertSame(selected, helperField("selectedDeviceInfo"))
        assertSame(callback, javaInterface.m_fnStreamCallBack[35])
        assertEquals(registrationEpoch, javaInterface.activeStreamRegistrationEpochForTest(35))
        assertEquals(0, fake.logoutCalls)
        assertEquals("registration must be suspended before native stop", 0, callbackHits)
        assertEquals(1L, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(1L, javaInterface.streamCallbackRejectedEntryCount)
        assertEquals(0L, javaInterface.streamCallbackDispatchedEntryCount)
        assertTrue(
            javaInterface.lastStreamCallbackRejectedEntryDetail
                .contains("dropReason=stale_registration_epoch"),
        )
        assertEquals(
            "a failed stop must restore thermal delivery before the prior callback is reactivated",
            listOf(0, 1),
            fake.thermalStreamControlValues,
        )
        nativeWrappers.single().fStreamCallback_JNI(35, validFrame)
        assertEquals(1, callbackHits)
        assertEquals(2L, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(1L, javaInterface.streamCallbackRejectedEntryCount)
        assertEquals(1L, javaInterface.streamCallbackDispatchedEntryCount)
    }

    @Test
    fun closeSessionLogoutFailurePreservesLoginForRetryButDoesNotReviveStoppedStream() {
        val javaInterface = JavaInterface.getInstance()
        val fake = FakeCalibrationBridge(byteArrayOf(7, 7))
        javaInterface.configureNativeBridge(fake)
        val selected = device(serial = "LOGOUT-FAIL")
        installCalibrationSession(36, selected, systemInfo())
        val callback = FStreamCallBack { _, _ -> }
        javaInterface.jniStartStreamCallbackInvoker =
            JavaInterface.JniStartStreamCallbackInvoker { _, _, _ -> 6 }
        assertEquals(
            6,
            javaInterface.USB_StartStreamCallback(
                36,
                USB_STREAM_CALLBACK_PARAM().apply { fnStreamCallBack = callback },
            ),
        )
        var logoutSucceeds = false
        F2UsbModuleHelper.INSTANCE.installSessionCloseOperationsForTests(
            stopChannel = { _, _ -> true },
            logout = {
                fake.logoutCalls += 1
                logoutSucceeds
            },
        )

        val failed = F2UsbModuleHelper.INSTANCE.closeSession()

        assertFalse(failed.ok)
        assertTrue(failed.summary.contains("stage=USB_Logout"))
        assertTrue(failed.summary.contains("login_preserved=true"))
        assertEquals(36, F2UsbModuleHelper.INSTANCE.activeUserId())
        assertEquals(-1, F2UsbModuleHelper.INSTANCE.activeChannel())
        assertSame(selected, helperField("selectedDeviceInfo"))
        assertEquals(0L, javaInterface.activeStreamRegistrationEpochForTest(36))
        assertEquals(null, javaInterface.m_fnStreamCallBack[36])

        logoutSucceeds = true
        val retried = F2UsbModuleHelper.INSTANCE.closeSession()

        assertTrue(retried.ok)
        assertEquals(2, fake.logoutCalls)
        assertEquals(-1, F2UsbModuleHelper.INSTANCE.activeUserId())
        assertEquals(-1, F2UsbModuleHelper.INSTANCE.activeChannel())
        assertEquals(null, helperField("selectedDeviceInfo"))
    }

    @Test
    fun failedPrefetchIsOneShotForSession() {
        val fake = FakeCalibrationBridge(byteArrayOf(6, 6), ok = false)
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(32, device(serial = "FAIL-ONCE"), systemInfo())
        val cache = tmp.newFolder("fail-once")

        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(cache, 10L)
        val failed = F2UsbModuleHelper.INSTANCE.awaitCalibrationPrefetchForTests()
        fake.ok = true
        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(cache, 10L)

        assertFalse(failed!!.ok)
        assertEquals(F2CalibrationCacheState.FETCH_FAILED.state, failed.provenance?.cacheState)
        assertEquals(1, fake.calls)
    }

    @Test
    fun staleCloseReopenQueuedPrefetchInvokesNativeZeroTimes() {
        val manualExecutor = ManualExecutorService()
        val fake = FakeCalibrationBridge(byteArrayOf(3, 3))
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCloseOperations(fake)
        F2UsbModuleHelper.INSTANCE.installCalibrationPrefetchExecutorFactoryForTests { manualExecutor }
        installCalibrationSession(40, device(serial = "OLD"), systemInfo())

        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(tmp.newFolder("old"), 10L)
        F2UsbModuleHelper.INSTANCE.closeSession()
        installCalibrationSession(41, device(serial = "NEW"), systemInfo())
        manualExecutor.runNext()

        assertEquals(0, fake.calls)
        assertEquals(null, F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult())
        assertTrue(manualExecutor.shutdownNowCalled)
    }

    @Test
    fun closeSessionCancelsPrefetchExecutorBeforeRealStopLogout() {
        val events = mutableListOf<String>()
        val manualExecutor = ManualExecutorService(events)
        val fake = FakeCalibrationBridge(byteArrayOf(8, 8), events = events)
        JavaInterface.getInstance().configureNativeBridge(fake)
        F2UsbModuleHelper.INSTANCE.installCalibrationPrefetchExecutorFactoryForTests { manualExecutor }
        installCloseOperations(fake)
        installCalibrationSession(33, device(serial = "CLOSE-CANCEL"), systemInfo())

        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(tmp.newFolder("close-cancel"), 10L)
        F2UsbModuleHelper.INSTANCE.closeSession()
        manualExecutor.runNext()

        assertEquals(listOf("shutdownNow", "stop", "logout"), events)
        assertEquals(0, fake.calls)
        assertEquals(1, fake.stopCalls)
        assertEquals(1, fake.logoutCalls)
        assertEquals(null, F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult())
        assertEquals(-1, F2UsbModuleHelper.INSTANCE.activeUserId())
        assertEquals(-1, F2UsbModuleHelper.INSTANCE.activeChannel())
    }

    private fun installCloseOperations(fake: FakeCalibrationBridge) {
        F2UsbModuleHelper.INSTANCE.installSessionCloseOperationsForTests(
            stopChannel = fake::USB_StopChannel,
            logout = fake::USB_Logout,
        )
    }

    private fun installCalibrationSession(
        testUserId: Int,
        deviceInfo: USB_DEVICE_INFO?,
        systemInfo: USB_SYSTEM_DEVICE_INFO?,
    ) {
        F2UsbModuleHelper.userId = testUserId
        F2UsbModuleHelper.channel = if (testUserId != -1 && deviceInfo != null) 1 else -1
        setHelperField("selectedDeviceInfo", deviceInfo)
        setHelperField("selectedSystemDeviceInfo", systemInfo)
    }

    private fun setHelperField(name: String, value: Any?) {
        val field = F2UsbModuleHelper::class.java.getDeclaredField(name)
        field.isAccessible = true
        field.set(F2UsbModuleHelper.INSTANCE, value)
    }

    private fun helperField(name: String): Any? {
        val field = F2UsbModuleHelper::class.java.getDeclaredField(name)
        field.isAccessible = true
        return field.get(F2UsbModuleHelper.INSTANCE)
    }

    private fun device(serial: String) = USB_DEVICE_INFO().apply {
        dwVID = 11231
        dwPID = 0x1234
        szSerialNumber = serial
        szDeviceName = "usb-f2"
    }

    private fun systemInfo(
        module: String = "F2MOD",
        firmware: String = "V1_0203_240101",
        hardware: String = "HW-1",
        deviceId: String = "DEV-ID",
    ) = USB_SYSTEM_DEVICE_INFO().apply {
        bySerialNumber = "SYSTEM-SERIAL"
        byModuleID = module
        byFirmwareVersion = firmware
        byHardwareVersion = hardware
        byDeviceID = deviceId
    }

    private fun sidecarFor(file: java.io.File) = file.parentFile!!.resolve("${file.name}.identity")

    private fun sidecarText(identityKey: String, length: Int, sha256: String): String =
        "version=2\nidentityKey=$identityKey\nlength=$length\nsha256=$sha256\n"

    private fun sha256Hex(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256")
            .digest(bytes)
            .joinToString("") { "%02x".format(it) }

    private fun awaitUninterruptibly(latch: CountDownLatch, timeout: Long, unit: TimeUnit) {
        val deadlineNanos = System.nanoTime() + unit.toNanos(timeout)
        var interrupted = false
        try {
            while (true) {
                val remaining = deadlineNanos - System.nanoTime()
                assertTrue("Timed out waiting for coordinated close", remaining > 0)
                try {
                    if (latch.await(remaining, TimeUnit.NANOSECONDS)) return
                } catch (_: InterruptedException) {
                    interrupted = true
                }
            }
        } finally {
            if (interrupted) Thread.currentThread().interrupt()
        }
    }

    private object ResetNativeBridge : JavaInterface.NativeBridge {
        override fun USB_Init(): Boolean = false
        override fun USB_Cleanup(): Boolean = true
        override fun USB_GetLastError(): Int = -1
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
        override fun USB_GetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_SetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_StopChannel(userId: Int, channel: Int): Boolean = false
        override fun USB_Logout(userId: Int): Boolean = false
    }

    private class FakeCalibrationBridge(
        private val bytes: ByteArray,
        var ok: Boolean = true,
        private val events: MutableList<String>? = null,
        private val onLogout: (() -> Unit)? = null,
    ) : JavaInterface.NativeBridge {
        var calls: Int = 0
        var lastUserId: Int = -1
        var lastCond: USB_COMMON_COND? = null
        var stopCalls: Int = 0
        var logoutCalls: Int = 0
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
        ): Boolean {
            calls += 1
            lastUserId = userId
            lastCond = USB_COMMON_COND().apply { byChannelID = cond.byChannelID }
            out.dwFileLenth = bytes.size
            bytes.copyInto(out.pCalibrationFile)
            return ok
        }

        override fun USB_SetVideoParam(userId: Int, param: USB_VIDEO_PARAM): Boolean = false
        override fun USB_SetThermalStreamParam(userId: Int, param: USB_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_GetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean {
            param.byEnable = 0
            return true
        }

        override fun USB_SetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean {
            thermalStreamControlValues += param.byEnable.toInt()
            return true
        }

        override fun USB_StopChannel(userId: Int, channel: Int): Boolean {
            stopCalls += 1
            events?.add("stop")
            return true
        }

        override fun USB_Logout(userId: Int): Boolean {
            logoutCalls += 1
            events?.add("logout")
            onLogout?.invoke()
            return true
        }
    }

    private class SingleThreadExecutorService(
        private val events: MutableList<String>? = null,
    ) : AbstractExecutorService() {
        @Volatile
        private var shutdown = false
        @Volatile
        private var thread: Thread? = null

        override fun execute(command: Runnable) {
            if (shutdown) return
            thread = Thread(command, "f2-calibration-test-prefetch").also { it.start() }
        }

        override fun shutdown() {
            shutdown = true
        }

        override fun shutdownNow(): MutableList<Runnable> {
            shutdown = true
            events?.add("shutdownNow")
            thread?.interrupt()
            return mutableListOf()
        }

        override fun isShutdown(): Boolean = shutdown

        override fun isTerminated(): Boolean = shutdown && thread?.isAlive != true

        override fun awaitTermination(timeout: Long, unit: TimeUnit): Boolean {
            thread?.join(unit.toMillis(timeout))
            return isTerminated
        }
    }

    private class ManualExecutorService(
        private val events: MutableList<String>? = null,
    ) : AbstractExecutorService() {
        private val commands = ArrayDeque<Runnable>()
        private var shutdown = false
        var shutdownNowCalled: Boolean = false
            private set

        override fun execute(command: Runnable) {
            if (!shutdown) commands.add(command)
        }

        fun runNext(): Boolean {
            val command = commands.removeFirstOrNull() ?: return false
            command.run()
            return true
        }

        override fun shutdown() {
            shutdown = true
        }

        override fun shutdownNow(): MutableList<Runnable> {
            shutdown = true
            shutdownNowCalled = true
            events?.add("shutdownNow")
            val pending = commands.toMutableList()
            commands.clear()
            return pending
        }

        override fun isShutdown(): Boolean = shutdown

        override fun isTerminated(): Boolean = shutdown && commands.isEmpty()

        override fun awaitTermination(timeout: Long, unit: TimeUnit): Boolean = isTerminated
    }
}
