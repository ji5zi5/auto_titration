package kr.auto.titration.mobile

import android.opengl.GLSurfaceView
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import com.hik.viewercommon.data.bean.SceneModeBean
import com.hik.f2module.F2SessionCloseOutcome
import com.hik.f2module.F2StageResult
import hik.common.yyrj.uicommon.widget.FloatTextureView
import kr.auto.titration.mobile.thermal.HikmicroJnaMini2Stream
import kr.auto.titration.mobile.thermal.PreviewManagerIIAppBinding
import java.lang.ref.WeakReference

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
    private val unbindPreview: (SurfaceView) -> Unit = HikmicroJnaMini2Stream::unbindOfficialPreviewSurface,
    private val shutdownPreviewSession: () -> F2StageResult = HikmicroJnaMini2Stream::shutdownOfficialPreviewSession,
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
        HikmicroJnaMini2Stream.claimPendingTerminalShutdownRetryForReplacementHost(
            onLoginCloseCompleted = retryRebindCallback(),
        )
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

    fun resetOfficialF2SessionForUsbLifecycle(@Suppress("UNUSED_PARAMETER") reason: String): F2StageResult {
        if (destroyed) {
            return F2StageResult(false, "official_preview_host_destroyed")
        }
        val wasBound = bound
        val result = HikmicroJnaMini2Stream.shutdownOfficialPreviewSessionWithRetryRegistration(
            shutdown = shutdownPreviewSession,
            beforeRetryScheduled = { failed ->
                when (officialPreviewHostCloseAction(failed, terminalDestroy = false)) {
                    OfficialPreviewHostCloseAction.PRESERVE_HOST_AND_BINDING -> bound = wasBound
                    OfficialPreviewHostCloseAction.KEEP_HOST_UNBOUND_AND_RETRY -> bound = false
                    else -> error("non-retry close action reached retry registration")
                }
            },
            onRetryClosed = retryRebindCallback(),
        )
        when (officialPreviewHostCloseAction(result, terminalDestroy = false)) {
            OfficialPreviewHostCloseAction.PRESERVE_HOST_AND_BINDING -> Unit
            OfficialPreviewHostCloseAction.KEEP_HOST_UNBOUND_AND_RETRY -> Unit
            OfficialPreviewHostCloseAction.REBIND_CLOSED_HOST -> {
                bound = false
                maybeBindOfficialPreview()
            }
            OfficialPreviewHostCloseAction.TRANSFER_OWNER_AND_COMMIT_DESTROYED_HOST -> error(
                "terminal owner transfer is invalid during USB lifecycle reset",
            )
            OfficialPreviewHostCloseAction.COMMIT_DESTROYED_HOST -> error(
                "terminal destroy action is invalid during USB lifecycle reset",
            )
        }
        return result
    }

    fun destroy(): F2StageResult {
        if (destroyed) {
            return F2StageResult(
                ok = true,
                summary = "official_preview_host_already_destroyed",
                closeOutcome = F2SessionCloseOutcome.CLOSED,
            )
        }
        val result = HikmicroJnaMini2Stream.shutdownOfficialPreviewSessionWithRetryRegistration(
            shutdown = shutdownPreviewSession,
            beforeRetryScheduled = { failed ->
                when (officialPreviewHostCloseAction(failed, terminalDestroy = true)) {
                    OfficialPreviewHostCloseAction.TRANSFER_OWNER_AND_COMMIT_DESTROYED_HOST -> {
                        PreviewManagerIIAppBinding.transferTerminalCloseRetryManagerToExternalOwner()
                        unbindSelectedSurface()
                        commitHostDestruction()
                    }
                    OfficialPreviewHostCloseAction.KEEP_HOST_UNBOUND_AND_RETRY ->
                        commitHostDestruction()
                    else -> error("non-retry terminal action reached retry registration")
                }
            },
        )
        when (officialPreviewHostCloseAction(result, terminalDestroy = true)) {
            OfficialPreviewHostCloseAction.TRANSFER_OWNER_AND_COMMIT_DESTROYED_HOST -> return result
            OfficialPreviewHostCloseAction.PRESERVE_HOST_AND_BINDING -> {
                error("reset-only preserve action is invalid during terminal host destroy")
            }
            OfficialPreviewHostCloseAction.KEEP_HOST_UNBOUND_AND_RETRY -> return result
            OfficialPreviewHostCloseAction.COMMIT_DESTROYED_HOST -> {
                commitHostDestruction()
                return result
            }
            OfficialPreviewHostCloseAction.REBIND_CLOSED_HOST -> error(
                "reset-only rebind action is invalid during terminal host destroy",
            )
        }
    }

    private fun commitHostDestruction() {
        destroyed = true
        selectedHolder?.removeCallback(this)
        selectedHolder = null
        holderCreated = false
        bound = false
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
            unbindSelectedSurface()
        }
    }

    private fun unbindSelectedSurface() {
        bound = false
        unbindPreview(selectedSurfaceView)
    }

    private fun retryRebindCallback(): () -> Unit {
        val hostRef = WeakReference(this)
        return {
            val host = hostRef.get()
            if (host != null) {
                host.rootView.post {
                    if (!host.destroyed) {
                        host.bound = false
                        host.maybeBindOfficialPreview()
                    }
                }
            }
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

internal enum class OfficialPreviewHostCloseAction {
    PRESERVE_HOST_AND_BINDING,
    TRANSFER_OWNER_AND_COMMIT_DESTROYED_HOST,
    KEEP_HOST_UNBOUND_AND_RETRY,
    REBIND_CLOSED_HOST,
    COMMIT_DESTROYED_HOST,
}

internal fun officialPreviewHostCloseAction(
    result: F2StageResult,
    terminalDestroy: Boolean,
): OfficialPreviewHostCloseAction = when (result.closeOutcome) {
    F2SessionCloseOutcome.STREAM_PRESERVED ->
        if (terminalDestroy) {
            OfficialPreviewHostCloseAction.TRANSFER_OWNER_AND_COMMIT_DESTROYED_HOST
        } else {
            OfficialPreviewHostCloseAction.PRESERVE_HOST_AND_BINDING
        }
    F2SessionCloseOutcome.STREAM_STOPPED_LOGIN_RETAINED ->
        OfficialPreviewHostCloseAction.KEEP_HOST_UNBOUND_AND_RETRY
    F2SessionCloseOutcome.CLOSED ->
        if (terminalDestroy) {
            OfficialPreviewHostCloseAction.COMMIT_DESTROYED_HOST
        } else {
            OfficialPreviewHostCloseAction.REBIND_CLOSED_HOST
        }
    F2SessionCloseOutcome.NOT_APPLICABLE ->
        if (result.ok && terminalDestroy) {
            OfficialPreviewHostCloseAction.COMMIT_DESTROYED_HOST
        } else if (result.ok) {
            OfficialPreviewHostCloseAction.REBIND_CLOSED_HOST
        } else {
            OfficialPreviewHostCloseAction.PRESERVE_HOST_AND_BINDING
        }
}

data class OfficialPreviewBinding(
    val root: View,
    val selectedSurface: SurfaceView,
    val visibleLightView: FloatTextureView,
    val sceneMode: SceneModeBean,
    val freezeCallback: (Boolean) -> Unit,
    val overlayAvailabilityCallback: (Boolean) -> Unit,
)
