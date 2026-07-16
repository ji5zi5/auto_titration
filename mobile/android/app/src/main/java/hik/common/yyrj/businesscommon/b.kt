package hik.common.yyrj.businesscommon

import android.content.Context
import android.content.SharedPreferences
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

/** Narrow Viewer 2.6.0 preference holder used by PreviewManagerII.l0/h1. */
class b private constructor() {
    private lateinit var sharedPreferences: SharedPreferences

    fun v(context: Context) {
        sharedPreferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    }

    private fun n(): MutableList<String> {
        val json = sharedPreferences.getString(PREVIEW_LOGO_VISIBLE, "")
        if (json.isNullOrEmpty()) return ArrayList()
        val type = object : TypeToken<MutableList<String>>() {}.type
        return Gson().fromJson(json, type)
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
