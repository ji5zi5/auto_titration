package com.hcusbsdk.Interface

import android.content.Context
import com.hcusbsdk.jna.HCUSBSDK
import com.hcusbsdk.jna.HCUSBSDKByJNA
import com.hcusbsdk.jna.USB_COMMON_COND as JnaUSB_COMMON_COND
import com.hcusbsdk.jna.USB_CONFIG_INPUT_INFO as JnaUSB_CONFIG_INPUT_INFO
import com.hcusbsdk.jna.USB_CONFIG_OUTPUT_INFO as JnaUSB_CONFIG_OUTPUT_INFO
import com.hcusbsdk.jna.USB_CTRL_THERMAL_STREAM_PARAM as JnaUSB_CTRL_THERMAL_STREAM_PARAM
import com.hcusbsdk.jna.USB_DEVICE_INFO as JnaUSB_DEVICE_INFO
import com.hcusbsdk.jna.USB_DEVICE_REG_RES as JnaUSB_DEVICE_REG_RES
import com.hcusbsdk.jna.USB_FRAME_INFO as JnaUSB_FRAME_INFO
import com.hcusbsdk.jna.USB_STREAM_CALLBACK_PARAM as JnaUSB_STREAM_CALLBACK_PARAM
import com.hcusbsdk.jna.USB_SYSTEM_DEVICE_INFO as JnaUSB_SYSTEM_DEVICE_INFO
import com.hcusbsdk.jna.USB_THERMAL_STREAM_PARAM as JnaUSB_THERMAL_STREAM_PARAM
import com.hcusbsdk.jna.USB_THERMOMETRY_CALIBRATION_FILE as JnaUSB_THERMOMETRY_CALIBRATION_FILE
import com.hcusbsdk.jna.USB_USER_LOGIN_INFO as JnaUSB_USER_LOGIN_INFO
import com.hcusbsdk.jna.USB_VIDEO_PARAM as JnaUSB_VIDEO_PARAM
import com.sun.jna.Pointer
import com.sun.jna.Structure
import java.util.concurrent.atomic.AtomicLong

private const val USB_GET_SYSTEM_DEVICE_INFO = 2011
const val USB_GET_THERMOMETRY_CALIBRATION_FILE = 2054
private const val USB_SET_THERMAL_STREAM_PARAM = 2039
private const val USB_GET_THERMAL_STREAM_CTRL = 2110
private const val USB_SET_THERMAL_STREAM_CTRL = 2111
private const val USB_SET_VIDEO_PARAM = 3004
private const val ENUM_TYPE_C = 0
private const val ENUM_TYPE_JAVA = 1
private const val MAX_JNA_FRAME_COPY_BYTES = 10 * 1024 * 1024

/**
 * Repo-owned facade with the same public package/class shape as the HIKMICRO
 * Viewer APK's com.hcusbsdk.Interface.JavaInterface.
 *
 * It preserves the official branch structure: USB_GetDeviceCount(context)
 * prepares Java/Android fd-based device info, USB_EnumDevices dispatches to
 * USB_EnumDevices_Java or USB_EnumDevices_C by m_iEnumType, and the public
 * USB_StartStreamCallback route stores official callback slots before calling
 * HCUSBSDKByJNI. The separate USB_StartStreamCallbackJNA route mirrors the
 * extracted official JNA wrapper: it builds/writes the native callback struct,
 * sets pUser=NULL, preserves callback keep-alives, and calls
 * HCUSBSDKByJNA.USB_StartStreamCallback through the configured HCUSBSDK facade.
 */
class JavaInterface private constructor() {
    interface NativeBridge {
        fun USB_Init(): Boolean
        fun USB_Cleanup(): Boolean
        fun USB_GetLastError(): Int
        fun USB_GetDeviceCount(): Int
        fun USB_EnumDevices_C(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean
        fun USB_Login(loginInfo: USB_USER_LOGIN_INFO, deviceRegRes: USB_DEVICE_REG_RES): Int
        fun USB_GetSysTemDeviceInfo(userId: Int, info: USB_SYSTEM_DEVICE_INFO): Boolean
        fun USB_GetThermometryCalibrationFile(
            userId: Int,
            cond: USB_COMMON_COND,
            out: USB_THERMOMETRY_CALIBRATION_FILE,
        ): Boolean
        fun USB_SetVideoParam(userId: Int, param: USB_VIDEO_PARAM): Boolean
        fun USB_SetThermalStreamParam(userId: Int, param: USB_THERMAL_STREAM_PARAM): Boolean
        fun USB_GetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean
        fun USB_SetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean
        fun USB_StopChannel(userId: Int, channel: Int): Boolean
        fun USB_Logout(userId: Int): Boolean
    }

