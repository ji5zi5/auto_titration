package com.hik.f1module

import com.sun.jna.Library
import com.sun.jna.Native
import com.sun.jna.Pointer
import com.sun.jna.Structure

/** Extracted official preview-enable message boundary used by V2.a/V2.b. */
object F1UsbModuleHelper {
    @JvmStatic fun USB_SetPreviewEnable(enable: Boolean): Boolean {
        val payload = PreviewEnable().apply { this.enable = if (enable) 1 else 0; write() }
        val config = MessageConfig().apply { type = 5; devInfo = payload.pointer; len = 4; write() }
        return Native.load("_thermal_module", ThermalModule::class.java).thermal_function_set_msg(config.pointer) == 0
    }
    private interface ThermalModule : Library { fun thermal_function_set_msg(config: Pointer): Int }
    @Structure.FieldOrder("enable") private class PreviewEnable : Structure() { @JvmField var enable: Int = 0 }
    @Structure.FieldOrder("type", "devInfo", "len") private class MessageConfig : Structure() {
        @JvmField var type: Int = 0; @JvmField var devInfo: Pointer? = Pointer.NULL; @JvmField var len: Int = 0
    }
}
