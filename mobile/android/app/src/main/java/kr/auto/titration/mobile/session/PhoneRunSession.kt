package kr.auto.titration.mobile.session

import kr.auto.titration.mobile.data.CsvFeatureRow
import kr.auto.titration.mobile.data.CsvSchema
import kr.auto.titration.mobile.data.ExperimentConfig
import kr.auto.titration.mobile.data.StandaloneFeatureFrame
import kr.auto.titration.mobile.pump.PumpSnapshot
import kr.auto.titration.mobile.thermal.ThermalRawFrameSummary
import kr.auto.titration.mobile.vision.RoiMask
import kotlin.math.roundToInt
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
    private var pumpSnapshot: PumpSnapshot = PumpSnapshot(
        mode = "android_manual_bluetooth",
        state = "idle",
        runRateMlPerS = 0.0,
    )

    fun startSetup(config: ExperimentConfig = ExperimentConfig()) {
        this.config = config
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
        val fallbackRawRoi = frame.thermalRawFrame?.rawRoi
        val fallbackRawMatrix = frame.thermalRawFrame?.rawMatrix
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
            thermalRawRoiAvg = thermalMaskStats?.avg ?: fallbackRawRoi?.avg,
            thermalRawRoiMin = thermalMaskStats?.min ?: fallbackRawRoi?.min,
            thermalRawRoiMax = thermalMaskStats?.max ?: fallbackRawRoi?.max,
            thermalRawMean = thermalMatrixStats?.avg ?: fallbackRawMatrix?.avg,
            thermalRawMin = thermalMatrixStats?.min ?: fallbackRawMatrix?.min,
            thermalRawMax = thermalMatrixStats?.max ?: fallbackRawMatrix?.max,
            thermalRawRoiStd = thermalMaskStats?.std,
            thermalRawRoiDelta = thermalMaskStats?.delta ?: fallbackRawRoi?.let { it.max - it.min },
            thermalRawRoiP50 = thermalMaskStats?.p50 ?: fallbackRawRoi?.p50,
            thermalRawRoiIqr = thermalMaskStats?.iqr,
            thermalRawStd = thermalMatrixStats?.std,
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
            iqr = q3 - q1,
            delta = (maxValue - minValue).toDouble(),
        )
    }

    private fun percentile(sortedValues: List<Int>, fraction: Double): Double {
        if (sortedValues.isEmpty()) return Double.NaN
        val index = ((sortedValues.size - 1) * fraction).roundToInt().coerceIn(0, sortedValues.size - 1)
        return sortedValues[index].toDouble()
    }

    private data class RawStats(
        val avg: Double,
        val min: Double,
        val max: Double,
        val std: Double,
        val p50: Double,
        val iqr: Double,
        val delta: Double,
    )

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
