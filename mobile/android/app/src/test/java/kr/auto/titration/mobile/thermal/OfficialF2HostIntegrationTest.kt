package kr.auto.titration.mobile.thermal

import com.hcusbsdk.Interface.USB_IMAGE_ENHANCEMENT_EX
import com.hik.library.player.d
import com.hik.viewer.manager.PreviewManagerII
import com.hik.viewercommon.data.bean.PreviewInfoDataBean
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2ModuleSubtype
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2PaletteSnapshot
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.nio.file.Path
import java.util.ArrayDeque
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

class OfficialF2HostIntegrationTest {
    @Test
    fun mapsOfficialV20SettingsToExactAgcEnvironmentAndAdjustmentKeys() {
        val enhancement = USB_IMAGE_ENHANCEMENT_EX().apply {
            struImageEnhancement.byWideTemperatureMode = 1
            struImageEnhancement.byWideTemperatureWork = 2
            struImageEnhancement.dwWideTemperatureUpThreshold = 1350
            struImageEnhancement.dwWideTemperatureDownThreshold = 750
            struImageEnhancement.byIspAgcMode = 7
            struImageEnhancement.dwLSEDetailLevel = 42
        }

        val settings = OfficialF2MeasurementCoordinator.settingsFromOfficialV20ForTests(
            brightness = 11,
            contrast = 22,
            enhancement = enhancement,
        )

        assertEquals(4, settings.agcMode)
        assertEquals(35f, settings.maxEnvironmentTemp, 0.0001f)
        assertEquals(-25f, settings.minEnvironmentTemp, 0.0001f)
        assertEquals(setOf("IspMode", "Brightness", "Contrast", "Sharpness"), settings.imageAdjustments.keys)
        assertEquals(7, settings.imageAdjustments["IspMode"])
        assertEquals(11, settings.imageAdjustments["Brightness"])
        assertEquals(22, settings.imageAdjustments["Contrast"])
        assertEquals(42, settings.imageAdjustments["Sharpness"])
    }

    @Test
    fun mapsUnknownWideTemperatureWorkToOfficialEnabledDefaultAgcMode2() {
        val enhancement = USB_IMAGE_ENHANCEMENT_EX().apply {
            struImageEnhancement.byWideTemperatureMode = 1
            struImageEnhancement.byWideTemperatureWork = 99.toByte()
        }

        val settings = OfficialF2MeasurementCoordinator.settingsFromOfficialV20ForTests(1, 2, enhancement)

        assertEquals(2, settings.agcMode)
    }

    @Test
    fun mapsDisabledWideTemperatureModeToOfficialAgcMode1() {
        val enhancement = USB_IMAGE_ENHANCEMENT_EX().apply {
            struImageEnhancement.byWideTemperatureMode = 0
            struImageEnhancement.byWideTemperatureWork = 3
        }

        val settings = OfficialF2MeasurementCoordinator.settingsFromOfficialV20ForTests(1, 2, enhancement)

        assertEquals(1, settings.agcMode)
    }

    @Test
    fun officialSubtypeMappingUsesDefaultBranchForObservedNumericModuleId() {
        assertEquals(OfficialF2ModuleSubtype.F2, OfficialF2MeasurementCoordinator.officialModuleSubtype("0953060001"))
        assertEquals(OfficialF2ModuleSubtype.F23, OfficialF2MeasurementCoordinator.officialModuleSubtype("F23"))
        assertEquals(OfficialF2ModuleSubtype.F2V2, OfficialF2MeasurementCoordinator.officialModuleSubtype("F2V2"))
        assertEquals(OfficialF2ModuleSubtype.F0, OfficialF2MeasurementCoordinator.officialModuleSubtype("F0"))
    }

    @Test
    fun officialCaptureSizeMatchesStandardF2AndF0Evidence() {
        val portraitF2 = OfficialF2MeasurementCoordinator.officialCaptureDimensionsForTests(OfficialF2ModuleSubtype.F2, 720, 960)
        val landscapeF2 = OfficialF2MeasurementCoordinator.officialCaptureDimensionsForTests(OfficialF2ModuleSubtype.F2, 960, 720)
        val f0 = OfficialF2MeasurementCoordinator.officialCaptureDimensionsForTests(OfficialF2ModuleSubtype.F0, 960, 720)

        assertEquals(720, portraitF2[0])
        assertEquals(960, portraitF2[1])
        assertEquals(960, landscapeF2[0])
        assertEquals(720, landscapeF2[1])
        assertEquals(720, f0[0])
        assertEquals(720, f0[1])
    }

