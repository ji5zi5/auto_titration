package kr.auto.titration.mobile.thermal

import org.junit.Test

@Suppress("unused")
class Mini2EvidenceGateTest {
    @Test
    fun statusModelCarriesCallbackEntryAndInvalidPacketTimeoutDiagnostics() {
        val invalidPacket = Mini2InvalidPacketDiagnostic(
            observedPacketSize = 102_944,
            elapsedMs = 40_001L,
            allowedPacketSizes = setOf(203_720, 183_496),
            userId = 2,
            channel = 0,
            fd = 17,
            profileClass = "f3.j",
        )
        val status = Mini2RawStreamStatus.streamAttemptStarted(
            reason = "waiting",
            fd = 17,
            userId = 2,
            channel = 0,
            callbackEntryCount = 3L,
            callbackEntryDetail = "route=jni count=3 callbackUserId=2 dwBufSize=102944",
            invalidPacketDiagnostic = invalidPacket,
        )

        check(status.callbackEntryCount == 3L)
        check(status.callbackEntryDetail.contains("route=jni"))
        check(status.invalidPacketDiagnostic === invalidPacket)
        check(status.invalidPacketDiagnostic.observedPacketSize == 102_944)
        check(status.invalidPacketDiagnostic.allowedPacketSizes == setOf(203_720, 183_496))
        check(status.invalidPacketDiagnostic.channel == 0)
        check(status.invalidPacketDiagnostic.fd == 17)
        check(status.invalidPacketDiagnostic.profileClass == "f3.j")
    }

    @Test
    fun blockedEvidenceDoesNotPermitCelsius() {
        val status = ThermalStatus.rawUnverified("raw Mini2 frame observed, converter unresolved")
        val evidence = Mini2ValidationEvidence(
            abiLoaded = true,
            fixtureCompared = false,
            liveStreamObserved = true,
            meanErrorC = null,
            maxPixelErrorC = null,
        )

        check(!evidence.mayEmitCelsius)
        check(NoFakeCelsiusGuard.nullableCelsius(24.5, status, evidence) == null)
    }

    @Test
    fun celsiusRequiresValidatedEvidenceAndCalibratedStatusTogether() {
        val evidence = Mini2ValidationEvidence(
            abiLoaded = true,
            fixtureCompared = true,
            liveStreamObserved = true,
            meanErrorC = 0.05,
            maxPixelErrorC = 0.25,
        )

        check(evidence.mayEmitCelsius)
        check(NoFakeCelsiusGuard.nullableCelsius(24.5, ThermalStatus.rawUnverified("not calibrated"), evidence) == null)
        check(
            NoFakeCelsiusGuard.nullableCelsius(
                24.5,
                ThermalStatus.calibrated("validated", "official_fixture", "mini2_validated"),
                evidence,
            ) == 24.5,
        )
    }

    @Test
    fun featureFrameRejectsFakeCelsiusWhenEvidenceIsUnresolved() {
        val thrown = runCatching {
            ThermalFeatureFrame(
                frameWidth = 2,
                frameHeight = 2,
                status = ThermalStatus.rawUnverified("raw only"),
                validationEvidence = Mini2ValidationEvidence(liveStreamObserved = true),
                rawRoi = MatrixSummary(avg = 100.0, min = 90.0, max = 110.0),
                celsiusRoi = MatrixSummary(avg = 0.0, min = 0.0, max = 0.0),
            )
        }.exceptionOrNull()

        check(thrown is IllegalArgumentException)
    }

    @Test
    fun rawOnlyFeatureFrameLeavesCelsiusColumnsBlank() {
        val row = ThermalFeatureFrame(
            frameWidth = 2,
            frameHeight = 2,
            status = ThermalStatus.rawUnverified("raw only"),
            validationEvidence = Mini2ValidationEvidence(liveStreamObserved = true),
            rawRoi = MatrixSummary(avg = 100.0, min = 90.0, max = 110.0),
        ).toCsvMap()

        check(row["thermal_raw_roi_avg"] == "100.0")
        check(!row.containsKey("thermal_roi_avg"))
        check(!row.containsKey("thermal_matrix_avg"))
    }

