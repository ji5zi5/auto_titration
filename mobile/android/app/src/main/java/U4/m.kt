package U4

import java.io.ByteArrayOutputStream
import java.io.DataOutput
import java.io.DataOutputStream
import java.io.OutputStream
import java.nio.ByteOrder

class m(output: OutputStream, byteOrder: ByteOrder) : l() {
    private val a: ByteArrayOutputStream
    protected lateinit var b: DataOutput

    init {
        o0(output, byteOrder)
        a = output as ByteArrayOutputStream
    }

    constructor(byteOrder: ByteOrder) : this(ByteArrayOutputStream(), byteOrder)

    override fun I(value: Byte) { b.writeByte(value.toInt()) }
    override fun Q(value: ByteArray, count: Int) {
        if (count != 0) {
            val actual = if (count == -1 || count > value.size) value.size else count
            b.write(value, 0, actual)
        }
    }
    override fun S(value: Char) { b.writeChar(value.code) }
    override fun a0(value: CharArray, count: Int) { for (idx in 0 until bounded(count, value.size)) b.writeChar(value[idx].code) }
    override fun b0(value: Double) { b.writeDouble(value) }
    override fun c(value: Boolean) { b.writeBoolean(value) }
    override fun c0(value: DoubleArray, count: Int) { for (idx in 0 until bounded(count, value.size)) b.writeDouble(value[idx]) }
    override fun e0(value: Float) { b.writeFloat(value) }
    override fun f0(value: FloatArray, count: Int) { for (idx in 0 until bounded(count, value.size)) b.writeFloat(value[idx]) }
    override fun g0(value: Int) { b.writeInt(value) }
    override fun h0(value: IntArray, count: Int) { for (idx in 0 until bounded(count, value.size)) b.writeInt(value[idx]) }
    override fun i0(value: Long) { b.writeLong(value) }
    override fun j0(value: LongArray, count: Int) { for (idx in 0 until bounded(count, value.size)) b.writeLong(value[idx]) }
    override fun l0(value: Array<Any>, count: Int) {
        if (count != 0) {
            val actual = if (count == -1 || count > value.size) value.size else count
            for (idx in 0 until actual) k0(value[idx])
        }
    }
    override fun m0(value: Short) { b.writeShort(value.toInt()) }
    override fun n0(value: ShortArray, count: Int) { for (idx in 0 until bounded(count, value.size)) b.writeShort(value[idx].toInt()) }
    protected fun o0(output: OutputStream, byteOrder: ByteOrder) { b = if (byteOrder != ByteOrder.LITTLE_ENDIAN) DataOutputStream(output) else e(output) }
    fun p0(beanObject: Any): ByteArray { k0(beanObject); return a.toByteArray() }
    override fun q(value: BooleanArray, count: Int) { for (idx in 0 until bounded(count, value.size)) b.writeBoolean(value[idx]) }

    private fun bounded(count: Int, size: Int): Int = if (count == -1 || count > size) size else count
}
