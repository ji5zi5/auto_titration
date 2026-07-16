package kr.auto.titration.mobile.thermal

/**
 * Evidence-gated parser for the device-reported temperature summary embedded in
 * coding-12 OFFLINE_UPLOAD_HEADER packets.
 *
 * This parses only USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE's packed
 * little-endian IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO at header offset 120. The
 * values are device summary/global/ROI metadata only; they are not evidence for
 * a full Celsius matrix.
 */
object HikmicroF2TemperatureMetadataParser {
    const val OFFLINE_UPLOAD_HEADER_BYTES: Int = 7_368
    const val OUTCOME_UPLOAD_OFFSET: Int = 120
    const val OUTCOME_UPLOAD_BYTES: Int = 4_516
    const val OUTCOME_RECORD_OFFSET: Int = OUTCOME_UPLOAD_OFFSET + 96
    const val OUTCOME_RECORD_BYTES: Int = 208
    const val MAX_OUTCOME_RECORDS: Int = 21

    fun parseOfflineUploadHeader(header: ByteArray): HikmicroF2TemperatureMetadata {
        if (header.size < OFFLINE_UPLOAD_HEADER_BYTES) {
            return blocked("truncated_offline_upload_header", "${header.size} bytes is shorter than the proved 7368-byte OFFLINE_UPLOAD_HEADER")
        }
        if (header.size != OFFLINE_UPLOAD_HEADER_BYTES) {
            return blocked("unexpected_offline_upload_header_size", "${header.size} bytes is not the exact proved 7368-byte OFFLINE_UPLOAD_HEADER")
        }
        if (OUTCOME_UPLOAD_OFFSET + OUTCOME_UPLOAD_BYTES > header.size) {
            return blocked("outcome_upload_info_out_of_bounds", "IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO exceeds header bounds")
        }

        return try {
            parseChecked(header)
        } catch (error: MetadataParseException) {
            blocked(error.code, error.message ?: error.code)
        }
    }

