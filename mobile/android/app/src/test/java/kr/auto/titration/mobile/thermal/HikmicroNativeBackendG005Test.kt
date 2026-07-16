package kr.auto.titration.mobile.thermal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HikmicroNativeBackendG005Test {
    @Test
    fun officialRouteLibraryInventoryAndRolesStayPinned() {
        assertEquals(
            listOf(
                "libc++_shared.so",
                "libjpeg.so",
                "libcrypto.so",
                "libusb-1.0.so",
                "libusb1.0.so",
                "libuvc.so",
                "libusbCam_host.so",
                "libjnidispatch.so",
                "libhikdsp.so",
                "libdadsp.so",
                "libAnalyzeData.so",
                "libFormatConversion.so",
                "libifrgisp.so",
                "libColorAlarm_PcProc.so",
                "libtvf.so",
                "libtsr_v2.0.0.so",
                "libacnn_v2.3.4.so",
                "libomp.so",
                "libxml2.so",
                "libMicroSecurityKit_Release_v8a.so",
                "libMicroParallel_Release_v8a.so",
                "libMicroDriver_Release_v8a.so",
                "libMicroDM_Release_v8a.so",
                "libMicroMC_Release_v8a.so",
                "libMicroRVP_Release_v8a.so",
                "libMicroRVR_Release_v8a.so",
                "libMicroJPEG_Release_v8a.so",
                "libMicroIA_Release_v8a.so",
                "libMicroJITA_Release_v8a.so",
                "libMicroTA_Release_v8a.so",
                "libMTlib.so",
                "libHwCodecer.so",
                "libThermalPlayCtrl.so",
                "libOfflinePic.so",
                "libOffline_Pic.so",
                "lib_thermal_module.so",
                "libRID_ANDROID_V1.0.6_BUILD_20250312.so",
                "libanalyzer_rid.so",
                "libHCUSBSDK.so",
            ),
            HikmicroNativeBackend.packagedLibraries,
        )
        assertEquals(setOf("libHCUSBSDK.so"), HikmicroNativeBackend.provenCoreLibrariesFor(HikmicroMini2ModuleType.F2))
        assertEquals(setOf("lib_thermal_module.so"), HikmicroNativeBackend.provenCoreLibrariesFor(HikmicroMini2ModuleType.F1))
        assertEquals(emptySet<String>(), HikmicroNativeBackend.provenCoreLibrariesFor(HikmicroMini2ModuleType.UNSUPPORTED))

        val passive = HikmicroNativeBackend.notAttemptedReport()
        assertEquals("not_attempted", passive.loadStrategy)
        assertEquals("not_attempted", passive.coreMissingReason)
        assertFalse(passive.allLoaded)
        assertFalse(passive.attemptedLibrariesLoaded)
        assertFalse(passive.coreF2Loaded)
        assertTrue(passive.entries.all { !it.attempted && !it.loaded && it.error == "not_attempted" })
        assertEquals(HikmicroNativeBackend.packagedLibraries.size, passive.entries.size)
    }

    @Test
    fun failedF2CoreLoadReportKeepsRetryStateTruthfulAndDoesNotPretendDeferredLibrariesLoaded() {
        val report = NativeLibraryLoadReport(
            entries = HikmicroNativeBackend.packagedLibraries.map { fileName ->
                if (fileName == "libHCUSBSDK.so") {
                    NativeLibraryLoadEntry(
                        fileName = fileName,
                        loadName = "HCUSBSDK",
                        loaded = false,
                        error = "java.lang.UnsatisfiedLinkError: no HCUSBSDK",
                        loadState = "failed",
                        attempted = true,
                        role = "f2_official_core",
                    )
                } else {
                    NativeLibraryLoadEntry(
                        fileName = fileName,
                        loadName = fileName.removePrefix("lib").removeSuffix(".so"),
                        loaded = false,
                        error = "deferred_not_proven_core_for_f2",
                        loadState = "deferred_not_proven_core_for_f2",
                        attempted = false,
                        role = "packaged_inventory",
                    )
                }
            },
            note = "unit report for failed F2 official core load",
            nativeLibraryDir = "/tmp/missing-hikmicro",
            loadStrategy = "system_load_absolute_native_library_dir",
            attemptCount = 2,
            attemptedAtElapsedMs = 123_456L,
            retryAfterMs = 3_000L,
            retryEligible = true,
            coreMissingReason = "libHCUSBSDK.so: java.lang.UnsatisfiedLinkError: no HCUSBSDK",
        )

        assertEquals(2, report.attemptCount)
        assertEquals(123_456L, report.attemptedAtElapsedMs)
        assertEquals(3_000L, report.retryAfterMs)
        assertTrue(report.retryEligible)
        assertFalse(report.coreF2Loaded)
        assertFalse(report.coreTemperatureLoaded)
        assertFalse(report.attemptedLibrariesLoaded)
        assertTrue(report.coreMissingReason.contains("libHCUSBSDK.so"))

        val f2Core = report.entries.single { it.fileName == "libHCUSBSDK.so" }
        assertTrue(f2Core.attempted)
        assertFalse(f2Core.loaded)
        assertEquals("failed", f2Core.loadState)

        val mtlib = report.entries.single { it.fileName == "libMTlib.so" }
        assertFalse(mtlib.attempted)
        assertFalse(mtlib.loaded)
        assertTrue(mtlib.loadState.contains("deferred"))
        assertEquals(1, report.entries.count { it.attempted })
        assertEquals(1, report.entries.count { it.attempted && !it.loaded })
        assertEquals(HikmicroNativeBackend.packagedLibraries.size - 1, report.entries.count { !it.attempted && !it.loaded })
    }

    @Test
    fun passiveUsbPermissionStatusDoesNotMutateLoadStateOrClaimCelsiusReadiness() {
        val before = HikmicroNativeBackend.coreAlreadyLoadedFor(HikmicroMini2ModuleType.F2)

        val status = HikmicroNativeBackend.passiveStatusForUsbPermission(
            usbPermissionGranted = true,
            preferredModuleType = HikmicroMini2ModuleType.F2,
        )
        val evidence = HikmicroNativeBackend.validationEvidence

        assertFalse(status.calibrated)
        assertEquals(ThermalCalibrationState.RAW_UNVERIFIED, status.state)
        assertTrue(status.reason.contains("deferred until an explicit Mini2 stream attempt"))
        assertEquals(before, HikmicroNativeBackend.coreAlreadyLoadedFor(HikmicroMini2ModuleType.F2))
        assertFalse(evidence.fixtureCompared)
        assertFalse(evidence.liveStreamObserved)
        assertFalse(evidence.mayEmitCelsius)
    }
}