    @Test
    fun conversionAttemptReportsPermissionBlockerAndNullCelsius() {
        val attempt = HikmicroTemperatureConversionAttempt.describe(
            loadReport = NativeLibraryLoadReport(
                entries = listOf(
                    NativeLibraryLoadEntry("libHCUSBSDK.so", "HCUSBSDK", loaded = false, error = "not_attempted"),
                    NativeLibraryLoadEntry("libMTlib.so", "MTlib", loaded = false, error = "not_attempted"),
                ),
                note = "USB permission missing; native load skipped",
                loadStrategy = "not_attempted",
                coreMissingReason = "not_attempted",
            ),
            usbPermissionGranted = false,
        )

        check(attempt.rawFrameStatus == "blocked_usb_permission")
        check(attempt.temperatureStatus == "blocked_no_fake_celsius")
        check(!attempt.celsiusAllowed)
        check(attempt.temperatureAvgC == null)
        check(attempt.temperatureMinC == null)
        check(attempt.temperatureMaxC == null)
        check(attempt.converterProfileStatus.startsWith("unresolved"))
        check(attempt.validationEvidence.converterProfileStatus.startsWith("unresolved"))
    }

    @Test
    fun fixtureParityWithoutLiveDeviceEvidenceCannotPromoteCelsiusSuccess() {
        val fixtureOnlyEvidence = Mini2ValidationEvidence(
            abiLoaded = true,
            fixtureCompared = true,
            liveStreamObserved = false,
            meanErrorC = 0.0,
            maxPixelErrorC = 0.0,
        )

        check(!fixtureOnlyEvidence.passesTechnicalGate)
        check(!fixtureOnlyEvidence.mayEmitCelsius)
        check(fixtureOnlyEvidence.converterProfileStatus == "unresolved_fixture_or_live_stream_validation_missing")
        check(
            NoFakeCelsiusGuard.nullableCelsius(
                0.0,
                ThermalStatus.calibrated("static fixture only", "fixture", "mini2"),
                fixtureOnlyEvidence,
            ) == null,
        )
    }

    @Test
    fun loadedAbiAndStaticSymbolsStillReportNullCelsiusUntilFixtureAndLiveEvidencePass() {
        val attempt = HikmicroTemperatureConversionAttempt.describe(
            loadReport = NativeLibraryLoadReport(
                entries = listOf(
                    NativeLibraryLoadEntry("libHCUSBSDK.so", "HCUSBSDK", loaded = true),
                    NativeLibraryLoadEntry("libMTlib.so", "MTlib", loaded = true),
                    NativeLibraryLoadEntry("libMicroJITA_Release_v8a.so", "MicroJITA_Release_v8a", loaded = true),
                    NativeLibraryLoadEntry("libMicroTA_Release_v8a.so", "MicroTA_Release_v8a", loaded = true),
                ),
                note = "host test synthetic loaded report",
                loadStrategy = "unit_test_static_report",
            ),
            usbPermissionGranted = true,
        )

        check(attempt.rawFrameStatus == "raw_unverified")
        check(attempt.temperatureStatus == "blocked_no_fake_celsius")
        check(!attempt.celsiusAllowed)
        check(attempt.celsiusPublishState == "unavailable_null_until_validation")
        check(attempt.temperatureAvgC == null)
        check(attempt.temperatureMinC == null)
        check(attempt.temperatureMaxC == null)
        check(attempt.symbols.contains("MT_Gray2Temp"))
        check(!attempt.validationEvidence.fixtureCompared)
        check(!attempt.validationEvidence.liveStreamObserved)
        check(!attempt.validationEvidence.mayEmitCelsius)
    }

    @Test
    fun passivePermissionGrantedStatusDoesNotLoadNativeCore() {
        check(!HikmicroNativeBackend.coreAlreadyLoadedFor(HikmicroMini2ModuleType.F2))

        val status = HikmicroNativeBackend.passiveStatusForUsbPermission(
            usbPermissionGranted = true,
            preferredModuleType = HikmicroMini2ModuleType.F2,
        )

        check(!status.calibrated)
        check(status.reason.contains("deferred until an explicit Mini2 stream attempt"))
        check(!HikmicroNativeBackend.coreAlreadyLoadedFor(HikmicroMini2ModuleType.F2))
    }
}
