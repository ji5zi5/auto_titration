package kr.auto.titration.mobile.thermal

import android.content.Context
import android.graphics.Rect
import android.os.SystemClock
import com.hik.f2module.F2CalibrationFileResult
import com.hik.f2module.F2CalibrationIdentitySummary
import com.hik.f2module.F2MeasurementSettings
import com.hik.f2module.F2SessionToken
import com.hik.f2module.F2UsbModuleHelper
import java.io.File
import java.util.HashMap
import java.util.concurrent.Executor
import java.util.concurrent.Executors
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2ModuleIdentity
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2ModuleSubtype
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2PaletteSnapshot
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2RadiometricBridge
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2RadiometricRequest
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2RadiometricResult

private const val OFFICIAL_F2_MEASUREMENT_MIN_INTERVAL_MS = 500L
private const val JPEG_SOI_0 = 0xff.toByte()
private const val JPEG_SOI_1 = 0xd8.toByte()
private const val STANDARD_F2_PORTRAIT_CAPTURE_WIDTH = 720
private const val STANDARD_F2_PORTRAIT_CAPTURE_HEIGHT = 960
private const val F0_CAPTURE_WIDTH = 720
private const val F0_CAPTURE_HEIGHT = 720

/**
 * Host-side official F2 measurement boundary.
 *
 * Preview callbacks only publish immutable official packet snapshots. This
 * coordinator is the first point that may acquire command 2054 calibration and
 * attempt the child-loaded official radiometric chain. It is async,
 * single-flight, lifecycle-generation checked, and intentionally publishes only
 * scalar Celsius stats; it never exposes or infers a full temperature matrix.
 */
object OfficialF2MeasurementCoordinator {
    private val lifecycleLock = Any()

    private var inFlightGeneration: Long? = null

    @Volatile
    private var executor: Executor = newExecutor()

    @Volatile
    private var generation: Long = 0L

    @Volatile
    private var lastAcceptedRequestElapsedMs: Long = 0L

    @Volatile
    private var latestState: OfficialF2ScalarMeasurementState = OfficialF2ScalarMeasurementState.idle()

    @Volatile
    private var latestCompletedState: OfficialF2ScalarMeasurementState? = null

    fun latest(): OfficialF2ScalarMeasurementState = synchronized(lifecycleLock) {
        selectOfficialF2PublishedMeasurementState(latestState, latestCompletedState)
    }

    fun resetLifecycle() {
        synchronized(lifecycleLock) {
            generation += 1L
            lastAcceptedRequestElapsedMs = 0L
            latestState = OfficialF2ScalarMeasurementState.idle()
            latestCompletedState = null
            inFlightGeneration = null
        }
    }

