package com.hcusbsdk

import android.app.PendingIntent
import com.hcusbsdk.Interface.EnumerateDevice
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EnumerateDeviceTest {
    @Test
    fun officialPermissionActionAndFlagBoundaryArePreserved() {
        assertEquals("com.android.example.USB_PERMISSION", EnumerateDevice.USB_PERMISSION_ACTION)
        assertEquals(PendingIntent.FLAG_ONE_SHOT, EnumerateDevice.permissionIntentFlags(30))
        assertEquals(PendingIntent.FLAG_IMMUTABLE, EnumerateDevice.permissionIntentFlags(31))
    }

    @Test
    fun officialProductTablesIncludeThermalCameraAcsAndTransmissionRanges() {
        assertTrue(EnumerateDevice.isSupportedProduct(11231, 257))
        assertTrue(EnumerateDevice.isSupportedProduct(11231, 258))
        assertTrue(EnumerateDevice.isSupportedProduct(8367, 512))
        assertTrue(EnumerateDevice.isSupportedProduct(3141, 24576))
        assertTrue(EnumerateDevice.isSupportedProduct(4429, 34185))
        assertTrue(EnumerateDevice.isSupportedProduct(11231, 645))
        assertTrue(EnumerateDevice.isSupportedProduct(11231, 671))
        assertTrue(EnumerateDevice.isSupportedProduct(11231, 769))
        assertTrue(EnumerateDevice.isSupportedProduct(11231, 1281))
        assertTrue(EnumerateDevice.isSupportedProduct(1155, 22352))

        assertFalse(EnumerateDevice.isSupportedProduct(11231, 256))
        assertFalse(EnumerateDevice.isSupportedProduct(8367, 513))
        assertFalse(EnumerateDevice.isSupportedProduct(9999, 258))
    }
}
