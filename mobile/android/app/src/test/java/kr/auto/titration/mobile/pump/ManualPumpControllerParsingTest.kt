package kr.auto.titration.mobile.pump

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ManualPumpControllerParsingTest {
    @Test
    fun statusParserReadsFirmwareStatusFromMultilineResponse() {
        val parsed = PumpStatusParser.parse("BT_DEVICE HC-05\nRESET\nSTATUS steps=-42 ml=0.1234\n")

        requireNotNull(parsed)
        assertEquals(-42L, parsed.steps)
        assertEquals(0.1234, parsed.firmwareVolumeMl, 0.000001)
        assertEquals("STATUS steps=-42 ml=0.1234", parsed.rawLine)
    }

    @Test
    fun movementWriteWithoutFirmwareResponseDoesNotInventStatusOrVolume() {
        val controller = ManualPumpController(FakeTransport("BT_DEVICE HC-05\nOK sent=b"))

        val response = controller.sendUserCommand(PumpCommand.StartRight)
        val snapshot = controller.snapshot()

        assertEquals("BT_DEVICE HC-05\nOK sent=b", response)
        assertEquals("running_forward", snapshot.state)
        assertNull(snapshot.confirmedStepCount)
        assertNull(snapshot.firmwareVolumeMl)
        assertEquals("", snapshot.lastStatusLine)
        assertEquals("HC-05", snapshot.bluetoothDeviceName)
        assertTrue(snapshot.connected)
    }

    @Test
    fun stopStatusUpdatesConfirmedFirmwareFields() {
        val controller = ManualPumpController(FakeTransport("BT_DEVICE HC-05\nSTOP\nSTATUS steps=100 ml=0.1000"))

        controller.sendUserCommand(PumpCommand.Stop)
        val snapshot = controller.snapshot()

        assertEquals("stopped", snapshot.state)
        assertEquals(100L, snapshot.confirmedStepCount)
        assertEquals(0.1000, requireNotNull(snapshot.firmwareVolumeMl), 0.000001)
        assertEquals("STATUS steps=100 ml=0.1000", snapshot.lastStatusLine)
    }

    @Test
    fun failedWriteDoesNotApplyMovementState() {
        val controller = ManualPumpController(FakeTransport("ERROR Bluetooth SPP write IOException: outcome uncertain"))

        controller.sendUserCommand(PumpCommand.StartLeft)
        val snapshot = controller.snapshot()

        assertEquals("idle", snapshot.state)
        assertEquals("ERROR Bluetooth SPP write IOException: outcome uncertain", snapshot.lastCommandResponse)
    }

    @Test
    fun automationCannotSendManualPumpCommands() {
        val controller = ManualPumpController(FakeTransport("OK sent=b"))

        assertThrows(IllegalArgumentException::class.java) {
            controller.sendUserCommand(PumpCommand.StartRight, CommandSource.ML_STATUS_AUTOMATION)
        }
    }

    private class FakeTransport(private val response: String) : PumpCommandTransport {
        override fun sendCommand(command: String): String = response
    }
}
