package kr.auto.titration.mobile.data

import java.util.UUID
import org.json.JSONException
import org.json.JSONObject

data class ExperimentConfig(
    val experimentId: String = UUID.randomUUID().toString(),
    val titrationType: String = "strong_acid_strong_base",
    val sampleName: String = "Hydrochloric acid",
    val sampleConcentrationM: Double = 0.1,
    val sampleVolumeMl: Double = 10.0,
    val sampleValence: Double = 1.0,
    val titrantName: String = "Sodium hydroxide",
    val titrantConcentrationM: Double = 0.1,
    val titrantValence: Double = 1.0,
    val theoreticalEquivalenceVolumeMl: Double = sampleConcentrationM * sampleVolumeMl * sampleValence / (titrantConcentrationM * titrantValence),
    val calculatedTheoreticalEquivalenceVolumeMl: Double = sampleConcentrationM * sampleVolumeMl * sampleValence / (titrantConcentrationM * titrantValence),
    val sampleConcentrationFromTheoreticalEquivalenceM: Double = titrantConcentrationM * theoreticalEquivalenceVolumeMl * titrantValence / (sampleVolumeMl * sampleValence),
    val equivalenceFormula: String = "nMV=n'M'V'",
    val pumpRunRateMlPerS: Double = 1.0,
) {
    init {
        require(titrationType.isNotBlank()) { "titration type must be nonblank" }
        require(sampleName.isNotBlank()) { "sample name must be nonblank" }
        require(titrantName.isNotBlank()) { "titrant name must be nonblank" }
        require(sampleConcentrationM > 0.0) { "sample concentration must be positive" }
        require(sampleVolumeMl > 0.0) { "sample volume must be positive" }
        require(sampleValence > 0.0) { "sample valence must be positive" }
        require(titrantConcentrationM > 0.0) { "titrant concentration must be positive" }
        require(titrantValence > 0.0) { "titrant valence must be positive" }
        require(theoreticalEquivalenceVolumeMl > 0.0) { "equivalence volume must be positive" }
        require(calculatedTheoreticalEquivalenceVolumeMl > 0.0) { "calculated equivalence volume must be positive" }
        require(sampleConcentrationFromTheoreticalEquivalenceM > 0.0) { "calculated sample concentration must be positive" }
        require(equivalenceFormula.isNotBlank()) { "equivalence formula must be nonblank" }
        require(pumpRunRateMlPerS > 0.0) { "pump rate must be positive" }
    }

    fun sampleConcentrationFromTitrantVolumeMl(titrantVolumeMl: Double): Double {
        require(titrantVolumeMl >= 0.0) { "titrant volume must not be negative" }
        return titrantConcentrationM * titrantVolumeMl * titrantValence / (sampleVolumeMl * sampleValence)
    }

    fun sampleConcentrationErrorPercent(calculatedM: Double): Double =
        (calculatedM - sampleConcentrationM) / sampleConcentrationM * 100.0

    companion object {
        fun fromJson(payloadJson: String): ExperimentConfig {
            val payload = try {
                JSONObject(payloadJson)
            } catch (error: JSONException) {
                throw IllegalArgumentException("invalid recording config JSON: ${error.message ?: error.javaClass.simpleName}")
            }
            return fromJson(payload)
        }

        fun fromJson(payload: JSONObject): ExperimentConfig {
            val sampleConcentration = requirePositiveDouble(payload, "sample_concentration_M", "시료 농도")
            val sampleVolume = requirePositiveDouble(payload, "sample_volume_ml", "시료 부피")
            val sampleValence = optionalPositiveDouble(payload, "sample_valence", "시료 반응가수") ?: 1.0
            val titrantConcentration = requirePositiveDouble(payload, "titrant_concentration_M", "표준용액 농도")
            val titrantValence = optionalPositiveDouble(payload, "titrant_valence", "표준용액 반응가수") ?: 1.0
            val calculatedTheory = sampleConcentration * sampleVolume * sampleValence / (titrantConcentration * titrantValence)
            val theory = optionalPositiveDouble(payload, "theoretical_equivalence_volume_ml", "이론 당량점") ?: calculatedTheory
            return ExperimentConfig(
                experimentId = payload.optString("experiment_id").trim().ifBlank { UUID.randomUUID().toString() },
                titrationType = requireNonBlank(payload, "titration_type", "적정 종류"),
                sampleName = requireNonBlank(payload, "sample_name", "시료 물질"),
                sampleConcentrationM = sampleConcentration,
                sampleVolumeMl = sampleVolume,
                sampleValence = sampleValence,
                titrantName = requireNonBlank(payload, "titrant_name", "표준용액 이름"),
                titrantConcentrationM = titrantConcentration,
                titrantValence = titrantValence,
                theoreticalEquivalenceVolumeMl = theory,
                calculatedTheoreticalEquivalenceVolumeMl = optionalPositiveDouble(
                    payload,
                    "calculated_theoretical_equivalence_volume_ml",
                    "계산 이론 당량점",
                ) ?: calculatedTheory,
                sampleConcentrationFromTheoreticalEquivalenceM = optionalPositiveDouble(
                    payload,
                    "sample_concentration_from_theoretical_equivalence_M",
                    "이론 당량점 기준 시료 농도",
                ) ?: (titrantConcentration * theory * titrantValence / (sampleVolume * sampleValence)),
                equivalenceFormula = payload.optString("equivalence_formula").trim().ifBlank { "nMV=n'M'V'" },
                pumpRunRateMlPerS = requirePositiveDouble(payload, "pump_rate_ml_per_s", "펌프 유량"),
            )
        }

        private fun requireNonBlank(payload: JSONObject, key: String, label: String): String {
            if (!payload.has(key) || payload.isNull(key)) {
                throw IllegalArgumentException("$label 누락: $key")
            }
            val value = payload.optString(key).trim()
            if (value.isBlank()) {
                throw IllegalArgumentException("${label}은 비어 있을 수 없습니다")
            }
            return value
        }

        private fun optionalPositiveDouble(payload: JSONObject, key: String, label: String): Double? {
            if (!payload.has(key) || payload.isNull(key)) return null
            val value = payload.optDouble(key, Double.NaN)
            if (!value.isFinite() || value <= 0.0) {
                throw IllegalArgumentException("${label}은 0보다 큰 숫자여야 합니다")
            }
            return value
        }

        private fun requirePositiveDouble(payload: JSONObject, key: String, label: String): Double {
            if (!payload.has(key) || payload.isNull(key)) {
                throw IllegalArgumentException("$label 누락: $key")
            }
            val value = payload.optDouble(key, Double.NaN)
            if (!value.isFinite() || value <= 0.0) {
                throw IllegalArgumentException("${label}은 0보다 큰 숫자여야 합니다")
            }
            return value
        }
    }
}
