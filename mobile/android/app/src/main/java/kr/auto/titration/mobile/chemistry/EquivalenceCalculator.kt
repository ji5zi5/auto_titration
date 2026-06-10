package kr.auto.titration.mobile.chemistry

import kr.auto.titration.mobile.data.ExperimentConfig
import kotlin.math.max

data class EquivalenceResult(
    val equivalenceVolumeMl: Double,
    val equivalenceTimeS: Double?,
    val expectedEquivalencePh: Double?,
    val warning: String,
)

object EquivalenceCalculator {
    fun equivalenceVolumeMl(
        sampleConcentrationM: Double,
        sampleVolumeMl: Double,
        sampleValence: Int = 1,
        titrantConcentrationM: Double,
        titrantValence: Int = 1,
    ): Double {
        require(sampleConcentrationM > 0.0) { "sample concentration must be positive" }
        require(sampleVolumeMl > 0.0) { "sample volume must be positive" }
        require(sampleValence > 0) { "sample valence must be positive" }
        require(titrantConcentrationM > 0.0) { "titrant concentration must be positive" }
        require(titrantValence > 0) { "titrant valence must be positive" }
        return sampleConcentrationM * sampleVolumeMl * sampleValence / (titrantConcentrationM * titrantValence)
    }

    fun fromConfig(config: ExperimentConfig, sampleValence: Int = 1, titrantValence: Int = 1): EquivalenceResult {
        val volume = equivalenceVolumeMl(
            sampleConcentrationM = config.sampleConcentrationM,
            sampleVolumeMl = config.sampleVolumeMl,
            sampleValence = sampleValence,
            titrantConcentrationM = config.titrantConcentrationM,
            titrantValence = titrantValence,
        )
        val time = if (config.pumpRunRateMlPerS > 0.0) volume / config.pumpRunRateMlPerS else null
        return EquivalenceResult(
            equivalenceVolumeMl = volume,
            equivalenceTimeS = time,
            expectedEquivalencePh = estimatePhLabel(config.titrationType),
            warning = "Equivalence volume is stoichiometric; endpoint color and pH 7 neutral point may differ.",
        )
    }

    private fun estimatePhLabel(titrationType: String): Double? {
        return when (titrationType) {
            "strong_acid_strong_base" -> 7.0
            "weak_acid_strong_base" -> 8.5
            "strong_acid_weak_base" -> 5.5
            "weak_acid_weak_base" -> null
            else -> null
        }
    }

    fun distanceToEquivalenceMl(theoreticalMl: Double, injectedMl: Double): Double = theoreticalMl - max(0.0, injectedMl)
}