    @JvmField
    val m_fnStreamCallBack = arrayOfNulls<FStreamCallBack>(10_000)

    @JvmField
    val m_fnStreamCallBack_jna = com.hcusbsdk.jna.HCUSBSDKByJNA.FStreamCallBack { callbackUserId, framePointer, _ ->
        m_fnStreamCallBack[callbackUserId]!!.fStreamCallback(callbackUserId, framePointer?.toInterfaceFrame())
    }

    @JvmField
    val m_fnStreamCallBack_jni = com.hcusbsdk.jni.StreamCallBack_JNI { callbackUserId, frameInfo ->
        m_fnStreamCallBack[callbackUserId]!!.fStreamCallback(callbackUserId, frameInfo.toInterfaceFrame())
    }

    internal data class NativeFrameCopySource(
        val nStamp: Int = 0,
        val dwStreamType: Int = 0,
        val dwWidth: Int = 0,
        val dwHeight: Int = 0,
        val dwFrameRate: Int = 0,
        val dwFrameType: Int = 0,
        val dwDataType: Int = 0,
        val nFrameNum: Int = 0,
        val pBuf: ByteArray = ByteArray(0),
        val dwBufSize: Int = 0,
    )

    private val streamCallbackEntryCounter = AtomicLong(0)

    @Volatile
    var lastStartStreamCallbackDetail: String = "not_started"
        private set

    @Volatile
    var lastStreamCallbackEntryDetail: String = "no_callback_entry"
        private set

    val streamCallbackEntryCount: Long
        get() = streamCallbackEntryCounter.get()

    fun resetStreamCallbackEntryDiagnostics() {
        streamCallbackEntryCounter.set(0L)
        lastStreamCallbackEntryDetail = "no_callback_entry"
    }

    @Volatile
    private var activeStreamCallbackUserId: Int = -1

    @Volatile
    private var activeStreamCallbackChannel: Int = -1

    @Volatile
    private var m_iEnumType: Int = ENUM_TYPE_JAVA

    @Volatile
    private var m_bInit: Boolean = false

    @Volatile
    private var nativeBridge: NativeBridge = NoopNativeBridge

    private val contextDeviceInfos = mutableListOf<USB_DEVICE_INFO>()
    private val enumerateDevice = EnumerateDevice()

