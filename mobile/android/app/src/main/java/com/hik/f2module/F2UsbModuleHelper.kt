package com.hik.f2module

import android.content.Context
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.SystemClock
import android.util.Size
import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.Interface.USB_CTRL_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_DEVICE_INFO
import com.hcusbsdk.Interface.USB_DEVICE_REG_RES
import com.hcusbsdk.Interface.USB_STREAM_CALLBACK_PARAM
import com.hcusbsdk.Interface.USB_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_USER_LOGIN_INFO
import com.hcusbsdk.Interface.USB_VIDEO_PARAM
import com.hcusbsdk.jna.HCUSBSDK
import com.hcusbsdk.jna.HCUSBSDKByJNA
import com.hcusbsdk.jna.USB_STREAM_CALLBACK_PARAM as JnaUSB_STREAM_CALLBACK_PARAM
import com.sun.jna.Pointer

const val HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE: Int = 103
const val HIKMICRO_CALLBACK_STREAM_TYPE: Int = 103
const val HIKMICRO_PREVIEW_WIDTH: Int = 256
const val HIKMICRO_PREVIEW_HEIGHT: Int = 344
const val HIKMICRO_FRAME_RATE: Int = 25
const val HIKMICRO_THERMAL_VIDEO_CODING_TYPE: Int = 12
const val HIKMICRO_OFFICIAL_MODULE_CONFIG_LABEL: String = "mini2_f2_p20_256x344_thermal_type12"
private const val OFFICIAL_STOP_THERMAL_CTRL_MAX_RETRIES: Int = 8

enum class F2StreamStartMode(val label: String) {
    OFFICIAL_INTERFACE("official_interface_wrapper"),
    OFFICIAL_JNA("official_jna_wrapper"),
}

enum class F2ResetMode(val label: String) {
    LIGHTWEIGHT_RETRY_NO_FD_CLOSE("lightweight_retry_no_fd_close lightweight_start_retry_no_fd_close"),
    FULL_SESSION_RESET_BEFORE_CANDIDATE("full_session_reset_before_candidate full_reset_stop_channel_logout_close_selected_connection"),
}

class F2UsbModuleHelper private constructor() {
    // Lifecycle invariant for Error84 recovery diagnostics: USB_StopChannel -> USB_Logout -> closeConnection.
    private val javaInterface: JavaInterface = JavaInterface.getInstance()
    private val deviceInfoList = mutableListOf<USB_DEVICE_INFO>()
    private val officialPrimaryJnaCandidate = F2StreamFormatCandidate(
        videoFormat = HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE,
        callbackStreamType = HIKMICRO_CALLBACK_STREAM_TYPE,
        startPath = "official_primary_f2_lifecycle official_primary_f2_lifecycle_jna official_jna_primary_103_103",
        startMode = F2StreamStartMode.OFFICIAL_JNA,
        resetMode = F2ResetMode.LIGHTWEIGHT_RETRY_NO_FD_CLOSE,
    )

    private val officialPrimaryInterfaceCandidate = F2StreamFormatCandidate(
        videoFormat = HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE,
        callbackStreamType = HIKMICRO_CALLBACK_STREAM_TYPE,
        startPath = "official_primary_f2_lifecycle official_primary_f2_lifecycle_interface official_interface_primary_103_103",
        startMode = F2StreamStartMode.OFFICIAL_INTERFACE,
        resetMode = F2ResetMode.LIGHTWEIGHT_RETRY_NO_FD_CLOSE,
    )

    @Volatile
    private var sdkInited: Boolean = false

    @Volatile
    private var selectedDeviceInfo: USB_DEVICE_INFO? = null

    @Volatile
    private var selectedDeviceName: String = ""

    @Volatile
    private var callbackKeepAlive: FStreamCallBack? = null

    @Volatile
    private var jnaCallbackKeepAlive: HCUSBSDKByJNA.FStreamCallBack? = null

    @Volatile
    private var startedElapsedMs: Long = 0L

    @Volatile
    var lastStageReport: String = "not_started"
        private set

    @Volatile
    var lastFailureReason: String = "not_started"
        private set

