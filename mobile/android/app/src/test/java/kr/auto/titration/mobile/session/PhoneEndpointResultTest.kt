package kr.auto.titration.mobile.session

import kr.auto.titration.mobile.data.ExperimentConfig
import kr.auto.titration.mobile.data.StandaloneFeatureFrame
import kr.auto.titration.mobile.export.SessionExporter
import kr.auto.titration.mobile.thermal.ThermalRawFrameSummary
import kr.auto.titration.mobile.thermal.ThermalStatus
import kr.auto.titration.mobile.vision.VisibleFeatures
import org.junit.Assert.*
import org.junit.Test

class PhoneEndpointResultTest {
    private fun stoppedRun(sampleConcentration: Double = 0.1): PhoneRunSession {
        val session = PhoneRunSession()
        session.startSetup(ExperimentConfig(experimentId = "fixture", sampleConcentrationM = sampleConcentration,
            sampleVolumeMl = 10.0, titrantConcentrationM = 0.1))
        session.markRoiLocked()
        session.startRecording(0L, 1.0)
        repeat(12) { i ->
            session.recordFrame(StandaloneFeatureFrame(
                runId = session.runId, frameId = i.toLong(), capturedElapsedNanos = i * 400_000_000L,
                visible = VisibleFeatures(2, 2, null, 10.0, 20.0, 30.0, i.toDouble(), 0.5, 0.6),
                thermalStatus = ThermalStatus.rawUnverified("fixture"),
                thermalRawFrame = ThermalRawFrameSummary(2, 2, rawValues = intArrayOf(100, 200, 300, 400)),
            ))
        }
        session.stopRecording()
        return session
    }

    @Test fun predictedConcentrationUsesStandardAndPredictedVolumeNotUnknownLabel() {
        for (label in listOf(0.1, 0.8)) {
            val s = stoppedRun(label)
            val token = s.beginFinalPrediction()
            assertTrue(s.finishFinalPrediction(token, s.runId, "available", 2.0, 0.75,
                "type_conditioned_sensor_endpoint_ranker", "fixture"))
            assertEquals(0.02, s.finalPredictionFields.getValue("sample_concentration_from_predicted_equivalence_M").toDouble(), 1e-12)
            val csv = SessionExporter.buildCsv(s.config, s.rows, s.finalPredictionFields)
            assertTrue(csv.contains("predicted_equivalence_status"))
            assertTrue(csv.contains("available"))
        }
    }

    @Test fun staleCompletionCannotWriteAnotherRun() {
        val s = stoppedRun()
        val token = s.beginFinalPrediction()
        s.startSetup(ExperimentConfig(experimentId = "new-run"))
        assertFalse(s.finishFinalPrediction(token, "fixture", "available", 2.0, 0.7,
            "type_conditioned_sensor_endpoint_ranker", "late"))
        assertTrue(s.finalPredictionFields.isEmpty())
    }

    @Test fun withheldResultHasNoInventedVolumeOrConcentration() {
        val s = stoppedRun()
        val token = s.beginFinalPrediction()
        assertTrue(s.finishFinalPrediction(token, s.runId, "withheld", null, null, "", "flat_recorded_sensor_signals"))
        assertFalse(s.finalPredictionFields.containsKey("predicted_equivalence_volume_ml"))
        assertFalse(s.finalPredictionFields.containsKey("sample_concentration_from_predicted_equivalence_M"))
    }

    @Test fun resultOutsideObservedVolumeIsRejected() {
        val s = stoppedRun(); val token = s.beginFinalPrediction()
        try {
            s.finishFinalPrediction(token, s.runId, "available", 100.0, 0.7, "type_conditioned_sensor_endpoint_ranker", "invalid")
            fail("must reject volume outside the recording")
        } catch (_: IllegalArgumentException) { }
    }

    @Test fun rawPercentilesUseLinearInterpolationLikeWindows() {
        val s = stoppedRun(); val row = s.rows.first()
        assertEquals(250.0, row.thermalRawRoiP50!!, 1e-12)
        assertEquals(385.0, row.thermalRawRoiP95!!, 1e-12)
        assertEquals("385.000000", row.toCsvMap(s.config)["thermal_raw_roi_p95"])
    }
}
