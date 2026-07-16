package com.hcusbsdk.Interface

import android.hardware.usb.UsbDeviceConnection

/** Java-facing official facade DTO. Native JNA structs remain byte-array based. */
class USB_DEVICE_INFO {
    var dwSize: Int = 0
    @JvmField var dwIndex: Int = 0
    @JvmField var dwVID: Int = 0
    @JvmField var dwPID: Int = 0
    @JvmField var szManufacturer: String = ""
    @JvmField var szDeviceName: String = ""
    @JvmField var szSerialNumber: String = ""
    @JvmField var byHaveAudio: Byte = 0
    var byRes: ByteArray = ByteArray(255)
    @JvmField var dwFd: Int = 0

    @Transient
    var usbDeviceConnection: UsbDeviceConnection? = null

    fun closeConnection() {
        usbDeviceConnection?.close()
        usbDeviceConnection = null
    }

    fun copyFrom(other: USB_DEVICE_INFO) {
        dwSize = other.dwSize
        dwIndex = other.dwIndex
        dwVID = other.dwVID
        dwPID = other.dwPID
        szManufacturer = other.szManufacturer
        szDeviceName = other.szDeviceName
        szSerialNumber = other.szSerialNumber
        byHaveAudio = other.byHaveAudio
        byRes = other.byRes.copyOf()
        dwFd = other.dwFd
        usbDeviceConnection = other.usbDeviceConnection
    }
}
