package U4

import java.io.OutputStream
import java.lang.reflect.Field
import java.lang.reflect.Method

abstract class l : OutputStream() {
    abstract fun I(value: Byte)
    abstract fun Q(value: ByteArray, count: Int)
    abstract fun S(value: Char)
    abstract fun a0(value: CharArray, count: Int)
    open fun b(field: Field, beanObject: Any) { k0(field.get(beanObject)) }
    abstract fun b0(value: Double)
    abstract fun c(value: Boolean)
    abstract fun c0(value: DoubleArray, count: Int)

    fun d0(info: j, getter: Method?, beanObject: Any, count: Int) {
        val field = info.a()
        if (field.type.isArray) {
            when (info.d()) {
                U4.b.a.BOOLEAN -> q((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as BooleanArray, count)
                U4.b.a.BYTE -> Q((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as ByteArray, count)
                U4.b.a.SHORT -> n0((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as ShortArray, count)
                U4.b.a.INT -> h0((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as IntArray, count)
                U4.b.a.LONG -> j0((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as LongArray, count)
                U4.b.a.CHAR -> a0((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as CharArray, count)
                U4.b.a.FLOAT -> f0((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as FloatArray, count)
                U4.b.a.DOUBLE -> c0((if (getter == null) field.get(beanObject) else getter.invoke(beanObject)) as DoubleArray, count)
                U4.b.a.OBJECT -> {
                    if (getter == null) {
                        @Suppress("UNCHECKED_CAST")
                    val objects = field.get(beanObject) as Array<Any?>
                        for (idx in objects.indices) {
                            if (field.type.componentType != null && objects[idx] == null) {
                                objects[idx] = field.type.componentType.getDeclaredConstructor().newInstance()
                            }
                        }
                        @Suppress("UNCHECKED_CAST")
                        l0(objects as Array<Any>, count)
                    } else {
                        @Suppress("UNCHECKED_CAST")
                        l0(getter.invoke(beanObject) as Array<Any>, count)
                    }
                }
            }
        } else {
            when (info.d()) {
                U4.b.a.BOOLEAN -> c(if (getter == null) field.getBoolean(beanObject) else getter.invoke(beanObject) as Boolean)
                U4.b.a.BYTE -> I(if (getter == null) field.getByte(beanObject) else getter.invoke(beanObject) as Byte)
                U4.b.a.SHORT -> m0(if (getter == null) field.getShort(beanObject) else getter.invoke(beanObject) as Short)
                U4.b.a.INT -> g0(if (getter == null) field.getInt(beanObject) else getter.invoke(beanObject) as Int)
                U4.b.a.LONG -> i0(if (getter == null) field.getLong(beanObject) else getter.invoke(beanObject) as Long)
                U4.b.a.CHAR -> S(if (getter == null) field.getChar(beanObject) else getter.invoke(beanObject) as Char)
                U4.b.a.FLOAT -> e0(if (getter == null) field.getFloat(beanObject) else getter.invoke(beanObject) as Float)
                U4.b.a.DOUBLE -> b0(if (getter == null) field.getDouble(beanObject) else getter.invoke(beanObject) as Double)
                U4.b.a.OBJECT -> if (getter == null) b(field, beanObject) else k0(getter.invoke(beanObject))
            }
        }
    }

    abstract fun e0(value: Float)
    abstract fun f0(value: FloatArray, count: Int)
    abstract fun g0(value: Int)
    abstract fun h0(value: IntArray, count: Int)
    abstract fun i0(value: Long)
    abstract fun j0(value: LongArray, count: Int)

    fun k0(beanObject: Any?) {
        if (beanObject == null) throw h("Struct classes cant be null. ")
        val graph = o.a(beanObject)
        val fields = graph.b()
        for (field in fields) {
            val info = graph.a(field.name) ?: throw h("Field Data not found for field: ${field.name}")
            val markerValue: Int
            val hasMarker: Boolean
            if (!info.e()) {
                markerValue = 0
                hasMarker = false
            } else {
                markerValue = if (!info.f()) {
                    (info.a().get(beanObject) as Number).toInt()
                } else {
                    (info.b()!!.invoke(beanObject) as Number).toInt()
                }
                hasMarker = true
            }
            if (!info.f()) {
                d0(info, null, beanObject, if (!hasMarker || markerValue < 0) -1 else markerValue)
            } else {
                d0(info, info.b(), beanObject, if (!hasMarker || markerValue < 0) -1 else markerValue)
            }
        }
    }

    abstract fun l0(value: Array<Any>, count: Int)
    abstract fun m0(value: Short)
    abstract fun n0(value: ShortArray, count: Int)
    abstract fun q(value: BooleanArray, count: Int)
    override fun write(b: Int) = Unit
}
