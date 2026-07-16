package kr.auto.titration.mobile.thermal

import android.content.Context
import com.sun.jna.Library
import com.sun.jna.Memory
import com.sun.jna.Native
import com.sun.jna.Pointer
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import kotlin.math.abs

private const val MTLIB_WIDTH = 256
private const val MTLIB_HEIGHT = 192
private const val MTLIB_PIXELS = MTLIB_WIDTH * MTLIB_HEIGHT
private const val MTLIB_PARAMS_SIZE = 0x20L
private const val MTLIB_DESC_SIZE = 0x40L
private const val MTLIB_POINT_SIZE_ANDROID = 0x20L
private const val MTLIB_BACKING_SIZE = 0x600000L
private const val MTLIB_ALIGNMENT = 0x80L
private const val MTLIB_TAG519_SIZE = 0x3800

/** Exact Android arm64 JNA binding for the statically proved MTlib INT ABI. */
interface HikmicroMtlibIntLibrary : Library {
    fun MT_GetMemSize_INT(params: Pointer, memDesc: Pointer): Int
    fun MT_Create_INT(params: Pointer, memDesc: Pointer, outHandle: Pointer): Int
    fun MT_SetConfig_INT(handle: Pointer, type: Int, data: Pointer, len: Int): Int
    fun MT_Process_INT(handle: Pointer, processType: Int, points: Pointer, count: Int): Int

    companion object {
        fun load(): HikmicroMtlibIntLibrary = Native.load("MTlib", HikmicroMtlibIntLibrary::class.java)
    }
}

data class HikmicroMtlibQ13(
    val atmosphericQ13: Int,
    val humidityQ13: Int,
    val windowTransQ13: Int,
    val windowTempMilliC: Int,
    val emissivityQ13: Int,
    val reflectedQ13: Int,
    val distanceQ13: Int,
) {
    fun isComplete(): Boolean = listOf(
        atmosphericQ13,
        humidityQ13,
        windowTransQ13,
        windowTempMilliC,
        emissivityQ13,
        reflectedQ13,
        distanceQ13,
    ).all { it != Int.MIN_VALUE }
}

data class HikmicroMtlibProvenance(
    val calibrationSha256: String,
    val q13Source: String,
    val addlineSource: String,
    val abi: String = HikmicroMtlibIntConverter.PROVED_ABI,
    val nativeReturnCodes: List<HikmicroMtlibNativeReturn> = emptyList(),
    val selfTestState: HikmicroMtlibSelfTestState = HikmicroMtlibSelfTestState.NOT_RUN,
    val failClosedReason: String? = null,
)

data class HikmicroMtlibNativeReturn(val call: String, val code: Int)

enum class HikmicroMtlibSelfTestState { NOT_RUN, PASSED, FAILED }

enum class HikmicroMtlibPublishState { PUBLISHABLE, BLOCKED }

data class HikmicroMtlibLiveFrame(
    val rawGray: IntArray?,
    val tag1Addline: ByteArray?,
    val tag519Calibration: ByteArray?,
    val q13: HikmicroMtlibQ13?,
    val provenance: HikmicroMtlibProvenance,
) {
    fun missingReason(): String? {
        if (rawGray == null) return "missing_live_raw_matrix"
        if (rawGray.size != MTLIB_PIXELS) return "invalid_live_raw_matrix_size=${rawGray.size}"
        if (tag1Addline == null) return "missing_live_tag1_addline"
        if (tag1Addline.size != 1024) return "invalid_live_tag1_addline_size=${tag1Addline.size}"
        if (tag519Calibration == null) return "missing_live_tag519_calibration"
        if (tag519Calibration.size != MTLIB_TAG519_SIZE) {
            return "invalid_live_tag519_calibration_size=${tag519Calibration.size}"
        }
        if (q13 == null || !q13.isComplete()) return "missing_live_q13_parameters"
        if (provenance.calibrationSha256.isBlank()) return "missing_calibration_sha256"
        if (sha256(tag519Calibration) != provenance.calibrationSha256) return "calibration_sha256_mismatch"
        if (provenance.q13Source.isBlank()) return "missing_q13_source"
        if (provenance.addlineSource.isBlank()) return "missing_addline_source"
        return null
    }
}

