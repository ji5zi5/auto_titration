package kr.auto.titration.mobile.vision

import kotlin.math.max
import kotlin.math.min
import java.util.ArrayDeque

/** Mask operations shared by YOLO and thermal ROI detectors. */
object MaskOps {
    fun boundingBox(mask: RoiMask): Roi? {
        var minX = mask.frameWidth
        var minY = mask.frameHeight
        var maxX = -1
        var maxY = -1
        for (y in 0 until mask.frameHeight) {
            val row = y * mask.frameWidth
            for (x in 0 until mask.frameWidth) {
                if (mask.mask[row + x]) {
                    minX = min(minX, x)
                    minY = min(minY, y)
                    maxX = max(maxX, x)
                    maxY = max(maxY, y)
                }
            }
        }
        if (maxX < minX || maxY < minY) return null
        return Roi(minX, minY, max(1, maxX - minX + 1), max(1, maxY - minY + 1), "mask")
    }

    fun clampRoi(roi: Roi, frameWidth: Int, frameHeight: Int): Roi {
        val safeFrameWidth = frameWidth.coerceAtLeast(1)
        val safeFrameHeight = frameHeight.coerceAtLeast(1)
        val x = roi.x.coerceIn(0, max(0, safeFrameWidth - 1))
        val y = roi.y.coerceIn(0, max(0, safeFrameHeight - 1))
        val width = roi.width.coerceAtLeast(1).coerceAtMost(max(1, safeFrameWidth - x))
        val height = roi.height.coerceAtLeast(1).coerceAtMost(max(1, safeFrameHeight - y))
        return roi.copy(x = x, y = y, width = width, height = height)
    }

    fun keepLargestComponent(mask: RoiMask, minAreaPx: Int = 4): RoiMask? {
        val visited = BooleanArray(mask.mask.size)
        val largest = mutableListOf<Int>()
        var componentCount = 0
        for (index in mask.mask.indices) {
            if (!mask.mask[index] || visited[index]) continue
            val component = floodFill(mask.mask, visited, mask.frameWidth, mask.frameHeight, index)
            if (component.size >= minAreaPx) {
                componentCount += 1
                if (component.size > largest.size) {
                    largest.clear()
                    largest.addAll(component)
                }
            }
        }
        if (largest.isEmpty()) return null
        val cleaned = BooleanArray(mask.mask.size)
        largest.forEach { cleaned[it] = true }
        return mask.copy(mask = cleaned, componentCount = componentCount.coerceAtLeast(1))
    }

    fun dilate(mask: BooleanArray, width: Int, height: Int, radius: Int = 1): BooleanArray {
        if (radius <= 0) return mask.copyOf()
        val out = BooleanArray(mask.size)
        for (y in 0 until height) {
            for (x in 0 until width) {
                var hit = false
                for (dy in -radius..radius) {
                    for (dx in -radius..radius) {
                        val sx = x + dx
                        val sy = y + dy
                        if (sx in 0 until width && sy in 0 until height && mask[sy * width + sx]) {
                            hit = true
                            break
                        }
                    }
                    if (hit) break
                }
                out[y * width + x] = hit
            }
        }
        return out
    }

    fun erode(mask: BooleanArray, width: Int, height: Int, radius: Int = 1): BooleanArray {
        if (radius <= 0) return mask.copyOf()
        val out = BooleanArray(mask.size)
        for (y in 0 until height) {
            for (x in 0 until width) {
                var keep = true
                for (dy in -radius..radius) {
                    for (dx in -radius..radius) {
                        val sx = x + dx
                        val sy = y + dy
                        if (sx !in 0 until width || sy !in 0 until height || !mask[sy * width + sx]) {
                            keep = false
                            break
                        }
                    }
                    if (!keep) break
                }
                out[y * width + x] = keep
            }
        }
        return out
    }

    fun smooth(mask: BooleanArray, width: Int, height: Int): BooleanArray = erode(dilate(mask, width, height), width, height)

    fun resizeNearest(mask: BooleanArray, fromWidth: Int, fromHeight: Int, toWidth: Int, toHeight: Int): BooleanArray {
        val out = BooleanArray(toWidth * toHeight)
        for (y in 0 until toHeight) {
            val sy = ((y.toDouble() + 0.5) * fromHeight / toHeight).toInt().coerceIn(0, fromHeight - 1)
            for (x in 0 until toWidth) {
                val sx = ((x.toDouble() + 0.5) * fromWidth / toWidth).toInt().coerceIn(0, fromWidth - 1)
                out[y * toWidth + x] = mask[sy * fromWidth + sx]
            }
        }
        return out
    }

    private fun floodFill(mask: BooleanArray, visited: BooleanArray, width: Int, height: Int, start: Int): List<Int> {
        val queue = ArrayDeque<Int>()
        val component = mutableListOf<Int>()
        visited[start] = true
        queue.add(start)
        while (!queue.isEmpty()) {
            val index = queue.removeFirst()
            component.add(index)
            val x = index % width
            val y = index / width
            val neighbors = intArrayOf(
                if (x > 0) index - 1 else -1,
                if (x + 1 < width) index + 1 else -1,
                if (y > 0) index - width else -1,
                if (y + 1 < height) index + width else -1,
            )
            for (next in neighbors) {
                if (next >= 0 && !visited[next] && mask[next]) {
                    visited[next] = true
                    queue.add(next)
                }
            }
        }
        return component
    }
}