    fun openUsbDevice(
        context: Context,
        usbManager: UsbManager,
        device: UsbDevice,
        nativeLibraryDir: String,
    ): F2OpenResult {
        return try {
            if (nativeLibraryDir.isNotBlank()) {
                HCUSBSDK.configureLibraryPath(nativeLibraryDir)
            }
            javaInterface.configureNativeBridge(JavaInterface.JnaNativeBridge(HCUSBSDK.getInstance()))

            if (!sdkInited) {
                if (!javaInterface.USB_Init()) {
                    val error = javaInterface.USB_GetLastError()
                    lastFailureReason = "USB_Init failed error=$error"
                    lastStageReport = "USB_Init=failed error=$error route=${device.vendorId}:${device.productId}"
                    return F2OpenResult(false, -1, null, lastFailureReason, lastStageReport)
                }
                sdkInited = true
            }

            val count = javaInterface.USB_GetDeviceCount(context)
            val devices = Array(count.coerceAtLeast(0)) { USB_DEVICE_INFO() }
            val enumOk = count > 0 && javaInterface.USB_EnumDevices(count, devices)
            deviceInfoList.clear()
            deviceInfoList.addAll(devices.filter { it.dwFd != 0 || it.dwVID != 0 || it.dwPID != 0 })
            val nativeEnumCount = runCatching { javaInterface.USB_GetDeviceCount() }.getOrDefault(-1)
            val selected = selectDevice(device)
            lastStageReport = "USB_Init=ok; USB_GetDeviceCount(context)=$count; USB_EnumDevices=$enumOk; nativeEnum=count=$nativeEnumCount; selectedFd=${selected?.dwFd ?: -1}; selectedIndex=${selected?.dwIndex ?: -1}; targetVid=${device.vendorId}; targetPid=${device.productId}"
            if (!enumOk || selected == null) {
                javaInterface.releaseUnselectedDeviceConnections(null)
                lastFailureReason = "Official F2 Android context enumeration did not produce an open UsbDeviceConnection; $lastStageReport"
                return F2OpenResult(false, -1, null, lastFailureReason, lastStageReport)
            }
            javaInterface.releaseUnselectedDeviceConnections(selected)

            cleanupPreviousOfficialF2Login()

            val loginInfo = USB_USER_LOGIN_INFO().apply {
                dwSize = 0
                dwTimeout = 5_000
                dwDevIndex = selected.dwIndex
                dwVID = selected.dwVID
                dwPID = selected.dwPID
                byLoginMode = 0
                dwFd = selected.dwFd
            }
            val reg = USB_DEVICE_REG_RES().apply { dwSize = 0 }
            val newUserId = javaInterface.USB_Login(loginInfo, reg)
            if (newUserId == -1) {
                val error = javaInterface.USB_GetLastError()
                val cleanupOk = javaInterface.USB_Cleanup()
                sdkInited = false
                selected.closeConnection()
                lastFailureReason = "USB_Login failed error=$error dwFd=${selected.dwFd} dwDevIndex=${selected.dwIndex} dwVID=${selected.dwVID} dwPID=${selected.dwPID}"
                lastStageReport = "$lastStageReport; USB_Login=failed error=$error; USB_Cleanup attempted ok=$cleanupOk; sdkInited=false"
                return F2OpenResult(false, -1, selected, lastFailureReason, lastStageReport)
            }

            userId = newUserId
            selectedDeviceInfo = selected
            selectedDeviceName = device.deviceName
            lastFailureReason = "open_ok"
            lastStageReport = "$lastStageReport; USB_Login(deviceInfoList[0])=ok userId=$userId dwFd=${selected.dwFd} dwDevIndex=${selected.dwIndex} dwVID=${selected.dwVID} dwPID=${selected.dwPID}; regDevice=${reg.szDeviceName}"
            F2OpenResult(true, userId, selected, lastFailureReason, lastStageReport)
        } catch (error: Throwable) {
            cleanupAfterException()
            lastFailureReason = "${error.javaClass.simpleName}: ${error.message ?: "no message"}"
            lastStageReport = "exception=$lastFailureReason"
            F2OpenResult(false, -1, null, lastFailureReason, lastStageReport)
        }
    }

    fun openUsbDevice(context: Context): Boolean {
        val count = javaInterface.USB_GetDeviceCount(context)
        val devices = Array(count.coerceAtLeast(0)) { USB_DEVICE_INFO() }
        return count > 0 && javaInterface.USB_EnumDevices(count, devices)
    }


    fun startStreamPreviewJNA(
        fStreamCallBack: HCUSBSDKByJNA.FStreamCallBack,
        size: Size,
        frameRate: Int,
        videoCodingType: Int,
        streamType: Int,
        streamingNew: Boolean,
    ): F2StartResult {
        val jnaCallbackParam = JnaUSB_STREAM_CALLBACK_PARAM().apply {
            dwStreamType = streamType
            fnStreamCallBack = fStreamCallBack
        }
        val officialInterfaceCallback = FStreamCallBack { _, _ ->
            // official startStreamPreviewJNA$1 compatibility callback slot; real frames arrive through HCUSBSDKByJNA.FStreamCallBack.
        }
        val interfaceCallbackParam = USB_STREAM_CALLBACK_PARAM().apply {
            dwSize = 0
            dwStreamType = streamType
            fnStreamCallBack = officialInterfaceCallback
        }
        jnaCallbackKeepAlive = fStreamCallBack
        callbackKeepAlive = officialInterfaceCallback
        val candidate = officialPrimaryJnaCandidate.copy(
            videoFormat = streamType,
            callbackStreamType = streamType,
            startPath = "${officialPrimaryJnaCandidate.startPath} official_f2_startStreamPreviewJNA_behavior_clone",
        )
        return startStreamPreviewCandidate(
            jnaCallbackParam = jnaCallbackParam,
            interfaceCallbackParam = interfaceCallbackParam,
            size = size,
            frameRate = frameRate,
            videoCodingType = videoCodingType,
            candidate = candidate,
            streamingNew = streamingNew,
        )
    }

