package com.hcusbsdk

import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.Interface.USB_FRAME_INFO
import java.util.concurrent.atomic.AtomicReference
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class JavaInterfaceF2PostCallbackContractTest {
    private val javaInterface = JavaInterface.getInstance()

    @After
    fun clearCallbackSlots() {
        synchronized(javaInterface.m_fnStreamCallBack) {
            javaInterface.m_fnStreamCallBack.indices.forEach { javaInterface.m_fnStreamCallBack[it] = null }
        }
    }

    @Test
    fun jniPostCallbackCopiesExactlyDwBufSizeBytesFromNativeFrame() {
        val received = AtomicReference<USB_FRAME_INFO?>()
        javaInterface.m_fnStreamCallBack[12] = FStreamCallBack { _, frame -> received.set(frame) }
        val nativeBytes = byteArrayOf(1, 2, 3, 4, 5, 6)
        val nativeFrame = com.hcusbsdk.jni.USB_FRAME_INFO().apply {
            nStamp = 101
            dwStreamType = 103
            dwWidth = 256
            dwHeight = 344
            dwFrameRate = 25
            dwFrameType = 7
            dwDataType = 8
            nFrameNum = 9
            pBuf = nativeBytes
            dwBufSize = 4
        }

        javaInterface.m_fnStreamCallBack_jni.fStreamCallback_JNI(12, nativeFrame)

        val frame = requireNotNull(received.get())
        assertEquals(101, frame.nStamp)
        assertEquals(103, frame.dwStreamType)
        assertEquals(256, frame.dwWidth)
        assertEquals(344, frame.dwHeight)
        assertEquals(25, frame.dwFrameRate)
        assertEquals(7, frame.dwFrameType)
        assertEquals(8, frame.dwDataType)
        assertEquals(9, frame.nFrameNum)
        assertEquals(4, frame.dwBufSize)
        assertArrayEquals(byteArrayOf(1, 2, 3, 4), frame.pBuf)
    }

    @Test
    fun jnaPostCallbackCopiesExactlyDwBufSizeBytesFromNativePointerFrame() {
        val received = AtomicReference<USB_FRAME_INFO?>()
        javaInterface.m_fnStreamCallBack[13] = FStreamCallBack { _, frame -> received.set(frame) }
        val nativeFrame = JavaInterface.NativeFrameCopySource(
            nStamp = 202,
            dwStreamType = 103,
            dwWidth = 192,
            dwHeight = 256,
            dwFrameRate = 25,
            dwFrameType = 3,
            dwDataType = 4,
            nFrameNum = 14,
            pBuf = byteArrayOf(10, 20, 30, 40, 50, 60),
            dwBufSize = 3,
        )
        val beforeEntryCount = javaInterface.streamCallbackEntryCount

        javaInterface.dispatchJnaFrameCopySourceForHostTest(13, nativeFrame)

        assertEquals(beforeEntryCount + 1, javaInterface.streamCallbackEntryCount)
        val detail = javaInterface.lastStreamCallbackEntryDetail
        assertTrue(detail, detail.contains("route=jna"))
        assertTrue(detail, detail.contains("callbackUserId=13"))
        assertTrue(detail, detail.contains("dwBufSize=3"))
        assertTrue(detail, detail.contains("dwFrameType=3"))
        assertTrue(detail, detail.contains("dwDataType=4"))
        assertTrue(detail, detail.contains("dwStreamType=103"))
        assertTrue(detail, detail.contains("frameNum=14"))
        val frame = requireNotNull(received.get())
        assertEquals(202, frame.nStamp)
        assertEquals(103, frame.dwStreamType)
        assertEquals(192, frame.dwWidth)
        assertEquals(256, frame.dwHeight)
        assertEquals(25, frame.dwFrameRate)
        assertEquals(3, frame.dwFrameType)
        assertEquals(4, frame.dwDataType)
        assertEquals(14, frame.nFrameNum)
        assertEquals(3, frame.dwBufSize)
        assertArrayEquals(byteArrayOf(10, 20, 30), frame.pBuf)
    }

    @Test
    fun postCallbackUsesTheOfficialSlotWithoutNullOrBoundsFallback() {
        val registered = AtomicReference<USB_FRAME_INFO?>()
        javaInterface.m_fnStreamCallBack[14] = FStreamCallBack { _, frame -> registered.set(frame) }

        assertThrows(NullPointerException::class.java) {
            javaInterface.m_fnStreamCallBack_jni.fStreamCallback_JNI(
                15,
                com.hcusbsdk.jni.USB_FRAME_INFO().apply {
                    pBuf = byteArrayOf(1, 2, 3)
                    dwBufSize = 3
                    dwFrameType = 4
                    dwDataType = 5
                    dwStreamType = 103
                    nFrameNum = 6
                },
            )
        }

        assertNotNull(javaInterface.m_fnStreamCallBack[14])
        assertEquals(null, registered.get())
    }
}
