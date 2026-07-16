package L5

import hik.common.yyrj.uicommon.data.ModuleType
import hik.common.yyrj.uicommon.data.ModuleTypeF2ModuleType

class d private constructor() {
    fun a(value: Float, mode: Int, moduleType: ModuleType): Byte = b(value, mode, moduleType).code.toByte()

    fun b(value: Float, mode: Int, moduleType: ModuleType): Char {
        val isF23 = moduleType == ModuleTypeF2ModuleType.F23
        val isF2V2 = moduleType == ModuleTypeF2ModuleType.F2V2
        val isF0 = moduleType == ModuleTypeF2ModuleType.F0
        return when (mode) {
            2 -> marker(value, -30f, -25f, 153f, 160f)
            3 -> when {
                isF23 -> marker(value, -30f, 95f, 663f, 685f)
                isF2V2 || isF0 -> marker(value, -30f, 95f, 408f, 420f)
                else -> marker(value, -30f, 95f, 357f, 370f)
            }
            else -> '+'
        }
    }

    fun c(value: Float, mode: Int, moduleType: ModuleType): Float {
        val isF23 = moduleType == ModuleTypeF2ModuleType.F23
        val isF2V2 = moduleType == ModuleTypeF2ModuleType.F2V2
        val isF0 = moduleType == ModuleTypeF2ModuleType.F0
        return when (mode) {
            2 -> clamp(value, -30f, -25f, 153f, 160f)
            3 -> when {
                isF23 -> clamp(value, -30f, 95f, 663f, 685f)
                isF2V2 || isF0 -> clamp(value, -30f, 95f, 408f, 420f)
                else -> clamp(value, -30f, 95f, 357f, 370f)
            }
            else -> value
        }
    }

    private fun marker(value: Float, lowLimit: Float, lowWarn: Float, highWarn: Float, highLimit: Float): Char = when {
        value < lowWarn && value >= lowLimit -> '~'
        value < lowLimit -> '<'
        value > highWarn && value <= highLimit -> '~'
        value > highLimit -> '>'
        else -> '+'
    }

    private fun clamp(value: Float, lowLimit: Float, lowWarn: Float, highWarn: Float, highLimit: Float): Float = when {
        value < lowWarn && value >= lowLimit -> value
        value < lowLimit -> lowLimit
        value > highWarn && value <= highLimit -> value
        value > highLimit -> highLimit
        else -> value
    }

    companion object { @JvmField val a: d = d() }
}