    @Test
    fun rendererJpegSelectionReturnsExactTimestampAndDoesNotReadYuvBytesAsJpeg() {
        val calls = AtomicInteger(0)
        val selected = PreviewManagerIIAppBinding.selectOfficialRendererJpegForTests(20, 720, 960) { index ->
            calls.incrementAndGet()
            when (index) {
                0 -> d(19, byteArrayOf(0x00, 0x11, 0x22))
                else -> d(20, jpeg(0x33))
            }
        }

        assertArrayEquals(jpeg(0x33), selected.jpegBytes)
        assertTrue(selected.source.contains("renderer_jpeg_exact_timestamp"))
        assertEquals(20, selected.selectedFrameNumStamp)
        assertEquals(OfficialProcessedF2Frame.RendererTimestampProvenance.EXACT, selected.timestampProvenance)
        assertEquals(2, calls.get())
    }

    @Test
    fun rendererJpegSelectionReportsNearestTimestampJpegForDiagnosticsOnly() {
        val selected = PreviewManagerIIAppBinding.selectOfficialRendererJpegForTests(100, 720, 960) { index ->
            when (index) {
                0 -> d(80, jpeg(0x01))
                1 -> d(97, byteArrayOf(0x10, 0x20, 0x30))
                2 -> d(110, jpeg(0x02))
                else -> d(120, byteArrayOf(0x12, 0x34))
            }
        }

        assertArrayEquals(jpeg(0x02), selected.jpegBytes)
        assertTrue(selected.source.contains("renderer_jpeg_nearest_timestamp"))
        assertEquals(110, selected.selectedFrameNumStamp)
        assertEquals(OfficialProcessedF2Frame.RendererTimestampProvenance.NEAREST, selected.timestampProvenance)
    }

    @Test
    fun rendererJpegSelectionFailsClosedWhenNoRendererJpegExists() {
        val selected = PreviewManagerIIAppBinding.selectOfficialRendererJpegForTests(100, 720, 960) { index ->
            d(100 + index, byteArrayOf(0x12, 0x34, 0x56))
        }

        assertEquals(0, selected.jpegBytes.size)
        assertTrue(selected.source.contains("renderer_jpeg_missing_fail_closed"))
        assertEquals(-1, selected.selectedFrameNumStamp)
        assertEquals(OfficialProcessedF2Frame.RendererTimestampProvenance.NONE, selected.timestampProvenance)
        assertFalse(OfficialF2MeasurementCoordinator.isJpeg(byteArrayOf(0x12, 0x34)))
    }

    @Test
    fun exactRendererStampIsEligibleForRadiometricMeasurement() {
        val frame = officialFrameWithRenderer(
            offlineStamp = 100,
            selectedStamp = 100,
            provenance = OfficialProcessedF2Frame.RendererTimestampProvenance.EXACT,
            source = "renderer_jpeg_exact_timestamp index=0",
        )

        val firJpeg = OfficialF2MeasurementCoordinator.requireExactRendererJpegForRadiometricMeasurementForTests(frame)

        assertArrayEquals(jpeg(0x44), firJpeg)
    }

    @Test
    fun nearestRendererStampIsRejectedBeforeCalibrationOrBridgeAndCannotReady() {
        val frame = officialFrameWithRenderer(
            offlineStamp = 100,
            selectedStamp = 110,
            provenance = OfficialProcessedF2Frame.RendererTimestampProvenance.NEAREST,
            source = "renderer_jpeg_nearest_timestamp index=2",
        )

        val failure = runCatching {
            OfficialF2MeasurementCoordinator.requireExactRendererJpegForRadiometricMeasurementForTests(frame)
        }.exceptionOrNull()

        assertNotNull(failure)
        assertTrue(failure!!.message!!.contains("targetStamp=100"))
        assertTrue(failure.message!!.contains("selectedStamp=110"))
        assertTrue(failure.message!!.contains("provenance=NEAREST"))
        assertTrue(failure.message!!.contains("source=renderer_jpeg_nearest_timestamp index=2"))
        assertFalse(failure.message!!.contains(OfficialF2ScalarMeasurementStatus.READY.name))

        val coordinatorSource = source("app/src/main/java/kr/auto/titration/mobile/thermal/OfficialF2MeasurementCoordinator.kt")
        val guardIndex = coordinatorSource.indexOf("requireExactRendererJpegForRadiometricMeasurement(officialFrame)")
        val calibrationIndex = coordinatorSource.indexOf(
            "val calibration = helper.acquireThermometryCalibrationFileOnce(calibrationDir, sessionToken)",
        )
        val bridgeIndex = coordinatorSource.indexOf("bridge.renderAndMeasure(appContext, request)")
        assertTrue(guardIndex >= 0)
        assertTrue(calibrationIndex > guardIndex)
        assertTrue(bridgeIndex > calibrationIndex)
    }

