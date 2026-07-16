package kr.auto.titration.mobile.thermal

import android.os.Build
import android.os.SystemClock
import java.io.File
import org.json.JSONArray
import org.json.JSONObject

private const val NATIVE_LOAD_RETRY_INTERVAL_MS = 3_000L

/** One native library load attempt packaged from the analyzed HIKMICRO Viewer APK. */
data class NativeLibraryLoadEntry(
    val fileName: String,
    val loadName: String,
    val loaded: Boolean,
    val error: String? = null,
    val loadState: String = if (loaded) "loaded" else error ?: "failed",
    val attempted: Boolean = loaded || (error != null && error != "not_attempted" && !loadState.contains("deferred")),
    val role: String = "packaged_inventory",
) {
    fun toJson(): JSONObject = JSONObject()
        .put("file", fileName)
        .put("load_name", loadName)
        .put("loaded", loaded)
        .put("attempted", attempted)
        .put("load_state", loadState)
        .put("role", role)
        .put("error", error ?: "")
}

data class NativeLibraryLoadReport(
    val entries: List<NativeLibraryLoadEntry>,
    val note: String,
    val nativeLibraryDir: String = "",
    val supportedAbis: List<String> = emptyList(),
    val loadStrategy: String = "system_load_library",
    val attemptCount: Int = 0,
    val attemptedAtElapsedMs: Long = 0L,
    val retryAfterMs: Long = 0L,
    val retryEligible: Boolean = false,
    val coreMissingReason: String = "",
) {
    val allLoaded: Boolean
        get() = entries.isNotEmpty() && entries.all { it.loaded }

    val attemptedLibrariesLoaded: Boolean
        get() = entries.any { it.attempted } && entries.filter { it.attempted }.all { it.loaded }

    val coreUsbLoaded: Boolean
        get() = coreF2Loaded

    val coreF1Loaded: Boolean
        get() = entries.any { it.fileName == "lib_thermal_module.so" && it.loaded }

    val coreF2Loaded: Boolean
        get() = entries.any { it.fileName == "libHCUSBSDK.so" && it.loaded }

    val coreMini2Loaded: Boolean
        get() = coreF1Loaded || coreF2Loaded

    val coreTemperatureLoaded: Boolean
        get() = entries.any { it.fileName == "libMTlib.so" && it.loaded } &&
            entries.any { it.fileName == "libMicroJITA_Release_v8a.so" && it.loaded } &&
            entries.any { it.fileName == "libMicroTA_Release_v8a.so" && it.loaded }

    fun toJson(): JSONObject = JSONObject()
        .put("all_loaded", allLoaded)
        .put("attempted_libraries_loaded", attemptedLibrariesLoaded)
        .put("core_usb_loaded", coreUsbLoaded)
        .put("core_f1_loaded", coreF1Loaded)
        .put("core_f2_loaded", coreF2Loaded)
        .put("core_mini2_loaded", coreMini2Loaded)
        .put("core_temperature_loaded", coreTemperatureLoaded)
        .put("native_library_dir", nativeLibraryDir)
        .put("supported_abis", JSONArray(supportedAbis))
        .put("load_strategy", loadStrategy)
        .put("attempt_count", attemptCount)
        .put("attempted_at_elapsed_ms", attemptedAtElapsedMs)
        .put("retry_after_ms", retryAfterMs)
        .put("retry_eligible", retryEligible)
        .put("core_missing_reason", coreMissingReason)
        .put("failed_count", entries.count { it.attempted && !it.loaded })
        .put("deferred_count", entries.count { !it.attempted && !it.loaded })
        .put("native_symbol_discovery", "see .omx/drafts/mini2-native-symbol-discovery.md")
        .put("note", note)
        .put("libraries", JSONArray(entries.map { it.toJson() }))

    fun coreLoadedFor(moduleType: HikmicroMini2ModuleType): Boolean = when (moduleType) {
        HikmicroMini2ModuleType.F1 -> coreF1Loaded
        HikmicroMini2ModuleType.F2 -> coreF2Loaded
        HikmicroMini2ModuleType.UNSUPPORTED -> false
    }

    fun coreMissingReasonFor(moduleType: HikmicroMini2ModuleType): String = when (moduleType) {
        HikmicroMini2ModuleType.F1 -> missingReasonFor("lib_thermal_module.so")
        HikmicroMini2ModuleType.F2 -> missingReasonFor("libHCUSBSDK.so")
        HikmicroMini2ModuleType.UNSUPPORTED -> "unsupported_hikmicro_usb_module"
    }

    private fun missingReasonFor(fileName: String): String {
        val entry = entries.firstOrNull { it.fileName == fileName }
        return when {
            entry == null -> "$fileName: not_packaged"
            entry.loaded -> ""
            else -> "$fileName: ${entry.error ?: "load_failed"}"
        }
    }
}

