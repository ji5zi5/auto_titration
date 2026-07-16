package A3

import android.graphics.Bitmap
import java.io.ByteArrayOutputStream

/** Official numeric helper singleton used by z3.c record-size calculation. */
class f private constructor() {
    fun a(bitmap: Bitmap): ByteArray = ByteArrayOutputStream().use { output ->
        bitmap.compress(Bitmap.CompressFormat.JPEG, 100, output)
        output.toByteArray()
    }

    fun f(value: Int): Int = if (value % 10 == 0) value else (value / 10 + 1) * 10
    companion object { @JvmField val a: f = f() }
}
