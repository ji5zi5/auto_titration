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
import com.hcusbsdk.Interface.USB_SYSTEM_DEVICE_INFO
import com.hcusbsdk.Interface.USB_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_THERMOMETRY_CALIBRATION_FILE
import com.hcusbsdk.Interface.USB_GET_THERMOMETRY_CALIBRATION_FILE
import com.hcusbsdk.Interface.USB_USER_LOGIN_INFO
import com.hcusbsdk.Interface.USB_VIDEO_PARAM
import com.hcusbsdk.jna.HCUSBSDK
import com.hcusbsdk.jna.HCUSBSDKByJNA
import com.hcusbsdk.jna.USB_STREAM_CALLBACK_PARAM as JnaUSB_STREAM_CALLBACK_PARAM
import com.sun.jna.Pointer
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolution
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolver
import java.io.File
import java.io.FileOutputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

const val HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE: Int = 103
const val HIKMICRO_CALLBACK_STREAM_TYPE: Int = 103
const val HIKMICRO_PREVIEW_WIDTH: Int = 256
const val HIKMICRO_PREVIEW_HEIGHT: Int = 344
const val HIKMICRO_FRAME_RATE: Int = 25
const val HIKMICRO_THERMAL_VIDEO_CODING_TYPE: Int = 12
const val HIKMICRO_OFFICIAL_MODULE_CONFIG_LABEL: String = "mini2_f2_p20_256x344_thermal_type12"
private const val OFFICIAL_STOP_THERMAL_CTRL_MAX_RETRIES: Int = 100

internal inline fun <T> withTemporaryF2ContextEnumerationCleanup(
    crossinline releaseTemporaryEnumerationConnections: () -> Unit,
    block: () -> T,
): T {
    try {
        return block()
    } finally {
        releaseTemporaryEnumerationConnections()
    }
}

class F2UsbModuleHelper private constructor() {
    // Lifecycle invariant for Error84 recovery diagnostics: USB_StopChannel -> USB_Logout -> closeConnection.
    private val javaInterface: JavaInterface = JavaInterface.getInstance()
    private val deviceInfoList = mutableListOf<USB_DEVICE_INFO>()


    @Volatile
    private var sdkInited: Boolean = false

    @Volatile
    private var selectedDeviceInfo: USB_DEVICE_INFO? = null

    @Volatile
    private var selectedDeviceName: String = ""

    @Volatile
    private var selectedProfileResolution: HikmicroF2ProfileResolution? = null

    @Volatile
    private var selectedSystemDeviceInfo: USB_SYSTEM_DEVICE_INFO? = null

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