    @Test
    fun missingRendererStampIsRejectedBeforeRadiometricMeasurement() {
        val frame = officialFrameWithRenderer(
            offlineStamp = 100,
            selectedStamp = -1,
            provenance = OfficialProcessedF2Frame.RendererTimestampProvenance.NONE,
            rendererJpegData = null,
            source = null,
        )

        val failure = runCatching {
            OfficialF2MeasurementCoordinator.requireExactRendererJpegForRadiometricMeasurementForTests(frame)
        }.exceptionOrNull()

        assertNotNull(failure)
        assertTrue(failure!!.message!!.contains("targetStamp=100"))
        assertTrue(failure.message!!.contains("selectedStamp=-1"))
        assertTrue(failure.message!!.contains("provenance=NONE"))
        assertTrue(failure.message!!.contains("source=missing"))
        assertFalse(failure.message!!.contains(OfficialF2ScalarMeasurementStatus.READY.name))
    }

    @Test
    fun mismatchedExactRendererStampIsRejectedBeforeRadiometricMeasurement() {
        val frame = officialFrameWithRenderer(
            offlineStamp = 100,
            selectedStamp = 101,
            provenance = OfficialProcessedF2Frame.RendererTimestampProvenance.EXACT,
            source = "renderer_jpeg_exact_timestamp stale_index=1",
        )

        val failure = runCatching {
            OfficialF2MeasurementCoordinator.requireExactRendererJpegForRadiometricMeasurementForTests(frame)
        }.exceptionOrNull()

        assertNotNull(failure)
        assertTrue(failure!!.message!!.contains("targetStamp=100"))
        assertTrue(failure.message!!.contains("selectedStamp=101"))
        assertTrue(failure.message!!.contains("provenance=EXACT"))
        assertTrue(failure.message!!.contains("source=renderer_jpeg_exact_timestamp stale_index=1"))
    }

    @Test
    fun officialPicDataBeanIsImmutableAndHasNoInventedReleaseContract() {
        val picDataMethods = d::class.java.declaredMethods.map { it.name }.toSet()
        val bindingSource = source("app/src/main/java/kr/auto/titration/mobile/thermal/PreviewManagerIIAppBinding.java")

        assertTrue(picDataMethods.containsAll(setOf("a", "b")))
        assertFalse(picDataMethods.contains("release"))
        assertFalse(bindingSource.contains("candidate.release("))
    }