data class HikmicroMtlibConversionResult(
    val state: HikmicroMtlibPublishState,
    val temperatureC: DoubleArray? = null,
    val provenance: HikmicroMtlibProvenance,
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is HikmicroMtlibConversionResult) return false
        return state == other.state &&
            provenance == other.provenance &&
            if (temperatureC == null) other.temperatureC == null else other.temperatureC?.let { temperatureC.contentEquals(it) } == true
    }

    override fun hashCode(): Int = 31 * state.hashCode() + (temperatureC?.contentHashCode() ?: 0) + provenance.hashCode()
}

data class HikmicroMtlibSelfTestReport(
    val state: HikmicroMtlibSelfTestState,
    val fixtureId: String,
    val nativeReturnCodes: List<HikmicroMtlibNativeReturn>,
    val failClosedReason: String? = null,
    val comparedPixels: Int = 0,
    val uniqueGrayCount: Int = 0,
)

internal interface HikmicroMtlibEngine {
    val nativeReturnCodes: List<HikmicroMtlibNativeReturn>
    fun configureStatic(tag519: ByteArray, q13: HikmicroMtlibQ13)
    fun configureFrame(tag1: ByteArray)
    fun processSingleGrayX64(gray: Int, q13: HikmicroMtlibQ13): Int
}

internal interface HikmicroMtlibNativeCalls {
    fun getMemSize(params: Pointer, memDesc: Pointer): Int
    fun create(params: Pointer, memDesc: Pointer, outHandle: Pointer): Int
    fun setConfig(handle: Pointer, type: Int, data: Pointer, len: Int): Int
    fun process(handle: Pointer, processType: Int, points: Pointer, count: Int): Int
}

internal class HikmicroMtlibJnaCalls(private val library: HikmicroMtlibIntLibrary) : HikmicroMtlibNativeCalls {
    override fun getMemSize(params: Pointer, memDesc: Pointer): Int = library.MT_GetMemSize_INT(params, memDesc)
    override fun create(params: Pointer, memDesc: Pointer, outHandle: Pointer): Int = library.MT_Create_INT(params, memDesc, outHandle)
    override fun setConfig(handle: Pointer, type: Int, data: Pointer, len: Int): Int = library.MT_SetConfig_INT(handle, type, data, len)
    override fun process(handle: Pointer, processType: Int, points: Pointer, count: Int): Int = library.MT_Process_INT(handle, processType, points, count)
}

internal data class HikmicroMtlibDescriptorLayout(
    val base0Address: Long,
    val size0: Int,
    val base1Address: Long,
    val size1: Int,
)

internal data class HikmicroMtlibDescriptorPlan(
    val base0PointerOffset: Long,
    val base0Address: Long,
    val size0Offset: Long,
    val size0: Int,
    val alignment0Offset: Long,
    val alignment: Int,
    val countOffset: Long,
    val count: Int,
    val base1PointerOffset: Long,
    val base1Address: Long,
    val size1Offset: Long,
    val size1: Int,
    val alignment1Offset: Long,
    val zeroOffset: Long,
    val zero: Int,
)

internal data class HikmicroMtlibMemoryDescriptor(
    val backing: Memory,
    val descriptor: Memory,
    val base0: Pointer,
    val size0: Int,
    val base1: Pointer,
    val size1: Int,
)

internal data class HikmicroMtlibProbeCreateResult<D : Any>(
    val probeDescriptor: D,
    val createDescriptor: D?,
    val getMemSizeReturnCode: Int,
    val createReturnCode: Int?,
)

/**
 * Runs the proved two-descriptor lifecycle without depending on JNA types.
 * MT_GetMemSize_INT may mutate its disposable descriptor, so MT_Create_INT must receive a newly
 * allocated and initialized descriptor/backing pair. Retainers preserve both allocations.
 */
