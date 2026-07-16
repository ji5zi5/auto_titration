package u5

import com.hik.modulelib.UsbModuleInfo
import hik.common.yyrj.businesscommon.data.DeviceInfoModel

/** Official current-module accessor singleton used in Viewer preference keys. */
class B private constructor() {
    private var deviceInfo: DeviceInfoModel = DeviceInfoModel()

    fun k(): DeviceInfoModel = deviceInfo
    fun l(value: UsbModuleInfo) {
        deviceInfo = DeviceInfoModel(value.getSerialNumber())
    }
    fun L(): Int = l2.k.e("PERFORMANCE_F22X", -1)
    fun d0(): Boolean = O
    fun h0(): Boolean = thermalGraphState == "ThgStart"

    internal fun setPlaybackStartCallbackEnabled(value: Boolean) {
        O = value
    }

    internal fun setThermalGraphState(value: String) {
        thermalGraphState = value
    }

    companion object {
        @JvmField val a: B = B()
        private var thermalGraphState: String = ""
        private var O: Boolean = false
    }
}
