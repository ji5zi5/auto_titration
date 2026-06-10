package kr.auto.titration.mobile.vision

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import org.tensorflow.lite.Interpreter
import java.io.FileNotFoundException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import kotlin.math.ceil
import kotlin.math.exp
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min

/** Upright/rotated RGB frame prepared outside the CameraX hot path for YOLO segmentation. */
data class YoloInputFrame(
    val frameId: Long,
    val frameWidth: Int,
    val frameHeight: Int,
    val sensorWidth: Int,
    val sensorHeight: Int,
    val rotationDegrees: Int,
    val rgbFloat32: FloatArray,
) {
    init {
        require(frameWidth > 0 && frameHeight > 0) { "YOLO frame size must be positive" }
        require(sensorWidth > 0 && sensorHeight > 0) { "YOLO sensor size must be positive" }
        require(rgbFloat32.size == INPUT_SIZE * INPUT_SIZE * 3) { "YOLO input must be 256x256 RGB float32" }
    }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is YoloInputFrame) return false
        return frameId == other.frameId &&
            frameWidth == other.frameWidth &&
            frameHeight == other.frameHeight &&
            sensorWidth == other.sensorWidth &&
            sensorHeight == other.sensorHeight &&
            rotationDegrees == other.rotationDegrees &&
            rgbFloat32.contentEquals(other.rgbFloat32)
    }

    override fun hashCode(): Int {
        var result = frameId.hashCode()
        result = 31 * result + frameWidth
        result = 31 * result + frameHeight
        result = 31 * result + sensorWidth
        result = 31 * result + sensorHeight
        result = 31 * result + rotationDegrees
        result = 31 * result + rgbFloat32.contentHashCode()
        return result
    }

    companion object {
        const val INPUT_SIZE = 256
    }
}

/**
 * Android-visible ROI detector contract for the Windows YOLO segmentation path.
 *
 * The class refuses to emit YOLO success unless the packaged model, metadata,
 * SHA256, tensor contract, LiteRT runtime, and decoded segmentation mask are all
 * available. Missing pieces are surfaced as explicit yolo_* blocker reasons.
 */