    @Synchronized
    fun openUsbDevice(
        context: Context,
        usbManager: UsbManager,
        device: UsbDevice,
        nativeLibraryDir: String,
    ): F2OpenResult {
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
        val inventory = deviceInfoList.joinToString(prefix = "[", postfix = "]") { info ->
            "index=${info.dwIndex},fd=${info.dwFd},vid=${info.dwVID},pid=${info.dwPID},name=${info.szDeviceName}"
        }
        val selected = selectOfficialContextEnumeratedDeviceInfo()
        lastStageReport = "USB_Init=ok; USB_GetDeviceCount(context)=$count; USB_EnumDevices=$enumOk; enumerationInventory=$inventory; officialSelection=deviceInfoList[0]; selectedFd=${selected?.dwFd ?: -1}; selectedIndex=${selected?.dwIndex ?: -1}; targetVid=${device.vendorId}; targetPid=${device.productId}"
        if (!enumOk || selected == null) {
            javaInterface.releaseUnselectedDeviceConnections(null)
            lastFailureReason = "Official F2 Android context enumeration did not produce an open UsbDeviceConnection; $lastStageReport"
            return F2OpenResult(false, -1, null, lastFailureReason, lastStageReport)
        }
        javaInterface.releaseUnselectedDeviceConnections(selected)

        cleanupPreviousOfficialF2Login(context)

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
        selectedDeviceName = selected.szDeviceName.ifBlank { device.deviceName }
        val systemDeviceInfo = USB_SYSTEM_DEVICE_INFO()
        val systemInfoOk = javaInterface.USB_GetSysTemDeviceInfo(userId, systemDeviceInfo)
        val profileResolution = if (systemInfoOk) {
            HikmicroF2ProfileResolver.resolve(systemDeviceInfo.byModuleID, normalizeOfficialFirmwareVersion(systemDeviceInfo.byFirmwareVersion))
        } else {
            HikmicroF2ProfileResolution(
                profile = null,
                moduleId = null,
                firmwareDate = null,
                reason = "system_device_info_failed error=${javaInterface.USB_GetLastError()}",
            )
        }
        selectedProfileResolution = profileResolution
        selectedSystemDeviceInfo = systemDeviceInfo.copyIdentity()
        lastFailureReason = if (profileResolution.isResolved) "open_ok" else "profile_unresolved ${profileResolution.reason}"
        lastStageReport = "$lastStageReport; USB_Login(deviceInfoList[0])=ok userId=$userId dwFd=${selected.dwFd} dwDevIndex=${selected.dwIndex} dwVID=${selected.dwVID} dwPID=${selected.dwPID}; regDevice=${reg.szDeviceName}; USB_GET_SYSTEM_DEVICE_INFO=attempted ok=$systemInfoOk command=2011 moduleId=${systemDeviceInfo.byModuleID} firmwareVersion=${systemDeviceInfo.byFirmwareVersion}; selectedProfile=${profileResolution.profile?.officialClassName ?: "unresolved"} profileReason=${profileResolution.reason} profileSize=${profileResolution.profile?.previewSize ?: "unresolved"} profileFps=${profileResolution.profile?.fps ?: -1} profileCoding=${profileResolution.profile?.thermalCoding ?: -1} profileStreamingNew=${profileResolution.profile?.streamingNew ?: false} profileAllowedSizes=${profileResolution.profile?.allowedPacketSizes ?: emptySet<Int>()}"
        return F2OpenResult(true, userId, selected, lastFailureReason, lastStageReport, systemDeviceInfo, profileResolution)
    }

    @Synchronized
    fun openUsbDevice(context: Context): Boolean {
        val count = javaInterface.USB_GetDeviceCount(context)
        val devices = Array(count.coerceAtLeast(0)) { USB_DEVICE_INFO() }
        return count > 0 && javaInterface.USB_EnumDevices(count, devices)
    }


    @Synchronized
    fun startStreamPreviewJNA(
        fStreamCallBack: HCUSBSDKByJNA.FStreamCallBack,
        size: Size,
        frameRate: Int,
        videoCodingType: Int,
        streamType: Int,
        streamingNew: Boolean,
    ): F2StartResult {
        activeProfileResolution()?.takeUnless { it.isResolved }?.let { return profileUnresolvedStartResult(it) }
        USB_SetVideoParam(size, frameRate, streamType)
        val jnaCallbackParam = JnaUSB_STREAM_CALLBACK_PARAM().apply {
            dwStreamType = streamType
            fnStreamCallBack = fStreamCallBack
        }
        val interfaceCallbackParam = USB_STREAM_CALLBACK_PARAM().apply {
            dwSize = 0
            dwStreamType = streamType
            fnStreamCallBack = FStreamCallBack { _, _ -> }
        }
        val callbackStarted = USB_StartStreamCallbackJNA(jnaCallbackParam, interfaceCallbackParam)
        if (!callbackStarted) {
            val error = javaInterface.USB_GetLastError()
            lastFailureReason = "startStreamPreviewJNA failed errorCode=$error"
            lastStageReport = "$lastStageReport; startStreamPreviewJNA failed resultCode=$error"
            return F2StartResult(false, false, error, lastFailureReason, lastStageReport)
        }
        if (videoCodingType > 0) {
            USB_SetThermalStreamParam(videoCodingType)
        }
        if (streamingNew) {
            Thread.sleep(100)
            USB_SetThermalStreamCtrl(true)
        }
        startedElapsedMs = SystemClock.elapsedRealtime()
        lastFailureReason = "stream_attempt_started"
        lastStageReport = "$lastStageReport; startStreamPreviewJNA resultCode=1 channel=$channel streamingNew=$streamingNew"
        return F2StartResult(true, true, 1, lastFailureReason, lastStageReport)
    }

