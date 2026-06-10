package kr.auto.titration.mobile.thermal

import android.graphics.Bitmap
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbManager
import android.os.SystemClock
import android.util.Base64
import com.sun.jna.Callback
import com.sun.jna.Library
import com.sun.jna.Native
import com.sun.jna.Pointer
import com.sun.jna.Structure
import java.io.ByteArrayOutputStream
import kotlin.math.max
import kotlin.math.min

private const val F1_STREAM_RETRY_INTERVAL_MS = 2_000L
private const val F1_FRAME_WAIT_TIMEOUT_MS = 5_000L
private const val F1_MAX_CAPTURE_BYTES = 512 * 1024
private const val F1_PREVIEW_DEFAULT_WIDTH = 120
private const val F1_PREVIEW_DEFAULT_HEIGHT = 160

/**
 * Best-effort port of the official-app F1 Mini2 path.
 *
 * Official APK evidence:
 * UsbManager.openDevice -> getFileDescriptor -> THERMAL_MSG_FOR_USB(type=6,len=92)
 * -> thermal_function_alarm_init -> thermal_function_stream_realtime_init
 * -> thermal_init_thermal_module -> USB_SetAlarmEnable(type=4)
 * -> USB_SetPreviewEnable(type=5).
 *
 * This class only emits raw/preview evidence. Celsius remains blocked until live
 * callback payloads and fixture comparison are validated on the target device.
 */
object HikmicroF1Mini2Stream {
    @Volatile
    private var session: F1StreamSession? = null
    @Volatile
    private var latestFrameSnapshot: F1StreamFrameSnapshot? = null
    @Volatile
    private var lastAttemptElapsedMs: Long = 0L
    @Volatile
    private var lastFailureReason: String = "not_started"
    @Volatile
    private var lastStreamStageReport: String = "not_started"

