package A5

import android.content.Context
import java.io.File

/** Narrow scoped-storage path used by PreviewManagerII.p0 calibration prefetch. */
class y private constructor() {
    private lateinit var context: Context

    fun K(context: Context) {
        this.context = context
    }

    fun t(): File = requireNotNull(context.getExternalFilesDir(null))

    fun r(path: String): File = File(t(), path)

    fun u(): File = r("/F2Data")

    class a internal constructor() {
        fun b(): y = e.value
    }

    companion object {
        @JvmField
        val c: a = a()

        private val e: Lazy<y> = lazy(LazyThreadSafetyMode.SYNCHRONIZED) { y() }
    }
}