    fun startStreamPreview(
        fStreamCallBack: FStreamCallBack,
        size: Size,
        frameRate: Int,
        videoCodingType: Int,
        streamType: Int,
        streamingNew: Boolean,
    ): F2StartResult {
        val callbackParam = USB_STREAM_CALLBACK_PARAM().apply {
            dwSize = 0
            dwStreamType = streamType
            fnStreamCallBack = fStreamCallBack
        }
        callbackKeepAlive = fStreamCallBack
        val candidate = officialPrimaryInterfaceCandidate.copy(
            videoFormat = streamType,
            callbackStreamType = streamType,
            startPath = "${officialPrimaryInterfaceCandidate.startPath} official_f2_startStreamPreview_behavior_clone",
        )
        return startStreamPreviewCandidate(
            interfaceCallbackParam = callbackParam,
            size = size,
            frameRate = frameRate,
            videoCodingType = videoCodingType,
            candidate = candidate,
            streamingNew = streamingNew,
        )
    }

    fun stopStreamPreview(context: Context, streamingNew: Boolean): F2StageResult {
        val stopStreamPreviewBeforeOfficialPrimaryStart = "stopStreamPreviewBeforeOfficialPrimaryStart"
        val currentUserId = userId
        val currentChannel = channel
        val thermalCtrlSummary = if (streamingNew && currentUserId != -1) {
            val thermalOff = setThermalStreamCtrl(currentUserId, enable = false)
            val verify = verifyThermalStreamCtrlDisabled(context, currentUserId, thermalOff)
            "USB_SetThermalStreamCtrl(false)=attempted ok=$thermalOff; $verify"
        } else {
            "USB_SetThermalStreamCtrl(false)=skipped userId=$currentUserId streamingNew=$streamingNew"
        }
        val summary = if (currentUserId != -1 && currentChannel != -1) {
            val ok = javaInterface.USB_StopChannel(currentUserId, currentChannel)
            if (ok) clearOfficialCallbackSlots()
            channel = -1
            "$stopStreamPreviewBeforeOfficialPrimaryStart $thermalCtrlSummary; USB_StopChannel=attempted ok=$ok userId=$currentUserId channel=$currentChannel streamingNew=$streamingNew context=${context.packageName}"
        } else {
            "$stopStreamPreviewBeforeOfficialPrimaryStart $thermalCtrlSummary; USB_StopChannel=skipped userId=$currentUserId channel=$currentChannel streamingNew=$streamingNew context=${context.packageName}"
        }
        lastStageReport = "$lastStageReport; $summary"
        return F2StageResult(true, summary)
    }

    fun closeSession() {
        cleanupPreviousOfficialF2Login()
    }

    fun isStreamingForDevice(deviceName: String): Boolean =
        userId != -1 && channel != -1 && selectedDeviceName == deviceName

    fun activeStartedElapsedMs(): Long = startedElapsedMs

    fun activeUserId(): Int = userId

    fun activeChannel(): Int = channel

    fun activeSelectedFd(): Int = selectedDeviceInfo?.dwFd ?: -1

