package l2

/** Official shared-preference helper API used by recovered Viewer globals. */
class k private constructor() {
    fun g(name: String): android.content.SharedPreferences = d2.a.a().getSharedPreferences(name, android.content.Context.MODE_PRIVATE)

    companion object {
        @JvmField val a: k = k()
        @JvmStatic fun a(key: String, defaultValue: Boolean): Boolean = a.g("app_update").getBoolean(key, defaultValue)
        @JvmStatic fun b(key: String, defaultValue: Boolean = false, mask: Int = 0, unused: Any? = null): Boolean = a(key, if (mask and 2 != 0) false else defaultValue)
        @JvmStatic fun c(key: String, defaultValue: Float): Float = a.g("app_update").getFloat(key, defaultValue)
        @JvmStatic fun d(key: String, defaultValue: Float = 0f, mask: Int = 0, unused: Any? = null): Float = c(key, if (mask and 2 != 0) 0f else defaultValue)
        @JvmStatic fun e(key: String, defaultValue: Int): Int = a.g("app_update").getInt(key, defaultValue)
        @JvmStatic fun f(key: String, defaultValue: Int = 0, mask: Int = 0, unused: Any? = null): Int = e(key, if (mask and 2 != 0) 0 else defaultValue)
        @JvmStatic fun h(key: String, defaultValue: String): String = a.g("app_update").getString(key, defaultValue)!!
        @JvmStatic fun i(key: String, defaultValue: String = "", mask: Int = 0, unused: Any? = null): String = h(key, if (mask and 2 != 0) "" else defaultValue)
        @JvmStatic fun j(key: String, value: Boolean) { a.g("app_update").edit().putBoolean(key, value).apply() }
        @JvmStatic fun k(key: String, value: Float) { a.g("app_update").edit().putFloat(key, value).apply() }
        @JvmStatic fun l(key: String, value: Int) { a.g("app_update").edit().putInt(key, value).apply() }
        @JvmStatic fun m(key: String, value: String) { a.g("app_update").edit().putString(key, value).apply() }
        @JvmStatic fun n(key: String) { a.g("app_update").edit().remove(key).apply() }
    }
}