internal fun <D : Any> hikmicroMtlibProbeThenCreate(
    allocateDescriptor: () -> D,
    retainProbeDescriptor: (D) -> Unit,
    getMemSize: (D) -> Int,
    retainCreateDescriptor: (D) -> Unit,
    create: (D) -> Int,
): HikmicroMtlibProbeCreateResult<D> {
    val probeDescriptor = allocateDescriptor().also(retainProbeDescriptor)
    val getMemSizeReturnCode = getMemSize(probeDescriptor)
    if (getMemSizeReturnCode != 0) {
        return HikmicroMtlibProbeCreateResult(
            probeDescriptor = probeDescriptor,
            createDescriptor = null,
            getMemSizeReturnCode = getMemSizeReturnCode,
            createReturnCode = null,
        )
    }

    val createDescriptor = allocateDescriptor().also(retainCreateDescriptor)
    check(probeDescriptor !== createDescriptor) {
        "MT_Create_INT requires a fresh descriptor/backing allocation after MT_GetMemSize_INT"
    }
    return HikmicroMtlibProbeCreateResult(
        probeDescriptor = probeDescriptor,
        createDescriptor = createDescriptor,
        getMemSizeReturnCode = getMemSizeReturnCode,
        createReturnCode = create(createDescriptor),
    )
}

internal class HikmicroMtlibIntSession(private val nativeCalls: HikmicroMtlibNativeCalls) : HikmicroMtlibEngine {
    private val params = Memory(MTLIB_PARAMS_SIZE)
    private val outHandle = Memory(Native.POINTER_SIZE.toLong())
    private val configKeepAlive = LinkedHashMap<String, Memory>()
    private val point = Memory(MTLIB_POINT_SIZE_ANDROID)
    private var probeDescriptorKeepAlive: HikmicroMtlibMemoryDescriptor? = null
    private var createDescriptorKeepAlive: HikmicroMtlibMemoryDescriptor? = null
    private var handle: Pointer? = null

    override val nativeReturnCodes: MutableList<HikmicroMtlibNativeReturn> = mutableListOf()

    @Synchronized
    fun ensureHandle(): Pointer {
        handle?.let { return it }
        params.clear(MTLIB_PARAMS_SIZE)
        params.setInt(0, MTLIB_WIDTH)
        params.setInt(4, MTLIB_HEIGHT)
        params.setInt(8, 1)
        params.setInt(12, 1)
        outHandle.clear(Native.POINTER_SIZE.toLong())
        val descriptorResult = hikmicroMtlibProbeThenCreate(
            allocateDescriptor = ::allocateMemoryDescriptor,
            retainProbeDescriptor = { probeDescriptorKeepAlive = it },
            getMemSize = { probe ->
                nativeCalls.getMemSize(params, probe.descriptor).also { ret ->
                    nativeReturnCodes += HikmicroMtlibNativeReturn("MT_GetMemSize_INT", ret)
                }
            },
            retainCreateDescriptor = { createDescriptorKeepAlive = it },
            create = { createDescriptor ->
                nativeCalls.create(params, createDescriptor.descriptor, outHandle).also { ret ->
                    nativeReturnCodes += HikmicroMtlibNativeReturn("MT_Create_INT", ret)
                }
            },
        )
        if (descriptorResult.getMemSizeReturnCode != 0) {
            error("MT_GetMemSize_INT failed ret=${descriptorResult.getMemSizeReturnCode}")
        }
        val ret = descriptorResult.createReturnCode
            ?: error("MT_Create_INT was not invoked with a fresh descriptor")
        val created = outHandle.getPointer(0)
        if (ret != 0 || created == null || Pointer.nativeValue(created) == 0L) {
            error("MT_Create_INT failed ret=$ret handle=${created?.let { Pointer.nativeValue(it) }}")
        }
        handle = created
        return created
    }

