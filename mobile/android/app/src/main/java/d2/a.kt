package d2

import android.annotation.SuppressLint
import android.content.Context

/** Official app-context singleton dependency for l2.k and USB-type probes. */
object a {
    @SuppressLint("StaticFieldLeak")
    private lateinit var context: Context

    @JvmStatic
    fun a(): Context = context

    @JvmStatic
    fun b(appContext: Context) {
        context = appContext.applicationContext
    }
}
