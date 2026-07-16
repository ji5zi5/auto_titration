package com.hik.f2module

import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.Interface.USB_COMMON_COND
import com.hcusbsdk.Interface.USB_CTRL_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_DEVICE_INFO
import com.hcusbsdk.Interface.USB_DEVICE_REG_RES
import com.hcusbsdk.Interface.USB_GET_THERMOMETRY_CALIBRATION_FILE
import com.hcusbsdk.Interface.USB_SYSTEM_DEVICE_INFO
import com.hcusbsdk.Interface.USB_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_THERMOMETRY_CALIBRATION_FILE
import com.hcusbsdk.Interface.USB_USER_LOGIN_INFO
import com.hcusbsdk.Interface.USB_VIDEO_PARAM
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class F2CalibrationFileTest {
    @get:Rule
    val tmp = TemporaryFolder()

    @After
    fun resetSharedCalibrationState() {
        installCalibrationSession(-1, null, null)
        JavaInterface.getInstance().configureNativeBridge(ResetNativeBridge)
    }

    @Test
    fun acquisitionRequiresLoggedInUserAndSelectedDevice() {
        val fake = FakeCalibrationBridge(byteArrayOf(1, 2, 3))
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(-1, null, null)

        val result = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(tmp.newFolder("cache"))

        assertFalse(result.ok)
        assertEquals("login_required_for_command_2054", result.reason)
        assertEquals(0, fake.calls)
    }

    @Test
    fun explicitAcquisitionWritesOfficialVisibleFileNameAndProvenanceWithoutCallbackPrefetch() {
        val bytes = byteArrayOf(5, 4, 3, 2)
        val fake = FakeCalibrationBridge(bytes)
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(12, device(serial = "SER/IAL 1"), systemInfo())

        val result = F2UsbModuleHelper.INSTANCE.acquireThermometryCalibrationFileOnce(tmp.newFolder("cache"))

        assertTrue(result.ok)
        val file = result.file
        assertNotNull(file)
        assertTrue(file!!.name.contains("HM-Calibration_SER_IAL_1.dat"))
        assertArrayEquals(bytes, file.readBytes())
        val provenance = result.provenance
        assertNotNull(provenance)
        assertEquals(bytes.size, provenance!!.length)
        assertEquals(USB_GET_THERMOMETRY_CALIBRATION_FILE, provenance.nativeCommand)
        assertEquals(F2CalibrationCacheState.FETCHED.state, provenance.cacheState)
        assertEquals(F2_CALIBRATION_FORMAT_STATE_UNVERIFIED_2054, provenance.formatState)
        assertEquals(1, fake.calls)
        assertEquals(12, fake.lastUserId)
        assertEquals(1, fake.lastCond?.byChannelID?.toInt())
    }

    @Test
    fun callbackTimePrefetchHookIsNoopForOfficialG007HotPath() {
        val fake = FakeCalibrationBridge(byteArrayOf(9, 9))
        JavaInterface.getInstance().configureNativeBridge(fake)
        installCalibrationSession(22, device(serial = "NO-PREFETCH"), systemInfo())

        F2UsbModuleHelper.INSTANCE.onPreviewFrameForCalibrationPrefetch(tmp.newFolder("cache"), 10)

        assertEquals(0, fake.calls)
        assertEquals(null, F2UsbModuleHelper.INSTANCE.latestCalibrationAcquisitionResult())
    }

    private fun installCalibrationSession(
        testUserId: Int,
        deviceInfo: USB_DEVICE_INFO?,
        systemInfo: USB_SYSTEM_DEVICE_INFO?,
    ) {
        F2UsbModuleHelper.userId = testUserId
        F2UsbModuleHelper.channel = if (testUserId != -1 && deviceInfo != null) 1 else -1
        setHelperField("selectedDeviceInfo", deviceInfo)
        setHelperField("selectedSystemDeviceInfo", systemInfo)
    }

    private fun setHelperField(name: String, value: Any?) {
        val field = F2UsbModuleHelper::class.java.getDeclaredField(name)
        field.isAccessible = true
        field.set(F2UsbModuleHelper.INSTANCE, value)
    }

    private fun device(serial: String) = USB_DEVICE_INFO().apply {
        dwVID = 11231
        dwPID = 0x1234
        szSerialNumber = serial
        szDeviceName = "usb-f2"
    }

    private fun systemInfo() = USB_SYSTEM_DEVICE_INFO().apply {
        bySerialNumber = "SYSTEM-SERIAL"
        byModuleID = "F2MOD"
        byFirmwareVersion = "V1_0203_240101"
        byDeviceID = "DEV-ID"
    }

    private object ResetNativeBridge : JavaInterface.NativeBridge {
        override fun USB_Init(): Boolean = false
        override fun USB_Cleanup(): Boolean = true
        override fun USB_GetLastError(): Int = -1
        override fun USB_GetDeviceCount(): Int = 0
        override fun USB_EnumDevices_C(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean = false
        override fun USB_Login(loginInfo: USB_USER_LOGIN_INFO, deviceRegRes: USB_DEVICE_REG_RES): Int = -1
        override fun USB_GetSysTemDeviceInfo(userId: Int, info: USB_SYSTEM_DEVICE_INFO): Boolean = false
        override fun USB_GetThermometryCalibrationFile(userId: Int, cond: USB_COMMON_COND, out: USB_THERMOMETRY_CALIBRATION_FILE): Boolean = false
        override fun USB_SetVideoParam(userId: Int, param: USB_VIDEO_PARAM): Boolean = false
        override fun USB_SetThermalStreamParam(userId: Int, param: USB_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_GetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_SetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_StopChannel(userId: Int, channel: Int): Boolean = false
        override fun USB_Logout(userId: Int): Boolean = false
    }

    private class FakeCalibrationBridge(private val bytes: ByteArray) : JavaInterface.NativeBridge {
        var calls: Int = 0
        var lastUserId: Int = -1
        var lastCond: USB_COMMON_COND? = null
        override fun USB_Init(): Boolean = true
        override fun USB_Cleanup(): Boolean = true
        override fun USB_GetLastError(): Int = 84
        override fun USB_GetDeviceCount(): Int = 0
        override fun USB_EnumDevices_C(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean = false
        override fun USB_Login(loginInfo: USB_USER_LOGIN_INFO, deviceRegRes: USB_DEVICE_REG_RES): Int = -1
        override fun USB_GetSysTemDeviceInfo(userId: Int, info: USB_SYSTEM_DEVICE_INFO): Boolean = false
        override fun USB_GetThermometryCalibrationFile(userId: Int, cond: USB_COMMON_COND, out: USB_THERMOMETRY_CALIBRATION_FILE): Boolean {
            calls += 1
            lastUserId = userId
            lastCond = USB_COMMON_COND().apply { byChannelID = cond.byChannelID }
            out.dwFileLenth = bytes.size
            bytes.copyInto(out.pCalibrationFile)
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
