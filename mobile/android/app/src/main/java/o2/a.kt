package o2

import android.content.Context
import android.hardware.usb.UsbDevice

/** Official USB-device probe singleton shape. */
class a private constructor() {
    fun c(context: Context): UsbDevice? {
        val manager = context.getSystemService(Context.USB_SERVICE) as? android.hardware.usb.UsbManager
        return manager?.deviceList?.values?.firstOrNull()
    }

    companion object {
        @JvmField val a: o2.a = o2.a()
    }
}
