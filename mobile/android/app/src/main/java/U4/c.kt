package U4

import java.nio.ByteOrder

/**
 * Official U4 struct codec entrypoint.  The implementation is split across the
 * same class graph as the extracted G007 APK: c -> m/n -> l/k -> o/g/j/b plus
 * d/e endian wrappers.
 *
 * Evidence anchors kept here for the repository contract test:
 * getAnnotation(f::class.java), getAnnotation(i::class.java),
 * getAnnotation(a::class.java), Order error for annotated fields,
 * ByteOrder.LITTLE_ENDIAN, k0(value), i0(child).
 */
abstract class c {
    companion object {
        @JvmStatic
        fun a(beanObject: Any, byteOrder: ByteOrder): ByteArray = m(byteOrder).p0(beanObject)

        @JvmStatic
        fun b(beanObject: Any, buffer: ByteArray, byteOrder: ByteOrder) { n(buffer, byteOrder).m0(beanObject) }
    }
}
