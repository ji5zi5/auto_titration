package kr.auto.titration.mobile.pump

import android.content.Context
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.util.Locale

private const val PC_RELAY_PREFERENCES = "pump_pc_relay_transport"
private const val PC_RELAY_URL_KEY = "base_url"
private const val ACTIVE_TRANSPORT_KEY = "active_transport"

data class PcRelayPumpTransportStatus(
    val configured: Boolean,
    val connected: Boolean,
    val baseUrl: String,
    val message: String,
)

object PcRelayPumpContract {
    fun normalizeBaseUrl(value: String): String {
        val raw = value.trim().trimEnd('/')
        require(raw.isNotBlank()) { "Windows PC address is required" }
        val candidate = if (raw.contains("://")) raw else "http://$raw"
        val uri = URI(candidate)
        require(uri.scheme.equals("http", ignoreCase = true)) {
            "Windows relay must use http:// on the local network"
        }
        require(!uri.host.isNullOrBlank()) { "Windows PC host is invalid" }
        require(uri.rawQuery == null && uri.rawFragment == null) {
            "Windows PC address must not contain a query or fragment"
        }
        require(uri.path.isNullOrBlank() || uri.path == "/") {
            "Enter only the Windows PC address and port"
        }
        val port = if (uri.port == -1) 8765 else uri.port
        require(port in 1..65535) { "Windows PC port is invalid" }
        return "http://${uri.host}:$port"
    }

    fun endpointFor(command: String): Pair<String, String> = when (
        command.trim().take(1).lowercase(Locale.US)
    ) {
        "a" -> "POST" to "/api/pump/retract"
        "b" -> "POST" to "/api/pump/dispense"
        "c" -> "POST" to "/api/pump/stop"
        "r" -> "POST" to "/api/pump/reset"
        "s" -> "GET" to "/api/collector-health"
        else -> throw IllegalArgumentException("unsupported PC relay pump command: $command")
    }

    fun requestBody(command: String): String = when (
        command.trim().take(1).lowercase(Locale.US)
    ) {
        "a", "b" -> "{\"manual_unbounded\":true}"
        else -> "{}"
    }
}

