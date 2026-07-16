package hik.common.yyrj.businesscommon.data

/** Narrow official DeviceInfoModel surface used by PreviewManagerII preference lookups. */
class DeviceInfoModel(
    private var serialNumber: String = "",
) {
    fun getSerialNumber(): String = serialNumber

    fun setSerialNumber(value: String) {
        serialNumber = value
    }
}
