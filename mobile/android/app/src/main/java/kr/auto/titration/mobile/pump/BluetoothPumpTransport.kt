package kr.auto.titration.mobile.pump

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
import java.io.IOException
import java.util.Locale
import java.util.UUID

/** Bluetooth Classic SPP transport for HC-05/HC-06/Arduino serial modules. */
class BluetoothPumpTransport(
    private val context: Context,
    private val preferredNameHints: List<String> = listOf("HC-05", "HC-06", "Arduino", "ESP32", "linvor"),
    private val readWindowMs: Long = 1_200L,
) : PumpCommandTransport {
    companion object {
        val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
    }

    @SuppressLint("MissingPermission", "HardwareIds")
    override fun sendCommand(command: String): String {
        val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter
            ?: return "BLOCKED BluetoothAdapter unavailable"
        if (!adapter.isEnabled) {
            return "BLOCKED Bluetooth adapter is off"
        }
        if (requiresConnectPermission() && ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.BLUETOOTH_CONNECT,
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            return "BLOCKED BLUETOOTH_CONNECT permission required"
        }

        val device = selectBondedDevice(adapter)
            ?: return "BLOCKED paired Bluetooth SPP pump not found; pair HC-05/HC-06/Arduino in Android settings first"
        val label = device.name ?: device.address ?: "unknown"
        val letter = command.trim().take(1).lowercase(Locale.US)
        PumpCommandContract.requireSupported(letter)

        return try {
            val socket = device.createRfcommSocketToServiceRecord(SPP_UUID)
            socket.use { btSocket ->
                btSocket.connect()
                val output = btSocket.outputStream
                output.write((letter + "\n").toByteArray(Charsets.US_ASCII))
                output.flush()
                val body = readAvailableResponse(btSocket.inputStream, letter)
                buildString {
                    append("BT_DEVICE ").append(label).append('\n')
                    if (body.isBlank()) {
                        append("OK sent=").append(letter)
                    } else {
                        append(body.trim())
                    }
                }
            }
        } catch (error: IOException) {
            "ERROR Bluetooth SPP ${error.javaClass.simpleName}: ${error.message ?: "connection failed"}"
        } catch (error: SecurityException) {
            "BLOCKED BLUETOOTH_CONNECT permission required: ${error.message ?: "security exception"}"
        }
    }

    @SuppressLint("MissingPermission")
    private fun selectBondedDevice(adapter: BluetoothAdapter): BluetoothDevice? {
        val bonded = adapter.bondedDevices.orEmpty().toList()
        if (bonded.isEmpty()) return null
        val preferred = bonded.firstOrNull { device ->
            val name = device.name.orEmpty().lowercase(Locale.US)
            preferredNameHints.any { hint -> name.contains(hint.lowercase(Locale.US)) }
        }
        return preferred ?: bonded.singleOrNull() ?: bonded.firstOrNull()
    }

    private fun readAvailableResponse(input: java.io.InputStream, commandLetter: String): String {
        val deadline = System.currentTimeMillis() + readWindowMs
        val response = StringBuilder()
        while (System.currentTimeMillis() < deadline) {
            val available = input.available()
            if (available > 0) {
                val buffer = ByteArray(available.coerceAtMost(256))
                val count = input.read(buffer)
                if (count > 0) {
                    response.append(String(buffer, 0, count, Charsets.US_ASCII))
                    val text = response.toString()
                    if (commandLetter == "s" && text.contains("STATUS steps=")) break
                    if ((commandLetter == "c" || commandLetter == "r") && text.contains("STATUS steps=")) break
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
