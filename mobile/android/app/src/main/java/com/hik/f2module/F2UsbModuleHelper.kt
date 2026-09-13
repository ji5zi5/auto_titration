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
import com.hcusbsdk.Interface.USB_IMAGE_BRIGHTNESS
import com.hcusbsdk.Interface.USB_IMAGE_CONTRAST
import com.hcusbsdk.Interface.USB_IMAGE_ENHANCEMENT_EX
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
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolution
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolver
import java.io.File
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.FileOutputStream
import java.io.IOException
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.Properties
import java.util.concurrent.CancellationException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.Future
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

const val HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE: Int = 103
const val HIKMICRO_CALLBACK_STREAM_TYPE: Int = 103
const val HIKMICRO_PREVIEW_WIDTH: Int = 256
const val HIKMICRO_PREVIEW_HEIGHT: Int = 344
const val HIKMICRO_FRAME_RATE: Int = 25
const val HIKMICRO_THERMAL_VIDEO_CODING_TYPE: Int = 12
const val HIKMICRO_OFFICIAL_MODULE_CONFIG_LABEL: String = "mini2_f2_p20_256x344_thermal_type12"
private const val OFFICIAL_STOP_THERMAL_CTRL_MAX_RETRIES: Int = 100
private const val OFFICIAL_STOP_THERMAL_CTRL_POLL_SLEEP_MS: Long = 10L

class F2UsbModuleHelper private constructor() {
    // Lifecycle invariant for Error84 recovery diagnostics: USB_StopChannel -> USB_Logout -> closeConnection.
    private val javaInterface: JavaInterface = JavaInterface.getInstance()
    private val deviceInfoList = mutableListOf<USB_DEVICE_INFO>()

    @Volatile
    private var latestCalibrationResult: F2CalibrationFileResult? = null

    private val calibrationPrefetchLock = Any()
    private val calibrationNativeCommandLock = Any()

    @Volatile
    private var calibrationSessionGeneration: Long = 0L

    @Volatile
    private var calibrationPrefetchAttemptedGeneration: Long = -1L

    @Volatile
    private var calibrationPrefetchFuture: Future<*>? = null

    @Volatile
    private var calibrationPrefetchExecutor: ExecutorService? = null

    @Volatile
    private var calibrationPrefetchExecutorFactory: () -> ExecutorService = { newCalibrationPrefetchExecutor() }

    @Volatile
    private var beforeCalibrationNativeCommandForTests: (() -> Unit)? = null

    @Volatile
    private var stopChannelOperation: (Int, Int) -> Boolean = { currentUserId, currentChannel ->
        javaInterface.USB_StopChannel(currentUserId, currentChannel)
    }

    @Volatile
    private var logoutOperation: (Int) -> Boolean = { currentUserId ->
        javaInterface.USB_Logout(currentUserId)
    }

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

