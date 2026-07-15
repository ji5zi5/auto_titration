package X2

import android.view.SurfaceView
import V2.f

/** Official non-M4 renderer factory. */
class a : b {
    override fun a(surfaceView: SurfaceView): f = V2.a(surfaceView.holder)
    override fun b(surfaceView: SurfaceView): f = V2.c(surfaceView.holder)
    override fun c(surfaceView: SurfaceView): f = V2.e(surfaceView)
}