    private fun parseChecked(header: ByteArray): HikmicroF2TemperatureMetadata {
        val unitCode = header.i32(OUTCOME_UPLOAD_OFFSET + 0)
        // Official d3.i coding-12 parsing proves fTmp/fMinTmp/fMaxTmp/fAvrTmp packet
        // floats are already base Celsius. enumTempUnit is a requested display unit:
        // 0 leaves C unchanged, 1 displays C->F, and 2 displays C->K. Unknown unit
        // codes therefore fail closed for validated Celsius instead of guessing.
        val requestedDisplayUnit = HikmicroF2TemperatureUnit.fromDeviceCode(unitCode)
        val reflectedTemperatureRawCelsius = header.f32Finite(OUTCOME_UPLOAD_OFFSET + 12, "reflected_temperature")
        val environmentTemperatureRawCelsius = header.f32Finite(OUTCOME_UPLOAD_OFFSET + 20, "environment_temperature")
        val minTemperatureRawCelsius = header.f32Finite(OUTCOME_UPLOAD_OFFSET + 24, "global_min_temperature")
        val maxTemperatureRawCelsius = header.f32Finite(OUTCOME_UPLOAD_OFFSET + 28, "global_max_temperature")
        val avgTemperatureRawCelsius = header.f32Finite(OUTCOME_UPLOAD_OFFSET + 32, "global_avg_temperature")
        val global = HikmicroF2DeviceGlobalSummary(
            enumTempUnit = unitCode,
            nativeUnit = requestedDisplayUnit,
            byRefTempKey = header.u8(OUTCOME_UPLOAD_OFFSET + 4),
            distance = header.f32Finite(OUTCOME_UPLOAD_OFFSET + 8, "distance"),
            reflectedTemperatureNative = reflectedTemperatureRawCelsius,
            reflectedTemperatureCelsius = requestedDisplayUnit?.validatedRawCelsius(reflectedTemperatureRawCelsius),
            reflectedTemperatureRequestedDisplay = requestedDisplayUnit?.fromCelsius(reflectedTemperatureRawCelsius),
            emissivity = header.f32Finite(OUTCOME_UPLOAD_OFFSET + 16, "emissivity"),
            environmentTemperatureNative = environmentTemperatureRawCelsius,
            environmentTemperatureCelsius = requestedDisplayUnit?.validatedRawCelsius(environmentTemperatureRawCelsius),
            environmentTemperatureRequestedDisplay = requestedDisplayUnit?.fromCelsius(environmentTemperatureRawCelsius),
            minTemperatureNative = minTemperatureRawCelsius,
            minTemperatureCelsius = requestedDisplayUnit?.validatedRawCelsius(minTemperatureRawCelsius),
            minTemperatureRequestedDisplay = requestedDisplayUnit?.fromCelsius(minTemperatureRawCelsius),
            maxTemperatureNative = maxTemperatureRawCelsius,
            maxTemperatureCelsius = requestedDisplayUnit?.validatedRawCelsius(maxTemperatureRawCelsius),
            maxTemperatureRequestedDisplay = requestedDisplayUnit?.fromCelsius(maxTemperatureRawCelsius),
            avgTemperatureNative = avgTemperatureRawCelsius,
            avgTemperatureCelsius = requestedDisplayUnit?.validatedRawCelsius(avgTemperatureRawCelsius),
            avgTemperatureRequestedDisplay = requestedDisplayUnit?.fromCelsius(avgTemperatureRawCelsius),
            points = (0 until 3).map { index -> header.point(OUTCOME_UPLOAD_OFFSET + 36 + index * 8, "global_point_$index") },
            u32TempMode = header.i32(OUTCOME_UPLOAD_OFFSET + 60),
            pointCount = header.u8(OUTCOME_UPLOAD_OFFSET + 84),
            boxCount = header.u8(OUTCOME_UPLOAD_OFFSET + 85),
            lineCount = header.u8(OUTCOME_UPLOAD_OFFSET + 86),
            totalCount = header.u8(OUTCOME_UPLOAD_OFFSET + 87),
            uploadType = header.i32(OUTCOME_UPLOAD_OFFSET + 4464),
            crcValue = header.i32(OUTCOME_UPLOAD_OFFSET + 4512),
        )

        if (global.pointCount > 3) fail("global_point_count_overflow", "global pointNum ${global.pointCount} exceeds IFR_POINT[3]")
        if (global.totalCount > MAX_OUTCOME_RECORDS) fail("outcome_total_overflow", "total ${global.totalCount} exceeds IFR_OUTCOME_INFO[21]")
        if (global.pointCount + global.boxCount + global.lineCount > global.totalCount) {
            fail(
                "outcome_count_relationship_invalid",
                "point/box/line counts ${global.pointCount}/${global.boxCount}/${global.lineCount} exceed total ${global.totalCount}",
            )
        }
        if (!ordered(global.minTemperatureNative, global.avgTemperatureNative, global.maxTemperatureNative)) {
            fail("global_temperature_relationship_invalid", "global min/avg/max are not ordered")
        }
        global.points.take(global.pointCount).forEachIndexed { index, point -> point.requireBounds("global_point_$index") }

        val roi = mutableListOf<HikmicroF2DeviceExpertRoiSummary>()
        for (index in 0 until global.totalCount) {
            val offset = OUTCOME_RECORD_OFFSET + index * OUTCOME_RECORD_BYTES
            roi += header.outcome(index, offset, requestedDisplayUnit)
        }

        return HikmicroF2TemperatureMetadata(
            deviceGlobalSummary = global,
            deviceExpertRoiSummary = roi.filter { it.enabled },
            blockedInvalidMetadata = null,
        )
    }

