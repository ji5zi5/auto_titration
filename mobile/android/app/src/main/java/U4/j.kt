package U4

import java.lang.reflect.Field
import java.lang.reflect.Method

class j(private val field: Field) {
    private var usesAccessor = false
    private var getter: Method? = null
    private var setter: Method? = null
    private var lengthMarker = false
    private var fieldType: b.a? = null

    fun a(): Field = field
    fun b(): Method? = getter
    fun c(): Method? = setter
    fun d(): b.a = fieldType ?: b.a.OBJECT
    fun e(): Boolean = lengthMarker
    fun f(): Boolean = usesAccessor
    fun g(value: Boolean) { lengthMarker = value }
    fun h(value: Method?) { getter = value }
    fun i(value: Boolean) { usesAccessor = value }
    fun j(value: Method?) { setter = value }
    fun k(value: b.a) { fieldType = value }
}