    private object NoopNativeBridge : NativeBridge {
        override fun USB_Init(): Boolean = false
        override fun USB_Cleanup(): Boolean = true
        override fun USB_GetLastError(): Int = -1
        override fun USB_GetDeviceCount(): Int = 0
        override fun USB_EnumDevices_C(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean = false
        override fun USB_Login(loginInfo: USB_USER_LOGIN_INFO, deviceRegRes: USB_DEVICE_REG_RES): Int = -1
        override fun USB_GetSysTemDeviceInfo(userId: Int, info: USB_SYSTEM_DEVICE_INFO): Boolean = false
        override fun USB_GetThermometryCalibrationFile(
            userId: Int,
            cond: USB_COMMON_COND,
            out: USB_THERMOMETRY_CALIBRATION_FILE,
        ): Boolean = false
        override fun USB_SetVideoParam(userId: Int, param: USB_VIDEO_PARAM): Boolean = false
        override fun USB_SetThermalStreamParam(userId: Int, param: USB_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_GetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_SetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_StopChannel(userId: Int, channel: Int): Boolean = false
        override fun USB_Logout(userId: Int): Boolean = false
    }

    fun configureNativeBridge(bridge: NativeBridge) {
        nativeBridge = bridge
    }

    fun USB_Init(): Boolean {
        if (m_bInit) return true
        val ok = nativeBridge.USB_Init()
        if (ok) m_bInit = true
        return ok
    }

    fun USB_Cleanup(): Boolean {
        releaseAllDeviceConnections()
        val ok = nativeBridge.USB_Cleanup()
        m_bInit = false
        return ok
    }

    fun USB_GetLastError(): Int = nativeBridge.USB_GetLastError()

    fun USB_GetDeviceCount(): Int {
        m_iEnumType = ENUM_TYPE_C
        return nativeBridge.USB_GetDeviceCount()
    }

    fun USB_GetDeviceCount(context: Context): Int {
        releaseAllDeviceConnections()
        m_iEnumType = ENUM_TYPE_JAVA
        val count = enumerateDevice.EnumDevice(context)
        val opened = enumerateDevice.drainEnumeratedDevices().mapIndexed { index, enumeratedDevice ->
            val device = enumeratedDevice.device
            USB_DEVICE_INFO().apply {
                dwSize = 0
                dwIndex = index + 1
                dwVID = device.vendorId
                dwPID = device.productId
                szManufacturer = safeUsbString { device.manufacturerName }
                szDeviceName = device.deviceName
                szSerialNumber = safeUsbString { device.serialNumber }
                byHaveAudio = 0
                dwFd = enumeratedDevice.fileDescriptor
                usbDeviceConnection = enumeratedDevice.connection
            }
        }
        synchronized(contextDeviceInfos) {
            contextDeviceInfos.clear()
            contextDeviceInfos.addAll(opened)
        }
        return count
    }

    fun USB_EnumDevices(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean {
        return if (m_iEnumType == ENUM_TYPE_JAVA) {
            USB_EnumDevices_Java(count, devices)
        } else {
            USB_EnumDevices_C(count, devices)
        }
    }

    fun USB_EnumDevices_C(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean =
        nativeBridge.USB_EnumDevices_C(count, devices)

    fun USB_EnumDevices_Java(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean {
        val source = synchronized(contextDeviceInfos) { contextDeviceInfos.toList() }
        if (count <= 0 || source.isEmpty()) return false
        source.take(minOf(count, devices.size)).forEachIndexed { index, info ->
            devices[index].copyFrom(info)
        }
        return true
    }

    fun USB_Login(loginInfo: USB_USER_LOGIN_INFO, deviceRegRes: USB_DEVICE_REG_RES): Int =
        nativeBridge.USB_Login(loginInfo, deviceRegRes)

    fun USB_GetSysTemDeviceInfo(userId: Int, info: USB_SYSTEM_DEVICE_INFO): Boolean =
        nativeBridge.USB_GetSysTemDeviceInfo(userId, info)

    fun USB_GetThermometryCalibrationFile(userId: Int, out: USB_THERMOMETRY_CALIBRATION_FILE): Boolean {
        val returned = USB_THERMOMETRY_CALIBRATION_FILE().apply {
            dwFileLenth = USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES
        }
        val cond = USB_COMMON_COND().apply { byChannelID = 1.toByte() }
        val ok = nativeBridge.USB_GetThermometryCalibrationFile(userId, cond, returned)
        if (!ok) return false
        val returnedLength = returned.dwFileLenth
        if (returnedLength <= 0 || returnedLength > USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES) {
            out.dwFileLenth = returnedLength
            return false
        }
        out.dwFileLenth = returnedLength
        returned.pCalibrationFile.copyInto(out.pCalibrationFile, endIndex = returnedLength)
        return true
    }

    fun USB_SetVideoParam(userId: Int, param: USB_VIDEO_PARAM): Boolean =
        nativeBridge.USB_SetVideoParam(userId, param)

    fun USB_SetThermalStreamParam(userId: Int, param: USB_THERMAL_STREAM_PARAM): Boolean =
        nativeBridge.USB_SetThermalStreamParam(userId, param)

    fun USB_GetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean =
        nativeBridge.USB_GetThermalStreamCtrl(userId, param)

    fun USB_SetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean =
        nativeBridge.USB_SetThermalStreamCtrl(userId, param)

    fun USB_StartStreamCallback(userId: Int, param: USB_STREAM_CALLBACK_PARAM?): Int =
        if (param?.fnStreamCallBack != null) USB_StartStreamCallback_jni(userId, param) else -1

    fun USB_StartStreamCallbackJNA(
        userId: Int,
        cbParam: JnaUSB_STREAM_CALLBACK_PARAM,
        param: USB_STREAM_CALLBACK_PARAM,
    ): Int {
        resetStreamCallbackEntryDiagnostics()
        return USB_StartStreamCallback_jna(userId, cbParam, param)
    }

    private fun USB_StartStreamCallback_jna(
        userId: Int,
        cbParam: JnaUSB_STREAM_CALLBACK_PARAM,
        param: USB_STREAM_CALLBACK_PARAM,
    ): Int {
        if (userId < 0 || userId >= m_fnStreamCallBack.size) return -1
        val callback = param.fnStreamCallBack ?: return -1
        val suppliedJnaCallback = cbParam.fnStreamCallBack
        val jnaCallback = com.hcusbsdk.jna.HCUSBSDKByJNA.FStreamCallBack { callbackUserId, framePointer, userPointer ->
            recordCallbackEntry("jna", callbackUserId, framePointer.toFrameEntrySummary())
            if (suppliedJnaCallback != null) {
                suppliedJnaCallback.invoke(callbackUserId, framePointer, userPointer)
            } else {
                callback.fStreamCallback(callbackUserId, framePointer?.toInterfaceFrame())
            }
        }
        synchronized(m_fnStreamCallBack) {
            m_fnStreamCallBack[userId] = callback
        }
        val nativeParam = JnaUSB_STREAM_CALLBACK_PARAM()
        // Official JNA wrapper shape: dwSize = nativeParam.size()
        nativeParam.dwSize = nativeParam.size()
        nativeParam.dwStreamType = param.dwStreamType
        nativeParam.pUser = Pointer.NULL
        nativeParam.fnStreamCallBack = jnaCallback
        nativeParam.write()
        activeStreamCallbackUserId = userId
        activeStreamCallbackChannel = -1
        val channel = HCUSBSDK.getInstance().USB_StartStreamCallback(userId, nativeParam.pointer)
        activeStreamCallbackChannel = channel
        val lastError = USB_GetLastError()
        lastStartStreamCallbackDetail =
            "official_jna_wrapper_return channel=$channel lastError=$lastError userId=$userId streamType=${param.dwStreamType} dwSize=${nativeParam.dwSize}"
        if (channel == -1) {
            clearCallbackSlot(userId)
        }
        return channel
    }

    private fun USB_StartStreamCallback_jni(userId: Int, param: USB_STREAM_CALLBACK_PARAM): Int {
        if (userId == -1 || userId > 10_000) return -1
        m_fnStreamCallBack[userId] = param.fnStreamCallBack
        val jniParam = com.hcusbsdk.jni.USB_STREAM_CALLBACK_PARAM().apply {
            dwSize = 0
            dwStreamType = param.dwStreamType
        }
        return com.hcusbsdk.jni.HCUSBSDKByJNI.getInstance()
            .USB_StartStreamCallback(userId, jniParam, m_fnStreamCallBack_jni)
    }

    fun USB_StopChannel(userId: Int, channel: Int): Boolean =
        com.hcusbsdk.jni.HCUSBSDKByJNI.getInstance().USB_StopChannel(userId, channel)

    fun USB_Logout(userId: Int): Boolean = HCUSBSDK.getInstance().USB_Logout(userId)

    fun releaseUnselectedDeviceConnections(selected: USB_DEVICE_INFO?) {
        synchronized(contextDeviceInfos) {
            contextDeviceInfos.forEach { info ->
                val isSelected = selected != null &&
                    info.dwFd == selected.dwFd &&
                    info.szDeviceName == selected.szDeviceName
                if (isSelected) {
                    // Transfer ownership to the selected facade DTO held by F2UsbModuleHelper.
                    info.usbDeviceConnection = null
                } else {
                    info.closeConnection()
                }
            }
            contextDeviceInfos.clear()
        }
    }

    fun releaseAllDeviceConnections() {
        enumerateDevice.releaseOpenedConnections()
        synchronized(contextDeviceInfos) {
            contextDeviceInfos.forEach { it.closeConnection() }
            contextDeviceInfos.clear()
        }
    }

    private fun clearCallbackSlot(userId: Int) {
        if (userId !in m_fnStreamCallBack.indices) return
        synchronized(m_fnStreamCallBack) {
            m_fnStreamCallBack[userId] = null
        }
    }

    internal fun dispatchJnaFrameCopySourceForHostTest(callbackUserId: Int, frame: NativeFrameCopySource) {
        recordCallbackEntry("jna", callbackUserId, frame.toFrameEntrySummary())
        val callback = if (callbackUserId in m_fnStreamCallBack.indices) {
            synchronized(m_fnStreamCallBack) { m_fnStreamCallBack[callbackUserId] }
        } else {
            null
        }
        callback?.fStreamCallback(callbackUserId, frame.toInterfaceFrame())
    }

    private fun recordCallbackEntry(route: String, callbackUserId: Int, frameSummary: String) {
        val count = streamCallbackEntryCounter.incrementAndGet()
        lastStreamCallbackEntryDetail =
            "route=$route count=$count callbackUserId=$callbackUserId activeUserId=$activeStreamCallbackUserId activeChannel=$activeStreamCallbackChannel $frameSummary"
    }

    private fun NativeFrameCopySource.toFrameEntrySummary(): String =
        "dwBufSize=$dwBufSize dwFrameType=$dwFrameType dwDataType=$dwDataType dwStreamType=$dwStreamType frameNum=$nFrameNum"

    private fun Pointer?.toFrameEntrySummary(): String {
        if (this == null) return "frame=null"
        val nativeFrame = JnaUSB_FRAME_INFO(this).apply { read() }
        return "dwBufSize=${nativeFrame.dwBufSize} dwFrameType=${nativeFrame.dwFrameType} dwDataType=${nativeFrame.dwDataType} dwStreamType=${nativeFrame.dwStreamType} frameNum=${nativeFrame.nFrameNum}"
    }

    private fun com.hcusbsdk.jni.USB_FRAME_INFO?.toFrameEntrySummary(): String {
        if (this == null) return "frame=null"
        return "dwBufSize=$dwBufSize dwFrameType=$dwFrameType dwDataType=$dwDataType dwStreamType=$dwStreamType frameNum=$nFrameNum"
    }

    private fun Pointer.toInterfaceFrame(): USB_FRAME_INFO {
        val nativeFrame = JnaUSB_FRAME_INFO(this).apply { read() }
        return nativeFrame.toInterfaceFrame { byteCount ->
            if (byteCount > 0) {
                nativeFrame.pBuf?.getByteArray(0, byteCount) ?: ByteArray(0)
            } else {
                ByteArray(0)
            }
        }
    }

    private fun JnaUSB_FRAME_INFO.toInterfaceFrame(readBytes: (Int) -> ByteArray): USB_FRAME_INFO {
        val byteCount = dwBufSize.coerceIn(0, MAX_JNA_FRAME_COPY_BYTES)
        val bytes = readBytes(byteCount)
        return USB_FRAME_INFO().apply {
            nStamp = this@toInterfaceFrame.nStamp
            dwStreamType = this@toInterfaceFrame.dwStreamType
            dwWidth = this@toInterfaceFrame.dwWidth
            dwHeight = this@toInterfaceFrame.dwHeight
            dwFrameRate = this@toInterfaceFrame.dwFrameRate
            dwFrameType = this@toInterfaceFrame.dwFrameType
            dwDataType = this@toInterfaceFrame.dwDataType
            nFrameNum = this@toInterfaceFrame.nFrameNum
            pBuf = bytes
            dwBufSize = bytes.size
        }
    }

    private fun NativeFrameCopySource.toInterfaceFrame(): USB_FRAME_INFO {
        val byteCount = dwBufSize.coerceIn(0, MAX_JNA_FRAME_COPY_BYTES)
        val bytes = pBuf.copyOf(byteCount)
        return USB_FRAME_INFO().apply {
            nStamp = this@toInterfaceFrame.nStamp
            dwStreamType = this@toInterfaceFrame.dwStreamType
            dwWidth = this@toInterfaceFrame.dwWidth
            dwHeight = this@toInterfaceFrame.dwHeight
            dwFrameRate = this@toInterfaceFrame.dwFrameRate
            dwFrameType = this@toInterfaceFrame.dwFrameType
            dwDataType = this@toInterfaceFrame.dwDataType
            nFrameNum = this@toInterfaceFrame.nFrameNum
            pBuf = bytes
            dwBufSize = bytes.size
        }
    }

    private fun com.hcusbsdk.jni.USB_FRAME_INFO?.toInterfaceFrame(): USB_FRAME_INFO? {
        if (this == null) return null
        val byteCount = dwBufSize.coerceIn(0, MAX_JNA_FRAME_COPY_BYTES)
        return USB_FRAME_INFO().also { target ->
            target.nStamp = nStamp
            target.dwStreamType = dwStreamType
            target.dwWidth = dwWidth
            target.dwHeight = dwHeight
            target.dwFrameRate = dwFrameRate
            target.dwFrameType = dwFrameType
            target.dwDataType = dwDataType
            target.nFrameNum = nFrameNum
            target.pBuf = pBuf.copyOf(byteCount)
            target.dwBufSize = target.pBuf.size
        }
    }

    private fun safeUsbString(read: () -> String?): String =
        read().orEmpty()

    class JnaNativeBridge(private val sdk: HCUSBSDKByJNA) : NativeBridge {
        override fun USB_Init(): Boolean = sdk.USB_Init()

        override fun USB_Cleanup(): Boolean = sdk.USB_Cleanup()

        override fun USB_GetLastError(): Int = sdk.USB_GetLastError()

        override fun USB_GetDeviceCount(): Int = sdk.USB_GetDeviceCount()

        override fun USB_EnumDevices_C(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean {
            if (count <= 0) return false
            val base = JnaUSB_DEVICE_INFO().apply {
                dwSize = size()
                write()
            }
            val structures = base.toArray(count)
            val nativeDevices = Array(count) { index ->
                (structures[index] as JnaUSB_DEVICE_INFO).apply {
                    dwSize = size()
                    write()
                }
            }
            val ok = sdk.USB_EnumDevices(count, nativeDevices)
            nativeDevices.forEach { it.read() }
            nativeDevices.take(minOf(count, devices.size)).forEachIndexed { index, native ->
                devices[index].apply {
                    dwSize = native.dwSize
                    dwIndex = native.dwIndex
                    dwVID = native.dwVID
                    dwPID = native.dwPID
                    szManufacturer = native.szManufacturer.toNullTerminatedString()
                    szDeviceName = native.szDeviceName.toNullTerminatedString()
                    szSerialNumber = native.szSerialNumber.toNullTerminatedString()
                    byHaveAudio = native.byHaveAudio
                    byRes = native.byRes.copyOf()
                    dwFd = 0
                }
            }
            return ok
        }

        override fun USB_Login(loginInfo: USB_USER_LOGIN_INFO, deviceRegRes: USB_DEVICE_REG_RES): Int {
            val nativeLogin = JnaUSB_USER_LOGIN_INFO().apply {
                dwSize = size()
                dwTimeout = loginInfo.dwTimeout
                dwDevIndex = loginInfo.dwDevIndex
                dwVID = loginInfo.dwVID
                dwPID = loginInfo.dwPID
                szUserName.fillFrom(loginInfo.szUserName)
                szPassword.fillFrom(loginInfo.szPassword)
                szSerialNumber.fillFrom(loginInfo.szSerialNumber)
                byLoginMode = loginInfo.byLoginMode
                byRes2 = loginInfo.byRes2.copyOf(3)
                dwFd = loginInfo.dwFd
                byRes = loginInfo.byRes.copyOf(248)
                write()
            }
            val nativeReg = JnaUSB_DEVICE_REG_RES().apply {
                dwSize = size()
                write()
            }
            val userId = sdk.USB_Login(nativeLogin.pointer, nativeReg.pointer)
            if (userId != -1) {
                nativeReg.read()
                deviceRegRes.dwSize = nativeReg.dwSize
                deviceRegRes.szDeviceName = nativeReg.szDeviceName.toNullTerminatedString()
                deviceRegRes.szSerialNumber = nativeReg.szSerialNumber.toNullTerminatedString()
                deviceRegRes.dwSoftwareVersion = nativeReg.dwSoftwareVersion
                deviceRegRes.wYear = nativeReg.wYear
                deviceRegRes.byMonth = nativeReg.byMonth
                deviceRegRes.byDay = nativeReg.byDay
                deviceRegRes.byRetryLoginTimes = nativeReg.byRetryLoginTimes
                deviceRegRes.byRes1 = nativeReg.byRes1.copyOf()
                deviceRegRes.dwSurplusLockTime = nativeReg.dwSurplusLockTime
                deviceRegRes.byRes = nativeReg.byRes.copyOf()
            }
            return userId
        }

        override fun USB_GetSysTemDeviceInfo(userId: Int, info: USB_SYSTEM_DEVICE_INFO): Boolean {
            val nativeInfo = JnaUSB_SYSTEM_DEVICE_INFO().apply { write() }
            val ok = getDeviceConfig(userId, USB_GET_SYSTEM_DEVICE_INFO, nativeInfo)
            if (ok) {
                nativeInfo.read()
                info.byFirmwareVersion = nativeInfo.byFirmwareVersion.toNullTerminatedString()
                info.byEncoderVersion = nativeInfo.byEncoderVersion.toNullTerminatedString()
                info.byHardwareVersion = nativeInfo.byHardwareVersion.toNullTerminatedString()
                info.byDeviceType = nativeInfo.byDeviceType.toNullTerminatedString()
                info.byProtocolVersion = nativeInfo.byProtocolVersion.toNullTerminatedString()
                info.bySerialNumber = nativeInfo.bySerialNumber.toNullTerminatedString()
                info.bySecondHardwareVersion = nativeInfo.bySecondHardwareVersion.toNullTerminatedString()
                info.byModuleID = nativeInfo.byModuleID.toNullTerminatedString()
                info.byDeviceID = nativeInfo.byDeviceID.toNullTerminatedString()
                info.byDeviceAssembleType = nativeInfo.byDeviceAssembleType
                info.byManufacturer = nativeInfo.byManufacturer
                info.byLanguageType = nativeInfo.byLanguageType
                info.byDeviceClass = nativeInfo.byDeviceClass
            }
            return ok
        }

        override fun USB_GetThermometryCalibrationFile(
            userId: Int,
            cond: USB_COMMON_COND,
            out: USB_THERMOMETRY_CALIBRATION_FILE,
        ): Boolean {
            val nativeCond = JnaUSB_COMMON_COND().apply {
                    byChannelID = cond.byChannelID
                    byRes = cond.byRes.copyOf(6)
                }
                val calibrationMemory = com.sun.jna.Memory(USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES.toLong()).apply {
                    clear(USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES.toLong())
                }
                val nativeParam = JnaUSB_THERMOMETRY_CALIBRATION_FILE().apply {
                    pCalibrationFile = calibrationMemory
                    dwFileLenth = USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES
                    write()
                }
                nativeCond.write()
                val inputInfo = JnaUSB_CONFIG_INPUT_INFO().apply {
                    lpCondBuffer = nativeCond.pointer
                    dwCondBufferSize = nativeCond.size()
                    write()
                }
                val outputInfo = JnaUSB_CONFIG_OUTPUT_INFO().apply {
                    lpOutBuffer = nativeParam.pointer
                    dwOutBufferSize = nativeParam.size()
                    write()
                }
                val ok = sdk.USB_GetDeviceConfig(
                    userId,
                    USB_GET_THERMOMETRY_CALIBRATION_FILE,
                    inputInfo.pointer,
                    outputInfo.pointer,
                )
                if (ok) {
                    outputInfo.read()
                    nativeParam.read()
                    out.dwFileLenth = nativeParam.dwFileLenth
                    if (nativeParam.dwFileLenth in 1..USB_THERMOMETRY_CALIBRATION_FILE_MAX_BYTES) {
                        calibrationMemory.read(0, out.pCalibrationFile, 0, nativeParam.dwFileLenth)
                    }
                }
            return ok
        }

        override fun USB_SetVideoParam(userId: Int, param: USB_VIDEO_PARAM): Boolean {
            val nativeParam = JnaUSB_VIDEO_PARAM().apply {
                dwVideoFormat = param.dwVideoFormat
                dwWidth = param.dwWidth
                dwHeight = param.dwHeight
                dwFramerate = param.dwFramerate
                dwBitrate = param.dwBitrate
                dwParamType = param.dwParamType
                dwValue = param.dwValue
            }
            return setDeviceConfig(userId, USB_SET_VIDEO_PARAM, nativeParam, JnaUSB_COMMON_COND())
        }

        override fun USB_SetThermalStreamParam(userId: Int, param: USB_THERMAL_STREAM_PARAM): Boolean {
            val nativeParam = JnaUSB_THERMAL_STREAM_PARAM().apply {
                dwSize = size()
                byVideoCodingType = param.byVideoCodingType
            }
            val cond = JnaUSB_COMMON_COND().apply { byChannelID = 1.toByte() }
            return setDeviceConfig(userId, USB_SET_THERMAL_STREAM_PARAM, nativeParam, cond)
        }

        override fun USB_GetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean {
            val nativeParam = JnaUSB_CTRL_THERMAL_STREAM_PARAM().apply {
                dwSize = size()
                write()
            }
            val ok = getDeviceConfig(userId, USB_GET_THERMAL_STREAM_CTRL, nativeParam)
            if (ok) {
                nativeParam.read()
                param.dwSize = nativeParam.dwSize
                param.byEnable = nativeParam.byEnable
                param.byRes = nativeParam.byRes.copyOf()
            }
            return ok
        }

        override fun USB_SetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean {
            val nativeParam = JnaUSB_CTRL_THERMAL_STREAM_PARAM().apply {
                dwSize = size()
                byEnable = param.byEnable
            }
            return setDeviceConfig(userId, USB_SET_THERMAL_STREAM_CTRL, nativeParam)
        }

        override fun USB_StopChannel(userId: Int, channel: Int): Boolean = sdk.USB_StopChannel(userId, channel)

        override fun USB_Logout(userId: Int): Boolean = sdk.USB_Logout(userId)

        private fun setDeviceConfig(
            userId: Int,
            command: Int,
            inputBuffer: Structure,
            condBuffer: Structure? = null,
        ): Boolean {
            inputBuffer.write()
            condBuffer?.write()
            val inputInfo = JnaUSB_CONFIG_INPUT_INFO().apply {
                if (condBuffer != null) {
                    lpCondBuffer = condBuffer.pointer
                    dwCondBufferSize = condBuffer.size()
                }
                lpInBuffer = inputBuffer.pointer
                dwInBufferSize = inputBuffer.size()
                write()
            }
            val outputInfo = JnaUSB_CONFIG_OUTPUT_INFO().apply { write() }
            return sdk.USB_SetDeviceConfig(userId, command, inputInfo.pointer, outputInfo.pointer)
        }

        private fun getDeviceConfig(
            userId: Int,
            command: Int,
            outputBuffer: Structure,
            condBuffer: Structure? = null,
        ): Boolean {
            condBuffer?.write()
            outputBuffer.write()
            val inputInfo = JnaUSB_CONFIG_INPUT_INFO().apply {
                if (condBuffer != null) {
                    lpCondBuffer = condBuffer.pointer
                    dwCondBufferSize = condBuffer.size()
                }
                write()
            }
            val outputInfo = JnaUSB_CONFIG_OUTPUT_INFO().apply {
                lpOutBuffer = outputBuffer.pointer
                dwOutBufferSize = outputBuffer.size()
                write()
            }
            val ok = sdk.USB_GetDeviceConfig(userId, command, inputInfo.pointer, outputInfo.pointer)
            if (ok) {
                outputInfo.read()
                outputBuffer.read()
            }
            return ok
        }

        private fun ByteArray.fillFrom(value: String) {
            fill(0)
            val bytes = value.encodeToByteArray()
            bytes.copyInto(this, endIndex = minOf(bytes.size, size - 1))
        }

        private fun ByteArray.toNullTerminatedString(): String {
            val length = indexOf(0).takeIf { it >= 0 } ?: size
            return copyOf(length).decodeToString().trim()
        }

    }

    companion object {
        @JvmField
        val INSTANCE: JavaInterface = JavaInterface()

        @JvmStatic
        fun getInstance(): JavaInterface = INSTANCE
    }
}
