package kr.auto.titration.mobile.pump

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PumpBluetoothDeviceSelectorTest {
    @Test
    fun persistedAddressWinsOverNameHints() {
        val devices = listOf(
            BondedPumpDevice(name = "HC-05", address = "00:11:22:33:44:55", likelyPump = true),
            BondedPumpDevice(name = "Lab Speaker", address = "AA:BB:CC:DD:EE:FF", likelyPump = false),
        )

        val selected = PumpBluetoothDeviceSelector.select(
            devices = devices,
            persistedAddress = "aa:bb:cc:dd:ee:ff",
        )

        assertEquals("AA:BB:CC:DD:EE:FF", selected?.address)
    }

    @Test
    fun persistedUnknownAddressFailsClosedInsteadOfFallingBack() {
        val devices = listOf(BondedPumpDevice(name = "HC-05", address = "00:11", likelyPump = true))

        val selected = PumpBluetoothDeviceSelector.select(
            devices = devices,
            persistedAddress = "FF:FF",
        )

        assertNull(selected)
    }

    @Test
    fun noPersistedAddressPicksPreferredPumpNameDeterministically() {
        val devices = listOf(
            BondedPumpDevice(name = "ESP32-PUMP", address = "33", likelyPump = true),
            BondedPumpDevice(name = "HC-05", address = "22", likelyPump = true),
            BondedPumpDevice(name = "Arduino-Titrator", address = "11", likelyPump = true),
        )

        val selected = PumpBluetoothDeviceSelector.select(devices = devices, persistedAddress = null)

        assertEquals("22", selected?.address)
    }

    @Test
    fun noPersistedAddressDoesNotChooseAmongMultipleUnrecognizedDevices() {
        val devices = listOf(
            BondedPumpDevice(name = "Keyboard", address = "11"),
            BondedPumpDevice(name = "Speaker", address = "22"),
        )

        val selected = PumpBluetoothDeviceSelector.select(devices = devices, persistedAddress = null)

        assertNull(selected)
    }

    @Test
    fun singleUnrecognizedDevicePreservesLegacyFallback() {
        val devices = listOf(BondedPumpDevice(name = "Serial Adapter", address = "11"))

        val selected = PumpBluetoothDeviceSelector.select(devices = devices, persistedAddress = null)

        assertEquals("11", selected?.address)
    }
}
