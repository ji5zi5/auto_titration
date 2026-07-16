package l2

import java.nio.ByteBuffer
import java.nio.ByteOrder

class c private constructor() {
    companion object {
        @JvmField val a: c = c()
        @JvmStatic fun b(self: c, bytes: ByteArray, order: ByteOrder?, mask: Int, unused: Any?): Float = self.a(bytes, if (mask and 2 != 0) ByteOrder.BIG_ENDIAN else order ?: ByteOrder.BIG_ENDIAN)
        @JvmStatic fun d(self: c, bytes: ByteArray, order: ByteOrder?, mask: Int, unused: Any?): Int = self.c(bytes, if (mask and 2 != 0) ByteOrder.BIG_ENDIAN else order ?: ByteOrder.BIG_ENDIAN)
        @JvmStatic fun f(self: c, bytes: ByteArray, order: ByteOrder?, mask: Int, unused: Any?): Short = self.e(bytes, if (mask and 2 != 0) ByteOrder.BIG_ENDIAN else order ?: ByteOrder.BIG_ENDIAN)
        @JvmStatic fun h(self: c, value: Short, order: ByteOrder?, mask: Int, unused: Any?): ByteArray = self.g(value, if (mask and 2 != 0) ByteOrder.BIG_ENDIAN else order ?: ByteOrder.BIG_ENDIAN)
    }
    fun a(bytes: ByteArray, byteOrder: ByteOrder): Float = Float.fromBits(c(bytes, byteOrder))
    fun c(bytes: ByteArray, byteOrder: ByteOrder): Int = if (bytes.size >= 4) ByteBuffer.wrap(bytes).order(byteOrder).int else -1
    fun e(bytes: ByteArray, byteOrder: ByteOrder): Short = if (bytes.size >= 2) ByteBuffer.wrap(bytes).order(byteOrder).short else (-1).toShort()
    fun g(value: Short, byteOrder: ByteOrder): ByteArray = ByteBuffer.allocate(2).order(byteOrder).putShort(value).array()
}