    private fun startStreamPreviewCandidate(
        jnaCallbackParam: JnaUSB_STREAM_CALLBACK_PARAM,
        interfaceCallbackParam: USB_STREAM_CALLBACK_PARAM,
        size: Size,
        frameRate: Int,
        videoCodingType: Int,
        candidate: F2StreamFormatCandidate,
        streamingNew: Boolean,
    ): F2StartResult {
        val currentUserId = userId
        if (currentUserId == -1) {
            lastFailureReason = "stream callback skipped because official login has not succeeded"
            lastStageReport = "$lastStageReport; ${candidate.startPath}; login=missing resetMode=${candidate.resetMode.label}"
            return F2StartResult(
                false,
                false,
                -1,
                lastFailureReason,
                lastStageReport,
                attemptDiagnostics = listOf(
                    candidate.toDiagnostic(
                        setVideoStatus = "not_run",
                        startStatus = "login_missing",
                        lastError = -1,
                        channel = -1,
                        fd = activeSelectedFd(),
                        userId = currentUserId,
                    )
                ),
            )
        }

        val videoParam = USB_VIDEO_PARAM().apply {
            dwVideoFormat = candidate.videoFormat
            dwWidth = size.width
            dwHeight = size.height
            dwFramerate = frameRate
        }
        val videoOk = javaInterface.USB_SetVideoParam(currentUserId, videoParam)
        val formatAttempts = mutableListOf<String>()
        val attemptDiagnostics = mutableListOf<F2StreamAttemptDiagnostic>()
        if (!videoOk) {
            val error = javaInterface.USB_GetLastError()
            val attempt = candidate.describe("setVideo_failed error=$error")
            formatAttempts += attempt
            attemptDiagnostics += candidate.toDiagnostic(
                setVideoStatus = "failed",
                startStatus = "not_started",
                lastError = error,
                channel = -1,
                fd = activeSelectedFd(),
                userId = currentUserId,
            )
            lastFailureReason = "USB_SetVideoParam failed before USB_StartStreamCallback ${candidate.describe("")} error=$error"
            lastStageReport = "$lastStageReport; ${candidate.startPath}; startMode=${candidate.startMode.label}; resetMode=${candidate.resetMode.label}; USB_SET_VIDEO_PARAM=failed command=3004 error=$error videoFormat=${candidate.videoFormat}; USB_SetVideoParam failed before USB_StartStreamCallback; next=official_primary_error_report; formatAttempts=${formatAttempts.joinToString(prefix = "[", postfix = "]")}"
            return F2StartResult(false, false, -1, lastFailureReason, lastStageReport, formatAttempts, attemptDiagnostics)
        }

        val callbackStarted = USB_StartStreamCallbackJNA(jnaCallbackParam, interfaceCallbackParam)
        val startedChannel = if (callbackStarted) channel else -1
        if (startedChannel == -1) {
            val error = javaInterface.USB_GetLastError()
            val attempt = candidate.describe("setVideo_ok startStream_failed error=$error")
            formatAttempts += attempt
            val startDetail = javaInterface.lastStartStreamCallbackDetail
            attemptDiagnostics += candidate.toDiagnostic(
                setVideoStatus = "ok",
                startStatus = "failed",
                lastError = error,
                channel = -1,
                fd = activeSelectedFd(),
                userId = currentUserId,
            )
            lastFailureReason = "USB_StartStreamCallback failed error=$error videoFormat=${candidate.videoFormat} callbackStreamType=${candidate.callbackStreamType}"
            lastStageReport = "$lastStageReport; ${candidate.startPath}; startMode=${candidate.startMode.label}; resetMode=${candidate.resetMode.label}; moduleConfig=$HIKMICRO_OFFICIAL_MODULE_CONFIG_LABEL; USB_SET_VIDEO_PARAM=ok videoFormat=${candidate.videoFormat} size=${size.width}x${size.height} fps=$frameRate; startStream=failed error=$error videoFormat=${candidate.videoFormat} callbackStreamType=${candidate.callbackStreamType}; startDetail=$startDetail; next=official_primary_error_report; formatAttempts=${formatAttempts.joinToString(prefix = "[", postfix = "]")}"
            return F2StartResult(false, false, -1, lastFailureReason, lastStageReport, formatAttempts, attemptDiagnostics)
        }
        channel = startedChannel
        callbackKeepAlive = interfaceCallbackParam.fnStreamCallBack
        jnaCallbackKeepAlive = jnaCallbackParam.fnStreamCallBack

        val thermalParam = USB_THERMAL_STREAM_PARAM().apply {
            dwSize = 0
            byVideoCodingType = videoCodingType.toByte()
        }
        val thermalParamOk = javaInterface.USB_SetThermalStreamParam(currentUserId, thermalParam)
        val thermalParamSummary = if (!thermalParamOk) {
            val error = javaInterface.USB_GetLastError()
            "USB_SET_THERMAL_STREAM_PARAM=failed_nonfatal command=2039 videoCodingType=$videoCodingType error=$error; official_continue_after_thermal_param_result"
        } else {
            "USB_SET_THERMAL_STREAM_PARAM=ok videoCodingType=$videoCodingType"
        }

        Thread.sleep(100)
        val ctrl = USB_CTRL_THERMAL_STREAM_PARAM().apply {
            dwSize = 0
            byEnable = 1
        }
        val thermalCtrlOk = javaInterface.USB_SetThermalStreamCtrl(currentUserId, ctrl)
        val thermalCtrlSummary = if (!thermalCtrlOk) {
            val error = javaInterface.USB_GetLastError()
            "USB_SET_THERMAL_STREAM_CTRL=failed_nonfatal command=2111 error=$error; official_continue_after_thermal_ctrl_result"
        } else {
            "USB_SET_THERMAL_STREAM_CTRL=ok enable=true"
        }

        startedElapsedMs = SystemClock.elapsedRealtime()
        val attempt = candidate.describe("setVideo_ok startStream_ok channel=$startedChannel")
        formatAttempts += attempt
        attemptDiagnostics += candidate.toDiagnostic(
            setVideoStatus = "ok",
            startStatus = "ok",
            lastError = 0,
            channel = startedChannel,
            fd = activeSelectedFd(),
            userId = currentUserId,
        )
        lastFailureReason = "stream_attempt_started"
        lastStageReport = "$lastStageReport; ${candidate.startPath}; startMode=${candidate.startMode.label}; resetMode=${candidate.resetMode.label}; moduleConfig=$HIKMICRO_OFFICIAL_MODULE_CONFIG_LABEL; USB_SET_VIDEO_PARAM=ok videoFormat=${candidate.videoFormat} size=${size.width}x${size.height} fps=$frameRate; USB_StartStreamCallback=ok channel=$startedChannel dwStreamType=${candidate.callbackStreamType}; $thermalParamSummary; Thread.sleep(100); $thermalCtrlSummary; formatAttempts=${formatAttempts.joinToString(prefix = "[", postfix = "]")}; streamingNew=$streamingNew"
        return F2StartResult(
            ok = true,
            waitingForFrame = true,
            channel = startedChannel,
            reason = "F2 USB_Init/Login/StartStreamCallback and HIKMICRO thermal stream config succeeded; waiting for first USB_FRAME_INFO callback",
            stageReport = lastStageReport,
            formatAttempts = formatAttempts,
            attemptDiagnostics = attemptDiagnostics,
        )
    }

