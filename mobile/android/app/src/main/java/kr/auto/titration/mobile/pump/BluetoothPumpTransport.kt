package kr.auto.titration.mobile.pump

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
import java.io.IOException
import java.io.InputStream
import java.util.Locale
import java.util.UUID

private const val PREFERENCES_NAME = "pump_bluetooth_transport"
private const val SELECTED_ADDRESS_KEY = "selected_address"

/** Bluetooth Classic SPP transport for HC-05/HC-06/Arduino serial modules. */
class BluetoothPumpTransport(
    private val context: Context,
    private val preferredNameHints: List<String> = PumpBluetoothDeviceSelector.defaultPreferredNameHints,
    private val readWindowMs: Long = 1_200L,
    private val shortAckWindowMs: Long = 150L,
) : PumpCommandTransport, AutoCloseable {
    companion object {
        val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
    }

    private val preferences: SharedPreferences by lazy {
        context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    }

    private var socket: BluetoothSocket? = null
    private var connectedAddress: String = ""
    private var connectedName: String = ""
    private var lastMessage: String = ""

    @Synchronized
    @SuppressLint("MissingPermission", "HardwareIds")
    override fun sendCommand(command: String): String {
        val letter = command.trim().take(1).lowercase(Locale.US)
        PumpCommandContract.requireSupported(letter)

        val connected = ensureConnected()
        if (!connected.connected) return connected.message
        val btSocket = socket ?: return "ERROR Bluetooth SPP socket unavailable after connect"
        val label = connected.deviceName.ifBlank { connected.deviceAddress.ifBlank { "unknown" } }

        return try {
            val output = btSocket.outputStream
            output.write((letter + "\n").toByteArray(Charsets.US_ASCII))
            output.flush()
            val body = readAvailableResponse(btSocket.inputStream, letter)
            val response = buildString {
                append("BT_DEVICE ").append(label).append('\n')
                if (body.isBlank()) {
                    append("OK sent=").append(letter)
                } else {
                    append(body.trim())
                }
            }
            lastMessage = response
            response
        } catch (error: IOException) {
            closeSocketOnly()
            val response = "ERROR Bluetooth SPP write ${error.javaClass.simpleName}: " +
                (error.message ?: "write failed; command outcome uncertain, not resent")
            lastMessage = response
            response
        } catch (error: SecurityException) {
            closeSocketOnly()
            val response = "BLOCKED BLUETOOTH_CONNECT permission required: ${error.message ?: "security exception"}"
            lastMessage = response
            response
        }
    }

    /** Lists bonded devices explicitly so the UI can present a stable address choice. */
    @Synchronized
    @SuppressLint("MissingPermission", "HardwareIds")
    fun bondedDevices(): List<BondedPumpDevice> {
        val adapter = adapterOrNull() ?: return emptyList()
        if (!hasConnectPermission()) return emptyList()
        return try {
            adapter.bondedDevices.orEmpty()
                .map { it.toBondedPumpDevice(preferredNameHints) }
                .sortedWith(compareBy<BondedPumpDevice> { it.name.lowercase(Locale.US) }.thenBy { it.address })
        } catch (_: SecurityException) {
            emptyList()
        }
    }

    /** Persists a caller-selected bonded-device address. Call [connect] to open it. */
    @Synchronized
    fun selectDevice(address: String): BluetoothPumpTransportStatus {
        val normalized = address.trim().uppercase(Locale.US)
        if (normalized.isBlank()) {
            preferences.edit().remove(SELECTED_ADDRESS_KEY).apply()
            disconnect()
            return statusSnapshot("Bluetooth pump selection cleared")
        }
        val bonded = bondedDevices()
        val selected = bonded.firstOrNull { it.address.equals(normalized, ignoreCase = true) }
            ?: return blocked("selected Bluetooth address is not bonded: $normalized")
        preferences.edit().putString(SELECTED_ADDRESS_KEY, selected.address).apply()
        if (connectedAddress.isNotBlank() && !connectedAddress.equals(selected.address, ignoreCase = true)) {
            closeSocketOnly()
        }
        lastMessage = "Selected Bluetooth pump ${selected.label}"
        return statusSnapshot(lastMessage)
    }

    /** Opens the persistent RFCOMM/SPP connection if needed. */
    @Synchronized
    @SuppressLint("MissingPermission", "HardwareIds")
    fun connect(): BluetoothPumpTransportStatus = ensureConnected()

    @Synchronized
    fun disconnect(): BluetoothPumpTransportStatus {
        closeSocketOnly()
        lastMessage = "Bluetooth pump disconnected"
        return statusSnapshot(lastMessage)
    }

    @Synchronized
    override fun close() {
        disconnect()
    }

    /** Read-only snapshot for UI/status bridges; does not connect or disconnect. */
    @Synchronized
    fun statusSnapshot(): BluetoothPumpTransportStatus = statusSnapshot(lastMessage)

    @SuppressLint("MissingPermission", "HardwareIds")
    private fun ensureConnected(): BluetoothPumpTransportStatus {
        val existing = socket
        if (existing != null && existing.isConnected) {
            return statusSnapshot("Bluetooth pump connected")
        }
        closeSocketOnly()

        val adapter = adapterOrNull()
            ?: return blocked("BluetoothAdapter unavailable")
        if (!adapter.isEnabled) {
            return blocked("Bluetooth adapter is off")
        }
        if (!hasConnectPermission()) {
            return blocked("BLUETOOTH_CONNECT permission required")
        }
        if (!hasScanPermission()) {
            return blocked("BLUETOOTH_SCAN permission required to cancel discovery before SPP connect")
        }

        val bonded = try {
            adapter.bondedDevices.orEmpty().toList()
        } catch (error: SecurityException) {
            return blocked("BLUETOOTH_CONNECT permission required: ${error.message ?: "security exception"}")
        }
        val candidates = bonded.map { it.toBondedPumpDevice(preferredNameHints) }
        val selection = PumpBluetoothDeviceSelector.select(
            devices = candidates,
            persistedAddress = persistedSelectedAddress(),
            preferredNameHints = preferredNameHints,
        ) ?: return blocked("paired Bluetooth SPP pump not found; pair HC-05/HC-06/Arduino or select a bonded address first")
        val device = bonded.firstOrNull { it.address.equals(selection.address, ignoreCase = true) }
            ?: return blocked("selected Bluetooth address is not bonded: ${selection.address}")

        var pendingSocket: BluetoothSocket? = null
        return try {
            if (adapter.isDiscovering) adapter.cancelDiscovery()
            pendingSocket = device.createRfcommSocketToServiceRecord(SPP_UUID)
            pendingSocket.connect()
            socket = pendingSocket
            connectedAddress = selection.address
            connectedName = selection.name
            pendingSocket = null
            lastMessage = "Bluetooth pump connected: ${selection.label}"
            statusSnapshot(lastMessage)
        } catch (error: IOException) {
            pendingSocket.closeQuietly()
            closeSocketOnly()
            error("Bluetooth SPP connect ${error.javaClass.simpleName}: ${error.message ?: "connection failed"}")
        } catch (error: SecurityException) {
            pendingSocket.closeQuietly()
            closeSocketOnly()
            blocked("BLUETOOTH_CONNECT permission required: ${error.message ?: "security exception"}")
        }
    }

    private fun adapterOrNull(): BluetoothAdapter? = context.getSystemService(BluetoothManager::class.java)?.adapter

    private fun persistedSelectedAddress(): String = preferences.getString(SELECTED_ADDRESS_KEY, "").orEmpty()

    private fun hasConnectPermission(): Boolean {
        return !requiresConnectPermission() || ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.BLUETOOTH_CONNECT,
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun hasScanPermission(): Boolean {
        return !requiresConnectPermission() || ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.BLUETOOTH_SCAN,
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun blocked(message: String): BluetoothPumpTransportStatus {
        val response = "BLOCKED $message"
        lastMessage = response
        return statusSnapshot(response)
    }

    private fun error(message: String): BluetoothPumpTransportStatus {
        val response = "ERROR $message"
        lastMessage = response
        return statusSnapshot(response)
    }

    private fun statusSnapshot(message: String): BluetoothPumpTransportStatus {
        val bonded = bondedDevices()
        val selectedAddress = persistedSelectedAddress()
        val selected = bonded.firstOrNull { it.address.equals(selectedAddress, ignoreCase = true) }
        val connected = socket?.isConnected == true
        return BluetoothPumpTransportStatus(
            connected = connected,
            selectedAddress = selectedAddress,
            selectedName = selected?.name.orEmpty(),
            deviceAddress = if (connected) connectedAddress else "",
            deviceName = if (connected) connectedName else "",
            bondedDeviceCount = bonded.size,
            message = message,
        )
    }

    private fun closeSocketOnly() {
        socket.closeQuietly()
        socket = null
        connectedAddress = ""
        connectedName = ""
    }

    private fun readAvailableResponse(input: InputStream, commandLetter: String): String {
        val responseWindowMs = if (commandLetter in setOf("a", "b", "c")) shortAckWindowMs else readWindowMs
        val deadline = System.currentTimeMillis() + responseWindowMs
        val response = StringBuilder()
        while (System.currentTimeMillis() < deadline) {
            val available = input.available()
            if (available > 0) {
                val buffer = ByteArray(available.coerceAtMost(256))
                val count = input.read(buffer)
                if (count > 0) {
                    response.append(String(buffer, 0, count, Charsets.US_ASCII))
                    val text = response.toString()
                    if (commandLetter == "s" && text.contains("STATUS steps=", ignoreCase = true)) break
                    if ((commandLetter == "c" || commandLetter == "r") && text.contains("STATUS steps=", ignoreCase = true)) break
                    if ((commandLetter == "a" || commandLetter == "b") && text.lineSequence().any { it.isNotBlank() }) break
                }
            } else {
                Thread.sleep(25)
            }
        }
        return response.toString()
    }

    private fun requiresConnectPermission(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
}

data class BondedPumpDevice(
    val name: String,
    val address: String,
    val likelyPump: Boolean = false,
) {
    val label: String get() = name.ifBlank { address }
}

data class BluetoothPumpTransportStatus(
    val connected: Boolean,
    val selectedAddress: String = "",
    val selectedName: String = "",
    val deviceAddress: String = "",
    val deviceName: String = "",
    val bondedDeviceCount: Int = 0,
    val message: String = "",
)

object PumpBluetoothDeviceSelector {
    val defaultPreferredNameHints = listOf("HC-05", "HC-06", "Arduino", "ESP32", "linvor")

    fun select(
        devices: List<BondedPumpDevice>,
        persistedAddress: String?,
        preferredNameHints: List<String> = defaultPreferredNameHints,
    ): BondedPumpDevice? {
        val selectedAddress = persistedAddress.orEmpty().trim()
        if (selectedAddress.isNotBlank()) {
            return devices.firstOrNull { it.address.equals(selectedAddress, ignoreCase = true) }
        }
        if (devices.isEmpty()) return null

        val withHints = devices.map { device ->
            val likely = device.likelyPump || hasPreferredName(device.name, preferredNameHints)
            if (likely == device.likelyPump) device else device.copy(likelyPump = likely)
        }
        val preferred = withHints.filter { it.likelyPump }
        if (preferred.isNotEmpty()) {
            return preferred.sortedWith(deviceComparator()).first()
        }
        return withHints.singleOrNull()
    }

    fun hasPreferredName(name: String, preferredNameHints: List<String> = defaultPreferredNameHints): Boolean {
        val normalized = name.lowercase(Locale.US)
        return preferredNameHints.any { hint -> normalized.contains(hint.lowercase(Locale.US)) }
    }

    private fun deviceComparator(): Comparator<BondedPumpDevice> = compareBy<BondedPumpDevice> {
        preferredRank(it.name)
    }.thenBy { it.name.lowercase(Locale.US) }.thenBy { it.address }

    private fun preferredRank(name: String): Int {
        val normalized = name.lowercase(Locale.US)
        return defaultPreferredNameHints.indexOfFirst { normalized.contains(it.lowercase(Locale.US)) }
            .let { if (it == -1) Int.MAX_VALUE else it }
    }
}

private fun BluetoothDevice.toBondedPumpDevice(preferredNameHints: List<String>): BondedPumpDevice {
    val safeName = try {
        name.orEmpty()
    } catch (_: SecurityException) {
        ""
    }
    val safeAddress = try {
        address.orEmpty().uppercase(Locale.US)
    } catch (_: SecurityException) {
        ""
    }
    return BondedPumpDevice(
        name = safeName,
        address = safeAddress,
        likelyPump = PumpBluetoothDeviceSelector.hasPreferredName(safeName, preferredNameHints),
    )
}

private fun BluetoothSocket?.closeQuietly() {
    try {
        this?.close()
    } catch (_: IOException) {
        // Best effort cleanup for failed/stale sockets.
    }
}
