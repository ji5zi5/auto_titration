package kr.auto.titration.mobile.thermal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ThermalFrameSafetyTest {
    @Test
    fun thermalRawFrameRequiresExactMatrixWhenRawValuesArePresent() {
        val tooLong = runCatching {
            ThermalRawFrameSummary(frameWidth = 2, frameHeight = 2, rawValues = intArrayOf(1, 2, 3, 4, 5))
        }.exceptionOrNull()
        val exact = ThermalRawFrameSummary(frameWidth = 2, frameHeight = 2, rawValues = intArrayOf(1, 2, 3, 4))

        assertTrue(tooLong is IllegalArgumentException)
        assertEquals(4, exact.rawValues?.size)
    }

    @Test
    fun thermalRoiRejectsNonExactRawMatrix() {
        val tooLong = ThermalRoiDetector.detect(IntArray(5) { it }, width = 2, height = 2)
        val tooShort = ThermalRoiDetector.detect(IntArray(3) { it }, width = 2, height = 2)

        assertEquals("failed", tooLong.status)
        assertEquals("thermal_raw_matrix_exact_size_required", tooLong.reason)
        assertEquals("thermal_raw_matrix_exact_size_required", tooShort.reason)
    }

    @Test
    fun celsiusFieldsRequireExistingValidationGateEvenWhenStatusClaimsCalibrated() {
        val thrown = runCatching {
            ThermalFeatureFrame(
                frameWidth = 2,
                frameHeight = 2,
                status = ThermalStatus.calibrated("claimed", "manual", "test"),
                validationEvidence = Mini2ValidationEvidence(
                    abiLoaded = true,
                    fixtureCompared = false,
                    liveStreamObserved = true,
                    meanErrorC = null,
                    maxPixelErrorC = null,
                ),
                celsiusMatrix = MatrixSummary(avg = 25.0, min = 24.0, max = 26.0),
            )
        }.exceptionOrNull()

        assertTrue(thrown is IllegalArgumentException)
    }
}