    private fun startStreamPreviewCandidate(
        interfaceCallbackParam: USB_STREAM_CALLBACK_PARAM,
        size: Size,
        frameRate: Int,
        videoCodingType: Int,
        candidate: F2StreamFormatCandidate,
        streamingNew: Boolean,
    ): F2StartResult {
        val currentUserId = userId
        if (currentUserId == -1) {
            lastFailureReason = "stream callback skipped because official login has not succeeded"
            lastStageReport = "$lastStageReport; ${candidate.startPath}; login=missing resetMode=${candidate.resetMode.label}"
            return F2StartResult(
                false,
                false,
                -1,
                lastFailureReason,
                lastStageReport,
                attemptDiagnostics = listOf(
                    candidate.toDiagnostic(
                        setVideoStatus = "not_run",
                        startStatus = "login_missing",
                        lastError = -1,
                        channel = -1,
                        fd = activeSelectedFd(),
                        userId = currentUserId,
                    )
                ),
            )
        }

        val videoParam = USB_VIDEO_PARAM().apply {
            dwVideoFormat = candidate.videoFormat
            dwWidth = size.width
            dwHeight = size.height
            dwFramerate = frameRate
        }
        val videoOk = javaInterface.USB_SetVideoParam(currentUserId, videoParam)
        val formatAttempts = mutableListOf<String>()
        val attemptDiagnostics = mutableListOf<F2StreamAttemptDiagnostic>()
        if (!videoOk) {
            val error = javaInterface.USB_GetLastError()
            val attempt = candidate.describe("setVideo_failed error=$error")
            formatAttempts += attempt
            attemptDiagnostics += candidate.toDiagnostic(
                setVideoStatus = "failed",
                startStatus = "not_started",
                lastError = error,
                channel = -1,
                fd = activeSelectedFd(),
                userId = currentUserId,
            )
            lastFailureReason = "USB_SetVideoParam failed before USB_StartStreamCallback ${candidate.describe("")} error=$error"
            lastStageReport = "$lastStageReport; ${candidate.startPath}; startMode=${candidate.startMode.label}; resetMode=${candidate.resetMode.label}; USB_SET_VIDEO_PARAM=failed command=3004 error=$error videoFormat=${candidate.videoFormat}; USB_SetVideoParam failed before USB_StartStreamCallback; next=official_primary_error_report; formatAttempts=${formatAttempts.joinToString(prefix = "[", postfix = "]")}"
            return F2StartResult(false, false, -1, lastFailureReason, lastStageReport, formatAttempts, attemptDiagnostics)
        }

        val callbackStarted = USB_StartStreamCallback(interfaceCallbackParam)
        val startedChannel = if (callbackStarted) channel else -1
        if (startedChannel == -1) {
            val error = javaInterface.USB_GetLastError()
            val attempt = candidate.describe("setVideo_ok startStream_failed error=$error")
            formatAttempts += attempt
            val startDetail = javaInterface.lastStartStreamCallbackDetail
            attemptDiagnostics += candidate.toDiagnostic(
                setVideoStatus = "ok",
                startStatus = "failed",
                lastError = error,
                channel = -1,
                fd = activeSelectedFd(),
                userId = currentUserId,
            )
            lastFailureReason = "USB_StartStreamCallback failed error=$error videoFormat=${candidate.videoFormat} callbackStreamType=${candidate.callbackStreamType}"
            lastStageReport = "$lastStageReport; ${candidate.startPath}; startMode=${candidate.startMode.label}; resetMode=${candidate.resetMode.label}; moduleConfig=$HIKMICRO_OFFICIAL_MODULE_CONFIG_LABEL; USB_SET_VIDEO_PARAM=ok videoFormat=${candidate.videoFormat} size=${size.width}x${size.height} fps=$frameRate; startStream=failed error=$error videoFormat=${candidate.videoFormat} callbackStreamType=${candidate.callbackStreamType}; startDetail=$startDetail; next=official_primary_error_report; formatAttempts=${formatAttempts.joinToString(prefix = "[", postfix = "]")}"
            return F2StartResult(false, false, -1, lastFailureReason, lastStageReport, formatAttempts, attemptDiagnostics)
        }
        channel = startedChannel
        callbackKeepAlive = interfaceCallbackParam.fnStreamCallBack

        val thermalParam = USB_THERMAL_STREAM_PARAM().apply {
            dwSize = 0
            byVideoCodingType = videoCodingType.toByte()
        }
        val thermalParamOk = javaInterface.USB_SetThermalStreamParam(currentUserId, thermalParam)
        val thermalParamSummary = if (!thermalParamOk) {
            val error = javaInterface.USB_GetLastError()
            "USB_SET_THERMAL_STREAM_PARAM=failed_nonfatal command=2039 videoCodingType=$videoCodingType error=$error; official_continue_after_thermal_param_result"
        } else {
            "USB_SET_THERMAL_STREAM_PARAM=ok videoCodingType=$videoCodingType"
        }

        Thread.sleep(100)
        val ctrl = USB_CTRL_THERMAL_STREAM_PARAM().apply {
            dwSize = 0
            byEnable = 1
        }
        val thermalCtrlOk = javaInterface.USB_SetThermalStreamCtrl(currentUserId, ctrl)
        val thermalCtrlSummary = if (!thermalCtrlOk) {
            val error = javaInterface.USB_GetLastError()
            "USB_SET_THERMAL_STREAM_CTRL=failed_nonfatal command=2111 error=$error; official_continue_after_thermal_ctrl_result"
        } else {
            "USB_SET_THERMAL_STREAM_CTRL=ok enable=true"
        }

        startedElapsedMs = SystemClock.elapsedRealtime()
        val attempt = candidate.describe("setVideo_ok startStream_ok channel=$startedChannel")
        formatAttempts += attempt
        attemptDiagnostics += candidate.toDiagnostic(
            setVideoStatus = "ok",
            startStatus = "ok",
            lastError = 0,
            channel = startedChannel,
            fd = activeSelectedFd(),
            userId = currentUserId,
        )
        lastFailureReason = "stream_attempt_started"
        lastStageReport = "$lastStageReport; ${candidate.startPath}; startMode=${candidate.startMode.label}; resetMode=${candidate.resetMode.label}; moduleConfig=$HIKMICRO_OFFICIAL_MODULE_CONFIG_LABEL; USB_SET_VIDEO_PARAM=ok videoFormat=${candidate.videoFormat} size=${size.width}x${size.height} fps=$frameRate; USB_StartStreamCallback=ok channel=$startedChannel dwStreamType=${candidate.callbackStreamType}; $thermalParamSummary; Thread.sleep(100); $thermalCtrlSummary; formatAttempts=${formatAttempts.joinToString(prefix = "[", postfix = "]")}; streamingNew=$streamingNew"
        return F2StartResult(
            ok = true,
            waitingForFrame = true,
            channel = startedChannel,
            reason = "F2 USB_Init/Login/StartStreamCallback and HIKMICRO thermal stream config succeeded; waiting for first USB_FRAME_INFO callback",
            stageReport = lastStageReport,
            formatAttempts = formatAttempts,
            attemptDiagnostics = attemptDiagnostics,
        )
    }

