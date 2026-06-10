package kr.auto.titration.mobile.ml

import android.content.Context
import java.io.File

/**
 * Availability gate for the visible-ROI YOLO segmentation runtime.
 *
 * This class deliberately does not fabricate detections: any missing runtime,
 * placeholder asset, SHA mismatch, or metadata/tensor mismatch returns an
 * explicit yolo_* reason for the bridge layer to surface.
 */
class LiteRtYoloSegmenter(
    private val context: Context,
    private val metadataAssetPath: String = VisibleRoiModelMetadata.DEFAULT_METADATA_ASSET,
) {
    fun availability(): YoloModelAvailability {
        val metadata = try {
            VisibleRoiModelMetadata.load(context, metadataAssetPath)
        } catch (error: Throwable) {
            return YoloModelAvailability.unavailable(
                "yolo_model_unavailable",
                "metadata unavailable at $metadataAssetPath: ${error.message ?: error.javaClass.simpleName}",
            )
        }

        val contract = YoloTensorContractValidator.validateTensorContract(metadata)
        if (!contract.available) return contract

        val asset = metadata.validateAssetSha256(context)
        if (!asset.available) return asset

        return try {
            Class.forName("org.tensorflow.lite.Interpreter")
            YoloModelAvailability.available("LiteRT Interpreter runtime and model asset are available")
        } catch (error: Throwable) {
            YoloModelAvailability.unavailable(
                "yolo_runtime_unavailable",
                "LiteRT runtime class unavailable: ${error.message ?: error.javaClass.simpleName}",
            )
        }
    }

    companion object {
        fun checkLiteRtDependencyCache(cacheRoot: File): YoloModelAvailability {
            if (!cacheRoot.exists()) {
                return YoloModelAvailability.unavailable(
                    "yolo_runtime_unavailable",
                    "LiteRT dependency cache root missing: ${cacheRoot.path}",
                )
            }
            val hasLiteRt215 = cacheRoot.walkTopDown().take(2_000).any { file ->
                file.path.contains("com.google.ai.edge.litert") &&
                    file.path.contains("litert") &&
                    file.path.contains(VisibleRoiModelMetadata.EXPECTED_LITERT_VERSION)
            }
            return if (hasLiteRt215) {
                YoloModelAvailability.available("LiteRT 2.1.5 dependency cache entry found")
            } else {
                YoloModelAvailability.unavailable(
                    "yolo_runtime_unavailable",
                    "LiteRT 2.1.5 dependency cache entry missing under ${cacheRoot.path}",
                )
            }
        }
    }
}