    fun ensureStreaming(
        usbManager: UsbManager,
        device: UsbDevice,
        nativeLibraryDir: String,
        nativeReport: NativeLibraryLoadReport,
        cacheDirPath: String,
    ): Mini2RawStreamStatus {
        val route = HikmicroMini2ModuleType.routeReason(device.vendorId, device.productId)
        val now = SystemClock.elapsedRealtime()

        latestFrameSnapshot?.let { snapshot ->
            if (session?.deviceName == device.deviceName) {
                if (now - snapshot.capturedElapsedMs <= F1_FRAME_WAIT_TIMEOUT_MS) {
                    return snapshot.toStatus(
                        reason = "Mini2 F1 _thermal_module callback observed; route=$route; stages=$lastStreamStageReport; Celsius still blocked until fixture validation",
                        route = route,
                    )
                }
                lastFailureReason = "restart stalled F1 stream after stale frame ${now - snapshot.capturedElapsedMs}ms old"
                lastStreamStageReport = "$lastStreamStageReport; restart stale_f1_frame"
                latestFrameSnapshot = null
                stopCurrentSession()
            }
        }

        if (!nativeReport.coreF1Loaded) {
            return Mini2RawStreamStatus.blockedNativeUsbLibrary(
                nativeReport.coreMissingReasonFor(HikmicroMini2ModuleType.F1)
                    .ifBlank { "lib_thermal_module.so is not loaded" },
                discovery = "hikmicro_f1_stream_blocked_native_library",
            )
        }

        val existing = session
        if (existing?.deviceName == device.deviceName) {
            if (now - existing.startedElapsedMs >= F1_FRAME_WAIT_TIMEOUT_MS) {
                lastFailureReason = "restart stalled F1 _thermal_module attempt after ${now - existing.startedElapsedMs}ms without realtime callback"
                lastStreamStageReport = "$lastStreamStageReport; restart stalled_f1_stream_attempt"
                stopCurrentSession()
            } else {
                return Mini2RawStreamStatus.streamAttemptStarted(
                    reason = "F1 _thermal_module preview enabled but no frame callback has arrived yet; route=$route; stages=$lastStreamStageReport; lastFailure=$lastFailureReason",
                    discovery = "hikmicro_f1_thermal_module_waiting_for_frame",
                    selectedBackend = HikmicroMini2ModuleType.F1.backendName,
                    stageReport = lastStreamStageReport,
                    deviceRoute = route,
                    fd = existing.connection.fileDescriptor,
                )
            }
        }

        if (now - lastAttemptElapsedMs < F1_STREAM_RETRY_INTERVAL_MS) {
            return Mini2RawStreamStatus.streamAttemptStarted(
                reason = "Retry throttled after previous F1 _thermal_module stream attempt; route=$route; stages=$lastStreamStageReport; lastFailure=$lastFailureReason",
                discovery = "hikmicro_f1_thermal_module_retry_throttled",
                selectedBackend = HikmicroMini2ModuleType.F1.backendName,
                stageReport = lastStreamStageReport,
                deviceRoute = route,
            )
        }
        lastAttemptElapsedMs = now

        return try {
            stopCurrentSession()
            if (nativeLibraryDir.isNotBlank()) {
                System.setProperty("jna.library.path", nativeLibraryDir)
            }
            val sdk = Native.load("_thermal_module", F1ThermalModuleByJNA::class.java)
            val connection = usbManager.openDevice(device)
                ?: return Mini2RawStreamStatus.blockedNativeStream(
                    "F1 UsbManager.openDevice returned null; Android USB permission or host open failed; route=$route",
                    discovery = "hikmicro_f1_open_device_null",
                ).also { lastFailureReason = it.reason }

            val address = UsbFsAddress.parse(device.deviceName)
            val ispStage = setIspAddress(sdk, cacheDirPath)
            val openStage = openDevice(
                sdk = sdk,
                usbfs = address.usbfs,
                fd = connection.fileDescriptor,
                devAddr = address.devAddr,
                busNum = address.busNum,
                vid = device.vendorId,
                pid = device.productId,
                reconnect = 0,
            )
            if (!openStage.ok) {
                connection.close()
                lastFailureReason = "F1 openDevice failed; route=$route; ${address.summary}; ${ispStage.summary}; ${openStage.summary}"
                lastStreamStageReport = lastFailureReason
                return Mini2RawStreamStatus.blockedNativeStream(
                    lastFailureReason,
                    discovery = "hikmicro_f1_open_device_failed",
                )
            }

            val alarmCallback = F1AlarmCallback { alarmType, pointer, len ->
                lastStreamStageReport = "$lastStreamStageReport; alarm type=$alarmType len=$len ptr=${pointer != null && pointer != Pointer.NULL}"
                1
            }
            val streamCallback = F1StreamCallback { frameInfo, len ->
                captureFrame(frameInfo, len)
                1
            }

            val alarmInit = sdk.thermal_function_alarm_init(alarmCallback)
            val streamInit = sdk.thermal_function_stream_realtime_init(streamCallback)
            val thermalInit = sdk.thermal_init_thermal_module()
            val alarmEnable = setRealtimeEnable(sdk, msgType = 4, stageName = "USB_SetAlarmEnable", enable = true)
            val previewEnable = setRealtimeEnable(sdk, msgType = 5, stageName = "USB_SetPreviewEnable", enable = true)

            lastStreamStageReport = buildString {
                append("route=").append(route)
                append("; ").append(address.summary)
                append("; fd=").append(connection.fileDescriptor)
                append("; ").append(ispStage.summary)
                append("; ").append(openStage.summary)
                append("; alarmInit=").append(alarmInit)
                append("; streamInit=").append(streamInit)
                append("; thermalInit=").append(thermalInit)
                append("; ").append(alarmEnable.summary)
                append("; ").append(previewEnable.summary)
            }

            if (!previewEnable.ok) {
                connection.close()
                lastFailureReason = "F1 preview enable failed; $lastStreamStageReport"
                return Mini2RawStreamStatus.blockedNativeStream(
                    lastFailureReason,
                    discovery = "hikmicro_f1_preview_enable_failed",
                )
            }

            session = F1StreamSession(
                deviceName = device.deviceName,
                connection = connection,
                alarmCallback = alarmCallback,
                streamCallback = streamCallback,
                startedElapsedMs = now,
            )
            lastFailureReason = "none"
            Mini2RawStreamStatus.streamAttemptStarted(
                reason = "F1 _thermal_module open/init/preview commands sent; waiting for first Mini2 realtime callback; stages=$lastStreamStageReport",
                discovery = "hikmicro_f1_thermal_module_callback_started",
                selectedBackend = HikmicroMini2ModuleType.F1.backendName,
                stageReport = lastStreamStageReport,
                deviceRoute = route,
                fd = connection.fileDescriptor,
            )
        } catch (error: Throwable) {
            stopCurrentSession()
            lastFailureReason = "${error.javaClass.simpleName}: ${error.message ?: "no message"}"
            lastStreamStageReport = "f1_exception=$lastFailureReason route=$route"
            Mini2RawStreamStatus.blockedNativeStream(
                lastFailureReason,
                discovery = "hikmicro_f1_thermal_module_exception",
            )
        }
    }

