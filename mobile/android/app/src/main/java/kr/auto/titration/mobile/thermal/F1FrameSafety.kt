package kr.auto.titration.mobile.thermal

/** Hardware-free safety checks for F1 callback payloads before preserving any preview/raw evidence. */
object F1FrameSafety {
    private val JPEG_SOI = byteArrayOf(0xff.toByte(), 0xd8.toByte())
    private val JPEG_EOI = byteArrayOf(0xff.toByte(), 0xd9.toByte())

    data class PreviewPlane(
        val width: Int,
        val height: Int,
        val bytes: ByteArray,
        val format: String,
    ) {
        override fun equals(other: Any?): Boolean {
            if (this === other) return true
            if (other !is PreviewPlane) return false
            return width == other.width &&
                height == other.height &&
                format == other.format &&
                bytes.contentEquals(other.bytes)
        }

        override fun hashCode(): Int {
            var result = width
            result = 31 * result + height
            result = 31 * result + format.hashCode()
            result = 31 * result + bytes.contentHashCode()
            return result
        }
    }

    data class CallbackEvidence(
        val previewPlane: PreviewPlane? = null,
        val rawValues: IntArray? = null,
        val rejectionReason: String = "unknown_payload_not_validated",
    ) {
        override fun equals(other: Any?): Boolean {
            if (this === other) return true
            if (other !is CallbackEvidence) return false
            return previewPlane == other.previewPlane &&
                rejectionReason == other.rejectionReason &&
                if (rawValues == null) other.rawValues == null else other.rawValues?.let { rawValues.contentEquals(it) } == true
        }

        override fun hashCode(): Int {
            var result = previewPlane?.hashCode() ?: 0
            result = 31 * result + (rawValues?.contentHashCode() ?: 0)
            result = 31 * result + rejectionReason.hashCode()
            return result
        }
    }

    data class CleanupCommand(val msgType: Int, val len: Int, val enable: Int? = null, val name: String)

    val officialCleanupCommands: List<CleanupCommand> = listOf(
        CleanupCommand(msgType = 5, len = 4, enable = 0, name = "USB_SetPreviewEnable(false)"),
        CleanupCommand(msgType = 14, len = 4, enable = null, name = "USB_SetDevDetach"),
    )

    fun validateCallbackPayload(bytes: ByteArray, width: Int, height: Int, yuvType: Int): CallbackEvidence {
        if (bytes.isEmpty()) {
            return CallbackEvidence(rejectionReason = "empty_callback_payload")
        }
        if (width <= 0 || height <= 0) {
            return CallbackEvidence(rejectionReason = "callback_dimensions_unavailable")
        }
        if (bytes.isJpeg()) {
            return CallbackEvidence(
                previewPlane = PreviewPlane(
                    width = width,
                    height = height,
                    bytes = bytes.copyOf(),
                    format = "jpeg",
                ),
                rejectionReason = "validated_jpeg_preview_yuvType=$yuvType",
            )
        }
        return CallbackEvidence(rejectionReason = "unknown_f1_payload_format_yuvType=$yuvType bytes=${bytes.size}")
    }

    fun validateRawMatrix(rawValues: IntArray?, width: Int, height: Int): Boolean =
        rawValues != null && width > 0 && height > 0 && rawValues.size == width * height

    private fun ByteArray.isJpeg(): Boolean =
        size >= 4 && this[0] == JPEG_SOI[0] && this[1] == JPEG_SOI[1] &&
            this[size - 2] == JPEG_EOI[0] && this[size - 1] == JPEG_EOI[1]
}