/**
 * Local/private HIKMICRO Android native backend gate.
 *
 * These libraries came from the previous HIKMICRO Viewer APK/XAPK analysis and
 * are packaged only so this APK can attempt phone-local Mini2 feasibility. The
 * backend intentionally stays raw_unverified until live stream callbacks and
 * fixture comparison are proven on the actual phone; it never emits Celsius just
 * because `libMTlib.so` or `grayToTemperature` symbols exist.
 */
object HikmicroNativeBackend : Mini2ThermalBackend {
    val packagedLibraries = listOf(
        "libc++_shared.so",
        "libjpeg.so",
        "libcrypto.so",
        "libusb-1.0.so",
        "libusb1.0.so",
        "libuvc.so",
        "libusbCam_host.so",
        "libjnidispatch.so",
        "libhikdsp.so",
        "libdadsp.so",
        "libAnalyzeData.so",
        "libFormatConversion.so",
        "libifrgisp.so",
        "libColorAlarm_PcProc.so",
        "libtvf.so",
        "libtsr_v2.0.0.so",
        "libacnn_v2.3.4.so",
        "libomp.so",
        "libxml2.so",
        "libMicroSecurityKit_Release_v8a.so",
        "libMicroParallel_Release_v8a.so",
        "libMicroDriver_Release_v8a.so",
        "libMicroDM_Release_v8a.so",
        "libMicroMC_Release_v8a.so",
        "libMicroRVP_Release_v8a.so",
        "libMicroRVR_Release_v8a.so",
        "libMicroJPEG_Release_v8a.so",
        "libMicroIA_Release_v8a.so",
        "libMicroJITA_Release_v8a.so",
        "libMicroTA_Release_v8a.so",
        "libMTlib.so",
        "libHwCodecer.so",
        "libThermalPlayCtrl.so",
        "libOfflinePic.so",
        "libOffline_Pic.so",
        "lib_thermal_module.so",
        "libRID_ANDROID_V1.0.6_BUILD_20250312.so",
        "libanalyzer_rid.so",
        "libHCUSBSDK.so",
    )

    val expectedSymbols = listOf(
        "HC_USBCamera_Init",
        "HC_USBCamera_Open",
        "HC_USBCamera_StartPreview",
        "USB_StartStreamCallback",
        "JNI_GetJpegpicWithAppendData",
        "thermal_init_thermal_module",
        "thermal_function_stream_realtime_init",
        "MT_Gray2Temp",
        "MT_GetGray2TempTable",
        "grayToTemperature",
    )

    @Volatile
    private var cachedReport: NativeLibraryLoadReport? = null
    @Volatile
    private var cachedNativeLibraryDir: String? = null
    @Volatile
    private var cachedReportLoadedAtMs: Long = 0L
    @Volatile
    private var cachedModuleType: HikmicroMini2ModuleType = HikmicroMini2ModuleType.UNSUPPORTED
    private val loadedLibraries = mutableSetOf<String>()
    private var nativeLoadAttemptCount: Int = 0

    fun notAttemptedReport(note: String = "Native library loading not attempted during passive status polling"): NativeLibraryLoadReport {
        return NativeLibraryLoadReport(
            entries = packagedLibraries.map { fileName ->
                NativeLibraryLoadEntry(
                    fileName = fileName,
                    loadName = loadNameFor(fileName),
                    loaded = false,
                    error = "not_attempted",
                    loadState = "not_attempted",
                    attempted = false,
                    role = libraryRoleFor(fileName, HikmicroMini2ModuleType.UNSUPPORTED),
                )
            },
            note = note,
            supportedAbis = supportedAbis(),
            loadStrategy = "not_attempted",
            coreMissingReason = "not_attempted",
        )
    }

    override val status: ThermalStatus
        get() = statusForUsbPermission(usbPermissionGranted = false)

    override val validationEvidence: Mini2ValidationEvidence
        get() = Mini2ValidationEvidence(
            abiLoaded = cachedReport?.allLoaded == true,
            fixtureCompared = false,
            liveStreamObserved = false,
            meanErrorC = null,
            maxPixelErrorC = null,
            licenseAllowsRedistribution = false,
            note = "Android HIKMICRO libs packaged; validation evidence is passive and does not load/open/start native USB without permission-gated probe flow.",
        )

