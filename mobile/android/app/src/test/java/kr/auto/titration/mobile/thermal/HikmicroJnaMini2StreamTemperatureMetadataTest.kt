package kr.auto.titration.mobile.thermal

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class HikmicroJnaMini2StreamTemperatureMetadataTest {
    @Test fun deviceTemperatureSummaryKeepsDeviceGlobalScopeOnly() {
        val summary = Mini2DeviceTemperatureSummary(25.0, 20.0, 30.0, "celsius", 0)

        assertEquals(25.0, summary.avgC, 0.0001)
        assertEquals(20.0, summary.minC, 0.0001)
        assertEquals(30.0, summary.maxC, 0.0001)
        assertEquals("celsius", summary.requestedDisplayUnit)
        assertEquals(0, summary.requestedDisplayUnitCode)
        assertEquals("device_global_summary", summary.provenance)
        assertEquals("device_global_summary", summary.scope)
        assertEquals("celsius", summary.nativeUnit)
        assertEquals(0, summary.nativeUnitCode)
    }

    @Test fun deviceTemperatureSummaryRejectsNonGlobalScopeMetadata() {
        assertThrows(IllegalArgumentException::class.java) {
            Mini2DeviceTemperatureSummary(
                avgC = 25.0,
                minC = 20.0,
                maxC = 30.0,
                requestedDisplayUnit = "celsius",
                requestedDisplayUnitCode = 0,
                provenance = "device_global_summary",
                scope = "full_matrix",
            )
        }
    }

    @Test fun deviceTemperatureSummaryJsonSourceEmitsOnlyDeviceGlobalScopeMetadata() {
        // Local JVM unit tests use Android's host-stub org.json.JSONObject, whose mutating methods
        // throw "Method ... not mocked". This source-shape assertion keeps the JSON contract covered
        // without replacing production's Android JSONObject construction with a test-only fake.
        val source = source("kr/auto/titration/mobile/thermal/Mini2RawStreamStatus.kt")
        val summaryJson = source.substringAfter("fun toJson(): JSONObject = JSONObject()")
            .substringBefore("/**\n * Honest raw-stream status")

        listOf(
            ".put(\"avg_c\", avgC)",
            ".put(\"min_c\", minC)",
            ".put(\"max_c\", maxC)",
            ".put(\"requested_display_unit\", requestedDisplayUnit)",
            ".put(\"requested_display_unit_code\", requestedDisplayUnitCode)",
            ".put(\"provenance\", provenance)",
            ".put(\"scope\", scope)",
            ".put(\"celsius_allowed\", true)",
            ".put(\"full_matrix_celsius_allowed\", false)",
        ).forEach { token -> assertTrue("missing JSON token: $token", summaryJson.contains(token)) }
    }

    private fun source(relative: String): String {
        val root = generateSequence(File(requireNotNull(System.getProperty("user.dir")))) { it.parentFile }
            .flatMap { sequenceOf(it, File(it, "mobile/android")) }
            .first { File(it, "app/src/main/java/$relative").exists() }
        return File(root, "app/src/main/java/$relative").readText()
    }
}