    @Synchronized
    fun startStreamPreview(
        fStreamCallBack: FStreamCallBack,
        size: Size,
        frameRate: Int,
        videoCodingType: Int,
        streamType: Int,
        streamingNew: Boolean,
    ): F2StartResult {
        activeProfileResolution()?.takeUnless { it.isResolved }?.let { return profileUnresolvedStartResult(it) }
        USB_SetVideoParam(size, frameRate, streamType)
        val callbackParam = USB_STREAM_CALLBACK_PARAM().apply {
            dwSize = 0
            dwStreamType = streamType
            fnStreamCallBack = fStreamCallBack
        }
        callbackKeepAlive = fStreamCallBack
        val callbackStarted = USB_StartStreamCallback(callbackParam)
        if (!callbackStarted) {
            val error = javaInterface.USB_GetLastError()
            lastFailureReason = "startStreamPreview failed errorCode=$error"
            lastStageReport = "$lastStageReport; startStreamPreview failed errorCode=$error"
            return F2StartResult(false, false, error, lastFailureReason, lastStageReport)
        }
        if (videoCodingType > 0) {
            USB_SetThermalStreamParam(videoCodingType)
        }
        if (streamingNew) {
            Thread.sleep(100)
            USB_SetThermalStreamCtrl(true)
        }
        startedElapsedMs = SystemClock.elapsedRealtime()
        lastFailureReason = "stream_attempt_started"
        lastStageReport = "$lastStageReport; startStreamPreview resultCode=1 channel=$channel streamingNew=$streamingNew"
        return F2StartResult(true, true, 1, lastFailureReason, lastStageReport)
    }

    @Synchronized
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

    @Synchronized
    fun closeSession() {
        cleanupPreviousOfficialF2Login()
    }

    fun isStreamingForDevice(deviceName: String): Boolean =
        userId != -1 && channel != -1 && selectedDeviceName == deviceName

    fun activeStartedElapsedMs(): Long = startedElapsedMs

    fun activeUserId(): Int = userId

    fun activeChannel(): Int = channel

    fun activeSelectedFd(): Int = selectedDeviceInfo?.dwFd ?: -1

    fun activeProfileResolution(): HikmicroF2ProfileResolution? = selectedProfileResolution

    @Synchronized
    fun acquireThermometryCalibrationFileOnce(cacheDir: File): F2CalibrationFileResult {
        val currentUserId = userId
        val selected = selectedDeviceInfo?.copyCalibrationIdentity()
        if (currentUserId == -1 || selected == null) {
            return F2CalibrationFileResult(
                ok = false,
                file = null,
                provenance = null,
                reason = "login_required_for_command_2054",
            )
        }
        return acquireThermometryCalibrationFile(
            F2CalibrationAcquisitionSnapshot(
                userId = currentUserId,
                deviceInfo = selected,
                systemDeviceInfo = selectedSystemDeviceInfo?.copyIdentity(),
                cacheDir = canonicalCacheDirectory(cacheDir),
            ),
        )
    }

    fun latestCalibrationAcquisitionResult(): F2CalibrationFileResult? = null

    fun onPreviewFrameForCalibrationPrefetch(
        cacheDir: File,
        previewFrameCounter: Long,
    ) {
        // Official F2 API/start callbacks do not issue command 2054.
    }

    private fun USB_SetVideoParam(videoSize: Size, frameRate: Int, streamType: Int): Boolean {
        val param = USB_VIDEO_PARAM().apply {
            dwVideoFormat = streamType
            dwWidth = videoSize.width
            dwHeight = videoSize.height
            dwFramerate = frameRate
        }
        return javaInterface.USB_SetVideoParam(userId, param)
    }

    private fun USB_SetThermalStreamParam(videoCodingType: Int): Boolean {
        val param = USB_THERMAL_STREAM_PARAM().apply {
            dwSize = 0
            byVideoCodingType = videoCodingType.toByte()
        }
        return javaInterface.USB_SetThermalStreamParam(userId, param)
    }

