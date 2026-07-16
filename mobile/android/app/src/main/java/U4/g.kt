package U4

import java.lang.reflect.Field
import java.lang.reflect.Method

class g(private val fields: Array<Field>, private val methods: Array<Method>) {
    private val lengthMarkers = HashMap<String, Field>()
    private val metadata = HashMap<String, j>()

    init {
        for (field in fields) {
            val modifiers = field.modifiers
            if ((modifiers and e.inv()) != 0 || (modifiers or e) == 0) {
                throw h("Field type should be public, private or protected : ${field.name}")
            }
            val data = j(field)
            val lengthAnnotation = field.getAnnotation(a::class.java)
            if (lengthAnnotation != null) {
                data.g(true)
                var found = false
                for (candidate in fields) {
                    if (lengthAnnotation.fieldName == candidate.name) {
                        lengthMarkers[candidate.name] = field
                        found = true
                        break
                    }
                }
                if (!found) throw h("Lenght Marker Fields target is not found: ${lengthAnnotation.fieldName}")
            }
            if (o.c(field.modifiers)) {
                data.h(c(methods, field))
                data.j(e(methods, field))
                data.i(true)
            }
            data.k(b.c(field))
            metadata[field.name] = data
        }
    }

    fun a(name: String): j? = metadata[name]
    fun b(): Array<Field> = fields
    fun d(name: String): Field? = lengthMarkers[name]
    fun f(field: Field): Boolean = lengthMarkers[field.name] != null

    companion object {
        private const val e: Int = 7

        private fun c(methods: Array<Method>, field: Field): Method {
            val getName = "get${field.name}"
            val isName = "is${field.name}"
            for (method in methods) {
                if (method.name.equals(getName, ignoreCase = true)) return method
            }
            if (field.type.name == "boolean") {
                for (method in methods) {
                    if (method.name.equals(isName, ignoreCase = true)) return method
                }
            }
            throw h("The field needs a getter method, but none supplied. Field: ${field.name}")
        }

        private fun e(methods: Array<Method>, field: Field): Method {
            val setName = "set${field.name}"
            for (method in methods) {
                if (method.name.equals(setName, ignoreCase = true)) return method
            }
            throw h("The field needs a setter method, but none supplied. Field: ${field.name}")
        }
    }
}
