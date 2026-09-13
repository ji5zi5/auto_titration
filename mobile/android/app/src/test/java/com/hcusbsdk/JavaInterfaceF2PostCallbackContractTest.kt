package com.hcusbsdk

import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.Interface.USB_FRAME_INFO
import com.sun.jna.Pointer
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class JavaInterfaceF2PostCallbackContractTest {
    private val javaInterface = JavaInterface.getInstance()

    @After
    fun clearCallbackSlots() {
        synchronized(javaInterface.m_fnStreamCallBack) {
            javaInterface.m_fnStreamCallBack.indices.forEach { javaInterface.m_fnStreamCallBack[it] = null }
        }
        javaInterface.resetStreamCallbackEntryDiagnostics()
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
        val beforeTotalCount = javaInterface.streamCallbackTotalEntryCount
        val beforeRejectedCount = javaInterface.streamCallbackRejectedEntryCount

        javaInterface.dispatchJnaFrameCopySourceForHostTest(13, nativeFrame)

        assertEquals(beforeEntryCount + 1, javaInterface.streamCallbackEntryCount)
        assertEquals(beforeTotalCount + 1, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(beforeRejectedCount, javaInterface.streamCallbackRejectedEntryCount)
        val detail = javaInterface.lastStreamCallbackEntryDetail
        assertTrue(detail, detail.contains("route=jna"))
        assertTrue(detail, detail.contains("disposition=dispatched"))
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
    fun jniPostCallbackRejectsDeclaredLengthBeyondAvailableBytesWithoutPadding() {
        val invocationCount = AtomicInteger(0)
        javaInterface.m_fnStreamCallBack[16] = FStreamCallBack { _, _ -> invocationCount.incrementAndGet() }
        val nativeFrame = com.hcusbsdk.jni.USB_FRAME_INFO().apply {
            pBuf = byteArrayOf(1, 2, 3)
            dwBufSize = 4
        }
        val acceptedBefore = javaInterface.streamCallbackEntryCount
        val totalBefore = javaInterface.streamCallbackTotalEntryCount
        val rejectedBefore = javaInterface.streamCallbackRejectedEntryCount

        javaInterface.m_fnStreamCallBack_jni.fStreamCallback_JNI(16, nativeFrame)

        assertEquals(0, invocationCount.get())
        assertEquals(acceptedBefore, javaInterface.streamCallbackEntryCount)
        assertEquals(totalBefore + 1, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(rejectedBefore + 1, javaInterface.streamCallbackRejectedEntryCount)
        val rejectedDetail = javaInterface.lastStreamCallbackRejectedEntryDetail
        assertTrue(rejectedDetail.contains("dropReason=declared_length_exceeds_available_bytes"))
        assertTrue(rejectedDetail.contains("dwBufSize=4"))
        assertTrue(rejectedDetail.contains("availableBytes=3"))
    }

    @Test
    fun byteArrayAdapterRejectsDeclaredLengthBeyondAvailableBytesWithoutPadding() {
        val received = AtomicReference<USB_FRAME_INFO?>()
        val invocationCount = AtomicInteger(0)
        javaInterface.m_fnStreamCallBack[17] = FStreamCallBack { _, frame ->
            invocationCount.incrementAndGet()
            received.set(frame)
        }
        val acceptedBefore = javaInterface.streamCallbackEntryCount
        val totalBefore = javaInterface.streamCallbackTotalEntryCount
        val rejectedBefore = javaInterface.streamCallbackRejectedEntryCount

        javaInterface.dispatchJnaFrameCopySourceForHostTest(
            17,
            JavaInterface.NativeFrameCopySource(
                pBuf = byteArrayOf(1, 2, 3),
                dwBufSize = 4,
            ),
        )

        assertEquals(0, invocationCount.get())
        assertNull(received.get())
        assertEquals(acceptedBefore, javaInterface.streamCallbackEntryCount)
        assertEquals(totalBefore + 1, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(rejectedBefore + 1, javaInterface.streamCallbackRejectedEntryCount)
        val rejectedDetail = javaInterface.lastStreamCallbackRejectedEntryDetail
        assertTrue(rejectedDetail.contains("dropReason=declared_length_exceeds_available_bytes"))
        assertTrue(rejectedDetail.contains("dwBufSize=4"))
        assertTrue(rejectedDetail.contains("availableBytes=3"))
    }

    @Test
    fun jnaPointerFramesRejectNullNegativeAndAboveMaximumDeclaredLengths() {
        val invocationCount = AtomicInteger(0)
        javaInterface.m_fnStreamCallBack[18] = FStreamCallBack { _, _ -> invocationCount.incrementAndGet() }
        val acceptedBefore = javaInterface.streamCallbackEntryCount
        val totalBefore = javaInterface.streamCallbackTotalEntryCount
        val rejectedBefore = javaInterface.streamCallbackRejectedEntryCount

        javaInterface.dispatchJnaFrameDeclarationForHostTest(18, declaredBytes = 1, pointerPresent = false)
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=positive_declared_length_with_null_pointer"))
        javaInterface.dispatchJnaFrameDeclarationForHostTest(18, declaredBytes = -1, pointerPresent = false)
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=negative_declared_length"))
        javaInterface.dispatchJnaFrameDeclarationForHostTest(
            18,
            declaredBytes = 10 * 1024 * 1024 + 1,
            pointerPresent = true,
        )
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=declared_length_exceeds_max"))

        assertEquals(0, invocationCount.get())
        assertEquals(acceptedBefore, javaInterface.streamCallbackEntryCount)
        assertEquals(totalBefore + 3, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(rejectedBefore + 3, javaInterface.streamCallbackRejectedEntryCount)
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("nativeAllocationLengthValidated=false"))
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("availableBytes=unavailable_pointer_abi"))
    }

    @Test
    fun explicitJnaPointerCallbackRejectsMalformedExternalPointerWithoutDereferencingIt() {
        val invocationCount = AtomicInteger(0)
        javaInterface.m_fnStreamCallBack[20] = FStreamCallBack { _, _ -> invocationCount.incrementAndGet() }
        val totalBefore = javaInterface.streamCallbackTotalEntryCount
        val rejectedBefore = javaInterface.streamCallbackRejectedEntryCount

        javaInterface.m_fnStreamCallBack_jna.invoke(20, Pointer.createConstant(1L), null)

        assertEquals(0, invocationCount.get())
        assertEquals(totalBefore + 1, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(rejectedBefore + 1, javaInterface.streamCallbackRejectedEntryCount)
        assertTrue(
            javaInterface.lastStreamCallbackRejectedEntryDetail
                .contains("dropReason=native_allocation_capacity_unprovable"),
        )
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("framePointerPresent=true"))
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("nativeAllocationLengthValidated=false"))
    }

    @Test
    fun legacySharedPostCallbackDropsUnknownSlotWithoutCrashingOrMisrouting() {
        val registered = AtomicReference<USB_FRAME_INFO?>()
        javaInterface.m_fnStreamCallBack[14] = FStreamCallBack { _, frame -> registered.set(frame) }
        val acceptedBefore = javaInterface.streamCallbackEntryCount

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

        assertNotNull(javaInterface.m_fnStreamCallBack[14])
        assertEquals(null, registered.get())
        assertEquals(acceptedBefore, javaInterface.streamCallbackEntryCount)
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("disposition=rejected"))
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=slot_cleared_or_unregistered"))
    }

    @Test
    fun rejectedJniEntryDoesNotOverwriteAcceptedPacketEvidence() {
        javaInterface.m_fnStreamCallBack[19] = FStreamCallBack { _, _ -> }
        javaInterface.m_fnStreamCallBack_jni.fStreamCallback_JNI(
            19,
            com.hcusbsdk.jni.USB_FRAME_INFO().apply {
                pBuf = byteArrayOf(1, 2, 3)
                dwBufSize = 3
            },
        )
        val acceptedCount = javaInterface.streamCallbackEntryCount
        val acceptedDetail = javaInterface.lastStreamCallbackEntryDetail

        javaInterface.m_fnStreamCallBack_jni.fStreamCallback_JNI(
            19,
            com.hcusbsdk.jni.USB_FRAME_INFO().apply {
                pBuf = byteArrayOf(1, 2, 3)
                dwBufSize = 4
            },
        )

        assertEquals(acceptedCount, javaInterface.streamCallbackEntryCount)
        assertEquals(acceptedDetail, javaInterface.lastStreamCallbackEntryDetail)
        assertTrue(acceptedDetail.contains("disposition=dispatched"))
        assertTrue(
            javaInterface.lastStreamCallbackRejectedEntryDetail
                .contains("dropReason=declared_length_exceeds_available_bytes"),
        )
    }
}
