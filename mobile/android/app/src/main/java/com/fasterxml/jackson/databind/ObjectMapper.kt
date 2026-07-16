package com.fasterxml.jackson.databind

/** Narrow ObjectMapper surface used by the DEX-ported Viewer preference holder. */
class ObjectMapper {
    fun writeValueAsString(value: Any?): String = when (value) {
        null -> "null"
        is Iterable<*> -> value.joinToString(prefix = "[", postfix = "]") { "\"${escape(it.toString())}\"" }
        else -> "\"${escape(value.toString())}\""
    }

    @Suppress("UNCHECKED_CAST")
    fun <T> readValue(content: String?, valueType: Class<T>): T {
        if (MutableList::class.java.isAssignableFrom(valueType) || java.util.ArrayList::class.java.isAssignableFrom(valueType)) {
            return parseStringArray(content) as T
        }
        throw IllegalArgumentException("Narrow ObjectMapper only supports List/ArrayList values")
    }

    private fun parseStringArray(json: String?): java.util.ArrayList<String> {
        val values = java.util.ArrayList<String>()
        if (json == null) return values
        var i = skipWs(json, 0)
        if (i >= json.length || json[i] != '[') return values
        i++
        while (true) {
            i = skipWs(json, i)
            if (i >= json.length) return values
            if (json[i] == ']') return values
            require(json[i] == '"') { "Expected JSON string array" }
            i++
            val item = StringBuilder()
            while (i < json.length) {
                val ch = json[i++]
                if (ch == '"') break
                if (ch == '\\') {
                    require(i < json.length) { "Bad JSON escape" }
                    when (val esc = json[i++]) {
                        '"' -> item.append('"')
                        '\\' -> item.append('\\')
                        '/' -> item.append('/')
                        'b' -> item.append('\b')
                        'f' -> item.append('\u000C')
                        'n' -> item.append('\n')
                        'r' -> item.append('\r')
                        't' -> item.append('\t')
                        'u' -> {
                            require(i + 4 <= json.length) { "Bad unicode escape" }
                            item.append(json.substring(i, i + 4).toInt(16).toChar())
                            i += 4
                        }
                        else -> throw IllegalArgumentException("Bad JSON escape: $esc")
                    }
                } else {
                    item.append(ch)
                }
            }
            values.add(item.toString())
            i = skipWs(json, i)
            if (i < json.length && json[i] == ',') {
                i++
                continue
            }
            if (i < json.length && json[i] == ']') return values
        }
    }

    private fun skipWs(value: String, start: Int): Int {
        var i = start
        while (i < value.length && value[i].isWhitespace()) i++
        return i
    }

    private fun escape(value: String): String = buildString(value.length) {
        value.forEach { ch ->
            when (ch) {
                '"' -> append("\\\"")
                '\\' -> append("\\\\")
                '\b' -> append("\\b")
                '\u000C' -> append("\\f")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> append(ch)
            }
        }
    }
}
