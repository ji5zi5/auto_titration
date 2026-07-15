package com.hcusbsdk

import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.jni.HCUSBSDKByJNI
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class JavaInterfaceOfficialJniLifecycleTest {
    @Test
    fun callbackWrapperUsesTheOfficialUserSlotDirectly() {
        val javaInterface = JavaInterface.getInstance()
        var receivedUserId = -1
        javaInterface.m_fnStreamCallBack[37] = FStreamCallBack { userId, _ -> receivedUserId = userId }

        javaInterface.m_fnStreamCallBack_jni.fStreamCallback_JNI(37, null)

        assertEquals(37, receivedUserId)
        javaInterface.m_fnStreamCallBack[37] = null
        assertThrows(NullPointerException::class.java) {
            javaInterface.m_fnStreamCallBack_jni.fStreamCallback_JNI(37, null)
        }
    }

    @Test
    fun publicStartRejectsMissingCallbackBeforeTouchingJniSingleton() {
        val javaInterface = JavaInterface.getInstance()
        val field = HCUSBSDKByJNI::class.java.getDeclaredField("UsbSdk")
        field.set(null, null)

        assertEquals(-1, javaInterface.USB_StartStreamCallback(3, null))
        assertEquals(-1, javaInterface.USB_StartStreamCallback(3, com.hcusbsdk.Interface.USB_STREAM_CALLBACK_PARAM()))
        assertNull(field.get(null))
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

    @Test
    fun sourcePinsOfficialJniStartStopAndJnaLogoutRoutes() {
        val source = java.io.File("src/main/java/com/hcusbsdk/Interface/JavaInterface.kt").readText()

        assertTrue(source.contains("if (param?.fnStreamCallBack != null) USB_StartStreamCallback_jni(userId, param) else -1"))
        assertTrue(source.contains("m_fnStreamCallBack[userId] = param.fnStreamCallBack"))
        assertTrue(source.contains("dwSize = 0"))
        assertTrue(source.contains("HCUSBSDKByJNI.getInstance().USB_StopChannel(userId, channel)"))
        assertTrue(source.contains("HCUSBSDK.getInstance().USB_Logout(userId)"))
    }
}

private val java.lang.reflect.Method.isSynchronized: Boolean
    get() = java.lang.reflect.Modifier.isSynchronized(modifiers)
