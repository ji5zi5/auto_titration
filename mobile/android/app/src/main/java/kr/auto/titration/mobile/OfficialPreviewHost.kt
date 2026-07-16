package kr.auto.titration.mobile

import android.opengl.GLSurfaceView
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import com.hik.viewercommon.data.bean.SceneModeBean
import hik.common.yyrj.uicommon.widget.FloatTextureView
import kr.auto.titration.mobile.thermal.HikmicroJnaMini2Stream
import kr.auto.titration.mobile.thermal.PreviewManagerIIAppBinding

/**
 * Native host for the official HIKMICRO PreviewManagerII graph.
 *
 * The WebView remains the product control UI, but it is no longer the renderer
 * endpoint. This host supplies the real, attached SurfaceView hierarchy that the
 * recovered official manager expects and binds only after Android reports a
 * valid SurfaceHolder.
 */
internal class OfficialPreviewHost(
    activity: ComponentActivity,
    private val bindPreview: (OfficialPreviewBinding) -> Unit = HikmicroJnaMini2Stream::bindOfficialPreviewSurface,
    private val unbindPreview: () -> Unit = HikmicroJnaMini2Stream::unbindOfficialPreviewSurface,
) : SurfaceHolder.Callback {
    val rootView: FrameLayout = FrameLayout(activity)
    private val previewRoot: FrameLayout = FrameLayout(activity)
    private val viewerSurfaceView: SurfaceView = SurfaceView(activity)
    private val hrlSurfaceView: GLSurfaceView = GLSurfaceView(activity)
    private val visibleLightView: FloatTextureView = FloatTextureView(activity)
    private var selectedSurfaceView: SurfaceView = viewerSurfaceView
    private var selectedHolder: SurfaceHolder? = null
    private var holderCreated = false
    private var bound = false
    private var destroyed = false

    init {
        PreviewManagerIIAppBinding.installLifecycle(activity)
        rootView.layoutParams = matchParentLayoutParams()
        previewRoot.layoutParams = matchParentLayoutParams()
        previewRoot.visibility = View.VISIBLE

        viewerSurfaceView.layoutParams = matchParentLayoutParams()
        hrlSurfaceView.layoutParams = matchParentLayoutParams()
        visibleLightView.layoutParams = FrameLayout.LayoutParams(240, 180)
        visibleLightView.visibility = View.VISIBLE

        previewRoot.addView(viewerSurfaceView)
        previewRoot.addView(hrlSurfaceView)
        previewRoot.addView(visibleLightView)
        rootView.addView(previewRoot)
        selectOfficialSurface()
        selectedHolder = selectedSurfaceView.holder.also { it.addCallback(this) }
        selectedSurfaceView.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> maybeBindOfficialPreview() }
    }

    fun attachUserInterface(webView: View) {
        if (webView.parent != rootView) {
            rootView.addView(webView, matchParentLayoutParams())
        }
    }

    fun destroy() {
        if (destroyed) return
        destroyed = true
        selectedHolder?.removeCallback(this)
        selectedHolder = null
        holderCreated = false
        if (bound) {
            bound = false
            unbindPreview()
        }
    }

    override fun surfaceCreated(holder: SurfaceHolder) {
        holderCreated = true
        maybeBindOfficialPreview()
    }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        holderCreated = true
        maybeBindOfficialPreview()
    }

    override fun surfaceDestroyed(holder: SurfaceHolder) {
        holderCreated = false
        if (bound) {
            bound = false
            unbindPreview()
        }
    }

    private fun selectOfficialSurface() {
        if (Z2.a.a.t()) {
            z3.c.a.u(hrlSurfaceView)
            hrlSurfaceView.visibility = View.VISIBLE
            viewerSurfaceView.visibility = View.INVISIBLE
            selectedSurfaceView = hrlSurfaceView
        } else {
            viewerSurfaceView.visibility = View.VISIBLE
            hrlSurfaceView.visibility = View.INVISIBLE
            selectedSurfaceView = viewerSurfaceView
        }
    }

    private fun maybeBindOfficialPreview() {
        if (destroyed || bound || !holderCreated) return
        val holder = selectedHolder ?: return
        val surface = holder.surface ?: return
        val width = selectedSurfaceView.width
        val height = selectedSurfaceView.height
        if (!surface.isValid || width <= 1 || height <= 1 || selectedSurfaceView.visibility != View.VISIBLE) return
        val binding = OfficialPreviewBinding(
            root = previewRoot,
            selectedSurface = selectedSurfaceView,
            visibleLightView = visibleLightView,
            sceneMode = officialSceneModeHolderValue(),
            freezeCallback = { _ -> },
            overlayAvailabilityCallback = { _ -> },
        )
        bindPreview(binding)
        bound = true
    }

    private fun officialSceneModeHolderValue(): SceneModeBean {
        if (Z2.g.a.z().isEmpty()) {
            Z2.g.a.X()
        }
        val sceneModes = Z2.g.a.z()
        val index = Z2.g.a.C().coerceIn(0, sceneModes.lastIndex.coerceAtLeast(0))
        return sceneModes.getOrNull(index) ?: SceneModeBean()
    }

    private fun matchParentLayoutParams(): FrameLayout.LayoutParams = FrameLayout.LayoutParams(
        FrameLayout.LayoutParams.MATCH_PARENT,
        FrameLayout.LayoutParams.MATCH_PARENT,
    )
}

data class OfficialPreviewBinding(
    val root: View,
    val selectedSurface: SurfaceView,
    val visibleLightView: FloatTextureView,
    val sceneMode: SceneModeBean,
    val freezeCallback: (Boolean) -> Unit,
    val overlayAvailabilityCallback: (Boolean) -> Unit,
)