    @Test
    fun standardPaletteSnapshotCarriesEveryOfficialCFieldAndRejectsUnprovedAbsence() {
        val append = ByteArray(38)
        putLeShort(append, 22, -2)
        putLeShort(append, 24, 300)
        putLeShort(append, 26, 400)
        putLeShort(append, 28, -500)
        putLeShort(append, 30, 600)
        putLeShort(append, 32, -700)
        putLeShort(append, 34, 800)
        putLeShort(append, 36, -900)
        val builder = PreviewManagerII::class.java.getDeclaredMethod(
            "buildStandardOfficialPaletteSnapshot",
            ByteArray::class.java,
            Float::class.javaPrimitiveType,
            Float::class.javaPrimitiveType,
            Int::class.javaPrimitiveType,
            Int::class.javaPrimitiveType,
            Int::class.javaPrimitiveType,
            Float::class.javaPrimitiveType,
            Float::class.javaPrimitiveType,
        ).apply { isAccessible = true }
        val snapshot = builder.invoke(
            null,
            append,
            44.5f,
            -12.25f,
            14,
            7,
            4,
            35f,
            -25f,
        ) as OfficialF2PaletteSnapshot

        assertTrue(snapshot.isPresent)
        assertEquals(1, snapshot.paletteMode)
        assertEquals(0, snapshot.customPseudoColorHexArrSize)
        assertNull(snapshot.customPseudoColorHexArr)
        assertEquals(14, snapshot.pseudoColor)
        assertEquals(44.5f, snapshot.maxTmp, 0f)
        assertEquals(-12.25f, snapshot.minTmp, 0f)
        assertEquals(7, snapshot.ispMode)
        assertEquals(4, snapshot.agcMode)
        assertEquals(35f, snapshot.wideTempUpThreshold, 0f)
        assertEquals(-25f, snapshot.wideTempDownThreshold, 0f)
        assertEquals(600, snapshot.rawGrayMax)
        assertEquals(-700, snapshot.rawGrayMin)
        assertEquals(400, snapshot.agcGrayMax)
        assertEquals(-500, snapshot.agcGrayMin)
        assertEquals(-2, snapshot.colorAlarmMax)
        assertEquals(300, snapshot.colorAlarmMin)
        assertEquals(800, snapshot.colorAlarm14bitMax)
        assertEquals(-900, snapshot.colorAlarm14bitMin)
        assertSame(snapshot, OfficialF2MeasurementCoordinator.requireProvedPaletteSnapshot(snapshot))
        assertTrue(runCatching { OfficialF2MeasurementCoordinator.requireProvedPaletteSnapshot(null) }.isFailure)
        assertTrue(
            runCatching {
                OfficialF2MeasurementCoordinator.requireProvedPaletteSnapshot(
                    OfficialF2PaletteSnapshot.absent(null),
                )
            }.isFailure,
        )
        assertTrue(
            runCatching {
                OfficialF2MeasurementCoordinator.requireProvedPaletteSnapshot(
                    OfficialF2PaletteSnapshot.present(2, 1, null),
                )
            }.isFailure,
        )
    }

    @Test
    fun previewSuccessCounterIdentifiesTheTenthSuccessfulFrameForPrefetch() {
        HikmicroJnaMini2Stream.resetOfficialPreviewSuccessCounter()
        var count = 0L
        repeat(10) { count = HikmicroJnaMini2Stream.onOfficialPreviewSuccess() }

        assertEquals(10L, count)
    }

    @Test
    fun calibrationDirectoryUsesPersistentF2DataAndRejectsCacheDirectory() {
        val externalFilesRoot = Files.createTempDirectory("official-external-files-root").toFile()
        val cacheDir = Files.createTempDirectory("official-cache-root").toFile()

        val directory = HikmicroJnaMini2Stream.officialF2DataDirectoryFromExternalFilesRoot(externalFilesRoot)
        val officialLiteralDirectory = File(externalFilesRoot, "/F2Data")
        val validated = OfficialF2MeasurementCoordinator.requireOfficialF2CalibrationDirectory(directory)

        assertEquals(externalFilesRoot.resolve("F2Data").canonicalFile, validated.canonicalFile)
        assertEquals(externalFilesRoot.resolve("F2Data").canonicalFile, officialLiteralDirectory.canonicalFile)
        assertEquals(officialLiteralDirectory.canonicalFile, validated.canonicalFile)
        assertFalse(validated.canonicalFile == cacheDir.canonicalFile)
        assertTrue(validated.isDirectory)
        assertTrue(validated.absolutePath.contains("F2Data"))
        assertTrue(runCatching { OfficialF2MeasurementCoordinator.requireOfficialF2CalibrationDirectory(cacheDir) }.isFailure)
        val coordinatorSource = source("app/src/main/java/kr/auto/titration/mobile/thermal/OfficialF2MeasurementCoordinator.kt")
        assertTrue(coordinatorSource.contains("helper.acquireThermometryCalibrationFileOnce(calibrationDir, sessionToken)"))
        assertTrue(coordinatorSource.contains("helper.acquireOfficialF2MeasurementSettingsOnce(sessionToken)"))
        assertTrue(coordinatorSource.contains("helper.isSessionTokenCurrent(sessionToken)"))
        assertTrue(coordinatorSource.contains("\"after_radiometric_bridge\""))
        assertTrue(coordinatorSource.contains("\"before_commit\""))
        assertFalse(coordinatorSource.contains("acquireThermometryCalibrationFileOnce(context.cacheDir)"))
    }

