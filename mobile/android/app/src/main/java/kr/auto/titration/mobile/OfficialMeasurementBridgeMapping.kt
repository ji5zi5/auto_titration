package kr.auto.titration.mobile

import java.util.Locale
import kr.auto.titration.mobile.thermal.OfficialF2ScalarMeasurementState
import kr.auto.titration.mobile.thermal.OfficialF2ScalarMeasurementStatus
import kr.auto.titration.mobile.vision.RoiMask

internal const val OFFICIAL_F2_MEASUREMENT_STATS_PROVENANCE =
    "official_f2_analyzer_measurement_stats"

internal data class OfficialMeasurementRectCoordinates(
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
)

internal fun officialMeasurementRectCoordinatesForBridge(
    mask: RoiMask?,
    frameWidth: Int,
    frameHeight: Int,
): OfficialMeasurementRectCoordinates? {
    if (mask == null || frameWidth <= 0 || frameHeight <= 0) return null
    val bbox = mask.bbox
    val left = bbox.x.coerceIn(0, frameWidth - 1)
    val top = bbox.y.coerceIn(0, frameHeight - 1)
    return OfficialMeasurementRectCoordinates(
        left = left,
        top = top,
        right = (bbox.x + bbox.width).coerceIn(left + 1, frameWidth),
        bottom = (bbox.y + bbox.height).coerceIn(top + 1, frameHeight),
    )
}

internal data class OfficialMeasurementBridgeFields(
    val status: String,
    val reason: String,
    val frameCounter: Long?,
    val averageCelsius: Double?,
    val minCelsius: Double?,
    val maxCelsius: Double?,
    val centerCelsius: Double?,
    val provenance: String?,
    val scope: String?,
    val matchesCurrentFrame: Boolean,
    val temporalScope: String?,
    val ageFrames: Long?,
    val fullMatrixCelsiusAllowed: Boolean,
)

internal fun officialMeasurementFieldsForBridge(
    state: OfficialF2ScalarMeasurementState,
    currentRawStreamFrameCounter: Long?,
): OfficialMeasurementBridgeFields {
    val average = state.averageCelsius?.toDouble()?.takeIf { it.isFinite() }
    val minimum = state.minCelsius?.toDouble()?.takeIf { it.isFinite() }
    val maximum = state.maxCelsius?.toDouble()?.takeIf { it.isFinite() }
    val center = state.centerCelsius?.toDouble()?.takeIf { it.isFinite() }
    val scope = normalizedOfficialMeasurementScope(state.measuredScope)
    val readyFinite = state.status == OfficialF2ScalarMeasurementStatus.READY &&
        average != null && minimum != null && maximum != null && scope != null &&
        minimum <= average && average <= maximum &&
        (center == null || center in minimum..maximum)
    val measurementFrameCounter = state.frameCounter
    val temporalFailureReason = when {
        !readyFinite -> null
        currentRawStreamFrameCounter == null || measurementFrameCounter == null ->
            "official_measurement_temporal_counter_missing " +
                "currentRawStreamFrameCounter=$currentRawStreamFrameCounter " +
                "measurementFrameCounter=$measurementFrameCounter"
        currentRawStreamFrameCounter < 0L || measurementFrameCounter < 0L ->
            "official_measurement_temporal_counter_invalid " +
                "currentRawStreamFrameCounter=$currentRawStreamFrameCounter " +
                "measurementFrameCounter=$measurementFrameCounter"
        measurementFrameCounter > currentRawStreamFrameCounter ->
            "official_measurement_future_frame_mismatch " +
                "measurementFrameCounter=$measurementFrameCounter " +
                "currentRawStreamFrameCounter=$currentRawStreamFrameCounter"
        else -> null
    }
    val publishableReady = readyFinite && temporalFailureReason == null
    val ageFrames = if (publishableReady) {
        requireNotNull(currentRawStreamFrameCounter) - requireNotNull(measurementFrameCounter)
    } else {
        null
    }
    val matchesCurrentFrame = publishableReady && ageFrames == 0L
    val temporalScope = when {
        !publishableReady -> null
        matchesCurrentFrame -> "current_frame"
        else -> "last_completed_measurement"
    }
    return OfficialMeasurementBridgeFields(
        status = state.status.name,
        reason = temporalFailureReason ?: state.reason,
        frameCounter = state.frameCounter,
        averageCelsius = average.takeIf { publishableReady },
        minCelsius = minimum.takeIf { publishableReady },
        maxCelsius = maximum.takeIf { publishableReady },
        centerCelsius = center.takeIf { publishableReady },
        provenance = OFFICIAL_F2_MEASUREMENT_STATS_PROVENANCE.takeIf { publishableReady },
        scope = scope.takeIf { publishableReady },
        matchesCurrentFrame = matchesCurrentFrame,
        temporalScope = temporalScope,
        ageFrames = ageFrames,
        fullMatrixCelsiusAllowed = false,
    )
}

private fun normalizedOfficialMeasurementScope(scope: String?): String? {
    return when (scope?.trim()?.lowercase(Locale.US)) {
        "fullscreen", "full_screen", "fullframe", "full_frame" -> "fullscreen"
        "rectangle", "rect", "roi", "measurement_roi" -> "rectangle"
        else -> null
    }
}
