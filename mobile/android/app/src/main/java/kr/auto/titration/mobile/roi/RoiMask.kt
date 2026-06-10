package kr.auto.titration.mobile.roi

import kr.auto.titration.mobile.vision.Roi
import kr.auto.titration.mobile.vision.RoiMask as VisionRoiMask

/** Runtime-capable contract mirror of Windows RoiMask for Android ROI parity. */
data class RoiMask(
    val mask: BooleanArray,
    val bbox: Roi,
    val confidence: Double,
    val source: String,
    val componentCount: Int,
    val stability: String,
    val frameWidth: Int = bbox.x + bbox.width,
    val frameHeight: Int = bbox.y + bbox.height,
    val shape: String = "mask",
) {
    init {
        require(frameWidth > 0 && frameHeight > 0) { "mask frame size must be positive" }
        require(mask.size == frameWidth * frameHeight) { "mask size must match frame dimensions" }
    }

    val areaPx: Int by lazy { mask.count { it } }
    val centroidX: Double by lazy { computeCentroid().first }
    val centroidY: Double by lazy { computeCentroid().second }
    val bboxString: String = "${bbox.x},${bbox.y},${bbox.width},${bbox.height}"

    fun toVision(): VisionRoiMask = VisionRoiMask(
        frameWidth = frameWidth,
        frameHeight = frameHeight,
        mask = mask.copyOf(),
        confidence = confidence,
        source = source,
        componentCount = componentCount,
        stability = stability,
    )

    private fun computeCentroid(): Pair<Double, Double> {
        var count = 0L
        var sumX = 0L
        var sumY = 0L
        for (y in 0 until frameHeight) {
            val row = y * frameWidth
            for (x in 0 until frameWidth) {
                if (mask[row + x]) {
                    count += 1
                    sumX += x.toLong()
                    sumY += y.toLong()
                }
            }
        }
        return if (count == 0L) {
            Pair(bbox.x + bbox.width / 2.0, bbox.y + bbox.height / 2.0)
        } else {
            Pair(sumX.toDouble() / count, sumY.toDouble() / count)
        }
    }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is RoiMask) return false
        return mask.contentEquals(other.mask) &&
            bbox == other.bbox &&
            confidence == other.confidence &&
            source == other.source &&
            componentCount == other.componentCount &&
            stability == other.stability &&
            frameWidth == other.frameWidth &&
            frameHeight == other.frameHeight &&
            shape == other.shape
    }

    override fun hashCode(): Int {
        var result = mask.contentHashCode()
        result = 31 * result + bbox.hashCode()
        result = 31 * result + confidence.hashCode()
        result = 31 * result + source.hashCode()
        result = 31 * result + componentCount
        result = 31 * result + stability.hashCode()
        result = 31 * result + frameWidth
        result = 31 * result + frameHeight
        result = 31 * result + shape.hashCode()
        return result
    }

    companion object {
        fun fromVision(mask: VisionRoiMask): RoiMask = RoiMask(
            mask = mask.mask.copyOf(),
            bbox = mask.bbox,
            confidence = mask.confidence,
            source = mask.source,
            componentCount = mask.componentCount,
            stability = mask.stability,
            frameWidth = mask.frameWidth,
            frameHeight = mask.frameHeight,
            shape = mask.shape,
        )
    }
}
