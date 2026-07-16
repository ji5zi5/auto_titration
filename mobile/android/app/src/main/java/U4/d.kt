package U4

import java.io.DataInput
import java.io.DataInputStream
import java.io.InputStream

class d(input: InputStream) : DataInput {
    private val a = DataInputStream(input)
    private val c = ByteArray(8)

    override fun readBoolean(): Boolean = a.readBoolean()
    override fun readByte(): Byte = a.readByte()
    override fun readChar(): Char {
        a.readFully(c, 0, 2)
        return (((c[0].toInt() and 0xff) or ((c[1].toInt() and 0xff) shl 8))).toChar()
    }
    override fun readDouble(): Double = java.lang.Double.longBitsToDouble(readLong())
    override fun readFloat(): Float = java.lang.Float.intBitsToFloat(readInt())
    override fun readFully(b: ByteArray) { a.readFully(b, 0, b.size) }
    override fun readFully(b: ByteArray, off: Int, len: Int) { a.readFully(b, off, len) }
    override fun readInt(): Int {
        a.readFully(c, 0, 4)
        return (c[0].toInt() and 0xff) or
            ((c[1].toInt() and 0xff) shl 8) or
            ((c[2].toInt() and 0xff) shl 16) or
            (c[3].toInt() shl 24)
    }
    @Suppress("DEPRECATION")
    override fun readLine(): String? = a.readLine()
    override fun readLong(): Long {
        a.readFully(c, 0, 8)
        return (c[0].toLong() and 0xffL) or
            ((c[1].toLong() and 0xffL) shl 8) or
            ((c[2].toLong() and 0xffL) shl 16) or
            ((c[3].toLong() and 0xffL) shl 24) or
            ((c[4].toLong() and 0xffL) shl 32) or
            ((c[5].toLong() and 0xffL) shl 40) or
            ((c[6].toLong() and 0xffL) shl 48) or
            (c[7].toLong() shl 56)
    }
    override fun readShort(): Short {
        a.readFully(c, 0, 2)
        return (((c[0].toInt() and 0xff) or ((c[1].toInt() and 0xff) shl 8))).toShort()
    }
    override fun readUTF(): String = a.readUTF()
    override fun readUnsignedByte(): Int = a.readUnsignedByte()
    override fun readUnsignedShort(): Int {
        a.readFully(c, 0, 2)
        return (c[0].toInt() and 0xff) or ((c[1].toInt() and 0xff) shl 8)
    }
    override fun skipBytes(n: Int): Int = a.skipBytes(n)
}