    fun requestMeasurement(
        context: Context,
        officialFrame: OfficialProcessedF2Frame,
        calibrationDir: File,
        measurementRoi: Rect? = null,
        helper: F2UsbModuleHelper = F2UsbModuleHelper.INSTANCE,
        bridge: OfficialF2RadiometricBridge = OfficialF2RadiometricBridge(),
        requestLifecycleGuard: () -> Boolean = { true },
    ): OfficialF2ScalarMeasurementState {
        val requestGeneration = generation
        val now = SystemClock.elapsedRealtime()
        if (!requestLifecycleGuard()) {
            return OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = "official_f2_measurement_external_lifecycle_changed_before_enqueue",
                calibration = helper.latestCalibrationAcquisitionResult(),
                identity = helper.activeCalibrationIdentitySummary(),
                generation = requestGeneration,
            )
        }
        val persistentCalibrationDir = try {
            requireOfficialF2CalibrationDirectory(calibrationDir)
        } catch (error: Throwable) {
            val failed = OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = "official_f2_persistent_calibration_directory_unavailable_fail_closed: ${error.message ?: error.javaClass.simpleName}",
                calibration = helper.latestCalibrationAcquisitionResult(),
                identity = helper.activeCalibrationIdentitySummary(),
                generation = requestGeneration,
            )
            synchronized(lifecycleLock) {
                if (requestGeneration == generation) latestState = failed
            }
            return failed
        }
        val sessionToken = helper.activeSessionToken()
        if (sessionToken == null) {
            val failed = OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = "official_f2_measurement_requires_active_session_token",
                calibration = helper.latestCalibrationAcquisitionResult(),
                identity = helper.activeCalibrationIdentitySummary(),
                generation = requestGeneration,
            )
            synchronized(lifecycleLock) {
                if (requestGeneration == generation) latestState = failed
            }
            return failed
        }
        synchronized(lifecycleLock) {
            if (requestGeneration != generation) {
                return OfficialF2ScalarMeasurementState.failed(
                    frameCounter = officialFrame.frameCounter,
                    reason = "official_f2_measurement_lifecycle_changed_before_enqueue",
                    calibration = helper.latestCalibrationAcquisitionResult(),
                    identity = helper.activeCalibrationIdentitySummary(),
                    generation = requestGeneration,
                )
            }
            if (!helper.isSessionTokenCurrent(sessionToken)) {
                return OfficialF2ScalarMeasurementState.failed(
                    frameCounter = officialFrame.frameCounter,
                    reason = "official_f2_session_changed_before_enqueue",
                    calibration = helper.latestCalibrationAcquisitionResult(),
                    identity = sessionToken.identity,
                    generation = requestGeneration,
                )
            }
            if (!requestLifecycleGuard()) {
                return OfficialF2ScalarMeasurementState.failed(
                    frameCounter = officialFrame.frameCounter,
                    reason = "official_f2_measurement_external_lifecycle_changed_before_enqueue_commit",
                    calibration = helper.latestCalibrationAcquisitionResult(),
                    identity = sessionToken.identity,
                    generation = requestGeneration,
                )
            }
            if (inFlightGeneration == generation) {
                return OfficialF2ScalarMeasurementState.transient(
                    status = OfficialF2ScalarMeasurementStatus.IN_FLIGHT,
                    reason = "official_f2_measurement_single_flight_already_running",
                    frameCounter = officialFrame.frameCounter,
                    requestedElapsedMs = now,
                ).also { latestState = it }
            }
            val elapsedSinceAccepted = now - lastAcceptedRequestElapsedMs
            if (lastAcceptedRequestElapsedMs != 0L && elapsedSinceAccepted < OFFICIAL_F2_MEASUREMENT_MIN_INTERVAL_MS) {
                return OfficialF2ScalarMeasurementState.transient(
                    status = OfficialF2ScalarMeasurementStatus.RATE_LIMITED,
                    reason = "official_f2_measurement_rate_limited elapsedMs=$elapsedSinceAccepted minMs=$OFFICIAL_F2_MEASUREMENT_MIN_INTERVAL_MS",
                    frameCounter = officialFrame.frameCounter,
                    requestedElapsedMs = now,
                ).also { latestState = it }
            }
            lastAcceptedRequestElapsedMs = now
            inFlightGeneration = requestGeneration
            latestState = OfficialF2ScalarMeasurementState.pending(
                frameCounter = officialFrame.frameCounter,
                requestedElapsedMs = now,
            )
        }

        val appContext = context.applicationContext ?: context
        try {
            executor.execute {
                val completed = runMeasurement(
                    appContext = appContext,
                    calibrationDir = persistentCalibrationDir,
                    officialFrame = officialFrame,
                    measurementRoi = measurementRoi,
                    helper = helper,
                    bridge = bridge,
                    requestGeneration = requestGeneration,
                    sessionToken = sessionToken,
                    requestLifecycleGuard = requestLifecycleGuard,
                )
                synchronized(lifecycleLock) {
                    if (requestGeneration == generation && inFlightGeneration == requestGeneration) {
                        val committed = if (
                            helper.isSessionTokenCurrent(sessionToken) &&
                            requestLifecycleGuard()
                        ) {
                            completed
                        } else {
                            staleSessionFailure(
                                officialFrame,
                                helper,
                                sessionToken,
                                requestGeneration,
                                "before_commit",
                            )
                        }
                        latestState = committed
                        if (committed.status == OfficialF2ScalarMeasurementStatus.READY) {
                            latestCompletedState = committed
                        }
                        inFlightGeneration = null
                    }
                }
            }
        } catch (error: Throwable) {
            val failed = OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = "official_f2_measurement_executor_rejected: ${error.javaClass.simpleName}: ${error.message ?: "no message"}",
                calibration = helper.latestCalibrationAcquisitionResult(),
                identity = helper.activeCalibrationIdentitySummary(),
                generation = requestGeneration,
            )
            synchronized(lifecycleLock) {
                if (requestGeneration == generation && inFlightGeneration == requestGeneration) {
                    latestState = failed
                    inFlightGeneration = null
                }
            }
            return failed
        }
        return latestState
    }

    internal fun installExecutorForTests(testExecutor: Executor?) {
        executor = testExecutor ?: newExecutor()
    }

    private fun runMeasurement(
        appContext: Context,
        calibrationDir: File,
        officialFrame: OfficialProcessedF2Frame,
        measurementRoi: Rect?,
        helper: F2UsbModuleHelper,
        bridge: OfficialF2RadiometricBridge,
        requestGeneration: Long,
        sessionToken: F2SessionToken,
        requestLifecycleGuard: () -> Boolean,
    ): OfficialF2ScalarMeasurementState {
        val paletteSnapshot = try {
            requireProvedPaletteSnapshot(officialFrame.paletteSnapshot)
        } catch (error: Throwable) {
            return OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = "official_f2_palette_snapshot_unavailable_fail_closed source=${officialFrame.paletteSnapshotSource}: ${error.message ?: error.javaClass.simpleName}",
                calibration = helper.latestCalibrationAcquisitionResult(),
                identity = helper.activeCalibrationIdentitySummary(),
                generation = requestGeneration,
            )
        }
        val previewInfo = officialFrame.offlinePreviewInfoData
        if (previewInfo == null ||
            officialFrame.processedFrameNumStamp < 0 ||
            officialFrame.offlineFrameNumStamp != officialFrame.processedFrameNumStamp
        ) {
            return OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = "official_f2_offline_callback_not_associated_fail_closed processedStamp=${officialFrame.processedFrameNumStamp} offlineStamp=${officialFrame.offlineFrameNumStamp}",
                calibration = helper.latestCalibrationAcquisitionResult(),
                identity = helper.activeCalibrationIdentitySummary(),
                generation = requestGeneration,
            )
        }
        val firJpeg = try {
            requireExactRendererJpegForRadiometricMeasurement(officialFrame)
        } catch (error: Throwable) {
            return OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = error.message ?: "official_f2_renderer_jpeg_unavailable_fail_closed",
                calibration = helper.latestCalibrationAcquisitionResult(),
                identity = helper.activeCalibrationIdentitySummary(),
                generation = requestGeneration,
            )
        }

        if (!isRequestCurrent(requestGeneration, helper, sessionToken, requestLifecycleGuard)) {
            return staleSessionFailure(officialFrame, helper, sessionToken, requestGeneration, "before_command_2054")
        }
        val calibration = helper.acquireThermometryCalibrationFileOnce(calibrationDir, sessionToken)
        val identity = sessionToken.identity
        val calibrationState = calibration.provenance?.cacheState
        if (!calibration.ok || calibration.file == null) {
            return OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = "official_f2_calibration_2054_unavailable: ${calibration.reason}",
                calibration = calibration,
                identity = identity,
                generation = requestGeneration,
            )
        }

        val rawData = previewInfo.getOffByteArrRawData().takeIf { it.isNotEmpty() }
            ?: previewInfo.getByteArrRawData().takeIf { it.isNotEmpty() }
        val rawAppend = previewInfo.getOffByteArrRawAppendData().takeIf { it.isNotEmpty() }
            ?: previewInfo.getByteArrRawAppendData().takeIf { it.isNotEmpty() }
        val head = previewInfo.getByteArrHead().takeIf { it.isNotEmpty() }
        val line2 = previewInfo.getByteArrRawAppendLine2().takeIf { it.isNotEmpty() }
        if (rawData == null || rawAppend == null || head == null || line2 == null) {
            return OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = "official_f2_snapshot_incomplete raw=${rawData?.size ?: 0} rawAppend=${rawAppend?.size ?: 0} head=${head?.size ?: 0} rawAppendLine2=${line2?.size ?: 0}",
                calibration = calibration,
                identity = identity,
                generation = requestGeneration,
            )
        }
        if (!isRequestCurrent(requestGeneration, helper, sessionToken, requestLifecycleGuard)) {
            return staleSessionFailure(
                officialFrame,
                helper,
                sessionToken,
                requestGeneration,
                "before_commands_2018_2020_2080",
            )
        }
        val settingsResult = helper.acquireOfficialF2MeasurementSettingsOnce(sessionToken)
        val settings = settingsResult.settings
        if (!settingsResult.ok || settings == null || settingsResult.identityKey != identity.identityKey) {
            return OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = "official_f2_settings_unavailable_fail_closed ${settingsResult.reason} settingsIdentity=${settingsResult.identityKey} activeIdentity=${identity.identityKey}",
                calibration = calibration,
                identity = identity,
                generation = requestGeneration,
            )
        }
        val moduleSubtype = officialModuleSubtype(identity.moduleId)
        val sessionProfile = try {
            requireAuthoritativeSessionProfile(sessionToken, officialFrame.packetSize)
        } catch (error: Throwable) {
            return OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = "official_f2_session_profile_mismatch_fail_closed: ${error.message ?: error.javaClass.simpleName}",
                calibration = calibration,
                identity = identity,
                generation = requestGeneration,
            )
        }
        if (!isRequestCurrent(requestGeneration, helper, sessionToken, requestLifecycleGuard)) {
            return staleSessionFailure(officialFrame, helper, sessionToken, requestGeneration, "before_radiometric_bridge")
        }
        return try {
            val request = OfficialF2RadiometricRequest.builder()
                .firJpegData(firJpeg)
                .firJpegSize(
                    officialFrame.rendererJpegWidth.takeIf { it > 0 } ?: officialFrame.width,
                    officialFrame.rendererJpegHeight.takeIf { it > 0 } ?: officialFrame.height,
                )
                .visibleJpegData(ByteArray(0))
                .rawData(rawData)
                .rawAppendData(rawAppend)
                .callbackHead(head)
                .rawAppendLine2(line2)
                .originalSize(officialFrame.width, officialFrame.height)
                .visibleSize(officialFrame.width, officialFrame.height)
                .calibrationFile(calibration.file)
                .calibrationIdentitySerialComponent(identity.serialFileComponent)
                .agcMode(settings.agcMode)
                .maxEnvironmentTemp(settings.maxEnvironmentTemp)
                .minEnvironmentTemp(settings.minEnvironmentTemp)
                .needsNewOfflineRawPic(officialFrame.isOffStreamInfo)
                .measurementRoi(measurementRoi)
                .videoCodingType(sessionProfile.thermalCoding)
                .packetSize(officialFrame.packetSize)
                .paletteSnapshot(paletteSnapshot)
                .imageAdjustments(HashMap(settings.imageAdjustments))
                .moduleSubtype(moduleSubtype)
                .moduleIdentity(identity.toOfficialModuleIdentity())
                .forcePaletteMode14(false)
                .build()
            val result = bridge.renderAndMeasure(appContext, request)
            if (!isRequestCurrent(requestGeneration, helper, sessionToken, requestLifecycleGuard)) {
                return staleSessionFailure(
                    officialFrame,
                    helper,
                    sessionToken,
                    requestGeneration,
                    "after_radiometric_bridge",
                )
            }
            result.toState(
                frameCounter = officialFrame.frameCounter,
                calibration = calibration,
                identity = identity,
                generation = requestGeneration,
                cacheState = calibrationState,
            )
        } catch (error: Throwable) {
            OfficialF2ScalarMeasurementState.failed(
                frameCounter = officialFrame.frameCounter,
                reason = "official_f2_radiometric_measurement_failed_closed: ${error.javaClass.simpleName}: ${error.message ?: "no message"}",
                calibration = calibration,
                identity = identity,
                generation = requestGeneration,
            )
        }
    }

    fun isJpeg(candidate: ByteArray): Boolean =
        candidate.size >= 2 && candidate[0] == JPEG_SOI_0 && candidate[1] == JPEG_SOI_1

    private fun requireAuthoritativeSessionProfile(
        sessionToken: F2SessionToken,
        packetSize: Int,
    ): HikmicroF2Profile {
        val resolution = sessionToken.profileResolution
        val profile = requireNotNull(resolution?.profile) {
            "resolved session profile is required"
        }
        require(resolution.moduleId == sessionToken.identity.moduleId) {
            "profile moduleId=${resolution.moduleId} session moduleId=${sessionToken.identity.moduleId}"
        }
        require(packetSize in profile.allowedPacketSizes) {
            "packetSize=$packetSize not allowed by ${profile.officialClassName} ${profile.allowedPacketSizes}"
        }
        return profile
    }

    internal fun requireAuthoritativeSessionProfileForTests(
        sessionToken: F2SessionToken,
        packetSize: Int,
    ): HikmicroF2Profile = requireAuthoritativeSessionProfile(sessionToken, packetSize)

    private fun isRequestCurrent(
        requestGeneration: Long,
        helper: F2UsbModuleHelper,
        sessionToken: F2SessionToken,
        requestLifecycleGuard: () -> Boolean,
    ): Boolean = requestGeneration == generation &&
        helper.isSessionTokenCurrent(sessionToken) &&
        requestLifecycleGuard()

    private fun staleSessionFailure(
        officialFrame: OfficialProcessedF2Frame,
        helper: F2UsbModuleHelper,
        sessionToken: F2SessionToken,
        requestGeneration: Long,
        stage: String,
    ): OfficialF2ScalarMeasurementState = OfficialF2ScalarMeasurementState.failed(
        frameCounter = officialFrame.frameCounter,
        reason = "official_f2_measurement_session_changed_$stage",
        calibration = helper.latestCalibrationAcquisitionResult(),
        identity = sessionToken.identity,
        generation = requestGeneration,
    )

    internal fun requireExactRendererJpegForRadiometricMeasurementForTests(
        officialFrame: OfficialProcessedF2Frame,
    ): ByteArray = requireExactRendererJpegForRadiometricMeasurement(officialFrame)

    private fun requireExactRendererJpegForRadiometricMeasurement(
        officialFrame: OfficialProcessedF2Frame,
    ): ByteArray {
        val rendererProvenance = officialFrame.rendererTimestampProvenance
        val selectedStamp = officialFrame.rendererSelectedFrameNumStamp
        val targetStamp = officialFrame.offlineFrameNumStamp
        val firJpeg = officialFrame.rendererJpegData?.takeIf { isJpeg(it) }?.copyOf()
        require(
            firJpeg != null &&
                rendererProvenance == OfficialProcessedF2Frame.RendererTimestampProvenance.EXACT &&
                selectedStamp == targetStamp,
        ) {
            "official_f2_renderer_jpeg_unavailable_fail_closed targetStamp=$targetStamp selectedStamp=$selectedStamp provenance=$rendererProvenance source=${officialFrame.rendererJpegSource ?: "missing"}"
        }
        return firJpeg
    }

    @JvmStatic
    fun officialCaptureSize(moduleSubtype: OfficialF2ModuleSubtype, displayWidth: Int, displayHeight: Int): android.util.Size {
        val dimensions = officialCaptureDimensions(moduleSubtype, displayWidth, displayHeight)
        return android.util.Size(dimensions[0], dimensions[1])
    }

    internal fun officialCaptureDimensionsForTests(
        moduleSubtype: OfficialF2ModuleSubtype,
        displayWidth: Int,
        displayHeight: Int,
    ): IntArray = officialCaptureDimensions(moduleSubtype, displayWidth, displayHeight)

    private fun officialCaptureDimensions(
        moduleSubtype: OfficialF2ModuleSubtype,
        displayWidth: Int,
        displayHeight: Int,
    ): IntArray =
        if (moduleSubtype == OfficialF2ModuleSubtype.F0) {
            intArrayOf(F0_CAPTURE_WIDTH, F0_CAPTURE_HEIGHT)
        } else if (displayWidth > displayHeight) {
            intArrayOf(STANDARD_F2_PORTRAIT_CAPTURE_HEIGHT, STANDARD_F2_PORTRAIT_CAPTURE_WIDTH)
        } else {
            intArrayOf(STANDARD_F2_PORTRAIT_CAPTURE_WIDTH, STANDARD_F2_PORTRAIT_CAPTURE_HEIGHT)
        }

    internal fun requireOfficialF2CalibrationDirectory(calibrationDir: File): File {
        require(calibrationDir.name == "F2Data") {
            "official_f2_calibration_directory_must_be_F2Data path=${calibrationDir.absolutePath}"
        }
        if (!calibrationDir.exists() && !calibrationDir.mkdirs()) {
            error("unable_to_create_official_f2_calibration_directory path=${calibrationDir.absolutePath}")
        }
        require(calibrationDir.isDirectory) {
            "official_f2_calibration_path_is_not_directory path=${calibrationDir.absolutePath}"
        }
        return calibrationDir
    }

    internal fun requireProvedPaletteSnapshot(
        paletteSnapshot: OfficialF2PaletteSnapshot?,
    ): OfficialF2PaletteSnapshot {
        val snapshot = requireNotNull(paletteSnapshot) {
            "preview_manager_Q_snapshot_missing_without_null_proof"
        }
        if (!snapshot.isPresent) {
            require(snapshot.absenceProof == OfficialF2PaletteSnapshot.AbsenceProof.PREVIEW_MANAGER_Q_RETURNED_NULL) {
                "preview_manager_Q_absence_is_unproved"
            }
            return snapshot
        }

        require(snapshot.paletteMode == 1 || snapshot.paletteMode == 2) {
            "preview_manager_Q_palette_mode_unsupported mode=${snapshot.paletteMode}"
        }
        require(
            listOf(
                snapshot.maxTmp,
                snapshot.minTmp,
                snapshot.wideTempUpThreshold,
                snapshot.wideTempDownThreshold,
            ).all { it.isFinite() },
        ) {
            "preview_manager_Q_palette_contains_non_finite_values"
        }
        if (snapshot.paletteMode == 2) {
            val custom = snapshot.customPseudoColorHexArr
            require(custom != null && snapshot.customPseudoColorHexArrSize == custom.size) {
                "preview_manager_Q_custom_palette_is_incomplete"
            }
        }
        return snapshot
    }

    @JvmStatic
    fun officialModuleSubtype(moduleId: String?): OfficialF2ModuleSubtype = when (d3.c.a.a(moduleId)) {
        hik.common.yyrj.uicommon.data.ModuleType.F2ModuleType.F23 -> OfficialF2ModuleSubtype.F23
        hik.common.yyrj.uicommon.data.ModuleType.F2ModuleType.F2V2 -> OfficialF2ModuleSubtype.F2V2
        hik.common.yyrj.uicommon.data.ModuleType.F2ModuleType.F0 -> OfficialF2ModuleSubtype.F0
        else -> OfficialF2ModuleSubtype.F2
    }

    @Suppress("unused")
    internal fun settingsFromOfficialV20ForTests(
        brightness: Int,
        contrast: Int,
        enhancement: com.hcusbsdk.Interface.USB_IMAGE_ENHANCEMENT_EX,
    ): F2MeasurementSettings = F2MeasurementSettings.fromOfficialV20(brightness, contrast, enhancement)

    private fun OfficialF2RadiometricResult.toState(
        frameCounter: Long,
        calibration: F2CalibrationFileResult,
        identity: F2CalibrationIdentitySummary,
        generation: Long,
        cacheState: String?,
    ): OfficialF2ScalarMeasurementState {
        val stats = ruleTemperatureStats
        return readyState(
            frameCounter = frameCounter,
            completedElapsedMs = SystemClock.elapsedRealtime(),
            lifecycleGeneration = generation,
            calibrationCacheState = cacheState ?: calibration.provenance?.cacheState,
            calibrationIdentityKey = calibration.provenance?.identityKey ?: identity.identityKey,
            calibrationFileName = calibration.file?.name,
            measuredScope = measuredScope.name,
            maxCelsius = stats.getMaxCelsius(),
            minCelsius = stats.getMinCelsius(),
            centerCelsius = stats.getCenterCelsius(),
            averageCelsius = stats.getAverageCelsius(),
        )
    }

    internal fun readyStateForTests(
        frameCounter: Long,
        measuredScope: String,
        maxCelsius: Float,
        minCelsius: Float,
        centerCelsius: Float,
        averageCelsius: Float,
    ): OfficialF2ScalarMeasurementState = readyState(
        frameCounter = frameCounter,
        completedElapsedMs = 0L,
        lifecycleGeneration = 0L,
        calibrationCacheState = "test",
        calibrationIdentityKey = "test",
        calibrationFileName = "HM-Calibration_test.dat",
        measuredScope = measuredScope,
        maxCelsius = maxCelsius,
        minCelsius = minCelsius,
        centerCelsius = centerCelsius,
        averageCelsius = averageCelsius,
    )

    private fun readyState(
        frameCounter: Long,
        completedElapsedMs: Long,
        lifecycleGeneration: Long,
        calibrationCacheState: String?,
        calibrationIdentityKey: String?,
        calibrationFileName: String?,
        measuredScope: String,
        maxCelsius: Float?,
        minCelsius: Float?,
        centerCelsius: Float?,
        averageCelsius: Float?,
    ): OfficialF2ScalarMeasurementState {
        require(measuredScope == "FULLSCREEN" || measuredScope == "RECTANGLE") {
            "official_f2_scalar_measurement_scope_invalid scope=$measuredScope"
        }
        val finiteStats = listOf(maxCelsius, minCelsius, centerCelsius, averageCelsius)
        require(finiteStats.all { it != null && it.isFinite() }) {
            "official_f2_scalar_measurement_stats_missing_or_non_finite"
        }
        val finiteMinimum = requireNotNull(minCelsius)
        val finiteAverage = requireNotNull(averageCelsius)
        val finiteMaximum = requireNotNull(maxCelsius)
        val finiteCenter = requireNotNull(centerCelsius)
        require(finiteMinimum <= finiteAverage && finiteAverage <= finiteMaximum) {
            "official_f2_scalar_measurement_stats_unordered"
        }
        require(finiteCenter in finiteMinimum..finiteMaximum) {
            "official_f2_scalar_measurement_center_out_of_range"
        }
        return OfficialF2ScalarMeasurementState(
            status = OfficialF2ScalarMeasurementStatus.READY,
            reason = "official_f2_scalar_measurement_ready",
            frameCounter = frameCounter,
            requestedElapsedMs = null,
            completedElapsedMs = completedElapsedMs,
            lifecycleGeneration = lifecycleGeneration,
            calibrationCacheState = calibrationCacheState,
            calibrationIdentityKey = calibrationIdentityKey,
            calibrationFileName = calibrationFileName,
            measuredScope = measuredScope,
            maxCelsius = maxCelsius,
            minCelsius = minCelsius,
            centerCelsius = centerCelsius,
            averageCelsius = averageCelsius,
            fullMatrixCelsiusAvailable = false,
        )
    }

    private fun F2CalibrationIdentitySummary.toOfficialModuleIdentity(): OfficialF2ModuleIdentity =
        OfficialF2ModuleIdentity.builder()
            .moduleId(moduleId)
            .serialNumber(serialNumber)
            .deviceType("F2")
            .deviceName(deviceName)
            .firmwareVersion(firmwareVersion)
            .hardwareVersion(hardwareVersion)
            .firmwareCode(deviceId)
            .build()

    private fun newExecutor(): Executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "OfficialF2MeasurementBoundary").apply { isDaemon = true }
    }
}