    @Synchronized
    override fun configureStatic(tag519: ByteArray, q13: HikmicroMtlibQ13) {
        requireHikmicroMtlibTag519(tag519)
        val h = ensureHandle()
        setConfigRetaining(h, 6, tag519, "type6_tag519", tolerateRetMinus18 = false)
        val keyValues = listOf(
            13 to 0,
            45 to 1,
            29 to 0,
            55 to 0,
            14 to 0,
            5 to q13.atmosphericQ13,
            6 to q13.humidityQ13,
            20 to q13.windowTransQ13,
            21 to q13.windowTempMilliC,
            152 to 1,
        )
        keyValues.forEach { (key, value) ->
            setConfigRetaining(h, 1, type1Payload(key, value), "type1_key$key", tolerateRetMinus18 = key == 55)
        }
    }

    @Synchronized
    override fun configureFrame(tag1: ByteArray) {
        require(tag1.size == 1024) { "tag1/addline must be exactly 1024 bytes" }
        val h = ensureHandle()
        val tag1Word284 = u16Le(tag1, 284 * 2)
        setConfigRetaining(h, 189, u32Payload(tag1Word284, 0, 0, 0), "type189_tag1_word284", tolerateRetMinus18 = false)
        setConfigRetaining(h, 12, tag1, "type12_tag1_addline", tolerateRetMinus18 = false)
    }

    @Synchronized
    override fun processSingleGrayX64(gray: Int, q13: HikmicroMtlibQ13): Int {
        val h = ensureHandle()
        point.clear(MTLIB_POINT_SIZE_ANDROID)
        point.setInt(0x04L, gray)
        point.setInt(0x14L, q13.emissivityQ13)
        point.setInt(0x18L, q13.reflectedQ13)
        point.setInt(0x1cL, q13.distanceQ13)
        val ret = nativeCalls.process(h, 0, point, 1)
        nativeReturnCodes += HikmicroMtlibNativeReturn("MT_Process_INT", ret)
        if (ret != 0) error("MT_Process_INT failed ret=$ret gray=$gray")
        return point.getInt(0x10L)
    }

    private fun setConfigRetaining(handle: Pointer, type: Int, data: ByteArray, label: String, tolerateRetMinus18: Boolean) {
        val memory = Memory(data.size.toLong())
        memory.write(0, data, 0, data.size)
        val ret = nativeCalls.setConfig(handle, type, memory, data.size)
        nativeReturnCodes += HikmicroMtlibNativeReturn("MT_SetConfig_INT:$label", ret)
        if (ret != 0 && !(tolerateRetMinus18 && ret == -18)) {
            error("MT_SetConfig_INT failed for $label ret=$ret")
        }
        configKeepAlive[label] = memory
    }

