package kr.auto.titration.mobile.ml

import org.json.JSONArray
import org.json.JSONObject

data class EquivalenceJsonModel(
    val modelType: String,
    val featureColumns: List<String>,
    val targetColumn: String,
    val bias: Double,
    val weights: List<Double>,
    val warnings: List<String>,
) {
    init {
        require(modelType == ModelContracts.CONSTANT_MEAN || modelType == ModelContracts.LINEAR_REGRESSION) {
            "unsupported model type: $modelType"
        }
        require(featureColumns.size == weights.size) { "feature/weight length mismatch" }
    }

    fun predict(row: Map<String, Double>): Double {
        var total = bias
        featureColumns.zip(weights).forEach { (feature, weight) ->
            total += (row[feature] ?: 0.0) * weight
        }
        return total
    }

    fun toJson(): JSONObject {
        return JSONObject()
            .put("model_type", modelType)
            .put("feature_columns", JSONArray(featureColumns))
            .put("target_column", targetColumn)
            .put("bias", bias)
            .put("weights", JSONArray(weights))
            .put("warnings", JSONArray(warnings))
    }

    companion object {
        fun fromJson(json: JSONObject): EquivalenceJsonModel {
            val features = json.getJSONArray("feature_columns").toStringList()
            val weights = json.getJSONArray("weights").toDoubleList()
            val warnings = json.optJSONArray("warnings")?.toStringList() ?: emptyList()
            return EquivalenceJsonModel(
                modelType = json.getString("model_type"),
                featureColumns = features,
                targetColumn = json.optString("target_column", "reference_equivalence_volume_ml"),
                bias = json.getDouble("bias"),
                weights = weights,
                warnings = warnings,
            )
        }

        fun constantMean(meanMl: Double, warning: String = "Sparse data: constant mean baseline only"): EquivalenceJsonModel {
            return EquivalenceJsonModel(
                modelType = ModelContracts.CONSTANT_MEAN,
                featureColumns = emptyList(),
                targetColumn = "reference_equivalence_volume_ml",
                bias = meanMl,
                weights = emptyList(),
                warnings = listOf(warning),
            )
        }
    }
}

private fun JSONArray.toStringList(): List<String> = List(length()) { index -> getString(index) }
private fun JSONArray.toDoubleList(): List<Double> = List(length()) { index -> getDouble(index) }