    private fun setIspAddress(sdk: F1ThermalModuleByJNA, cacheDirPath: String): F1StageResult {
        val ispPath = if (cacheDirPath.endsWith("/")) cacheDirPath else "$cacheDirPath/"
        val payload = THERMAL_MSG_FOR_ISP_ADDR().apply {
            val bytes = ispPath.toByteArray(Charsets.UTF_8)
            System.arraycopy(bytes, 0, ispAlgAddr, 0, min(bytes.size, ispAlgAddr.size))
            write()
        }
        return sendConfig(
            sdk = sdk,
            msgType = 7,
            len = 128,
            payload = payload,
            stageName = "USB_SetISPAddress",
        )
    }

    private fun openDevice(
        sdk: F1ThermalModuleByJNA,
        usbfs: String,
        fd: Int,
        devAddr: Int,
        busNum: Int,
        vid: Int,
        pid: Int,
        reconnect: Int,
    ): F1StageResult {
        val payload = THERMAL_MSG_FOR_USB().apply {
            val bytes = usbfs.toByteArray(Charsets.UTF_8)
            System.arraycopy(bytes, 0, byUsbfs, 0, min(bytes.size, byUsbfs.size))
            this.fd = fd
            this.pid = pid
            this.vid = vid
            this.busnum = busNum
            this.devaddr = devAddr
            this.usbfsLen = min(bytes.size + 1, byUsbfs.size)
            this.bReconnect = reconnect
            write()
        }
        return sendConfig(
            sdk = sdk,
            msgType = 6,
            len = 92,
            payload = payload,
            stageName = "USB_OpenDevice",
        )
    }

    private fun setRealtimeEnable(
        sdk: F1ThermalModuleByJNA,
        msgType: Int,
        stageName: String,
        enable: Boolean,
    ): F1StageResult {
        val payload = THERMAL_MSG_FOR_FUNC_STREAM_REALTIME_ENABLE().apply {
            this.enable = if (enable) 1 else 0
            write()
        }
        return sendConfig(
            sdk = sdk,
            msgType = msgType,
            len = 4,
            payload = payload,
            stageName = stageName,
        )
    }

    private fun sendConfig(
        sdk: F1ThermalModuleByJNA,
        msgType: Int,
        len: Int,
        payload: Structure,
        stageName: String,
    ): F1StageResult {
        return try {
            payload.write()
            val config = THERMAL_MSG_Config().apply {
                type = msgType
                devInfo = payload.pointer
                this.len = len
                write()
            }
            val result = sdk.thermal_function_set_msg(config.pointer)
            F1StageResult(
                ok = result == 0,
                summary = "$stageName result=$result type=$msgType len=$len",
            )
        } catch (error: Throwable) {
            F1StageResult(
                ok = false,
                summary = "$stageName exception ${error.javaClass.simpleName}:${error.message ?: "no message"} type=$msgType len=$len",
            )
        }
    }