    companion object {
        fun allocateMemoryDescriptor(totalSize: Long = MTLIB_BACKING_SIZE): HikmicroMtlibMemoryDescriptor {
            val backing = Memory(totalSize + 0x400L)
            val rawAddress = Pointer.nativeValue(backing)
            val plan = createMemoryDescriptorPlan(rawAddress, backing.size())
            val base0 = backing.share(plan.base0Address - rawAddress)
            val base1 = backing.share(plan.base1Address - rawAddress)
            val desc = Memory(MTLIB_DESC_SIZE)
            desc.clear(MTLIB_DESC_SIZE)
            desc.setPointer(plan.base0PointerOffset, base0)
            desc.setInt(plan.size0Offset, plan.size0)
            desc.setInt(plan.alignment0Offset, plan.alignment)
            desc.setInt(plan.countOffset, plan.count)
            desc.setPointer(plan.base1PointerOffset, base1)
            desc.setInt(plan.size1Offset, plan.size1)
            desc.setInt(plan.alignment1Offset, plan.alignment)
            desc.setInt(plan.zeroOffset, plan.zero)
            return HikmicroMtlibMemoryDescriptor(
                backing = backing,
                descriptor = desc,
                base0 = base0,
                size0 = plan.size0,
                base1 = base1,
                size1 = plan.size1,
            )
        }

        fun createMemoryDescriptorPlan(rawAddress: Long, backingSize: Long): HikmicroMtlibDescriptorPlan {
            val layout = calculateDescriptorLayout(rawAddress, backingSize)
            return HikmicroMtlibDescriptorPlan(
                base0PointerOffset = 0x00L,
                base0Address = layout.base0Address,
                size0Offset = 0x08L,
                size0 = layout.size0,
                alignment0Offset = 0x0cL,
                alignment = MTLIB_ALIGNMENT.toInt(),
                countOffset = 0x14L,
                count = 1,
                base1PointerOffset = 0x18L,
                base1Address = layout.base1Address,
                size1Offset = 0x20L,
                size1 = layout.size1,
                alignment1Offset = 0x24L,
                zeroOffset = 0x2cL,
                zero = 0,
            )
        }

        fun calculateDescriptorLayout(rawAddress: Long, backingSize: Long): HikmicroMtlibDescriptorLayout {
            val base0Address = align128(rawAddress)
            val base1Address = align128(base0Address + 0x500L + 0x3d00L)
            val endAddress = rawAddress + backingSize
            val size0 = ((base1Address - base0Address) and (MTLIB_ALIGNMENT - 1L).inv()).toInt()
            val size1 = ((endAddress - base1Address) and (MTLIB_ALIGNMENT - 1L).inv()).toInt()
            require(size0 > 0 && size1 > 0) { "invalid MTlib descriptor sizes size0=$size0 size1=$size1" }
            return HikmicroMtlibDescriptorLayout(base0Address, size0, base1Address, size1)
        }
    }
}

