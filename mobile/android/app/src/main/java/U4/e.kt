package U4

import java.io.DataOutput
import java.io.DataOutputStream
import java.io.OutputStream

class e(output: OutputStream) : DataOutput {
    protected val a = DataOutputStream(output)
    private val b = ByteArray(8)

    @Synchronized
    override fun write(value: Int) { a.write(value) }
    override fun write(bytes: ByteArray) { a.write(bytes, 0, bytes.size) }
    @Synchronized
    override fun write(bytes: ByteArray, off: Int, len: Int) { a.write(bytes, off, len) }
    override fun writeBoolean(v: Boolean) { a.writeBoolean(v) }
    override fun writeByte(v: Int) { a.writeByte(v) }
    override fun writeBytes(s: String) { a.writeBytes(s) }
    override fun writeChar(v: Int) {
        b[0] = v.toByte(); b[1] = (v shr 8).toByte(); a.write(b, 0, 2)
    }
    override fun writeChars(s: String) { for (ch in s) writeChar(ch.code) }
    override fun writeDouble(v: Double) { writeLong(java.lang.Double.doubleToLongBits(v)) }
    override fun writeFloat(v: Float) { writeInt(java.lang.Float.floatToIntBits(v)) }
    override fun writeInt(v: Int) {
        b[0] = v.toByte(); b[1] = (v shr 8).toByte(); b[2] = (v shr 16).toByte(); b[3] = (v shr 24).toByte(); a.write(b, 0, 4)
    }
    override fun writeLong(v: Long) {
        b[0] = v.toByte(); b[1] = (v shr 8).toByte(); b[2] = (v shr 16).toByte(); b[3] = (v shr 24).toByte()
        b[4] = (v shr 32).toByte(); b[5] = (v shr 40).toByte(); b[6] = (v shr 48).toByte(); b[7] = (v shr 56).toByte(); a.write(b, 0, 8)
    }
    override fun writeShort(v: Int) {
        b[0] = v.toByte(); b[1] = (v shr 8).toByte(); a.write(b, 0, 2)
    }
    override fun writeUTF(s: String) { a.writeUTF(s) }
}
