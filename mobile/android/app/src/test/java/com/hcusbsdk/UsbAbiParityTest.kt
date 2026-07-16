package com.hcusbsdk

import com.hcusbsdk.Interface.FStreamCallBack
import com.sun.jna.Structure
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class UsbAbiParityTest {
    @Test
    fun publicDeviceInfoMatchesOfficialViewerFieldSurface() {
        val fields = com.hcusbsdk.Interface.USB_DEVICE_INFO::class.java.fields
            .map { it.name }
            .sorted()

        assertEquals(
            listOf(
                "byHaveAudio",
                "dwFd",
                "dwIndex",
                "dwPID",
                "dwVID",
                "szDeviceName",
                "szManufacturer",
                "szSerialNumber",
            ),
            fields,
        )
    }

    @Test
    fun publicLoginInfoMatchesOfficialViewerFieldSurface() {
        val fields = com.hcusbsdk.Interface.USB_USER_LOGIN_INFO::class.java.fields
            .map { it.name }
            .sorted()

        assertEquals(
            listOf(
                "byLoginMode",
                "dwDevIndex",
                "dwFd",
                "dwPID",
                "dwTimeout",
                "dwVID",
                "szPassword",
                "szSerialNumber",
                "szUserName",
            ),
            fields,
        )
    }

    @Test
    fun publicStreamCallbackParamExposesOnlyOfficialFields() {
        val fields = com.hcusbsdk.Interface.USB_STREAM_CALLBACK_PARAM::class.java.fields
            .map { it.name to it.type }
            .sortedBy { it.first }

        assertEquals(
            listOf(
                "dwStreamType" to Int::class.javaPrimitiveType,
                "fnStreamCallBack" to FStreamCallBack::class.java,
            ),
            fields,
        )
    }

    @Test
    fun publicFrameInfoMatchesOfficialViewerFieldSurfaceAndBufferSize() {
        val fields = com.hcusbsdk.Interface.USB_FRAME_INFO::class.java.fields
            .map { it.name }
            .sorted()

        assertEquals(
            listOf(
                "dwBufSize",
                "dwDataType",
                "dwFrameRate",
                "dwFrameType",
                "dwHeight",
                "dwStreamType",
                "dwWidth",
                "nFrameNum",
                "nStamp",
                "pBuf",
            ),
            fields,
        )
        assertEquals(10 * 1024 * 1024, com.hcusbsdk.Interface.USB_FRAME_INFO().pBuf.size)
    }

    @Test
    fun jniCallbackParamInheritsUsbConfigAndMatchesOfficialFields() {
        val param = com.hcusbsdk.jni.USB_STREAM_CALLBACK_PARAM()
        val config: Any = param

        assertTrue(config is com.hcusbsdk.jni.USB_CONFIG)
        assertArrayEquals(
            arrayOf("byRes", "dwSize", "dwStreamType"),
            param.javaClass.fields.map { it.name }.sorted().toTypedArray(),
        )
        assertEquals(128, param.byRes.size)
    }

    @Test
    fun jniFrameInfoInheritsUsbConfigAndUsesOfficialBufferSizes() {
        val frame = com.hcusbsdk.jni.USB_FRAME_INFO()
        val config: Any = frame

        assertTrue(config is com.hcusbsdk.jni.USB_CONFIG)
        assertArrayEquals(
            arrayOf(
                "byRes",
                "dwBufSize",
                "dwDataType",
                "dwFrameRate",
                "dwFrameType",
                "dwHeight",
                "dwStreamType",
                "dwWidth",
                "nFrameNum",
                "nStamp",
                "pBuf",
            ),
            frame.javaClass.fields.map { it.name }.sorted().toTypedArray(),
        )
        assertEquals(8_294_400, frame.pBuf.size)
        assertEquals(128, frame.byRes.size)
    }

    @Test
    fun jnaOfficialRouteStructFieldOrdersAndReserveLengthsStayPinned() {
        assertEquals(
            listOf("dwSize", "dwStreamType", "fnStreamCallBack", "pUser", "byRes"),
            fieldOrder(com.hcusbsdk.jna.USB_STREAM_CALLBACK_PARAM::class.java),
        )
        assertTrue(source("com/hcusbsdk/jna/HCUSBSDKByJNA.kt").contains("class USB_STREAM_CALLBACK_PARAM : Structure() {"))
        assertTrue(source("com/hcusbsdk/jna/HCUSBSDKByJNA.kt").contains("@JvmField var byRes: ByteArray = ByteArray(128)"))

        assertEquals(
            listOf(
                "nStamp",
                "dwStreamType",
                "dwWidth",
                "dwHeight",
                "dwFrameRate",
                "dwFrameType",
                "dwDataType",
                "nFrameNum",
                "pBuf",
                "dwBufSize",
                "byRes",
            ),
            fieldOrder(com.hcusbsdk.jna.USB_FRAME_INFO::class.java),
        )
        assertTrue(source("com/hcusbsdk/jna/HCUSBSDKByJNA.kt").contains("class USB_FRAME_INFO(pointer: Pointer) : Structure(pointer)"))

        assertEquals(
            listOf("dwSize", "byVideoCodingType", "byRes"),
            fieldOrder(com.hcusbsdk.jna.USB_THERMAL_STREAM_PARAM::class.java),
        )
        assertTrue(source("com/hcusbsdk/jna/HCUSBSDKByJNA.kt").contains("@JvmField var byRes: ByteArray = ByteArray(15)"))
    }

    @Test
    fun jnaDeviceConfigWrappersMatchOfficialViewerAbi() {
        assertEquals(
            listOf("dwSize", "byChannelID", "bySID", "byRes"),
            fieldOrder(com.hcusbsdk.jna.USB_COMMON_COND::class.java),
        )
        assertTrue(
            classSource("com/hcusbsdk/jna/HCUSBSDKByJNA.kt", "USB_COMMON_COND")
                .contains("@JvmField var byRes: ByteArray = ByteArray(6)"),
        )

        assertEquals(
            listOf("lpCondBuffer", "dwCondBufferSize", "lpInBuffer", "dwInBufferSize", "byRes"),
            fieldOrder(com.hcusbsdk.jna.USB_CONFIG_INPUT_INFO::class.java),
        )
        assertTrue(
            classSource("com/hcusbsdk/jna/HCUSBSDKByJNA.kt", "USB_CONFIG_INPUT_INFO")
                .contains("@JvmField var byRes: ByteArray = ByteArray(48)"),
        )

        assertEquals(
            listOf("lpOutBuffer", "dwOutBufferSize", "byRes"),
            fieldOrder(com.hcusbsdk.jna.USB_CONFIG_OUTPUT_INFO::class.java),
        )
        assertTrue(
            classSource("com/hcusbsdk/jna/HCUSBSDKByJNA.kt", "USB_CONFIG_OUTPUT_INFO")
                .contains("@JvmField var byRes: ByteArray = ByteArray(56)"),
        )
    }

    @Test
    fun officialRouteMethodSignaturesStayPinnedAcrossJnaJniAndPublicFacade() {
        assertEquals(
            Int::class.javaPrimitiveType,
            com.hcusbsdk.jna.HCUSBSDKByJNA::class.java.getDeclaredMethod(
                "USB_StartStreamCallback",
                Int::class.javaPrimitiveType,
                com.sun.jna.Pointer::class.java,
            ).returnType,
        )
        assertEquals(
            Boolean::class.javaPrimitiveType,
            com.hcusbsdk.jna.HCUSBSDKByJNA::class.java.getDeclaredMethod(
                "USB_GetDeviceConfig",
                Int::class.javaPrimitiveType,
                Int::class.javaPrimitiveType,
                com.sun.jna.Pointer::class.java,
                com.sun.jna.Pointer::class.java,
            ).returnType,
        )
        assertEquals(
            Int::class.javaPrimitiveType,
            com.hcusbsdk.jni.HCUSBSDKByJNI::class.java.getDeclaredMethod(
                "USB_StartStreamCallback",
                Int::class.javaPrimitiveType,
                com.hcusbsdk.jni.USB_STREAM_CALLBACK_PARAM::class.java,
                com.hcusbsdk.jni.StreamCallBack_JNI::class.java,
            ).returnType,
        )
        assertEquals(
            Int::class.javaPrimitiveType,
            com.hcusbsdk.Interface.JavaInterface::class.java.getDeclaredMethod(
                "USB_StartStreamCallback",
                Int::class.javaPrimitiveType,
                com.hcusbsdk.Interface.USB_STREAM_CALLBACK_PARAM::class.java,
            ).returnType,
        )
    }

    @Test
    fun jniWrapperExposesOfficialDeviceConfigEntryPoint() {
        val method = com.hcusbsdk.jni.HCUSBSDKByJNI::class.java.getDeclaredMethod(
            "USB_GetDeviceConfig",
            Int::class.javaPrimitiveType,
            Int::class.javaPrimitiveType,
            com.hcusbsdk.jni.USB_CONFIG::class.java,
            com.hcusbsdk.jni.USB_CONFIG::class.java,
            com.hcusbsdk.jni.USB_CONFIG::class.java,
        )

        assertEquals(Boolean::class.javaPrimitiveType, method.returnType)
    }
}


private fun fieldOrder(type: Class<out Structure>): List<String> =
    requireNotNull(type.getAnnotation(Structure.FieldOrder::class.java)) { "missing JNA FieldOrder on ${type.name}" }.value.toList()

private fun source(relativeMainPath: String): String =
    java.io.File("src/main/java", relativeMainPath).readText()

private fun classSource(relativeMainPath: String, className: String): String {
    val contents = source(relativeMainPath)
    val start = contents.indexOf("class $className")
    require(start >= 0) { "missing class $className in $relativeMainPath" }
    val nextStructure = contents.indexOf("\n@Structure.FieldOrder", start + className.length)
    return contents.substring(start, if (nextStructure >= 0) nextStructure else contents.length)
}
