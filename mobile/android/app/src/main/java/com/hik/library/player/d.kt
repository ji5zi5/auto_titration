package com.hik.library.player

/** Exact Viewer PicDataBean shape (not a Kotlin data class). */
class d(
    private var a: Int,
    private var b: ByteArray?,
) {
    fun a(): Int = a
    fun b(): ByteArray? = b

    override fun equals(other: Any?): Boolean = other is d && a == other.a && b === other.b
    override fun hashCode(): Int = 31 * a + (b?.contentHashCode() ?: 0)
    override fun toString(): String = "PicDataBean(frameTime=$a, picData=${b?.contentToString()})"
}
