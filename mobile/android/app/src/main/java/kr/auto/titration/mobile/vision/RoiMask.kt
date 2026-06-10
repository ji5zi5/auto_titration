package kr.auto.titration.mobile.vision

import org.json.JSONObject
import kotlin.math.max

/** Windows RoiMask-equivalent metadata for Android ROI parity. */
data class RoiMask(
    val frameWidth: Int,
    val frameHeight: Int,
    val mask: BooleanArray,
    val confidence: Double,
    val source: String,
    val componentCount: Int = 1,
    val stability: String = "fresh",
) {
    init {
        require(frameWidth > 0 && frameHeight > 0) { "mask frame size must be positive" }
        require(mask.size == frameWidth * frameHeight) { "mask size must match frame dimensions" }
    }

    val areaPx: Int by lazy { mask.count { it } }
    val bbox: Roi by lazy { MaskOps.boundingBox(this) ?: Roi(0, 0, 1, 1, "mask_empty") }
    val centroidX: Double by lazy { computeCentroid().first }
    val centroidY: Double by lazy { computeCentroid().second }
    val shape: String = "mask"

    fun contains(x: Int, y: Int): Boolean {
        if (x !in 0 until frameWidth || y !in 0 until frameHeight) return false
        return mask[y * frameWidth + x]
    }

    fun withStability(value: String): RoiMask = copy(stability = value)

    fun bboxCsvString(): String = "${bbox.x},${bbox.y},${bbox.width},${bbox.height}"

    fun toJson(prefix: String? = null): JSONObject {
        val keyPrefix = prefix?.takeIf { it.isNotBlank() }?.let { "${it}_" } ?: ""
        return JSONObject()
            .put("${keyPrefix}roi_shape", shape)
            .put("${keyPrefix}mask_source", source)
            .put("${keyPrefix}mask_area_px", areaPx)
            .put("${keyPrefix}mask_bbox", bboxCsvString())
            .put("${keyPrefix}mask_confidence", confidence)
            .put("${keyPrefix}mask_component_count", componentCount)
            .put("${keyPrefix}mask_stability", stability)
            .put("${keyPrefix}mask_centroid_x", centroidX)
            .put("${keyPrefix}mask_centroid_y", centroidY)
    }

    private fun computeCentroid(): Pair<Double, Double> {
        var sumX = 0L
        var sumY = 0L
        var count = 0L
        for (y in 0 until frameHeight) {
            val row = y * frameWidth
            for (x in 0 until frameWidth) {
                if (mask[row + x]) {
                    sumX += x.toLong()
                    sumY += y.toLong()
                    count += 1
                }
            }
        }
        return if (count > 0) {
            Pair(sumX.toDouble() / count, sumY.toDouble() / count)
        } else {
            Pair(max(0, frameWidth - 1) / 2.0, max(0, frameHeight - 1) / 2.0)
        }
    }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is RoiMask) return false
        return frameWidth == other.frameWidth &&
            frameHeight == other.frameHeight &&
            mask.contentEquals(other.mask) &&
            confidence == other.confidence &&
            source == other.source &&
            componentCount == other.componentCount &&
            stability == other.stability
    }

    override fun hashCode(): Int {
        var result = frameWidth
        result = 31 * result + frameHeight
        result = 31 * result + mask.contentHashCode()
        result = 31 * result + confidence.hashCode()
        result = 31 * result + source.hashCode()
        result = 31 * result + componentCount
        result = 31 * result + stability.hashCode()
        return result
    }
}

fun roiMaskFromBool(
    mask: BooleanArray,
    frameWidth: Int,
    frameHeight: Int,
    confidence: Double,
    source: String,
    componentCount: Int = 1,
    stability: String = "fresh",
): RoiMask = RoiMask(
    frameWidth = frameWidth,
    frameHeight = frameHeight,
    mask = mask,
    confidence = confidence,
    source = source,
    componentCount = componentCount,
    stability = stability,
)
