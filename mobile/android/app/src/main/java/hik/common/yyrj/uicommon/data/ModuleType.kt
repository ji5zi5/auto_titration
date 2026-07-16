package hik.common.yyrj.uicommon.data

interface ModuleType {
    enum class F1ModuleType : ModuleType { F1, F1B }
    enum class F2ModuleType : ModuleType { F2, F23, F2V2, F0 }
}

typealias ModuleTypeF1ModuleType = ModuleType.F1ModuleType
typealias ModuleTypeF2ModuleType = ModuleType.F2ModuleType
