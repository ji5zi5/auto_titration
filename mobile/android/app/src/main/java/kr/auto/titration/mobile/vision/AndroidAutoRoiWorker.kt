package kr.auto.titration.mobile.vision

import android.os.SystemClock

/** Latest-only worker shell; workers return evidence and never run inside CameraX analyzer. */
class AndroidAutoRoiWorker(
    private val detector: YoloSegmentationDetector,
    private val state: AndroidRoiSelectionState,
) {
    fun requestVisibleCandidate(target: String, visibleFrameId: Long, inputFrame: YoloInputFrame?): AutoRoiWorkerResult {
        val settings = state.requestCandidate(target = target, visibleFrameId = visibleFrameId)
        val detection = detector.detectLatestVisibleMaskOrFailure(settings.target, inputFrame)
        val result = AutoRoiWorkerResult(
            settings = settings,
            detection = detection.copy(
                pendingRequests = state.pendingRequests(),
                pendingTarget = state.pendingTarget(),
            ),
            completedAtMs = SystemClock.elapsedRealtime(),
            droppedPending = state.droppedPending,
        )
        state.complete(result)
        return result
    }
}
