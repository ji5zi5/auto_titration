package kr.auto.titration.mobile

import kr.auto.titration.mobile.thermal.OfficialF2ScalarMeasurementState
import kr.auto.titration.mobile.thermal.OfficialF2ScalarMeasurementStatus
import kr.auto.titration.mobile.thermal.OfficialF2MeasurementCoordinator
import kr.auto.titration.mobile.thermal.selectOfficialF2PublishedMeasurementState
import kr.auto.titration.mobile.vision.RoiMask
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class G010OfficialMeasurementBridgeTest {
    @Test
    fun measurementRectClampsMaskBboxAndFullscreenFallbackIsNull() {
        val mask = RoiMask(
            frameWidth = 4,
            frameHeight = 4,
            mask = booleanArrayOf(
                false, false, false, false,
                false, false, false, false,
                false, false, true, true,
                false, false, true, true,
            ),
            confidence = 0.9,
            source = "test",
        )

        val rect = requireNotNull(officialMeasurementRectCoordinatesForBridge(mask, frameWidth = 3, frameHeight = 3))

        assertEquals(2, rect.left)
        assertEquals(2, rect.top)
        assertEquals(3, rect.right)
        assertEquals(3, rect.bottom)
        assertNull(officialMeasurementRectCoordinatesForBridge(null, frameWidth = 256, frameHeight = 192))
        assertNull(officialMeasurementRectCoordinatesForBridge(mask, frameWidth = 0, frameHeight = 192))
    }

    @Test
    fun officialFieldsMarkExactCurrentReadyFiniteMeasurementAsCurrentFrameAndNeverMatrix() {
        val fields = officialMeasurementFieldsForBridge(
            state = readyMeasurementState(frameCounter = 42L, centerCelsius = null),
            currentRawStreamFrameCounter = 42L,
        )

        assertEquals("READY", fields.status)
        assertEquals(42L, fields.frameCounter)
        assertEquals(25.75, fields.averageCelsius!!, 0.0001)
        assertEquals(21.25, fields.minCelsius!!, 0.0001)
        assertEquals(31.5, fields.maxCelsius!!, 0.0001)
        assertNull(fields.centerCelsius)
        assertEquals("official_f2_analyzer_measurement_stats", fields.provenance)
        assertEquals("rectangle", fields.scope)
        assertTrue(fields.matchesCurrentFrame)
        assertEquals("current_frame", fields.temporalScope)
        assertEquals(0L, fields.ageFrames)
        assertFalse(fields.fullMatrixCelsiusAllowed)
    }

    @Test
    fun officialFieldsRetainStaleReadyFiniteMeasurementAsLastCompletedMeasurement() {
        val fields = officialMeasurementFieldsForBridge(
            state = readyMeasurementState(frameCounter = 42L),
            currentRawStreamFrameCounter = 45L,
        )

        assertFalse(fields.matchesCurrentFrame)
        assertEquals("last_completed_measurement", fields.temporalScope)
        assertEquals(3L, fields.ageFrames)
        assertEquals(25.75, fields.averageCelsius!!, 0.0001)
        assertEquals("rectangle", fields.scope)
        assertEquals("official_f2_analyzer_measurement_stats", fields.provenance)
        assertFalse(fields.fullMatrixCelsiusAllowed)
    }

    @Test
    fun officialFieldsFailClosedForMissingFutureAndNegativeCounters() {
        val missingCurrent = officialMeasurementFieldsForBridge(
            state = readyMeasurementState(frameCounter = 42L),
            currentRawStreamFrameCounter = null,
        )
        assertFalse(missingCurrent.matchesCurrentFrame)
        assertNull(missingCurrent.temporalScope)
        assertNull(missingCurrent.ageFrames)
        assertNull(missingCurrent.averageCelsius)
        assertNull(missingCurrent.provenance)
        assertTrue(missingCurrent.reason.contains("temporal_counter_missing"))

        val missingMeasurement = officialMeasurementFieldsForBridge(
            state = readyMeasurementState(frameCounter = null),
            currentRawStreamFrameCounter = 42L,
        )
        assertFalse(missingMeasurement.matchesCurrentFrame)
        assertNull(missingMeasurement.temporalScope)
        assertNull(missingMeasurement.ageFrames)
        assertNull(missingMeasurement.averageCelsius)
        assertNull(missingMeasurement.provenance)
        assertTrue(missingMeasurement.reason.contains("temporal_counter_missing"))

        val futureMeasurement = officialMeasurementFieldsForBridge(
            state = readyMeasurementState(frameCounter = 43L),
            currentRawStreamFrameCounter = 42L,
        )
        assertFalse(futureMeasurement.matchesCurrentFrame)
        assertNull(futureMeasurement.temporalScope)
        assertNull(futureMeasurement.ageFrames)
        assertNull(futureMeasurement.averageCelsius)
        assertNull(futureMeasurement.provenance)
        assertNull(futureMeasurement.scope)
        assertTrue(futureMeasurement.reason.contains("future_frame_mismatch"))
        assertTrue(futureMeasurement.reason.contains("measurementFrameCounter=43"))
        assertTrue(futureMeasurement.reason.contains("currentRawStreamFrameCounter=42"))

        val negativeCurrent = officialMeasurementFieldsForBridge(
            state = readyMeasurementState(frameCounter = 42L),
            currentRawStreamFrameCounter = -1L,
        )
        assertFalse(negativeCurrent.matchesCurrentFrame)
        assertNull(negativeCurrent.temporalScope)
        assertNull(negativeCurrent.ageFrames)
        assertNull(negativeCurrent.averageCelsius)
        assertNull(negativeCurrent.provenance)
        assertTrue(negativeCurrent.reason.contains("temporal_counter_invalid"))

        val negativeMeasurement = officialMeasurementFieldsForBridge(
            state = readyMeasurementState(frameCounter = -1L),
            currentRawStreamFrameCounter = 42L,
        )
        assertFalse(negativeMeasurement.matchesCurrentFrame)
        assertNull(negativeMeasurement.temporalScope)
        assertNull(negativeMeasurement.ageFrames)
        assertNull(negativeMeasurement.averageCelsius)
        assertNull(negativeMeasurement.provenance)
        assertTrue(negativeMeasurement.reason.contains("temporal_counter_invalid"))
    }

    @Test
    fun officialFieldsRejectNonReadyOrNonFiniteValues() {
        val idleFields = officialMeasurementFieldsForBridge(
            state = OfficialF2ScalarMeasurementState.idle(),
            currentRawStreamFrameCounter = 0L,
        )

        assertEquals("IDLE", idleFields.status)
        assertNull(idleFields.averageCelsius)
        assertNull(idleFields.provenance)
        assertFalse(idleFields.matchesCurrentFrame)
        assertNull(idleFields.temporalScope)
        assertNull(idleFields.ageFrames)
        assertFalse(idleFields.fullMatrixCelsiusAllowed)

        val nonFiniteFields = officialMeasurementFieldsForBridge(
            state = OfficialF2ScalarMeasurementState.idle().copy(
                status = OfficialF2ScalarMeasurementStatus.READY,
                frameCounter = 42L,
                measuredScope = "fullscreen",
                averageCelsius = Float.NaN,
                minCelsius = 20.0f,
                maxCelsius = 30.0f,
                fullMatrixCelsiusAvailable = true,
            ),
            currentRawStreamFrameCounter = 42L,
        )
        assertEquals("READY", nonFiniteFields.status)
        assertNull(nonFiniteFields.averageCelsius)
        assertNull(nonFiniteFields.minCelsius)
        assertNull(nonFiniteFields.maxCelsius)
        assertNull(nonFiniteFields.provenance)
        assertNull(nonFiniteFields.scope)
        assertFalse(nonFiniteFields.matchesCurrentFrame)
        assertNull(nonFiniteFields.temporalScope)
        assertNull(nonFiniteFields.ageFrames)
        assertFalse(nonFiniteFields.fullMatrixCelsiusAllowed)
    }

    @Test
    fun officialFieldsRejectUnorderedOrOutOfRangeStats() {
        val unordered = officialMeasurementFieldsForBridge(
            state = readyMeasurementState(frameCounter = 42L).copy(
                averageCelsius = 32.0f,
                minCelsius = 20.0f,
                maxCelsius = 30.0f,
            ),
            currentRawStreamFrameCounter = 42L,
        )
        val centerOutOfRange = officialMeasurementFieldsForBridge(
            state = readyMeasurementState(frameCounter = 42L).copy(
                centerCelsius = 35.0f,
            ),
            currentRawStreamFrameCounter = 42L,
        )

        listOf(unordered, centerOutOfRange).forEach { fields ->
            assertNull(fields.averageCelsius)
            assertNull(fields.minCelsius)
            assertNull(fields.maxCelsius)
            assertNull(fields.centerCelsius)
            assertNull(fields.provenance)
            assertFalse(fields.matchesCurrentFrame)
        }
        assertTrue(runCatching {
            OfficialF2MeasurementCoordinator.readyStateForTests(
                frameCounter = 42L,
                measuredScope = "FULLSCREEN",
                maxCelsius = 30.0f,
                minCelsius = 20.0f,
                centerCelsius = 25.0f,
                averageCelsius = 35.0f,
            )
        }.isFailure)
    }

    @Test
    fun transientFollowupRequestDoesNotEraseLastCompletedReadyMeasurement() {
        val ready = readyMeasurementState(frameCounter = 41L)
        val pending = OfficialF2ScalarMeasurementState.pending(42L, 100L)
        val inFlight = OfficialF2ScalarMeasurementState.transient(
            OfficialF2ScalarMeasurementStatus.IN_FLIGHT,
            "in_flight",
            42L,
            101L,
        )
        val rateLimited = OfficialF2ScalarMeasurementState.transient(
            OfficialF2ScalarMeasurementStatus.RATE_LIMITED,
            "rate_limited",
            42L,
            102L,
        )
        val failed = OfficialF2ScalarMeasurementState.failed(
            frameCounter = 42L,
            reason = "failed",
            calibration = null,
            identity = null,
            generation = 1L,
        )

        assertEquals(ready, selectOfficialF2PublishedMeasurementState(pending, ready))
        assertEquals(ready, selectOfficialF2PublishedMeasurementState(inFlight, ready))
        assertEquals(ready, selectOfficialF2PublishedMeasurementState(rateLimited, ready))
        assertEquals(failed, selectOfficialF2PublishedMeasurementState(failed, ready))
        assertEquals(pending, selectOfficialF2PublishedMeasurementState(pending, null))
    }

    private fun readyMeasurementState(frameCounter: Long?, centerCelsius: Float? = 27.0f) = OfficialF2ScalarMeasurementState(
        status = OfficialF2ScalarMeasurementStatus.READY,
        reason = "official_f2_scalar_measurement_ready",
        frameCounter = frameCounter,
        requestedElapsedMs = null,
        completedElapsedMs = 100L,
        lifecycleGeneration = 1L,
        calibrationCacheState = "ready",
        calibrationIdentityKey = "id",
        calibrationFileName = "F2Data.bin",
        measuredScope = "RECTANGLE",
        maxCelsius = 31.5f,
        minCelsius = 21.25f,
        centerCelsius = centerCelsius,
        averageCelsius = 25.75f,
        fullMatrixCelsiusAvailable = true,
    )
}
