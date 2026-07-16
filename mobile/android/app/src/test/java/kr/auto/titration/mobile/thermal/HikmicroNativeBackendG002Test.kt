package kr.auto.titration.mobile.thermal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class HikmicroNativeBackendG002Test {
    @Test
    fun f2ExplicitLoadPlanAttemptsOnlyProvedHcusbsdkCore() {
        assertEquals(setOf("libHCUSBSDK.so"), HikmicroNativeBackend.provenCoreLibrariesFor(HikmicroMini2ModuleType.F2))
        assertEquals(setOf("lib_thermal_module.so"), HikmicroNativeBackend.provenCoreLibrariesFor(HikmicroMini2ModuleType.F1))
    }

    @Test
    fun passiveNotAttemptedReportKeepsInventoryWithoutLoading() {
        val report = HikmicroNativeBackend.notAttemptedReport()
        assertEquals("not_attempted", report.loadStrategy)
        assertFalse(report.allLoaded)
        assertFalse(report.attemptedLibrariesLoaded)
        assertEquals(0, report.entries.count { it.attempted && !it.loaded })
        assertEquals(HikmicroNativeBackend.packagedLibraries.size, report.entries.count { !it.attempted && !it.loaded })
        assertFalse(report.coreLoadedFor(HikmicroMini2ModuleType.F2))
        assertTrue(report.entries.any { it.fileName == "libHCUSBSDK.so" && !it.attempted && it.loadState == "not_attempted" })
        assertTrue(report.entries.any { it.fileName == "libMTlib.so" && !it.attempted && it.loadState == "not_attempted" })
    }

    @Test
    fun f2CoreLoadedIsNotReportedAsAllLoadedWhenInventoryIsDeferred() {
        val report = f2CoreLoadedWithDeferredInventory()
        assertTrue(report.coreLoadedFor(HikmicroMini2ModuleType.F2))
        assertTrue(report.attemptedLibrariesLoaded)
        assertFalse(report.allLoaded)
        assertEquals("", report.coreMissingReasonFor(HikmicroMini2ModuleType.F2))
        assertFalse(report.coreTemperatureLoaded)
        assertEquals(0, report.entries.count { it.attempted && !it.loaded })
        assertEquals(2, report.entries.count { !it.attempted && !it.loaded })
    }

    @Test
    fun failedF2CoreIsNotRouteReadyAndJsonStaysTruthful() {
        val report = NativeLibraryLoadReport(
            entries = listOf(
                NativeLibraryLoadEntry(
                    fileName = "libHCUSBSDK.so",
                    loadName = "HCUSBSDK",
                    loaded = false,
                    error = "missing symbol",
                    loadState = "failed",
                    attempted = true,
                    role = "f2_proved_core",
                ),
                NativeLibraryLoadEntry(
                    fileName = "libuvc.so",
                    loadName = "uvc",
                    loaded = false,
                    error = "packaged_dt_needed_dependency_deferred",
                    loadState = "packaged_dt_needed_dependency_deferred",
                    attempted = false,
                    role = "f2_dt_needed_dependency",
                ),
            ),
            note = "test",
        )
        assertFalse(report.coreLoadedFor(HikmicroMini2ModuleType.F2))
        assertFalse(report.attemptedLibrariesLoaded)
        assertFalse(report.allLoaded)
        assertEquals("libHCUSBSDK.so: missing symbol", report.coreMissingReasonFor(HikmicroMini2ModuleType.F2))
        assertEquals(1, report.entries.count { it.attempted && !it.loaded })
        assertEquals(1, report.entries.count { !it.attempted && !it.loaded })
    }

    @Test
    fun failedUnprovedLibraryDoesNotBecomeF2CoreFailureButAllLoadedRemainsFalse() {
        val report = NativeLibraryLoadReport(
            entries = listOf(
                NativeLibraryLoadEntry("libHCUSBSDK.so", "HCUSBSDK", loaded = true, loadState = "loaded", attempted = true, role = "f2_proved_core"),
                NativeLibraryLoadEntry("libMicroTA_Release_v8a.so", "MicroTA_Release_v8a", loaded = false, error = "unproved failure", loadState = "failed", attempted = true, role = "packaged_deferred_inventory"),
            ),
            note = "test",
        )
        assertTrue(report.coreLoadedFor(HikmicroMini2ModuleType.F2))
        assertEquals("", report.coreMissingReasonFor(HikmicroMini2ModuleType.F2))
        assertFalse(report.attemptedLibrariesLoaded)
        assertFalse(report.allLoaded)
        assertEquals(1, report.entries.count { it.attempted && !it.loaded })
        assertEquals(0, report.entries.count { !it.attempted && !it.loaded })
    }

    @Test
    fun truthfulJsonCountsAndBooleansAreNamedInSource() {
        val source = File("src/main/java/kr/auto/titration/mobile/thermal/HikmicroNativeBackend.kt").readText()

        assertTrue(source.contains(".put(\"all_loaded\", allLoaded)"))
        assertTrue(source.contains(".put(\"attempted_libraries_loaded\", attemptedLibrariesLoaded)"))
        assertTrue(source.contains(".put(\"failed_count\", entries.count { it.attempted && !it.loaded })"))
        assertTrue(source.contains(".put(\"deferred_count\", entries.count { !it.attempted && !it.loaded })"))
        assertTrue(source.contains("val allLoaded: Boolean\n        get() = entries.isNotEmpty() && entries.all { it.loaded }"))
        assertTrue(source.contains("val attemptedLibrariesLoaded: Boolean\n        get() = entries.any { it.attempted } && entries.filter { it.attempted }.all { it.loaded }"))
    }

    private fun f2CoreLoadedWithDeferredInventory(): NativeLibraryLoadReport = NativeLibraryLoadReport(
        entries = listOf(
            NativeLibraryLoadEntry(
                fileName = "libHCUSBSDK.so",
                loadName = "HCUSBSDK",
                loaded = true,
                loadState = "loaded",
                attempted = true,
                role = "f2_proved_core",
            ),
            NativeLibraryLoadEntry(
                fileName = "libuvc.so",
                loadName = "uvc",
                loaded = false,
                error = "packaged_dt_needed_dependency_deferred",
                loadState = "packaged_dt_needed_dependency_deferred",
                attempted = false,
                role = "f2_dt_needed_dependency",
            ),
            NativeLibraryLoadEntry(
                fileName = "libMTlib.so",
                loadName = "MTlib",
                loaded = false,
                error = "packaged_deferred_not_attempted",
                loadState = "packaged_deferred_not_attempted",
                attempted = false,
                role = "packaged_deferred_inventory",
            ),
        ),
        note = "test",
    )
}
