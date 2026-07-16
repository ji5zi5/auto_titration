package kr.auto.titration.mobile.thermal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class HikmicroJnaMini2StreamTemperatureMetadataTest {
    @Test fun deviceTemperatureSummaryKeepsDeviceGlobalScopeOnly() {
        val summary = Mini2DeviceTemperatureSummary(25.0, 20.0, 30.0, "celsius", 0)
        val json = summary.toJson()
        assertEquals(25.0, json.getDouble("avg_c"), 0.0001)
        assertEquals("celsius", json.getString("requested_display_unit"))
    }
}
