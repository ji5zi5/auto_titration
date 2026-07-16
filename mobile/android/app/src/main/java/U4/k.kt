package U4

import java.io.InputStream
import java.lang.reflect.Field
import java.lang.reflect.Method

abstract class k : InputStream() {
    protected abstract fun I(value: ByteArray)
    protected abstract fun Q(): Char
    protected abstract fun S(value: CharArray)
    protected abstract fun a0(): Double

    fun b(field: Field, beanObject: Any) {
        if (field.get(beanObject) == null) {
            if (field.type.name.endsWith("CString")) {
                throw h("CString objects should be initialized before unpacking :${field.name}")
            } else {
                field.set(beanObject, field.type.getDeclaredConstructor().newInstance())
            }
        }
        i0(field.get(beanObject))
    }

    protected abstract fun b0(value: DoubleArray)
    protected abstract fun c(): Boolean

    fun c0(info: j, getter: Method?, setter: Method?, beanObject: Any) {
        val field = info.a()
        if (field.type.isArray) {
            if (getter != null && getter.invoke(beanObject) == null) {
                throw h("Arrays can not be null : ${field.name}")
            }
            when (info.d()) {
                U4.b.a.BOOLEAN -> q((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as BooleanArray)
                U4.b.a.BYTE -> I((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as ByteArray)
                U4.b.a.SHORT -> k0((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as ShortArray)
                U4.b.a.INT -> f0((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as IntArray)
                U4.b.a.LONG -> h0((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as LongArray)
                U4.b.a.CHAR -> S((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as CharArray)
                U4.b.a.FLOAT -> e0((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as FloatArray)
                U4.b.a.DOUBLE -> b0((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as DoubleArray)
                U4.b.a.OBJECT -> if (getter == null) {
                    @Suppress("UNCHECKED_CAST")
                    val objects = field.get(beanObject) as Array<Any?>
                    for (idx in objects.indices) {
                        if (field.type.componentType != null) {
                            objects[idx] = field.type.componentType.getDeclaredConstructor().newInstance()
                        }
                    }
                    @Suppress("UNCHECKED_CAST")
                    j0(objects as Array<Any>)
                } else {
                    @Suppress("UNCHECKED_CAST")
                    j0(getter.invoke(beanObject) as Array<Any>)
                }
            }
        } else {
            when (info.d()) {
                U4.b.a.BOOLEAN -> if (setter == null) field.setBoolean(beanObject, c()) else setter.invoke(beanObject, c())
                U4.b.a.BYTE -> if (setter == null) field.setByte(beanObject, readByte()) else setter.invoke(beanObject, readByte())
                U4.b.a.SHORT -> if (setter == null) field.setShort(beanObject, readShort()) else setter.invoke(beanObject, readShort())
                U4.b.a.INT -> if (setter == null) field.setInt(beanObject, readInt()) else setter.invoke(beanObject, readInt())
                U4.b.a.LONG -> if (setter == null) field.setLong(beanObject, g0()) else setter.invoke(beanObject, g0())
                U4.b.a.CHAR -> if (setter == null) field.setChar(beanObject, Q()) else setter.invoke(beanObject, Q())
                U4.b.a.FLOAT -> if (setter == null) field.setFloat(beanObject, d0()) else setter.invoke(beanObject, d0())
                U4.b.a.DOUBLE -> if (setter == null) field.setDouble(beanObject, a0()) else setter.invoke(beanObject, a0())
                U4.b.a.OBJECT -> if (setter == null) {
                    b(field, beanObject)
                } else {
                    var value = getter!!.invoke(beanObject)
                    if (value == null) {
                        if (field.name.endsWith("CString")) {
                            throw h("CString objects should be initialized :${field.name}")
                        } else {
                            value = field.type.getDeclaredConstructor().newInstance()
                        }
                    }
                    i0(value)
                    setter.invoke(beanObject, value)
                }
            }
        }
    }

    override fun close() = Unit
    protected abstract fun d0(): Float
    protected abstract fun e0(value: FloatArray)
    protected abstract fun f0(value: IntArray)
    protected abstract fun g0(): Long
    protected abstract fun h0(value: LongArray)
    abstract fun i0(beanObject: Any?)
    protected abstract fun j0(value: Array<Any>)
    protected abstract fun k0(value: ShortArray)
    override fun read(): Int = -1
    protected abstract fun readByte(): Byte
    protected abstract fun readInt(): Int
    protected abstract fun readShort(): Short
    protected abstract fun q(value: BooleanArray)
}
