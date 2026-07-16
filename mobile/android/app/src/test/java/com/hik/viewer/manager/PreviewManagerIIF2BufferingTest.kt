package com.hik.viewer.manager

import com.hcusbsdk.Interface.USB_FRAME_INFO
import kr.auto.titration.mobile.thermal.PreviewManagerIIAppBinding
import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback
import java.util.Arrays
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PreviewManagerIIF2BufferingTest {
    private fun newManager() = PreviewManagerII(null, false, false)

    @Test fun officialRReturnsPersistentCallbackAndCopiesExactBytesIntoMailbox() {
        val manager = newManager()
        Z2.a.a.u(f3.j().apply { d(12) })
        manager.openPreviewCallback()
        val callback = manager.R()
        assertNotNull(callback)
        val source = ByteArray(NORMAL_SIZE - 7) { (it % 127).toByte() }
        callback.fStreamCallback(1, frameInfo(NORMAL_SIZE, source, 1))
        val s0 = PreviewManagerII::class.java.getDeclaredField("s0").apply { isAccessible = true }.get(manager) as ByteArray
        assertEquals(NORMAL_SIZE, s0.size)
        assertArrayEquals(source.copyOf(NORMAL_SIZE), s0)
        assertEquals(NORMAL_SIZE, Z2.g.a.n())
        manager.closePreviewCallback()
    }

    @Test fun officialOfflineMailboxGateRequiresCoding12AndUsesR0() {
        val manager = newManager()
        val previous = Z2.a.a.p()
        try {
            Z2.a.a.u(f3.j().apply { d(12) })
            manager.openPreviewCallback()
            manager.R().fStreamCallback(1, frameInfo(OFFLINE_SIZE, ByteArray(OFFLINE_SIZE) { 3 }, 3))
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
            Z2.a.a.u(f3.j().apply { d(12) })
            manager.openPreviewCallback()
            manager.R().fStreamCallback(1, frameInfo(NORMAL_SIZE, ByteArray(NORMAL_SIZE) { 1 }, 1))
            manager.R().fStreamCallback(1, frameInfo(OFFLINE_SIZE, ByteArray(OFFLINE_SIZE) { 2 }, 3))
            val s0 = PreviewManagerII::class.java.getDeclaredField("s0").apply { isAccessible = true }.get(manager) as ByteArray
            val r0 = PreviewManagerII::class.java.getDeclaredField("r0").apply { isAccessible = true }.get(manager) as ByteArray
            assertEquals(NORMAL_SIZE, s0.size)
            assertEquals(OFFLINE_SIZE, r0.size)
        } finally {
            manager.closePreviewCallback()
            Z2.a.a.u(previous)
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

    private fun frameInfo(size: Int, bytes: ByteArray, frameNum: Int): USB_FRAME_INFO = USB_FRAME_INFO().apply {
        dwBufSize = size
        pBuf = bytes
        nFrameNum = frameNum
        dwFrameType = 5
        dwDataType = 6
        dwStreamType = 7
    }

    private companion object {
        private const val NORMAL_SIZE = 203_720
        private const val OFFLINE_SIZE = 183_496
    }
}
