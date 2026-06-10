package kr.auto.titration.mobile

import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

const val MOBILE_FEATURE_SCHEMA_VERSION = "mobile_feature_frame.v1"

/**
 * Thin HTTP client for the laptop collector bridge.
 * The laptop endpoint is POST {serverBase}/api/mobile/ingest with {token, frame} JSON.
 */
class MobileFeatureClient(
    private val serverBase: String,
    private val pairingToken: String,
) {
    data class Result(
        val ok: Boolean,
        val statusCode: Int,
        val responseText: String,
    )

    fun postFeatureFrame(frame: JSONObject): Result {
        frame.put("schema", MOBILE_FEATURE_SCHEMA_VERSION)
        val endpoint = serverBase.trimEnd('/') + "/api/mobile/ingest"
        val body = JSONObject()
            .put("token", pairingToken)
            .put("frame", frame)
            .toString()

        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 900
            readTimeout = 900
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
        }

        return try {
            OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { writer ->
                writer.write(body)
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.use { input ->
                BufferedReader(InputStreamReader(input, Charsets.UTF_8)).readText()
            } ?: ""
            Result(ok = status in 200..299, statusCode = status, responseText = response)
        } finally {
            connection.disconnect()
        }
    }

    companion object {
        fun normalizeServerBase(raw: String): String {
            val trimmed = raw.trim()
            if (trimmed.startsWith("http://", ignoreCase = true) || trimmed.startsWith("https://", ignoreCase = true)) {
                return trimmed
            }
            return String.format(Locale.US, "http://%s", trimmed)
        }
    }
}
