package kr.auto.titration.mobile.thermal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HikmicroF2ProfileTest {
    @Test
    fun officialVidPidRoutingMatchesViewerBoundaries() {
        assertEquals(HikmicroMini2ModuleType.F1, HikmicroMini2ModuleType.classify(11231, 320))
        assertEquals(HikmicroMini2ModuleType.F2, HikmicroMini2ModuleType.classify(11231, 257))
        assertEquals(HikmicroMini2ModuleType.F2, HikmicroMini2ModuleType.classify(11231, 258))
        assertEquals(HikmicroMini2ModuleType.F2, HikmicroMini2ModuleType.classify(8367, 0))

        assertEquals(HikmicroMini2ModuleType.UNSUPPORTED, HikmicroMini2ModuleType.classify(11231, 319))
        assertEquals(HikmicroMini2ModuleType.UNSUPPORTED, HikmicroMini2ModuleType.classify(8368, 258))
    }

    @Test
    fun module356FirmwareDateBoundariesResolveOfficialProfiles() {
        assertProfile(
            expectedClass = "f3.i",
            expectedSize = HikmicroF2Size(192, 520),
            expectedFps = 25,
            expectedCoding = 8,
            expectedStreamingNew = false,
            expectedAllowedPacketSizes = setOf(102944),
            resolution = HikmicroF2ProfileResolver.resolve("0953560101", "APP_010203_20221121"),
        )
        assertProfile(
            expectedClass = "f3.f",
            expectedSize = HikmicroF2Size(192, 520),
            expectedFps = 25,
            expectedCoding = 11,
            expectedStreamingNew = true,
            expectedAllowedPacketSizes = setOf(206392),
            resolution = HikmicroF2ProfileResolver.resolve("0953560104", "APP_010203_20221122"),
        )
        assertProfile(
            expectedClass = "f3.f",
            expectedSize = HikmicroF2Size(192, 520),
            expectedFps = 25,
            expectedCoding = 11,
            expectedStreamingNew = true,
            expectedAllowedPacketSizes = setOf(206392),
            resolution = HikmicroF2ProfileResolver.resolve("0953560105", "APP_010203_20231115"),
        )
        assertProfile(
            expectedClass = "f3.g",
            expectedSize = HikmicroF2Size(256, 344),
            expectedFps = 25,
            expectedCoding = 12,
            expectedStreamingNew = true,
            expectedAllowedPacketSizes = setOf(101320, 183496, 98304),
            resolution = HikmicroF2ProfileResolver.resolve("0953560101", "APP_010203_20231116"),
        )
        assertProfile(
            expectedClass = "f3.g",
            expectedSize = HikmicroF2Size(256, 344),
            expectedFps = 25,
            expectedCoding = 12,
            expectedStreamingNew = true,
            expectedAllowedPacketSizes = setOf(101320, 183496, 98304),
            resolution = HikmicroF2ProfileResolver.resolve("0953560104", "APP_010203_20231229"),
        )
        assertProfile(
            expectedClass = "f3.h",
            expectedSize = HikmicroF2Size(256, 344),
            expectedFps = 25,
            expectedCoding = 12,
            expectedStreamingNew = true,
            expectedAllowedPacketSizes = setOf(101320, 183496, 98304),
            resolution = HikmicroF2ProfileResolver.resolve("0953560105", "APP_010203_20231230"),
        )
    }

    @Test
    fun module351FirmwareDateBoundariesResolveOfficialProfiles() {
        assertProfile(
            expectedClass = "f3.c",
            expectedSize = HikmicroF2Size(288, 776),
            expectedFps = 50,
            expectedCoding = 11,
            expectedStreamingNew = true,
            expectedAllowedPacketSizes = setOf(453688),
            resolution = HikmicroF2ProfileResolver.resolve("0953510000", "APP_010203_20231116"),
        )
        assertProfile(
            expectedClass = "f3.d",
            expectedSize = HikmicroF2Size(384, 512),
            expectedFps = 50,
            expectedCoding = 12,
            expectedStreamingNew = true,
            expectedAllowedPacketSizes = setOf(193480, 400584, 221184),
            resolution = HikmicroF2ProfileResolver.resolve("0953510100", "APP_010203_20231117"),
        )
        assertProfile(
            expectedClass = "f3.d",
            expectedSize = HikmicroF2Size(384, 512),
            expectedFps = 50,
            expectedCoding = 12,
            expectedStreamingNew = true,
            expectedAllowedPacketSizes = setOf(193480, 400584, 221184),
            resolution = HikmicroF2ProfileResolver.resolve("0953510000", "APP_010203_20231229"),
        )
        assertProfile(
            expectedClass = "f3.e",
            expectedSize = HikmicroF2Size(384, 512),
            expectedFps = 50,
            expectedCoding = 12,
            expectedStreamingNew = true,
            expectedAllowedPacketSizes = setOf(193480, 400584, 221184),
            resolution = HikmicroF2ProfileResolver.resolve("0953510100", "APP_010203_20231230"),
        )
    }

    @Test
    fun dateIndependentModuleFamiliesResolveWithoutUsingUniversalDefaults() {
        assertProfile(
            expectedClass = "f3.j",
            expectedSize = HikmicroF2Size(256, 344),
            expectedFps = 25,
            expectedCoding = 12,
            expectedStreamingNew = true,
            expectedAllowedPacketSizes = setOf(203720, 183496),
            resolution = HikmicroF2ProfileResolver.resolve("0953060001", "APP_010203_20200101"),
        )
        assertProfile(
            expectedClass = "f3.b",
            expectedSize = HikmicroF2Size(96, 176),
            expectedFps = 25,
            expectedCoding = 12,
            expectedStreamingNew = true,
            expectedAllowedPacketSizes = setOf(61384, 41160),
            resolution = HikmicroF2ProfileResolver.resolve("0953080000", "APP_010203_20260714"),
        )
    }

    @Test
    fun unresolvedInputsReturnExplicitUnresolvedResults() {
        assertUnresolved("module_id_missing", HikmicroF2ProfileResolver.resolve(" ", "APP_010203_20231230"))
        assertUnresolved("firmware_date_unresolved", HikmicroF2ProfileResolver.resolve("0953560101", "20231230"))
        assertUnresolved("firmware_date_unresolved", HikmicroF2ProfileResolver.resolve("0953560101", "APP_010203_notadate"))
        assertUnresolved("unsupported_module_id", HikmicroF2ProfileResolver.resolve("0953560102", "APP_010203_20231230"))
    }

    @Test
    fun officialD3ModuleIdGroupsAreCompleteAndNonSelectorFamiliesStayUnresolved() {
        assertEquals(setOf("0953560101", "0953560104", "0953560105"), HikmicroF2ProfileResolver.officialModuleIdGroups["b"])
        assertEquals(setOf("0953510000", "0953510100"), HikmicroF2ProfileResolver.officialModuleIdGroups["c"])
        assertEquals(setOf("0953060001", "0953060002"), HikmicroF2ProfileResolver.officialModuleIdGroups["d"])
        assertEquals(setOf("0953080000"), HikmicroF2ProfileResolver.officialModuleIdGroups["e"])
        assertEquals(setOf("0953560101", "0953560105", "0953060002"), HikmicroF2ProfileResolver.officialModuleIdGroups["f"])
        assertEquals(setOf("0953510000", "0953510100"), HikmicroF2ProfileResolver.officialModuleIdGroups["g"])
        assertEquals(setOf("0953560102", "0953560103"), HikmicroF2ProfileResolver.officialModuleIdGroups["h"])
        assertEquals(setOf("0951710000"), HikmicroF2ProfileResolver.officialModuleIdGroups["i"])

        for (moduleId in setOf("0953560102", "0953560103", "0951710000")) {
            assertUnresolved(
                "unsupported_module_id",
                HikmicroF2ProfileResolver.resolve(moduleId, "APP_010203_20231230"),
            )
        }
    }

    private fun assertProfile(
        expectedClass: String,
        expectedSize: HikmicroF2Size,
        expectedFps: Int,
        expectedCoding: Int,
        expectedStreamingNew: Boolean,
        expectedAllowedPacketSizes: Set<Int>,
        resolution: HikmicroF2ProfileResolution,
    ) {
        assertTrue(resolution.reason, resolution.isResolved)
        val profile = resolution.profile ?: error("expected resolved profile")
        assertEquals(expectedClass, profile.officialClassName)
        assertEquals(expectedSize, profile.previewSize)
        assertEquals(expectedFps, profile.fps)
        assertEquals(expectedCoding, profile.thermalCoding)
        assertEquals(expectedStreamingNew, profile.streamingNew)
        assertEquals(expectedAllowedPacketSizes, profile.allowedPacketSizes)
    }

    private fun assertUnresolved(expectedReason: String, resolution: HikmicroF2ProfileResolution) {
        assertFalse(resolution.reason, resolution.isResolved)
        assertNull(resolution.profile)
        assertEquals(expectedReason, resolution.reason)
    }
}