    private fun captureFrame(frameInfoPointer: Pointer?, callbackLen: Int) {
        if (frameInfoPointer == null || frameInfoPointer == Pointer.NULL) return
        try {
            val thermalInfo = THERMAL_DATA_INFO_MINI(frameInfoPointer).apply {
                read()
                yuvInfo.read()
            }
            val yuv = thermalInfo.yuvInfo
            val size = yuv.nYUVLen.coerceIn(0, F1_MAX_CAPTURE_BYTES)
            val buffer = yuv.pYUV
            if (size <= 0 || buffer == null || buffer == Pointer.NULL) {
                lastFailureReason = "f1_callback_without_yuv len=$callbackLen yuvLen=${yuv.nYUVLen}"
                return
            }
            val bytes = buffer.getByteArray(0, size)
            val width = yuv.nWidth.takeIf { it > 0 } ?: F1_PREVIEW_DEFAULT_WIDTH
            val height = yuv.nHeight.takeIf { it > 0 } ?: F1_PREVIEW_DEFAULT_HEIGHT
            latestFrameSnapshot = F1StreamFrameSnapshot(
                frameCounter = max(1L, latestFrameSnapshot?.frameCounter?.plus(1) ?: 1L),
                width = width,
                height = height,
                yuvType = yuv.nYUVType,
                bufferSize = size,
                previewDataUrl = buildPreviewDataUrl(bytes, width, height),
                capturedElapsedMs = SystemClock.elapsedRealtime(),
                callbackLen = callbackLen,
                fd = session?.connection?.fileDescriptor ?: -1,
            )
        } catch (error: Throwable) {
            lastFailureReason = "f1_callback_capture_failed: ${error.javaClass.simpleName}:${error.message ?: "no message"}"
        }
    }

    private fun stopCurrentSession() {
        val current = session ?: return
        session = null
        runCatching { current.connection.close() }
    }

    private fun buildPreviewDataUrl(bytes: ByteArray, width: Int, height: Int): String {
        if (bytes.size >= 4 && bytes[0] == 0xff.toByte() && bytes[1] == 0xd8.toByte()) {
            return "data:image/jpeg;base64,${Base64.encodeToString(bytes, Base64.NO_WRAP)}"
        }
        val safeWidth = width.takeIf { it > 0 } ?: F1_PREVIEW_DEFAULT_WIDTH
        val safeHeight = height.takeIf { it > 0 } ?: F1_PREVIEW_DEFAULT_HEIGHT
        val pixelCount = safeWidth * safeHeight
        if (pixelCount <= 0 || bytes.isEmpty()) return ""
        val pixels = IntArray(pixelCount)
        val stride = max(1, bytes.size / pixelCount)
        for (index in 0 until pixelCount) {
            val byteIndex = min(bytes.lastIndex, index * stride)
            val luminance = bytes[byteIndex].toInt() and 0xff
            pixels[index] = 0xff000000.toInt() or (luminance shl 16) or (luminance shl 8) or luminance
        }
        val bitmap = Bitmap.createBitmap(pixels, safeWidth, safeHeight, Bitmap.Config.ARGB_8888)
        return ByteArrayOutputStream().use { output ->
            bitmap.compress(Bitmap.CompressFormat.JPEG, 70, output)
            bitmap.recycle()
            "data:image/jpeg;base64,${Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP)}"
        }
    }

    private data class F1StreamSession(
        val deviceName: String,
        val connection: UsbDeviceConnection,
        @Suppress("unused") val alarmCallback: F1AlarmCallback,
        @Suppress("unused") val streamCallback: F1StreamCallback,
        val startedElapsedMs: Long,
    )

    private data class F1StageResult(
        val ok: Boolean,
        val summary: String,
    )

    private data class F1StreamFrameSnapshot(
        val frameCounter: Long,
        val width: Int,
        val height: Int,
        val yuvType: Int,
        val bufferSize: Int,
        val previewDataUrl: String,
        val capturedElapsedMs: Long,
        val callbackLen: Int,
        val fd: Int,
    ) {
        fun toStatus(reason: String, route: String): Mini2RawStreamStatus = Mini2RawStreamStatus.streamAttemptStarted(
            reason = "$reason; yuvType=$yuvType bytes=$bufferSize callbackLen=$callbackLen elapsedMs=$capturedElapsedMs",
            frameCounter = frameCounter,
            frameWidth = width,
            frameHeight = height,
            frameFormat = "hikmicro_f1_thermal_data_info_yuv_raw_unverified",
            thermalPreviewDataUrl = previewDataUrl,
            discovery = "hikmicro_f1_thermal_module_yuv_observed",
            selectedBackend = HikmicroMini2ModuleType.F1.backendName,
            stageReport = lastStreamStageReport,
            deviceRoute = route,
            fd = fd,
        )
    }

