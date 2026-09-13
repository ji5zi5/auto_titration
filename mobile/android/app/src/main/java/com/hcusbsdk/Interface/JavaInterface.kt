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
import com.hcusbsdk.jna.USB_IMAGE_BRIGHTNESS as JnaUSB_IMAGE_BRIGHTNESS
import com.hcusbsdk.jna.USB_IMAGE_CONTRAST as JnaUSB_IMAGE_CONTRAST
import com.hcusbsdk.jna.USB_IMAGE_ENHANCEMENT as JnaUSB_IMAGE_ENHANCEMENT
import com.hcusbsdk.jna.USB_IMAGE_ENHANCEMENT_EX as JnaUSB_IMAGE_ENHANCEMENT_EX
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
const val USB_GET_IMAGE_BRIGHTNESS = 2018
const val USB_GET_IMAGE_CONTRAST = 2020
const val USB_GET_IMAGE_ENHANCEMENT = 2026
const val USB_GET_IMAGE_ENHANCEMENT_V20 = 2080
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
        fun USB_GetImageBrightNess(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_BRIGHTNESS): Boolean = false
        fun USB_GetImageContrast(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_CONTRAST): Boolean = false
        fun USB_GetImageEnhancement(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_ENHANCEMENT): Boolean = false
        fun USB_GetImageEnhancementV20(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_ENHANCEMENT_EX): Boolean = false
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
        val candidate = framePointer.toJnaFrameCopyCandidate()
        recordRejectedCallbackFrame("jna", callbackUserId, candidate.summary, candidate.rejectionReason)
    }

    @JvmField
    val m_fnStreamCallBack_jni = com.hcusbsdk.jni.StreamCallBack_JNI { callbackUserId, frameInfo ->
        val rejectionReason = frameInfo.copyRejectionReason()
        val frameSummary = frameInfo.toFrameEntrySummary()
        if (rejectionReason != null) {
            recordRejectedCallbackFrame("jni", callbackUserId, frameSummary, rejectionReason)
        } else {
            val callback = callbackForDispatch("jni", callbackUserId, frameSummary)
            callback?.invoke(callbackUserId, requireNotNull(frameInfo).toInterfaceFrame())
        }
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

    private val streamCallbackTotalEntryCounter = AtomicLong(0)
    private val streamCallbackRejectedEntryCounter = AtomicLong(0)
    private val streamCallbackDispatchedEntryCounter = AtomicLong(0)
    private val streamRegistrationEpochCounter = AtomicLong(0)
    private val activeStreamRegistrationEpochs = LongArray(m_fnStreamCallBack.size)
    private val jniStreamCallbackKeepAlives =
        arrayOfNulls<com.hcusbsdk.jni.StreamCallBack_JNI>(m_fnStreamCallBack.size)
    private val jnaStreamCallbackKeepAlives =
        arrayOfNulls<com.hcusbsdk.jna.HCUSBSDKByJNA.FStreamCallBack>(m_fnStreamCallBack.size)

    internal fun interface JniStartStreamCallbackInvoker {
        fun USB_StartStreamCallback(
            userId: Int,
            callbackParam: com.hcusbsdk.jni.USB_STREAM_CALLBACK_PARAM,
            callback: com.hcusbsdk.jni.StreamCallBack_JNI,
        ): Int
    }

    internal fun interface JnaStartStreamCallbackInvoker {
        fun USB_StartStreamCallback(
            userId: Int,
            callbackParam: JnaUSB_STREAM_CALLBACK_PARAM,
        ): Int
    }

    internal fun interface JnaCallbackParamWriter {
        fun write(callbackParam: JnaUSB_STREAM_CALLBACK_PARAM)
    }

    @Volatile
    internal var jniStartStreamCallbackInvoker: JniStartStreamCallbackInvoker =
        JniStartStreamCallbackInvoker { userId, callbackParam, callback ->
            com.hcusbsdk.jni.HCUSBSDKByJNI.getInstance()
                .USB_StartStreamCallback(userId, callbackParam, callback)
        }

    @Volatile
    internal var jnaStartStreamCallbackInvoker: JnaStartStreamCallbackInvoker =
        JnaStartStreamCallbackInvoker { userId, callbackParam ->
            HCUSBSDK.getInstance().USB_StartStreamCallback(userId, callbackParam.pointer)
        }

    @Volatile
    internal var jnaCallbackParamWriter: JnaCallbackParamWriter =
        JnaCallbackParamWriter { callbackParam -> callbackParam.write() }

    @Volatile
    var lastStartStreamCallbackDetail: String = "not_started"
        private set

    @Volatile
    var lastStreamCallbackEntryDetail: String = "no_callback_entry"
        private set

    @Volatile
    var lastStreamCallbackRejectedEntryDetail: String = "no_rejected_callback_entry"
        private set

    val streamCallbackTotalEntryCount: Long
        get() = streamCallbackTotalEntryCounter.get()

    val streamCallbackRejectedEntryCount: Long
        get() = streamCallbackRejectedEntryCounter.get()

    val streamCallbackDispatchedEntryCount: Long
        get() = streamCallbackDispatchedEntryCounter.get()

    /**
     * Backward-compatible packet-evidence count. Rejected or otherwise
     * undispatched callback entries are deliberately excluded.
     */
    val streamCallbackEntryCount: Long
        get() = streamCallbackDispatchedEntryCount

    fun resetStreamCallbackEntryDiagnostics() {
        streamCallbackTotalEntryCounter.set(0L)
        streamCallbackRejectedEntryCounter.set(0L)
        streamCallbackDispatchedEntryCounter.set(0L)
        lastStreamCallbackEntryDetail = "no_callback_entry"
        lastStreamCallbackRejectedEntryDetail = "no_rejected_callback_entry"
    }

    internal fun resetJniStartStreamCallbackInvokerForTest() {
        jniStartStreamCallbackInvoker = JniStartStreamCallbackInvoker { userId, callbackParam, callback ->
            com.hcusbsdk.jni.HCUSBSDKByJNI.getInstance()
                .USB_StartStreamCallback(userId, callbackParam, callback)
        }
    }

    internal fun resetJnaStartStreamCallbackInvokerForTest() {
        jnaStartStreamCallbackInvoker = JnaStartStreamCallbackInvoker { userId, callbackParam ->
            HCUSBSDK.getInstance().USB_StartStreamCallback(userId, callbackParam.pointer)
        }
    }

    internal fun resetJnaCallbackParamWriterForTest() {
        jnaCallbackParamWriter = JnaCallbackParamWriter { callbackParam -> callbackParam.write() }
    }

    internal fun resetStreamCallbackRegistrationsForTest() {
        synchronized(m_fnStreamCallBack) {
            m_fnStreamCallBack.fill(null)
            activeStreamRegistrationEpochs.fill(0L)
            jniStreamCallbackKeepAlives.fill(null)
            jnaStreamCallbackKeepAlives.fill(null)
        }
        resetActiveStreamCallbackState()
    }

    @Volatile
    private var activeStreamCallbackUserId: Int = -1

    @Volatile
    private var activeStreamCallbackChannel: Int = -1

    @Volatile
    private var activeStreamCallbackRegistrationEpoch: Long = 0L

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
        override fun USB_GetImageBrightNess(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_BRIGHTNESS): Boolean = false
        override fun USB_GetImageContrast(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_CONTRAST): Boolean = false
        override fun USB_GetImageEnhancement(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_ENHANCEMENT): Boolean = false
        override fun USB_GetImageEnhancementV20(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_ENHANCEMENT_EX): Boolean = false
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


    fun USB_GetImageBrightNess(userId: Int, out: USB_IMAGE_BRIGHTNESS?): Boolean {
        if (out == null) return false
        val returned = USB_IMAGE_BRIGHTNESS()
        val cond = USB_COMMON_COND().apply { byChannelID = 1.toByte() }
        val ok = nativeBridge.USB_GetImageBrightNess(userId, cond, returned)
        if (!ok) return false
        out.dwBrightness = returned.dwBrightness
        return true
    }

    fun USB_GetImageContrast(userId: Int, out: USB_IMAGE_CONTRAST?): Boolean {
        if (out == null) return false
        val returned = USB_IMAGE_CONTRAST()
        val cond = USB_COMMON_COND().apply { byChannelID = 1.toByte() }
        val ok = nativeBridge.USB_GetImageContrast(userId, cond, returned)
        if (!ok) return false
        out.dwContrast = returned.dwContrast
        return true
    }

    fun USB_GetImageEnhancement(userId: Int, out: USB_IMAGE_ENHANCEMENT?): Boolean {
        if (out == null) return false
        val returned = USB_IMAGE_ENHANCEMENT()
        val cond = USB_COMMON_COND().apply { byChannelID = 1.toByte() }
        val ok = nativeBridge.USB_GetImageEnhancement(userId, cond, returned)
        if (!ok) return false
        out.copyFrom(returned)
        return true
    }

    fun USB_GetImageEnhancementV20(userId: Int, out: USB_IMAGE_ENHANCEMENT_EX?): Boolean {
        if (out == null) return false
        val returned = USB_IMAGE_ENHANCEMENT_EX()
        val cond = USB_COMMON_COND().apply { byChannelID = 1.toByte() }
        val ok = nativeBridge.USB_GetImageEnhancementV20(userId, cond, returned)
        if (!ok) return false
        out.copyFrom(returned)
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
        val registration = registerJnaStreamCallback(userId, callback, suppliedJnaCallback)
        val jnaCallback = registration.callback
        val registrationEpoch = registration.epoch
        var nativeParam: JnaUSB_STREAM_CALLBACK_PARAM? = null
        return completeJnaStartRegistration(
            userId = userId,
            registrationEpoch = registrationEpoch,
            streamType = param.dwStreamType,
            dwSize = { nativeParam?.dwSize ?: -1 },
            writeAction = {
                nativeParam = JnaUSB_STREAM_CALLBACK_PARAM().also {
                    // Official JNA wrapper shape: dwSize = nativeParam.size()
                    it.dwSize = it.size()
                    it.dwStreamType = param.dwStreamType
                    it.pUser = Pointer.NULL
                    it.fnStreamCallBack = jnaCallback
                    jnaCallbackParamWriter.write(it)
                }
            },
            invokeAction = {
                jnaStartStreamCallbackInvoker.USB_StartStreamCallback(userId, requireNotNull(nativeParam))
            },
        )
    }

    private fun completeJnaStartRegistration(
        userId: Int,
        registrationEpoch: Long,
        streamType: Int,
        dwSize: () -> Int,
        writeAction: () -> Unit,
        invokeAction: () -> Int,
    ): Int {
        setActiveStreamCallbackStateIfCurrent(userId, registrationEpoch, -1)
        var phase = "write"
        return try {
            writeAction()
            phase = "invoke"
            val channel = invokeAction()
            setActiveStreamCallbackStateIfCurrent(userId, registrationEpoch, channel)
            phase = "last_error"
            val lastError = USB_GetLastError()
            lastStartStreamCallbackDetail =
                "official_jna_wrapper_return channel=$channel lastError=$lastError userId=$userId streamType=$streamType dwSize=${dwSize()}"
            if (channel == -1) {
                invalidateStreamCallbackRegistrationIfCurrent(userId, registrationEpoch)
                resetStreamCallbackEntryDiagnostics()
            }
            channel
        } catch (throwable: Throwable) {
            invalidateStreamCallbackRegistrationIfCurrent(userId, registrationEpoch)
            resetStreamCallbackEntryDiagnostics()
            lastStartStreamCallbackDetail =
                "official_jna_wrapper_throw phase=$phase type=${throwable::class.java.name} userId=$userId streamType=$streamType dwSize=${dwSize()}"
            throw throwable
        }
    }

    private data class JnaStreamCallbackRegistration(
        val epoch: Long,
        val callback: com.hcusbsdk.jna.HCUSBSDKByJNA.FStreamCallBack,
    )

    private fun registerJnaStreamCallback(
        userId: Int,
        callback: FStreamCallBack,
        @Suppress("UNUSED_PARAMETER")
        suppliedJnaCallback: com.hcusbsdk.jna.HCUSBSDKByJNA.FStreamCallBack?,
    ): JnaStreamCallbackRegistration {
        val registrationEpoch = streamRegistrationEpochCounter.incrementAndGet()
        val jnaCallback = com.hcusbsdk.jna.HCUSBSDKByJNA.FStreamCallBack { callbackUserId, framePointer, _ ->
            val candidate = framePointer.toJnaFrameCopyCandidate()
            recordRejectedCallbackFrame("jna", callbackUserId, candidate.summary, candidate.rejectionReason)
        }
        synchronized(m_fnStreamCallBack) {
            m_fnStreamCallBack[userId] = callback
            activeStreamRegistrationEpochs[userId] = registrationEpoch
            jnaStreamCallbackKeepAlives[userId] = jnaCallback
            jniStreamCallbackKeepAlives[userId] = null
        }
        return JnaStreamCallbackRegistration(registrationEpoch, jnaCallback)
    }

    internal fun interface HostJnaStreamCallback {
        fun invoke(callbackUserId: Int, frame: NativeFrameCopySource)
    }

    internal fun registerJnaStreamCallbackForHostTest(
        userId: Int,
        callback: FStreamCallBack,
        suppliedJnaCallback: com.hcusbsdk.jna.HCUSBSDKByJNA.FStreamCallBack,
    ): HostJnaStreamCallback {
        val registration = registerJnaStreamCallback(userId, callback, suppliedJnaCallback)
        return HostJnaStreamCallback { callbackUserId, frame ->
            val rejectionReason = frame.copyRejectionReason()
            val frameSummary = frame.toFrameEntrySummary()
            if (rejectionReason != null) {
                recordRejectedCallbackFrame("jna", callbackUserId, frameSummary, rejectionReason)
            } else {
                val registeredCallback = callbackForRegistrationDispatch(
                    route = "jna",
                    registeredUserId = userId,
                    registrationEpoch = registration.epoch,
                    registeredCallback = callback,
                    callbackUserId = callbackUserId,
                    frameSummary = frameSummary,
                )
                if (registeredCallback != null) {
                    suppliedJnaCallback.invoke(callbackUserId, null, null)
                }
            }
        }
    }

    internal fun runJnaStartTransactionForHostTest(
        userId: Int,
        callback: FStreamCallBack,
        writeAction: () -> Unit,
        invokeAction: () -> Int,
    ): Int {
        val registration = registerJnaStreamCallback(userId, callback, null)
        return completeJnaStartRegistration(
            userId = userId,
            registrationEpoch = registration.epoch,
            streamType = 0,
            dwSize = { 0 },
            writeAction = writeAction,
            invokeAction = invokeAction,
        )
    }

    private fun USB_StartStreamCallback_jni(userId: Int, param: USB_STREAM_CALLBACK_PARAM): Int {
        if (userId !in m_fnStreamCallBack.indices) return -1
        resetStreamCallbackEntryDiagnostics()
        val callback = param.fnStreamCallBack ?: return -1
        val registrationEpoch = streamRegistrationEpochCounter.incrementAndGet()
        val jniCallback = com.hcusbsdk.jni.StreamCallBack_JNI { callbackUserId, frameInfo ->
            val rejectionReason = frameInfo.copyRejectionReason()
            val frameSummary = frameInfo.toFrameEntrySummary()
            if (rejectionReason != null) {
                recordRejectedCallbackFrame("jni", callbackUserId, frameSummary, rejectionReason)
            } else {
                val registeredCallback = callbackForRegistrationDispatch(
                    route = "jni",
                    registeredUserId = userId,
                    registrationEpoch = registrationEpoch,
                    registeredCallback = callback,
                    callbackUserId = callbackUserId,
                    frameSummary = frameSummary,
                )
                registeredCallback?.invoke(callbackUserId, requireNotNull(frameInfo).toInterfaceFrame())
            }
        }
        synchronized(m_fnStreamCallBack) {
            m_fnStreamCallBack[userId] = callback
            activeStreamRegistrationEpochs[userId] = registrationEpoch
            jniStreamCallbackKeepAlives[userId] = jniCallback
            jnaStreamCallbackKeepAlives[userId] = null
        }
        setActiveStreamCallbackStateIfCurrent(userId, registrationEpoch, -1)
        val jniParam = com.hcusbsdk.jni.USB_STREAM_CALLBACK_PARAM().apply {
            dwSize = 0
            dwStreamType = param.dwStreamType
        }
        return try {
            val channel = jniStartStreamCallbackInvoker.USB_StartStreamCallback(userId, jniParam, jniCallback)
            setActiveStreamCallbackStateIfCurrent(userId, registrationEpoch, channel)
            val lastError = USB_GetLastError()
            lastStartStreamCallbackDetail =
                "official_jni_wrapper_return channel=$channel lastError=$lastError userId=$userId streamType=${param.dwStreamType} dwSize=${jniParam.dwSize}"
            if (channel == -1) {
                invalidateStreamCallbackRegistrationIfCurrent(userId, registrationEpoch)
                resetStreamCallbackEntryDiagnostics()
            }
            channel
        } catch (throwable: Throwable) {
            invalidateStreamCallbackRegistrationIfCurrent(userId, registrationEpoch)
            resetStreamCallbackEntryDiagnostics()
            lastStartStreamCallbackDetail =
                "official_jni_wrapper_throw type=${throwable::class.java.name} userId=$userId streamType=${param.dwStreamType} dwSize=${jniParam.dwSize}"
            throw throwable
        }
    }

    fun USB_StopChannel(userId: Int, channel: Int): Boolean {
        val suspended = suspendStreamCallbackRegistration(userId)
        val stopped = try {
            com.hcusbsdk.jni.HCUSBSDKByJNI.getInstance().USB_StopChannel(userId, channel)
        } catch (throwable: Throwable) {
            restoreStreamCallbackRegistration(suspended)
            throw throwable
        }
        if (stopped) {
            invalidateStreamCallbackRegistration(userId)
        } else {
            restoreStreamCallbackRegistration(suspended)
        }
        return stopped
    }

    fun USB_Logout(userId: Int): Boolean {
        invalidateStreamCallbackRegistration(userId)
        return HCUSBSDK.getInstance().USB_Logout(userId)
    }

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

    internal data class SuspendedStreamCallbackRegistration(
        val userId: Int,
        val epoch: Long,
        val callback: FStreamCallBack,
    )

    internal fun suspendStreamCallbackRegistration(userId: Int): SuspendedStreamCallbackRegistration? {
        if (userId !in m_fnStreamCallBack.indices) return null
        synchronized(m_fnStreamCallBack) {
            val callback = m_fnStreamCallBack[userId] ?: return null
            val epoch = activeStreamRegistrationEpochs[userId]
            if (epoch == 0L) return null
            activeStreamRegistrationEpochs[userId] = 0L
            return SuspendedStreamCallbackRegistration(userId, epoch, callback)
        }
    }

    internal fun restoreStreamCallbackRegistration(suspended: SuspendedStreamCallbackRegistration?) {
        suspended ?: return
        synchronized(m_fnStreamCallBack) {
            if (
                activeStreamRegistrationEpochs[suspended.userId] == 0L &&
                m_fnStreamCallBack[suspended.userId] === suspended.callback
            ) {
                activeStreamRegistrationEpochs[suspended.userId] = suspended.epoch
            }
        }
    }

    internal fun invalidateStreamCallbackRegistration(userId: Int) {
        if (userId !in m_fnStreamCallBack.indices) return
        synchronized(m_fnStreamCallBack) {
            activeStreamRegistrationEpochs[userId] = 0L
            m_fnStreamCallBack[userId] = null
            jniStreamCallbackKeepAlives[userId] = null
            jnaStreamCallbackKeepAlives[userId] = null
        }
        if (activeStreamCallbackUserId == userId) resetActiveStreamCallbackState()
    }

    private fun invalidateStreamCallbackRegistrationIfCurrent(userId: Int, registrationEpoch: Long) {
        synchronized(m_fnStreamCallBack) {
            if (activeStreamRegistrationEpochs[userId] == registrationEpoch) {
                activeStreamRegistrationEpochs[userId] = 0L
                m_fnStreamCallBack[userId] = null
                jniStreamCallbackKeepAlives[userId] = null
                jnaStreamCallbackKeepAlives[userId] = null
            }
            if (
                activeStreamCallbackUserId == userId &&
                activeStreamCallbackRegistrationEpoch == registrationEpoch
            ) {
                resetActiveStreamCallbackState()
            }
        }
    }

    private fun setActiveStreamCallbackStateIfCurrent(userId: Int, registrationEpoch: Long, channel: Int) {
        synchronized(m_fnStreamCallBack) {
            if (activeStreamRegistrationEpochs[userId] != registrationEpoch) return
            activeStreamCallbackUserId = userId
            activeStreamCallbackChannel = channel
            activeStreamCallbackRegistrationEpoch = registrationEpoch
        }
    }

    internal fun activeStreamRegistrationEpochForTest(userId: Int): Long =
        if (userId in m_fnStreamCallBack.indices) {
            synchronized(m_fnStreamCallBack) { activeStreamRegistrationEpochs[userId] }
        } else {
            0L
        }

    private fun resetActiveStreamCallbackState() {
        activeStreamCallbackUserId = -1
        activeStreamCallbackChannel = -1
        activeStreamCallbackRegistrationEpoch = 0L
    }

    internal fun dispatchJnaFrameCopySourceForHostTest(callbackUserId: Int, frame: NativeFrameCopySource) {
        val rejectionReason = frame.copyRejectionReason()
        val frameSummary = frame.toFrameEntrySummary()
        if (rejectionReason != null) {
            recordRejectedCallbackFrame("jna", callbackUserId, frameSummary, rejectionReason)
        } else {
            val callback = callbackForDispatch("jna", callbackUserId, frameSummary)
            callback?.invoke(callbackUserId, frame.toInterfaceFrame())
        }
    }

    internal fun dispatchJnaFrameDeclarationForHostTest(
        callbackUserId: Int,
        declaredBytes: Int,
        pointerPresent: Boolean,
    ) {
        val summary =
            "dwBufSize=$declaredBytes availableBytes=unavailable_pointer_abi " +
                "nativeAllocationLengthValidated=false pBufNull=${!pointerPresent}"
        val rejectionReason = jnaFrameCopyRejectionReason(declaredBytes, pointerPresent)
        if (rejectionReason != null) {
            recordRejectedCallbackFrame("jna", callbackUserId, summary, rejectionReason)
        }
    }

    private fun recordRejectedCallbackFrame(
        route: String,
        callbackUserId: Int,
        frameSummary: String,
        rejectionReason: String,
    ) {
        val totalCount = streamCallbackTotalEntryCounter.incrementAndGet()
        val rejectedCount = streamCallbackRejectedEntryCounter.incrementAndGet()
        lastStreamCallbackRejectedEntryDetail =
            "route=$route disposition=rejected dropReason=$rejectionReason rejectedCount=$rejectedCount totalEntryCount=$totalCount callbackUserId=$callbackUserId activeUserId=$activeStreamCallbackUserId activeChannel=$activeStreamCallbackChannel $frameSummary"
    }

    private fun callbackForDispatch(
        route: String,
        callbackUserId: Int,
        frameSummary: String,
    ): FStreamCallBack? {
        val callback = if (callbackUserId in m_fnStreamCallBack.indices) {
            synchronized(m_fnStreamCallBack) { m_fnStreamCallBack[callbackUserId] }
        } else {
            null
        }
        if (callback == null) {
            val dropReason = if (callbackUserId !in m_fnStreamCallBack.indices) {
                "slot_out_of_range"
            } else {
                "slot_cleared_or_unregistered"
            }
            recordRejectedCallbackFrame(route, callbackUserId, frameSummary, dropReason)
            return null
        }

        val totalCount = streamCallbackTotalEntryCounter.incrementAndGet()
        val dispatchedCount = streamCallbackDispatchedEntryCounter.incrementAndGet()
        lastStreamCallbackEntryDetail =
            "route=$route disposition=dispatched dispatchedCount=$dispatchedCount totalEntryCount=$totalCount callbackUserId=$callbackUserId activeUserId=$activeStreamCallbackUserId activeChannel=$activeStreamCallbackChannel $frameSummary"
        return callback
    }

    private fun callbackForRegistrationDispatch(
        route: String,
        registeredUserId: Int,
        registrationEpoch: Long,
        registeredCallback: FStreamCallBack,
        callbackUserId: Int,
        frameSummary: String,
    ): FStreamCallBack? {
        val currentEpoch: Long
        val callbackMatches: Boolean
        synchronized(m_fnStreamCallBack) {
            currentEpoch = activeStreamRegistrationEpochs[registeredUserId]
            callbackMatches = m_fnStreamCallBack[registeredUserId] === registeredCallback
        }
        val callback = registeredCallback.takeIf {
            callbackUserId == registeredUserId &&
                currentEpoch == registrationEpoch &&
                callbackMatches
        }
        if (callback == null) {
            val dropReason = when {
                callbackUserId != registeredUserId -> "user_id_mismatch"
                currentEpoch != registrationEpoch -> "stale_registration_epoch"
                else -> "callback_replaced"
            }
            recordRejectedCallbackFrame(
                route,
                callbackUserId,
                "registeredUserId=$registeredUserId registrationEpoch=$registrationEpoch activeEpoch=$currentEpoch $frameSummary",
                dropReason,
            )
            return null
        }

        val totalCount = streamCallbackTotalEntryCounter.incrementAndGet()
        val dispatchedCount = streamCallbackDispatchedEntryCounter.incrementAndGet()
        lastStreamCallbackEntryDetail =
            "route=$route disposition=dispatched dispatchedCount=$dispatchedCount totalEntryCount=$totalCount callbackUserId=$callbackUserId registeredUserId=$registeredUserId registrationEpoch=$registrationEpoch activeEpoch=$currentEpoch activeUserId=$activeStreamCallbackUserId activeChannel=$activeStreamCallbackChannel $frameSummary"
        return callback
    }

    private fun NativeFrameCopySource.toFrameEntrySummary(): String =
        "dwBufSize=$dwBufSize availableBytes=${pBuf.size} dwFrameType=$dwFrameType dwDataType=$dwDataType dwStreamType=$dwStreamType frameNum=$nFrameNum"

    private data class JnaFrameCopyCandidate(
        val summary: String,
        val rejectionReason: String,
    )

    private fun Pointer?.toJnaFrameCopyCandidate(): JnaFrameCopyCandidate {
        if (this == null) {
            return JnaFrameCopyCandidate("frame=null nativeCapacity=unavailable_pointer_abi", "frame_pointer_null")
        }
        return JnaFrameCopyCandidate(
            "framePointerPresent=true availableBytes=unavailable_pointer_abi nativeAllocationLengthValidated=false",
            "native_allocation_capacity_unprovable",
        )
    }

    private fun com.hcusbsdk.jni.USB_FRAME_INFO?.toFrameEntrySummary(): String {
        if (this == null) return "frame=null"
        return "dwBufSize=$dwBufSize availableBytes=${pBuf.size} dwFrameType=$dwFrameType dwDataType=$dwDataType dwStreamType=$dwStreamType frameNum=$nFrameNum"
    }

    private fun jnaFrameCopyRejectionReason(declaredBytes: Int, pointerPresent: Boolean): String? = when {
        declaredBytes < 0 -> "negative_declared_length"
        declaredBytes > MAX_JNA_FRAME_COPY_BYTES -> "declared_length_exceeds_max"
        declaredBytes > 0 && !pointerPresent -> "positive_declared_length_with_null_pointer"
        else -> null
    }

    private fun NativeFrameCopySource.copyRejectionReason(): String? = when {
        dwBufSize < 0 -> "negative_declared_length"
        dwBufSize > MAX_JNA_FRAME_COPY_BYTES -> "declared_length_exceeds_max"
        dwBufSize > pBuf.size -> "declared_length_exceeds_available_bytes"
        else -> null
    }

    private fun NativeFrameCopySource.toInterfaceFrame(): USB_FRAME_INFO {
        check(copyRejectionReason() == null)
        val bytes = pBuf.copyOf(dwBufSize)
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
            dwBufSize = this@toInterfaceFrame.dwBufSize
        }
    }

    private fun com.hcusbsdk.jni.USB_FRAME_INFO?.copyRejectionReason(): String? = when {
        this == null -> "frame_info_null"
        dwBufSize < 0 -> "negative_declared_length"
        dwBufSize > MAX_JNA_FRAME_COPY_BYTES -> "declared_length_exceeds_max"
        dwBufSize > pBuf.size -> "declared_length_exceeds_available_bytes"
        else -> null
    }

    private fun com.hcusbsdk.jni.USB_FRAME_INFO.toInterfaceFrame(): USB_FRAME_INFO {
        check(copyRejectionReason() == null)
        return USB_FRAME_INFO().also { target ->
            target.nStamp = nStamp
            target.dwStreamType = dwStreamType
            target.dwWidth = dwWidth
            target.dwHeight = dwHeight
            target.dwFrameRate = dwFrameRate
            target.dwFrameType = dwFrameType
            target.dwDataType = dwDataType
            target.nFrameNum = nFrameNum
            target.pBuf = pBuf.copyOf(dwBufSize)
            target.dwBufSize = dwBufSize
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

        override fun USB_GetImageBrightNess(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_BRIGHTNESS): Boolean {
            val nativeParam = JnaUSB_IMAGE_BRIGHTNESS().apply { dwSize = size() }
            val ok = getDeviceConfig(userId, USB_GET_IMAGE_BRIGHTNESS, nativeParam, cond.toJnaCond())
            if (ok) out.dwBrightness = nativeParam.dwBrightness
            return ok
        }

        override fun USB_GetImageContrast(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_CONTRAST): Boolean {
            val nativeParam = JnaUSB_IMAGE_CONTRAST().apply { dwSize = size() }
            val ok = getDeviceConfig(userId, USB_GET_IMAGE_CONTRAST, nativeParam, cond.toJnaCond())
            if (ok) out.dwContrast = nativeParam.dwContrast
            return ok
        }

        override fun USB_GetImageEnhancement(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_ENHANCEMENT): Boolean {
            val nativeParam = JnaUSB_IMAGE_ENHANCEMENT().apply { dwSize = size() }
            val ok = getDeviceConfig(userId, USB_GET_IMAGE_ENHANCEMENT, nativeParam, cond.toJnaCond())
            if (ok) out.copyFrom(nativeParam.toInterface())
            return ok
        }

        override fun USB_GetImageEnhancementV20(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_ENHANCEMENT_EX): Boolean {
            val nativeParam = JnaUSB_IMAGE_ENHANCEMENT_EX().apply {
                struImageEnhancement.dwSize = struImageEnhancement.size()
            }
            val ok = getDeviceConfig(userId, USB_GET_IMAGE_ENHANCEMENT_V20, nativeParam, cond.toJnaCond())
            if (ok) out.copyFrom(nativeParam.toInterface())
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

        private fun USB_COMMON_COND.toJnaCond(): JnaUSB_COMMON_COND = JnaUSB_COMMON_COND().apply {
            byChannelID = this@toJnaCond.byChannelID
            byRes = this@toJnaCond.byRes.copyOf(6)
        }

        private fun JnaUSB_IMAGE_ENHANCEMENT.toInterface(): USB_IMAGE_ENHANCEMENT = USB_IMAGE_ENHANCEMENT().also { target ->
            target.byNoiseReduceMode = byNoiseReduceMode
            target.byBirdWatchingMode = byBirdWatchingMode
            target.byHighLightMode = byHighLightMode
            target.byHighLightLevel = byHighLightLevel
            target.dwGeneralLevel = dwGeneralLevel
            target.dwFrameNoiseReduceLevel = dwFrameNoiseReduceLevel
            target.dwInterFrameNoiseReduceLevel = dwInterFrameNoiseReduceLevel
            target.byPaletteMode = byPaletteMode
            target.byLSEDetailEnabled = byLSEDetailEnabled
            target.byHookEdgeMode = byHookEdgeMode
            target.byHookEdgeLevel = byHookEdgeLevel
            target.dwLSEDetailLevel = dwLSEDetailLevel
            target.byWideTemperatureMode = byWideTemperatureMode
            target.byWideTemperatureWork = byWideTemperatureWork
            target.byIspAgcMode = byIspAgcMode
            target.byAISuperResolution = byAISuperResolution
            target.dwWideTemperatureUpThreshold = dwWideTemperatureUpThreshold
            target.dwWideTemperatureDownThreshold = dwWideTemperatureDownThreshold
        }

        private fun JnaUSB_IMAGE_ENHANCEMENT_EX.toInterface(): USB_IMAGE_ENHANCEMENT_EX = USB_IMAGE_ENHANCEMENT_EX().also { target ->
            target.struImageEnhancement.copyFrom(struImageEnhancement.toInterface())
            target.bySkyAreaCullLevel = bySkyAreaCullLevel
            target.byAGCMode = byAGCMode
            target.byGaussianFilterEnabled = byGaussianFilterEnabled
            target.byEdgePreservingFilterEnabled = byEdgePreservingFilterEnabled
            target.dwGaussianFilterCenterPoint = dwGaussianFilterCenterPoint
            target.dwBilateralFilterRadius = dwBilateralFilterRadius
            target.dwBilateralFilterEdgeThreshold = dwBilateralFilterEdgeThreshold
            target.byBurnPreventionEnabled = byBurnPreventionEnabled
            target.byBurnPreventionMode = byBurnPreventionMode
            target.byRelativeHumidityThreshold = byRelativeHumidityThreshold
            target.bySharpenBoost = bySharpenBoost
            target.dwBurnPreventionShutterCloseTime = dwBurnPreventionShutterCloseTime
            target.byBurnPreventionShutterControl = byBurnPreventionShutterControl
            target.byBurnPreventionRecovery = byBurnPreventionRecovery
            target.byIsothermEnabled = byIsothermEnabled
            target.byRawDataNoiseReduceEnabled = byRawDataNoiseReduceEnabled
            target.dwIsothermalUpperThreshold = dwIsothermalUpperThreshold
            target.dwIsothermalLowerThreshold = dwIsothermalLowerThreshold
            target.byIsothermalType = byIsothermalType
            target.byColorAlarmType = byColorAlarmType
            target.dwColorAlarmUpperLimit = dwColorAlarmUpperLimit
            target.dwColorAlarmLowerLimit = dwColorAlarmLowerLimit
            target.dwRelativeHumidity = dwRelativeHumidity
            target.dwAtmosphericTemperature = dwAtmosphericTemperature
            target.byAutoShutEnabled = byAutoShutEnabled
            target.byGeneralLevelDefault = byGeneralLevelDefault
            target.byGeneralLevelMin = byGeneralLevelMin
            target.byGeneralLevelMax = byGeneralLevelMax
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
