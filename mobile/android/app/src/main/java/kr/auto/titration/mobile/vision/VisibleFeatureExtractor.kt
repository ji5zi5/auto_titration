package kr.auto.titration.mobile.vision

import androidx.camera.core.ImageProxy
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sqrt

/** Phone-local RGB/HSV feature extraction from CameraX YUV_420_888 frames. */
object VisibleFeatureExtractor {
    fun defaultCenterRoi(frameWidth: Int, frameHeight: Int): Roi {
        val width = max(1, frameWidth / 2)
        val height = max(1, frameHeight / 2)
        return Roi(
            x = max(0, (frameWidth - width) / 2),
            y = max(0, (frameHeight - height) / 2),
            width = width,
            height = height,
            shape = "center_rect",
        )
    }

    fun extract(image: ImageProxy, roi: Roi, previous: VisibleFeatures? = null): VisibleFeatures {
        val safeRoi = clampRoi(roi, image.width, image.height)
        val yPlane = image.planes[0]
        val uPlane = image.planes[1]
        val vPlane = image.planes[2]
        val yBuffer = yPlane.buffer.duplicate()
        val uBuffer = uPlane.buffer.duplicate()
        val vBuffer = vPlane.buffer.duplicate()

        var count = 0L
        var rSum = 0.0
        var gSum = 0.0
        var bSum = 0.0
        var hSum = 0.0
        var sSum = 0.0
        var vSum = 0.0

        val xEnd = safeRoi.x + safeRoi.width
        val yEnd = safeRoi.y + safeRoi.height
        for (py in safeRoi.y until yEnd) {
            for (px in safeRoi.x until xEnd) {
                val yValue = yBuffer.get(yPlane.rowStride * py + yPlane.pixelStride * px).toInt() and 0xff
                val uvX = px / 2
                val uvY = py / 2
                val uValue = uBuffer.get(uPlane.rowStride * uvY + uPlane.pixelStride * uvX).toInt() and 0xff
                val vValue = vBuffer.get(vPlane.rowStride * uvY + vPlane.pixelStride * uvX).toInt() and 0xff
                val rgb = yuvToRgb(yValue, uValue, vValue)
                val hsv = rgbToHsv(rgb.r, rgb.g, rgb.b)
                rSum += rgb.r
                gSum += rgb.g
                bSum += rgb.b
                hSum += hsv.h
                sSum += hsv.s
                vSum += hsv.v
                count += 1
            }
        }

        if (count == 0L) {
            return VisibleFeatures(image.width, image.height, safeRoi)
        }
        val rMean = rSum / count
        val gMean = gSum / count
        val bMean = bSum / count
        val hMean = hSum / count
        val sMean = sSum / count
        val vMean = vSum / count
        val hsvDelta = previous?.let { prior ->
            sqrt(
                hueDistance(hMean, prior.hMean ?: hMean).pow(2) +
                    (sMean - (prior.sMean ?: sMean)).pow(2) +
                    (vMean - (prior.vMean ?: vMean)).pow(2),
            )
        }
        val colorDelta = previous?.let { prior ->
            sqrt(
                (rMean - (prior.rMean ?: rMean)).pow(2) +
                    (gMean - (prior.gMean ?: gMean)).pow(2) +
                    (bMean - (prior.bMean ?: bMean)).pow(2),
            )
        }
        return VisibleFeatures(
            frameWidth = image.width,
            frameHeight = image.height,
            roi = safeRoi,
            rMean = rMean,
            gMean = gMean,
            bMean = bMean,
            hMean = hMean,
            sMean = sMean,
            vMean = vMean,
            hsvDelta = hsvDelta ?: 0.0,
            colorDelta = colorDelta ?: 0.0,
        )
    }

    fun rgbToHsv(r: Int, g: Int, b: Int): Hsv {
        val rf = r / 255.0
        val gf = g / 255.0
        val bf = b / 255.0
        val maxValue = max(rf, max(gf, bf))
        val minValue = min(rf, min(gf, bf))
        val delta = maxValue - minValue
        val hue = when {
            delta == 0.0 -> 0.0
            maxValue == rf -> (60.0 * (((gf - bf) / delta) % 6.0) + 360.0) % 360.0
            maxValue == gf -> 60.0 * (((bf - rf) / delta) + 2.0)
            else -> 60.0 * (((rf - gf) / delta) + 4.0)
        }
        val saturation = if (maxValue == 0.0) 0.0 else delta / maxValue
        return Hsv(hue, saturation, maxValue)
    }

    private fun yuvToRgb(y: Int, u: Int, v: Int): Rgb {
        val c = y - 16
        val d = u - 128
        val e = v - 128
        val r = clamp((298 * c + 409 * e + 128) shr 8)
        val g = clamp((298 * c - 100 * d - 208 * e + 128) shr 8)
        val b = clamp((298 * c + 516 * d + 128) shr 8)
        return Rgb(r, g, b)
    }

    private fun clamp(value: Int): Int = min(255, max(0, value))

    private fun clampRoi(roi: Roi, frameWidth: Int, frameHeight: Int): Roi {
        val x = roi.x.coerceIn(0, max(0, frameWidth - 1))
        val y = roi.y.coerceIn(0, max(0, frameHeight - 1))
        val width = roi.width.coerceAtMost(frameWidth - x).coerceAtLeast(1)
        val height = roi.height.coerceAtMost(frameHeight - y).coerceAtLeast(1)
        return roi.copy(x = x, y = y, width = width, height = height)
    }

    private fun hueDistance(a: Double, b: Double): Double {
        val diff = abs(a - b) % 360.0
        return min(diff, 360.0 - diff) / 180.0
    }
}

data class Rgb(val r: Int, val g: Int, val b: Int)
data class Hsv(val h: Double, val s: Double, val v: Double)
