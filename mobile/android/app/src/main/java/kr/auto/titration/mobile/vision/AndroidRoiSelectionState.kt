package kr.auto.titration.mobile.vision

import android.os.SystemClock

/** Latest-only Android state equivalent to Windows RoiSelectionState pending candidate logic. */
class AndroidRoiSelectionState(
    private val maxResultAgeMs: Long = 2_000L,
) {
    private var generation = 0L
    private var pending: AutoRoiSettingsSnapshot? = null
    private var lastResult: AutoRoiWorkerResult? = null
    var droppedPending: Int = 0
        private set

    fun requestCandidate(target: String, visibleFrameId: Long, thermalFrameId: Long = 0L): AutoRoiSettingsSnapshot {
        val now = SystemClock.elapsedRealtime()
        if (pending != null) droppedPending += 1
        generation += 1
        val snapshot = AutoRoiSettingsSnapshot(
            generation = generation,
            target = normalizeTarget(target),
            visibleFrameId = visibleFrameId,
            thermalFrameId = thermalFrameId,
            requestedAtMs = now,
        )
        pending = snapshot
        return snapshot
    }

    fun complete(result: AutoRoiWorkerResult) {
        if (pending?.generation == result.settings.generation) {
            pending = null
        }
        lastResult = result
    }

    fun pendingRequests(): Int = if (pending == null) 0 else 1
    fun pendingTarget(): String = pending?.target.orEmpty()
    fun settingsGeneration(): Long = generation

    fun latestFreshResult(nowMs: Long = SystemClock.elapsedRealtime()): AutoRoiWorkerResult? {
        val result = lastResult ?: return null
        return if (nowMs - result.completedAtMs <= maxResultAgeMs && result.settings.generation <= generation) result else null
    }

    fun rejectReasonIfLockedOrRecording(recording: Boolean): String? = if (recording) "roi_locked_or_recording" else null

    private fun normalizeTarget(target: String): String = when (target.lowercase()) {
        "visible", "camera" -> "visible"
        "thermal", "mini2" -> "thermal"
        else -> "both"
    }
}
