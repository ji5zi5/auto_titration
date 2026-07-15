package kr.auto.titration.mobile.thermal

/**
 * Official HIKMICRO Viewer F2 profile selector, kept pure Kotlin so it can be
 * verified by JVM unit tests without USB hardware or Android framework objects.
 *
 * Evidence:
 * - _workspace/hikmicro-analysis-20260714/final-technical-analysis.md sections 3 and 6
 * - .omx/.../evidence/dad/d3_l.java: module-id/date selector
 * - .omx/.../evidence/dad/f3_b.java..f3_j.java: profile fields
 * - .omx/.../evidence/dad/Z2_a.java: official Size constants
 */
data class HikmicroF2Size(val width: Int, val height: Int) {
    init {
        require(width > 0) { "width must be positive" }
        require(height > 0) { "height must be positive" }
    }

    override fun toString(): String = "${width}x$height"
}

data class HikmicroF2Profile(
    val officialClassName: String,
    val moduleIds: Set<String>,
    val previewSize: HikmicroF2Size,
    val fps: Int,
    val thermalCoding: Int,
    val streamingNew: Boolean,
    val allowedPacketSizes: Set<Int>,
)

data class HikmicroF2ProfileResolution(
    val profile: HikmicroF2Profile?,
    val moduleId: String?,
    val firmwareDate: Int?,
    val reason: String,
) {
    val isResolved: Boolean
        get() = profile != null
}

object HikmicroF2ProfileResolver {
    private val moduleIds356 = setOf("0953560101", "0953560104", "0953560105")
    private val moduleIds351 = setOf("0953510000", "0953510100")
    private val moduleIds306 = setOf("0953060001", "0953060002")
    private val moduleIds308 = setOf("0953080000")

    /** Exact d3.l static module-ID lists, including non-profile-selector families. */
    val officialModuleIdGroups: Map<String, Set<String>> = linkedMapOf(
        "b" to moduleIds356,
        "c" to moduleIds351,
        "d" to moduleIds306,
        "e" to moduleIds308,
        "f" to setOf("0953560101", "0953560105", "0953060002"),
        "g" to setOf("0953510000", "0953510100"),
        "h" to setOf("0953560102", "0953560103"),
        "i" to setOf("0951710000"),
    )

    val F3_I = HikmicroF2Profile(
        officialClassName = "f3.i",
        moduleIds = moduleIds356,
        previewSize = HikmicroF2Size(192, 520),
        fps = 25,
        thermalCoding = 8,
        streamingNew = false,
        allowedPacketSizes = setOf(102944),
    )

    val F3_F = HikmicroF2Profile(
        officialClassName = "f3.f",
        moduleIds = moduleIds356,
        previewSize = HikmicroF2Size(192, 520),
        fps = 25,
        thermalCoding = 11,
        streamingNew = true,
        allowedPacketSizes = setOf(206392),
    )

    val F3_G = HikmicroF2Profile(
        officialClassName = "f3.g",
        moduleIds = moduleIds356,
        previewSize = HikmicroF2Size(256, 344),
        fps = 25,
        thermalCoding = 12,
        streamingNew = true,
        allowedPacketSizes = setOf(101320, 183496, 98304),
    )

    val F3_H = HikmicroF2Profile(
        officialClassName = "f3.h",
        moduleIds = moduleIds356,
        previewSize = HikmicroF2Size(256, 344),
        fps = 25,
        thermalCoding = 12,
        streamingNew = true,
        allowedPacketSizes = F3_G.allowedPacketSizes,
    )

    val F3_C = HikmicroF2Profile(
        officialClassName = "f3.c",
        moduleIds = moduleIds351,
        previewSize = HikmicroF2Size(288, 776),
        fps = 50,
        thermalCoding = 11,
        streamingNew = true,
        allowedPacketSizes = setOf(453688),
    )

    val F3_D = HikmicroF2Profile(
        officialClassName = "f3.d",
        moduleIds = moduleIds351,
        previewSize = HikmicroF2Size(384, 512),
        fps = 50,
        thermalCoding = 12,
        streamingNew = true,
        allowedPacketSizes = setOf(193480, 400584, 221184),
    )

    val F3_E = HikmicroF2Profile(
        officialClassName = "f3.e",
        moduleIds = moduleIds351,
        previewSize = HikmicroF2Size(384, 512),
        fps = 50,
        thermalCoding = 12,
        streamingNew = true,
        allowedPacketSizes = F3_D.allowedPacketSizes,
    )

    val F3_J = HikmicroF2Profile(
        officialClassName = "f3.j",
        moduleIds = moduleIds306,
        previewSize = HikmicroF2Size(256, 344),
        fps = 25,
        thermalCoding = 12,
        streamingNew = true,
        allowedPacketSizes = setOf(203720, 183496),
    )

    val F3_B = HikmicroF2Profile(
        officialClassName = "f3.b",
        moduleIds = moduleIds308,
        previewSize = HikmicroF2Size(96, 176),
        fps = 25,
        thermalCoding = 12,
        streamingNew = true,
        allowedPacketSizes = setOf(61384, 41160),
    )

    fun resolve(moduleId: String?, firmwareVersion: String?): HikmicroF2ProfileResolution {
        val normalizedModuleId = moduleId?.trim().orEmpty()
        if (normalizedModuleId.isEmpty()) {
            return unresolved(null, null, "module_id_missing")
        }

        val firmwareDate = extractFirmwareDate(firmwareVersion)
        if (firmwareDate == null) {
            return unresolved(normalizedModuleId, null, "firmware_date_unresolved")
        }

        val profile = when {
            normalizedModuleId in moduleIds356 -> when {
                firmwareDate <= 20221121 -> F3_I
                firmwareDate <= 20231115 -> F3_F
                firmwareDate <= 20231229 -> F3_G
                else -> F3_H
            }
            normalizedModuleId in moduleIds351 -> when {
                firmwareDate <= 20231116 -> F3_C
                firmwareDate <= 20231229 -> F3_D
                else -> F3_E
            }
            normalizedModuleId in moduleIds306 -> F3_J
            normalizedModuleId in moduleIds308 -> F3_B
            else -> null
        }

        return if (profile == null) {
            unresolved(normalizedModuleId, firmwareDate, "unsupported_module_id")
        } else {
            HikmicroF2ProfileResolution(
                profile = profile,
                moduleId = normalizedModuleId,
                firmwareDate = firmwareDate,
                reason = "official_f2_profile ${profile.officialClassName} module_id=$normalizedModuleId firmware_date=$firmwareDate",
            )
        }
    }

    /**
     * Mirrors d3.l: split strFirmwareVersion by '_' and parse the last token when
     * the official minimum shape (at least three tokens) is present.
     */
    fun extractFirmwareDate(firmwareVersion: String?): Int? {
        val parts = firmwareVersion?.trim()?.split('_') ?: return null
        if (parts.size < 3) return null
        val dateToken = parts.last()
        if (dateToken.length != 8 || !dateToken.all(Char::isDigit)) return null
        return dateToken.toIntOrNull()
    }

    private fun unresolved(
        moduleId: String?,
        firmwareDate: Int?,
        reason: String,
    ): HikmicroF2ProfileResolution = HikmicroF2ProfileResolution(
        profile = null,
        moduleId = moduleId,
        firmwareDate = firmwareDate,
        reason = reason,
    )
}
