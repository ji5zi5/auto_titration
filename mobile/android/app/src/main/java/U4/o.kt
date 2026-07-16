package U4

import java.lang.reflect.Field
import java.lang.reflect.Modifier

abstract class o {
    companion object {
        private val a = HashMap<String, g>()

        @JvmStatic
        @Synchronized
        fun a(beanObject: Any): g {
            val className = beanObject.javaClass.name
            val cached = a[className]
            if (cached != null) return cached
            if (beanObject.javaClass.getAnnotation(f::class.java) == null) {
                throw h("No struct Annotation found for $className")
            }
            b(beanObject)
            val declaredFields = beanObject.javaClass.declaredFields
            val orderedSlots = arrayOfNulls<Field>(declaredFields.size)
            var count = 0
            for (field in declaredFields) {
                val order = field.getAnnotation(i::class.java) ?: continue
                val orderValue = order.order
                if (orderValue < 0 || orderValue >= declaredFields.size) {
                    throw h("Order is illegal for StructField : ${field.name}")
                }
                count++
                orderedSlots[orderValue] = field
            }
            val ordered = arrayOfNulls<Field>(count)
            for (idx in 0 until count) {
                ordered[idx] = orderedSlots[idx] ?: throw h("Order error for annotated fields! : $className")
            }
            val graph = g(Array(count) { ordered[it]!! }, beanObject.javaClass.declaredMethods)
            a[className] = graph
            return graph
        }

        @JvmStatic
        fun b(beanObject: Any) {
            val modifiers = beanObject.javaClass.modifiers
            if ((modifiers and Modifier.PUBLIC) == 0) {
                throw h("Struct operations are only accessible for public classes. Class: ${beanObject.javaClass.name}")
            }
            if ((modifiers and (Modifier.ABSTRACT or Modifier.INTERFACE)) != 0) {
                throw h("Struct operations are not accessible for abstract classes and interfaces. Class: ${beanObject.javaClass.name}")
            }
        }

        @JvmStatic
        fun c(modifiers: Int): Boolean = !((modifiers != 0) && ((modifiers and 6) == 0))
    }
}