    private fun ByteArray.outcome(
        index: Int,
        offset: Int,
        requestedDisplayUnit: HikmicroF2TemperatureUnit?,
    ): HikmicroF2DeviceExpertRoiSummary {
        val enabled = u8(offset + 0) != 0
        val regionId = u8(offset + 1)
        val regionTypeCode = i32(offset + 36)
        val regionType = HikmicroF2RegionType.fromDeviceCode(regionTypeCode)
        val pointCount = i32(offset + 108)
        if (pointCount !in 0..12) {
            fail("roi_point_count_overflow", "ROI[$index] pointNum $pointCount exceeds recod[12]")
        }
        if (enabled && regionType == null) {
            fail("unknown_roi_region_type", "ROI[$index] enabled with unsupported regiontype $regionTypeCode")
        }

        val endpoint0 = point(offset + 92, "roi_${index}_point_0")
        val endpoint1 = point(offset + 100, "roi_${index}_point_1")
        val polygon = (0 until pointCount).map { recodIndex -> point(offset + 112 + recodIndex * 8, "roi_${index}_recod_$recodIndex") }
        if (enabled) {
            endpoint0.requireBounds("roi_${index}_point_0")
            endpoint1.requireBounds("roi_${index}_point_1")
            polygon.forEachIndexed { recodIndex, point -> point.requireBounds("roi_${index}_recod_$recodIndex") }
            requireRegionLayout(index, regionType, pointCount)
        }

        val min = f32Finite(offset + 76, "roi_${index}_min_temperature")
        val max = f32Finite(offset + 80, "roi_${index}_max_temperature")
        val avg = f32Finite(offset + 84, "roi_${index}_avg_temperature")
        if (enabled && !ordered(min, avg, max)) {
            fail("roi_temperature_relationship_invalid", "ROI[$index] min/avg/max are not ordered")
        }

        return HikmicroF2DeviceExpertRoiSummary(
            index = index,
            enabled = enabled,
            regionId = regionId,
            regionTypeCode = regionTypeCode,
            regionType = regionType,
            referenceTemperatureRaw = i32(offset + 4),
            distance = f32Finite(offset + 28, "roi_${index}_distance"),
            maxTemperatureStatus = u8(offset + 33),
            minTemperatureStatus = u8(offset + 34),
            avgTemperatureStatus = u8(offset + 35),
            name = copyOfRange(offset + 40, offset + 72).decodeNullTerminatedAscii(),
            emissivity = f32Finite(offset + 72, "roi_${index}_emissivity"),
            minTemperatureNative = min,
            minTemperatureCelsius = requestedDisplayUnit?.validatedRawCelsius(min),
            minTemperatureRequestedDisplay = requestedDisplayUnit?.fromCelsius(min),
            maxTemperatureNative = max,
            maxTemperatureCelsius = requestedDisplayUnit?.validatedRawCelsius(max),
            maxTemperatureRequestedDisplay = requestedDisplayUnit?.fromCelsius(max),
            avgTemperatureNative = avg,
            avgTemperatureCelsius = requestedDisplayUnit?.validatedRawCelsius(avg),
            avgTemperatureRequestedDisplay = requestedDisplayUnit?.fromCelsius(avg),
            diffTemperatureNative = f32Finite(offset + 88, "roi_${index}_diff_temperature"),
            point0 = endpoint0,
            point1 = endpoint1,
            pointCount = pointCount,
            polygonPoints = polygon,
        )
    }

    private fun requireRegionLayout(index: Int, regionType: HikmicroF2RegionType?, pointCount: Int) {
        when (regionType) {
            HikmicroF2RegionType.BOX -> if (pointCount !in 0..4) fail("roi_box_layout_invalid", "ROI[$index] box pointNum $pointCount exceeds expected box polygon")
            HikmicroF2RegionType.LINE -> if (pointCount !in 0..2) fail("roi_line_layout_invalid", "ROI[$index] line pointNum $pointCount exceeds expected line polygon")
            HikmicroF2RegionType.POINT -> if (pointCount !in 0..1) fail("roi_point_layout_invalid", "ROI[$index] point pointNum $pointCount exceeds expected point polygon")
            null -> Unit
        }
    }

    private fun ByteArray.i32(offset: Int): Int {
        requireRange(offset, 4)
        return (this[offset].toInt() and 0xff) or
            ((this[offset + 1].toInt() and 0xff) shl 8) or
            ((this[offset + 2].toInt() and 0xff) shl 16) or
            ((this[offset + 3].toInt() and 0xff) shl 24)
    }

