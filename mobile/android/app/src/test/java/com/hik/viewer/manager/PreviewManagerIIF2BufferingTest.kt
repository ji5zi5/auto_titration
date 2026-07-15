package com.hik.viewer.manager

import com.hcusbsdk.Interface.USB_FRAME_INFO
import com.hik.f2module.F2StreamFrame
import java.util.Collections
import java.util.concurrent.CountDownLatch
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
import f3.j

class PreviewManagerIIF2BufferingTest {
    private val manager = PreviewManagerII.INSTANCE

    @Test
    fun callbackCopiesExactlyDwBufSizeWithoutClampingToSourceLength() {
        val callback = manager.createF2ModuleStreamCallback(setOf(NORMAL_SIZE)) { }
            .getFStreamCallBack()!!
        val lifecycleLock = PreviewManagerII::class.java.getDeclaredField("lifecycleLock").let {
            it.isAccessible = true
            it.get(manager)
        }
        val source = ByteArray(NORMAL_SIZE - 7) { (it % 127).toByte() }

        synchronized(lifecycleLock) {
            callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, source, frameNum = 1))
            val packet = PreviewManagerII::class.java.getDeclaredField("normalSlot").let {
                it.isAccessible = true
                it.get(manager)
            }
            assertNotNull(packet)
            val copied = requireNotNull(packet).javaClass.getDeclaredField("bytes").let {
                it.isAccessible = true
                it.get(packet) as ByteArray
            }
            assertEquals(NORMAL_SIZE, copied.size)
            assertArrayEquals(source.copyOf(NORMAL_SIZE), copied)
            manager.closePreviewCallback()
        }
    }

    @Ignore("Local JVM stubs cannot execute production android.util.Size.getWidth() path; covered by Android/instrumented execution gap.")
    @Test
    fun callbackCopiesExactAcceptedSizeAndDispatchesOffCallbackThread() {
        val delivered = CountDownLatch(1)
        val callbackThreads = Collections.synchronizedList(mutableListOf<String>())
        val frames = Collections.synchronizedList(mutableListOf<F2StreamFrame>())
        val streamCallback = manager.createF2ModuleStreamCallback(setOf(NORMAL_SIZE)) { frame ->
            callbackThreads += Thread.currentThread().name
            frames += frame
            delivered.countDown()
        }.getFStreamCallBack()!!

        val source = ByteArray(NORMAL_SIZE - 7) { (it % 127).toByte() }
        val callbackThreadName = Thread.currentThread().name
        streamCallback.fStreamCallback(
            9,
            frameInfo(
                size = NORMAL_SIZE,
                bytes = source,
                frameNum = 44,
                width = 256,
                height = 192,
            ),
        )

        assertTrue(delivered.await(1, TimeUnit.SECONDS))
        assertEquals(1, frames.size)
        assertEquals(9, frames[0].callbackUserId)
        assertEquals(44L, frames[0].frameCounter)
        assertEquals(256, frames[0].width)
        assertEquals(192, frames[0].height)
        assertEquals(NORMAL_SIZE, frames[0].bytes.size)
        assertArrayEquals(source.copyOf(NORMAL_SIZE), frames[0].bytes)
        assertFalse("onFrame must not run on native callback thread", callbackThreads.contains(callbackThreadName))
    }

    @Ignore("Local JVM stubs cannot execute production android.util.Size.getWidth() path; covered by Android/instrumented execution gap.")
    @Test
    fun offlineSlotHasPriorityAndIsConsumedOnceBeforeNormalLatest() {
        val firstEntered = CountDownLatch(1)
        val releaseFirst = CountDownLatch(1)
        val delivered = CountDownLatch(3)
        val frames = Collections.synchronizedList(mutableListOf<F2StreamFrame>())
        val callback = manager.createF2ModuleStreamCallback(PreviewManagerII.officialF2KnownPacketSizes) { frame ->
            frames += frame
            delivered.countDown()
            if (frame.frameCounter == 1L) {
                firstEntered.countDown()
                assertTrue(releaseFirst.await(1, TimeUnit.SECONDS))
            }
        }.getFStreamCallBack()!!

        callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 1), frameNum = 1))
        assertTrue(firstEntered.await(1, TimeUnit.SECONDS))

        callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 2), frameNum = 2))
        callback.fStreamCallback(1, frameInfo(OFFLINE_SIZE, filled(OFFLINE_SIZE, 3), frameNum = 3))
        releaseFirst.countDown()

        assertTrue(delivered.await(2, TimeUnit.SECONDS))
        assertEquals(listOf(1L, 3L, 2L), frames.map { it.frameCounter })
        assertEquals(listOf(NORMAL_SIZE, OFFLINE_SIZE, NORMAL_SIZE), frames.map { it.bytes.size })
    }

    @Ignore("Local JVM stubs cannot execute production android.util.Size.getWidth() path; covered by Android/instrumented execution gap.")
    @Test
    fun officialOfflineMailboxGateRequiresCoding12ModuleType() {
        val firstEntered = CountDownLatch(1)
        val releaseFirst = CountDownLatch(1)
        val delivered = CountDownLatch(2)
        val frames = Collections.synchronizedList(mutableListOf<F2StreamFrame>())
        Z2.a.a.u(j().apply { d(14) })
        val callback = manager.createF2ModuleStreamCallback(PreviewManagerII.officialF2KnownPacketSizes) { frame ->
            frames += frame
            delivered.countDown()
            if (frame.frameCounter == 1L) {
                firstEntered.countDown()
                assertTrue(releaseFirst.await(1, TimeUnit.SECONDS))
            }
        }.getFStreamCallBack()!!

        callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 1), frameNum = 1))
        assertTrue(firstEntered.await(1, TimeUnit.SECONDS))
        callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 2), frameNum = 2))
        callback.fStreamCallback(1, frameInfo(OFFLINE_SIZE, filled(OFFLINE_SIZE, 3), frameNum = 3))
        releaseFirst.countDown()

        assertTrue(delivered.await(2, TimeUnit.SECONDS))
        assertEquals(listOf(1L, 3L), frames.map { it.frameCounter })
        assertEquals(listOf(NORMAL_SIZE, OFFLINE_SIZE), frames.map { it.bytes.size })
    }

    @Ignore("Local JVM stubs cannot execute production android.util.Size.getWidth() path; covered by Android/instrumented execution gap.")
    @Test
    fun officialK2OfflineCallbackExecutesModule12FrameStampSideEffect() {
        Z2.a.a.u(j().apply { d(12) })
        val callback = manager.createF2ModuleStreamCallback(setOf(OFFLINE_SIZE)) { }
            .getFStreamCallBack()!!
        val bytes = filled(OFFLINE_SIZE, 3)
        bytes[40_392 + 20] = 0x34
        bytes[40_392 + 21] = 0x12

        callback.fStreamCallback(1, frameInfo(OFFLINE_SIZE, bytes, frameNum = 3))

        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(1)
        while (System.nanoTime() < deadline && manager.latestExecutedOfflineCallback == null) {
            Thread.sleep(5)
        }
        assertNotNull(manager.latestExecutedOfflineCallback)
        val executed = requireNotNull(manager.latestExecutedOfflineCallback)
        assertEquals(0x1234, executed.second)
    }

    @Ignore("Local JVM stubs cannot execute production android.util.Size.getWidth() path; covered by Android/instrumented execution gap.")
    @Test
    fun normalLatestFrameReplacesOlderQueuedNormalFrames() {
        val firstEntered = CountDownLatch(1)
        val releaseFirst = CountDownLatch(1)
        val delivered = CountDownLatch(2)
        val frames = Collections.synchronizedList(mutableListOf<F2StreamFrame>())
        val callback = manager.createF2ModuleStreamCallback(setOf(NORMAL_SIZE)) { frame ->
            frames += frame
            delivered.countDown()
            if (frame.frameCounter == 1L) {
                firstEntered.countDown()
                assertTrue(releaseFirst.await(1, TimeUnit.SECONDS))
            }
        }.getFStreamCallBack()!!

        callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 1), frameNum = 1))
        assertTrue(firstEntered.await(1, TimeUnit.SECONDS))

        callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 2), frameNum = 2))
        callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 4), frameNum = 4))
        releaseFirst.countDown()

        assertTrue(delivered.await(2, TimeUnit.SECONDS))
        assertEquals(listOf(1L, 4L), frames.map { it.frameCounter })
    }

    @Ignore("Local JVM stubs cannot execute production android.util.Size.getWidth() path; covered by Android/instrumented execution gap.")
    @Test
    fun duplicateNormalFrameContentIsSuppressedUntilContentHashChanges() {
        val delivered = CountDownLatch(2)
        val count = AtomicInteger(0)
        val frames = Collections.synchronizedList(mutableListOf<F2StreamFrame>())
        val callback = manager.createF2ModuleStreamCallback(setOf(NORMAL_SIZE)) { frame ->
            frames += frame
            count.incrementAndGet()
            delivered.countDown()
        }.getFStreamCallBack()!!
        val duplicate = filled(NORMAL_SIZE, 8)

        callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, duplicate, frameNum = 10))
        waitForCount(count, 1)
        callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, duplicate.copyOf(), frameNum = 11))
        Thread.sleep(90)
        assertEquals(1, count.get())

        callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 9), frameNum = 12))
        assertTrue(delivered.await(1, TimeUnit.SECONDS))
        assertEquals(listOf(10L, 12L), frames.map { it.frameCounter })
    }

    @Ignore("Local JVM stubs cannot execute production android.util.Size.getWidth() path; covered by Android/instrumented execution gap.")
    @Test
    fun closeClearsAndStopsThenOpenRestartsConsumerForExistingCallback() {
        val count = AtomicInteger(0)
        val first = CountDownLatch(1)
        val firstCallback = manager.createF2ModuleStreamCallback(setOf(NORMAL_SIZE)) {
            count.incrementAndGet()
            first.countDown()
        }.getFStreamCallBack()!!

        firstCallback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 1), frameNum = 1))
        assertTrue(first.await(1, TimeUnit.SECONDS))
        manager.closePreviewCallback()
        firstCallback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 2), frameNum = 2))
        Thread.sleep(70)
        assertEquals(1, count.get())

        manager.openPreviewCallback()
        firstCallback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 2), frameNum = 2))
        waitForCount(count, 2)
        assertEquals(2, count.get())
    }


    @Test
    fun officialKnownPacketGateExcludesUnprovenSizesAndKeepsExtractedG3DE() {
        assertFalse(98_304 in PreviewManagerII.officialF2KnownPacketSizes)
        assertFalse(221_184 in PreviewManagerII.officialF2KnownPacketSizes)
        assertEquals(
            setOf(41_160, 61_384, 101_320, 183_496, 193_480, 203_720, 400_584),
            PreviewManagerII.officialF2KnownPacketSizes,
        )
    }

    @Test
    fun callbackProcessorComesFromOfficialModuleFactory() {
        val previousProfile = Z2.a.a.p()
        try {
            assertEquals(g3.d::class.java, callbackProcessorClass(moduleId = 12, streamingNew = false))
            assertEquals(g3.e::class.java, callbackProcessorClass(moduleId = 12, streamingNew = true))
            assertEquals(g3.c::class.java, callbackProcessorClass(moduleId = 11, streamingNew = false))
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previousProfile)
        }
    }

    @Test
    fun officialRendererRejectsLumaOnlySubstituteBeforeGyuvHandoff() {
        assertThrows(IllegalArgumentException::class.java) {
            manager.renderOfficialNv12Preview(ByteArray(4), width = 2, height = 2)
        }
    }

    @Test
    fun processorJStoresOfficialCallbackSlotsAndKClearsThem() {
        val processor = g3.d()
        val freezeCallback: (Boolean) -> Unit = {}
        val thawCallback: (Boolean) -> Unit = {}
        val metadataCallback: (Any?) -> Unit = {}
        val overlayCallback: (Any?, Any?, Any?, Any?, Any?) -> Unit = { _, _, _, _, _ -> }
        val osdCallback: (Any?) -> Unit = {}

        processor.j(freezeCallback, thawCallback, metadataCallback, overlayCallback, osdCallback)

        assertEquals(freezeCallback, processor.callbackSlot("freezeCallback"))
        assertEquals(thawCallback, processor.callbackSlot("thawCallback"))
        assertEquals(metadataCallback, processor.callbackSlot("metadataCallback"))
        assertEquals(overlayCallback, processor.callbackSlot("overlayCallback"))
        assertEquals(osdCallback, processor.callbackSlot("osdBgCallback"))

        processor.k()
        assertEquals(null, processor.callbackSlot("freezeCallback"))
        assertEquals(null, processor.callbackSlot("thawCallback"))
        assertEquals(null, processor.callbackSlot("metadataCallback"))
        assertEquals(null, processor.callbackSlot("overlayCallback"))
        assertEquals(null, processor.callbackSlot("osdBgCallback"))
    }

    private fun g3.F2OfficialPacketProcessor.callbackSlot(name: String): Any? {
        val field = g3.F2OfficialPacketProcessor::class.java.getDeclaredField(name)
        field.isAccessible = true
        return field.get(this)
    }

    @Test
    fun validPacketsDoNotResetDelayedOfficialErrorTimerAndTimeoutResetsIt() {
        val invalidNotified = CountDownLatch(2)
        val invalidCount = AtomicInteger(0)
        val invalidSize = AtomicInteger(0)
        val invalidElapsed = AtomicLong(0L)
        PreviewManagerII::class.java.getDeclaredField("invalidPacketStartMs").apply {
            isAccessible = true
            setLong(manager, 0L)
        }
        val callback = manager.createF2ModuleStreamCallback(
            allowedPacketSizes = setOf(NORMAL_SIZE),
            invalidPacketErrorDelayMs = 80L,
            onInvalidPacketSizeTimeout = { packetSize, elapsedMs ->
                invalidCount.incrementAndGet()
                invalidSize.set(packetSize)
                invalidElapsed.set(elapsedMs)
                invalidNotified.countDown()
            },
        ) { }.getFStreamCallBack()!!
        val lifecycleLock = PreviewManagerII::class.java.getDeclaredField("lifecycleLock").let {
            it.isAccessible = true
            it.get(manager)
        }

        synchronized(lifecycleLock) {
            callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 1), frameNum = 1))
            Thread.sleep(55)
            callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, filled(NORMAL_SIZE, 2), frameNum = 2))
            Thread.sleep(40)
            callback.fStreamCallback(1, frameInfo(102_944, filled(102_944, 1), frameNum = 1))
            assertEquals(1, invalidCount.get())

            callback.fStreamCallback(1, frameInfo(102_944, filled(102_944, 2), frameNum = 2))
            assertEquals("the timeout branch resets the official timer to zero", 1, invalidCount.get())
            Thread.sleep(90)
            callback.fStreamCallback(1, frameInfo(102_944, filled(102_944, 2), frameNum = 2))
            manager.closePreviewCallback()
        }

        assertTrue(invalidNotified.await(1, TimeUnit.SECONDS))
        assertEquals(2, invalidCount.get())
        assertEquals(102_944, invalidSize.get())
        assertTrue("elapsed should reflect delayed invalid-size window", invalidElapsed.get() > 80L)
    }

    @Test
    fun unsupportedPacketStillIncrementsFrameCountAndPublishesCopiedSizeBeforeGate() {
        val frameCounterField = PreviewManagerII::class.java.getDeclaredField("frameCounter").apply {
            isAccessible = true
        }
        val before = frameCounterField.getLong(manager)
        val invalidSize = 102_944
        val callback = manager.createF2ModuleStreamCallback(setOf(NORMAL_SIZE)) { }
            .getFStreamCallBack()!!

        callback.fStreamCallback(1, frameInfo(invalidSize, filled(invalidSize, 3), frameNum = 1))

        assertEquals(before + 1L, frameCounterField.getLong(manager))
        assertEquals(invalidSize, Z2.g.a.n())
        manager.closePreviewCallback()
    }

    private fun waitForCount(count: AtomicInteger, expected: Int) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(1)
        while (System.nanoTime() < deadline) {
            if (count.get() >= expected) return
            Thread.sleep(5)
        }
        assertEquals(expected, count.get())
    }

    private fun callbackProcessorClass(moduleId: Int, streamingNew: Boolean): Class<*> {
        Z2.a.a.u(j().apply { d(moduleId) })
        val callback = manager.createF2ModuleStreamCallback(
            allowedPacketSizes = PreviewManagerII.officialF2KnownPacketSizes,
            streamingNew = streamingNew,
        ) { }.getFStreamCallBack()!!
        return callback.javaClass.getDeclaredField("processor").let {
            it.isAccessible = true
            it.get(callback).javaClass
        }
    }

    private fun frameInfo(
        size: Int,
        bytes: ByteArray,
        frameNum: Int,
        width: Int = 0,
        height: Int = 0,
    ): USB_FRAME_INFO = USB_FRAME_INFO().apply {
        dwBufSize = size
        pBuf = bytes
        nFrameNum = frameNum
        dwWidth = width
        dwHeight = height
        dwFrameType = 5
        dwDataType = 6
        dwStreamType = 7
    }

    private fun filled(size: Int, value: Int): ByteArray = ByteArray(size) { value.toByte() }

    private companion object {
        private const val NORMAL_SIZE = 61_384
        private const val OFFLINE_SIZE = 41_160
    }
}
