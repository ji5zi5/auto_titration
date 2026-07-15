package y3

import android.opengl.EGLContext

/** Official recorder dependency used by z3.c recording branches. */
class b(context: EGLContext?) {
    private var path: String = ""
    private var width: Int = 720
    private var height: Int = 960
    private val eglContext: EGLContext? = context
    @Volatile var recording: Boolean = false
        private set
    private var scale: Float = 0f
    private var lastPresentationTimeNs: Long = 0L
    private var lastDrawers: List<w3.f> = emptyList()

    fun t(width: Int, height: Int) { this.width = width; this.height = height }
    fun u(scale: Float, path: String) { this.path = path; this.scale = scale; recording = true }
    fun r(presentationTimeNs: Long, drawers: List<w3.f>) {
        if (!recording) return
        lastPresentationTimeNs = presentationTimeNs
        lastDrawers = drawers.toList()
    }
    fun v() { recording = false }
}