/** Sends pump commands to the Windows dashboard, which owns USB serial. */
class PcRelayPumpTransport(
    context: Context,
    private val connectTimeoutMs: Int = 1_500,
    private val readTimeoutMs: Int = 2_000,
) : PumpCommandTransport {
    private val preferences = context.getSharedPreferences(
        PC_RELAY_PREFERENCES,
        Context.MODE_PRIVATE,
    )
    private var connected = false
    private var lastMessage = "Windows PC relay not connected"

    @Synchronized
    fun configure(baseUrl: String): PcRelayPumpTransportStatus {
        val normalized = PcRelayPumpContract.normalizeBaseUrl(baseUrl)
        preferences.edit().putString(PC_RELAY_URL_KEY, normalized).apply()
        val response = request("s")
        connected = !response.startsWith("ERROR") && !response.startsWith("BLOCKED")
        lastMessage = response
        return statusSnapshot()
    }

    @Synchronized
    fun disconnect(): PcRelayPumpTransportStatus {
        connected = false
        lastMessage = "Windows PC relay disconnected"
        return statusSnapshot()
    }

    @Synchronized
    fun statusSnapshot(): PcRelayPumpTransportStatus = PcRelayPumpTransportStatus(
        configured = configuredBaseUrl().isNotBlank(),
        connected = connected,
        baseUrl = configuredBaseUrl(),
        message = lastMessage,
    )

    @Synchronized
    override fun sendCommand(command: String): String {
        val response = request(command)
        connected = !response.startsWith("ERROR") && !response.startsWith("BLOCKED")
        lastMessage = response
        return response
    }

    private fun configuredBaseUrl(): String = preferences.getString(
        PC_RELAY_URL_KEY,
        "",
    ).orEmpty()

    private fun request(command: String): String {
        val baseUrl = configuredBaseUrl()
        if (baseUrl.isBlank()) return "BLOCKED Windows PC relay address is not configured"
        val letter = command.trim().take(1).lowercase(Locale.US)
        PumpCommandContract.requireSupported(letter)
        val (method, path) = PcRelayPumpContract.endpointFor(letter)
        val connection = try {
            URL(baseUrl + path).openConnection() as HttpURLConnection
        } catch (error: IOException) {
            return "ERROR PC relay URL ${error.message ?: "open failed"}"
        }
        return try {
            connection.requestMethod = method
            connection.connectTimeout = connectTimeoutMs
            connection.readTimeout = readTimeoutMs
            connection.setRequestProperty("Accept", "application/json")
            if (method == "POST") {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use {
                    it.write(PcRelayPumpContract.requestBody(letter).toByteArray(Charsets.UTF_8))
                }
            }
            val statusCode = connection.responseCode
            val stream = if (statusCode in 200..299) connection.inputStream else connection.errorStream
            val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            val payload = if (body.isBlank()) JSONObject() else JSONObject(body)
            if (statusCode !in 200..299 || payload.optBoolean("ok", false).not()) {
                val pump = payload.optJSONObject("pump")
                val reason = payload.optString("error").ifBlank {
                    pump?.optString("error").orEmpty().ifBlank { "HTTP $statusCode" }
                }
                return "ERROR PC relay $reason"
            }
            val pump = payload.optJSONObject("pump")
            val acknowledgement = pump?.optString("firmware_ack").orEmpty().ifBlank {
                pump?.optString("message").orEmpty().ifBlank {
                    if (letter == "s") "collector health ok" else "OK sent=$letter"
                }
            }
            buildString {
                append("PC_RELAY ").append(baseUrl).append('\n')
                append(acknowledgement)
                val steps = pump?.opt("confirmed_step_count")
                val volume = pump?.opt("firmware_volume_ml")
                if (steps is Number && volume is Number) {
                    append("\nSTATUS steps=").append(steps.toLong())
                    append(" ml=").append(volume.toDouble())
                }
            }
        } catch (error: Exception) {
            "ERROR PC relay ${error.javaClass.simpleName}: ${error.message ?: "request failed"}"
        } finally {
            connection.disconnect()
        }
    }
}

enum class PumpTransportMode(val key: String) {
    BLUETOOTH("bluetooth"),
    PC_RELAY("pc_relay"),
}

/** Runtime switch keeping one ManualPumpController and command contract. */
class SelectablePumpTransport(
    context: Context,
    private val bluetooth: BluetoothPumpTransport,
    private val pcRelay: PcRelayPumpTransport,
) : PumpCommandTransport, AutoCloseable {
    private val preferences = context.getSharedPreferences(
        PC_RELAY_PREFERENCES,
        Context.MODE_PRIVATE,
    )
    private var mode = if (
        preferences.getString(ACTIVE_TRANSPORT_KEY, "") == PumpTransportMode.PC_RELAY.key
    ) {
        PumpTransportMode.PC_RELAY
    } else {
        PumpTransportMode.BLUETOOTH
    }

    @Synchronized
    fun useBluetooth(): PumpTransportMode {
        mode = PumpTransportMode.BLUETOOTH
        preferences.edit().putString(ACTIVE_TRANSPORT_KEY, mode.key).apply()
        return mode
    }

    @Synchronized
    fun usePcRelay(baseUrl: String): PcRelayPumpTransportStatus {
        mode = PumpTransportMode.PC_RELAY
        preferences.edit().putString(ACTIVE_TRANSPORT_KEY, mode.key).apply()
        return pcRelay.configure(baseUrl)
    }

    @Synchronized
    fun disconnectPcRelay(): PcRelayPumpTransportStatus = pcRelay.disconnect()

    @Synchronized
    fun activeMode(): PumpTransportMode = mode

    @Synchronized
    fun pcRelayStatus(): PcRelayPumpTransportStatus = pcRelay.statusSnapshot()

    @Synchronized
    override fun sendCommand(command: String): String = when (mode) {
        PumpTransportMode.BLUETOOTH -> bluetooth.sendCommand(command)
        PumpTransportMode.PC_RELAY -> pcRelay.sendCommand(command)
    }

    override fun close() {
        pcRelay.disconnect()
        bluetooth.close()
    }
}