    private fun ByteArray.u8(offset: Int): Int {
        requireRange(offset, 1)
        return this[offset].toInt() and 0xff
    }

    private fun ByteArray.f32(offset: Int): Float = Float.fromBits(i32(offset))

    private fun ByteArray.f32Finite(offset: Int, field: String): Float {
        val value = f32(offset)
        if (!value.isFinite()) fail("invalid_float", "$field is not finite")
        return value
    }

    private fun ByteArray.point(offset: Int, field: String): HikmicroF2TemperaturePoint =
        HikmicroF2TemperaturePoint(i32(offset), i32(offset + 4)).also {
            if (it.x == Int.MIN_VALUE || it.y == Int.MIN_VALUE) fail("invalid_point", "$field contains impossible sentinel coordinate")
        }

    private fun ByteArray.requireRange(offset: Int, length: Int) {
        if (offset < 0 || length < 0 || offset + length > size) {
            fail("metadata_field_out_of_bounds", "field offset=$offset length=$length exceeds ${size} bytes")
        }
    }

    private fun HikmicroF2TemperaturePoint.requireBounds(field: String) {
        if (x !in 0..1000 || y !in 0..1000) {
            fail("point_out_of_bounds", "$field ($x,$y) is outside proved 0..1000 normalized coordinates")
        }
    }

    private fun ordered(min: Float, avg: Float, max: Float): Boolean = min <= avg && avg <= max

    private fun blocked(code: String, reason: String): HikmicroF2TemperatureMetadata = HikmicroF2TemperatureMetadata(
        deviceGlobalSummary = null,
        deviceExpertRoiSummary = emptyList(),
        blockedInvalidMetadata = HikmicroF2BlockedInvalidMetadata(code, reason),
    )

    private fun fail(code: String, message: String): Nothing = throw MetadataParseException(code, message)

    private fun ByteArray.decodeNullTerminatedAscii(): String {
        val end = indexOf(0.toByte())
        val length = if (end >= 0) end else size
        return copyOfRange(0, length).map { byte ->
            val value = byte.toInt() and 0xff
            if (value in 32..126) value.toChar() else '_'
        }.joinToString("").trim()
    }
}

private class MetadataParseException(val code: String, message: String) : RuntimeException(message)

data class HikmicroF2TemperatureMetadata(
    val deviceGlobalSummary: HikmicroF2DeviceGlobalSummary?,
    val deviceExpertRoiSummary: List<HikmicroF2DeviceExpertRoiSummary>,
    val blockedInvalidMetadata: HikmicroF2BlockedInvalidMetadata?,
) {
    val hasValidatedDeviceCelsiusSummaries: Boolean
        get() = deviceGlobalSummary?.hasCelsius == true || deviceExpertRoiSummary.any { it.hasCelsius }

    val provesFullMatrixCelsius: Boolean get() = false
}

data class HikmicroF2BlockedInvalidMetadata(
    val code: String,
    val reason: String,
) {
    val provenance: String get() = "blocked_invalid_metadata"
}

