package kr.auto.titration.mobile.session

data class RecordingTimeline(
    val startedElapsedNanos: Long,
    val pumpRateMlPerS: Double,
) {
    init {
        require(startedElapsedNanos >= 0L) { "start time must be non-negative" }
        require(pumpRateMlPerS >= 0.0) { "pump rate must be non-negative" }
    }

    fun elapsedS(nowElapsedNanos: Long): Double {
        val elapsedNs = (nowElapsedNanos - startedElapsedNanos).coerceAtLeast(0L)
        return elapsedNs / 1_000_000_000.0
    }

    fun injectedVolumeMl(nowElapsedNanos: Long): Double = elapsedS(nowElapsedNanos) * pumpRateMlPerS
}
