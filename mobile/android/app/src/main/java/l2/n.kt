package l2

import android.content.res.Resources
import android.util.TypedValue

/** Exact dp conversion singleton used by PreviewManagerII.f1. */
class n private constructor() {
    fun a(dp: Int): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP,
        dp.toFloat(),
        Resources.getSystem().displayMetrics,
    ).toInt()

    companion object {
        @JvmField
        val a: n = n()
    }
}