data class HikmicroF2DeviceGlobalSummary(
    val enumTempUnit: Int,
    val nativeUnit: HikmicroF2TemperatureUnit?,
    val byRefTempKey: Int,
    val distance: Float,
    /** Raw packet field; official coding-12 evidence proves known enumTempUnit 0/1/2 values are base Celsius. */
    val reflectedTemperatureNative: Float,
    val reflectedTemperatureCelsius: Float?,
    val reflectedTemperatureRequestedDisplay: Float?,
    val emissivity: Float,
    /** Raw packet field; official coding-12 evidence proves known enumTempUnit 0/1/2 values are base Celsius. */
    val environmentTemperatureNative: Float,
    val environmentTemperatureCelsius: Float?,
    val environmentTemperatureRequestedDisplay: Float?,
    /** Raw packet field; official coding-12 evidence proves known enumTempUnit 0/1/2 values are base Celsius. */
    val minTemperatureNative: Float,
    val minTemperatureCelsius: Float?,
    val minTemperatureRequestedDisplay: Float?,
    /** Raw packet field; official coding-12 evidence proves known enumTempUnit 0/1/2 values are base Celsius. */
    val maxTemperatureNative: Float,
    val maxTemperatureCelsius: Float?,
    val maxTemperatureRequestedDisplay: Float?,
    /** Raw packet field; official coding-12 evidence proves known enumTempUnit 0/1/2 values are base Celsius. */
    val avgTemperatureNative: Float,
    val avgTemperatureCelsius: Float?,
    val avgTemperatureRequestedDisplay: Float?,
    val points: List<HikmicroF2TemperaturePoint>,
    val u32TempMode: Int,
    val pointCount: Int,
    val boxCount: Int,
    val lineCount: Int,
    val totalCount: Int,
    val uploadType: Int,
    val crcValue: Int,
) {
    val provenance: String get() = "device_global_summary"
    val hasCelsius: Boolean get() = minTemperatureCelsius != null && maxTemperatureCelsius != null && avgTemperatureCelsius != null
}

data class HikmicroF2DeviceExpertRoiSummary(
    val index: Int,
    val enabled: Boolean,
    val regionId: Int,
    val regionTypeCode: Int,
    val regionType: HikmicroF2RegionType?,
    val referenceTemperatureRaw: Int,
    val distance: Float,
    val maxTemperatureStatus: Int,
    val minTemperatureStatus: Int,
    val avgTemperatureStatus: Int,
    val name: String,
    val emissivity: Float,
    /** Raw packet field; official coding-12 evidence proves known enumTempUnit 0/1/2 values are base Celsius. */
    val minTemperatureNative: Float,
    val minTemperatureCelsius: Float?,
    val minTemperatureRequestedDisplay: Float?,
    /** Raw packet field; official coding-12 evidence proves known enumTempUnit 0/1/2 values are base Celsius. */
    val maxTemperatureNative: Float,
    val maxTemperatureCelsius: Float?,
    val maxTemperatureRequestedDisplay: Float?,
    /** Raw packet field; official coding-12 evidence proves known enumTempUnit 0/1/2 values are base Celsius. */
    val avgTemperatureNative: Float,
    val avgTemperatureCelsius: Float?,
    val avgTemperatureRequestedDisplay: Float?,
    val diffTemperatureNative: Float,
    val point0: HikmicroF2TemperaturePoint,
    val point1: HikmicroF2TemperaturePoint,
    val pointCount: Int,
    val polygonPoints: List<HikmicroF2TemperaturePoint>,
) {
    val provenance: String get() = "device_expert_roi_summary"
    val hasCelsius: Boolean get() = minTemperatureCelsius != null && maxTemperatureCelsius != null && avgTemperatureCelsius != null
}

data class HikmicroF2TemperaturePoint(
    val x: Int,
    val y: Int,
)

enum class HikmicroF2RegionType(val deviceCode: Int) {
    BOX(1),
    LINE(2),
    POINT(3),
    ;

    companion object {
        fun fromDeviceCode(code: Int): HikmicroF2RegionType? = values().singleOrNull { it.deviceCode == code }
    }
}

enum class HikmicroF2TemperatureUnit(val deviceCode: Int) {
    /** enumTempUnit 0: display raw packet Celsius unchanged. */
    CELSIUS(0),
    /** enumTempUnit 1: requested display unit; official p2.a applies C * 1.8 + 32. */
    FAHRENHEIT(1),
    /** enumTempUnit 2: requested display unit; official p2.a applies C + 273.15. */
    KELVIN(2),
    ;

    fun validatedRawCelsius(value: Float): Float = value

    fun fromCelsius(value: Float): Float = when (this) {
        CELSIUS -> value
        FAHRENHEIT -> value * 1.8f + 32.0f
        KELVIN -> value + 273.15f
    }

    companion object {
        fun fromDeviceCode(code: Int): HikmicroF2TemperatureUnit? = values().singleOrNull { it.deviceCode == code }
    }
}
