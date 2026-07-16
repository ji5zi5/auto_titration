package d3

import hik.common.yyrj.uicommon.data.ModuleType
import hik.common.yyrj.uicommon.data.ModuleTypeF2ModuleType

class c private constructor() {
    fun a(moduleID: String?): ModuleType = when (moduleID?.uppercase()) {
        "F23" -> ModuleTypeF2ModuleType.F23
        "F2V2" -> ModuleTypeF2ModuleType.F2V2
        "F0" -> ModuleTypeF2ModuleType.F0
        else -> ModuleTypeF2ModuleType.F2
    }
    companion object { @JvmField val a: c = c() }
}
