package U4

import java.lang.reflect.Field

abstract class b {
    enum class a(val typeName: String, val arrayCode: Char, val code: Int) {
        BOOLEAN("boolean", 'Z', 0),
        BYTE("byte", 'B', 1),
        CHAR("char", 'C', 2),
        SHORT("short", 'S', 3),
        INT("int", 'I', 4),
        LONG("long", 'J', 5),
        FLOAT("float", 'F', 6),
        DOUBLE("double", 'D', 7),
        OBJECT("object", 'O', 8),
    }

    companion object {
        private val byName = HashMap<String, a>()
        private val byArrayCode = HashMap<Char, a>()

        init {
            for (value in a.entries) {
                byName[value.typeName] = value
                byArrayCode[value.arrayCode] = value
            }
        }

        @JvmStatic
        fun a(typeCode: Char): a = byArrayCode[typeCode] ?: a.OBJECT

        @JvmStatic
        fun b(typeName: String): a = byName[typeName] ?: a.OBJECT

        @JvmStatic
        fun c(field: Field): a = if (field.type.isArray) a(field.type.name[1]) else b(field.type.name)
    }
}