    private data class UsbFsAddress(
        val usbfs: String,
        val busNum: Int,
        val devAddr: Int,
    ) {
        val summary: String
            get() = "usbfs=$usbfs busnum=$busNum devaddr=$devAddr"

        companion object {
            fun parse(deviceName: String): UsbFsAddress {
                val parts = deviceName.split('/').filter { it.isNotBlank() }
                val bus = parts.getOrNull(parts.lastIndex - 1)?.toIntOrNull() ?: 0
                val dev = parts.lastOrNull()?.toIntOrNull() ?: 0
                val usbfs = if (parts.size >= 3) {
                    "/" + parts.dropLast(2).joinToString("/")
                } else {
                    "/dev/bus/usb"
                }
                return UsbFsAddress(
                    usbfs = usbfs.ifBlank { "/dev/bus/usb" },
                    busNum = bus,
                    devAddr = dev,
                )
            }
        }
    }

    private interface F1ThermalModuleByJNA : Library {
        fun thermal_function_set_msg(config: Pointer): Int
        fun thermal_function_alarm_init(callback: Callback): Int
        fun thermal_function_stream_realtime_init(callback: Callback): Int
        fun thermal_init_thermal_module(): Int
    }

    fun interface F1StreamCallback : Callback {
        fun invoke(frameInfo: Pointer?, len: Int): Int
    }

    fun interface F1AlarmCallback : Callback {
        fun invoke(alarmType: Int, alarmInfo: Pointer?, len: Int): Int
    }

    @Structure.FieldOrder("type", "devInfo", "len")
    class THERMAL_MSG_Config : Structure() {
        @JvmField var type: Int = 0
        @JvmField var devInfo: Pointer? = Pointer.NULL
        @JvmField var len: Int = 0
    }

    @Structure.FieldOrder("byUsbfs", "fd", "pid", "vid", "busnum", "devaddr", "usbfsLen", "bReconnect")
    class THERMAL_MSG_FOR_USB : Structure() {
        @JvmField var byUsbfs: ByteArray = ByteArray(64)
        @JvmField var fd: Int = 0
        @JvmField var pid: Int = 0
        @JvmField var vid: Int = 0
        @JvmField var busnum: Int = 0
        @JvmField var devaddr: Int = 0
        @JvmField var usbfsLen: Int = 0
        @JvmField var bReconnect: Int = 0
    }

    @Structure.FieldOrder("ispAlgAddr")
    class THERMAL_MSG_FOR_ISP_ADDR : Structure() {
        @JvmField var ispAlgAddr: ByteArray = ByteArray(128)
    }

    @Structure.FieldOrder("enable")
    class THERMAL_MSG_FOR_FUNC_STREAM_REALTIME_ENABLE : Structure() {
        @JvmField var enable: Int = 0
    }

    @Structure.FieldOrder("dwYear", "dwMon", "dwDay", "dwHour", "dwMin", "dwSec", "dwMs", "res")
    class SYSTEM_TIME : Structure() {
        @JvmField var dwYear: Short = 0
        @JvmField var dwMon: Short = 0
        @JvmField var dwDay: Short = 0
        @JvmField var dwHour: Short = 0
        @JvmField var dwMin: Short = 0
        @JvmField var dwSec: Short = 0
        @JvmField var dwMs: Short = 0
        @JvmField var res: Short = 0
    }

    @Structure.FieldOrder("pYUV", "nYUVLen", "nYUVType", "nWidth", "nHeight", "nFrameTime", "systemTime")
    class YUV_INFO : Structure() {
        @JvmField var pYUV: Pointer? = Pointer.NULL
        @JvmField var nYUVLen: Int = 0
        @JvmField var nYUVType: Int = 0
        @JvmField var nWidth: Int = 0
        @JvmField var nHeight: Int = 0
        @JvmField var nFrameTime: Int = 0
        @JvmField var systemTime: SYSTEM_TIME = SYSTEM_TIME()
    }

    @Structure.FieldOrder("yuvInfo")
    class THERMAL_DATA_INFO_MINI(pointer: Pointer) : Structure(pointer) {
        @JvmField var yuvInfo: YUV_INFO = YUV_INFO()
    }
}