    @Test
    fun schedulerEligibilityRequiresFreshFrameAndBoundManager() {
        assertFalse(isOfficialMeasurementScheduleEligible(null, 100L, 100L, managerBound = true))
        assertFalse(isOfficialMeasurementScheduleEligible(1L, 100L, 100L, managerBound = false))
        assertFalse(isOfficialMeasurementScheduleEligible(1L, 100L, 100L + FRAME_WAIT_TIMEOUT_MS + 1L, managerBound = true))
        assertTrue(isOfficialMeasurementScheduleEligible(1L, 100L, 100L + FRAME_WAIT_TIMEOUT_MS, managerBound = true))
    }

    @Test
    fun schedulerReturnsBeforeBlockingWorkerAndRunsRendererWorkOffCallerThread() {
        val scheduler = OfficialF2MeasurementScheduler()
        val key = OfficialF2MeasurementScheduleKey(41L, null)
        val workerStarted = CountDownLatch(1)
        val releaseWorker = CountDownLatch(1)
        val workerFinished = CountDownLatch(1)
        val callerReturned = CountDownLatch(1)
        val accepted = AtomicBoolean(false)
        val workerThread = AtomicReference<Thread>()
        val callerThread = Thread({
            accepted.set(scheduler.schedule(key) {
                workerThread.set(Thread.currentThread())
                workerStarted.countDown()
                releaseWorker.await(2, TimeUnit.SECONDS)
                workerFinished.countDown()
            })
            callerReturned.countDown()
        }, "measurement-api-caller")

        callerThread.start()
        assertTrue(workerStarted.await(2, TimeUnit.SECONDS))
        val returnedWhileWorkerBlocked = callerReturned.await(2, TimeUnit.SECONDS)
        releaseWorker.countDown()
        assertTrue(workerFinished.await(2, TimeUnit.SECONDS))
        callerThread.join(2_000L)

        assertTrue(accepted.get())
        assertTrue(returnedWhileWorkerBlocked)
        assertNotSame(callerThread, workerThread.get())
        assertTrue(workerThread.get().isDaemon)
        assertEquals("OfficialF2LatestMeasurementScheduler", workerThread.get().name)
    }

    @Test
    fun schedulerDeduplicatesSingleFlightAndLifecycleResetInvalidatesQueuedWork() {
        val executor = ManualExecutor()
        val scheduler = OfficialF2MeasurementScheduler(executor)
        val fullscreenFrame7 = OfficialF2MeasurementScheduleKey(7L, null)
        val rectangleFrame7 = OfficialF2MeasurementScheduleKey(7L, OfficialF2MeasurementRoiKey(1, 2, 30, 40))
        val fullscreenFrame8 = OfficialF2MeasurementScheduleKey(8L, null)
        val executions = mutableListOf<OfficialF2MeasurementScheduleKey>()

        assertTrue(scheduler.schedule(fullscreenFrame7) { executions += fullscreenFrame7 })
        assertFalse(scheduler.schedule(rectangleFrame7) { executions += rectangleFrame7 })
        scheduler.resetLifecycle()
        assertTrue(scheduler.schedule(fullscreenFrame7) { executions += fullscreenFrame7 })

        executor.runNext()
        assertTrue(executions.isEmpty())
        assertFalse(scheduler.schedule(rectangleFrame7) { executions += rectangleFrame7 })
        executor.runNext()
        assertEquals(listOf(fullscreenFrame7), executions)
        assertFalse(scheduler.schedule(fullscreenFrame7) { executions += fullscreenFrame7 })

        assertTrue(scheduler.schedule(rectangleFrame7) { executions += rectangleFrame7 })
        executor.runNext()
        assertTrue(scheduler.schedule(fullscreenFrame8) { executions += fullscreenFrame8 })
        executor.runNext()
        assertEquals(listOf(fullscreenFrame7, rectangleFrame7, fullscreenFrame8), executions)
    }