    private fun USB_SetThermalStreamCtrl(enable: Boolean): Boolean =
        javaInterface.USB_SetThermalStreamCtrl(
            userId,
            USB_CTRL_THERMAL_STREAM_PARAM().apply {
                dwSize = 0
                byEnable = if (enable) 1 else 0
            },
        )

    private fun USB_StartStreamCallback(callbackParam: USB_STREAM_CALLBACK_PARAM): Boolean {
        val rawChannel = javaInterface.USB_StartStreamCallback(userId, callbackParam)
        channel = rawChannel
        return rawChannel != -1
    }

    private fun USB_StartStreamCallbackJNA(
        cbParam: JnaUSB_STREAM_CALLBACK_PARAM,
        struStreamCBParam: USB_STREAM_CALLBACK_PARAM,
    ): Boolean {
        val callbackSlots = JavaInterface.getInstance().m_fnStreamCallBack
        if (userId >= 0 && userId < callbackSlots.size) {
            synchronized(callbackSlots) {
                callbackSlots[userId] = struStreamCBParam.fnStreamCallBack
            }
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
        val rawChannel = HCUSBSDK.getInstance().USB_StartStreamCallback(userId, nativeParam.pointer)
        channel = rawChannel
        return rawChannel != -1
    }

    private fun selectOfficialContextEnumeratedDeviceInfo(): USB_DEVICE_INFO? =
        deviceInfoList.firstOrNull()

    private fun normalizeOfficialFirmwareVersion(version: String): String {
        val trimmed = trimString(version)
        val parts = trimmed.split("_")
        if (parts.size < 4) return trimmed
        val module = parts[1].let { if (it.length == 5) "0$it" else it }
        return "${parts[0]}_${module}_${parts[3]}"
    }

    private fun trimString(value: String): String = value.trim { it <= ' ' || it == '\u0000' }

    private fun profileDiagnosticLabel(): String {
        val resolution = selectedProfileResolution
        val profile = resolution?.profile
        return "selectedProfile=${profile?.officialClassName ?: "unresolved"} profileReason=${resolution?.reason ?: "not_read"} moduleId=${resolution?.moduleId ?: ""} firmwareDate=${resolution?.firmwareDate ?: -1} profileSize=${profile?.previewSize ?: "unresolved"} profileFps=${profile?.fps ?: -1} profileCoding=${profile?.thermalCoding ?: -1} profileStreamingNew=${profile?.streamingNew ?: false} profileAllowedSizes=${profile?.allowedPacketSizes ?: emptySet<Int>()}"
    }

    private fun profileUnresolvedStartResult(resolution: HikmicroF2ProfileResolution): F2StartResult {
        lastFailureReason = "profile_unresolved ${resolution.reason}"
        lastStageReport = "$lastStageReport; profile_unresolved command=2011 reason=${resolution.reason} moduleId=${resolution.moduleId ?: ""} firmwareDate=${resolution.firmwareDate ?: -1}; USB_SET_VIDEO_PARAM=not_run; USB_StartStreamCallback=not_run"
        return F2StartResult(
            ok = false,
            waitingForFrame = false,
            channel = -1,
            reason = lastFailureReason,
            stageReport = lastStageReport,
            profileResolution = resolution,
        )
    }

    private fun cleanupPreviousOfficialF2Login(context: Context? = null) {
        val currentUserId = userId
        val currentChannel = channel
        val selectedFd = selectedDeviceInfo?.dwFd ?: -1
        channel = -1
        if (currentUserId != -1) {
            val thermalOff = setThermalStreamCtrl(currentUserId, enable = false)
            val verify = verifyThermalStreamCtrlDisabled(context = context, currentUserId = currentUserId, initialDisableOk = thermalOff)
            lastStageReport = "$lastStageReport; official_login_reset USB_SetThermalStreamCtrl(false)=attempted ok=$thermalOff userId=$currentUserId; $verify"
        } else {
            lastStageReport = "$lastStageReport; official_login_reset USB_SetThermalStreamCtrl(false)=skipped userId=$currentUserId"
        }
        if (currentUserId != -1 && currentChannel != -1) {
            val stopOk = javaInterface.USB_StopChannel(currentUserId, currentChannel)
            if (stopOk) clearOfficialCallbackSlots()
            lastStageReport = "$lastStageReport; official_login_reset USB_StopChannel=attempted ok=$stopOk userId=$currentUserId channel=$currentChannel"
        } else {
            lastStageReport = "$lastStageReport; official_login_reset USB_StopChannel=skipped userId=$currentUserId channel=$currentChannel"
        }
        if (currentUserId != -1) {
            val logoutOk = javaInterface.USB_Logout(currentUserId)
            lastStageReport = "$lastStageReport; official_login_reset USB_Logout=attempted ok=$logoutOk userId=$currentUserId"
        } else {
            lastStageReport = "$lastStageReport; official_login_reset USB_Logout=skipped userId=$currentUserId"
        }
        lastStageReport = "$lastStageReport; official_login_reset closeConnection=attempted selectedFd=$selectedFd"
        selectedDeviceInfo?.closeConnection()
        userId = -1
        channel = -1
        selectedDeviceInfo = null
        selectedDeviceName = ""
        selectedProfileResolution = null
        selectedSystemDeviceInfo = null
        callbackKeepAlive = null
        jnaCallbackKeepAlive = null
        startedElapsedMs = 0L
    }

    private fun setThermalStreamCtrl(currentUserId: Int, enable: Boolean): Boolean =
        javaInterface.USB_SetThermalStreamCtrl(
            currentUserId,
            USB_CTRL_THERMAL_STREAM_PARAM().apply {
                dwSize = 0
                byEnable = if (enable) 1 else 0
            },
        )

    private fun getThermalStreamCtrlState(currentUserId: Int): ThermalStreamCtrlState {
        val param = USB_CTRL_THERMAL_STREAM_PARAM().apply { dwSize = 0 }
        val ok = javaInterface.USB_GetThermalStreamCtrl(currentUserId, param)
        val error = if (ok) 0 else javaInterface.USB_GetLastError()
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
        val deviceCountNote = context?.let { safeContext ->
            withTemporaryF2ContextEnumerationCleanup(
                releaseTemporaryEnumerationConnections = {
                    javaInterface.releaseUnselectedDeviceConnections(selectedDeviceInfo)
                },
            ) {
                val count = javaInterface.USB_GetDeviceCount(safeContext)
                val enumOk = if (count > 0) {
                    javaInterface.USB_EnumDevices(count, Array(count) { USB_DEVICE_INFO() })
                } else {
                    false
                }
                "deviceCountCheck=attempted context=${safeContext.packageName} count=$count reEnumerateOk=$enumOk"
            }
        } ?: "deviceCountCheck=skipped_no_context"
        val parts = mutableListOf(
            "verifyThermalStreamCtrlDisabled official_stop_lifecycle bounded_poll_reenumerate_retry start initialDisableOk=$initialDisableOk $deviceCountNote maxRetries=$OFFICIAL_STOP_THERMAL_CTRL_MAX_RETRIES"
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
            try {
                Thread.sleep(((retryIndex + 1) * 10L).coerceAtMost(100L))
            } catch (error: InterruptedException) {
                Thread.currentThread().interrupt()
            }
        }
        parts += "verifyThermalStreamCtrlDisabled=gave_up"
        return parts.joinToString("; ")
    }

    private fun acquireThermometryCalibrationFile(
        snapshot: F2CalibrationAcquisitionSnapshot,
    ): F2CalibrationFileResult {
        val identity = buildCalibrationIdentity(snapshot.deviceInfo, snapshot.systemDeviceInfo)
        val targetDir = sanitizeCacheDirectory(snapshot.cacheDir)
        val fileName = "HM-Calibration_${identity.serialFileComponent}.dat"
        val targetFile = File(targetDir, fileName)
        if (targetFile.isFile && targetFile.length() > 0L) {
            val bytes = targetFile.readBytes()
            if (bytes.isNotEmpty()) {
                return F2CalibrationFileResult(
                    ok = true,
                    file = targetFile,
                    provenance = F2CalibrationFileProvenance(
                        sha256 = sha256Hex(bytes),
                        length = bytes.size,
                        identityKey = identity.identityKey,
                        nativeCommand = USB_GET_THERMOMETRY_CALIBRATION_FILE,
                        cacheState = F2CalibrationCacheState.HIT.state,
                        formatState = F2_CALIBRATION_FORMAT_STATE_UNVERIFIED_2054,
                    ),
                    reason = "cache_hit",
                )
            }
        }

        val calibration = USB_THERMOMETRY_CALIBRATION_FILE()
        val ok = javaInterface.USB_GetThermometryCalibrationFile(snapshot.userId, calibration)
        if (!ok) {
            val error = javaInterface.USB_GetLastError()
            return calibrationFailureResult(
                identity = identity,
                length = calibration.dwFileLenth,
                reason = "USB_GetThermometryCalibrationFile failed error=$error dwFileLenth=${calibration.dwFileLenth}",
            )
        }

        val bytes = calibration.pCalibrationFile.copyOf(calibration.dwFileLenth)
        atomicWrite(targetFile, bytes)
        return F2CalibrationFileResult(
            ok = true,
            file = targetFile,
            provenance = F2CalibrationFileProvenance(
                sha256 = sha256Hex(bytes),
                length = bytes.size,
                identityKey = identity.identityKey,
                nativeCommand = USB_GET_THERMOMETRY_CALIBRATION_FILE,
                cacheState = F2CalibrationCacheState.FETCHED.state,
                formatState = F2_CALIBRATION_FORMAT_STATE_UNVERIFIED_2054,
            ),
            reason = "fetched",
        )
    }

    private fun calibrationFailureResult(
        identity: F2CalibrationIdentity,
        length: Int = 0,
        reason: String,
    ): F2CalibrationFileResult = F2CalibrationFileResult(
        ok = false,
        file = null,
        provenance = F2CalibrationFileProvenance(
            sha256 = "",
            length = length,
            identityKey = identity.identityKey,
            nativeCommand = USB_GET_THERMOMETRY_CALIBRATION_FILE,
            cacheState = F2CalibrationCacheState.FETCH_FAILED.state,
            formatState = F2_CALIBRATION_FORMAT_STATE_UNVERIFIED_2054,
        ),
        reason = reason,
    )

    private fun canonicalCacheDirectory(cacheDir: File): File =
        cacheDir.canonicalFile

    private fun buildCalibrationIdentity(
        selected: USB_DEVICE_INFO,
        systemInfo: USB_SYSTEM_DEVICE_INFO?,
    ): F2CalibrationIdentity {
        val serial = trimString(
            selected.szSerialNumber.ifBlank { systemInfo?.bySerialNumber.orEmpty() }
        ).ifBlank { "unknown_serial" }
        val moduleId = trimString(systemInfo?.byModuleID.orEmpty())
        val firmware = trimString(systemInfo?.byFirmwareVersion.orEmpty())
        val deviceId = trimString(systemInfo?.byDeviceID.orEmpty())
        val parts = listOf(
            "vid=${selected.dwVID}",
            "pid=${selected.dwPID}",
            "serial=$serial",
            "moduleId=$moduleId",
            "firmware=$firmware",
            "deviceId=$deviceId",
        )
        val identityKey = parts.joinToString("|")
        return F2CalibrationIdentity(
            identityKey = identityKey,
            serialFileComponent = sanitizeFileComponent(serial),
        )
    }

    private fun sanitizeCacheDirectory(cacheDir: File): File {
        cacheDir.mkdirs()
        return cacheDir.canonicalFile.also { it.mkdirs() }
    }

    private fun sanitizeFileComponent(value: String): String {
        val sanitized = value.trim()
            .replace(Regex("[^A-Za-z0-9._-]+"), "_")
            .trim('.', '_', '-')
        return sanitized.ifBlank { "unknown_serial" }
    }

    private fun atomicWrite(targetFile: File, bytes: ByteArray) {
        val parent = targetFile.parentFile ?: error("Calibration cache target requires a parent directory")
        parent.mkdirs()
        val tmp = File(parent, ".${targetFile.name}.${System.nanoTime()}.tmp")
        try {
            FileOutputStream(tmp).use { stream ->
                stream.write(bytes)
                stream.fd.sync()
            }
            try {
                Files.move(
                    tmp.toPath(),
                    targetFile.toPath(),
                    StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING,
                )
            } catch (_: AtomicMoveNotSupportedException) {
                Files.move(tmp.toPath(), targetFile.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
        } finally {
            if (tmp.exists()) tmp.delete()
        }
    }

    private fun sha256Hex(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256")
            .digest(bytes)
            .joinToString("") { "%02x".format(it) }

    private fun USB_DEVICE_INFO.copyCalibrationIdentity(): USB_DEVICE_INFO = USB_DEVICE_INFO().also { copy ->
        copy.dwSize = dwSize
        copy.dwIndex = dwIndex
        copy.dwVID = dwVID
        copy.dwPID = dwPID
        copy.szManufacturer = szManufacturer
        copy.szDeviceName = szDeviceName
        copy.szSerialNumber = szSerialNumber
        copy.byHaveAudio = byHaveAudio
        copy.byRes = byRes.copyOf()
        copy.dwFd = dwFd
    }

    private fun USB_SYSTEM_DEVICE_INFO.copyIdentity(): USB_SYSTEM_DEVICE_INFO = USB_SYSTEM_DEVICE_INFO().also { copy ->
        copy.byFirmwareVersion = byFirmwareVersion
        copy.byEncoderVersion = byEncoderVersion
        copy.byHardwareVersion = byHardwareVersion
        copy.byDeviceType = byDeviceType
        copy.byProtocolVersion = byProtocolVersion
        copy.bySerialNumber = bySerialNumber
        copy.bySecondHardwareVersion = bySecondHardwareVersion
        copy.byModuleID = byModuleID
        copy.byDeviceID = byDeviceID
        copy.byDeviceAssembleType = byDeviceAssembleType
        copy.byManufacturer = byManufacturer
        copy.byLanguageType = byLanguageType
        copy.byDeviceClass = byDeviceClass
    }

    private fun clearOfficialCallbackSlots() {
        val callbacks = JavaInterface.getInstance().m_fnStreamCallBack
        synchronized(callbacks) {
            callbacks.fill(null)
        }
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
    val systemDeviceInfo: USB_SYSTEM_DEVICE_INFO? = null,
    val profileResolution: HikmicroF2ProfileResolution? = null,
)

data class F2StartResult(
    val ok: Boolean,
    val waitingForFrame: Boolean,
    val channel: Int,
    val reason: String,
    val stageReport: String,
    val attemptDiagnostics: List<F2StreamAttemptDiagnostic> = emptyList(),
    val profileResolution: HikmicroF2ProfileResolution? = null,
)

data class F2StageResult(
    val ok: Boolean,
    val summary: String,
)

const val F2_CALIBRATION_FORMAT_STATE_UNVERIFIED_2054: String = "unverified_2054_calibration_file"

data class F2CalibrationFileResult(
    val ok: Boolean,
    val file: File?,
    val provenance: F2CalibrationFileProvenance?,
    val reason: String,
)

data class F2CalibrationFileProvenance(
    val sha256: String,
    val length: Int,
    val identityKey: String,
    val nativeCommand: Int,
    val cacheState: String,
    val formatState: String,
)

enum class F2CalibrationCacheState(val state: String) {
    HIT("hit"),
    FETCHED("fetched"),
    FETCH_FAILED("fetch_failed"),
}

private data class F2CalibrationIdentity(
    val identityKey: String,
    val serialFileComponent: String,
)

private data class F2CalibrationAcquisitionSnapshot(
    val userId: Int,
    val deviceInfo: USB_DEVICE_INFO,
    val systemDeviceInfo: USB_SYSTEM_DEVICE_INFO?,
    val cacheDir: File,
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


data class F2StreamAttemptDiagnostic(
    val startMode: String = "",
    val resetMode: String = "",
    val videoFormat: Int = 0,
    val callbackStreamType: Int = 0,
    val setVideoStatus: String = "",
    val startStatus: String = "",
    val lastError: Int = 0,
    val channel: Int = -1,
    val fd: Int = -1,
    val userId: Int = -1,
    val startPath: String = "",
    val verboseOnly: Boolean = false,
    val profileClass: String = "",
    val profileModuleId: String = "",
    val profileFirmwareDate: Int = -1,
    val profileAllowedSizes: Set<Int> = emptySet(),
)