    private fun USB_StartStreamCallbackJNA(
        cbParam: JnaUSB_STREAM_CALLBACK_PARAM,
        struStreamCBParam: USB_STREAM_CALLBACK_PARAM,
    ): Boolean {
        val currentUserId = userId
        val callbackSlots = JavaInterface.getInstance().m_fnStreamCallBack
        if (currentUserId < 0 || currentUserId >= callbackSlots.size) {
            return false
        }
        synchronized(callbackSlots) {
            callbackSlots[currentUserId] = struStreamCBParam.fnStreamCallBack
        }
        val nativeParam = JnaUSB_STREAM_CALLBACK_PARAM().apply {
            dwSize = size()
            dwStreamType = struStreamCBParam.dwStreamType
            pUser = Pointer.NULL
            fnStreamCallBack = cbParam.fnStreamCallBack
            write()
        }
        callbackKeepAlive = struStreamCBParam.fnStreamCallBack
        jnaCallbackKeepAlive = cbParam.fnStreamCallBack
        val rawChannel = try {
            HCUSBSDK.getInstance().USB_StartStreamCallback(currentUserId, nativeParam.pointer)
        } catch (_: Throwable) {
            -1
        }
        channel = rawChannel
        if (rawChannel == -1) {
            synchronized(callbackSlots) {
                callbackSlots[currentUserId] = null
            }
        }
        return rawChannel != -1
    }

