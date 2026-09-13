package kr.auto.titration.mobile.session

import kr.auto.titration.mobile.data.CsvFeatureRow
import kr.auto.titration.mobile.data.CsvSchema
import kr.auto.titration.mobile.data.ExperimentConfig
import kr.auto.titration.mobile.data.StandaloneFeatureFrame
import kr.auto.titration.mobile.pump.PumpSnapshot
import kr.auto.titration.mobile.thermal.ThermalRawFrameSummary
import kr.auto.titration.mobile.vision.RoiMask
import kotlin.math.roundToInt
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.sqrt

enum class SessionState {
    IDLE,
    SETUP,
    ROI_LOCKED,
    RECORDING,
    STOPPED,
    EXPORTED,
}

/**
 * Phone-local run state for the standalone app.
 *
 * This replaces the previous assumption that the laptop server owns run IDs,
 * recording state, CSV rows, and pump timeline.  Frames can be observed before
 * recording, but only the RECORDING state appends CSV rows.
 */
class PhoneRunSession(
    var config: ExperimentConfig = ExperimentConfig(),
) {
    val runId: String
        get() = config.experimentId
    var state: SessionState = SessionState.IDLE
        private set
    var frameCount: Long = 0
        private set
    var recordedRowCount: Int = 0
        private set
    var lastFrame: StandaloneFeatureFrame? = null
        private set
    val rows: MutableList<CsvFeatureRow> = mutableListOf()
    private var timeline: RecordingTimeline? = null
    private var predictionGeneration: Long = 0
    var finalPredictionFields: Map<String, String> = emptyMap()
        private set

    fun beginFinalPrediction(): Long {
        require(state == SessionState.STOPPED || state == SessionState.EXPORTED) { "final prediction requires stopped recording" }
        predictionGeneration += 1
        finalPredictionFields = mapOf("predicted_equivalence_status" to "pending", "predicted_equivalence_reason" to "analyzing_on_phone")
        return predictionGeneration
    }

    fun finishFinalPrediction(
        generation: Long, resultRunId: String, status: String,
        volumeMl: Double?, confidence: Double?, source: String, reason: String,
    ): Boolean {
        if (generation != predictionGeneration || resultRunId != runId ||
            (state != SessionState.STOPPED && state != SessionState.EXPORTED)) return false
        require(status in setOf("available", "withheld", "unavailable")) { "invalid endpoint result status" }
        val fields = linkedMapOf("predicted_equivalence_status" to status,
            "predicted_equivalence_reason" to reason,
            "predicted_equivalence_source" to source)
        if (status == "available") {
            require(hasEndpointObservations()) { "insufficient_or_flat_endpoint_observations" }
            require(source == "type_conditioned_sensor_endpoint_ranker") { "unexpected model source" }
            require(volumeMl != null && volumeMl.isFinite() && volumeMl > 0.0) { "invalid predicted volume" }
            require(rows.isNotEmpty() && volumeMl <= rows.maxOf { it.injectedVolumeMl } + 0.000001) { "predicted volume exceeds recorded volume" }
            require(confidence != null && confidence.isFinite() && confidence in 0.0..1.0) { "invalid model confidence" }
            fields["predicted_equivalence_volume_ml"] = volumeMl.toString()
            fields["predicted_equivalence_confidence"] = confidence.toString()
            fields["sample_concentration_from_predicted_equivalence_M"] = config.sampleConcentrationFromTitrantVolumeMl(volumeMl).toString()
            fields["predicted_equivalence_evidence"] = reason
        }
        finalPredictionFields = fields
        return true
    }

    private fun hasEndpointObservations(): Boolean {
        if (rows.size < 8 || rows.maxOf { it.timeS } - rows.minOf { it.timeS } < 3.0) return false
        if (rows.any { !it.timeS.isFinite() || it.timeS < 0 || !it.injectedVolumeMl.isFinite() || it.injectedVolumeMl < 0 }) return false
        if (rows.maxOf { it.injectedVolumeMl } <= rows.minOf { it.injectedVolumeMl }) return false
        val visible = rows.count { listOf(it.visibleHMean, it.visibleSMean, it.visibleVMean).all { v -> v != null && v.isFinite() } }
        val thermal = rows.count {
            val a = it.thermalRawRoiP50; val b = it.thermalRawRoiP95
            a != null && b != null && a.isFinite() && b.isFinite() && a > 0 && b >= a
        }
        if (visible < rows.size * 0.8 || thermal < rows.size * 0.8) return false
        val channels = listOf(rows.mapNotNull { it.visibleHMean }, rows.mapNotNull { it.visibleSMean },
            rows.mapNotNull { it.visibleVMean }, rows.mapNotNull { it.thermalRawRoiP50 }, rows.mapNotNull { it.thermalRawRoiP95 })
        return channels.any { values -> values.size > 1 && values.max() - values.min() > 1e-12 }
    }

    private var pumpSnapshot: PumpSnapshot = PumpSnapshot(
        mode = "android_manual_bluetooth",
        state = "idle",
        runRateMlPerS = 0.0,
    )
    private var thermalStreamSnapshot: ThermalStreamSnapshot = ThermalStreamSnapshot.EMPTY

    fun startSetup(config: ExperimentConfig = ExperimentConfig()) {
        this.config = config
        predictionGeneration += 1
        finalPredictionFields = emptyMap()
        frameCount = 0
        recordedRowCount = 0
        lastFrame = null
        rows.clear()
        timeline = null
        pumpSnapshot = PumpSnapshot(
            mode = "android_manual_bluetooth",
            state = "idle",
            runRateMlPerS = 0.0,
        )
        thermalStreamSnapshot = ThermalStreamSnapshot.EMPTY
        state = SessionState.SETUP
    }

    fun markRoiLocked() {
        require(state == SessionState.SETUP || state == SessionState.STOPPED) {
            "ROI can only be locked during setup or after stopping"
        }
        state = SessionState.ROI_LOCKED
    }

    fun startRecording(startedElapsedNanos: Long, pumpRateMlPerS: Double = config.pumpRunRateMlPerS) {
        require(state == SessionState.ROI_LOCKED) { "recording requires locked ROI" }
        predictionGeneration += 1
        finalPredictionFields = emptyMap()
        timeline = RecordingTimeline(startedElapsedNanos, pumpRateMlPerS)
        state = SessionState.RECORDING
    }

    fun stopRecording() {
        if (state == SessionState.RECORDING) {
            state = SessionState.STOPPED
        }
    }

    fun updatePumpSnapshot(snapshot: PumpSnapshot) {
        pumpSnapshot = snapshot
    }

    fun updateThermalStreamSnapshot(rawStreamJson: JSONObject?) {
        thermalStreamSnapshot = ThermalStreamSnapshot.fromJson(rawStreamJson)
    }

    fun markExported() {
        require(state == SessionState.STOPPED || state == SessionState.EXPORTED) {
            "export requires a stopped recording"
        }
        state = SessionState.EXPORTED
    }

    fun recordFrame(frame: StandaloneFeatureFrame): CsvFeatureRow? {
        lastFrame = frame
        frameCount += 1
        if (state != SessionState.RECORDING) {
            return null
        }
        val row = buildCsvRow(frame)
        rows += row
        recordedRowCount = rows.size
        return row
    }

    private fun buildCsvRow(frame: StandaloneFeatureFrame): CsvFeatureRow {
        val recordingTimeline = requireNotNull(timeline) { "recording timeline missing" }
        val injected = recordingTimeline.injectedVolumeMl(frame.capturedElapsedNanos)
        val distance = config.theoreticalEquivalenceVolumeMl - injected
        val concentrationFromInjected = config.sampleConcentrationFromTitrantVolumeMl(injected)
        val thermalMatrixStats = computeRawStats(frame.thermalRawFrame, mask = null)
        val thermalMaskStats = computeRawStats(frame.thermalRawFrame, frame.thermalMask)
        val storedRawRoi = frame.thermalRawFrame?.rawRoi
        val storedRawMatrix = frame.thermalRawFrame?.rawMatrix
        return CsvFeatureRow(
            schemaVersion = CsvSchema.SCHEMA_VERSION,
            experimentId = config.experimentId,
            frameId = frame.frameId,
            timeS = recordingTimeline.elapsedS(frame.capturedElapsedNanos),
            visibleTimeS = frame.timeS,
            thermalTimeS = null,
            syncOffsetMs = null,
            syncQuality = "phone_single_clock_pending_thermal",
            injectedVolumeMl = injected,
            distanceToEquivalenceMl = distance,
            pumpState = pumpSnapshot.state.ifBlank { "estimated_running" },
            pumpRateMlPerS = recordingTimeline.pumpRateMlPerS,
            pumpStepCount = pumpSnapshot.confirmedStepCount,
            pumpConfirmedStepCount = pumpSnapshot.confirmedStepCount,
            pumpFirmwareVolumeMl = pumpSnapshot.firmwareVolumeMl,
            pumpLastStatusLine = pumpSnapshot.lastStatusLine,
            visibleRMean = frame.visible?.rMean,
            visibleGMean = frame.visible?.gMean,
            visibleBMean = frame.visible?.bMean,
            visibleHMean = frame.visible?.hMean,
            visibleSMean = frame.visible?.sMean,
            visibleVMean = frame.visible?.vMean,
            visibleHsvDelta = frame.visible?.hsvDelta,
            visibleColorDelta = frame.visible?.colorDelta,
            roiShape = (frame.visibleMask ?: frame.thermalMask)?.shape ?: "rectangle",
            visibleRoiShape = frame.visibleMask?.shape ?: frame.visible?.roi?.shape ?: "rectangle",
            thermalRoiShape = frame.thermalMask?.shape ?: "rectangle",
            visibleMaskSource = frame.visibleMask?.source.orEmpty(),
            thermalMaskSource = frame.thermalMask?.source.orEmpty(),
            visibleMaskAreaPx = frame.visibleMask?.areaPx,
            visibleMaskConfidence = frame.visibleMask?.confidence,
            visibleMaskBbox = frame.visibleMask?.bboxCsvString().orEmpty(),
            visibleMaskComponentCount = frame.visibleMask?.componentCount,
            visibleMaskStability = frame.visibleMask?.stability.orEmpty(),
            thermalMaskAreaPx = frame.thermalMask?.areaPx,
            thermalMaskConfidence = frame.thermalMask?.confidence,
            thermalMaskBbox = frame.thermalMask?.bboxCsvString().orEmpty(),
            thermalMaskComponentCount = frame.thermalMask?.componentCount,
            thermalMaskStability = frame.thermalMask?.stability.orEmpty(),
            maskBbox = (frame.visibleMask ?: frame.thermalMask)?.bboxCsvString().orEmpty(),
            maskConfidence = (frame.visibleMask ?: frame.thermalMask)?.confidence,
            maskComponentCount = (frame.visibleMask ?: frame.thermalMask)?.componentCount,
            maskStability = (frame.visibleMask ?: frame.thermalMask)?.stability.orEmpty(),
            autoRoiWorkerEnabled = true,
            autoRoiResultStatus = frame.autoRoiResultStatus,
            autoRoiResultReason = frame.autoRoiResultReason,
            autoRoiDroppedPending = frame.autoRoiDroppedPending,
            csvSessionId = config.experimentId,
            csvRowIndex = rows.size + 1,
            csvRecordingElapsedS = recordingTimeline.elapsedS(frame.capturedElapsedNanos),
            pumpElapsedS = recordingTimeline.elapsedS(frame.capturedElapsedNanos),
            theoreticalEquivalenceTimeS = if (recordingTimeline.pumpRateMlPerS > 0.0) config.theoreticalEquivalenceVolumeMl / recordingTimeline.pumpRateMlPerS else null,
            timeToEquivalenceS = if (recordingTimeline.pumpRateMlPerS > 0.0) distance / recordingTimeline.pumpRateMlPerS else null,
            equivalenceWindowMl = distance,
            equivalenceWindowLabel = if (kotlin.math.abs(distance) <= 0.2) "near_equivalence" else "outside_equivalence_window",
            sampleConcentrationFromInjectedM = concentrationFromInjected,
            sampleConcentrationErrorPercent = config.sampleConcentrationErrorPercent(concentrationFromInjected),
            thermalCalibrated = frame.thermalStatus.calibrated,
            thermalConversionModel = frame.thermalStatus.conversionModel,
            thermalMatrixShape = frame.thermalRawFrame
                ?.let { "${it.frameHeight}x${it.frameWidth}" }
                .orEmpty(),
            thermalRawRoiAvg = thermalMaskStats?.avg ?: storedRawRoi?.avg,
            thermalRawRoiMin = thermalMaskStats?.min ?: storedRawRoi?.min,
            thermalRawRoiMax = thermalMaskStats?.max ?: storedRawRoi?.max,
            thermalRawMean = thermalMatrixStats?.avg ?: storedRawMatrix?.avg,
            thermalRawMin = thermalMatrixStats?.min ?: storedRawMatrix?.min,
            thermalRawMax = thermalMatrixStats?.max ?: storedRawMatrix?.max,
            thermalRawRoiStd = thermalMaskStats?.std,
            thermalRawRoiDelta = thermalMaskStats?.delta ?: storedRawRoi?.let { it.max - it.min },
            thermalRawRoiP50 = thermalMaskStats?.p50 ?: storedRawRoi?.p50,
            thermalRawRoiP95 = thermalMaskStats?.p95 ?: storedRawRoi?.p95,
            thermalRawRoiIqr = thermalMaskStats?.iqr,
            thermalRawStd = thermalMatrixStats?.std,
            thermalStatusRawJson = thermalStreamSnapshot.rawJson,
            thermalRawPacketClassification = thermalStreamSnapshot.packetClassification,
            thermalRawPacketStatus = thermalStreamSnapshot.packetStatus,
            thermalRawPacketSizeBytes = thermalStreamSnapshot.packetSizeBytes,
            thermalSelectedProfileName = thermalStreamSnapshot.selectedProfileName,
            thermalSelectedProfileSize = thermalStreamSnapshot.selectedProfileSize,
            thermalSelectedProfileFps = thermalStreamSnapshot.selectedProfileFps,
            thermalSelectedProfileCoding = thermalStreamSnapshot.selectedProfileCoding,
            thermalSelectedProfileStreamingNew = thermalStreamSnapshot.selectedProfileStreamingNew,
            thermalSelectedProfileAllowedSizes = thermalStreamSnapshot.selectedProfileAllowedSizes,
            thermalConverterProfileStatus = thermalStreamSnapshot.converterProfileStatus,
            thermalConverterValidationState = thermalStreamSnapshot.converterValidationState,
            thermalCelsiusAllowed = thermalStreamSnapshot.celsiusAllowed,
            thermalDeviceGlobalAvgC = thermalStreamSnapshot.deviceGlobalSummary?.avgC,
            thermalDeviceGlobalMinC = thermalStreamSnapshot.deviceGlobalSummary?.minC,
            thermalDeviceGlobalMaxC = thermalStreamSnapshot.deviceGlobalSummary?.maxC,
            thermalDeviceGlobalCelsiusAllowed = thermalStreamSnapshot.deviceGlobalSummary != null,
            thermalDeviceGlobalProvenance = thermalStreamSnapshot.deviceGlobalSummary?.provenance.orEmpty(),
            thermalDeviceGlobalScope = thermalStreamSnapshot.deviceGlobalSummary?.scope.orEmpty(),
            thermalDeviceGlobalRequestedDisplayUnit = thermalStreamSnapshot.deviceGlobalSummary?.requestedDisplayUnit.orEmpty(),
            thermalDeviceGlobalRequestedDisplayUnitCode = thermalStreamSnapshot.deviceGlobalSummary?.requestedDisplayUnitCode,
            thermalFullMatrixCelsiusAllowed = thermalStreamSnapshot.fullMatrixCelsiusAllowed,
            officialMeasurementStatus = thermalStreamSnapshot.officialMeasurement?.status.orEmpty(),
            officialMeasurementReason = thermalStreamSnapshot.officialMeasurement?.reason.orEmpty(),
            officialMeasurementFrameCounter = thermalStreamSnapshot.officialMeasurement?.frameCounter,
            officialTemperatureAvgC = thermalStreamSnapshot.officialMeasurement?.avgC,
            officialTemperatureMinC = thermalStreamSnapshot.officialMeasurement?.minC,
            officialTemperatureMaxC = thermalStreamSnapshot.officialMeasurement?.maxC,
            officialTemperatureCenterC = thermalStreamSnapshot.officialMeasurement?.centerC,
            officialTemperatureProvenance = thermalStreamSnapshot.officialMeasurement?.provenance.orEmpty(),
            officialTemperatureScope = thermalStreamSnapshot.officialMeasurement?.scope.orEmpty(),
            officialMeasurementMatchesCurrentFrame = thermalStreamSnapshot.officialMeasurement?.matchesCurrentFrame,
            officialMeasurementTemporalScope = thermalStreamSnapshot.officialMeasurement?.temporalScope,
            officialMeasurementAgeFrames = thermalStreamSnapshot.officialMeasurement?.ageFrames,
            officialFullMatrixCelsiusAllowed = false,
            pendingAutoCandidateRequests = frame.pendingAutoCandidateRequests,
            pendingAutoCandidateTarget = frame.pendingAutoCandidateTarget,
            warnings = buildWarnings(frame),
        )
    }

    private fun computeRawStats(frame: ThermalRawFrameSummary?, mask: RoiMask?): RawStats? {
        val rawValues = frame?.rawValues ?: return null
        val width = frame.frameWidth
        val height = frame.frameHeight
        val count = width * height
        if (width <= 0 || height <= 0 || rawValues.size < count) return null
        if (mask != null && (mask.frameWidth != width || mask.frameHeight != height)) return null

        val selected = ArrayList<Int>(if (mask == null) count else mask.areaPx.coerceAtLeast(1))
        var sum = 0.0
        var minValue = Int.MAX_VALUE
        var maxValue = Int.MIN_VALUE
        for (index in 0 until count) {
            if (mask != null && !mask.mask[index]) continue
            val value = rawValues[index]
            selected += value
            sum += value
            minValue = kotlin.math.min(minValue, value)
            maxValue = kotlin.math.max(maxValue, value)
        }
        if (selected.isEmpty()) return null
        val avg = sum / selected.size
        var variance = 0.0
        for (value in selected) {
            val delta = value - avg
            variance += delta * delta
        }
        selected.sort()
        val p50 = percentile(selected, 0.50)
        val q1 = percentile(selected, 0.25)
        val q3 = percentile(selected, 0.75)
        return RawStats(
            avg = avg,
            min = minValue.toDouble(),
            max = maxValue.toDouble(),
            std = sqrt(variance / selected.size),
            p50 = p50,
            p95 = percentile(selected, 0.95),
            iqr = q3 - q1,
            delta = (maxValue - minValue).toDouble(),
        )
    }

    private fun percentile(sortedValues: List<Int>, fraction: Double): Double {
        if (sortedValues.isEmpty()) return Double.NaN
        val index = (sortedValues.size - 1) * fraction
        val low = kotlin.math.floor(index).toInt().coerceIn(0, sortedValues.size - 1)
        val high = kotlin.math.ceil(index).toInt().coerceIn(0, sortedValues.size - 1)
        return sortedValues[low] + (sortedValues[high] - sortedValues[low]) * (index - low)
    }

    private data class RawStats(
        val avg: Double,
        val min: Double,
        val max: Double,
        val std: Double,
        val p50: Double,
        val p95: Double,
        val iqr: Double,
        val delta: Double,
    )


    private data class ThermalDeviceGlobalSummary(
        val avgC: Double,
        val minC: Double,
        val maxC: Double,
        val provenance: String,
        val scope: String,
        val requestedDisplayUnit: String,
        val requestedDisplayUnitCode: Int?,
    ) {
        companion object {
            fun fromJson(json: JSONObject): ThermalDeviceGlobalSummary? {
                if (json.optBoolean("full_matrix_celsius_allowed", false)) return null
                val summary = json.optJSONObject("device_global_summary")
                    ?: json.optJSONObject("temperature_summary")
                val provenance = firstNonBlank(
                    summary?.optCleanString("provenance"),
                    json.optCleanString("temperature_provenance"),
                    json.optCleanString("provenance"),
                )
                val scope = firstNonBlank(
                    summary?.optCleanString("scope"),
                    json.optCleanString("temperature_scope"),
                    json.optCleanString("scope"),
                )
                if (provenance != "device_global_summary" || scope != "device_global_summary") return null

                val avg = firstFiniteDouble(
                    summary?.optFiniteDouble("avg_c"),
                    summary?.optFiniteDouble("temperature_avg_c"),
                    json.optFiniteDouble("temperature_avg_c"),
                    json.optFiniteDouble("avg_c"),
                ) ?: return null
                val min = firstFiniteDouble(
                    summary?.optFiniteDouble("min_c"),
                    summary?.optFiniteDouble("temperature_min_c"),
                    json.optFiniteDouble("temperature_min_c"),
                    json.optFiniteDouble("min_c"),
                ) ?: return null
                val max = firstFiniteDouble(
                    summary?.optFiniteDouble("max_c"),
                    summary?.optFiniteDouble("temperature_max_c"),
                    json.optFiniteDouble("temperature_max_c"),
                    json.optFiniteDouble("max_c"),
                ) ?: return null
                if (min > avg || avg > max) return null

                return ThermalDeviceGlobalSummary(
                    avgC = avg,
                    minC = min,
                    maxC = max,
                    provenance = provenance,
                    scope = scope,
                    requestedDisplayUnit = firstNonBlank(
                        summary?.optCleanString("requested_display_unit"),
                        json.optCleanString("temperature_requested_display_unit"),
                        json.optCleanString("requested_display_unit"),
                    ),
                    requestedDisplayUnitCode = summary?.optIntOrNull("requested_display_unit_code")
                        ?: json.optIntOrNull("temperature_requested_display_unit_code")
                        ?: json.optIntOrNull("requested_display_unit_code"),
                )
            }

            private fun firstNonBlank(vararg values: String?): String =
                values.firstOrNull { !it.isNullOrBlank() }.orEmpty()

            private fun firstFiniteDouble(vararg values: Double?): Double? =
                values.firstOrNull { it != null && it.isFinite() }

            private fun JSONObject.optCleanString(name: String): String =
                if (has(name) && !isNull(name)) optString(name).trim() else ""

            private fun JSONObject.optFiniteDouble(name: String): Double? =
                if (has(name) && !isNull(name)) optDouble(name).takeIf { it.isFinite() } else null

            private fun JSONObject.optIntOrNull(name: String): Int? = if (has(name) && !isNull(name)) optInt(name) else null
        }
    }


    private data class OfficialMeasurementSummary(
        val status: String,
        val reason: String,
        val frameCounter: Long?,
        val avgC: Double,
        val minC: Double,
        val maxC: Double,
        val centerC: Double?,
        val provenance: String,
        val scope: String,
        val matchesCurrentFrame: Boolean,
        val temporalScope: String,
        val ageFrames: Long?,
    ) {
        companion object {
            private const val PROVENANCE = "official_f2_analyzer_measurement_stats"

            fun fromJson(json: JSONObject): OfficialMeasurementSummary? {
                val status = json.optCleanString("official_measurement_status")
                val provenance = json.optCleanString("official_temperature_provenance")
                val scope = json.optCleanString("official_temperature_scope")
                if (status != "READY" || provenance != PROVENANCE || scope !in setOf("fullscreen", "rectangle")) return null
                if (json.optBoolean("official_full_matrix_celsius_allowed", false)) return null
                val avg = json.optFiniteDouble("official_temperature_avg_c") ?: return null
                val min = json.optFiniteDouble("official_temperature_min_c") ?: return null
                val max = json.optFiniteDouble("official_temperature_max_c") ?: return null
                if (min > avg || avg > max) return null
                val center = json.optFiniteDouble("official_temperature_center_c")
                if (center != null && center !in min..max) return null
                val currentFrameCounter = json.optStrictLong("frame_counter") ?: return null
                val measurementFrameCounter =
                    json.optStrictLong("official_measurement_frame_counter") ?: return null
                if (
                    currentFrameCounter < 0L ||
                    measurementFrameCounter < 0L ||
                    measurementFrameCounter > currentFrameCounter
                ) {
                    return null
                }
                val ageFrames = currentFrameCounter - measurementFrameCounter
                val matchesCurrentFrame =
                    currentFrameCounter == measurementFrameCounter &&
                    json.optStrictBoolean("official_measurement_matches_current_frame") == true &&
                    json.optCleanString("official_measurement_temporal_scope") == "current_frame" &&
                    json.optStrictLong("official_measurement_age_frames") == 0L
                return OfficialMeasurementSummary(
                    status = status,
                    reason = json.optCleanString("official_measurement_reason"),
                    frameCounter = measurementFrameCounter,
                    avgC = avg,
                    minC = min,
                    maxC = max,
                    centerC = center,
                    provenance = provenance,
                    scope = scope,
                    matchesCurrentFrame = matchesCurrentFrame,
                    temporalScope = if (matchesCurrentFrame) "current_frame" else "last_completed_measurement",
                    ageFrames = ageFrames,
                )
            }

            private fun JSONObject.optCleanString(name: String): String =
                if (has(name) && !isNull(name)) optString(name).trim() else ""

            private fun JSONObject.optFiniteDouble(name: String): Double? =
                if (has(name) && !isNull(name)) optDouble(name).takeIf { it.isFinite() } else null

            private fun JSONObject.optStrictBoolean(name: String): Boolean? =
                if (has(name) && !isNull(name)) opt(name) as? Boolean else null

            private fun JSONObject.optStrictLong(name: String): Long? {
                if (!has(name) || isNull(name)) return null
                return when (val value = opt(name)) {
                    is Byte -> value.toLong()
                    is Short -> value.toLong()
                    is Int -> value.toLong()
                    is Long -> value
                    is Float -> value.toExactLongOrNull()
                    is Double -> value.toExactLongOrNull()
                    is String -> value.trim().toLongOrNull()
                    else -> null
                }
            }

            private fun Number.toExactLongOrNull(): Long? {
                val doubleValue = toDouble()
                if (!doubleValue.isFinite()) return null
                val longValue = toLong()
                return longValue.takeIf { it.toDouble() == doubleValue }
            }
        }
    }

    private data class ThermalStreamSnapshot(
        val rawJson: String,
        val packetClassification: String,
        val packetStatus: String,
        val packetSizeBytes: Int?,
        val selectedProfileName: String,
        val selectedProfileSize: String,
        val selectedProfileFps: Int?,
        val selectedProfileCoding: Int?,
        val selectedProfileStreamingNew: Boolean?,
        val selectedProfileAllowedSizes: String,
        val converterProfileStatus: String,
        val converterValidationState: String,
        val celsiusAllowed: Boolean,
        val deviceGlobalSummary: ThermalDeviceGlobalSummary?,
        val fullMatrixCelsiusAllowed: Boolean,
        val officialMeasurement: OfficialMeasurementSummary?,
    ) {
        companion object {
            val EMPTY = ThermalStreamSnapshot(
                rawJson = "",
                packetClassification = "",
                packetStatus = "",
                packetSizeBytes = null,
                selectedProfileName = "",
                selectedProfileSize = "",
                selectedProfileFps = null,
                selectedProfileCoding = null,
                selectedProfileStreamingNew = null,
                selectedProfileAllowedSizes = "",
                converterProfileStatus = "",
                converterValidationState = "",
                celsiusAllowed = false,
                deviceGlobalSummary = null,
                fullMatrixCelsiusAllowed = false,
                officialMeasurement = null,
            )

            fun fromJson(rawStreamJson: JSONObject?): ThermalStreamSnapshot {
                val json = rawStreamJson ?: return EMPTY
                val selectedProfile = json.optJSONObject("selected_profile")
                val validationState = json.optJSONObject("converter_validation_state")
                val deviceGlobalSummary = ThermalDeviceGlobalSummary.fromJson(json)
                val officialMeasurement = OfficialMeasurementSummary.fromJson(json)
                return ThermalStreamSnapshot(
                    rawJson = json.toString(),
                    packetClassification = json.optString("packet_classification"),
                    packetStatus = json.optString("packet_status"),
                    packetSizeBytes = json.optIntOrNull("packet_size_bytes"),
                    selectedProfileName = selectedProfile?.optString("name").orEmpty().ifBlank { json.optString("selected_profile_name") },
                    selectedProfileSize = selectedProfile?.optString("size").orEmpty().ifBlank { json.optString("selected_profile_size") },
                    selectedProfileFps = selectedProfile?.optIntOrNull("fps") ?: json.optIntOrNull("selected_profile_fps"),
                    selectedProfileCoding = selectedProfile?.optIntOrNull("coding") ?: json.optIntOrNull("selected_profile_coding"),
                    selectedProfileStreamingNew = selectedProfile?.optBooleanOrNull("streamingNew") ?: json.optBooleanOrNull("selected_profile_streamingNew"),
                    selectedProfileAllowedSizes = (selectedProfile?.optJSONArray("allowed_packet_sizes") ?: json.optJSONArray("selected_profile_allowed_sizes")).csvString(),
                    converterProfileStatus = json.optString("converter_profile_status"),
                    converterValidationState = validationState?.toString().orEmpty(),
                    celsiusAllowed = officialMeasurement?.matchesCurrentFrame == true,
                    deviceGlobalSummary = deviceGlobalSummary,
                    fullMatrixCelsiusAllowed = false,
                    officialMeasurement = officialMeasurement,
                )
            }

            private fun JSONObject.optIntOrNull(name: String): Int? = if (has(name) && !isNull(name)) optInt(name) else null

            private fun JSONObject.optBooleanOrNull(name: String): Boolean? = if (has(name) && !isNull(name)) optBoolean(name) else null

            private fun JSONArray?.csvString(): String {
                if (this == null) return ""
                return (0 until length()).joinToString(";") { index -> opt(index).toString() }
            }
        }
    }

    private fun buildWarnings(frame: StandaloneFeatureFrame): String {
        val warnings = mutableListOf("injected_volume_timeline_estimate")
        if (pumpSnapshot.firmwareVolumeMl == null) {
            warnings += "pump_firmware_volume_absent"
        }
        if (!frame.thermalStatus.calibrated) {
            warnings += "thermal_not_calibrated"
        }
        return warnings.joinToString(";")
    }
}