open class YoloSegmentationDetector(
    private val context: Context,
    private val modelAsset: String = MODEL_ASSET,
    private val metadataAsset: String = METADATA_ASSET,
) {
    @Volatile
    private var interpreter: Interpreter? = null

    @Volatile
    private var interpreterModelBuffer: ByteBuffer? = null

    fun validateTensorContract(): ModelContractStatus {
        val metadata = try {
            JSONObject(context.assets.open(metadataAsset).bufferedReader().use { it.readText() })
        } catch (_: FileNotFoundException) {
            return ModelContractStatus(false, "yolo_model_unavailable", "metadata missing: $metadataAsset")
        } catch (error: Throwable) {
            return ModelContractStatus(false, "yolo_tensor_contract_mismatch", "metadata invalid: ${error.message}")
        }
        val modelBytes = try {
            context.assets.open(modelAsset).use { it.readBytes() }
        } catch (_: FileNotFoundException) {
            return ModelContractStatus(false, "yolo_model_unavailable", "model missing: $modelAsset")
        } catch (error: Throwable) {
            return ModelContractStatus(false, "yolo_model_unavailable", "model unreadable: ${error.message}")
        }
        val expectedSha = metadata.optString("sha256")
        val actualSha = sha256(modelBytes)
        if (expectedSha.isBlank() || !expectedSha.equals(actualSha, ignoreCase = true)) {
            return ModelContractStatus(false, "yolo_tensor_contract_mismatch", "model sha256 mismatch")
        }
        if (metadata.optBoolean("placeholder_model", false)) {
            return ModelContractStatus(false, "yolo_model_unavailable", "placeholder model asset is not an exported TFLite model")
        }
        if (metadata.optInt("input_size", 0) != YoloInputFrame.INPUT_SIZE) {
            return ModelContractStatus(false, "yolo_tensor_contract_mismatch", "input_size must be 256")
        }
        val contract = metadata.optJSONObject("output_tensor_contract")
            ?: return ModelContractStatus(false, "yolo_tensor_contract_mismatch", "output_tensor_contract missing")
        if (!contract.optString("detection_tensor").contains("4 + classes + mask_dim") ||
            !contract.optString("prototype_tensor").contains("mask_dim")) {
            return ModelContractStatus(false, "yolo_tensor_contract_mismatch", "unexpected output tensor contract")
        }
        return ModelContractStatus(true, "model_ready", "model and metadata contract validated")
    }

    fun detectLatestVisibleMaskOrFailure(
        target: String = "visible",
        inputFrame: YoloInputFrame? = null,
    ): RoiDetectionResult {
        val contract = validateTensorContract()
        if (!contract.ok) {
            return RoiDetectionResult(
                ok = false,
                target = target,
                appliedNow = false,
                reason = contract.reason,
                confidence = null,
                status = "failed",
            )
        }
        val frame = inputFrame ?: return RoiDetectionResult(
            ok = false,
            target = target,
            appliedNow = false,
            reason = "no_yolo_visible_candidate",
            status = "failed",
        )
        return detectFrame(frame, target)
    }

    fun detectFrame(inputFrame: YoloInputFrame, target: String = "visible"): RoiDetectionResult {
        val runtime = try {
            ensureInterpreter()
        } catch (error: Throwable) {
            return RoiDetectionResult(
                ok = false,
                target = target,
                appliedNow = false,
                reason = RUNTIME_UNAVAILABLE_REASON,
                status = "failed",
            )
        }

        return try {
            val inputShape = runtime.getInputTensor(0).shape()
            if (!inputShape.contentEquals(intArrayOf(1, YoloInputFrame.INPUT_SIZE, YoloInputFrame.INPUT_SIZE, 3))) {
                return tensorMismatch(target, "unexpected input tensor shape ${inputShape.joinToString(prefix = "[", postfix = "]")}")
            }
            val output0Shape = runtime.getOutputTensor(0).shape()
            val output1Shape = runtime.getOutputTensor(1).shape()
            if (output0Shape.size != 3 || output1Shape.size != 4) {
                return tensorMismatch(target, "unexpected output rank detection=${output0Shape.size} prototype=${output1Shape.size}")
            }

            val output0 = Array(output0Shape[0]) { Array(output0Shape[1]) { FloatArray(output0Shape[2]) } }
            val output1 = Array(output1Shape[0]) { Array(output1Shape[1]) { Array(output1Shape[2]) { FloatArray(output1Shape[3]) } } }
            val inputBuffer = ByteBuffer.allocateDirect(inputFrame.rgbFloat32.size * FLOAT_BYTES).order(ByteOrder.nativeOrder())
            inputFrame.rgbFloat32.forEach { inputBuffer.putFloat(it.coerceIn(0f, 1f)) }
            inputBuffer.rewind()
            runtime.runForMultipleInputsOutputs(arrayOf(inputBuffer), mapOf(0 to output0, 1 to output1))
            decodeYoloOutputs(output0, output0Shape, output1, output1Shape, inputFrame, target)
        } catch (error: IllegalArgumentException) {
            tensorMismatch(target, "LiteRT tensor execution mismatch: ${error.message ?: error.javaClass.simpleName}")
        } catch (error: Throwable) {
            RoiDetectionResult(
                ok = false,
                target = target,
                appliedNow = false,
                reason = RUNTIME_UNAVAILABLE_REASON,
                status = "failed",
            )
        }
    }

    fun parseFixtureDetections(fixture: JSONObject, frameWidth: Int, frameHeight: Int): RoiDetectionResult {
        val detections = fixture.optJSONArray("detections") ?: JSONArray()
        var sawAllowedWithoutMask = false
        var bestMask: RoiMask? = null
        var bestClass = ""
        var bestConfidence = 0.0
        for (i in 0 until detections.length()) {
            val det = detections.optJSONObject(i) ?: continue
            val className = det.optString("class_name")
            val confidence = det.optDouble("confidence", 0.0)
            if (className !in ACCEPTED_CLASSES) continue
            val maskArray = det.optJSONArray("mask")
            if (maskArray == null) {
                sawAllowedWithoutMask = true
                continue
            }
            val parsed = parseBooleanMask(maskArray, frameWidth, frameHeight)
            val roiMask = roiMaskFromBool(parsed, frameWidth, frameHeight, confidence, "yolo_mask:$className")
            val largest = MaskOps.keepLargestComponent(roiMask, minAreaPx = 4) ?: continue
            if (largest.areaPx > frameWidth * frameHeight * OVERSIZED_MASK_FRACTION) {
                return RoiDetectionResult(false, "visible", false, "oversized_yolo_visible_candidate", confidence, status = "failed")
            }
            if (confidence >= bestConfidence) {
                bestMask = largest
                bestClass = className
                bestConfidence = confidence
            }
        }
        val mask = bestMask
        return when {
            mask != null -> RoiDetectionResult(
                ok = true,
                target = "visible",
                appliedNow = true,
                reason = "yolo_visible_candidate:$bestClass",
                confidence = bestConfidence,
                visibleMask = mask,
                status = "applied",
            )
            sawAllowedWithoutMask -> RoiDetectionResult(false, "visible", false, "yolo_segmentation_mask_unavailable", status = "failed")
            else -> RoiDetectionResult(false, "visible", false, "no_yolo_visible_candidate", status = "failed")
        }
    }

    private fun ensureInterpreter(): Interpreter {
        interpreter?.let { return it }
        return synchronized(this) {
            interpreter?.let { return@synchronized it }
            val modelBytes = context.assets.open(modelAsset).use { it.readBytes() }
            val modelBuffer = ByteBuffer.allocateDirect(modelBytes.size).order(ByteOrder.nativeOrder())
            modelBuffer.put(modelBytes)
            modelBuffer.rewind()
            interpreterModelBuffer = modelBuffer
            Interpreter(modelBuffer).also { loaded ->
                loaded.allocateTensors()
                interpreter = loaded
            }
        }
    }

    private fun decodeYoloOutputs(
        detectionTensor: Array<Array<FloatArray>>,
        detectionShape: IntArray,
        prototypeTensor: Array<Array<Array<FloatArray>>>,
        prototypeShape: IntArray,
        inputFrame: YoloInputFrame,
        target: String,
    ): RoiDetectionResult {
        val protoHwc = prototypeShape[3] == MASK_DIM
        val protoChw = prototypeShape[1] == MASK_DIM
        if (!protoHwc && !protoChw) {
            return tensorMismatch(target, "prototype mask_dim=$MASK_DIM not found in ${prototypeShape.joinToString(prefix = "[", postfix = "]")}")
        }
        val protoHeight = if (protoHwc) prototypeShape[1] else prototypeShape[2]
        val protoWidth = if (protoHwc) prototypeShape[2] else prototypeShape[3]
        val channelsFirst = detectionShape[1] == 4 + COCO80_NAMES.size + MASK_DIM
        val channelsLast = detectionShape[2] == 4 + COCO80_NAMES.size + MASK_DIM
        if (!channelsFirst && !channelsLast) {
            return tensorMismatch(target, "detection tensor must contain 4+80+$MASK_DIM channels, got ${detectionShape.joinToString(prefix = "[", postfix = "]")}")
        }
        val predictions = if (channelsFirst) detectionShape[2] else detectionShape[1]
        fun det(channel: Int, index: Int): Float = if (channelsFirst) detectionTensor[0][channel][index] else detectionTensor[0][index][channel]
        fun proto(y: Int, x: Int, coeff: Int): Float = if (protoHwc) prototypeTensor[0][y][x][coeff] else prototypeTensor[0][coeff][y][x]

        var bestIndex = -1
        var bestClassIndex = -1
        var bestClassName = ""
        var bestScore = 0f
        var sawAllowedCandidate = false
        for (i in 0 until predictions) {
            for (className in ACCEPTED_CLASSES) {
                val classIndex = COCO80_NAMES.indexOf(className)
                if (classIndex < 0) continue
                val score = det(4 + classIndex, i)
                if (score > bestScore) {
                    bestScore = score
                    bestIndex = i
                    bestClassIndex = classIndex
                    bestClassName = className
                    if (score >= SCORE_THRESHOLD) sawAllowedCandidate = true
                }
            }
        }

        if (bestIndex < 0 || bestClassIndex < 0 || bestScore < SCORE_THRESHOLD) {
            return RoiDetectionResult(false, target, false, "no_yolo_visible_candidate", bestScore.takeIf { it > 0f }?.toDouble(), status = "failed")
        }
        if (!sawAllowedCandidate) {
            return RoiDetectionResult(false, target, false, "no_yolo_visible_candidate", bestScore.toDouble(), status = "failed")
        }

        val box = detectionBox(bestIndex) { channel -> det(channel, bestIndex) }
        if (box.width <= 1f || box.height <= 1f) {
            return RoiDetectionResult(false, target, false, "yolo_segmentation_mask_unavailable", bestScore.toDouble(), status = "failed")
        }
        val protoLeft = floor(box.left * protoWidth / YoloInputFrame.INPUT_SIZE).toInt().coerceIn(0, protoWidth - 1)
        val protoTop = floor(box.top * protoHeight / YoloInputFrame.INPUT_SIZE).toInt().coerceIn(0, protoHeight - 1)
        val protoRight = ceil(box.right * protoWidth / YoloInputFrame.INPUT_SIZE).toInt().coerceIn(protoLeft + 1, protoWidth)
        val protoBottom = ceil(box.bottom * protoHeight / YoloInputFrame.INPUT_SIZE).toInt().coerceIn(protoTop + 1, protoHeight)

        val protoMask = BooleanArray(protoWidth * protoHeight)
        var protoArea = 0
        for (y in protoTop until protoBottom) {
            for (x in protoLeft until protoRight) {
                var logit = 0f
                for (k in 0 until MASK_DIM) {
                    logit += det(4 + COCO80_NAMES.size + k, bestIndex) * proto(y, x, k)
                }
                val keep = sigmoid(logit) >= MASK_THRESHOLD
                protoMask[y * protoWidth + x] = keep
                if (keep) protoArea += 1
            }
        }
        if (protoArea <= 0) {
            return RoiDetectionResult(false, target, false, "yolo_segmentation_mask_unavailable", bestScore.toDouble(), status = "failed")
        }

        val frameMask = MaskOps.resizeNearest(
            mask = MaskOps.smooth(protoMask, protoWidth, protoHeight),
            fromWidth = protoWidth,
            fromHeight = protoHeight,
            toWidth = inputFrame.frameWidth,
            toHeight = inputFrame.frameHeight,
        )
        val rawMask = roiMaskFromBool(
            frameMask,
            inputFrame.frameWidth,
            inputFrame.frameHeight,
            bestScore.toDouble(),
            "yolo_mask:$bestClassName",
        )
        val largest = MaskOps.keepLargestComponent(rawMask, minAreaPx = max(4, inputFrame.frameWidth * inputFrame.frameHeight / 50_000))
            ?: return RoiDetectionResult(false, target, false, "yolo_segmentation_mask_unavailable", bestScore.toDouble(), status = "failed")
        if (largest.areaPx > inputFrame.frameWidth * inputFrame.frameHeight * OVERSIZED_MASK_FRACTION) {
            return RoiDetectionResult(false, target, false, "oversized_yolo_visible_candidate", bestScore.toDouble(), status = "failed")
        }
        return RoiDetectionResult(
            ok = true,
            target = target,
            appliedNow = true,
            reason = "yolo_visible_candidate:$bestClassName",
            confidence = bestScore.toDouble(),
            visibleMask = largest,
            status = "applied",
        )
    }

    private fun detectionBox(index: Int, det: (Int) -> Float): DetectionBox {
        val rawCx = det(0)
        val rawCy = det(1)
        val rawWidth = det(2)
        val rawHeight = det(3)
        val scale = if (max(max(rawCx, rawCy), max(rawWidth, rawHeight)) <= 2f) YoloInputFrame.INPUT_SIZE.toFloat() else 1f
        val cx = rawCx * scale
        val cy = rawCy * scale
        val width = rawWidth * scale
        val height = rawHeight * scale
        val left = (cx - width / 2f).coerceIn(0f, YoloInputFrame.INPUT_SIZE.toFloat())
        val top = (cy - height / 2f).coerceIn(0f, YoloInputFrame.INPUT_SIZE.toFloat())
        val right = (cx + width / 2f).coerceIn(0f, YoloInputFrame.INPUT_SIZE.toFloat())
        val bottom = (cy + height / 2f).coerceIn(0f, YoloInputFrame.INPUT_SIZE.toFloat())
        return DetectionBox(left = min(left, right), top = min(top, bottom), right = max(left, right), bottom = max(top, bottom))
    }

    private fun parseBooleanMask(array: JSONArray, width: Int, height: Int): BooleanArray {
        val out = BooleanArray(width * height)
        val rows = array.length().coerceAtLeast(1)
        for (y in 0 until height) {
            val row = array.optJSONArray((y * rows / height).coerceIn(0, rows - 1)) ?: JSONArray()
            val cols = row.length().coerceAtLeast(1)
            for (x in 0 until width) {
                out[y * width + x] = row.optDouble((x * cols / width).coerceIn(0, cols - 1), 0.0) > 0.5
            }
        }
        return out
    }

    private fun tensorMismatch(target: String, detail: String): RoiDetectionResult = RoiDetectionResult(
        ok = false,
        target = target,
        appliedNow = false,
        reason = "yolo_tensor_contract_mismatch",
        status = "failed",
    )

    private fun sha256(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        return digest.joinToString("") { "%02x".format(it) }
    }

    private data class DetectionBox(val left: Float, val top: Float, val right: Float, val bottom: Float) {
        val width: Float = right - left
        val height: Float = bottom - top
    }

    data class ModelContractStatus(val ok: Boolean, val reason: String, val detail: String)

    companion object {
        const val WINDOWS_PARITY_REASON_EXAMPLE = "yolo_visible_candidate:cup"
        const val RUNTIME_UNAVAILABLE_REASON = "yolo_runtime_unavailable"
        const val MODEL_ASSET = "models/yolo11n-seg-256-fp32.tflite"
        const val METADATA_ASSET = "models/yolo11n-seg-256-fp32.metadata.json"
        const val MASK_DIM = 32
        const val FLOAT_BYTES = 4
        const val SCORE_THRESHOLD = 0.25f
        const val MASK_THRESHOLD = 0.5f
        const val OVERSIZED_MASK_FRACTION = 0.85
        val ACCEPTED_CLASSES = setOf("cup", "bottle", "wine glass", "bowl", "vase", "beaker", "flask", "glass", "container")
        val COCO80_NAMES = listOf(
            "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
            "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
            "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
            "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
            "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
            "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed",
            "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave", "oven",
            "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
        )
    }
}

private fun sigmoid(value: Float): Float = (1.0 / (1.0 + exp(-value.toDouble()))).toFloat()

// yolo_runtime_unavailable
