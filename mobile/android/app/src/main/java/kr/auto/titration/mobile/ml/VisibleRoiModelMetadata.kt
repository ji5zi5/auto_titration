package kr.auto.titration.mobile.ml

import android.content.Context
import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject

data class VisibleRoiModelMetadata(
    val assetPath: String,
    val sha256: String,
    val sourceModel: String,
    val exportCommand: String,
    val inputSize: Int,
    val acceptedClasses: Set<String>,
    val outputTensorContract: Map<String, String>,
    val runtime: String,
    val liteRtVersion: String,
    val placeholderModel: Boolean,
    val parityPolicy: String,
) {
    fun validateAssetSha256(context: Context): YoloModelAvailability {
        val bytes = try {
            context.assets.open(assetPath).use { it.readBytes() }
        } catch (_: Exception) {
            return YoloModelAvailability.unavailable("yolo_model_unavailable", "missing asset: $assetPath")
        }
        val actual = sha256Hex(bytes)
        if (!actual.equals(sha256, ignoreCase = true)) {
            return YoloModelAvailability.unavailable(
                "yolo_model_unavailable",
                "asset SHA256 mismatch for $assetPath expected=$sha256 actual=$actual",
            )
        }
        if (placeholderModel) {
            return YoloModelAvailability.unavailable(
                "yolo_model_unavailable",
                "placeholder_model=true; replace $assetPath with exported YOLO segmentation TFLite before claiming success",
            )
        }
        return YoloModelAvailability.available("model asset present and SHA256 verified")
    }

    companion object {
        const val DEFAULT_METADATA_ASSET = "models/yolo11n-seg-256-fp32.metadata.json"
        const val DEFAULT_MODEL_ASSET = "models/yolo11n-seg-256-fp32.tflite"
        const val EXPECTED_LITERT_VERSION = "2.1.5"

        fun load(context: Context, metadataAssetPath: String = DEFAULT_METADATA_ASSET): VisibleRoiModelMetadata {
            val raw = context.assets.open(metadataAssetPath).bufferedReader(Charsets.UTF_8).use { it.readText() }
            return fromJson(JSONObject(raw))
        }

        fun fromJson(json: JSONObject): VisibleRoiModelMetadata {
            return VisibleRoiModelMetadata(
                assetPath = json.optString("asset_path", DEFAULT_MODEL_ASSET),
                sha256 = json.optString("sha256"),
                sourceModel = json.optString("source_model"),
                exportCommand = json.optString("export_command"),
                inputSize = json.optInt("input_size", 0),
                acceptedClasses = json.optJSONArray("accepted_classes").toStringSet(),
                outputTensorContract = json.optJSONObject("output_tensor_contract").toStringMap(),
                runtime = json.optString("runtime"),
                liteRtVersion = json.optString("litert_version"),
                placeholderModel = json.optBoolean("placeholder_model", false),
                parityPolicy = json.optString("parity_policy"),
            )
        }

        fun sha256Hex(bytes: ByteArray): String {
            val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
            return digest.joinToString(separator = "") { byte -> "%02x".format(byte) }
        }
    }
}

private fun JSONArray?.toStringSet(): Set<String> {
    if (this == null) return emptySet()
    return List(length()) { index -> getString(index) }.map { it.trim() }.filter { it.isNotEmpty() }.toSet()
}

private fun JSONObject?.toStringMap(): Map<String, String> {
    if (this == null) return emptyMap()
    return keys().asSequence().associateWith { key -> optString(key) }
}
