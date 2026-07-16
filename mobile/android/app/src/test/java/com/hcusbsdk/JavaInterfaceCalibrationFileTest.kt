package com.hcusbsdk

import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.Interface.USB_COMMON_COND
import com.hcusbsdk.Interface.USB_CTRL_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_DEVICE_INFO
import com.hcusbsdk.Interface.USB_DEVICE_REG_RES
import com.hcusbsdk.Interface.USB_GET_THERMOMETRY_CALIBRATION_FILE
import com.hcusbsdk.Interface.USB_SYSTEM_DEVICE_INFO
import com.hcusbsdk.Interface.USB_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_THERMOMETRY_CALIBRATION_FILE
import com.hcusbsdk.Interface.USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES
import com.hcusbsdk.Interface.USB_USER_LOGIN_INFO
import com.hcusbsdk.Interface.USB_VIDEO_PARAM
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class JavaInterfaceCalibrationFileTest {

    @Test
    fun calibrationFileStructsExposeOfficialFieldOrderAndOneMibBuffer() {
        assertEquals(
            listOf("dwFileLenth", "pCalibrationFile"),
            USB_THERMOMETRY_CALIBRATION_FILE::class.java.fields.map { it.name }.sorted(),
        )
        assertEquals(USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES, USB_THERMOMETRY_CALIBRATION_FILE().pCalibrationFile.size)

        val fieldOrder = com.hcusbsdk.jna.USB_THERMOMETRY_CALIBRATION_FILE::class.java
            .getAnnotation(com.sun.jna.Structure.FieldOrder::class.java)
        assertArrayEquals(arrayOf("pCalibrationFile", "dwFileLenth"), fieldOrder!!.value)
    }
    @Test
    fun calibrationFileCommandUsesOfficial2054ChannelOneAndCopiesReturnedBytesOnly() {
        val fake = FakeNativeBridge(returnedLength = 3, returnedBytes = byteArrayOf(10, 20, 30, 40))
        val javaInterface = JavaInterface.getInstance().apply { configureNativeBridge(fake) }
        val out = USB_THERMOMETRY_CALIBRATION_FILE()

        val ok = javaInterface.USB_GetThermometryCalibrationFile(userId = 7, out = out)

        assertTrue(ok)
        assertEquals(7, fake.lastUserId)
        assertEquals(USB_GET_THERMOMETRY_CALIBRATION_FILE, fake.lastCommand)
        assertEquals(1, fake.lastCond?.byChannelID?.toInt())
        assertEquals(USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES, fake.requestedMaxLength)
        assertEquals(3, out.dwFileLenth)
        assertArrayEquals(byteArrayOf(10, 20, 30), out.pCalibrationFile.copyOf(3))
        assertEquals(0, out.pCalibrationFile[3].toInt())
    }

    @Test
    fun calibrationFileRejectsNonPositiveAndOversizedReturnedLengths() {
        val javaInterface = JavaInterface.getInstance()

        val zeroFake = FakeNativeBridge(returnedLength = 0, returnedBytes = byteArrayOf(1))
        javaInterface.configureNativeBridge(zeroFake)
        val zeroOut = USB_THERMOMETRY_CALIBRATION_FILE()
        assertFalse(javaInterface.USB_GetThermometryCalibrationFile(userId = 1, out = zeroOut))
        assertEquals(0, zeroOut.dwFileLenth)
        assertEquals(0, zeroOut.pCalibrationFile[0].toInt())

        val oversizedFake = FakeNativeBridge(
            returnedLength = USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES + 1,
            returnedBytes = byteArrayOf(2),
        )
        javaInterface.configureNativeBridge(oversizedFake)
        val oversizedOut = USB_THERMOMETRY_CALIBRATION_FILE()
        assertFalse(javaInterface.USB_GetThermometryCalibrationFile(userId = 1, out = oversizedOut))
        assertEquals(USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES + 1, oversizedOut.dwFileLenth)
        assertEquals(0, oversizedOut.pCalibrationFile[0].toInt())
    }

    internal class FakeNativeBridge(
        private val returnedLength: Int,
        private val returnedBytes: ByteArray,
    ) : JavaInterface.NativeBridge {
        var lastUserId: Int = -1
        var lastCommand: Int = -1
        var lastCond: USB_COMMON_COND? = null
        var requestedMaxLength: Int = -1
        var calls: Int = 0

        override fun USB_Init(): Boolean = true
        override fun USB_Cleanup(): Boolean = true
        override fun USB_GetLastError(): Int = 84
        override fun USB_GetDeviceCount(): Int = 0
        override fun USB_EnumDevices_C(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean = false
        override fun USB_Login(loginInfo: USB_USER_LOGIN_INFO, deviceRegRes: USB_DEVICE_REG_RES): Int = -1
        override fun USB_GetSysTemDeviceInfo(userId: Int, info: USB_SYSTEM_DEVICE_INFO): Boolean = false
        override fun USB_GetThermometryCalibrationFile(
            userId: Int,
            cond: USB_COMMON_COND,
            out: USB_THERMOMETRY_CALIBRATION_FILE,
        ): Boolean {
            calls += 1
            lastUserId = userId
            lastCommand = USB_GET_THERMOMETRY_CALIBRATION_FILE
            lastCond = USB_COMMON_COND().apply {
                byChannelID = cond.byChannelID
                byRes = cond.byRes.copyOf()
            }
            requestedMaxLength = out.dwFileLenth
            out.dwFileLenth = returnedLength
            returnedBytes.copyInto(out.pCalibrationFile, endIndex = minOf(returnedBytes.size, out.pCalibrationFile.size))
            return true
        }
        override fun USB_SetVideoParam(userId: Int, param: USB_VIDEO_PARAM): Boolean = false
        override fun USB_SetThermalStreamParam(userId: Int, param: USB_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_GetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_SetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_StopChannel(userId: Int, channel: Int): Boolean = false
        override fun USB_Logout(userId: Int): Boolean = false
    }
}
