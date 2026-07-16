package kr.auto.titration.mobile

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class G004BridgeTemperatureSummaryTest {
    @Test
    fun liveBridgeCopiesValidatedDeviceGlobalSummaryWithoutMatrixClaim() {
        val stream = fakeJson(
            "celsius_allowed" to true,
            "temperature_avg_c" to 26.5,
            "temperature_min_c" to 22.25,
            "temperature_max_c" to 31.75,
            "temperature_provenance" to "device_global_summary",
            "temperature_scope" to "device_global_summary",
            "temperature_requested_display_unit" to "fahrenheit",
            "temperature_requested_display_unit_code" to 1,
            "temperature_summary" to fakeJson(
                "avg_c" to 26.5,
                "min_c" to 22.25,
                "max_c" to 31.75,
                "provenance" to "device_global_summary",
                "scope" to "device_global_summary",
            ),
            "full_matrix_celsius_allowed" to false,
            "full_matrix_temperature_status" to "unproved_not_emitted",
            "temperature_conversion_attempt" to fakeJson(
                "celsius_allowed" to false,
                "temperature_avg_c" to null,
            ),
        )
        val live = fakeJson()

        copyMini2TemperatureSummaryFieldsForBridge(live, stream)

        assertTrue(live.getBoolean("celsius_allowed"))
        assertEquals(26.5, live.getDouble("temperature_avg_c"), 0.0001)
        assertEquals(22.25, live.getDouble("temperature_min_c"), 0.0001)
        assertEquals(31.75, live.getDouble("temperature_max_c"), 0.0001)
        assertEquals("device_global_summary", live.getString("temperature_provenance"))
        assertEquals("device_global_summary", live.getString("temperature_scope"))
        assertEquals("fahrenheit", live.getString("temperature_requested_display_unit"))
        assertEquals(1, live.getInt("temperature_requested_display_unit_code"))
        assertEquals(26.5, live.getJSONObject("temperature_summary").getDouble("avg_c"), 0.0001)
        assertFalse(live.getBoolean("full_matrix_celsius_allowed"))
        assertEquals("unproved_not_emitted", live.getString("full_matrix_temperature_status"))
    }

    @Test
    fun liveBridgeEmitsExplicitNullsWhenSummaryAbsentAndDoesNotFabricateZero() {
        val live = fakeJson()

        copyMini2TemperatureSummaryFieldsForBridge(live, fakeJson())

        assertFalse(live.getBoolean("celsius_allowed"))
        assertTrue(live.isNull("temperature_avg_c"))
        assertTrue(live.isNull("temperature_min_c"))
        assertTrue(live.isNull("temperature_max_c"))
        assertTrue(live.isNull("temperature_provenance"))
        assertTrue(live.isNull("temperature_scope"))
        assertTrue(live.isNull("temperature_requested_display_unit"))
        assertTrue(live.isNull("temperature_requested_display_unit_code"))
        assertTrue(live.isNull("temperature_summary"))
        assertFalse(live.getBoolean("full_matrix_celsius_allowed"))
        assertEquals("unproved_not_emitted", live.getString("full_matrix_temperature_status"))
    }
    @Test
    fun liveBridgeRejectsUntrustedFiniteValuesWithExplicitNulls() {
        val stream = fakeJson(
            "celsius_allowed" to true,
            "temperature_avg_c" to 0.0,
            "temperature_min_c" to 0.0,
            "temperature_max_c" to 0.0,
            "temperature_provenance" to "private_unvalidated_payload",
            "temperature_scope" to "private_unvalidated_payload",
            "temperature_requested_display_unit" to "Celsius",
            "temperature_requested_display_unit_code" to 0,
            "full_matrix_celsius_allowed" to false,
        )
        val live = fakeJson()

        copyMini2TemperatureSummaryFieldsForBridge(live, stream)

        assertFalse(live.getBoolean("celsius_allowed"))
        assertTrue(live.isNull("temperature_avg_c"))
        assertTrue(live.isNull("temperature_provenance"))
        assertTrue(live.isNull("temperature_summary"))
        assertFalse(live.getBoolean("full_matrix_celsius_allowed"))
    }


    private fun fakeJson(vararg entries: Pair<String, Any?>): JSONObject = FakeJSONObject(mutableMapOf(*entries))

    private class FakeJSONObject(private val values: MutableMap<String, Any?> = mutableMapOf()) : JSONObject() {
        override fun put(name: String, value: Any?): JSONObject = putValue(name, value)

        override fun put(name: String, value: Boolean): JSONObject = putValue(name, value)

        override fun put(name: String, value: Double): JSONObject = putValue(name, value)

        override fun put(name: String, value: Int): JSONObject = putValue(name, value)

        override fun put(name: String, value: Long): JSONObject = putValue(name, value)

        private fun putValue(name: String, value: Any?): JSONObject {
            values[name] = if (value === NULL) null else value
            return this
        }

        override fun has(name: String?): Boolean = values.containsKey(name.orEmpty())

        override fun isNull(name: String?): Boolean = values[name.orEmpty()] == null

        override fun getBoolean(name: String): Boolean = values[name] as Boolean

        override fun getDouble(name: String): Double = (values[name] as Number).toDouble()

        override fun getInt(name: String): Int = (values[name] as Number).toInt()

        override fun getString(name: String): String = values[name].toString()

        override fun getJSONObject(name: String): JSONObject = values[name] as JSONObject

        override fun optBoolean(name: String?): Boolean = optBoolean(name, false)

        override fun optBoolean(name: String?, fallback: Boolean): Boolean = values[name.orEmpty()] as? Boolean ?: fallback

        override fun optString(name: String?): String = optString(name, "")

        override fun optString(name: String?, fallback: String): String = values[name.orEmpty()]?.toString() ?: fallback

        override fun optInt(name: String?): Int = optInt(name, 0)

        override fun optInt(name: String?, fallback: Int): Int = when (val value = values[name.orEmpty()]) {
            is Number -> value.toInt()
            is String -> value.toIntOrNull() ?: fallback
            else -> fallback
        }

        override fun optDouble(name: String?): Double = optDouble(name, Double.NaN)

        override fun optDouble(name: String?, fallback: Double): Double = when (val value = values[name.orEmpty()]) {
            is Number -> value.toDouble()
            is String -> value.toDoubleOrNull() ?: fallback
            else -> fallback
        }

        override fun optJSONObject(name: String?): JSONObject? = values[name.orEmpty()] as? JSONObject

        override fun toString(): String = values.toString()
    }
}