    private fun USB_StartStreamCallback(callbackParam: USB_STREAM_CALLBACK_PARAM): Boolean {
        val currentUserId = userId
        val rawChannel = javaInterface.USB_StartStreamCallback(currentUserId, callbackParam)
        channel = rawChannel
        return rawChannel != -1
    }

    private fun selectDevice(device: UsbDevice): USB_DEVICE_INFO? =
        deviceInfoList.firstOrNull { it.szDeviceName == device.deviceName }
            ?: deviceInfoList.firstOrNull { it.dwVID == device.vendorId && it.dwPID == device.productId }

    private fun cleanupPreviousOfficialF2Login() {
        val currentUserId = userId
        val currentChannel = channel
        val selectedFd = selectedDeviceInfo?.dwFd ?: -1
        if (currentUserId != -1) {
            val thermalOff = setThermalStreamCtrl(currentUserId, enable = false)
            val verify = verifyThermalStreamCtrlDisabled(context = null, currentUserId = currentUserId, initialDisableOk = thermalOff)
            lastStageReport = "$lastStageReport; ${F2ResetMode.FULL_SESSION_RESET_BEFORE_CANDIDATE.label} USB_SetThermalStreamCtrl(false)=attempted ok=$thermalOff userId=$currentUserId; $verify"
        } else {
            lastStageReport = "$lastStageReport; ${F2ResetMode.FULL_SESSION_RESET_BEFORE_CANDIDATE.label} USB_SetThermalStreamCtrl(false)=skipped userId=$currentUserId"
        }
        if (currentUserId != -1 && currentChannel != -1) {
            val stopOk = runCatching { javaInterface.USB_StopChannel(currentUserId, currentChannel) }.getOrDefault(false)
            if (stopOk) clearOfficialCallbackSlots()
            lastStageReport = "$lastStageReport; ${F2ResetMode.FULL_SESSION_RESET_BEFORE_CANDIDATE.label} USB_StopChannel=attempted ok=$stopOk userId=$currentUserId channel=$currentChannel"
        } else {
            lastStageReport = "$lastStageReport; ${F2ResetMode.FULL_SESSION_RESET_BEFORE_CANDIDATE.label} USB_StopChannel=skipped userId=$currentUserId channel=$currentChannel"
        }
        if (currentUserId != -1) {
            val logoutOk = runCatching { javaInterface.USB_Logout(currentUserId) }.getOrDefault(false)
            lastStageReport = "$lastStageReport; ${F2ResetMode.FULL_SESSION_RESET_BEFORE_CANDIDATE.label} USB_Logout=attempted ok=$logoutOk userId=$currentUserId"
        } else {
            lastStageReport = "$lastStageReport; ${F2ResetMode.FULL_SESSION_RESET_BEFORE_CANDIDATE.label} USB_Logout=skipped userId=$currentUserId"
        }
        lastStageReport = "$lastStageReport; ${F2ResetMode.FULL_SESSION_RESET_BEFORE_CANDIDATE.label} closeConnection=attempted selectedFd=$selectedFd"
        selectedDeviceInfo?.closeConnection()
        userId = -1
        channel = -1
        selectedDeviceInfo = null
        selectedDeviceName = ""
        callbackKeepAlive = null
        jnaCallbackKeepAlive = null
        startedElapsedMs = 0L
    }

    private fun setThermalStreamCtrl(currentUserId: Int, enable: Boolean): Boolean =
        runCatching {
            javaInterface.USB_SetThermalStreamCtrl(
                currentUserId,
                USB_CTRL_THERMAL_STREAM_PARAM().apply {
                    dwSize = 0
                    byEnable = if (enable) 1 else 0
                },
            )
        }.getOrDefault(false)

    private fun getThermalStreamCtrlState(currentUserId: Int): ThermalStreamCtrlState {
        val param = USB_CTRL_THERMAL_STREAM_PARAM().apply { dwSize = 0 }
        val ok = runCatching { javaInterface.USB_GetThermalStreamCtrl(currentUserId, param) }.getOrDefault(false)
        val error = if (ok) 0 else runCatching { javaInterface.USB_GetLastError() }.getOrDefault(-1)
        return ThermalStreamCtrlState(
            ok = ok,
            streamEnable = ok && param.byEnable.toInt() != 0,
            byEnable = param.byEnable.toInt(),
            lastError = error,
        )
    }

