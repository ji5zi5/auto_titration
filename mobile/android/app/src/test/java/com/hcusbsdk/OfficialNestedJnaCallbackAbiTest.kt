package com.hcusbsdk

import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.jna.HCUSBSDKByJNA
import com.hcusbsdk.jna.USB_STREAM_CALLBACK_PARAM
import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback
import com.sun.jna.Callback
import com.sun.jna.Pointer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OfficialNestedJnaCallbackAbiTest {
    @Test
    fun callbackUsesTheOfficialNestedBinaryNameAndInvokeDescriptor() {
        val callbackType = HCUSBSDKByJNA.FStreamCallBack::class.java
        val invoke = callbackType.getDeclaredMethod(
            "invoke",
            Int::class.javaPrimitiveType,
            Pointer::class.java,
            Pointer::class.java,
        )

        assertEquals("com.hcusbsdk.jna.HCUSBSDKByJNA\$FStreamCallBack", callbackType.name)
        assertTrue(Callback::class.java.isAssignableFrom(callbackType))
        assertEquals(Void.TYPE, invoke.returnType)
        assertFalse(callbackType.declaredMethods.any { it.name != "invoke" })
    }

    @Test
    fun holderAndJnaStructureExposeOnlyTheOfficialNestedCallbackType() {
        val callbackType = HCUSBSDKByJNA.FStreamCallBack::class.java
        val holderType = F2ModuleStreamCallback::class.java

        assertEquals(
            listOf(callbackType, FStreamCallBack::class.java),
            holderType.declaredConstructors.single().parameterTypes.toList(),
        )
        assertEquals(callbackType, holderType.getDeclaredField("fStreamCallBackJNA").type)
        assertEquals(callbackType, holderType.getDeclaredMethod("getFStreamCallBackJNA").returnType)
        assertEquals(
            Void.TYPE,
            holderType.getDeclaredMethod("setFStreamCallBackJNA", callbackType).returnType,
        )
        assertEquals(callbackType, USB_STREAM_CALLBACK_PARAM::class.java.getDeclaredField("fnStreamCallBack").type)
        assertTrue(runCatching { Class.forName("com.hcusbsdk.jna.FStreamCallBack_JNA") }.isFailure)
    }
}