    fun ensureLibrariesLoaded(
        nativeLibraryDir: String? = null,
        forceRetry: Boolean = false,
        moduleType: HikmicroMini2ModuleType = HikmicroMini2ModuleType.F2,
    ): NativeLibraryLoadReport {
        val normalizedNativeLibraryDir = nativeLibraryDir?.takeIf { it.isNotBlank() }
        val now = SystemClock.elapsedRealtime()
        cachedReport?.takeIf { cached ->
            cachedNativeLibraryDir == normalizedNativeLibraryDir &&
                cachedModuleType == moduleType &&
                !forceRetry &&
                (cached.coreLoadedFor(moduleType) || !cached.coreLoadedFor(moduleType) && now - cachedReportLoadedAtMs < NATIVE_LOAD_RETRY_INTERVAL_MS)
        }?.let { return it }
        synchronized(this) {
            val lockedNow = SystemClock.elapsedRealtime()
            cachedReport?.takeIf { cached ->
                cachedNativeLibraryDir == normalizedNativeLibraryDir &&
                    cachedModuleType == moduleType &&
                    !forceRetry &&
                    (cached.coreLoadedFor(moduleType) || !cached.coreLoadedFor(moduleType) && lockedNow - cachedReportLoadedAtMs < NATIVE_LOAD_RETRY_INTERVAL_MS)
            }?.let { return it }
            nativeLoadAttemptCount += 1
            val attemptStartedAtMs = SystemClock.elapsedRealtime()
            val coreLoadSet = provenCoreLibrariesFor(moduleType)
            val entries = packagedLibraries.map { fileName ->
                val loadName = loadNameFor(fileName)
                val role = libraryRoleFor(fileName, moduleType)
                when {
                    fileName in loadedLibraries -> NativeLibraryLoadEntry(
                        fileName = fileName,
                        loadName = loadName,
                        loaded = true,
                        loadState = "loaded_previously",
                        attempted = true,
                        role = role,
                    )
                    fileName in coreLoadSet -> try {
                        loadPackagedLibrary(
                            fileName = fileName,
                            loadName = loadName,
                            nativeLibraryDir = normalizedNativeLibraryDir,
                        )
                        loadedLibraries.add(fileName)
                        NativeLibraryLoadEntry(
                            fileName = fileName,
                            loadName = loadName,
                            loaded = true,
                            loadState = "loaded",
                            attempted = true,
                            role = role,
                        )
                    } catch (error: Throwable) {
                        NativeLibraryLoadEntry(
                            fileName = fileName,
                            loadName = loadName,
                            loaded = false,
                            error = error.message ?: error.javaClass.simpleName,
                            loadState = "failed",
                            attempted = true,
                            role = role,
                        )
                    }
                    else -> NativeLibraryLoadEntry(
                        fileName = fileName,
                        loadName = loadName,
                        loaded = false,
                        error = deferredReasonFor(fileName, moduleType),
                        loadState = deferredReasonFor(fileName, moduleType),
                        attempted = false,
                        role = role,
                    )
                }
            }
            return NativeLibraryLoadReport(
                entries = entries,
                note = "official ${moduleType.routeName.uppercase()} load plan: only proved route core is explicitly loaded; packaged DT_NEEDED/deferred libraries remain diagnostic inventory",
                nativeLibraryDir = normalizedNativeLibraryDir.orEmpty(),
                supportedAbis = supportedAbis(),
                loadStrategy = if (normalizedNativeLibraryDir == null) {
                    "system_load_library"
                } else {
                    "system_load_absolute_native_library_dir"
                },
                attemptCount = nativeLoadAttemptCount,
                attemptedAtElapsedMs = attemptStartedAtMs,
                retryAfterMs = if (entries.filter { it.attempted }.all { it.loaded }) 0L else NATIVE_LOAD_RETRY_INTERVAL_MS,
                retryEligible = entries.any { it.attempted && !it.loaded },
                coreMissingReason = coreMissingReason(entries, moduleType),
            ).also {
                cachedNativeLibraryDir = normalizedNativeLibraryDir
                cachedModuleType = moduleType
                cachedReport = it
                cachedReportLoadedAtMs = SystemClock.elapsedRealtime()
            }
        }
    }


    fun passiveStatusForUsbPermission(
        usbPermissionGranted: Boolean,
        preferredModuleType: HikmicroMini2ModuleType = HikmicroMini2ModuleType.F2,
    ): ThermalStatus {
        if (!usbPermissionGranted) {
            return ThermalStatus.blocked("Mini2 USB permission is required before opening HIKMICRO native stream")
        }
        if (!preferredModuleType.isSupported) {
            return ThermalStatus.blocked("Unsupported HIKMICRO USB VID/PID; official APK route cannot select F1/F2 backend")
        }
        return ThermalStatus.rawUnverified(
            "USB permission granted; HIKMICRO ${preferredModuleType.routeName.uppercase()} native load/open/start is deferred until an explicit Mini2 stream attempt",
            backendName = preferredModuleType.backendName,
        )
    }

