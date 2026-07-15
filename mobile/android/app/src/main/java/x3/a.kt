package x3

import android.view.SurfaceView
import java.lang.ref.WeakReference
import kotlin.jvm.functions.Function2

/** Official renderer dependency used by z3.c UI branches. */
class a {
    enum class b { a, b }

    private var surfaceView: WeakReference<SurfaceView>? = null
    private val drawers: MutableList<w3.f> = ArrayList()
    private var sizeCallback: Function2<Int, Int, kotlin.Unit>? = null
    private var mode: b = b.a
    private var lastPresentationTime: Long = 0L

    fun l(mode: b) { this.mode = mode }
    fun o(callback: Function2<Int, Int, kotlin.Unit>) { sizeCallback = callback }
    fun i(drawer: w3.f) { drawers.add(drawer) }
    fun n(surfaceView: SurfaceView) { this.surfaceView = WeakReference(surfaceView) }
    fun k(timeMillis: Long) { lastPresentationTime = timeMillis }
}
