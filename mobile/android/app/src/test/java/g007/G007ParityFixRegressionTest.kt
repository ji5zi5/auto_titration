package g007

import com.hik.f2module.IFR_INFO
import java.io.File
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class G007ParityFixRegressionTest {
    @Test fun officialZ2PreviewDefaultsMatchExtractedDexConstants() {
        assertEquals(true, Z2.a.a.i())
        assertEquals(false, Z2.a.a.q())
        assertEquals(2, Z2.a.a.r())
        assertEquals(1, Z2.a.a.s())
    }

    @Test fun offlineUploadHeaderIsPopulatedByU4LittleEndianDecode() {
        val expected = IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE().apply {
            dwIsFreezedata = 0x01020304
            ifrRealtimeTmOutcomeUploadInfo.enumTempUnit = 0x11223344
            ifrRealtimeTmOutcomeUploadInfo.byRefTempkey = 0x55
            ifrRealtimeTmOutcomeUploadInfo.fDistance = 1.25f
            ifrRealtimeTmOutcomeUploadInfo.fRefTemp = 2.5f
            ifrRealtimeTmOutcomeUploadInfo.fEmissionRate = 0.98f
            ifrRealtimeTmOutcomeUploadInfo.fEnvTemp = 21.5f
            ifrRealtimeTmOutcomeUploadInfo.fMinTmp = 18.25f
            ifrRealtimeTmOutcomeUploadInfo.fMaxTmp = 31.75f
            ifrRealtimeTmOutcomeUploadInfo.fAvrTmp = 24.5f
            ifrRealtimeTmOutcomeUploadInfo.ifrPointArr[0].x = 7
            ifrRealtimeTmOutcomeUploadInfo.ifrPointArr[0].y = 9
            ifrRealtimeTmOutcomeUploadInfo.u32TempMode = 0x66778899.toInt()
            ifrRealtimeTmOutcomeUploadInfo.pointNum = 1
            ifrRealtimeTmOutcomeUploadInfo.boxNum = 2
            ifrRealtimeTmOutcomeUploadInfo.lineNum = 3
            ifrRealtimeTmOutcomeUploadInfo.total = 6
            ifrRealtimeTmOutcomeUploadInfo.uploadType = 0x0a0b0c0d
            ifrRealtimeTmOutcomeUploadInfo.u32CrcVal = 0x10203040
        }

        val bytes = U4.c.a(expected, ByteOrder.LITTLE_ENDIAN)
        assertEquals(6_712, bytes.size)
        assertEquals(0x04.toByte(), bytes[116])
        assertEquals(0x03.toByte(), bytes[117])
        assertEquals(0x02.toByte(), bytes[118])
        assertEquals(0x01.toByte(), bytes[119])

        val decoded = IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE()
        U4.c.b(decoded, bytes, ByteOrder.LITTLE_ENDIAN)

        val info = decoded.ifrRealtimeTmOutcomeUploadInfo
        assertEquals(expected.dwIsFreezedata, decoded.dwIsFreezedata)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.enumTempUnit, info.enumTempUnit)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.byRefTempkey, info.byRefTempkey)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.fDistance, info.fDistance)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.fRefTemp, info.fRefTemp)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.fEmissionRate, info.fEmissionRate)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.fEnvTemp, info.fEnvTemp)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.fMinTmp, info.fMinTmp)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.fMaxTmp, info.fMaxTmp)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.fAvrTmp, info.fAvrTmp)
        assertEquals(7, info.ifrPointArr[0].x)
        assertEquals(9, info.ifrPointArr[0].y)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.u32TempMode, info.u32TempMode)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.pointNum, info.pointNum)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.boxNum, info.boxNum)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.lineNum, info.lineNum)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.total, info.total)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.uploadType, info.uploadType)
        assertEquals(expected.ifrRealtimeTmOutcomeUploadInfo.u32CrcVal, info.u32CrcVal)
    }

    @Test fun productionSourcesDoNotContainLegacyG007Fallbacks() {
        val root = generateSequence(File(requireNotNull(System.getProperty("user.dir")))) { it.parentFile }
            .flatMap { sequenceOf(it, File(it, "mobile/android")) }
            .first { File(it, "app/src/main/java/g3/d.java").exists() }
        val sources = listOf(
            "app/src/main/java/com/hik/f2module/IFR_INFO.kt",
            "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt",
            "app/src/main/java/com/hik/f1module/hcusbcamerasdk/jna/HCUSBCameraSDKBy.kt",
            "app/src/main/java/Z2/a.java",
            "app/src/main/java/g3/d.java",
            "app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt",
        ).associateWith { File(root, it).readText() }

        sources.forEach { (_, text) ->
            assertFalse(text.contains("OfficialFieldOrder"))
        }
        val processor = sources.getValue("app/src/main/java/g3/d.java")
        assertFalse(processor.contains("hydrateOfflineUploadHeader"))
        assertFalse(processor.contains("java.vm.name"))
        assertFalse(processor.contains("rotatedWidth * rotatedHeight * 3 / 2"))
        assertFalse(processor.contains("copyOf(yuvBytes.size"))

        val z2Profile = sources.getValue("app/src/main/java/Z2/a.java")
        assertFalse(z2Profile.contains("return 0;"))
        assertFalse(z2Profile.contains("return true;"))
        assertTrue(z2Profile.contains("Z2.g.b(Z2.g.a, false, 1, null)"))
        assertTrue(z2Profile.contains("UsbModuleType.F1.INSTANCE) && s"))

        val api = sources.getValue("app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt")
        assertFalse(api.contains("wrapCalibrationPrefetchCallbacks"))
        assertEquals(2, Regex("streamCallback\\.getFStreamCallBack(?:JNA)?\\(\\)").findAll(api).count())

        val appAdapter = sources.getValue(
            "app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt"
        )
        val previewCallback = appAdapter.substringAfter("callback = { frame ->")
            .substringBefore("onInvalidPacketSizeTimeout =")
        assertTrue(previewCallback.contains("f2Helper.onPreviewFrameForCalibrationPrefetch("))
        assertFalse(previewCallback.contains("acquireThermometryCalibrationFileOnce("))
        assertFalse(previewCallback.contains("renderAndMeasure("))
        assertFalse(Regex("""\bUSB_Get\w*\(""").containsMatchIn(previewCallback))
        val successCallback = appAdapter.substringAfter("internal fun onOfficialPreviewSuccess")
            .substringBefore("internal fun resetOfficialPreviewSuccessCounter")
        assertFalse(successCallback.contains("previewSuccessTimes == 10L"))
        assertFalse(successCallback.contains("onPreviewFrameForCalibrationPrefetch"))
    }

    @Test fun officialF2ApiAndHelperExcludeCandidateAndFallbackMachinery() {
        val root = generateSequence(File(requireNotNull(System.getProperty("user.dir")))) { it.parentFile }
            .flatMap { sequenceOf(it, File(it, "mobile/android")) }
            .first { File(it, "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt").exists() }
        val sources = listOf(
            "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt",
            "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt",
        ).associateWith { File(root, it).readText() }
        val forbiddenTokens = listOf(
            "formatAttempts",
            "startStreamPreviewCandidate",
            "F2StreamFormatCandidate",
            "runCatching",
            "wrapCalibrationPrefetchCallbacks",
            "cleanupAfterException",
        )

        sources.forEach { (path, text) ->
            forbiddenTokens.forEach { token ->
                assertFalse("$path contains $token", text.contains(token))
            }
            assertFalse(
                "$path catches Throwable",
                Regex("""catch\s*\(\s*[^)]*\bThrowable\b[^)]*\)""").containsMatchIn(text),
            )
        }

        val api = sources.getValue("app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt")
        assertFalse(api.contains("fun latestCalibrationAcquisitionResult("))
    }

    @Test fun g010MeasurementBoundaryDoesNotRunCalibrationOrRadiometricChainPerPreviewFrame() {
        val root = generateSequence(File(requireNotNull(System.getProperty("user.dir")))) { it.parentFile }
            .flatMap { sequenceOf(it, File(it, "mobile/android")) }
            .first { File(it, "app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt").exists() }
        val stream = File(root, "app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt").readText()
        val helper = File(root, "app/src/main/java/com/hik/f2module/F2UsbModuleHelper.kt").readText()
        val coordinator = File(root, "app/src/main/java/kr/auto/titration/mobile/thermal/OfficialF2MeasurementCoordinator.kt").readText()

        val successCallback = stream.substringAfter("internal fun onOfficialPreviewSuccess")
            .substringBefore("internal fun resetOfficialPreviewSuccessCounter")
        assertFalse(successCallback.contains("acquireThermometryCalibrationFileOnce"))
        assertFalse(successCallback.contains("OfficialF2RadiometricBridge"))
        assertFalse(successCallback.contains("renderAndMeasure"))
        assertFalse(stream.substringAfter("private fun captureOfficialF2Frame").substringBefore("@Synchronized\n    internal fun onOfficialPreviewSuccess").contains("renderAndMeasure"))

        val prefetchBody = helper.substringAfter("fun onPreviewFrameForCalibrationPrefetch")
            .substringBefore("fun activeCalibrationIdentitySummary")
        assertTrue(prefetchBody.contains("previewFrameCounter != 10L"))
        assertTrue(prefetchBody.contains("calibrationPrefetchAttemptedGeneration"))
        assertTrue(prefetchBody.contains("executor.submit"))
        assertFalse(prefetchBody.contains("USB_GetThermometryCalibrationFile"))
        assertFalse(prefetchBody.contains("calibrationPrefetchExecutor.execute"))

        assertTrue(coordinator.contains("helper.acquireThermometryCalibrationFileOnce(calibrationDir, sessionToken)"))
        assertTrue(coordinator.contains("helper.acquireOfficialF2MeasurementSettingsOnce(sessionToken)"))
        assertTrue(coordinator.contains("helper.isSessionTokenCurrent(sessionToken)"))
        assertTrue(coordinator.contains("requireOfficialF2CalibrationDirectory(calibrationDir)"))
        assertFalse(coordinator.contains("context.cacheDir"))
        assertTrue(coordinator.contains("bridge.renderAndMeasure(appContext, request)"))
        assertTrue(coordinator.contains("fullMatrixCelsiusAvailable = false"))
    }
}
