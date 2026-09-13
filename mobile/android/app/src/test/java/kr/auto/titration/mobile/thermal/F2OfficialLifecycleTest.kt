package kr.auto.titration.mobile.thermal

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.USB_FRAME_INFO
import com.hik.f2module.F2UsbModuleApi
import com.hik.f2module.F2UsbModuleHelper
import com.hik.f2module.F2StageResult
import com.hik.f2module.ThermalStreamCtrlState
import com.hik.f2module.replacementStartBlockedResult
import com.hik.f2module.verifyThermalStreamCtrlDisabledBounded
import com.hik.viewer.manager.PreviewManagerII
import com.sun.jna.Callback
import kr.auto.titration.mobile.thermal.PreviewManagerIIAppBinding
import java.lang.reflect.Modifier
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class F2OfficialLifecycleTest {
    @Before
    fun installOfficialPreviewLifecycle() {
        PreviewManagerIIAppBinding.installLifecycle(testLifecycle())
    }

    @Test
    fun productionPreviewCallbackIsJniOnlyAndExactGatesSelectedProfilePacketSizes() {
        val accepted = 203_720
        val rejected = 102_944
        val delivered = CountDownLatch(1)
        val dispatchCount = AtomicInteger(0)
        val receivedBytes = AtomicReference<ByteArray?>()
        val manager = PreviewManagerIIAppBinding.manager()
        val profile = f3.j().apply { d(12) }
        Z2.a.a.u(profile)
        manager.closePreviewCallback()
        manager.openPreviewCallback()
        captureProcessorProfile(manager, profile)
        PreviewManagerIIAppBinding.bind(manager) { frame ->
            receivedBytes.set(frame.bytes)
            dispatchCount.incrementAndGet()
            delivered.countDown()
        }
        val callbackHolder = com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback(null, manager.R())

        try {
            assertNull("production path must not install automatic JNA fallback", callbackHolder.getFStreamCallBackJNA())
            val callback = callbackHolder.getFStreamCallBack()
            assertNotNull(callback)

            callback!!.invoke(7, frameOfSize(rejected, fill = 0x11))
            assertFalse(
                "nonempty packets outside the selected profile must be dropped",
                delivered.await(150, TimeUnit.MILLISECONDS),
            )
            assertEquals("rejected packets must not dispatch", 0, dispatchCount.get())
            assertNull("rejected packets must not publish bytes", receivedBytes.get())

            callback.invoke(7, frameOfSize(accepted, fill = 0x22))
            val slot = PreviewManagerII::class.java.getDeclaredField("s0").apply { isAccessible = true }.get(manager) as ByteArray
            assertEquals(accepted, slot.size)
            assertArrayEquals(ByteArray(accepted) { 0x22 }, slot)
        } finally {
            manager.closePreviewCallback()
        }
    }

    @Test
    fun previewCallbackCloseIsIdempotentAndOpenStartStopReopenDeliversOnlyWhenOpen() {
        val packetSize = 203_720
        val manager = PreviewManagerIIAppBinding.manager()
        val profile = f3.j().apply { d(12) }
        Z2.a.a.u(profile)
        manager.closePreviewCallback()
        manager.openPreviewCallback()
        captureProcessorProfile(manager, profile)
        val firstDelivered = CountDownLatch(1)
        val reopenedDelivered = CountDownLatch(1)
        val dispatchCount = AtomicInteger(0)
        val receivedFills = mutableListOf<Int>()
        PreviewManagerIIAppBinding.bind(manager) { frame ->
            synchronized(receivedFills) { receivedFills += (frame.bytes.first().toInt() and 0xff) }
            val count = dispatchCount.incrementAndGet()
            if (count == 1) firstDelivered.countDown()
            if (count == 2) reopenedDelivered.countDown()
        }
        val callbackHolder = com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback(null, manager.R())

        try {
            val callback = callbackHolder.getFStreamCallBack()
            assertNotNull(callback)

            callback!!.invoke(7, frameOfSize(packetSize, fill = 0x31))
            val firstSlot = PreviewManagerII::class.java.getDeclaredField("s0").apply { isAccessible = true }.get(manager) as ByteArray
            assertEquals(packetSize, firstSlot.size)

            manager.closePreviewCallback()
            manager.closePreviewCallback()
            callback.invoke(7, frameOfSize(packetSize, fill = 0x32))
            assertFalse(
                "closed preview callback must drop frames from repeated stop/close actions",
                reopenedDelivered.await(150, TimeUnit.MILLISECONDS),
            )
            assertEquals(0, dispatchCount.get())

            manager.openPreviewCallback()
            captureProcessorProfile(manager, profile)
            callback.invoke(7, frameOfSize(packetSize, fill = 0x33))
            assertEquals("stale callback must remain rejected after reopen", 0, dispatchCount.get())
            val staleSlot = PreviewManagerII::class.java.getDeclaredField("s0").apply { isAccessible = true }.get(manager) as ByteArray
            assertEquals("stale callback must not populate the reopened mailbox", 0, staleSlot.size)
            val reopenedCallback = manager.R()
            assertNotNull(reopenedCallback)
            assertFalse("reopen must install a callback for the new epoch", callback === reopenedCallback)
            reopenedCallback!!.invoke(7, frameOfSize(packetSize, fill = 0x33))
            val reopenedSlot = PreviewManagerII::class.java.getDeclaredField("s0").apply { isAccessible = true }.get(manager) as ByteArray
            assertEquals(packetSize, reopenedSlot.size)
            assertNull("production path must still avoid automatic JNA fallback", callbackHolder.getFStreamCallBackJNA())
        } finally {
            manager.closePreviewCallback()
        }
    }

    @Test
    fun f2LifecycleEntrypointsAreSerializedAgainstDuplicateActions() {
        val apiMethods = F2UsbModuleApi::class.java.declaredMethods
            .filter { it.name in setOf("openUsbModule", "startStreamPreview", "startStreamPreviewJNA", "stopStreamPreview") }
        assertTrue(apiMethods.isNotEmpty())
        apiMethods.forEach { method ->
            assertTrue("${method.name} should be synchronized", Modifier.isSynchronized(method.modifiers))
        }

        val helperMethods = F2UsbModuleHelper::class.java.declaredMethods
            .filter { it.name in setOf("openUsbDevice", "startStreamPreview", "startStreamPreviewJNA", "stopStreamPreview", "closeSession") }
        assertTrue(helperMethods.isNotEmpty())
        helperMethods.forEach { method ->
            assertTrue("${method.name} should be synchronized", Modifier.isSynchronized(method.modifiers))
        }
    }


    @Test
    fun openUsbModuleMatchesOfficialFiveAttemptLinearBackoff() {
        val source = readProjectSource(
            "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt",
            "mobile/android/app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt",
        )
        val method = extractFunctionSource(source, "openUsbModule")

        assertEquals(
            "official loop keeps one helper call site",
            1,
            Regex("helper\\.openUsbDevice\\s*\\(").findAll(method).count(),
        )
        assertTrue("official open tracks retryIndex", method.contains("retryIndex"))
        assertTrue("official open retries at most five attempts", method.contains("retryIndex < 5"))
        assertTrue("official open uses linear 500ms backoff", method.contains("Thread.sleep(retryIndex * 500L)"))
        assertTrue("official open wraps helper call in do/while", method.contains("do {") && method.contains("while ("))
        assertTrue("stage report must expose final official retry state", method.contains("retryIndex=\$retryIndex"))
    }

    @Test
    fun officialStopThermalControlRetryBoundMatchesDadLifecycle() {
        val helperConstants = Class.forName("com.hik.f2module.F2UsbModuleHelperKt")
        val retryBound = helperConstants.getDeclaredField("OFFICIAL_STOP_THERMAL_CTRL_MAX_RETRIES").apply {
            isAccessible = true
        }.getInt(null)

        assertEquals("DAD stop thermal-control retry/poll bound must stay official", 100, retryBound)
    }

    @Test
    fun officialStopAlwaysWaitsThenCallsNativeStopEvenForMinusOneChannel() {
        val source = readProjectSource(
            "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt",
            "mobile/android/app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt",
        )
        val method = extractFunctionSource(source, "stopStreamPreview")

        assertTrue("official stop waits 100ms after thermal-control polling", method.contains("Thread.sleep(100)"))
        assertTrue("official stop always reaches native channel stop", method.contains("stopChannelOperation(currentUserId, currentChannel)"))
        assertFalse("official APK does not skip stop solely for channel -1", method.contains("currentChannel != -1"))
    }

    @Test
    fun thermalDisableVerificationCountsEveryEnabledPollAndStopsAtExactBound() {
        var polls = 0
        var retries = 0
        val sleeps = mutableListOf<Long>()

        val report = verifyThermalStreamCtrlDisabledBounded(
            initialDisableOk = true,
            maxAttempts = 4,
            getState = {
                polls += 1
                ThermalStreamCtrlState(ok = true, streamEnable = true, byEnable = 1, lastError = 0)
            },
            retryDisable = {
                retries += 1
                true
            },
            getDeviceCount = { 1 },
            contextLabel = "test.package",
            sleep = { sleeps += it },
        )

        assertEquals(4, polls)
        assertEquals(3, retries)
        assertEquals(listOf(10L, 10L, 10L), sleeps)
        assertTrue(report.contains("reason=max_attempts"))
        assertTrue(report.contains("attempts=4"))
        assertTrue(report.contains("unsuccessfulPolls=4"))
    }

    @Test
    fun thermalDisableVerificationRestoresInterruptAndReturnsImmediately() {
        Thread.interrupted()
        var polls = 0
        try {
            val report = verifyThermalStreamCtrlDisabledBounded(
                initialDisableOk = true,
                maxAttempts = 5,
                getState = {
                    polls += 1
                    ThermalStreamCtrlState(ok = true, streamEnable = true, byEnable = 1, lastError = 0)
                },
                retryDisable = { true },
                getDeviceCount = { 1 },
                contextLabel = "test.package",
                sleep = { throw InterruptedException("test interrupt") },
            )

            assertEquals(1, polls)
            assertTrue(report.contains("reason=interrupted"))
            assertTrue(Thread.currentThread().isInterrupted)
        } finally {
            Thread.interrupted()
        }
    }

    @Test
    fun replacementStartIsBlockedOnlyWhenARealActiveChannelFailsToStop() {
        val failedStop = F2StageResult(ok = false, summary = "USB_StopChannel=attempted ok=false error=84")

        for (path in listOf("official_interface_wrapper", "official_jna_wrapper")) {
            val blocked = replacementStartBlockedResult(
                activeChannelBeforeStop = 7,
                stopResult = failedStop,
                startPath = path,
                stageReport = "start",
                profileResolution = null,
            ) ?: error("expected replacement start to be blocked")

            assertFalse(blocked.ok)
            assertFalse(blocked.waitingForFrame)
            assertEquals(7, blocked.channel)
            assertTrue(blocked.reason.contains("existing_active_channel_stop_failed"))
            assertTrue(blocked.stageReport.contains("USB_StartStreamCallback=not_run"))
            assertEquals("blocked_existing_channel_stop_failed", blocked.attemptDiagnostics.single().startStatus)
            assertEquals(path, blocked.attemptDiagnostics.single().startPath)
        }

        assertNull(
            "a no-active channel stop result must preserve the existing start behavior",
            replacementStartBlockedResult(-1, failedStop, "official_interface_wrapper", "start", null),
        )
        assertNull(
            replacementStartBlockedResult(
                7,
                F2StageResult(ok = true, summary = "USB_StopChannel=attempted ok=true"),
                "official_jna_wrapper",
                "start",
                null,
            ),
        )
    }

    @Test
    fun officialInterfaceCallbackAbiExtendsJnaCallbackAndUsesInvoke() {
        val callbackType = FStreamCallBack::class.java
        assertTrue(Callback::class.java.isAssignableFrom(callbackType))
        val method = callbackType.getDeclaredMethod("invoke", Integer.TYPE, USB_FRAME_INFO::class.java)
        assertEquals(Void.TYPE, method.returnType)

        val implementation = Class.forName("com.hik.viewer.manager.PreviewManagerII\$d")
        val invoke = implementation.getDeclaredMethod("invoke", Integer.TYPE, USB_FRAME_INFO::class.java)
        assertTrue(Modifier.isSynchronized(invoke.modifiers))
    }

    @Test
    fun officialStartConfigKeepsSingleStreamTypeAndProfileFieldsForProductionLifecycle() {
        val resolution = HikmicroF2ProfileResolver.resolve("0953060001", "APP_010203_20240101")
        val result = F2UsbModuleApi.resolveStartConfig(resolution)

        assertTrue(result.reason, result.ok)
        val config = result.config ?: error("expected config")
        assertEquals(HikmicroF2Size(256, 344), config.previewSizeValue)
        assertEquals(25, config.frameRate)
        assertEquals(12, config.videoCodingType)
        assertTrue(config.streamingNew)
        assertEquals(setOf(203_720, 183_496), config.allowedPacketSizes)
        assertFalse("profile resolution should not fall back to a universal packet-size ladder", 102_944 in config.allowedPacketSizes)
    }

    @Test
    fun f2ApiWiresInvalidPacketTimeoutWithoutChangingOfficialCallbackShape() {
        val source = readProjectSource(
            "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt",
            "mobile/android/app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt",
        )
        val method = extractFunctionSource(source, "startStreamPreview")
        val nativeStart = extractFunctionSource(source, "startNativeStreamPreviewLocked")

        assertTrue(
            "invalid-packet timeout callback must be attached to the official PreviewManagerII callback holder",
            method.contains("setInvalidPacketSizeTimeoutCallback"),
        )
        assertTrue(
            "fresh starts must clear stale Java callback diagnostics before any bounded-wait classification",
            nativeStart.indexOf("resetStreamCallbackEntryDiagnostics") >
                nativeStart.indexOf("val fStreamCallBack = streamCallback.getFStreamCallBack()") &&
                nativeStart.indexOf("resetStreamCallbackEntryDiagnostics") <
                nativeStart.indexOf("helper.startStreamPreview("),
        )
        assertTrue(
            "official JNI callback shape must remain F2ModuleStreamCallback(null, previewManager.R())",
            method.contains("F2ModuleStreamCallback(null, previewManager.R())"),
        )
        assertFalse(
            "invalid-packet diagnostics must not introduce an automatic JNA fallback",
            method.contains("getFStreamCallBackJNA"),
        )
    }

    @Test
    fun noJavaCallbackAfterAcceptedStartFailsClosedForCelsiusStatus() {
        val status = Mini2RawStreamStatus(
            rawStreamStatus = "blocked_native_stream",
            reason = "waiting for first official F2 callback",
            stageReport = "USB_SET_VIDEO_PARAM=ok; USB_StartStreamCallback=ok channel=0 error=0; startStreamPreview resultCode=1 channel=0",
            fd = 55,
            userId = 7,
            channel = 0,
            callbackEntryCount = 0L,
            callbackEntryDetail = "no_callback_entry",
            rawAvg = 12345.0,
            rawMin = 12000,
            rawMax = 13000,
        )

        val temperatureFields = status.toJsonTemperatureFieldsForTest()

        assertEquals("blocked_native_stream", status.rawStreamStatus)
        assertEquals("native_start_accepted_no_java_callback_after_bounded_wait", status.postStartState)
        assertEquals(0L, status.callbackEntryCount)
        assertEquals("no_callback_entry", status.callbackEntryDetail)
        assertNull(status.deviceTemperatureSummary)
        assertFalse("no callback must not publish Celsius", temperatureFields["celsius_allowed"] as Boolean)
        assertNull(temperatureFields["temperature_avg_c"])
        assertNull(temperatureFields["temperature_min_c"])
        assertNull(temperatureFields["temperature_max_c"])
        assertFalse("full-matrix Celsius remains unproved", temperatureFields["full_matrix_celsius_allowed"] as Boolean)
        assertEquals("unproved_not_emitted", temperatureFields["full_matrix_temperature_status"] as String)
    }


    private fun readProjectSource(vararg relativePaths: String): String {
        val roots = generateSequence(java.io.File(System.getProperty("user.dir"))) { it.parentFile }
            .take(8)
            .toList()
        for (root in roots) {
            for (relativePath in relativePaths) {
                val file = java.io.File(root, relativePath)
                if (file.isFile) return file.readText()
            }
        }
        error("Unable to locate source file in ${roots.joinToString { it.absolutePath }}")
    }

    private fun extractFunctionSource(source: String, functionName: String): String {
        val start = source.indexOf("fun $functionName(")
        require(start >= 0) { "Function $functionName not found" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Function $functionName body not found" }
        var depth = 0
        for (index in bodyStart until source.length) {
            when (source[index]) {
                '{' -> depth += 1
                '}' -> {
                    depth -= 1
                    if (depth == 0) return source.substring(start, index + 1)
                }
            }
        }
        error("Function $functionName body did not close")
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

    private fun frameOfSize(size: Int, fill: Int): USB_FRAME_INFO = USB_FRAME_INFO().apply {
        dwBufSize = size
        pBuf = ByteArray(size) { fill.toByte() }
        dwWidth = 256
        dwHeight = 344
        dwStreamType = 103
        nFrameNum = 1
    }

    private fun captureProcessorProfile(manager: PreviewManagerII, profile: f3.k) {
        PreviewManagerII::class.java.getDeclaredMethod("captureProcessorProfile", f3.k::class.java)
            .apply { isAccessible = true }
            .invoke(manager, profile)
    }
}
