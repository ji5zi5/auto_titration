package d2

import android.annotation.SuppressLint
import android.content.Context

/** Official app-context singleton dependency for l2.k and USB-type probes. */
class a private constructor() {
    companion object {
        @JvmField
        val a: d2.a = d2.a()

        @SuppressLint("StaticFieldLeak")
        private lateinit var b: Context

        @JvmStatic
        fun a(): Context = b

        @JvmStatic
        fun b(context: Context) {
            b = context.applicationContext
        }
    }
}
