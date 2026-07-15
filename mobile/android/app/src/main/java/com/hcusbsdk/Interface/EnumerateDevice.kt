package com.hcusbsdk.Interface

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbManager
import android.os.Build

/** Official Android USB enumeration path recovered from Viewer 2.6.0. */
class EnumerateDevice {
    data class EnumeratedDevice(
        val device: UsbDevice,
        val connection: UsbDeviceConnection?,
        val fileDescriptor: Int,
    )

    fun EnumDevice(context: Context): Int {
        releaseOpenedConnections()
        val usbManager = context.getSystemService(Context.USB_SERVICE) as? UsbManager ?: return 0
        val filtered = usbManager.deviceList
            .filterValues { device -> isSupportedProduct(device.vendorId, device.productId) }

        synchronized(stateLock) {
            m_deviceList.clear()
            m_deviceList.putAll(filtered)
            m_fdList = IntArray(filtered.size)
        }

        val permissionIntent = PendingIntent.getBroadcast(
            context,
            0,
            Intent(USB_PERMISSION_ACTION),
            permissionIntentFlags(Build.VERSION.SDK_INT),
        )
        filtered.values.forEachIndexed { index, device ->
            if (!usbManager.hasPermission(device)) {
                usbManager.requestPermission(device, permissionIntent)
            }
            val connection = usbManager.openDevice(device)
            val fileDescriptor = connection?.fileDescriptor ?: 0
            synchronized(stateLock) {
                m_fdList[index] = fileDescriptor
                enumeratedDevices += EnumeratedDevice(device, connection, fileDescriptor)
            }
        }
        return filtered.size
    }

    fun drainEnumeratedDevices(): List<EnumeratedDevice> = synchronized(stateLock) {
        enumeratedDevices.toList().also { enumeratedDevices.clear() }
    }

    fun releaseOpenedConnections() {
        synchronized(stateLock) {
            enumeratedDevices.forEach { it.connection?.close() }
            enumeratedDevices.clear()
            m_deviceList.clear()
            m_fdList = IntArray(0)
        }
    }

    companion object {
        const val USB_PERMISSION_ACTION: String = "com.android.example.USB_PERMISSION"

        @JvmField
        val m_deviceList: LinkedHashMap<String, UsbDevice> = linkedMapOf()

        @JvmField
        var m_fdList: IntArray = IntArray(0)

        private val stateLock = Any()
        private val enumeratedDevices = mutableListOf<EnumeratedDevice>()

        private val exactProducts = setOf(
            11231 to 257,
            11231 to 383,
            3141 to 24576,
            3141 to 25446,
            4429 to 34185,
            11231 to 640,
            11231 to 645,
            3034 to 22594,
            11231 to 671,
            11231 to 769,
            1155 to 22352,
            1155 to 22315,
        )

        internal fun isSupportedProduct(vendorId: Int, productId: Int): Boolean =
            (vendorId to productId) in exactProducts ||
                ((vendorId == 11231 || vendorId == 8367) && productId in 257..512) ||
                (vendorId == 11231 && productId in 513..768) ||
                (vendorId == 11231 && productId in 769..1024) ||
                (vendorId == 11231 && productId in 1281..1536)

        internal fun permissionIntentFlags(sdkInt: Int): Int =
            if (sdkInt <= Build.VERSION_CODES.R) PendingIntent.FLAG_ONE_SHOT else PendingIntent.FLAG_IMMUTABLE
    }
}
