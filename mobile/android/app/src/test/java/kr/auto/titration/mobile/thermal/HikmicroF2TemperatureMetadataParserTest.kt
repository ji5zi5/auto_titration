package kr.auto.titration.mobile.thermal

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HikmicroF2TemperatureMetadataParserTest {
    @Test
    fun parsesGlobalAndBoxLinePointRoiSummariesWithCelsiusUnit() {
        val header = validHeader(unit = 0, total = 3, pointCount = 0, boxCount = 1, lineCount = 1)
        writeOutcome(header, 0, enabled = true, regionId = 7, type = 1, pointCount = 4, min = 20.0f, max = 30.0f, avg = 25.0f)
        writeOutcome(header, 1, enabled = true, regionId = 8, type = 2, pointCount = 2, min = -40.0f, max = 120.0f, avg = 10.0f)
        writeOutcome(header, 2, enabled = true, regionId = 9, type = 3, pointCount = 1, min = 1000.0f, max = 1200.0f, avg = 1100.0f)

        val parsed = HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(header)

        assertNull(parsed.blockedInvalidMetadata)
        assertFalse(parsed.provesFullMatrixCelsius)
        assertTrue(parsed.hasDeviceCelsiusDiagnostics)
        val global = requireNotNull(parsed.deviceGlobalSummary)
        assertEquals(0, global.enumTempUnit)
        assertEquals(HikmicroF2TemperatureUnit.CELSIUS, global.nativeUnit)
        assertEquals(1.25f, global.distance, 0.0001f)
        assertEquals(0.96f, global.emissivity, 0.0001f)
        assertEquals(20.0f, requireNotNull(global.minTemperatureCelsius), 0.0001f)
        assertEquals(40.0f, requireNotNull(global.maxTemperatureCelsius), 0.0001f)
        assertEquals(30.0f, requireNotNull(global.avgTemperatureCelsius), 0.0001f)
        assertEquals(HikmicroF2TemperaturePoint(123, 456), global.points[0])
        assertEquals(3, parsed.deviceExpertRoiSummary.size)
        assertEquals(HikmicroF2RegionType.BOX, parsed.deviceExpertRoiSummary[0].regionType)
        assertEquals(25.0f, requireNotNull(parsed.deviceExpertRoiSummary[0].avgTemperatureCelsius), 0.0001f)
        assertEquals(HikmicroF2RegionType.LINE, parsed.deviceExpertRoiSummary[1].regionType)
        assertEquals(HikmicroF2RegionType.POINT, parsed.deviceExpertRoiSummary[2].regionType)
    }

    @Test
    fun treatsKnownFahrenheitAndKelvinUnitCodesAsDisplayRequestsOverRawCelsius() {
        val fahrenheit = validHeader(unit = 1, min = 20.0f, max = 30.0f, avg = 25.0f, total = 1, boxCount = 1)
        writeOutcome(fahrenheit, 0, enabled = true, min = 20.0f, max = 30.0f, avg = 25.0f)
        val fParsed = HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(fahrenheit)
        val fGlobal = requireNotNull(fParsed.deviceGlobalSummary)
        val fRoi = fParsed.deviceExpertRoiSummary.single()
        assertEquals(HikmicroF2TemperatureUnit.FAHRENHEIT, fGlobal.nativeUnit)
        assertEquals(20.0f, requireNotNull(fGlobal.minTemperatureCelsius), 0.0001f)
        assertEquals(30.0f, requireNotNull(fGlobal.maxTemperatureCelsius), 0.0001f)
        assertEquals(25.0f, requireNotNull(fGlobal.avgTemperatureCelsius), 0.0001f)
        assertEquals(68.0f, requireNotNull(fGlobal.minTemperatureRequestedDisplay), 0.0001f)
        assertEquals(86.0f, requireNotNull(fGlobal.maxTemperatureRequestedDisplay), 0.0001f)
        assertEquals(77.0f, requireNotNull(fGlobal.avgTemperatureRequestedDisplay), 0.0001f)
        assertEquals(20.0f, requireNotNull(fRoi.minTemperatureCelsius), 0.0001f)
        assertEquals(30.0f, requireNotNull(fRoi.maxTemperatureCelsius), 0.0001f)
        assertEquals(25.0f, requireNotNull(fRoi.avgTemperatureCelsius), 0.0001f)
        assertEquals(68.0f, requireNotNull(fRoi.minTemperatureRequestedDisplay), 0.0001f)
        assertEquals(86.0f, requireNotNull(fRoi.maxTemperatureRequestedDisplay), 0.0001f)
        assertEquals(77.0f, requireNotNull(fRoi.avgTemperatureRequestedDisplay), 0.0001f)

        val kelvin = validHeader(unit = 2, min = 20.0f, max = 30.0f, avg = 25.0f)
        val kParsed = requireNotNull(HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(kelvin).deviceGlobalSummary)
        assertEquals(HikmicroF2TemperatureUnit.KELVIN, kParsed.nativeUnit)
        assertEquals(20.0f, requireNotNull(kParsed.minTemperatureCelsius), 0.0001f)
        assertEquals(30.0f, requireNotNull(kParsed.maxTemperatureCelsius), 0.0001f)
        assertEquals(25.0f, requireNotNull(kParsed.avgTemperatureCelsius), 0.0001f)
        assertEquals(293.15f, requireNotNull(kParsed.minTemperatureRequestedDisplay), 0.0001f)
        assertEquals(303.15f, requireNotNull(kParsed.maxTemperatureRequestedDisplay), 0.0001f)
        assertEquals(298.15f, requireNotNull(kParsed.avgTemperatureRequestedDisplay), 0.0001f)
    }

    @Test
    fun preservesNativeValuesAndBlocksCelsiusForUnknownUnit() {
        val header = validHeader(unit = 99, min = 12.0f, max = 14.0f, avg = 13.0f)

        val parsed = HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(header)

        val global = requireNotNull(parsed.deviceGlobalSummary)
        assertEquals(99, global.enumTempUnit)
        assertNull(global.nativeUnit)
        assertEquals(12.0f, global.minTemperatureNative, 0.0001f)
        assertNull(global.minTemperatureCelsius)
        assertNull(global.minTemperatureRequestedDisplay)
        assertFalse(parsed.hasDeviceCelsiusDiagnostics)
    }

    @Test
    fun rejectsNanAndInfinityWithoutTemperatureRangeGuessing() {
        val nanHeader = validHeader(min = Float.NaN)
        val nan = HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(nanHeader)
        assertEquals("invalid_float", nan.blockedInvalidMetadata?.code)

        val infHeader = validHeader(max = Float.POSITIVE_INFINITY)
        val inf = HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(infHeader)
        assertEquals("invalid_float", inf.blockedInvalidMetadata?.code)

        val extremeButFinite = validHeader(min = -273.0f, max = 1500.0f, avg = 100.0f)
        assertNull(HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(extremeButFinite).blockedInvalidMetadata)
    }

    @Test
    fun rejectsCountOverflowTruncatedHeadersAndUnknownRegionTypes() {
        val totalOverflow = validHeader(total = 22)
        assertEquals(
            "outcome_total_overflow",
            HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(totalOverflow).blockedInvalidMetadata?.code,
        )

        val pointOverflow = validHeader(pointCount = 4)
        assertEquals(
            "global_point_count_overflow",
            HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(pointOverflow).blockedInvalidMetadata?.code,
        )

        val truncated = HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(ByteArray(7_367))
        assertEquals("truncated_offline_upload_header", truncated.blockedInvalidMetadata?.code)

        val unknownRegion = validHeader(total = 1)
        writeOutcome(unknownRegion, 0, enabled = true, type = 99)
        assertEquals(
            "unknown_roi_region_type",
            HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(unknownRegion).blockedInvalidMetadata?.code,
        )
    }

    @Test
    fun rejectsExactLengthAllZeroUninitializedHeaderWithoutDiagnosticCelsius() {
        val parsed =
            HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(ByteArray(7_368))

        assertEquals("uninitialized_zero_offline_upload_header", parsed.blockedInvalidMetadata?.code)
        assertNull(parsed.deviceGlobalSummary)
        assertTrue(parsed.deviceExpertRoiSummary.isEmpty())
        assertFalse(parsed.hasDeviceCelsiusDiagnostics)
    }

    @Test
    fun packetDerivedDeviceSummaryRemainsDiagnosticAndCannotGrantGenericCelsius() {
        val parsed = HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(validHeader())
        val global = requireNotNull(parsed.deviceGlobalSummary)
        val status = Mini2RawStreamStatus.streamAttemptStarted(
            reason = "test",
            frameCounter = 1,
            deviceTemperatureSummary = Mini2DeviceTemperatureSummary(
                avgC = requireNotNull(global.avgTemperatureCelsius).toDouble(),
                minC = requireNotNull(global.minTemperatureCelsius).toDouble(),
                maxC = requireNotNull(global.maxTemperatureCelsius).toDouble(),
                requestedDisplayUnit = requireNotNull(global.nativeUnit).name,
                requestedDisplayUnitCode = global.enumTempUnit,
            ),
        )
        val fields = status.toJsonTemperatureFieldsForTest()

        assertFalse(fields.getValue("celsius_allowed") as Boolean)
        assertEquals(null, fields["temperature_avg_c"])
        assertEquals(30.0, fields["device_global_temperature_avg_c"])
        assertEquals("device_global_summary", fields["device_global_temperature_provenance"])
    }

    @Test
    fun rejectsInvalidRegionLayoutsAndPointBounds() {
        val invalidBox = validHeader(total = 1, boxCount = 1)
        writeOutcome(invalidBox, 0, enabled = true, type = 1, pointCount = 5)
        assertEquals("roi_box_layout_invalid", HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(invalidBox).blockedInvalidMetadata?.code)

        val invalidPointBounds = validHeader(total = 1, boxCount = 1)
        writeOutcome(invalidPointBounds, 0, enabled = true, type = 1, pointCount = 4, x0 = 1001)
        assertEquals("point_out_of_bounds", HikmicroF2TemperatureMetadataParser.parseOfflineUploadHeader(invalidPointBounds).blockedInvalidMetadata?.code)
    }

    private fun validHeader(
        unit: Int = 0,
        min: Float = 20.0f,
        max: Float = 40.0f,
        avg: Float = 30.0f,
        total: Int = 0,
        pointCount: Int = 0,
        boxCount: Int = 0,
        lineCount: Int = 0,
    ): ByteArray {
        val header = ByteArray(7_368)
        header.i32(120, unit)
        header.u8(124, 1)
        header.f32(128, 1.25f)
        header.f32(132, 22.0f)
        header.f32(136, 0.96f)
        header.f32(140, 23.0f)
        header.f32(144, min)
        header.f32(148, max)
        header.f32(152, avg)
        header.point(156, 123, 456)
        header.point(164, 200, 500)
        header.point(172, 300, 600)
        header.i32(180, 2)
        header.u8(204, pointCount)
        header.u8(205, boxCount)
        header.u8(206, lineCount)
        header.u8(207, total)
        header.i32(4_584, 12)
        header.i32(4_632, 0x1234_5678)
        return header
    }

    private fun writeOutcome(
        header: ByteArray,
        index: Int,
        enabled: Boolean = true,
        regionId: Int = index + 1,
        type: Int = 1,
        pointCount: Int = 4,
        min: Float = 21.0f,
        max: Float = 31.0f,
        avg: Float = 26.0f,
        x0: Int = 10,
    ) {
        val base = 216 + index * 208
        header.u8(base, if (enabled) 1 else 0)
        header.u8(base + 1, regionId)
        header.i32(base + 4, 1100)
        header.f32(base + 28, 1.5f)
        header.u8(base + 33, 2)
        header.u8(base + 34, 2)
        header.u8(base + 35, 2)
        header.i32(base + 36, type)
        val name = "ROI$regionId".toByteArray(Charsets.US_ASCII)
        name.copyInto(header, base + 40)
        header.f32(base + 72, 0.95f)
        header.f32(base + 76, min)
        header.f32(base + 80, max)
        header.f32(base + 84, avg)
        header.f32(base + 88, max - min)
        header.point(base + 92, x0, 20)
        header.point(base + 100, 900, 920)
        header.i32(base + 108, pointCount)
        repeat(pointCount.coerceAtMost(12)) { i -> header.point(base + 112 + i * 8, 100 + i, 200 + i) }
    }

    private fun ByteArray.i32(offset: Int, value: Int) {
        ByteBuffer.wrap(this, offset, 4).order(ByteOrder.LITTLE_ENDIAN).putInt(value)
    }

    private fun ByteArray.u8(offset: Int, value: Int) {
        this[offset] = value.toByte()
    }

    private fun ByteArray.f32(offset: Int, value: Float) {
        ByteBuffer.wrap(this, offset, 4).order(ByteOrder.LITTLE_ENDIAN).putFloat(value)
    }

    private fun ByteArray.point(offset: Int, x: Int, y: Int) {
        i32(offset, x)
        i32(offset + 4, y)
    }
}
