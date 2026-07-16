package k3

import java.nio.ByteOrder

class b private constructor() {
    companion object {
        @JvmField val a: b = b()
        @JvmStatic fun b(self: b, beanObject: Any, byteOrder: ByteOrder?, mask: Int, unused: Any?): ByteArray? =
            self.a(beanObject, if (mask and 2 != 0) ByteOrder.LITTLE_ENDIAN else byteOrder ?: ByteOrder.LITTLE_ENDIAN)
        @JvmStatic fun d(self: b, beanObject: Any, buffer: ByteArray, byteOrder: ByteOrder?, mask: Int, unused: Any?) {
            self.c(beanObject, buffer, if (mask and 4 != 0) ByteOrder.LITTLE_ENDIAN else byteOrder ?: ByteOrder.LITTLE_ENDIAN)
        }
    }

    fun a(beanObject: Any, byteOrder: ByteOrder): ByteArray? {
        return try {
            U4.c.a(beanObject, byteOrder)
        } catch (e: Exception) {
            e.printStackTrace()
            StringBuilder().append("beanToBuffer: ").append(e.message).toString()
            null
        }
    }

    fun c(beanObject: Any, buffer: ByteArray, byteOrder: ByteOrder) {
        try {
            U4.c.b(beanObject, buffer, byteOrder)
        } catch (e: Exception) {
            e.printStackTrace()
            StringBuilder().append("bufferToBean: ").append(e.message).toString()
        }
    }
}