class HikmicroMtlibIntConverter internal constructor(
    private val engine: HikmicroMtlibEngine,
    initialSelfTestState: HikmicroMtlibSelfTestState = HikmicroMtlibSelfTestState.NOT_RUN,
) {
    private var currentSelfTestState: HikmicroMtlibSelfTestState = initialSelfTestState
    private var currentSelfTestFailure: String? = null

    fun convertLive(frame: HikmicroMtlibLiveFrame): HikmicroMtlibConversionResult {
        val snapshot = frame.copy(
            rawGray = frame.rawGray?.copyOf(),
            tag1Addline = frame.tag1Addline?.copyOf(),
            tag519Calibration = frame.tag519Calibration?.copyOf(),
        )
        val missing = snapshot.missingReason()
        if (missing != null) return blocked(snapshot.provenance, missing)
        if (currentSelfTestState != HikmicroMtlibSelfTestState.PASSED) {
            return blocked(
                snapshot.provenance.copy(selfTestState = currentSelfTestState),
                currentSelfTestFailure ?: "android_mtlib_fixture_self_test_not_passed",
            )
        }
        return runCatching {
            convertValidated(
                rawGray = snapshot.rawGray ?: error("validated raw missing"),
                tag1 = snapshot.tag1Addline ?: error("validated tag1 missing"),
                tag519 = snapshot.tag519Calibration ?: error("validated tag519 missing"),
                q13 = snapshot.q13 ?: error("validated q13 missing"),
            )
        }.fold(
            onSuccess = { temps ->
                HikmicroMtlibConversionResult(
                    state = HikmicroMtlibPublishState.PUBLISHABLE,
                    temperatureC = temps,
                    provenance = snapshot.provenance.copy(
                        nativeReturnCodes = engine.nativeReturnCodes.toList(),
                        selfTestState = currentSelfTestState,
                        failClosedReason = null,
                    ),
                )
            },
            onFailure = { blocked(snapshot.provenance, "native_conversion_failed:${it.message}") },
        )
    }

    fun runFixtureSelfTest(context: Context): HikmicroMtlibSelfTestReport = runFixtureSelfTest(
        AssetFixtureLoader(context, "hikmicro/mtlib-fixture/IR_00001"),
    )

    internal fun runFixtureSelfTest(loader: HikmicroMtlibFixtureLoader): HikmicroMtlibSelfTestReport {
        val fixtureId = "IR_00001"
        return runCatching {
            val fixture = loader.load()
            fixture.verifyChecksums()
            val converted = convertValidated(fixture.rawGray, fixture.tag1Addline, fixture.tag519Calibration, fixture.q13)
            val convertedX64 = converted.map { (it * 64.0).toInt() }.toIntArray()
            fixture.expectedFirst32.forEachIndexed { index, expected ->
                check(fixture.rawGray[index] == expected.gray) { "fixture raw[$index] expected gray ${expected.gray} got ${fixture.rawGray[index]}" }
                check(convertedX64[index] == expected.temperatureX64) {
                    "fixture x64[$index] expected ${expected.temperatureX64} got ${convertedX64[index]}"
                }
            }
            val min = convertedX64.minOrNull() ?: error("empty conversion")
            val max = convertedX64.maxOrNull() ?: error("empty conversion")
            check(min == fixture.expectedTempX64Min && max == fixture.expectedTempX64Max) {
                "fixture x64 min/max expected ${fixture.expectedTempX64Min}/${fixture.expectedTempX64Max} got $min/$max"
            }
            val mean = converted.average()
            check(abs(mean - fixture.expectedTempCMean) <= fixture.meanTolerance) {
                "fixture mean expected ${fixture.expectedTempCMean} got $mean"
            }
            currentSelfTestState = HikmicroMtlibSelfTestState.PASSED
            currentSelfTestFailure = null
            HikmicroMtlibSelfTestReport(
                state = HikmicroMtlibSelfTestState.PASSED,
                fixtureId = fixtureId,
                nativeReturnCodes = engine.nativeReturnCodes.toList(),
                comparedPixels = converted.size,
                uniqueGrayCount = fixture.rawGray.toSet().size,
            )
        }.getOrElse {
            currentSelfTestState = HikmicroMtlibSelfTestState.FAILED
            currentSelfTestFailure = "fixture_self_test_failed:${it.message}"
            HikmicroMtlibSelfTestReport(
                state = HikmicroMtlibSelfTestState.FAILED,
                fixtureId = fixtureId,
                nativeReturnCodes = engine.nativeReturnCodes.toList(),
                failClosedReason = currentSelfTestFailure,
            )
        }
    }

    private fun convertValidated(rawGray: IntArray, tag1: ByteArray, tag519: ByteArray, q13: HikmicroMtlibQ13): DoubleArray {
        require(rawGray.size == MTLIB_PIXELS) { "raw matrix must have $MTLIB_PIXELS pixels" }
        require(tag1.size == 1024) { "tag1/addline must be exactly 1024 bytes" }
        requireHikmicroMtlibTag519(tag519)
        require(q13.isComplete()) { "q13 parameters must be complete" }
        engine.configureStatic(tag519, q13)
        engine.configureFrame(tag1)
        val unique = LinkedHashMap<Int, Int>()
        rawGray.forEach { gray -> unique.putIfAbsent(gray and 0xffff, 0) }
        unique.keys.forEach { gray -> unique[gray] = engine.processSingleGrayX64(gray, q13) }
        return DoubleArray(rawGray.size) { index -> (unique[rawGray[index] and 0xffff] ?: error("missing converted gray")) / 64.0 }
    }

    private fun blocked(provenance: HikmicroMtlibProvenance, reason: String): HikmicroMtlibConversionResult =
        HikmicroMtlibConversionResult(
            state = HikmicroMtlibPublishState.BLOCKED,
            temperatureC = null,
            provenance = provenance.copy(
                nativeReturnCodes = engine.nativeReturnCodes.toList(),
                failClosedReason = reason,
            ),
        )

    companion object {
        const val PROVED_ABI: String =
            "MT_GetMemSize_INT(params,mem_desc); MT_Create_INT(params,mem_desc,out_handle); " +
                "MT_SetConfig_INT(handle,type,data,len); MT_Process_INT(handle,process_type,point,count); " +
                "Android point stride 0x20 count=1 gray+0x04 out_x64+0x10 q13+0x14/+0x18/+0x1c"

        fun create(library: HikmicroMtlibIntLibrary = HikmicroMtlibIntLibrary.load()): HikmicroMtlibIntConverter =
            HikmicroMtlibIntConverter(HikmicroMtlibIntSession(HikmicroMtlibJnaCalls(library)))

        internal fun createForTests(
            engine: HikmicroMtlibEngine,
            initialSelfTestState: HikmicroMtlibSelfTestState = HikmicroMtlibSelfTestState.NOT_RUN,
        ): HikmicroMtlibIntConverter = HikmicroMtlibIntConverter(engine, initialSelfTestState)
    }
}

