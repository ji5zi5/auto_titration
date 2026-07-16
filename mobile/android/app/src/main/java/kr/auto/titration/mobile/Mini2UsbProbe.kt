package kr.auto.titration.mobile

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.SystemClock
import androidx.core.content.ContextCompat
import kr.auto.titration.mobile.thermal.HikmicroNativeBackend
import kr.auto.titration.mobile.thermal.HikmicroF1Mini2Stream
import kr.auto.titration.mobile.thermal.HikmicroJnaMini2Stream
import kr.auto.titration.mobile.thermal.HikmicroMini2ModuleType
import kr.auto.titration.mobile.thermal.HikmicroTemperatureConversionAttempt
import kr.auto.titration.mobile.thermal.Mini2RawStreamStatus
import kr.auto.titration.mobile.thermal.Mini2OfficialRuntimeMode
import kr.auto.titration.mobile.thermal.NativeLibraryLoadReport
import kr.auto.titration.mobile.thermal.ThermalRawFrameSummary
import kr.auto.titration.mobile.thermal.ThermalStatus
import org.json.JSONArray
import org.json.JSONObject

private const val MINI2_VENDOR_ID = 0x2bdf
private const val MINI2_PRODUCT_ID = 0x0102
private const val USB_PERMISSION_ACTION = "kr.auto.titration.mobile.USB_PERMISSION"

/**
 * USB host probe for HIKMICRO Mini2 in phone-standalone mode.
 *
 * This class reports evidence status only. It may load the private Android
 * HIKMICRO native libraries and request USB permission, but it must not invent
 * calibrated Celsius from raw bytes. Until the Android native stream/converter is
 * live-validated on the target phone, Mini2 frames remain raw_unverified or
 * blocked and Celsius fields remain blank.
 */
class Mini2UsbProbe(private val context: Context) {
    private val usbManager: UsbManager = context.getSystemService(Context.USB_SERVICE) as UsbManager
    private val nativeLibraryDir: String = context.applicationInfo.nativeLibraryDir.orEmpty()
    private val permissionRequests: MutableSet<String> = mutableSetOf()
    private val knownMini2ProductIds = setOf(
        HikmicroMini2ModuleType.HIKMICRO_F1_PRODUCT_ID,
        HikmicroMini2ModuleType.HIKMICRO_F2_PRODUCT_ID_0102,
        HikmicroMini2ModuleType.HIKMICRO_F2_PRODUCT_ID_0101,
    )
    private val stateLock = Any()

