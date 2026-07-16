package hik.common.yyrj.businesscommon

import android.content.Context
import android.content.SharedPreferences
import com.fasterxml.jackson.databind.ObjectMapper

/** Narrow Viewer 2.6.0 preference holder used by PreviewManagerII.l0/h1. */
class b private constructor() {
    private var context: Context? = null
    private val b: ObjectMapper = ObjectMapper()
    private lateinit var c: SharedPreferences

    fun v(context: Context) {
        this.context = context
        c = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    }

    private fun n(): MutableList<String> {
        val json = c.getString(PREVIEW_LOGO_VISIBLE, "")
        return if (json.isNullOrEmpty()) {
            ArrayList()
        } else {
            @Suppress("UNCHECKED_CAST")
            (b.readValue(json, ArrayList<String>().javaClass) as Collection<String>).toMutableList()
        }
    }

    fun w(serialNum: String): Boolean = n().none { it == serialNum }

    class a internal constructor() {
        fun a(): b = e.value
    }

    companion object {
        private const val PREFERENCES_NAME = "com.hikvison.commercialvision:settingConfig"
        private const val PREVIEW_LOGO_VISIBLE = "preview_logo_visible"

        @JvmField
        val d: a = a()

        private val e: Lazy<b> = lazy(LazyThreadSafetyMode.SYNCHRONIZED) { b() }

        @JvmStatic
        fun x(self: b, serialNum: String?, mask: Int, unused: Any?): Boolean {
            val effectiveSerial = if (mask and 1 != 0) u5.B.a.k().getSerialNumber() else requireNotNull(serialNum)
            return self.w(effectiveSerial)
        }
    }
}
