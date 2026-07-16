package p2

/** Official temperature-unit arithmetic helper: C/F/K only. */
class a private constructor() {
    fun a(value: Float): Float = 32f + value * 1.8f
    fun b(value: Float): Float = value + 273.15f
    fun c(value: Float): Float = (value - 32f) / 1.8f
    fun d(value: Float): Float = value - 273.15f
    companion object { @JvmField val a: a = a() }
}
