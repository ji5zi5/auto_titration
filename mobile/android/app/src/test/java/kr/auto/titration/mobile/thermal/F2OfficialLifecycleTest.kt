package kr.auto.titration.mobile.thermal

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import com.hcusbsdk.Interface.USB_FRAME_INFO
import com.hik.f2module.F2UsbModuleApi
import com.hik.f2module.F2UsbModuleHelper
import com.hik.f2module.withTemporaryF2ContextEnumerationCleanup
import com.hik.viewer.manager.PreviewManagerII
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
        Z2.a.a.u(f3.j().apply { d(12) })
        manager.closePreviewCallback()
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

            callback!!.fStreamCallback(7, frameOfSize(rejected, fill = 0x11))
            assertFalse(
                "nonempty packets outside the selected profile must be dropped",
                delivered.await(150, TimeUnit.MILLISECONDS),
            )
            assertEquals("rejected packets must not dispatch", 0, dispatchCount.get())
            assertNull("rejected packets must not publish bytes", receivedBytes.get())

            callback.fStreamCallback(7, frameOfSize(accepted, fill = 0x22))
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
        Z2.a.a.u(f3.j().apply { d(12) })
        manager.closePreviewCallback()
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

            callback!!.fStreamCallback(7, frameOfSize(packetSize, fill = 0x31))
            val firstSlot = PreviewManagerII::class.java.getDeclaredField("s0").apply { isAccessible = true }.get(manager) as ByteArray
            assertEquals(packetSize, firstSlot.size)

            manager.closePreviewCallback()
            manager.closePreviewCallback()
            callback.fStreamCallback(7, frameOfSize(packetSize, fill = 0x32))
            assertFalse(
                "closed preview callback must drop frames from repeated stop/close actions",
                reopenedDelivered.await(150, TimeUnit.MILLISECONDS),
            )
            assertEquals(0, dispatchCount.get())

            manager.openPreviewCallback()
            callback.fStreamCallback(7, frameOfSize(packetSize, fill = 0x33))
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
    fun openUsbModuleIsSingleOfficialOpenAttemptWithoutWrapperRetryLadder() {
        val source = readProjectSource(
            "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt",
            "mobile/android/app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt",
        )
        val method = extractFunctionSource(source, "openUsbModule")

        assertEquals(
            "F2 open must make exactly one bounded helper.openUsbDevice call",
            1,
            Regex("helper\\.openUsbDevice\\s*\\(").findAll(method).count(),
        )
        assertFalse("openUsbModule must not expose a maxRetries wrapper", method.contains("maxRetries"))
        assertFalse("openUsbModule must not track retryIndex", method.contains("retryIndex"))
        assertFalse("openUsbModule must not sleep/back off around open", method.contains("Thread.sleep"))
        assertFalse("openUsbModule must not wrap openUsbDevice in a retry loop", method.contains("while ("))
        assertTrue(
            "openUsbModule stage report must truthfully describe the single attempt",
            method.contains("singleAttempt success="),
        )
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
    fun temporaryContextEnumerationCleanupRunsOnSuccessThrowAndEarlyReturn() {
        val successEvents = mutableListOf<String>()
        val success = withTemporaryF2ContextEnumerationCleanup(
            releaseTemporaryEnumerationConnections = { successEvents += "cleanup" },
        ) {
            successEvents += "enumerated"
            "deviceCountCheck=attempted"
        }

        assertEquals("deviceCountCheck=attempted", success)
        assertEquals(listOf("enumerated", "cleanup"), successEvents)

        val failureEvents = mutableListOf<String>()
        val thrown = runCatching {
            withTemporaryF2ContextEnumerationCleanup(
                releaseTemporaryEnumerationConnections = { failureEvents += "cleanup" },
            ) {
                failureEvents += "enumerated"
                throw IllegalStateException("enum failed")
            }
        }.exceptionOrNull()

        assertTrue(thrown is IllegalStateException)
        assertEquals(listOf("enumerated", "cleanup"), failureEvents)
        assertEquals(listOf("early", "cleanup"), earlyReturnCleanupEvents())
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

    private fun earlyReturnCleanupEvents(): List<String> {
        val events = mutableListOf<String>()
        withTemporaryF2ContextEnumerationCleanup(
            releaseTemporaryEnumerationConnections = { events += "cleanup" },
        ) {
            events += "early"
            return events
        }
    }

    private fun frameOfSize(size: Int, fill: Int): USB_FRAME_INFO = USB_FRAME_INFO().apply {
        dwBufSize = size
        pBuf = ByteArray(size) { fill.toByte() }
        dwWidth = 256
        dwHeight = 344
        dwStreamType = 103
        nFrameNum = 1
    }
}
