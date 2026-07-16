package com.hik.viewercommon.data.bean

/** Official singleton identity model used by Viewer globals. */
sealed class UsbModuleType private constructor() {
    object NONE : UsbModuleType()
    object F1 : UsbModuleType()
    object F2 : UsbModuleType()
}
