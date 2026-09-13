package kr.auto.titration.mobile.thermal

import com.hik.f2module.F2UsbModuleApi
import com.hik.f2module.F2CalibrationIdentitySummary
import com.hik.f2module.F2SessionToken
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
    fun mismatchedPublicOverridesAreRejectedEvenAfterProfileResolved() {
        val resolution = HikmicroF2ProfileResolver.resolve("0953060001", "APP_010203_20200101")

        val result = F2UsbModuleApi.resolveStartConfig(
            resolution = resolution,
            streamingNewOverride = false,
            frameRateOverride = 15,
            videoCodingTypeOverride = 8,
            previewSizeValueOverride = HikmicroF2Size(192, 520),
        )

        assertFalse(result.ok)
        assertNull(result.config)
        assertTrue(result.reason.contains("profile_override_mismatch"))
        assertTrue(result.reason.contains("streamingNew=false expected=true"))
        assertTrue(result.reason.contains("frameRate=15 expected=25"))
        assertTrue(result.reason.contains("videoCodingType=8 expected=12"))
        assertTrue(result.reason.contains("previewSizeValue=192x520 expected=256x344"))
        assertTrue(result.toStartResult("open_ok").stageReport.contains("USB_SET_VIDEO_PARAM=not_run"))
    }

    @Test
    fun exactProfileOverridesPreserveValidF3JStart() {
        val resolution = HikmicroF2ProfileResolver.resolve("0953060001", "APP_010203_20200101")

        val result = F2UsbModuleApi.resolveStartConfig(
            resolution = resolution,
            streamingNewOverride = true,
            frameRateOverride = 25,
            videoCodingTypeOverride = 12,
            previewSizeValueOverride = HikmicroF2Size(256, 344),
        )

        assertTrue(result.reason, result.ok)
        val config = result.config ?: error("expected config")
        assertEquals("f3.j", config.profileClass)
        assertEquals(256, config.previewSizeValue.width)
        assertEquals(344, config.previewSizeValue.height)
        assertEquals(25, config.frameRate)
        assertEquals(12, config.videoCodingType)
        assertEquals(true, config.streamingNew)
        assertEquals(setOf(203720, 183496), config.allowedPacketSizes)
    }

    @Test
    fun measurementRequiresPacketFromTheSessionProfilesAllowedSet() {
        val resolution = HikmicroF2ProfileResolver.resolve("0953060001", "APP_010203_20200101")
        val token = F2SessionToken(
            generation = 1,
            userId = 2,
            identity = F2CalibrationIdentitySummary(
                identityKey = "identity",
                serialFileComponent = "serial",
                serialNumber = "serial",
                moduleId = "0953060001",
                firmwareVersion = "APP_010203_20200101",
                hardwareVersion = "HW",
                deviceId = "device",
                deviceName = "Mini2",
                vid = 1,
                pid = 2,
            ),
            profileResolution = resolution,
        )

        assertEquals(
            "f3.j",
            OfficialF2MeasurementCoordinator
                .requireAuthoritativeSessionProfileForTests(token, 203720)
                .officialClassName,
        )
        val error = runCatching {
            OfficialF2MeasurementCoordinator
                .requireAuthoritativeSessionProfileForTests(token, 101320)
        }.exceptionOrNull()
        assertTrue(error is IllegalArgumentException)
        assertTrue(error?.message.orEmpty().contains("not allowed by f3.j"))

        val mismatchedProfileToken = token.copy(
            profileResolution = resolution.copy(moduleId = "0953060002"),
        )
        val profileError = runCatching {
            OfficialF2MeasurementCoordinator
                .requireAuthoritativeSessionProfileForTests(mismatchedProfileToken, 203720)
        }.exceptionOrNull()
        assertTrue(profileError is IllegalArgumentException)
        assertTrue(profileError?.message.orEmpty().contains("profile moduleId=0953060002"))
    }
}
