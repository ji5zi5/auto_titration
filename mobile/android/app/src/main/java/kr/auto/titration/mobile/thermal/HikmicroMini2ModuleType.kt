package kr.auto.titration.mobile.thermal

import android.hardware.usb.UsbDevice
import org.json.JSONObject

/**
 * Official-app USB routing extracted from the HIKMICRO Viewer APK.
 *
 * Evidence artifact:
 * .omx/analysis/hikmicro_viewer_xapk/f1_f2_runtime_selection_deep_dive.md
 */
enum class HikmicroMini2ModuleType(val routeName: String, val backendName: String) {
    F1("f1", "hikmicro_f1_thermal_module"),
    F2("f2", "hikmicro_f2_hcusb_sdk"),
    UNSUPPORTED("unsupported", "unsupported_hikmicro_usb"),
    ;

    val isSupported: Boolean
        get() = this == F1 || this == F2

    companion object {
        const val HIKMICRO_VENDOR_ID = 0x2bdf // 11231
        const val HIKMICRO_F1_PRODUCT_ID = 0x0140 // 320
        const val HIKMICRO_F2_PRODUCT_ID_0102 = 0x0102 // 258
        const val HIKMICRO_F2_PRODUCT_ID_0101 = 0x0101 // 257
        const val HIKMICRO_F2_ALT_VENDOR_ID = 0x20af // 8367

        fun isOfficialF1Route(vendorId: Int, productId: Int): Boolean =
            vendorId == HIKMICRO_VENDOR_ID && productId == HIKMICRO_F1_PRODUCT_ID

        fun isOfficialF2Route(vendorId: Int, productId: Int): Boolean =
            vendorId == HIKMICRO_VENDOR_ID &&
                (productId == HIKMICRO_F2_PRODUCT_ID_0102 || productId == HIKMICRO_F2_PRODUCT_ID_0101) ||
                vendorId == HIKMICRO_F2_ALT_VENDOR_ID

        fun classify(vendorId: Int, productId: Int): HikmicroMini2ModuleType = when {
            isOfficialF1Route(vendorId, productId) -> F1
            isOfficialF2Route(vendorId, productId) -> F2
            else -> UNSUPPORTED
        }

        fun classify(device: UsbDevice): HikmicroMini2ModuleType = classify(device.vendorId, device.productId)

        fun isHikmicroCandidate(device: UsbDevice): Boolean =
            device.vendorId == HIKMICRO_VENDOR_ID || device.vendorId == HIKMICRO_F2_ALT_VENDOR_ID

        fun routeReason(vendorId: Int, productId: Int): String {
            return when (classify(vendorId, productId)) {
                F1 -> "official_apk_vid_pid_route 11231:320 -> F1 _thermal_module"
                F2 -> "official_apk_vid_pid_route ${vendorId}:${productId} -> F2 HCUSBSDK"
                UNSUPPORTED -> "unsupported_vid_pid ${vendorId}:${productId}; official routes are 11231:320(F1), 11231:258/257(F2), 8367:*(F2)"
            }
        }

        fun routeJson(device: UsbDevice?): JSONObject {
            if (device == null) {
                return JSONObject()
                    .put("module_type", UNSUPPORTED.routeName)
                    .put("backend", UNSUPPORTED.backendName)
                    .put("reason", "device_not_found")
            }
            val type = classify(device)
            return JSONObject()
                .put("module_type", type.routeName)
                .put("backend", type.backendName)
                .put("reason", routeReason(device.vendorId, device.productId))
                .put("vendor_id_decimal", device.vendorId)
                .put("product_id_decimal", device.productId)
                .put("vendor_id_hex", String.format("0x%04x", device.vendorId))
                .put("product_id_hex", String.format("0x%04x", device.productId))
        }
    }
}