    fun coreAlreadyLoadedFor(moduleType: HikmicroMini2ModuleType): Boolean =
        cachedReport?.coreLoadedFor(moduleType) == true

    fun statusForUsbPermission(
        usbPermissionGranted: Boolean,
        nativeLibraryDir: String? = null,
        forceRetry: Boolean = false,
        preferredModuleType: HikmicroMini2ModuleType = HikmicroMini2ModuleType.F2,
    ): ThermalStatus {
        if (!usbPermissionGranted) {
            return ThermalStatus.blocked("Mini2 USB permission is required before opening HIKMICRO native stream")
        }
        if (!preferredModuleType.isSupported) {
            return ThermalStatus.blocked("Unsupported HIKMICRO USB VID/PID; official APK route cannot select F1/F2 backend")
        }
        val report = ensureLibrariesLoaded(nativeLibraryDir, forceRetry = forceRetry, moduleType = preferredModuleType)
        if (!report.coreLoadedFor(preferredModuleType)) {
            return ThermalStatus.blocked(
                "HIKMICRO ${preferredModuleType.routeName.uppercase()} native core did not load; ${report.coreMissingReasonFor(preferredModuleType)}",
            )
        }
        if (!report.coreTemperatureLoaded) {
            return ThermalStatus.rawUnverified(
                "USB permission granted; ${preferredModuleType.routeName.uppercase()} raw stream backend may be available, but temperature converter libraries did not all load",
                backendName = preferredModuleType.backendName,
            )
        }
        return ThermalStatus.rawUnverified(
            "USB permission granted and HIKMICRO ${preferredModuleType.routeName.uppercase()} Android libraries loaded; raw/preview stream is still live-hardware gated and Celsius is not emitted until validation passes",
            backendName = preferredModuleType.backendName,
        )
    }

    private fun supportedAbis(): List<String> = runCatching { Build.SUPPORTED_ABIS?.toList().orEmpty() }.getOrDefault(emptyList())

    private fun loadPackagedLibrary(fileName: String, loadName: String, nativeLibraryDir: String?) {
        if (nativeLibraryDir != null) {
            val packagedFile = File(nativeLibraryDir, fileName)
            if (packagedFile.isFile) {
                System.load(packagedFile.absolutePath)
                return
            }
        }
        System.loadLibrary(loadName)
    }

    fun provenCoreLibrariesFor(moduleType: HikmicroMini2ModuleType): Set<String> = when (moduleType) {
        HikmicroMini2ModuleType.F2 -> setOf("libHCUSBSDK.so")
        HikmicroMini2ModuleType.F1 -> setOf("lib_thermal_module.so")
        HikmicroMini2ModuleType.UNSUPPORTED -> emptySet()
    }

    private fun coreMissingReason(entries: List<NativeLibraryLoadEntry>, moduleType: HikmicroMini2ModuleType): String {
        val failedCore = entries.firstOrNull { it.fileName in provenCoreLibrariesFor(moduleType) && !it.loaded }
        return failedCore?.let { "${it.fileName}: ${it.error ?: it.loadState}" }.orEmpty()
    }

    private fun libraryRoleFor(fileName: String, moduleType: HikmicroMini2ModuleType): String = when {
        fileName in provenCoreLibrariesFor(moduleType) -> "${moduleType.routeName}_proved_core"
        moduleType == HikmicroMini2ModuleType.F2 && fileName in setOf("libuvc.so", "libusb1.0.so") -> "f2_dt_needed_dependency"
        moduleType == HikmicroMini2ModuleType.F1 && fileName in setOf("libusbCam_host.so", "libusb-1.0.so", "libhikdsp.so", "libdadsp.so") -> "f1_dt_needed_dependency"
        else -> "packaged_deferred_inventory"
    }

    private fun deferredReasonFor(fileName: String, moduleType: HikmicroMini2ModuleType): String = when (libraryRoleFor(fileName, moduleType)) {
        "f2_dt_needed_dependency", "f1_dt_needed_dependency" -> "packaged_dt_needed_dependency_deferred"
        else -> "packaged_deferred_not_attempted"
    }

    private fun loadNameFor(fileName: String): String = fileName.removePrefix("lib").removeSuffix(".so")

}
