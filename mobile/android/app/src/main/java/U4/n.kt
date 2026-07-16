package U4

import java.io.ByteArrayInputStream
import java.io.DataInput
import java.io.DataInputStream
import java.io.InputStream
import java.lang.reflect.Array as JArray
import java.nio.ByteOrder

class n(input: InputStream, byteOrder: ByteOrder) : k() {
    lateinit var a: DataInput

    init { l0(input, byteOrder) }
    constructor(buffer: ByteArray, byteOrder: ByteOrder) : this(ByteArrayInputStream(buffer), byteOrder)

    override fun I(value: ByteArray) { a.readFully(value) }
    override fun Q(): Char = a.readChar()
    override fun S(value: CharArray) { for (idx in value.indices) value[idx] = Q() }
    override fun a0(): Double = a.readDouble()
    override fun b0(value: DoubleArray) { for (idx in value.indices) value[idx] = a0() }
    override fun c(): Boolean = a.readBoolean()
    override fun d0(): Float = a.readFloat()
    override fun e0(value: FloatArray) { for (idx in value.indices) value[idx] = d0() }
    override fun f0(value: IntArray) { for (idx in value.indices) value[idx] = readInt() }
    override fun g0(): Long = a.readLong()
    override fun h0(value: LongArray) { for (idx in value.indices) value[idx] = g0() }

    override fun i0(beanObject: Any?) {
        if (beanObject == null) throw h("Struct objects cannot be null.")
        val graph = o.a(beanObject)
        val fields = graph.b()
        for (field in fields) {
            val info = graph.a(field.name) ?: throw h("Field Data not found for field: ${field.name}")
            val length: Int
            val hasMarker: Boolean
            if (!graph.f(field)) {
                length = -1
                hasMarker = false
            } else {
                val markerInfo = graph.a(graph.d(field.name)!!.name)!!
                length = if (!markerInfo.f()) {
                    (markerInfo.a().get(beanObject) as Number).toInt()
                } else {
                    (markerInfo.b()!!.invoke(beanObject) as Number).toInt()
                }
                hasMarker = true
            }
            if (!info.f()) {
                if (hasMarker && length >= 0) {
                    val array = JArray.newInstance(field.type.componentType, length)
                    field.set(beanObject, array)
                    if (!field.type.componentType.isPrimitive) {
                        @Suppress("UNCHECKED_CAST")
                        val objects = array as Array<Any?>
                        for (idx in 0 until length) objects[idx] = field.type.componentType.getDeclaredConstructor().newInstance()
                    }
                }
                if (!hasMarker && field.type.isArray && field.get(beanObject) == null) {
                    throw h("Arrays can not be null. : ${field.name}")
                }
                if (!hasMarker || (hasMarker && length >= 0)) c0(info, null, null, beanObject)
            } else {
                val getter = info.b()
                val setter = info.c()
                if (getter == null || setter == null) throw h(" getter/setter required for : ${field.name}")
                if (hasMarker && length >= 0) {
                    val array = JArray.newInstance(field.type.componentType, length)
                    setter.invoke(beanObject, array)
                    if (!field.type.componentType.isPrimitive) {
                        @Suppress("UNCHECKED_CAST")
                        val objects = array as Array<Any?>
                        for (idx in 0 until length) objects[idx] = field.type.componentType.getDeclaredConstructor().newInstance()
                    }
                }
                if (!hasMarker && field.type.isArray && getter.invoke(beanObject) == null) {
                    throw h("Arrays can not be null :${field.name}")
                }
                c0(info, getter, setter, beanObject)
            }
        }
    }

    override fun j0(value: Array<Any>) { for (item in value) i0(item) }
    override fun k0(value: ShortArray) { for (idx in value.indices) value[idx] = readShort() }
    protected fun l0(input: InputStream, byteOrder: ByteOrder) { a = if (byteOrder != ByteOrder.LITTLE_ENDIAN) DataInputStream(input) else d(input) }
    fun m0(beanObject: Any?) { i0(beanObject) }
    override fun q(value: BooleanArray) { for (idx in value.indices) value[idx] = c() }
    override fun readByte(): Byte = a.readByte()
    override fun readInt(): Int = a.readInt()
    override fun readShort(): Short = a.readShort()
}
