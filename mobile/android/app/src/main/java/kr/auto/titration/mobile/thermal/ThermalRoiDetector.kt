package kr.auto.titration.mobile.thermal

import kr.auto.titration.mobile.vision.MaskOps
import kr.auto.titration.mobile.vision.RoiDetectionResult
import kr.auto.titration.mobile.vision.roiMaskFromBool
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/** Raw-matrix contrast thermal ROI detector equivalent to Windows auto_detect_thermal_roi. */
object ThermalRoiDetector {
    private const val FLAT_RAW_MATRIX_REASON = "thermal_raw_contrast_flat"

    fun detect(rawValues: IntArray?, width: Int, height: Int): RoiDetectionResult {
        if (rawValues == null || rawValues.isEmpty() || width <= 0 || height <= 0) {
            return RoiDetectionResult(false, "thermal", false, "thermal_raw_matrix_unavailable", status = "failed")
        }
        val count = width * height
        if (rawValues.size != count) {
            return RoiDetectionResult(false, "thermal", false, "thermal_raw_matrix_exact_size_required", status = "failed")
        }
        val values = rawValues.copyOf()
        val mean = values.average()
        var variance = 0.0
        var minValue = Int.MAX_VALUE
        var maxValue = Int.MIN_VALUE
        for (i in 0 until count) {
            val v = values[i]
            minValue = minOf(minValue, v)
            maxValue = maxOf(maxValue, v)
            variance += (v - mean) * (v - mean)
        }
        val std = sqrt(variance / count)
        if (maxValue - minValue < 8 || std < 1.0) {
            return RoiDetectionResult(false, "thermal", false, FLAT_RAW_MATRIX_REASON, status = "failed")
        }
        val median = median(values)
        val threshold = max(8.0, std * 0.7)
        val mask = BooleanArray(count)
        for (i in 0 until count) {
            mask[i] = abs(values[i] - median) >= threshold
        }
        val smoothed = MaskOps.smooth(mask, width, height)
        val minAreaPx = max(12, (count * 0.0005).toInt())
        val rawMask = roiMaskFromBool(smoothed, width, height, confidence = confidence(std, minValue, maxValue), source = "thermal_contrast_candidate")
        val largest = MaskOps.keepLargestComponent(rawMask, minAreaPx = minAreaPx)
            ?: return RoiDetectionResult(false, "thermal", false, "no_thermal_candidate", status = "failed")
        if (largest.areaPx < max(40, (count * 0.003).toInt())) {
            return RoiDetectionResult(false, "thermal", false, "not_enough_thermal_contrast", confidence = 0.1, status = "failed")
        }
        return RoiDetectionResult(
            ok = true,
            target = "thermal",
            appliedNow = true,
            reason = "thermal_contrast_candidate",
            confidence = largest.confidence,
            thermalMask = largest,
            status = "applied",
        )
    }

    private fun confidence(std: Double, minValue: Int, maxValue: Int): Double {
        val dynamic = (maxValue - minValue).coerceAtLeast(1)
        return min(0.95, max(0.5, 0.45 + min(0.15, std / dynamic.toDouble())))
    }

    private fun median(values: IntArray): Double {
        val sorted = values.copyOf()
        sorted.sort()
        val middle = sorted.size / 2
        return if (sorted.size % 2 == 0) {
            (sorted[middle - 1].toDouble() + sorted[middle].toDouble()) / 2.0
        } else {
            sorted[middle].toDouble()
        }
    }
}