    @Volatile
    private var receiverRegistered = false
    private var permissionRequestCount = 0
    private var lastPermissionRequestElapsedMs = 0L
    private var lastPermissionDecisionElapsedMs = 0L
    private var lastPermissionDeviceName = ""
    private var lastPermissionGranted: Boolean? = null
    private var pendingPermissionDeviceName = ""
    private var lastUsbEvent = "none"
    private var lastUsbEventElapsedMs = 0L
    private var lastUsbEventDeviceName = ""

    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(receiverContext: Context, intent: Intent) {
            val action = intent.action.orEmpty()
            val device = intent.usbDeviceExtra()
            val elapsedMs = SystemClock.elapsedRealtime()
            synchronized(stateLock) {
                lastUsbEvent = action
                lastUsbEventElapsedMs = elapsedMs
                lastUsbEventDeviceName = device?.deviceName.orEmpty()
                when (action) {
                    USB_PERMISSION_ACTION -> {
                        lastPermissionGranted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                        lastPermissionDecisionElapsedMs = elapsedMs
                        pendingPermissionDeviceName = ""
                    }
                    UsbManager.ACTION_USB_DEVICE_ATTACHED -> {
                        if (device != null && HikmicroMini2ModuleType.isHikmicroCandidate(device)) {
                            permissionRequests.remove(device.deviceName)
                            lastPermissionGranted = null
                        }
                    }
                    UsbManager.ACTION_USB_DEVICE_DETACHED -> {
                        val detachedDeviceName = device?.deviceName ?: pendingPermissionDeviceName
                        val pendingDeviceDetached = device?.deviceName == pendingPermissionDeviceName
                        if ((device != null && HikmicroMini2ModuleType.isHikmicroCandidate(device)) || pendingDeviceDetached) {
                            permissionRequests.remove(detachedDeviceName)
                            pendingPermissionDeviceName = ""
                            lastPermissionGranted = false
                        }
                    }
                }
            }
        }
    }

    fun startMonitoring() {
        if (receiverRegistered) return
        val filter = IntentFilter().apply {
            addAction(USB_PERMISSION_ACTION)
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        ContextCompat.registerReceiver(
            context,
            usbReceiver,
            filter,
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        receiverRegistered = true
    }

    fun stopMonitoring() {
        if (!receiverRegistered) return
        try {
            context.unregisterReceiver(usbReceiver)
        } catch (_: IllegalArgumentException) {
            // Already unregistered by Android lifecycle; status polling can continue safely.
        } finally {
            receiverRegistered = false
        }
    }

    fun probe(
        requestPermissionIfMissing: Boolean = true,
        forcePermissionRequest: Boolean = false,
        forceNativeLoad: Boolean = false,
        attemptRawStream: Boolean = false,
        runtimeMode: Mini2OfficialRuntimeMode = Mini2OfficialRuntimeMode.OFFICIAL_PRIMARY,
    ): JSONObject {
        val mini2 = findMini2Candidate()
        val hasPermission = mini2?.let { usbManager.hasPermission(it) } == true
        val moduleType = mini2?.let { HikmicroMini2ModuleType.classify(it) } ?: HikmicroMini2ModuleType.UNSUPPORTED
        val routeJson = HikmicroMini2ModuleType.routeJson(mini2)
        val explicitNativeStreamAttempt = attemptRawStream
        val status = safeProbeStatus(
            requestPermissionIfMissing = requestPermissionIfMissing,
            forcePermissionRequest = forcePermissionRequest,
            forceNativeLoad = forceNativeLoad,
            allowNativeLoad = explicitNativeStreamAttempt,
        )
        val shouldAttemptNativeLoad = explicitNativeStreamAttempt && mini2 != null && hasPermission && moduleType.isSupported
        val nativeReport = try {
            if (shouldAttemptNativeLoad) {
                HikmicroNativeBackend.ensureLibrariesLoaded(
                    nativeLibraryDir = nativeLibraryDir,
                    forceRetry = forceNativeLoad,
                    moduleType = moduleType,
                )
            } else {
                HikmicroNativeBackend.notAttemptedReport(
                    note = nativeNotAttemptedReason(
                        mini2 = mini2,
                        hasPermission = hasPermission,
                        moduleType = moduleType,
                    ),
                )
            }
        } catch (error: Throwable) {
            HikmicroNativeBackend.notAttemptedReport(
                note = "native_load_exception ${error.javaClass.simpleName}: ${error.message ?: "no message"}",
            )
        }
        val conversion = HikmicroTemperatureConversionAttempt.describe(
            loadReport = nativeReport,
            usbPermissionGranted = hasPermission,
        )
        val rawStreamStatus = if (attemptRawStream) {
            safeRawStreamStatus(mini2, hasPermission, nativeReport, runtimeMode)
        } else {
            safePassiveRawStreamStatus(mini2, hasPermission, nativeReport)
        }
        val permissionSnapshot = permissionSnapshot(mini2, hasPermission)
        val currentUsbPresence = currentUsbPresenceJson(
            mini2 = mini2,
            hasPermission = hasPermission,
            status = status,
            permissionSnapshot = permissionSnapshot,
            routeJson = routeJson,
        )
        val rawStreamJson = enrichRawStreamJson(rawStreamStatus.toJson(), conversion)
        val result = JSONObject()
            .put("thermal_calibrated", status.calibrated)
            .put("mini2_vendor_id", String.format("0x%04x", MINI2_VENDOR_ID))
            .put("mini2_expected_product_id", "0x0140(F1),0x0102(F2),0x0101(F2)")
            .put("mini2_status", status.state.name.lowercase())
            .put("mini2_reason", status.reason)
            .put("thermal_conversion_model", status.conversionModel)
            .put("thermal_backend", status.backendName)
            .put("mini2_official_module_type", moduleType.routeName)
            .put("mini2_selected_backend", moduleType.backendName)
            .put("mini2_route", routeJson)
            .put("mini2_route_reason", routeJson.optString("reason"))
            .put("raw_frame_status", rawStreamStatus.rawStreamStatus)
            .put("raw_stream_status", rawStreamStatus.rawStreamStatus)
            .put("temperature_conversion_status", conversion.temperatureStatus)
            .put("hikmicro_native", nativeReport.toJson())
            .put(
                "mini2_native_permission_gate",
                nativePermissionGateJson(
                    mini2 = mini2,
                    hasPermission = hasPermission,
                    moduleType = moduleType,
                    nativeLoadAttempted = shouldAttemptNativeLoad,
                ),
            )
            .put("temperature_attempt", conversion.toJson())
            .put("converter_validation_state", conversion.validationEvidence.toJson())
            .put("celsius_allowed", hasValidDeviceGlobalSummary(rawStreamJson))
            .put("temperature_avg_c", if (hasValidDeviceGlobalSummary(rawStreamJson)) jsonFiniteDoubleOrNull(rawStreamJson, "temperature_avg_c") ?: JSONObject.NULL else JSONObject.NULL)
            .put("temperature_min_c", if (hasValidDeviceGlobalSummary(rawStreamJson)) jsonFiniteDoubleOrNull(rawStreamJson, "temperature_min_c") ?: JSONObject.NULL else JSONObject.NULL)
            .put("temperature_max_c", if (hasValidDeviceGlobalSummary(rawStreamJson)) jsonFiniteDoubleOrNull(rawStreamJson, "temperature_max_c") ?: JSONObject.NULL else JSONObject.NULL)
            .put("temperature_provenance", if (hasValidDeviceGlobalSummary(rawStreamJson)) jsonStringOrNull(rawStreamJson, "temperature_provenance") else JSONObject.NULL)
            .put("temperature_scope", if (hasValidDeviceGlobalSummary(rawStreamJson)) jsonStringOrNull(rawStreamJson, "temperature_scope") else JSONObject.NULL)
            .put("temperature_requested_display_unit", if (hasValidDeviceGlobalSummary(rawStreamJson)) jsonStringOrNull(rawStreamJson, "temperature_requested_display_unit") else JSONObject.NULL)
            .put("temperature_requested_display_unit_code", if (hasValidDeviceGlobalSummary(rawStreamJson)) jsonIntOrNull(rawStreamJson, "temperature_requested_display_unit_code") else JSONObject.NULL)
            .put("temperature_summary", if (hasValidDeviceGlobalSummary(rawStreamJson)) rawStreamJson.optJSONObject("temperature_summary") ?: JSONObject.NULL else JSONObject.NULL)
            .put("full_matrix_celsius_allowed", false)
            .put("full_matrix_temperature_status", rawStreamJson.optString("full_matrix_temperature_status", "unproved_not_emitted"))
            .put("raw_stream", rawStreamJson)
            .put("passive_raw_stream", rawStreamJson)
            .put("current_usb_presence", currentUsbPresence)
            .put("mini2_runtime_mode", runtimeMode.name)
            .put("android_native_library_dir", nativeLibraryDir)
            .put("mini2_devices", devicesJson())
            .put("mini2_permission_state", permissionSnapshot.optString("mini2_permission_state"))
            .put("permission_request_count", permissionSnapshot.optInt("permission_request_count"))
            .put("permission_pending", permissionSnapshot.optBoolean("permission_pending"))
            .put("last_permission_request_elapsed_ms", permissionSnapshot.optLong("last_permission_request_elapsed_ms"))
            .put("last_permission_decision_elapsed_ms", permissionSnapshot.optLong("last_permission_decision_elapsed_ms"))
            .put("last_usb_event", permissionSnapshot.optString("last_usb_event"))
            .put("last_usb_event_elapsed_ms", permissionSnapshot.optLong("last_usb_event_elapsed_ms"))
            .put("usb_receiver_registered", permissionSnapshot.optBoolean("usb_receiver_registered"))

        if (attemptRawStream) {
            result.put("last_stream_attempt", rawStreamJson)
        } else {
            result.put("last_stream_attempt", JSONObject.NULL)
        }

        if (mini2 != null) {
            result
                .put("mini2_device_name", mini2.deviceName)
                .put("mini2_product_id_detected", String.format("0x%04x", mini2.productId))
                .put("mini2_vendor_id_detected", String.format("0x%04x", mini2.vendorId))
                .put("mini2_known_product", moduleType.isSupported)
                .put("mini2_interface_count", mini2.interfaceCount)
                .put("mini2_usb_permission", hasPermission)
        }
        return result
    }

    fun safeProbeStatus(
        requestPermissionIfMissing: Boolean = true,
        forcePermissionRequest: Boolean = false,
        forceNativeLoad: Boolean = false,
        allowNativeLoad: Boolean = false,
    ): ThermalStatus {
        return try {
            probeStatus(
                requestPermissionIfMissing = requestPermissionIfMissing,
                forcePermissionRequest = forcePermissionRequest,
                forceNativeLoad = forceNativeLoad,
                allowNativeLoad = allowNativeLoad,
            )
        } catch (error: Throwable) {
            ThermalStatus.blocked("Mini2 status probe failed safely: ${error.javaClass.simpleName}: ${error.message ?: "no message"}")
        }
    }

    fun latestRawFrameSummary(): ThermalRawFrameSummary? {
        return try {
            val mini2 = findMini2Candidate() ?: return null
            if (!usbManager.hasPermission(mini2)) return null
            val moduleType = HikmicroMini2ModuleType.classify(mini2)
            if (moduleType != HikmicroMini2ModuleType.F2) return null
            if (!HikmicroNativeBackend.coreAlreadyLoadedFor(moduleType)) return null
            HikmicroJnaMini2Stream.latestRawFrameSummary(mini2)
        } catch (_: Throwable) {
            null
        }
    }

    fun latestRawStreamJson(
        runtimeMode: Mini2OfficialRuntimeMode = Mini2OfficialRuntimeMode.OFFICIAL_PRIMARY,
    ): JSONObject? {
        val status = latestRawStreamStatus(runtimeMode) ?: return null
        val conversion = HikmicroTemperatureConversionAttempt.describe(
            loadReport = HikmicroNativeBackend.notAttemptedReport(note = "latest_raw_stream_json_converter_status_only"),
            usbPermissionGranted = true,
        )
        return enrichRawStreamJson(status.toJson(), conversion)
    }

    fun latestRawStreamStatus(
        runtimeMode: Mini2OfficialRuntimeMode = Mini2OfficialRuntimeMode.OFFICIAL_PRIMARY,
    ): Mini2RawStreamStatus? {
        return try {
            val mini2 = findMini2Candidate() ?: return null
            if (!usbManager.hasPermission(mini2)) return null
            val moduleType = HikmicroMini2ModuleType.classify(mini2)
            if (moduleType != HikmicroMini2ModuleType.F2) return null
            if (!HikmicroNativeBackend.coreAlreadyLoadedFor(moduleType)) return null
            HikmicroJnaMini2Stream.peekActiveStatus(mini2, runtimeMode)
        } catch (_: Throwable) {
            null
        }
    }

    fun probeStatus(
        requestPermissionIfMissing: Boolean = true,
        forcePermissionRequest: Boolean = false,
        forceNativeLoad: Boolean = false,
        allowNativeLoad: Boolean = false,
    ): ThermalStatus {
        val mini2 = findMini2Candidate()
            ?: return ThermalStatus.blocked("Mini2 USB device not found on Android USB host")
        val moduleType = HikmicroMini2ModuleType.classify(mini2)
        if (!moduleType.isSupported) {
            return ThermalStatus.blocked(HikmicroMini2ModuleType.routeReason(mini2.vendorId, mini2.productId))
        }

        if (!usbManager.hasPermission(mini2)) {
            val requested = if (requestPermissionIfMissing) {
                requestPermissionOnce(mini2, forcePermissionRequest)
            } else {
                false
            }
            val state = permissionSnapshot(mini2, hasPermission = false).optString("mini2_permission_state")
            return if (requested) {
                ThermalStatus.blocked("USB permission requested; waiting for Android grant")
            } else if (state == "denied") {
                ThermalStatus.blocked("USB permission denied; tap Mini2 USB 확인 to retry")
            } else {
                ThermalStatus.blocked("USB permission pending; waiting for Android grant")
            }
        }

        if (!allowNativeLoad) {
            return HikmicroNativeBackend.passiveStatusForUsbPermission(
                usbPermissionGranted = true,
                preferredModuleType = moduleType,
            )
        }

        return try {
            HikmicroNativeBackend.statusForUsbPermission(
                usbPermissionGranted = true,
                nativeLibraryDir = nativeLibraryDir,
                forceRetry = forceNativeLoad,
                preferredModuleType = moduleType,
            )
        } catch (error: Throwable) {
            ThermalStatus.blocked("Mini2 native library status failed safely: ${error.javaClass.simpleName}: ${error.message ?: "no message"}")
        }
    }

    fun findMini2Device(): UsbDevice? = findMini2Candidate()

    fun findMini2Candidate(): UsbDevice? {
        return usbManager.deviceList.values
            .filter { device -> HikmicroMini2ModuleType.isHikmicroCandidate(device) }
            .sortedWith(
                compareByDescending<UsbDevice> { HikmicroMini2ModuleType.classify(it).isSupported }
                    .thenByDescending { it.productId in knownMini2ProductIds }
                    .thenBy { it.deviceName },
            )
            .firstOrNull()
    }

    fun requestPermission(): Boolean {
        val device = findMini2Candidate() ?: return false
        return requestPermission(device)
    }

    fun requestPermission(device: UsbDevice): Boolean {
        val mutabilityFlag = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            /*
             * UsbManager.requestPermission returns the grant result by filling
             * EXTRA_DEVICE and EXTRA_PERMISSION_GRANTED into this PendingIntent.
             * If it is immutable, Android can deliver our action without those
             * fill-in extras, which looks exactly like a false denial.
             */
            PendingIntent.FLAG_MUTABLE
        } else {
            0
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or mutabilityFlag
        val permissionIntent = PendingIntent.getBroadcast(
            context,
            0,
            Intent(USB_PERMISSION_ACTION).setPackage(context.packageName),
            flags,
        )
        synchronized(stateLock) {
            permissionRequestCount += 1
            lastPermissionRequestElapsedMs = SystemClock.elapsedRealtime()
            lastPermissionDeviceName = device.deviceName
            pendingPermissionDeviceName = device.deviceName
            lastPermissionGranted = null
        }
        usbManager.requestPermission(device, permissionIntent)
        return true
    }

    private fun requestPermissionOnce(device: UsbDevice, forcePermissionRequest: Boolean = false): Boolean {
        if (forcePermissionRequest) {
            permissionRequests.remove(device.deviceName)
            synchronized(stateLock) {
                pendingPermissionDeviceName = ""
                lastPermissionGranted = null
            }
        }
        return if (permissionRequests.add(device.deviceName)) {
            requestPermission(device)
        } else {
            false
        }
    }

    private fun rawStreamStatus(
        mini2: UsbDevice?,
        hasPermission: Boolean,
        nativeReport: NativeLibraryLoadReport,
        runtimeMode: Mini2OfficialRuntimeMode,
    ): Mini2RawStreamStatus {
        if (mini2 == null) {
            return Mini2RawStreamStatus.blockedNativeStream(
                "Mini2 USB device not found; cannot open official HIKMICRO stream",
                discovery = "hikmicro_official_stream_blocked_device_not_found",
            )
        }
        if (!hasPermission) {
            return Mini2RawStreamStatus.blockedUsbPermission("USB permission is required before opening Mini2 raw stream")
        }
        val moduleType = HikmicroMini2ModuleType.classify(mini2)
        if (!moduleType.isSupported) {
            return Mini2RawStreamStatus.blockedNativeStream(
                HikmicroMini2ModuleType.routeReason(mini2.vendorId, mini2.productId),
                discovery = "hikmicro_official_route_unsupported",
            )
        }
        if (!nativeReport.coreLoadedFor(moduleType)) {
            return Mini2RawStreamStatus.blockedNativeUsbLibrary(
                nativeReport.coreMissingReasonFor(moduleType).ifBlank { "HIKMICRO ${moduleType.routeName.uppercase()} native core is not loaded" },
                discovery = "native_symbol_discovery_blocked_by_${moduleType.routeName}_library_load",
            )
        }
        if (moduleType == HikmicroMini2ModuleType.F1) {
            return HikmicroF1Mini2Stream.ensureStreaming(
                usbManager = usbManager,
                device = mini2,
                nativeLibraryDir = nativeLibraryDir,
                nativeReport = nativeReport,
                cacheDirPath = context.cacheDir.absolutePath,
            )
        }
        return HikmicroJnaMini2Stream.ensureStreaming(
            context = context,
            usbManager = usbManager,
            device = mini2,
            nativeLibraryDir = nativeLibraryDir,
            nativeReport = nativeReport,
            runtimeMode = runtimeMode,
        )
    }

    private fun safeRawStreamStatus(
        mini2: UsbDevice?,
        hasPermission: Boolean,
        nativeReport: NativeLibraryLoadReport,
        runtimeMode: Mini2OfficialRuntimeMode,
    ): Mini2RawStreamStatus {
        return try {
            rawStreamStatus(mini2, hasPermission, nativeReport, runtimeMode)
        } catch (error: Throwable) {
            Mini2RawStreamStatus.blockedNativeStream(
                "raw_stream_exception ${error.javaClass.simpleName}: ${error.message ?: "no message"}",
                discovery = "raw_stream_exception",
            )
        }
    }

    private fun passiveRawStreamStatus(
        mini2: UsbDevice?,
        hasPermission: Boolean,
        nativeReport: NativeLibraryLoadReport,
    ): Mini2RawStreamStatus {
        if (mini2 == null) {
            return Mini2RawStreamStatus.blockedNativeStream(
                "Mini2 USB device not found; passive status cannot report an active raw stream",
                discovery = "hikmicro_official_passive_poll_device_not_found",
            )
        }
        if (!hasPermission) {
            return Mini2RawStreamStatus.blockedUsbPermission("USB permission is required before passive Mini2 raw stream status can open or inspect native stream state")
        }
        val moduleType = HikmicroMini2ModuleType.classify(mini2)
        if (moduleType == HikmicroMini2ModuleType.F2 && HikmicroNativeBackend.coreAlreadyLoadedFor(moduleType)) {
            HikmicroJnaMini2Stream.peekActiveStatus(
                device = mini2,
                runtimeMode = Mini2OfficialRuntimeMode.OFFICIAL_PRIMARY,
            )?.let { return it }
        }
        return Mini2RawStreamStatus.blockedNativeStream(
            "Mini2 official HCUSBSDK/JNI stream is not started by passive status polling; WebView auto-probe or Mini2 USB 확인 starts one explicit stream probe",
            discovery = "hikmicro_official_passive_poll_crash_guard",
        )
    }

    private fun safePassiveRawStreamStatus(
        mini2: UsbDevice?,
        hasPermission: Boolean,
        nativeReport: NativeLibraryLoadReport,
    ): Mini2RawStreamStatus {
        return try {
            passiveRawStreamStatus(mini2, hasPermission, nativeReport)
        } catch (error: Throwable) {
            Mini2RawStreamStatus.blockedNativeStream(
                "passive_raw_stream_exception ${error.javaClass.simpleName}: ${error.message ?: "no message"}",
                discovery = "passive_raw_stream_exception",
            )
        }
    }


    private fun enrichRawStreamJson(rawStreamJson: JSONObject, conversion: kr.auto.titration.mobile.thermal.HikmicroConversionAttempt): JSONObject {
        val text = listOf(
            rawStreamJson.optString("stage_report"),
            rawStreamJson.optString("reason"),
        ).joinToString("; ")
        val profileName = firstNonBlank(
            parseToken(text, "selectedProfile"),
            parseToken(text, "profile_class"),
            lastAttemptString(rawStreamJson, "profile_class"),
        )
        val profileSize = parseToken(text, "profileSize")
        val profileFps = parseToken(text, "profileFps").toIntOrNullStrict()
        val profileCoding = parseToken(text, "profileCoding").toIntOrNullStrict()
        val profileStreamingNew = parseToken(text, "profileStreamingNew").toBooleanOrNullStrict()
        val allowedSizes = parseAllowedSizes(text).ifEmpty { lastAttemptIntArray(rawStreamJson, "profile_allowed_sizes") }
        val moduleId = firstNonBlank(parseToken(text, "moduleId"), lastAttemptString(rawStreamJson, "profile_module_id"))
        val firmwareDate = firstNonBlank(parseToken(text, "firmwareDate"), lastAttemptInt(rawStreamJson, "profile_firmware_date")?.takeIf { it >= 0 }?.toString())
        val packetClassification = parseToken(text, "packet_classification")
        val packetStatus = parseToken(text, "packet_status")
        val packetSizeBytes = parseToken(text, "bytes").toIntOrNullStrict()
        val evidencePrefix = parseToken(text, "evidence_prefix")
        val selectedProfile = JSONObject()
            .put("inputs", JSONObject()
                .put("module_id", moduleId.ifBlank { JSONObject.NULL })
                .put("firmware_date", firmwareDate.ifBlank { JSONObject.NULL }))
            .put("name", profileName.ifBlank { JSONObject.NULL })
            .put("size", profileSize.ifBlank { JSONObject.NULL })
            .put("fps", profileFps ?: JSONObject.NULL)
            .put("coding", profileCoding ?: JSONObject.NULL)
            .put("streamingNew", profileStreamingNew ?: JSONObject.NULL)
            .put("allowed_packet_sizes", JSONArray(allowedSizes))

        val hasDeviceGlobalSummary = hasValidDeviceGlobalSummary(rawStreamJson)
        val converterAttemptDiagnostic = conversion.toJson()
        rawStreamJson
            .put("temperature_conversion_attempt", converterAttemptDiagnostic)
            .put("matrix_conversion_attempt", converterAttemptDiagnostic)
            .put("full_matrix_celsius_allowed", false)
            .put("full_matrix_temperature_status", rawStreamJson.optString("full_matrix_temperature_status", "unproved_not_emitted"))
        if (!hasDeviceGlobalSummary) {
            rawStreamJson
                .put("celsius_allowed", false)
                .put("temperature_avg_c", JSONObject.NULL)
                .put("temperature_min_c", JSONObject.NULL)
                .put("temperature_max_c", JSONObject.NULL)
                .put("temperature_provenance", JSONObject.NULL)
                .put("temperature_scope", JSONObject.NULL)
                .put("temperature_requested_display_unit", JSONObject.NULL)
                .put("temperature_requested_display_unit_code", JSONObject.NULL)
                .put("temperature_summary", JSONObject.NULL)
        }

        return rawStreamJson
            .put("selected_profile", selectedProfile)
            .put("selected_profile_inputs", selectedProfile.optJSONObject("inputs"))
            .put("selected_profile_name", profileName.ifBlank { JSONObject.NULL })
            .put("selected_profile_size", profileSize.ifBlank { JSONObject.NULL })
            .put("selected_profile_fps", profileFps ?: JSONObject.NULL)
            .put("selected_profile_coding", profileCoding ?: JSONObject.NULL)
            .put("selected_profile_streamingNew", profileStreamingNew ?: JSONObject.NULL)
            .put("selected_profile_allowed_sizes", JSONArray(allowedSizes))
            .put("packet_classification", packetClassification.ifBlank { JSONObject.NULL })
            .put("packet_status", packetStatus.ifBlank { JSONObject.NULL })
            .put("packet_size_bytes", packetSizeBytes ?: JSONObject.NULL)
            .put("packet_evidence_prefix", evidencePrefix.ifBlank { JSONObject.NULL })
            .put("converter_profile_status", if (hasDeviceGlobalSummary) rawStreamJson.optString("converter_profile_status", conversion.converterProfileStatus) else conversion.converterProfileStatus)
            .put("converter_validation_state", conversion.validationEvidence.toJson())
    }

    private fun hasValidDeviceGlobalSummary(rawStreamJson: JSONObject): Boolean {
        val summary = rawStreamJson.optJSONObject("temperature_summary")
        val provenance = rawStreamJson.optString("temperature_provenance", summary?.optString("provenance").orEmpty())
        val scope = rawStreamJson.optString("temperature_scope", summary?.optString("scope").orEmpty())
        return rawStreamJson.optBoolean("celsius_allowed", false) &&
            !rawStreamJson.optBoolean("full_matrix_celsius_allowed", false) &&
            provenance == "device_global_summary" &&
            scope == "device_global_summary" &&
            jsonFiniteDoubleOrNull(rawStreamJson, "temperature_avg_c") != null &&
            jsonFiniteDoubleOrNull(rawStreamJson, "temperature_min_c") != null &&
            jsonFiniteDoubleOrNull(rawStreamJson, "temperature_max_c") != null
    }

    private fun jsonFiniteDoubleOrNull(json: JSONObject, key: String): Double? {
        if (!json.has(key) || json.isNull(key)) return null
        val value = json.optDouble(key, Double.NaN)
        return value.takeIf { it.isFinite() }
    }

    private fun jsonStringOrNull(json: JSONObject, key: String): Any {
        if (!json.has(key) || json.isNull(key)) return JSONObject.NULL
        return json.optString(key).takeIf { it.isNotBlank() } ?: JSONObject.NULL
    }

    private fun jsonIntOrNull(json: JSONObject, key: String): Any {
        if (!json.has(key) || json.isNull(key)) return JSONObject.NULL
        return json.optInt(key)
    }

    private fun parseToken(text: String, key: String): String {
        val match = Regex("(?:^|[;\\s])" + Regex.escape(key) + "=([^;\\s]+)").find(text) ?: return ""
        return match.groupValues[1].trim().trim(',')
    }

    private fun parseAllowedSizes(text: String): List<Int> {
        val bracket = Regex("profileAllowedSizes=\\[([^\\]]*)\\]").find(text)?.groupValues?.get(1) ?: return emptyList()
        return bracket.split(',').mapNotNull { it.trim().toIntOrNull() }
    }

    private fun firstNonBlank(vararg values: String?): String = values.firstOrNull { !it.isNullOrBlank() }.orEmpty()

    private fun String.toIntOrNullStrict(): Int? = trim().takeIf { it.isNotBlank() }?.toIntOrNull()

    private fun String.toBooleanOrNullStrict(): Boolean? = when (trim().lowercase()) {
        "true" -> true
        "false" -> false
        else -> null
    }

    private fun lastAttempt(rawStreamJson: JSONObject): JSONObject? {
        val attempts = rawStreamJson.optJSONArray("attempt_diagnostics") ?: return null
        for (index in attempts.length() - 1 downTo 0) {
            val item = attempts.optJSONObject(index) ?: continue
            return item
        }
        return null
    }

    private fun lastAttemptString(rawStreamJson: JSONObject, key: String): String =
        lastAttempt(rawStreamJson)?.optString(key).orEmpty()

    private fun lastAttemptInt(rawStreamJson: JSONObject, key: String): Int? {
        val attempt = lastAttempt(rawStreamJson) ?: return null
        return if (attempt.has(key) && !attempt.isNull(key)) attempt.optInt(key) else null
    }

    private fun lastAttemptIntArray(rawStreamJson: JSONObject, key: String): List<Int> {
        val array = lastAttempt(rawStreamJson)?.optJSONArray(key) ?: return emptyList()
        return (0 until array.length()).mapNotNull { index -> array.optInt(index) }
    }

    private fun currentUsbPresenceJson(
        mini2: UsbDevice?,
        hasPermission: Boolean,
        status: ThermalStatus,
        permissionSnapshot: JSONObject,
        routeJson: JSONObject,
    ): JSONObject = JSONObject()
        .put("state", status.state.name.lowercase())
        .put("reason", status.reason)
        .put("device_present", mini2 != null)
        .put("has_permission", hasPermission)
        .put("permission_state", permissionSnapshot.optString("mini2_permission_state"))
        .put("permission_pending", permissionSnapshot.optBoolean("permission_pending"))
        .put("last_usb_event", permissionSnapshot.optString("last_usb_event"))
        .put("last_usb_event_elapsed_ms", permissionSnapshot.optLong("last_usb_event_elapsed_ms"))
        .put("last_usb_event_device_name", permissionSnapshot.optString("last_usb_event_device_name"))
        .put("route", routeJson)
        .put("route_reason", routeJson.optString("reason"))
        .put("official_module_type", routeJson.optString("module_type"))
        .put("selected_backend", routeJson.optString("backend"))

    private fun nativePermissionGateJson(
        mini2: UsbDevice?,
        hasPermission: Boolean,
        moduleType: HikmicroMini2ModuleType,
        nativeLoadAttempted: Boolean,
    ): JSONObject = JSONObject()
        .put("device_present", mini2 != null)
        .put("has_permission", hasPermission)
        .put("native_load_attempted", nativeLoadAttempted)
        .put("native_open_start_allowed", nativeLoadAttempted && mini2 != null && hasPermission && moduleType.isSupported)
        .put("explicit_native_stream_requested", nativeLoadAttempted)
        .put("reason", nativeNotAttemptedReason(mini2, hasPermission, moduleType))

    private fun nativeNotAttemptedReason(
        mini2: UsbDevice?,
        hasPermission: Boolean,
        moduleType: HikmicroMini2ModuleType,
    ): String = when {
        mini2 == null -> "Mini2 USB device not found; native load/open/start skipped"
        !hasPermission -> "USB permission missing; native load/open/start skipped until Android grants Mini2 access"
        !moduleType.isSupported -> "Unsupported HIKMICRO USB module; native load/open/start skipped"
        else -> "USB permission granted and supported Mini2 route selected; native load/open/start deferred until explicit Mini2 stream attempt"
    }

    private fun devicesJson(): JSONArray = JSONArray(
        usbManager.deviceList.values
            .sortedBy { it.deviceName }
            .map { device ->
                JSONObject()
                    .put("device_name", device.deviceName)
                    .put("vendor_id", String.format("0x%04x", device.vendorId))
                    .put("product_id", String.format("0x%04x", device.productId))
                    .put("official_module_type", HikmicroMini2ModuleType.classify(device).routeName)
                    .put("selected_backend", HikmicroMini2ModuleType.classify(device).backendName)
                    .put("route_reason", HikmicroMini2ModuleType.routeReason(device.vendorId, device.productId))
                    .put("interface_count", device.interfaceCount)
                    .put("is_hikmicro_vendor", HikmicroMini2ModuleType.isHikmicroCandidate(device))
                    .put("has_permission", usbManager.hasPermission(device))
            },
    )

    private fun permissionSnapshot(device: UsbDevice?, hasPermission: Boolean): JSONObject {
        synchronized(stateLock) {
            val pending = pendingPermissionDeviceName.isNotBlank()
            val permissionState = when {
                hasPermission -> "granted"
                lastPermissionGranted == false && lastPermissionDeviceName == device?.deviceName -> "denied"
                pending -> "requested"
                device == null -> "device_not_found"
                else -> "not_requested"
            }
            return JSONObject()
                .put("mini2_permission_state", permissionState)
                .put("permission_request_count", permissionRequestCount)
                .put("permission_pending", pending)
                .put("last_permission_request_elapsed_ms", lastPermissionRequestElapsedMs)
                .put("last_permission_decision_elapsed_ms", lastPermissionDecisionElapsedMs)
                .put("last_permission_device_name", lastPermissionDeviceName)
                .put("pending_permission_device_name", pendingPermissionDeviceName)
                .put("last_permission_granted", lastPermissionGranted ?: JSONObject.NULL)
                .put("last_usb_event", lastUsbEvent)
                .put("last_usb_event_elapsed_ms", lastUsbEventElapsedMs)
                .put("last_usb_event_device_name", lastUsbEventDeviceName)
                .put("usb_receiver_registered", receiverRegistered)
        }
    }

    @Suppress("DEPRECATION")
    private fun Intent.usbDeviceExtra(): UsbDevice? {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
        } else {
            getParcelableExtra(UsbManager.EXTRA_DEVICE)
        }
    }

    /** Legacy compatibility for older mobile-frame protocol tests. */
    fun attachThermalFields(frame: JSONObject): JSONObject {
        val evidence = probe(requestPermissionIfMissing = false)
        frame.put("thermal_calibrated", false)
        frame.put("thermal_status", evidence.optString("mini2_status", "blocked"))
        frame.put("thermal_raw_status", evidence.optString("mini2_status", "blocked"))
        frame.put("thermal_raw_note", evidence.optString("mini2_reason", "Mini2 not calibrated"))
        frame.put("mini2", evidence)
        return frame
    }
}
