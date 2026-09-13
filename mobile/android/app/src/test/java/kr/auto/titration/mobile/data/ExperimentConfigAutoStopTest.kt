package kr.auto.titration.mobile.data

import org.junit.Assert.assertThrows
import org.junit.Test

class ExperimentConfigAutoStopTest {
    @Test
    fun androidAcceptsRecordingConfigOnlyWhenUnsupportedAutomationIsDisabled() {
        ExperimentConfig.requireAndroidAutoStopDisabled(
            autoStopEnabled = false,
            pulseEnabled = false,
        )
    }

    @Test
    fun androidRejectsAutoStopActivation() {
        assertThrows(IllegalArgumentException::class.java) {
            ExperimentConfig.requireAndroidAutoStopDisabled(
                autoStopEnabled = true,
                pulseEnabled = false,
            )
        }
    }

    @Test
    fun androidRejectsPulseActivation() {
        assertThrows(IllegalArgumentException::class.java) {
            ExperimentConfig.requireAndroidAutoStopDisabled(
                autoStopEnabled = false,
                pulseEnabled = true,
            )
        }
    }
}
