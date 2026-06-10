package kr.auto.titration.mobile.data

import java.io.Writer

/** Minimal append-only CSV writer for phone-local experiment export. */
class LocalCsvWriter(
    private val writer: Writer,
    private val columns: List<String> = CsvSchema.coreColumns,
) {
    private var headerWritten = false

    fun writeHeaderIfNeeded() {
        if (!headerWritten) {
            writer.append(columns.joinToString(",") { escape(it) })
            writer.append('\n')
            headerWritten = true
        }
    }

    fun appendRow(row: Map<String, String>) {
        writeHeaderIfNeeded()
        writer.append(columns.joinToString(",") { column -> escape(row[column].orEmpty()) })
        writer.append('\n')
        writer.flush()
    }

    fun flush() {
        writer.flush()
    }

    private fun escape(value: String): String {
        val mustQuote = value.any { it == ',' || it == '"' || it == '\n' || it == '\r' }
        if (!mustQuote) return value
        return "\"" + value.replace("\"", "\"\"") + "\""
    }
}
