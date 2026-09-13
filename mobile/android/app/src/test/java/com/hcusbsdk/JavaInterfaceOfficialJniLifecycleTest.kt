package com.hcusbsdk

import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.Interface.USB_STREAM_CALLBACK_PARAM
import com.hcusbsdk.jni.HCUSBSDKByJNI
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class JavaInterfaceOfficialJniLifecycleTest {
    private val javaInterface = JavaInterface.getInstance()

    @Before
    fun resetCallbacks() {
        javaInterface.resetStreamCallbackRegistrationsForTest()
        javaInterface.resetStreamCallbackEntryDiagnostics()
        javaInterface.resetJniStartStreamCallbackInvokerForTest()
        javaInterface.resetJnaStartStreamCallbackInvokerForTest()
        javaInterface.resetJnaCallbackParamWriterForTest()
    }

    @After
    fun restoreJniInvoker() {
        javaInterface.resetStreamCallbackRegistrationsForTest()
        javaInterface.resetStreamCallbackEntryDiagnostics()
        javaInterface.resetJniStartStreamCallbackInvokerForTest()
        javaInterface.resetJnaStartStreamCallbackInvokerForTest()
        javaInterface.resetJnaCallbackParamWriterForTest()
    }

    @Test
    fun globalCallbackWrappersDropLateAndOutOfRangeCallbacksWithoutThrowing() {
        var receivedUserId = -1
        javaInterface.m_fnStreamCallBack[37] = FStreamCallBack { userId, _ -> receivedUserId = userId }

        javaInterface.m_fnStreamCallBack_jni.fStreamCallback_JNI(37, validJniFrame())

        assertEquals(37, receivedUserId)
        assertEquals(1L, javaInterface.streamCallbackDispatchedEntryCount)
        assertEquals(1L, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(0L, javaInterface.streamCallbackRejectedEntryCount)
        javaInterface.m_fnStreamCallBack[37] = null
        javaInterface.m_fnStreamCallBack_jni.fStreamCallback_JNI(37, validJniFrame())
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("route=jni"))
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("disposition=rejected"))
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=slot_cleared_or_unregistered"))

        javaInterface.m_fnStreamCallBack_jni.fStreamCallback_JNI(-1, validJniFrame())
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=slot_out_of_range"))
        javaInterface.m_fnStreamCallBack_jni.fStreamCallback_JNI(10_000, validJniFrame())
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=slot_out_of_range"))

        javaInterface.m_fnStreamCallBack_jna.invoke(37, null, null)
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("route=jna"))
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=frame_pointer_null"))
        javaInterface.dispatchJnaFrameCopySourceForHostTest(10_000, validJnaFrameSource())
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=slot_out_of_range"))
        assertEquals(1L, javaInterface.streamCallbackDispatchedEntryCount)
        assertEquals(6L, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(5L, javaInterface.streamCallbackRejectedEntryCount)
    }

    @Test
    fun publicStartRejectsMissingCallbackBeforeTouchingJniSingleton() {
        val field = HCUSBSDKByJNI::class.java.getDeclaredField("UsbSdk")
        field.set(null, null)

        assertEquals(-1, javaInterface.USB_StartStreamCallback(3, null))
        assertEquals(-1, javaInterface.USB_StartStreamCallback(3, USB_STREAM_CALLBACK_PARAM()))
        assertNull(field.get(null))
    }

    @Test
    fun jniStartValidatesUserIdAgainstActualCallbackSlotIndices() {
        var nativeCallCount = 0
        javaInterface.jniStartStreamCallbackInvoker = JavaInterface.JniStartStreamCallbackInvoker { _, _, _ ->
            nativeCallCount += 1
            4
        }
        val callback = FStreamCallBack { _, _ -> }
        val param = USB_STREAM_CALLBACK_PARAM().apply { fnStreamCallBack = callback }

        assertEquals(-1, javaInterface.USB_StartStreamCallback(-2, param))
        assertEquals(-1, javaInterface.USB_StartStreamCallback(-1, param))
        assertEquals(-1, javaInterface.USB_StartStreamCallback(10_000, param))
        assertEquals(0, nativeCallCount)
        assertNull(javaInterface.m_fnStreamCallBack[0])
        assertNull(javaInterface.m_fnStreamCallBack[9_999])

        assertEquals(4, javaInterface.USB_StartStreamCallback(0, param))
        assertSame(callback, javaInterface.m_fnStreamCallBack[0])
        assertEquals(4, javaInterface.USB_StartStreamCallback(9_999, param))
        assertSame(callback, javaInterface.m_fnStreamCallBack[9_999])
        assertEquals(2, nativeCallCount)
    }

    @Test
    fun successfulJniStartKeepsOfficialCallShapeAndUpdatesBookkeeping() {
        var callbackHits = 0
        val callback = FStreamCallBack { userId, frame ->
            callbackHits += 1
            assertEquals(42, userId)
            assertNotNull(frame)
            assertEquals(1, frame!!.dwBufSize)
        }
        var observedUserId = -1
        var observedStreamType = -1
        var observedSize = -1
        var observedCallback: com.hcusbsdk.jni.StreamCallBack_JNI? = null
        javaInterface.jniStartStreamCallbackInvoker = JavaInterface.JniStartStreamCallbackInvoker { userId, jniParam, jniCallback ->
            observedUserId = userId
            observedStreamType = jniParam.dwStreamType
            observedSize = jniParam.dwSize
            observedCallback = jniCallback
            12
        }

        val result = javaInterface.USB_StartStreamCallback(
            42,
            USB_STREAM_CALLBACK_PARAM().apply {
                dwStreamType = 7
                fnStreamCallBack = callback
            },
        )
        observedCallback!!.fStreamCallback_JNI(42, validJniFrame())

        assertEquals(12, result)
        assertEquals(42, observedUserId)
        assertEquals(7, observedStreamType)
        assertEquals(0, observedSize)
        assertNotSame(javaInterface.m_fnStreamCallBack_jni, observedCallback)
        assertSame(callback, javaInterface.m_fnStreamCallBack[42])
        assertEquals(1, callbackHits)
        assertEquals(42, privateIntField("activeStreamCallbackUserId"))
        assertEquals(12, privateIntField("activeStreamCallbackChannel"))
        assertTrue(javaInterface.lastStreamCallbackEntryDetail.contains("route=jni"))
        assertTrue(javaInterface.lastStreamCallbackEntryDetail.contains("activeUserId=42"))
        assertTrue(javaInterface.lastStreamCallbackEntryDetail.contains("activeChannel=12"))
        assertEquals(1L, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(1L, javaInterface.streamCallbackDispatchedEntryCount)
        assertEquals(0L, javaInterface.streamCallbackRejectedEntryCount)
    }

    @Test
    fun jniStartFalseReturnClearsJustRegisteredSlotAndActiveDiagnostics() {
        javaInterface.jniStartStreamCallbackInvoker = JavaInterface.JniStartStreamCallbackInvoker { _, _, _ -> -1 }
        val callback = FStreamCallBack { _, _ -> }

        val result = javaInterface.USB_StartStreamCallback(
            43,
            USB_STREAM_CALLBACK_PARAM().apply { fnStreamCallBack = callback },
        )

        assertEquals(-1, result)
        assertNull(javaInterface.m_fnStreamCallBack[43])
        assertEquals(-1, privateIntField("activeStreamCallbackUserId"))
        assertEquals(-1, privateIntField("activeStreamCallbackChannel"))
        assertEquals("no_callback_entry", javaInterface.lastStreamCallbackEntryDetail)
        assertTrue(javaInterface.lastStartStreamCallbackDetail.contains("channel=-1"))
    }

    @Test
    fun jniStartThrownFailureClearsJustRegisteredSlotAndActiveDiagnostics() {
        javaInterface.jniStartStreamCallbackInvoker = JavaInterface.JniStartStreamCallbackInvoker { _, _, _ ->
            throw IllegalStateException("native boom")
        }
        val callback = FStreamCallBack { _, _ -> }

        val thrown = assertThrows(IllegalStateException::class.java) {
            javaInterface.USB_StartStreamCallback(
                44,
                USB_STREAM_CALLBACK_PARAM().apply { fnStreamCallBack = callback },
            )
        }

        assertEquals("native boom", thrown.message)
        assertNull(javaInterface.m_fnStreamCallBack[44])
        assertEquals(-1, privateIntField("activeStreamCallbackUserId"))
        assertEquals(-1, privateIntField("activeStreamCallbackChannel"))
        assertEquals("no_callback_entry", javaInterface.lastStreamCallbackEntryDetail)
        assertTrue(javaInterface.lastStartStreamCallbackDetail.contains("official_jni_wrapper_throw"))
    }

    @Test
    fun channelZeroReturnKeepsRegisteredCallbackSlotAndActiveDiagnostics() {
        val callback = FStreamCallBack { _, _ -> }
        javaInterface.jniStartStreamCallbackInvoker = JavaInterface.JniStartStreamCallbackInvoker { _, _, _ -> 0 }

        val result = javaInterface.USB_StartStreamCallback(45, USB_STREAM_CALLBACK_PARAM().apply {
            dwStreamType = 103
            fnStreamCallBack = callback
        })

        assertEquals(0, result)
        assertSame(callback, javaInterface.m_fnStreamCallBack[45])
        assertEquals(45, privateIntField("activeStreamCallbackUserId"))
        assertEquals(0, privateIntField("activeStreamCallbackChannel"))
        assertTrue(javaInterface.lastStartStreamCallbackDetail.contains("channel=0"))
        assertTrue(javaInterface.lastStartStreamCallbackDetail.contains("streamType=103"))
        assertEquals("no_callback_entry", javaInterface.lastStreamCallbackEntryDetail)
    }

    @Test
    fun jniSameUserReuseDropsOldPerStartWrapperAndClearDropsCurrentWrapper() {
        val nativeWrappers = mutableListOf<com.hcusbsdk.jni.StreamCallBack_JNI>()
        javaInterface.jniStartStreamCallbackInvoker =
            JavaInterface.JniStartStreamCallbackInvoker { _, _, callback ->
                nativeWrappers += callback
                nativeWrappers.size
            }
        var firstHits = 0
        var secondHits = 0

        assertEquals(
            1,
            javaInterface.USB_StartStreamCallback(
                46,
                USB_STREAM_CALLBACK_PARAM().apply {
                    fnStreamCallBack = FStreamCallBack { _, _ -> firstHits += 1 }
                },
            ),
        )
        val firstEpoch = javaInterface.activeStreamRegistrationEpochForTest(46)
        assertEquals(
            2,
            javaInterface.USB_StartStreamCallback(
                46,
                USB_STREAM_CALLBACK_PARAM().apply {
                    fnStreamCallBack = FStreamCallBack { _, _ -> secondHits += 1 }
                },
            ),
        )
        val secondEpoch = javaInterface.activeStreamRegistrationEpochForTest(46)

        assertTrue(secondEpoch > firstEpoch)
        nativeWrappers[0].fStreamCallback_JNI(46, validJniFrame())
        assertEquals(0, firstHits)
        assertEquals(0, secondHits)
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=stale_registration_epoch"))
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("registrationEpoch=$firstEpoch"))
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("activeEpoch=$secondEpoch"))
        assertEquals(1L, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(1L, javaInterface.streamCallbackRejectedEntryCount)
        assertEquals(0L, javaInterface.streamCallbackDispatchedEntryCount)

        nativeWrappers[1].fStreamCallback_JNI(46, validJniFrame())
        assertEquals(1, secondHits)
        assertEquals(2L, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(1L, javaInterface.streamCallbackRejectedEntryCount)
        assertEquals(1L, javaInterface.streamCallbackDispatchedEntryCount)

        javaInterface.invalidateStreamCallbackRegistration(46)
        nativeWrappers[1].fStreamCallback_JNI(46, validJniFrame())
        assertEquals(1, secondHits)
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=stale_registration_epoch"))
        assertEquals(3L, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(2L, javaInterface.streamCallbackRejectedEntryCount)
        assertEquals(1L, javaInterface.streamCallbackDispatchedEntryCount)
    }

    @Test
    fun jnaSameUserReuseDropsOldPerStartWrapperAndClearDropsCurrentWrapper() {
        val nativeWrappers = mutableListOf<JavaInterface.HostJnaStreamCallback>()
        var firstHits = 0
        var secondHits = 0

        fun register(callback: com.hcusbsdk.jna.HCUSBSDKByJNA.FStreamCallBack) {
            nativeWrappers += javaInterface.registerJnaStreamCallbackForHostTest(
                userId = 47,
                callback = FStreamCallBack { _, _ -> },
                suppliedJnaCallback = callback,
            )
        }

        register(com.hcusbsdk.jna.HCUSBSDKByJNA.FStreamCallBack { _, _, _ -> firstHits += 1 })
        val firstEpoch = javaInterface.activeStreamRegistrationEpochForTest(47)
        register(com.hcusbsdk.jna.HCUSBSDKByJNA.FStreamCallBack { _, _, _ -> secondHits += 1 })
        val secondEpoch = javaInterface.activeStreamRegistrationEpochForTest(47)

        assertTrue(secondEpoch > firstEpoch)
        nativeWrappers[0].invoke(47, validJnaFrameSource())
        assertEquals(0, firstHits)
        assertEquals(0, secondHits)
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=stale_registration_epoch"))
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("registrationEpoch=$firstEpoch"))
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("activeEpoch=$secondEpoch"))
        assertEquals(1L, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(1L, javaInterface.streamCallbackRejectedEntryCount)
        assertEquals(0L, javaInterface.streamCallbackDispatchedEntryCount)

        nativeWrappers[1].invoke(47, validJnaFrameSource())
        assertEquals(1, secondHits)
        assertEquals(2L, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(1L, javaInterface.streamCallbackRejectedEntryCount)
        assertEquals(1L, javaInterface.streamCallbackDispatchedEntryCount)

        javaInterface.invalidateStreamCallbackRegistration(47)
        nativeWrappers[1].invoke(47, validJnaFrameSource())
        assertEquals(1, secondHits)
        assertTrue(javaInterface.lastStreamCallbackRejectedEntryDetail.contains("dropReason=stale_registration_epoch"))
        assertEquals(3L, javaInterface.streamCallbackTotalEntryCount)
        assertEquals(2L, javaInterface.streamCallbackRejectedEntryCount)
        assertEquals(1L, javaInterface.streamCallbackDispatchedEntryCount)
    }

    @Test
    fun jnaWriteFailureClearsInstalledEpochKeepaliveSlotAndActiveState() {
        var nativeCallCount = 0
        val callback = FStreamCallBack { _, _ -> }

        val thrown = assertThrows(IllegalStateException::class.java) {
            javaInterface.runJnaStartTransactionForHostTest(
                userId = 48,
                callback = callback,
                writeAction = { throw IllegalStateException("write boom") },
                invokeAction = {
                    nativeCallCount += 1
                    3
                },
            )
        }

        assertEquals("write boom", thrown.message)
        assertEquals(0, nativeCallCount)
        assertNull(javaInterface.m_fnStreamCallBack[48])
        assertEquals(0L, javaInterface.activeStreamRegistrationEpochForTest(48))
        assertNull(privateCallbackKeepAlive("jnaStreamCallbackKeepAlives", 48))
        assertEquals(-1, privateIntField("activeStreamCallbackUserId"))
        assertEquals(-1, privateIntField("activeStreamCallbackChannel"))
        assertTrue(javaInterface.lastStartStreamCallbackDetail.contains("official_jna_wrapper_throw"))
        assertTrue(javaInterface.lastStartStreamCallbackDetail.contains("phase=write"))
    }

    @Test
    fun jnaInvocationFailureInvalidatesOnlyItsEpochAndPreservesReplacementRegistration() {
        val original = FStreamCallBack { _, _ -> }
        val replacement = FStreamCallBack { _, _ -> }
        var replacementEpoch = 0L
        val thrown = assertThrows(IllegalArgumentException::class.java) {
            javaInterface.runJnaStartTransactionForHostTest(
                userId = 49,
                callback = original,
                writeAction = {},
                invokeAction = {
                    javaInterface.registerJnaStreamCallbackForHostTest(
                        userId = 49,
                        callback = replacement,
                        suppliedJnaCallback = com.hcusbsdk.jna.HCUSBSDKByJNA.FStreamCallBack { _, _, _ -> },
                    )
                    replacementEpoch = javaInterface.activeStreamRegistrationEpochForTest(49)
                    throw IllegalArgumentException("invoke boom")
                },
            )
        }

        assertEquals("invoke boom", thrown.message)
        assertSame(replacement, javaInterface.m_fnStreamCallBack[49])
        assertTrue(replacementEpoch > 0L)
        assertEquals(replacementEpoch, javaInterface.activeStreamRegistrationEpochForTest(49))
        assertNotNull(privateCallbackKeepAlive("jnaStreamCallbackKeepAlives", 49))
        assertEquals(-1, privateIntField("activeStreamCallbackUserId"))
        assertEquals(-1, privateIntField("activeStreamCallbackChannel"))
        assertTrue(javaInterface.lastStartStreamCallbackDetail.contains("official_jna_wrapper_throw"))
        assertTrue(javaInterface.lastStartStreamCallbackDetail.contains("phase=invoke"))
    }

    @Test
    fun jniWrapperHasOfficialConstantsAndLazySynchronizedSingleton() {
        assertEquals(1_024, HCUSBSDKByJNI.MAX_CONFIG_COND_BUFFER_SIZE)
        assertEquals(1_048_576, HCUSBSDKByJNI.MAX_CONFIG_INPUT_BUFFER_SIZE)
        assertEquals(1_048_576, HCUSBSDKByJNI.MAX_CONFIG_OUTPUT_BUFFER_SIZE)
        assertEquals(8_294_400, HCUSBSDKByJNI.MAX_FRAME_SIZE)
        assertEquals(10, HCUSBSDKByJNI.MAX_ROI_REGIONS)
        assertTrue(HCUSBSDKByJNI::class.java.getDeclaredMethod("getInstance").isSynchronized)

        val first = HCUSBSDKByJNI.getInstance()
        val second = HCUSBSDKByJNI.getInstance()
        assertNotNull(first)
        assertSame(first, second)
    }

    private fun privateIntField(name: String): Int {
        val field = JavaInterface::class.java.getDeclaredField(name)
        field.isAccessible = true
        return field.getInt(javaInterface)
    }

    private fun privateCallbackKeepAlive(name: String, userId: Int): Any? {
        val field = JavaInterface::class.java.getDeclaredField(name)
        field.isAccessible = true
        return (field.get(javaInterface) as Array<*>)[userId]
    }

    private fun validJniFrame() = com.hcusbsdk.jni.USB_FRAME_INFO().apply {
        pBuf = byteArrayOf(1)
        dwBufSize = 1
    }

    private fun validJnaFrameSource() = JavaInterface.NativeFrameCopySource(
        pBuf = byteArrayOf(1),
        dwBufSize = 1,
    )

}

private val java.lang.reflect.Method.isSynchronized: Boolean
    get() = java.lang.reflect.Modifier.isSynchronized(modifiers)
