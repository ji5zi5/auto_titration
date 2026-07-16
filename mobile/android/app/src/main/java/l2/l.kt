package l2

import android.content.res.Resources

/** Official system-display helper consumed by W2.a. */
class l private constructor() {
    fun a(): Int = screenHeight
    fun b(): Int = screenWidth
    fun c(): Int {
        val resources = Resources.getSystem()
        val identifier = resources.getIdentifier("status_bar_height", "dimen", "android")
        return if (identifier > 0) resources.getDimensionPixelSize(identifier) else 0
    }

    companion object {
        @JvmField val a: l = l()
        private val screenWidth = Resources.getSystem().displayMetrics.widthPixels
        private val screenHeight = Resources.getSystem().displayMetrics.heightPixels
    }
}