    private fun verifyThermalStreamCtrlDisabled(
        context: Context?,
        currentUserId: Int,
        initialDisableOk: Boolean,
    ): String {
        val deviceCountNote = context?.packageName?.let { packageName ->
            "deviceCountCheck=skipped_preserve_selected_fd context=$packageName"
        } ?: "deviceCountCheck=skipped_no_context"
        val parts = mutableListOf(
            "verifyThermalStreamCtrlDisabled official_stop_lifecycle start initialDisableOk=$initialDisableOk $deviceCountNote maxRetries=$OFFICIAL_STOP_THERMAL_CTRL_MAX_RETRIES"
        )
        for (retryIndex in 0..OFFICIAL_STOP_THERMAL_CTRL_MAX_RETRIES) {
            val state = getThermalStreamCtrlState(currentUserId)
            parts += "USB_GetThermalStreamCtrl=attempted ok=${state.ok} streamEnable=${state.streamEnable} byEnable=${state.byEnable} error=${state.lastError} retryIndex=$retryIndex"
            if (state.ok && !state.streamEnable) {
                parts += "verifyThermalStreamCtrlDisabled=done streamEnable=false retryIndex=$retryIndex"
                return parts.joinToString("; ")
            }
            if (retryIndex >= OFFICIAL_STOP_THERMAL_CTRL_MAX_RETRIES) break
            val retryOk = setThermalStreamCtrl(currentUserId, enable = false)
            parts += "USB_SetThermalStreamCtrl(false)#retry=attempted ok=$retryOk retryIndex=${retryIndex + 1}"
            runCatching { Thread.sleep(((retryIndex + 1) * 10L).coerceAtMost(100L)) }
        }
        parts += "verifyThermalStreamCtrlDisabled=gave_up"
        return parts.joinToString("; ")
    }

    private fun clearOfficialCallbackSlots() {
        val callbacks = JavaInterface.getInstance().m_fnStreamCallBack
        synchronized(callbacks) {
            callbacks.fill(null)
        }
    }

    private fun cleanupAfterException() {
        cleanupPreviousOfficialF2Login()
        javaInterface.releaseAllDeviceConnections()
    }

    companion object {
        @JvmField
        @Volatile
        var userId: Int = -1

        @JvmField
        @Volatile
        var channel: Int = -1

        @JvmField
        val INSTANCE: F2UsbModuleHelper = F2UsbModuleHelper()
    }
}

data class F2OpenResult(
    val ok: Boolean,
    val userId: Int,
    val deviceInfo: USB_DEVICE_INFO?,
    val reason: String,
    val stageReport: String,
)

data class F2StartResult(
    val ok: Boolean,
    val waitingForFrame: Boolean,
    val channel: Int,
    val reason: String,
    val stageReport: String,
    val formatAttempts: List<String> = emptyList(),
    val attemptDiagnostics: List<F2StreamAttemptDiagnostic> = emptyList(),
)

data class F2StageResult(
    val ok: Boolean,
    val summary: String,
)

private data class ThermalStreamCtrlState(
    val ok: Boolean,
    val streamEnable: Boolean,
    val byEnable: Int,
    val lastError: Int,
)

data class F2StreamFrame(
    val callbackUserId: Int,
    val frameCounter: Long,
    val width: Int,
    val height: Int,
    val frameType: Int,
    val dataType: Int,
    val streamType: Int,
    val bytes: ByteArray,
)

fun interface F2StreamCallback {
    fun onFrame(frame: F2StreamFrame)
}

data class F2StreamFormatCandidate(
    val videoFormat: Int,
    val callbackStreamType: Int,
    val startPath: String,
    val startMode: F2StreamStartMode,
    val resetMode: F2ResetMode,
    val verboseOnly: Boolean = false,
) {
    fun describe(result: String): String =
        "videoFormat=$videoFormat/callbackStreamType=$callbackStreamType/path=$startPath/startMode=${startMode.label}/resetMode=${resetMode.label}/verboseOnly=$verboseOnly${result.takeIf { it.isNotBlank() }?.let { ":$it" } ?: ""}"

    fun toDiagnostic(
        setVideoStatus: String,
        startStatus: String,
        lastError: Int,
        channel: Int,
        fd: Int = -1,
        userId: Int = -1,
    ): F2StreamAttemptDiagnostic = F2StreamAttemptDiagnostic(
        startMode = startMode.label,
        resetMode = resetMode.label,
        videoFormat = videoFormat,
        callbackStreamType = callbackStreamType,
        setVideoStatus = setVideoStatus,
        startStatus = startStatus,
        lastError = lastError,
        channel = channel,
        fd = fd,
        userId = userId,
        startPath = startPath,
        verboseOnly = verboseOnly,
    )
}

data class F2StreamAttemptDiagnostic(
    val startMode: String,
    val resetMode: String,
    val videoFormat: Int,
    val callbackStreamType: Int,
    val setVideoStatus: String,
    val startStatus: String,
    val lastError: Int,
    val channel: Int,
    val fd: Int,
    val userId: Int,
    val startPath: String,
    val verboseOnly: Boolean,
)
