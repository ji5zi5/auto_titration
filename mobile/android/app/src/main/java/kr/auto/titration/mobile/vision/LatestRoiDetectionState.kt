package kr.auto.titration.mobile.vision

/** Contract wrapper documenting latest-only frame submission; YOLO never runs in CameraX analyzer. */
class LatestRoiDetectionState(
    private val state: AndroidRoiSelectionState = AndroidRoiSelectionState(),
) {
    fun submitVisibleFrame(frameId: Long, target: String = "visible"): AutoRoiSettingsSnapshot =
        state.requestCandidate(target = target, visibleFrameId = frameId)

    fun complete(result: AutoRoiWorkerResult) {
        state.complete(result)
    }

    fun latestFreshResult(nowMs: Long = android.os.SystemClock.elapsedRealtime()): AutoRoiWorkerResult? =
        state.latestFreshResult(nowMs)

    fun pendingRequests(): Int = state.pendingRequests()

    fun pendingTarget(): String = state.pendingTarget()
}