    @Test
    fun lifecycleResetPreventsRunningWorkerFromPublishingStaleResult() {
        val scheduler = OfficialF2MeasurementScheduler()
        val workerStarted = CountDownLatch(1)
        val releaseWorker = CountDownLatch(1)
        val workerFinished = CountDownLatch(1)
        val published = AtomicInteger(0)

        assertTrue(scheduler.schedule(OfficialF2MeasurementScheduleKey(9L, null)) { generation ->
            workerStarted.countDown()
            releaseWorker.await(2, TimeUnit.SECONDS)
            scheduler.runIfGenerationCurrent(generation) { published.incrementAndGet() }
            workerFinished.countDown()
        })
        assertTrue(workerStarted.await(2, TimeUnit.SECONDS))
        scheduler.resetLifecycle()
        releaseWorker.countDown()
        assertTrue(workerFinished.await(2, TimeUnit.SECONDS))

        assertEquals(0, published.get())
    }

    @Test
    fun readyScalarStateHasExplicitScopeFiniteStatsFrameAndNoMatrix() {
        val fullscreen = OfficialF2MeasurementCoordinator.readyStateForTests(
            frameCounter = 55L,
            measuredScope = "FULLSCREEN",
            maxCelsius = 31.5f,
            minCelsius = 20.25f,
            centerCelsius = 25.5f,
            averageCelsius = 25.0f,
        )
        val rectangle = OfficialF2MeasurementCoordinator.readyStateForTests(
            frameCounter = 56L,
            measuredScope = "RECTANGLE",
            maxCelsius = 30f,
            minCelsius = 21f,
            centerCelsius = 26f,
            averageCelsius = 25f,
        )

        assertEquals(OfficialF2ScalarMeasurementStatus.READY, fullscreen.status)
        assertEquals(55L, fullscreen.frameCounter)
        assertEquals("FULLSCREEN", fullscreen.measuredScope)
        assertEquals("RECTANGLE", rectangle.measuredScope)
        assertTrue(listOf(fullscreen.maxCelsius, fullscreen.minCelsius, fullscreen.centerCelsius, fullscreen.averageCelsius)
            .all { it != null && it.isFinite() })
        assertFalse(fullscreen.fullMatrixCelsiusAvailable)
        assertFalse(rectangle.fullMatrixCelsiusAvailable)
        assertTrue(runCatching {
            OfficialF2MeasurementCoordinator.readyStateForTests(57L, "FULLSCREEN", Float.NaN, 1f, 1f, 1f)
        }.isFailure)
    }

    @Test
    fun idleScalarStateAlsoNeverPublishesFullMatrix() {
        val state = OfficialF2ScalarMeasurementState.idle()

        assertFalse(state.fullMatrixCelsiusAvailable)
        assertNull(state.maxCelsius)
    }

    private fun jpeg(marker: Int): ByteArray = byteArrayOf(0xff.toByte(), 0xd8.toByte(), marker.toByte())

    private fun officialFrameWithRenderer(
        offlineStamp: Int,
        selectedStamp: Int,
        provenance: OfficialProcessedF2Frame.RendererTimestampProvenance,
        rendererJpegData: ByteArray? = jpeg(0x44),
        source: String?,
    ): OfficialProcessedF2Frame = OfficialProcessedF2Frame(
        7L,
        103,
        720,
        960,
        null,
        true,
        "processor",
        0L,
        offlineStamp,
        OfficialF2PaletteSnapshot.absent(
            OfficialF2PaletteSnapshot.AbsenceProof.PREVIEW_MANAGER_Q_RETURNED_NULL,
        ),
        "preview_manager_Q_returned_actual_null",
        PreviewInfoDataBean(),
        offlineStamp,
        rendererJpegData,
        source,
        720,
        960,
        selectedStamp,
        provenance,
    )

    private fun putLeShort(target: ByteArray, offset: Int, value: Int) {
        target[offset] = (value and 0xff).toByte()
        target[offset + 1] = ((value ushr 8) and 0xff).toByte()
    }

    private fun source(relativePath: String): String {
        var root = Path.of("").toAbsolutePath()
        repeat(6) {
            val candidate = root.resolve(relativePath)
            if (Files.exists(candidate)) return String(Files.readAllBytes(candidate))
            val appCandidate = root.resolve("../").normalize().resolve(relativePath)
            if (Files.exists(appCandidate)) return String(Files.readAllBytes(appCandidate))
            root = root.parent ?: root
        }
        throw java.nio.file.NoSuchFileException(relativePath)
    }

    private class ManualExecutor : Executor {
        private val tasks = ArrayDeque<Runnable>()

        override fun execute(command: Runnable) {
            tasks.addLast(command)
        }

        fun runNext() {
            tasks.removeFirst().run()
        }
    }
}