internal data class HikmicroMtlibExpectedPoint(val gray: Int, val temperatureX64: Int)

internal data class HikmicroMtlibFixture(
    val rawGray: IntArray,
    val tag1Addline: ByteArray,
    val tag519Calibration: ByteArray,
    val q13: HikmicroMtlibQ13,
    val expectedFirst32: List<HikmicroMtlibExpectedPoint>,
    val expectedTempX64Min: Int,
    val expectedTempX64Max: Int,
    val expectedTempCMean: Double,
    val meanTolerance: Double,
    val fileChecksums: Map<String, String>,
    val fileBytes: Map<String, Int>,
    private val bytesByName: Map<String, ByteArray>,
) {
    fun verifyChecksums() {
        fileChecksums.forEach { (name, sha) ->
            val bytes = bytesByName[name] ?: error("missing fixture asset $name")
            check(bytes.size == fileBytes.getValue(name)) { "fixture $name byte size changed" }
            check(sha256(bytes) == sha) { "fixture $name checksum mismatch" }
        }
    }

    override fun equals(other: Any?): Boolean = this === other
    override fun hashCode(): Int = System.identityHashCode(this)
}

internal interface HikmicroMtlibFixtureLoader {
    fun load(): HikmicroMtlibFixture
}

internal class AssetFixtureLoader(private val context: Context, private val base: String) : HikmicroMtlibFixtureLoader {
    override fun load(): HikmicroMtlibFixture = parseFixture { name -> context.assets.open("$base/$name") }
}

internal fun parseFixture(open: (String) -> InputStream): HikmicroMtlibFixture {
    val manifest = open("manifest.json").use { it.readBytes().decodeToString() }
    fun manifestString(key: String): String = Regex("\"$key\"\\s*:\\s*\"([^\"]+)\"").find(manifest)?.groupValues?.get(1)
        ?: error("manifest missing $key")
    fun manifestInt(key: String): Int = Regex("\"$key\"\\s*:\\s*(-?\\d+)").find(manifest)?.groupValues?.get(1)?.toInt()
        ?: error("manifest missing $key")
    fun manifestDouble(key: String): Double = Regex("\"$key\"\\s*:\\s*(-?\\d+(?:\\.\\d+)?)").find(manifest)?.groupValues?.get(1)?.toDouble()
        ?: error("manifest missing $key")

    val names = listOf("raw_u16_256x192_le.bin", "tag1_addline.bin", "tag519.bin", "expected_first32_x64.bin")
    val bytesByName = names.associateWith { name -> open(name).use { it.readBytes() } }
    val checksums = names.associateWith { name -> manifestFileValue(manifest, name, "sha256") }
    val sizes = names.associateWith { name -> manifestFileValue(manifest, name, "bytes").toInt() }
    val raw = bytesToU16Array(bytesByName.getValue("raw_u16_256x192_le.bin"))
    val expected = parseExpectedFirst32(bytesByName.getValue(manifestString("first32_binary")))
    return HikmicroMtlibFixture(
        rawGray = raw,
        tag1Addline = bytesByName.getValue("tag1_addline.bin"),
        tag519Calibration = bytesByName.getValue("tag519.bin"),
        q13 = HikmicroMtlibQ13(
            atmosphericQ13 = manifestInt("atmospheric_q13"),
            humidityQ13 = manifestInt("humidity_q13"),
            windowTransQ13 = manifestInt("window_trans_q13"),
            windowTempMilliC = manifestInt("window_temp_milli_c"),
            emissivityQ13 = manifestInt("emissivity_q13"),
            reflectedQ13 = manifestInt("reflected_q13"),
            distanceQ13 = manifestInt("distance_q13"),
        ),
        expectedFirst32 = expected,
        expectedTempX64Min = manifestArrayInt(manifest, "temp_x64_minmax", 0),
        expectedTempX64Max = manifestArrayInt(manifest, "temp_x64_minmax", 1),
        expectedTempCMean = manifestDouble("temp_c_mean"),
        meanTolerance = manifestDouble("temp_c_mean_abs_tolerance"),
        fileChecksums = checksums,
        fileBytes = sizes,
        bytesByName = bytesByName,
    )
}

