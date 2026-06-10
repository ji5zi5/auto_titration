package kr.auto.titration.mobile.pump

import java.util.Locale

interface PumpCommandTransport {
    fun sendCommand(command: String): String
}

class DryRunPumpTransport : PumpCommandTransport {
    val commands: MutableList<String> = mutableListOf()

    override fun sendCommand(command: String): String {
        commands += command
        return when (command.trim().lowercase(Locale.US)) {
            "s" -> "STATUS steps=0 ml=0.0000"
            "r" -> "RESET\nSTATUS steps=0 ml=0.0000"
            "a" -> "LEFT"
            "b" -> "RIGHT"
            "c" -> "STOP\nSTATUS steps=0 ml=0.0000"
            else -> "ERR unsupported $command"
        }
    }
}

/**
 * Android-side manual pump boundary for the current Arduino firmware.
 *
 * The firmware accepts single-letter serial commands only:
 * a=left/reverse, b=right/forward, c=stop, s=status, r=reset.  Commands are
 * allowed only from explicit user actions. ML/status automation still cannot
 * start or stop the pump.
 */
class ManualPumpController(
    private val transport: PumpCommandTransport = DryRunPumpTransport(),
    @Suppress("unused") private val calibration: PumpCalibration = PumpCalibration(),
) {
    private var state: String = "idle"
    private var runRateMlPerS: Double = 0.0
    private var commandedSteps: Long = 0
    private var confirmedStepCount: Long? = null
    private var firmwareVolumeMl: Double? = null
    private var lastStatusLine: String = ""
    private var lastCommandResponse: String = ""
    private var warning: String = ""

    @Synchronized
    fun sendUserCommand(command: PumpCommand, source: CommandSource = CommandSource.USER_ACTION): String {
        require(source == CommandSource.USER_ACTION) { "pump commands require explicit user action" }
        val line = command.toLine()
        PumpCommandContract.requireSupported(line)
        val response = try {
            transport.sendCommand(line)
        } catch (error: Throwable) {
            state = "bluetooth_error"
            warning = error.message ?: error.javaClass.simpleName
            "ERROR ${error.javaClass.simpleName}: ${warning}"
        }
        lastCommandResponse = response
        val parsed = PumpStatusParser.parse(response)
        if (parsed != null) {
            confirmedStepCount = parsed.steps
            firmwareVolumeMl = parsed.firmwareVolumeMl
            lastStatusLine = parsed.rawLine
        }
        applyAcceptedCommand(command, parsed)
        return response
    }

    fun rejectAutomation(command: PumpCommand): Nothing {
        throw IllegalStateException("ML/equivalence automation cannot send pump command ${command.name}")
    }

    @Synchronized
    fun snapshot(): PumpSnapshot = PumpSnapshot(
        mode = "android_manual_bluetooth",
        state = state,
        runRateMlPerS = runRateMlPerS,
        commandedStepCount = commandedSteps,
        confirmedStepCount = confirmedStepCount,
        firmwareVolumeMl = firmwareVolumeMl,
        lastStatusLine = lastStatusLine,
        lastCommandResponse = lastCommandResponse,
        bluetoothDeviceName = extractTransportName(lastCommandResponse),
        connected = lastCommandResponse.isNotBlank() && !isFailureResponse(lastCommandResponse),
        warning = warning,
    )

    private fun applyAcceptedCommand(command: PumpCommand, parsed: PumpStatus?) {
        if (isFailureResponse(lastCommandResponse)) return
        when (command) {
            PumpCommand.StartLeft -> {
                state = "running_reverse"
                warning = ""
            }
            PumpCommand.StartRight -> {
                state = "running_forward"
                warning = ""
            }
            PumpCommand.Stop -> {
                state = "stopped"
                runRateMlPerS = 0.0
                warning = ""
            }
            PumpCommand.Status -> {
                if (parsed != null && state == "idle") state = "status_ready"
                warning = ""
            }
            PumpCommand.Reset -> {
                commandedSteps = 0
                if (parsed != null) {
                    confirmedStepCount = parsed.steps
                    firmwareVolumeMl = parsed.firmwareVolumeMl
                }
                state = "reset"
                warning = ""
            }
        }
    }

    private fun isFailureResponse(response: String): Boolean {
        val normalized = response.trimStart().uppercase(Locale.US)
        return normalized.startsWith("ERROR") || normalized.startsWith("BLOCKED")
    }

    private fun extractTransportName(response: String): String {
        return response.lineSequence()
            .firstOrNull { it.startsWith("BT_DEVICE ") }
            ?.removePrefix("BT_DEVICE ")
            ?.trim()
            .orEmpty()
    }
}

enum class CommandSource { USER_ACTION, ML_STATUS_AUTOMATION }

sealed class PumpCommand(val name: String, val letter: String) {
    object StartLeft : PumpCommand(name = "START_LEFT", letter = "a")
    object StartRight : PumpCommand(name = "START_RIGHT", letter = "b")
    object Stop : PumpCommand(name = "STOP", letter = "c")
    object Status : PumpCommand(name = "STATUS", letter = "s")
    object Reset : PumpCommand(name = "RESET", letter = "r")

    fun toLine(): String = letter

    companion object {
        fun fromBridge(value: String): PumpCommand {
            val normalized = value.trim().lowercase(Locale.US)
            return when (normalized) {
                "a", "left", "reverse", "start_left", "startleft" -> StartLeft
                "b", "right", "forward", "start_right", "startright", "start" -> StartRight
                "c", "stop" -> Stop
                "s", "status" -> Status
                "r", "reset" -> Reset
                else -> throw IllegalArgumentException("unsupported pump bridge command: $value")
            }
        }
    }
}

object PumpStatusParser {
    private val statusRegex = Regex("STATUS\\s+steps=(-?\\d+)\\s+ml=([-+]?\\d+(?:\\.\\d+)?)", RegexOption.IGNORE_CASE)

    fun parse(response: String): PumpStatus? {
        val match = statusRegex.find(response) ?: return null
        return PumpStatus(
            steps = match.groupValues[1].toLong(),
            firmwareVolumeMl = match.groupValues[2].toDouble(),
            rawLine = match.value,
        )
    }
}
