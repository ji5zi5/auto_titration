package kr.auto.titration.mobile.thermal

import com.hik.f2module.F2UsbModuleApi
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HikmicroF2ProfileWiringTest {
    @Test
    fun productionStartConfigRefusesUnresolvedProfileInsteadOfUniversalDefaults() {
        val unresolved = HikmicroF2ProfileResolution(
            profile = null,
            moduleId = "0953560102",
            firmwareDate = 20231230,
            reason = "unsupported_module_id",
        )

        val result = F2UsbModuleApi.resolveStartConfig(unresolved)

        assertFalse(result.ok)
        assertNull(result.config)
        assertEquals(unresolved, result.profileResolution)
        assertTrue(result.reason.contains("profile_unresolved"))
        assertTrue(result.toStartResult("open_ok").stageReport.contains("USB_SET_VIDEO_PARAM=not_run"))
    }

    @Test
    fun productionStartConfigUsesResolvedOfficialProfileFields() {
        val resolution = HikmicroF2ProfileResolver.resolve("0953510100", "APP_010203_20231230")

        val result = F2UsbModuleApi.resolveStartConfig(resolution)

        assertTrue(result.reason, result.ok)
        val config = result.config ?: error("expected config")
        assertEquals("f3.e", config.profileClass)
        assertEquals(384, config.previewSizeValue.width)
        assertEquals(512, config.previewSizeValue.height)
        assertEquals(50, config.frameRate)
        assertEquals(12, config.videoCodingType)
        assertEquals(true, config.streamingNew)
        assertEquals(setOf(193480, 400584, 221184), config.allowedPacketSizes)
    }

    @Test
    fun explicitOverridesAreAllowedOnlyAfterProfileResolved() {
        val resolution = HikmicroF2ProfileResolver.resolve("0953060001", "APP_010203_20200101")

        val result = F2UsbModuleApi.resolveStartConfig(
            resolution = resolution,
            streamingNewOverride = false,
            frameRateOverride = 15,
            videoCodingTypeOverride = 8,
            previewSizeValueOverride = HikmicroF2Size(192, 520),
        )

        assertTrue(result.ok)
        val config = result.config ?: error("expected config")
        assertEquals("f3.j", config.profileClass)
        assertEquals(192, config.previewSizeValue.width)
        assertEquals(520, config.previewSizeValue.height)
        assertEquals(15, config.frameRate)
        assertEquals(8, config.videoCodingType)
        assertEquals(false, config.streamingNew)
        assertEquals(setOf(203720, 183496), config.allowedPacketSizes)
    }
}