enum class OfficialF2ScalarMeasurementStatus {
    IDLE,
    PENDING,
    IN_FLIGHT,
    RATE_LIMITED,
    READY,
    FAILED,
}

internal fun selectOfficialF2PublishedMeasurementState(
    currentState: OfficialF2ScalarMeasurementState,
    latestCompletedState: OfficialF2ScalarMeasurementState?,
): OfficialF2ScalarMeasurementState {
    val requestIsTransient = currentState.status == OfficialF2ScalarMeasurementStatus.PENDING ||
        currentState.status == OfficialF2ScalarMeasurementStatus.IN_FLIGHT ||
        currentState.status == OfficialF2ScalarMeasurementStatus.RATE_LIMITED
    return if (
        requestIsTransient &&
        latestCompletedState?.status == OfficialF2ScalarMeasurementStatus.READY
    ) {
        latestCompletedState
    } else {
        currentState
    }
}

data class OfficialF2ScalarMeasurementState(
    val status: OfficialF2ScalarMeasurementStatus,
    val reason: String,
    val frameCounter: Long?,
    val requestedElapsedMs: Long?,
    val completedElapsedMs: Long?,
    val lifecycleGeneration: Long?,
    val calibrationCacheState: String?,
    val calibrationIdentityKey: String?,
    val calibrationFileName: String?,
    val measuredScope: String?,
    val maxCelsius: Float?,
    val minCelsius: Float?,
    val centerCelsius: Float?,
    val averageCelsius: Float?,
    val fullMatrixCelsiusAvailable: Boolean,
) {
    companion object {
        fun idle(): OfficialF2ScalarMeasurementState = OfficialF2ScalarMeasurementState(
            status = OfficialF2ScalarMeasurementStatus.IDLE,
            reason = "official_f2_scalar_measurement_idle",
            frameCounter = null,
            requestedElapsedMs = null,
            completedElapsedMs = null,
            lifecycleGeneration = null,
            calibrationCacheState = null,
            calibrationIdentityKey = null,
            calibrationFileName = null,
            measuredScope = null,
            maxCelsius = null,
            minCelsius = null,
            centerCelsius = null,
            averageCelsius = null,
            fullMatrixCelsiusAvailable = false,
        )

        fun pending(frameCounter: Long, requestedElapsedMs: Long): OfficialF2ScalarMeasurementState =
            idle().copy(
                status = OfficialF2ScalarMeasurementStatus.PENDING,
                reason = "official_f2_scalar_measurement_pending",
                frameCounter = frameCounter,
                requestedElapsedMs = requestedElapsedMs,
            )

        fun transient(
            status: OfficialF2ScalarMeasurementStatus,
            reason: String,
            frameCounter: Long,
            requestedElapsedMs: Long,
        ): OfficialF2ScalarMeasurementState = idle().copy(
            status = status,
            reason = reason,
            frameCounter = frameCounter,
            requestedElapsedMs = requestedElapsedMs,
        )

        fun failed(
            frameCounter: Long,
            reason: String,
            calibration: F2CalibrationFileResult?,
            identity: F2CalibrationIdentitySummary?,
            generation: Long,
        ): OfficialF2ScalarMeasurementState = idle().copy(
            status = OfficialF2ScalarMeasurementStatus.FAILED,
            reason = reason,
            frameCounter = frameCounter,
            completedElapsedMs = SystemClock.elapsedRealtime(),
            lifecycleGeneration = generation,
            calibrationCacheState = calibration?.provenance?.cacheState,
            calibrationIdentityKey = calibration?.provenance?.identityKey ?: identity?.identityKey,
            calibrationFileName = calibration?.file?.name,
        )
    }
}