        val cleanupResult = cleanupPreviousOfficialF2Login(context)
        if (!cleanupResult.ok) {
            selected.closeConnection()
            lastFailureReason = cleanupResult.summary
            lastStageReport = "$lastStageReport; replacement_aborted ${cleanupResult.summary}"
            return F2OpenResult(
                ok = false,
                userId = userId,
                deviceInfo = selectedDeviceInfo,
                reason = lastFailureReason,
                stageReport = lastStageReport,
                systemDeviceInfo = selectedSystemDeviceInfo,
                profileResolution = selectedProfileResolution,
            )
        }

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
        synchronized(calibrationPrefetchLock) {
            calibrationSessionGeneration += 1
            calibrationPrefetchAttemptedGeneration = -1L
        }
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
        profileAuthorityStartRejection(
            size,
            frameRate,
            videoCodingType,
            streamType,
            streamingNew,
        )?.let { return it }
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
            try {
                Thread.sleep(100)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
            }
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
        val profileResolution = activeProfileResolution()
        profileAuthorityStartRejection(
            size,
            frameRate,
            videoCodingType,
            streamType,
            streamingNew,
        )?.let { return it }
        val setVideoOk = USB_SetVideoParam(size, frameRate, streamType)
        val setVideoError = if (setVideoOk) 0 else javaInterface.USB_GetLastError()
        lastStageReport = "$lastStageReport; USB_SET_VIDEO_PARAM=${if (setVideoOk) "ok" else "failed"} videoFormat=$streamType size=${size.width}x${size.height} fps=$frameRate error=$setVideoError"
        val callbackParam = USB_STREAM_CALLBACK_PARAM().apply {
            dwSize = 0
            dwStreamType = streamType
            fnStreamCallBack = fStreamCallBack
        }
        callbackKeepAlive = fStreamCallBack
        val callbackStarted = USB_StartStreamCallback(callbackParam)
        val startError = if (callbackStarted) 0 else javaInterface.USB_GetLastError()
        val attempt = F2StreamAttemptDiagnostic(
            startMode = "official_interface_wrapper",
            resetMode = "official_stop_before_start",
            videoFormat = streamType,
            callbackStreamType = streamType,
            setVideoStatus = if (setVideoOk) "ok" else "failed",
            startStatus = if (callbackStarted) "ok" else "failed",
            lastError = startError,
            channel = channel,
            fd = selectedDeviceInfo?.dwFd ?: -1,
            userId = userId,
            startPath = "official_f2_startStreamPreview_interface",
            profileClass = profileResolution?.profile?.officialClassName.orEmpty(),
            profileModuleId = profileResolution?.moduleId.orEmpty(),
            profileFirmwareDate = profileResolution?.firmwareDate ?: -1,
            profileAllowedSizes = profileResolution?.profile?.allowedPacketSizes.orEmpty(),
        )
        if (!callbackStarted) {
            lastFailureReason = "startStreamPreview failed errorCode=$startError"
            lastStageReport = "$lastStageReport; USB_StartStreamCallback=failed channel=$channel error=$startError ${javaInterface.lastStartStreamCallbackDetail}; startStreamPreview failed errorCode=$startError"
            return F2StartResult(false, false, startError, lastFailureReason, lastStageReport, listOf(attempt), profileResolution)
        }
        lastStageReport = "$lastStageReport; USB_StartStreamCallback=ok channel=$channel error=$startError ${javaInterface.lastStartStreamCallbackDetail}"
        if (videoCodingType > 0) {
            val thermalParamOk = USB_SetThermalStreamParam(videoCodingType)
            val thermalParamError = if (thermalParamOk) 0 else javaInterface.USB_GetLastError()
            lastStageReport = "$lastStageReport; USB_SET_THERMAL_STREAM_PARAM=${if (thermalParamOk) "ok" else "failed"} command=2039 videoCodingType=$videoCodingType error=$thermalParamError; official_continue_after_thermal_param_result"
        }
        if (streamingNew) {
            try {
                Thread.sleep(100)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
            }
            val thermalCtrlOk = USB_SetThermalStreamCtrl(true)
            val thermalCtrlError = if (thermalCtrlOk) 0 else javaInterface.USB_GetLastError()
            lastStageReport = "$lastStageReport; USB_SET_THERMAL_STREAM_CTRL=${if (thermalCtrlOk) "ok" else "failed"} enable=true error=$thermalCtrlError"
        }
        startedElapsedMs = SystemClock.elapsedRealtime()
        lastFailureReason = "stream_attempt_started"
        lastStageReport = "$lastStageReport; startStreamPreview resultCode=1 channel=$channel streamingNew=$streamingNew"
        return F2StartResult(true, true, 1, lastFailureReason, lastStageReport, listOf(attempt), profileResolution)
    }

    @Synchronized
    fun stopStreamPreview(context: Context, streamingNew: Boolean): F2StageResult {
        val stopStreamPreviewBeforeOfficialPrimaryStart = "stopStreamPreviewBeforeOfficialPrimaryStart"
        val currentUserId = userId
        val currentChannel = channel
        val thermalCtrlSummary = if (streamingNew) {
            val thermalOff = setThermalStreamCtrl(currentUserId, enable = false)
            val verify = verifyThermalStreamCtrlDisabled(context, currentUserId, thermalOff)
            "USB_SetThermalStreamCtrl(false)=attempted ok=$thermalOff; $verify"
        } else {
            "USB_SetThermalStreamCtrl(false)=skipped userId=$currentUserId streamingNew=$streamingNew"
        }
        if (streamingNew) {
            try {
                Thread.sleep(100)
            } catch (error: InterruptedException) {
                Thread.currentThread().interrupt()
            }
        }
        val suspendedRegistration = javaInterface.suspendStreamCallbackRegistration(currentUserId)
        val stopResult = try {
            F2StopChannelInvocation(
                ok = stopChannelOperation(currentUserId, currentChannel),
                failureDetail = "",
            )
        } catch (error: RuntimeException) {
            F2StopChannelInvocation(
                ok = false,
                failureDetail = " throwable=${error::class.java.name}",
            )
        } catch (error: LinkageError) {
            F2StopChannelInvocation(
                ok = false,
                failureDetail = " throwable=${error::class.java.name}",
            )
        }
        val ok = stopResult.ok
        val stopError = if (ok) 0 else javaInterface.USB_GetLastError()
        if (ok) {
            clearOfficialCallbackSlots(currentUserId)
            channel = -1
            callbackKeepAlive = null
            jnaCallbackKeepAlive = null
            startedElapsedMs = 0L
        } else {
            javaInterface.restoreStreamCallbackRegistration(suspendedRegistration)
            if (streamingNew) {
                val thermalRestoreOk = setThermalStreamCtrl(currentUserId, enable = true)
                lastStageReport =
                    "$lastStageReport; USB_SetThermalStreamCtrl(true)=attempted_after_failed_stop ok=$thermalRestoreOk userId=$currentUserId"
            }
        }
        val summary = "$stopStreamPreviewBeforeOfficialPrimaryStart $thermalCtrlSummary; USB_StopChannel=attempted ok=$ok error=$stopError${stopResult.failureDetail} userId=$currentUserId channel=$currentChannel streamingNew=$streamingNew context=${context.packageName}"
        lastStageReport = "$lastStageReport; $summary"
        return F2StageResult(ok, summary)
    }

    @Synchronized
    fun closeSession(): F2StageResult = cleanupPreviousOfficialF2Login()

    fun isStreamingForDevice(deviceName: String): Boolean =
        userId != -1 && channel != -1 && selectedDeviceName == deviceName

    fun activeStartedElapsedMs(): Long = startedElapsedMs

    fun activeUserId(): Int = userId

    fun activeChannel(): Int = channel

    fun activeSelectedFd(): Int = selectedDeviceInfo?.dwFd ?: -1

    fun activeProfileResolution(): HikmicroF2ProfileResolution? = selectedProfileResolution

    @JvmOverloads
    @Synchronized
    fun acquireThermometryCalibrationFileOnce(
        cacheDir: File,
        expectedSession: F2SessionToken? = null,
    ): F2CalibrationFileResult {
        if (expectedSession != null && !isSessionTokenCurrentLocked(expectedSession)) {
            return F2CalibrationFileResult(
                ok = false,
                file = null,
                provenance = null,
                reason = "stale_f2_session_before_command_2054",
            )
        }
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
        val systemInfo = selectedSystemDeviceInfo?.copyIdentity()
        val result = acquireThermometryCalibrationFile(
            F2CalibrationAcquisitionSnapshot(
                userId = currentUserId,
                deviceInfo = selected,
                systemDeviceInfo = systemInfo,
                cacheDir = canonicalCacheDirectory(cacheDir),
            ),
        )
        latestCalibrationResult = result
        return result
    }

    fun latestCalibrationAcquisitionResult(): F2CalibrationFileResult? = latestCalibrationResult

    @JvmOverloads
    @Synchronized
    fun acquireOfficialF2MeasurementSettingsOnce(
        expectedSession: F2SessionToken? = null,
    ): F2MeasurementSettingsResult {
        if (expectedSession != null && !isSessionTokenCurrentLocked(expectedSession)) {
            return F2MeasurementSettingsResult(
                ok = false,
                settings = null,
                identityKey = expectedSession.identity.identityKey,
                reason = "stale_f2_session_before_commands_2018_2020_2080",
            )
        }
        val currentUserId = userId
        val identity = activeCalibrationIdentitySummary()
        if (currentUserId == -1 || identity == null) {
            return F2MeasurementSettingsResult(
                ok = false,
                settings = null,
                identityKey = identity?.identityKey,
                reason = "login_required_for_commands_2018_2020_2080",
            )
        }

        val brightness = USB_IMAGE_BRIGHTNESS()
        val contrast = USB_IMAGE_CONTRAST()
        val enhancement = USB_IMAGE_ENHANCEMENT_EX()
        val ok = synchronized(calibrationNativeCommandLock) {
            val brightnessOk = javaInterface.USB_GetImageBrightNess(currentUserId, brightness)
            val contrastOk = javaInterface.USB_GetImageContrast(currentUserId, contrast)
            val enhancementOk = javaInterface.USB_GetImageEnhancementV20(currentUserId, enhancement)
            if (!brightnessOk || !contrastOk || !enhancementOk) {
                return F2MeasurementSettingsResult(
                    ok = false,
                    settings = null,
                    identityKey = identity.identityKey,
                    reason = "official_f2_settings_unavailable_fail_closed brightnessOk=$brightnessOk contrastOk=$contrastOk enhancementV20Ok=$enhancementOk lastError=${javaInterface.USB_GetLastError()}",
                )
            }
            true
        }
        if (!ok) {
            return F2MeasurementSettingsResult(
                ok = false,
                settings = null,
                identityKey = identity.identityKey,
                reason = "official_f2_settings_unavailable_fail_closed",
            )
        }
        val settings = F2MeasurementSettings.fromOfficialV20(
            brightness = brightness.dwBrightness,
            contrast = contrast.dwContrast,
            enhancement = enhancement,
        )
        return F2MeasurementSettingsResult(
            ok = true,
            settings = settings,
            identityKey = identity.identityKey,
            reason = "official_f2_settings_fetched_commands_2018_2020_2080_channel_1",
        )
    }

    fun onPreviewFrameForCalibrationPrefetch(
        cacheDir: File,
        previewFrameCounter: Long,
        diagnoseMode: Boolean = false,
        previewPathEligible: Boolean = true,
    ) {
        if (previewFrameCounter != 10L || diagnoseMode || !previewPathEligible) return

        val currentUserId = userId
        val selected = selectedDeviceInfo?.copyCalibrationIdentity() ?: return
        if (currentUserId == -1) return
        val systemInfo = selectedSystemDeviceInfo?.copyIdentity()
        val snapshot = F2CalibrationAcquisitionSnapshot(
            generation = calibrationSessionGeneration,
            userId = currentUserId,
            deviceInfo = selected,
            systemDeviceInfo = systemInfo,
            cacheDir = canonicalCacheDirectory(cacheDir),
        )
        synchronized(calibrationPrefetchLock) {
            if (calibrationPrefetchAttemptedGeneration == snapshot.generation) return
            calibrationPrefetchAttemptedGeneration = snapshot.generation
        }

        val identity = buildCalibrationIdentity(snapshot.deviceInfo, snapshot.systemDeviceInfo)
        val targetDir = sanitizeCacheDirectory(snapshot.cacheDir)
        existingCalibrationFileResult(targetDir, identity)?.let { hit ->
            if (isCalibrationSnapshotCurrent(snapshot)) {
                latestCalibrationResult = hit
            }
            return
        }

        synchronized(calibrationPrefetchLock) {
            if (calibrationSessionGeneration != snapshot.generation) return
            val executor = calibrationPrefetchExecutorFactory()
            calibrationPrefetchExecutor = executor
            calibrationPrefetchFuture = executor.submit { runCalibrationPrefetch(snapshot, executor) }
        }
    }

    @Synchronized
    fun activeCalibrationIdentitySummary(): F2CalibrationIdentitySummary? {
        val selected = selectedDeviceInfo?.copyCalibrationIdentity() ?: return null
        val systemInfo = selectedSystemDeviceInfo?.copyIdentity()
        val identity = buildCalibrationIdentity(selected, systemInfo)
        return F2CalibrationIdentitySummary(
            identityKey = identity.identityKey,
            serialFileComponent = identity.serialFileComponent,
            serialNumber = trimString(selected.szSerialNumber.ifBlank { systemInfo?.bySerialNumber.orEmpty() }),
            moduleId = trimString(systemInfo?.byModuleID.orEmpty()),
            firmwareVersion = trimString(systemInfo?.byFirmwareVersion.orEmpty()),
            hardwareVersion = trimString(systemInfo?.byHardwareVersion.orEmpty()),
            deviceId = trimString(systemInfo?.byDeviceID.orEmpty()),
            deviceName = trimString(selected.szDeviceName),
            vid = selected.dwVID,
            pid = selected.dwPID,
        )
    }

    @Synchronized
    fun activeSessionToken(): F2SessionToken? {
        val currentUserId = userId
        if (currentUserId == -1) return null
        val identity = activeCalibrationIdentitySummary() ?: return null
        return F2SessionToken(
            generation = calibrationSessionGeneration,
            userId = currentUserId,
            identity = identity,
            profileResolution = selectedProfileResolution,
        )
    }

    @Synchronized
    fun isSessionTokenCurrent(token: F2SessionToken): Boolean =
        isSessionTokenCurrentLocked(token)

    private fun isSessionTokenCurrentLocked(token: F2SessionToken): Boolean {
        if (calibrationSessionGeneration != token.generation || userId != token.userId) return false
        val currentIdentity = activeCalibrationIdentitySummary() ?: return false
        return currentIdentity.identityKey == token.identity.identityKey &&
            selectedProfileResolution == token.profileResolution
    }

    internal fun resetCalibrationAcquisitionStateForTests() {
        cancelCalibrationPrefetchAndAdvanceGeneration()
        latestCalibrationResult = null
    }

    internal fun awaitCalibrationPrefetchForTests(timeoutMillis: Long = 5_000L): F2CalibrationFileResult? {
        val future = synchronized(calibrationPrefetchLock) { calibrationPrefetchFuture } ?: return latestCalibrationResult
        try {
            future.get(timeoutMillis, TimeUnit.MILLISECONDS)
        } catch (_: CancellationException) {
            // Cancellation is an expected close/reset outcome.
        } catch (_: TimeoutException) {
            throw AssertionError("Timed out waiting for calibration prefetch")
        }
        return latestCalibrationResult
    }

    internal fun installCalibrationPrefetchExecutorFactoryForTests(factory: (() -> ExecutorService)?) {
        synchronized(calibrationPrefetchLock) {
            calibrationPrefetchExecutorFactory = factory ?: { newCalibrationPrefetchExecutor() }
        }
    }

    internal fun installBeforeCalibrationNativeCommandHookForTests(hook: (() -> Unit)?) {
        beforeCalibrationNativeCommandForTests = hook
    }

    internal fun installSessionCloseOperationsForTests(
        stopChannel: ((Int, Int) -> Boolean)?,
        logout: ((Int) -> Boolean)?,
    ) {
        stopChannelOperation = stopChannel ?: { currentUserId, currentChannel ->
            javaInterface.USB_StopChannel(currentUserId, currentChannel)
        }
        logoutOperation = logout ?: { currentUserId ->
            javaInterface.USB_Logout(currentUserId)
        }
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
        callbackKeepAlive = struStreamCBParam.fnStreamCallBack
        jnaCallbackKeepAlive = cbParam.fnStreamCallBack
        val rawChannel = javaInterface.USB_StartStreamCallbackJNA(userId, cbParam, struStreamCBParam)
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

    private fun profileAuthorityStartRejection(
        size: Size,
        frameRate: Int,
        videoCodingType: Int,
        streamType: Int,
        streamingNew: Boolean,
    ): F2StartResult? {
        val resolution = selectedProfileResolution
        val profile = resolution?.profile
        if (profile == null) {
            return profileUnresolvedStartResult(
                resolution ?: HikmicroF2ProfileResolution(
                    profile = null,
                    moduleId = null,
                    firmwareDate = null,
                    reason = "system_device_info_not_read",
                ),
            )
        }
        val mismatch =
            size.width != profile.previewSize.width ||
                size.height != profile.previewSize.height ||
                frameRate != profile.fps ||
                videoCodingType != profile.thermalCoding ||
                streamType != HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE ||
                streamingNew != profile.streamingNew
        if (!mismatch) return null

        lastFailureReason =
            "profile_start_mismatch profile=${profile.officialClassName} " +
                "requested=${size.width}x${size.height}/$frameRate/$videoCodingType/$streamType/$streamingNew " +
                "expected=${profile.previewSize}/${profile.fps}/${profile.thermalCoding}/" +
                "$HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE/${profile.streamingNew}"
        lastStageReport =
            "$lastStageReport; $lastFailureReason; USB_SET_VIDEO_PARAM=not_run; " +
                "USB_StartStreamCallback=not_run"
        return F2StartResult(
            ok = false,
            waitingForFrame = false,
            channel = -1,
            reason = lastFailureReason,
            stageReport = lastStageReport,
            profileResolution = resolution,
        )
    }

    private fun cleanupPreviousOfficialF2Login(context: Context? = null): F2StageResult {
        val currentUserId = userId
        val currentChannel = channel
        val selected = selectedDeviceInfo
        val selectedFd = selected?.dwFd ?: -1
        val calibrationGenerationBeforeCleanup: Long
        val calibrationAttemptBeforeCleanup: Long
        synchronized(calibrationPrefetchLock) {
            calibrationGenerationBeforeCleanup = calibrationSessionGeneration
            calibrationAttemptBeforeCleanup = calibrationPrefetchAttemptedGeneration
        }
        cancelCalibrationPrefetchAndAdvanceGeneration()
        synchronized(calibrationNativeCommandLock) {
            if (currentUserId != -1) {
                val thermalOff = setThermalStreamCtrl(currentUserId, enable = false)
                val verify = verifyThermalStreamCtrlDisabled(context = context, currentUserId = currentUserId, initialDisableOk = thermalOff)
                lastStageReport = "$lastStageReport; official_login_reset USB_SetThermalStreamCtrl(false)=attempted ok=$thermalOff userId=$currentUserId; $verify"
            } else {
                lastStageReport = "$lastStageReport; official_login_reset USB_SetThermalStreamCtrl(false)=skipped userId=$currentUserId"
            }
            if (currentUserId != -1 && currentChannel != -1) {
                val suspendedRegistration = javaInterface.suspendStreamCallbackRegistration(currentUserId)
                val stopResult = invokeStopChannel(currentUserId, currentChannel)
                val stopOk = stopResult.ok
                lastStageReport = "$lastStageReport; official_login_reset USB_StopChannel=attempted ok=$stopOk userId=$currentUserId channel=$currentChannel"
                if (!stopOk) {
                    javaInterface.restoreStreamCallbackRegistration(suspendedRegistration)
                    val thermalRestoreOk = setThermalStreamCtrl(currentUserId, enable = true)
                    lastStageReport =
                        "$lastStageReport; official_login_reset USB_SetThermalStreamCtrl(true)=attempted_after_failed_stop ok=$thermalRestoreOk userId=$currentUserId"
                    synchronized(calibrationPrefetchLock) {
                        if (calibrationSessionGeneration == calibrationGenerationBeforeCleanup + 1L) {
                            calibrationSessionGeneration = calibrationGenerationBeforeCleanup
                            calibrationPrefetchAttemptedGeneration = calibrationAttemptBeforeCleanup
                        }
                    }
                    val reason =
                        "official_login_reset_failed stage=USB_StopChannel userId=$currentUserId channel=$currentChannel error=${javaInterface.USB_GetLastError()}${stopResult.failureDetail} thermal_stream_restore_ok=$thermalRestoreOk session_preserved=true"
                    lastFailureReason = reason
                    lastStageReport = "$lastStageReport; $reason"
                    return F2StageResult(
                        ok = false,
                        summary = reason,
                        closeOutcome = F2SessionCloseOutcome.STREAM_PRESERVED,
                    )
                }
                clearOfficialCallbackSlots(currentUserId)
                channel = -1
                callbackKeepAlive = null
                jnaCallbackKeepAlive = null
                startedElapsedMs = 0L
            } else {
                lastStageReport = "$lastStageReport; official_login_reset USB_StopChannel=skipped userId=$currentUserId channel=$currentChannel"
            }
        }

        synchronized(calibrationNativeCommandLock) {
            latestCalibrationResult = null
            if (currentUserId != -1) {
                clearOfficialCallbackSlots(currentUserId)
                val logoutOk = logoutOperation(currentUserId)
                lastStageReport = "$lastStageReport; official_login_reset USB_Logout=attempted ok=$logoutOk userId=$currentUserId"
                if (!logoutOk) {
                    val reason =
                        "official_login_reset_failed stage=USB_Logout userId=$currentUserId channel=${channel} error=${javaInterface.USB_GetLastError()} login_preserved=true stream_stopped=true"
                    lastFailureReason = reason
                    lastStageReport = "$lastStageReport; $reason"
                    return F2StageResult(
                        ok = false,
                        summary = reason,
                        closeOutcome = F2SessionCloseOutcome.STREAM_STOPPED_LOGIN_RETAINED,
                    )
                }
            } else {
                lastStageReport = "$lastStageReport; official_login_reset USB_Logout=skipped userId=$currentUserId"
            }
            lastStageReport = "$lastStageReport; official_login_reset closeConnection=attempted selectedFd=$selectedFd"
            selected?.closeConnection()
            userId = -1
            channel = -1
            selectedDeviceInfo = null
            selectedDeviceName = ""
            selectedProfileResolution = null
            selectedSystemDeviceInfo = null
            callbackKeepAlive = null
            jnaCallbackKeepAlive = null
            startedElapsedMs = 0L
            return F2StageResult(
                ok = true,
                summary = "official_login_reset_complete userId=$currentUserId channel=$currentChannel",
                closeOutcome = F2SessionCloseOutcome.CLOSED,
            )
        }
    }

    private fun invokeStopChannel(currentUserId: Int, currentChannel: Int): F2StopChannelInvocation =
        try {
            F2StopChannelInvocation(
                ok = stopChannelOperation(currentUserId, currentChannel),
                failureDetail = "",
            )
        } catch (error: RuntimeException) {
            F2StopChannelInvocation(
                ok = false,
                failureDetail = " throwable=${error::class.java.name}",
            )
        } catch (error: LinkageError) {
            F2StopChannelInvocation(
                ok = false,
                failureDetail = " throwable=${error::class.java.name}",
            )
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
    ): String = verifyThermalStreamCtrlDisabledBounded(
        initialDisableOk = initialDisableOk,
        maxAttempts = OFFICIAL_STOP_THERMAL_CTRL_MAX_RETRIES,
        getState = { getThermalStreamCtrlState(currentUserId) },
        retryDisable = { setThermalStreamCtrl(currentUserId, enable = false) },
        getDeviceCount = context?.let { nonNullContext ->
            { javaInterface.USB_GetDeviceCount(nonNullContext) }
        },
        contextLabel = context?.packageName,
        sleep = { Thread.sleep(it) },
    )

    private fun acquireThermometryCalibrationFile(
        snapshot: F2CalibrationAcquisitionSnapshot,
        beforeNativeCommand: (() -> Boolean)? = null,
    ): F2CalibrationFileResult {
        val identity = buildCalibrationIdentity(snapshot.deviceInfo, snapshot.systemDeviceInfo)
        val targetDir = sanitizeCacheDirectory(snapshot.cacheDir)
        val targetFile = calibrationCacheFile(targetDir, identity)
        existingCalibrationFileResult(targetDir, identity)?.let { return it }

        beforeCalibrationNativeCommandForTests?.invoke()
        val calibration = USB_THERMOMETRY_CALIBRATION_FILE()
        val ok = synchronized(calibrationNativeCommandLock) {
            if (beforeNativeCommand != null && !beforeNativeCommand()) {
                return calibrationFailureResult(
                    identity = identity,
                    reason = "stale_calibration_prefetch_before_command_2054",
                )
            }
            javaInterface.USB_GetThermometryCalibrationFile(snapshot.userId, calibration)
        }
        if (!ok) {
            val error = javaInterface.USB_GetLastError()
            return calibrationFailureResult(
                identity = identity,
                length = calibration.dwFileLenth,
                reason = "USB_GetThermometryCalibrationFile failed error=$error dwFileLenth=${calibration.dwFileLenth}",
            )
        }

        val bytes = calibration.pCalibrationFile.copyOf(calibration.dwFileLenth)
        val digest = sha256Hex(bytes)
        atomicWrite(targetFile, bytes)
        atomicWrite(calibrationIdentityFile(targetFile), calibrationSidecarBytes(identity, bytes.size, digest))
        return F2CalibrationFileResult(
            ok = true,
            file = targetFile,
            provenance = F2CalibrationFileProvenance(
                sha256 = digest,
                length = bytes.size,
                identityKey = identity.identityKey,
                nativeCommand = USB_GET_THERMOMETRY_CALIBRATION_FILE,
                cacheState = F2CalibrationCacheState.FETCHED.state,
                formatState = F2_CALIBRATION_FORMAT_STATE_UNVERIFIED_2054,
            ),
            reason = "fetched",
        )
    }

    private fun runCalibrationPrefetch(
        snapshot: F2CalibrationAcquisitionSnapshot,
        executor: ExecutorService,
    ) {
        try {
            if (!isCalibrationSnapshotCurrent(snapshot)) return
            val result = acquireThermometryCalibrationFile(snapshot) {
                isCalibrationSnapshotCurrent(snapshot)
            }
            if (result.reason == "stale_calibration_prefetch_before_command_2054") return
            if (!isCalibrationSnapshotCurrent(snapshot)) return
            latestCalibrationResult = result
        } finally {
            synchronized(calibrationPrefetchLock) {
                if (calibrationPrefetchExecutor === executor) {
                    calibrationPrefetchExecutor = null
                    calibrationPrefetchFuture = null
                }
            }
            executor.shutdown()
        }
    }

    private fun isCalibrationSnapshotCurrent(snapshot: F2CalibrationAcquisitionSnapshot): Boolean {
        if (calibrationSessionGeneration != snapshot.generation) return false
        if (userId != snapshot.userId) return false
        val selected = selectedDeviceInfo?.copyCalibrationIdentity() ?: return false
        val systemInfo = selectedSystemDeviceInfo?.copyIdentity()
        return buildCalibrationIdentity(selected, systemInfo).identityKey ==
            buildCalibrationIdentity(snapshot.deviceInfo, snapshot.systemDeviceInfo).identityKey
    }

    private fun cancelCalibrationPrefetchAndAdvanceGeneration() {
        val future: Future<*>?
        val executor: ExecutorService?
        synchronized(calibrationPrefetchLock) {
            calibrationSessionGeneration += 1
            calibrationPrefetchAttemptedGeneration = -1L
            future = calibrationPrefetchFuture
            executor = calibrationPrefetchExecutor
            calibrationPrefetchFuture = null
            calibrationPrefetchExecutor = null
        }
        future?.cancel(true)
        executor?.shutdownNow()
    }

    private fun newCalibrationPrefetchExecutor(): ExecutorService =
        Executors.newSingleThreadExecutor { runnable ->
            Thread(runnable, "f2-calibration-prefetch").apply { isDaemon = true }
        }

    private fun existingCalibrationFileResult(
        cacheDir: File,
        identity: F2CalibrationIdentity,
    ): F2CalibrationFileResult? {
        val targetFile = calibrationCacheFile(cacheDir, identity)
        if (!targetFile.isFile || targetFile.length() <= 0L) return null
        val sidecar = readCalibrationSidecar(calibrationIdentityFile(targetFile)) ?: return null
        if (sidecar.identityKey != identity.identityKey) return null
        val bytes = try {
            targetFile.readBytes()
        } catch (_: IOException) {
            return null
        }
        if (bytes.isEmpty()) return null
        val digest = sha256Hex(bytes)
        if (sidecar.length != bytes.size || sidecar.sha256 != digest) return null
        return F2CalibrationFileResult(
            ok = true,
            file = targetFile,
            provenance = F2CalibrationFileProvenance(
                sha256 = digest,
                length = bytes.size,
                identityKey = identity.identityKey,
                nativeCommand = USB_GET_THERMOMETRY_CALIBRATION_FILE,
                cacheState = F2CalibrationCacheState.HIT.state,
                formatState = F2_CALIBRATION_FORMAT_STATE_UNVERIFIED_2054,
            ),
            reason = "cache_hit",
        )
    }

    private fun calibrationCacheFile(cacheDir: File, identity: F2CalibrationIdentity): File =
        File(cacheDir, "HM-Calibration_${identity.serialFileComponent}.dat")

    private fun calibrationIdentityFile(targetFile: File): File =
        File(targetFile.parentFile, "${targetFile.name}.identity")

    private fun calibrationSidecarBytes(
        identity: F2CalibrationIdentity,
        length: Int,
        sha256: String,
    ): ByteArray {
        val properties = Properties().apply {
            setProperty(CALIBRATION_SIDECAR_VERSION_KEY, CALIBRATION_SIDECAR_VERSION)
            setProperty(CALIBRATION_SIDECAR_IDENTITY_KEY, identity.identityKey)
            setProperty(CALIBRATION_SIDECAR_LENGTH_KEY, length.toString())
            setProperty(CALIBRATION_SIDECAR_SHA256_KEY, sha256)
        }
        val output = ByteArrayOutputStream()
        properties.store(output, "HIKMICRO F2 calibration cache sidecar")
        return output.toByteArray()
    }

    private fun readCalibrationSidecar(sidecarFile: File): F2CalibrationCacheSidecar? {
        val properties = try {
            Properties().apply {
                ByteArrayInputStream(sidecarFile.readBytes()).use { load(it) }
            }
        } catch (_: IllegalArgumentException) {
            return null
        } catch (_: IOException) {
            return null
        }
        if (properties.getProperty(CALIBRATION_SIDECAR_VERSION_KEY) != CALIBRATION_SIDECAR_VERSION) return null
        val identityKey = properties.getProperty(CALIBRATION_SIDECAR_IDENTITY_KEY) ?: return null
        val length = properties.getProperty(CALIBRATION_SIDECAR_LENGTH_KEY)?.toIntOrNull() ?: return null
        val sha256 = properties.getProperty(CALIBRATION_SIDECAR_SHA256_KEY) ?: return null
        if (identityKey.isBlank() || length <= 0 || !SHA256_HEX_PATTERN.matches(sha256)) return null
        return F2CalibrationCacheSidecar(identityKey = identityKey, length = length, sha256 = sha256)
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
        val hardware = trimString(systemInfo?.byHardwareVersion.orEmpty())
        val deviceId = trimString(systemInfo?.byDeviceID.orEmpty())
        val parts = listOf(
            "vid=${selected.dwVID}",
            "pid=${selected.dwPID}",
            "serial=$serial",
            "moduleId=$moduleId",
            "firmware=$firmware",
            "hardwareVersion=$hardware",
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

    private fun clearOfficialCallbackSlots(currentUserId: Int) {
        javaInterface.invalidateStreamCallbackRegistration(currentUserId)
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
    val closeOutcome: F2SessionCloseOutcome = F2SessionCloseOutcome.NOT_APPLICABLE,
)

enum class F2SessionCloseOutcome {
    NOT_APPLICABLE,
    STREAM_PRESERVED,
    STREAM_STOPPED_LOGIN_RETAINED,
    CLOSED,
}

private data class F2StopChannelInvocation(
    val ok: Boolean,
    val failureDetail: String,
)

const val F2_CALIBRATION_FORMAT_STATE_UNVERIFIED_2054: String = "unverified_2054_calibration_file"

private const val CALIBRATION_SIDECAR_VERSION = "2"
private const val CALIBRATION_SIDECAR_VERSION_KEY = "version"
private const val CALIBRATION_SIDECAR_IDENTITY_KEY = "identityKey"
private const val CALIBRATION_SIDECAR_LENGTH_KEY = "length"
private const val CALIBRATION_SIDECAR_SHA256_KEY = "sha256"
private val SHA256_HEX_PATTERN = Regex("[0-9a-f]{64}")

private data class F2CalibrationCacheSidecar(
    val identityKey: String,
    val length: Int,
    val sha256: String,
)

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

data class F2CalibrationIdentitySummary(
    val identityKey: String,
    val serialFileComponent: String,
    val serialNumber: String,
    val moduleId: String,
    val firmwareVersion: String,
    val hardwareVersion: String,
    val deviceId: String,
    val deviceName: String,
    val vid: Int,
    val pid: Int,
)

data class F2SessionToken(
    val generation: Long,
    val userId: Int,
    val identity: F2CalibrationIdentitySummary,
    val profileResolution: HikmicroF2ProfileResolution?,
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
    val generation: Long = -1L,
    val userId: Int,
    val deviceInfo: USB_DEVICE_INFO,
    val systemDeviceInfo: USB_SYSTEM_DEVICE_INFO?,
    val cacheDir: File,
)

internal data class ThermalStreamCtrlState(
    val ok: Boolean,
    val streamEnable: Boolean,
    val byEnable: Int,
    val lastError: Int,
)

internal fun verifyThermalStreamCtrlDisabledBounded(
    initialDisableOk: Boolean,
    maxAttempts: Int,
    getState: () -> ThermalStreamCtrlState,
    retryDisable: () -> Boolean,
    getDeviceCount: (() -> Int)?,
    contextLabel: String?,
    sleep: (Long) -> Unit,
): String {
    require(maxAttempts > 0) { "maxAttempts must be positive" }
    val parts = mutableListOf(
        "verifyThermalStreamCtrlDisabled official_stop_lifecycle start initialDisableOk=$initialDisableOk maxAttempts=$maxAttempts"
    )
    var unsuccessfulPolls = 0
    while (unsuccessfulPolls < maxAttempts) {
        val state = getState()
        parts += "USB_GetThermalStreamCtrl=attempted ok=${state.ok} streamEnable=${state.streamEnable} byEnable=${state.byEnable} error=${state.lastError} attempt=${unsuccessfulPolls + 1}"
        if (state.ok && !state.streamEnable) {
            parts += "verifyThermalStreamCtrlDisabled=done streamEnable=false attempts=${unsuccessfulPolls + 1} unsuccessfulPolls=$unsuccessfulPolls"
            return parts.joinToString("; ")
        }

        unsuccessfulPolls += 1
        val deviceCount = getDeviceCount?.invoke()
        parts += if (deviceCount == null) {
            "USB_GetDeviceCount(context)=skipped_no_context unsuccessfulPolls=$unsuccessfulPolls"
        } else {
            "USB_GetDeviceCount(context)=attempted context=$contextLabel count=$deviceCount unsuccessfulPolls=$unsuccessfulPolls"
        }
        if (deviceCount != null && deviceCount <= 0) {
            parts += "verifyThermalStreamCtrlDisabled=gave_up reason=device_disconnected unsuccessfulPolls=$unsuccessfulPolls deviceCount=$deviceCount"
            return parts.joinToString("; ")
        }
        if (unsuccessfulPolls >= maxAttempts) {
            parts += "verifyThermalStreamCtrlDisabled=gave_up reason=max_attempts attempts=$maxAttempts unsuccessfulPolls=$unsuccessfulPolls"
            return parts.joinToString("; ")
        }

        val retryOk = retryDisable()
        parts += "USB_SetThermalStreamCtrl(false)#retry=attempted ok=$retryOk unsuccessfulPolls=$unsuccessfulPolls"
        try {
            sleep(OFFICIAL_STOP_THERMAL_CTRL_POLL_SLEEP_MS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            parts += "verifyThermalStreamCtrlDisabled=gave_up reason=interrupted unsuccessfulPolls=$unsuccessfulPolls"
            return parts.joinToString("; ")
        }
    }
    error("bounded thermal stream control loop exhausted without returning")
}

data class F2StreamFrame(
    val callbackUserId: Int,
    val frameCounter: Long,
    val width: Int,
    val height: Int,
    val frameType: Int,
    val dataType: Int,
    val streamType: Int,
    val bytes: ByteArray,
    val lifecycleGeneration: Long = -1L,
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


data class F2MeasurementSettingsResult(
    val ok: Boolean,
    val settings: F2MeasurementSettings?,
    val identityKey: String?,
    val reason: String,
)

data class F2MeasurementSettings(
    val agcMode: Int,
    val maxEnvironmentTemp: Float,
    val minEnvironmentTemp: Float,
    val imageAdjustments: java.util.HashMap<String, Any>,
) {
    companion object {
        fun fromOfficialV20(
            brightness: Int,
            contrast: Int,
            enhancement: USB_IMAGE_ENHANCEMENT_EX,
        ): F2MeasurementSettings {
            val nested = enhancement.struImageEnhancement
            val wideMode = nested.byWideTemperatureMode.toUnsignedInt()
            val wideWork = nested.byWideTemperatureWork.toUnsignedInt()
            val agcMode = if (wideMode != 1) {
                1
            } else {
                when (wideWork) {
                    1 -> 2
                    2 -> 4
                    3 -> 3
                    else -> 2
                }
            }
            return F2MeasurementSettings(
                agcMode = agcMode,
                maxEnvironmentTemp = nested.dwWideTemperatureUpThreshold / 10f - 100f,
                minEnvironmentTemp = nested.dwWideTemperatureDownThreshold / 10f - 100f,
                imageAdjustments = java.util.HashMap<String, Any>().apply {
                    put("IspMode", nested.byIspAgcMode.toUnsignedInt())
                    put("Brightness", brightness)
                    put("Contrast", contrast)
                    put("Sharpness", nested.dwLSEDetailLevel)
                },
            )
        }
    }
}

private fun Byte.toUnsignedInt(): Int = toInt() and 0xff
