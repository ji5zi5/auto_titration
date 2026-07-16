package kr.auto.titration.mobile.thermal

import com.sun.jna.Pointer
import java.lang.reflect.Modifier
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HikmicroMtlibIntConverterTest {
    @Test
    fun jnaInterfaceExposesExactMtlibIntSignaturesWithoutLoadingJnaOnHostJvm() {
        assertMtlibSignature("MT_GetMemSize_INT", Pointer::class.java, Pointer::class.java)
        assertMtlibSignature("MT_Create_INT", Pointer::class.java, Pointer::class.java, Pointer::class.java)
        assertMtlibSignature("MT_SetConfig_INT", Pointer::class.java, Int::class.javaPrimitiveType!!, Pointer::class.java, Int::class.javaPrimitiveType!!)
        assertMtlibSignature("MT_Process_INT", Pointer::class.java, Int::class.javaPrimitiveType!!, Pointer::class.java, Int::class.javaPrimitiveType!!)
    }

    @Test
    fun androidPointRecordIsExactly0x20AndPutsOnlyProvedOffsets() {
        val q13 = HikmicroMtlibQ13(
            atmosphericQ13 = 1,
            humidityQ13 = 2,
            windowTransQ13 = 3,
            windowTempMilliC = 4,
            emissivityQ13 = 7946,
            reflectedQ13 = 204800,
            distanceQ13 = 8192,
        )

        val point = packAndroidPointRecord(gray = 5338, q13 = q13)

        assertEquals(0x20, point.size)
        assertEquals(5338, point.i32(0x04))
        assertEquals(0, point.i32(0x10))
        assertEquals(7946, point.i32(0x14))
        assertEquals(204800, point.i32(0x18))
        assertEquals(8192, point.i32(0x1c))
        assertEquals(0, point.i32(0x00))
        assertEquals(0, point.i32(0x08))
        assertEquals(0, point.i32(0x0c))
    }

    @Test
    fun descriptorCalculationsUseProvedOffsetsAnd128ByteAlignment() {
        val plan = HikmicroMtlibIntSession.createMemoryDescriptorPlan(
            rawAddress = 0x10003L,
            backingSize = 0x600000L + 0x400L,
        )

        assertEquals(0x00L, plan.base0PointerOffset)
        assertEquals(0L, plan.base0Address % 0x80L)
        assertEquals(0x08L, plan.size0Offset)
        assertEquals(0x4200, plan.size0)
        assertEquals(0x0cL, plan.alignment0Offset)
        assertEquals(0x80, plan.alignment)
        assertEquals(0x14L, plan.countOffset)
        assertEquals(1, plan.count)
        assertEquals(0x18L, plan.base1PointerOffset)
        assertEquals(0L, plan.base1Address % 0x80L)
        assertEquals(0x20L, plan.size1Offset)
        assertTrue("descriptor must leave a positive second arena", plan.size1 > 0)
        assertEquals(0x24L, plan.alignment1Offset)
        assertEquals(0x2cL, plan.zeroOffset)
        assertEquals(0, plan.zero)
    }

    @Test
    fun getMemSizeUsesDisposableDescriptorBeforeFreshCreateDescriptor() {
        data class DescriptorToken(val id: Int)

        val events = mutableListOf<String>()
        var nextId = 0
        val result = hikmicroMtlibProbeThenCreate(
            allocateDescriptor = {
                DescriptorToken(++nextId).also { events += "allocate:${it.id}" }
            },
            retainProbeDescriptor = { events += "retain-probe:${it.id}" },
            getMemSize = { events += "get-mem-size:${it.id}"; 0 },
            retainCreateDescriptor = { events += "retain-create:${it.id}" },
            create = { events += "create:${it.id}"; 0 },
        )

        assertEquals(1, result.probeDescriptor.id)
        assertEquals(2, result.createDescriptor?.id)
        assertFalse(result.probeDescriptor === result.createDescriptor)
        assertEquals(0, result.getMemSizeReturnCode)
        assertEquals(0, result.createReturnCode)
        assertEquals(
            listOf(
                "allocate:1",
                "retain-probe:1",
                "get-mem-size:1",
                "allocate:2",
                "retain-create:2",
                "create:2",
            ),
            events,
        )
    }

    @Test
    fun fixtureManifestChecksumsAndExpectedVectorsAreStable() {
        val base = File("src/main/assets/hikmicro/mtlib-fixture/IR_00001")
        val fixture = parseFixture { name -> File(base, name).inputStream() }

        fixture.verifyChecksums()
        assertEquals(49152, fixture.rawGray.size)
        assertEquals(1024, fixture.tag1Addline.size)
        assertEquals(14336, fixture.tag519Calibration.size)
        assertEquals(257884, fixture.q13.atmosphericQ13)
        assertEquals(7946, fixture.q13.emissivityQ13)
        assertEquals(32, fixture.expectedFirst32.size)
        assertEquals(5338, fixture.expectedFirst32.first().gray)
        assertEquals(2127, fixture.expectedFirst32.first().temperatureX64)
        assertEquals(1425, fixture.expectedTempX64Min)
        assertEquals(2175, fixture.expectedTempX64Max)
        assertEquals("43e43546810d5679d2818b52799997743b5013dd6f7214e4f702387f4e402594", fixture.fileChecksums.getValue("raw_u16_256x192_le.bin"))
    }

    @Test
    fun liveGateBlocksWithoutSelfTestOrCompleteProvenanceAndNeverReturnsFakeZeroCelsius() {
        val converter = HikmicroMtlibIntConverter.createForTests(RecordingEngine())
        val blockedNotRun = converter.convertLive(
            completeFrame(selfTestState = HikmicroMtlibSelfTestState.NOT_RUN),
        )
        val blockedMissingRaw = converter.convertLive(
            completeFrame(selfTestState = HikmicroMtlibSelfTestState.PASSED).copy(rawGray = null),
        )

        assertEquals(HikmicroMtlibPublishState.BLOCKED, blockedNotRun.state)
        assertNull(blockedNotRun.temperatureC)
        assertEquals("android_mtlib_fixture_self_test_not_passed", blockedNotRun.provenance.failClosedReason)
        assertEquals(HikmicroMtlibPublishState.BLOCKED, blockedMissingRaw.state)
        assertNull(blockedMissingRaw.temperatureC)
        assertEquals("missing_live_raw_matrix", blockedMissingRaw.provenance.failClosedReason)
    }

    @Test
    fun publishableLiveConversionRequiresCompleteMetadataAndUsesCountOneUniqueGrayCalls() {
        val native = RecordingEngine()
        val converter = HikmicroMtlibIntConverter.createForTests(
            native,
            initialSelfTestState = HikmicroMtlibSelfTestState.PASSED,
        )
        val frame = completeFrame(selfTestState = HikmicroMtlibSelfTestState.NOT_RUN)

        val result = converter.convertLive(frame)

        assertEquals(HikmicroMtlibPublishState.PUBLISHABLE, result.state)
        assertEquals(49152, result.temperatureC?.size)
        assertTrue(result.temperatureC!!.all { it == 10.0 })
        assertEquals(listOf(6, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 189, 12), native.setConfigTypes)
        assertEquals(listOf(1), native.processCounts)
        assertEquals(0x20, native.pointSizes.single())
        assertEquals(1234, native.grays.single())
        assertFalse(result.provenance.nativeReturnCodes.isEmpty())
    }

    @Test
    fun liveGateRequiresExactTag519SizeAndActualCalibrationSha256() {
        val engine = RecordingEngine()
        val converter = HikmicroMtlibIntConverter.createForTests(
            engine,
            initialSelfTestState = HikmicroMtlibSelfTestState.PASSED,
        )
        val valid = completeFrame(selfTestState = HikmicroMtlibSelfTestState.PASSED)
        val wrongSizeBytes = valid.tag519Calibration!!.copyOf(0x3800 - 1)
        val wrongSize = converter.convertLive(
            valid.copy(
                tag519Calibration = wrongSizeBytes,
                provenance = valid.provenance.copy(calibrationSha256 = sha256ForTest(wrongSizeBytes)),
            ),
        )
        val tamperedBytes = valid.tag519Calibration.copyOf().also { it[0] = (it[0].toInt() xor 0x01).toByte() }
        val mismatchedHash = converter.convertLive(valid.copy(tag519Calibration = tamperedBytes))

        assertEquals(HikmicroMtlibPublishState.BLOCKED, wrongSize.state)
        assertNull(wrongSize.temperatureC)
        assertEquals("invalid_live_tag519_calibration_size=14335", wrongSize.provenance.failClosedReason)
        assertEquals(HikmicroMtlibPublishState.BLOCKED, mismatchedHash.state)
        assertNull(mismatchedHash.temperatureC)
        assertEquals("calibration_sha256_mismatch", mismatchedHash.provenance.failClosedReason)
        assertTrue(engine.setConfigTypes.isEmpty())
    }

    @Test
    fun validatedTag519ContractRejectsEveryNonExactLength() {
        listOf(0, 1, 0x3800 - 1, 0x3800 + 1).forEach { size ->
            val failure = runCatching { requireHikmicroMtlibTag519(ByteArray(size)) }.exceptionOrNull()
            assertTrue("size $size must fail closed", failure is IllegalArgumentException)
        }
        requireHikmicroMtlibTag519(ByteArray(0x3800))
    }

    @Test
    fun provedAbiStringPinsDescriptorTagAndPointContracts() {
        assertEquals(
            "MT_GetMemSize_INT(params,mem_desc); MT_Create_INT(params,mem_desc,out_handle); " +
                "MT_SetConfig_INT(handle,type,data,len); MT_Process_INT(handle,process_type,point,count); " +
                "Android point stride 0x20 count=1 gray+0x04 out_x64+0x10 q13+0x14/+0x18/+0x1c",
            HikmicroMtlibIntConverter.PROVED_ABI,
        )
        assertEquals(0x3800, ByteArray(0x3800).also(::requireHikmicroMtlibTag519).size)
    }

    @Test
    fun incompleteQ13BlocksBeforeNativeConfigurationAndDoesNotReturnFakeZero() {
        val engine = RecordingEngine()
        val converter = HikmicroMtlibIntConverter.createForTests(
            engine,
            initialSelfTestState = HikmicroMtlibSelfTestState.PASSED,
        )
        val frame = completeFrame(selfTestState = HikmicroMtlibSelfTestState.PASSED).copy(
            q13 = HikmicroMtlibQ13(
                atmosphericQ13 = Int.MIN_VALUE,
                humidityQ13 = 491520,
                windowTransQ13 = 8192,
                windowTempMilliC = 20000,
                emissivityQ13 = 7946,
                reflectedQ13 = 204800,
                distanceQ13 = 8192,
            ),
        )

        val result = converter.convertLive(frame)

        assertEquals(HikmicroMtlibPublishState.BLOCKED, result.state)
        assertNull(result.temperatureC)
        assertEquals("missing_live_q13_parameters", result.provenance.failClosedReason)
        assertTrue(engine.setConfigTypes.isEmpty())
        assertTrue(engine.processCounts.isEmpty())
    }

    @Test
    fun failedFixtureSelfTestKeepsLiveConversionBlockedEvenWhenFrameProvenanceClaimsPassed() {
        val engine = RecordingEngine()
        val converter = HikmicroMtlibIntConverter.createForTests(engine)

        val report = converter.runFixtureSelfTest(FailingFixtureLoader())
        val result = converter.convertLive(completeFrame(selfTestState = HikmicroMtlibSelfTestState.PASSED))

        assertEquals(HikmicroMtlibSelfTestState.FAILED, report.state)
        assertTrue(report.failClosedReason!!.startsWith("fixture_self_test_failed:"))
        assertEquals(HikmicroMtlibPublishState.BLOCKED, result.state)
        assertNull(result.temperatureC)
        assertTrue(result.provenance.failClosedReason!!.startsWith("fixture_self_test_failed:"))
    }


    private fun assertMtlibSignature(name: String, vararg parameterTypes: Class<*>) {
        val method = HikmicroMtlibIntLibrary::class.java.getMethod(name, *parameterTypes)
        assertEquals(Int::class.javaPrimitiveType, method.returnType)
        assertTrue("$name must be declared by the JNA interface", Modifier.isAbstract(method.modifiers))
    }

    private fun completeFrame(selfTestState: HikmicroMtlibSelfTestState): HikmicroMtlibLiveFrame {
        val tag519 = ByteArray(0x3800) { (it and 0xff).toByte() }
        return HikmicroMtlibLiveFrame(
            rawGray = IntArray(49152) { 1234 },
            tag1Addline = ByteArray(1024).also { it[568] = 0x12; it[569] = 0x34 },
            tag519Calibration = tag519,
            q13 = HikmicroMtlibQ13(
                atmosphericQ13 = 257884,
                humidityQ13 = 491520,
                windowTransQ13 = 8192,
                windowTempMilliC = 20000,
                emissivityQ13 = 7946,
                reflectedQ13 = 204800,
                distanceQ13 = 8192,
            ),
            provenance = HikmicroMtlibProvenance(
                calibrationSha256 = sha256ForTest(tag519),
                q13Source = "live-q13-test",
                addlineSource = "live-tag1-test",
                selfTestState = selfTestState,
            ),
        )
    }

    private fun sha256ForTest(bytes: ByteArray): String = java.security.MessageDigest.getInstance("SHA-256")
        .digest(bytes)
        .joinToString("") { "%02x".format(it) }

    private fun ByteArray.i32(offset: Int): Int =
        (this[offset].toInt() and 0xff) or
            ((this[offset + 1].toInt() and 0xff) shl 8) or
            ((this[offset + 2].toInt() and 0xff) shl 16) or
            (this[offset + 3].toInt() shl 24)
}