internal fun packAndroidPointRecord(gray: Int, q13: HikmicroMtlibQ13): ByteArray {
    val buffer = ByteBuffer.allocate(MTLIB_POINT_SIZE_ANDROID.toInt()).order(ByteOrder.LITTLE_ENDIAN)
    buffer.putInt(0x04, gray)
    buffer.putInt(0x14, q13.emissivityQ13)
    buffer.putInt(0x18, q13.reflectedQ13)
    buffer.putInt(0x1c, q13.distanceQ13)
    return buffer.array()
}

internal fun type1Payload(key: Int, value: Int): ByteArray = u32Payload(key, value)

internal fun requireHikmicroMtlibTag519(tag519: ByteArray) {
    require(tag519.size == MTLIB_TAG519_SIZE) {
        "tag519 calibration must be exactly $MTLIB_TAG519_SIZE bytes (0x3800), got ${tag519.size}"
    }
}

private fun u32Payload(vararg values: Int): ByteArray = ByteBuffer.allocate(values.size * 4).order(ByteOrder.LITTLE_ENDIAN).apply {
    values.forEach { putInt(it) }
}.array()

private fun parseExpectedFirst32(bytes: ByteArray): List<HikmicroMtlibExpectedPoint> {
    require(bytes.size % 6 == 0) { "expected vector record bytes must be divisible by 6" }
    val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
    return List(bytes.size / 6) {
        HikmicroMtlibExpectedPoint(gray = buffer.short.toInt() and 0xffff, temperatureX64 = buffer.int)
    }
}

private fun bytesToU16Array(bytes: ByteArray): IntArray {
    require(bytes.size == MTLIB_PIXELS * 2) { "raw fixture must be ${MTLIB_PIXELS * 2} bytes" }
    val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
    return IntArray(MTLIB_PIXELS) { buffer.short.toInt() and 0xffff }
}

private fun u16Le(bytes: ByteArray, offset: Int): Int =
    (bytes[offset].toInt() and 0xff) or ((bytes[offset + 1].toInt() and 0xff) shl 8)

private fun align128(value: Long): Long = (value + 0x7fL) and 0x7fL.inv()

private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
    .digest(bytes)
    .joinToString("") { "%02x".format(it) }

private fun manifestFileValue(manifest: String, fileName: String, field: String): String {
    val block = Regex("\"${Regex.escape(fileName)}\"\\s*:\\s*\\{([^}]*)}").find(manifest)?.groupValues?.get(1)
        ?: error("manifest missing file $fileName")
    return Regex("\"$field\"\\s*:\\s*(?:\"([^\"]+)\"|(\\d+))").find(block)?.let {
        it.groupValues[1].ifBlank { it.groupValues[2] }
    } ?: error("manifest missing $fileName.$field")
}

private fun manifestArrayInt(manifest: String, key: String, index: Int): Int {
    val values = Regex("\"$key\"\\s*:\\s*\\[([^]]+)]").find(manifest)?.groupValues?.get(1)
        ?: error("manifest missing $key")
    return values.split(',').map { it.trim().toDouble().toInt() }[index]
}
