package d3

import com.hik.viewercommon.data.bean.PreviewInfoDataBean
import com.hik.viewercommon.data.bean.TempCallbackBean
import java.math.RoundingMode
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
import java.util.Locale

/** Official d3.b observable TempCallbackBean builder recovered from Viewer 2.6.0. */
class b private constructor() {
    fun a(
        tempMode: Int,
        max: Float,
        cen: Float,
        min: Float,
        maxChar: Char,
        cenChar: Char,
        minChar: Char,
        previewInfoData: PreviewInfoDataBean,
        rawWidth: Int,
    ): TempCallbackBean {
        val empty = TempCallbackBean(tempMode, max, cen, min, maxChar, cenChar, minChar)
        if (!Z2.a.a.q()) return empty
        val raw = previewInfoData.getByteArrRawData()
        val append = previewInfoData.getByteArrRawAppendData()
        if (append.isEmpty()) return empty
        val rawWithAppend = ByteArray(raw.size + append.size)
        raw.copyInto(rawWithAppend)
        append.copyInto(rawWithAppend, raw.size)
        val first = append.copyOfRange(0, rawWidth * 2)
        val second = append.copyOfRange(rawWidth * 2, rawWidth * 4)
        val maxGrey = if (262 >= first.size - 2) 0 else leShort(first.copyOfRange(262, 264), 0).toInt()
        val cenGrey = if (264 >= first.size - 2) 0 else leShort(first.copyOfRange(264, 266), 0).toInt()
        return TempCallbackBean(
            tempMode = tempMode,
            max = max,
            cen = cen,
            min = min,
            maxChar = maxChar,
            cenChar = cenChar,
            minChar = minChar,
            maxGrey = maxGrey,
            cenGrey = cenGrey,
            CAV = leShort(first.copyOfRange(2, 4), 0).toInt(),
            ShutterCav = leShort(first.copyOfRange(40, 42), 0).toInt(),
            Tec = leShort(first.copyOfRange(10, 12), 0).toInt(),
            Sens = leShort(first.copyOfRange(26, 28), 0).toInt(),
            Env = leInt(second.copyOfRange(16, 20), 0),
            rawWithAppendData = rawWithAppend,
        )
    }

    fun b(value: Float): String = DecimalFormat("0.0", DecimalFormatSymbols(Locale.US)).apply {
        roundingMode = RoundingMode.DOWN
        decimalFormatSymbols = DecimalFormatSymbols().apply { decimalSeparator = '.' }
    }.format(value)

    fun c(byteArrYuvAppendData: ByteArray): Int = if (byteArrYuvAppendData.isNotEmpty()) {
        leShort(byteArrYuvAppendData.copyOfRange(20, 22), 0).toInt()
    } else 0

    private fun leShort(bytes: ByteArray, offset: Int): Short = ByteBuffer.wrap(bytes, offset, 2).order(ByteOrder.LITTLE_ENDIAN).short
    private fun leInt(bytes: ByteArray, offset: Int): Int = ByteBuffer.wrap(bytes, offset, 4).order(ByteOrder.LITTLE_ENDIAN).int

    companion object { @JvmField val a: b = b() }
}