private class RecordingEngine : HikmicroMtlibEngine {
    override val nativeReturnCodes: MutableList<HikmicroMtlibNativeReturn> = mutableListOf()
    val setConfigTypes = mutableListOf<Int>()
    val processCounts = mutableListOf<Int>()
    val pointSizes = mutableListOf<Int>()
    val grays = mutableListOf<Int>()

    override fun configureStatic(tag519: ByteArray, q13: HikmicroMtlibQ13) {
        setConfigTypes += listOf(6, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1)
        nativeReturnCodes += HikmicroMtlibNativeReturn("MT_SetConfig_INT:type6_tag519", 0)
        nativeReturnCodes += HikmicroMtlibNativeReturn("MT_SetConfig_INT:type1_key55", -18)
    }

    override fun configureFrame(tag1: ByteArray) {
        setConfigTypes += listOf(189, 12)
        nativeReturnCodes += HikmicroMtlibNativeReturn("MT_SetConfig_INT:type189_tag1_word284", 0)
        nativeReturnCodes += HikmicroMtlibNativeReturn("MT_SetConfig_INT:type12_tag1_addline", 0)
    }

    override fun processSingleGrayX64(gray: Int, q13: HikmicroMtlibQ13): Int {
        processCounts += 1
        pointSizes += 0x20
        grays += gray
        nativeReturnCodes += HikmicroMtlibNativeReturn("MT_Process_INT", 0)
        return 640
    }
}


private class FailingFixtureLoader : HikmicroMtlibFixtureLoader {
    override fun load(): HikmicroMtlibFixture {
        val tag519 = ByteArray(0x3800) { (it and 0xff).toByte() }
        return HikmicroMtlibFixture(
            rawGray = IntArray(49152) { 1234 },
            tag1Addline = ByteArray(1024),
            tag519Calibration = tag519,
            q13 = HikmicroMtlibQ13(
                atmosphericQ13 = 257884,
                humidityQ13 = 491520,
                windowTransQ13 = 8192,
                windowTempMilliC = 20000,
                emissivityQ13 = 7946,
                reflectedQ13 = 204800,
                distanceQ13 = 8192,
            ),
            expectedFirst32 = List(32) { HikmicroMtlibExpectedPoint(gray = 1234, temperatureX64 = 1) },
            expectedTempX64Min = 1,
            expectedTempX64Max = 1,
            expectedTempCMean = 1.0 / 64.0,
            meanTolerance = 0.0,
            fileChecksums = emptyMap(),
            fileBytes = emptyMap(),
            bytesByName = emptyMap(),
        )
    }
}
