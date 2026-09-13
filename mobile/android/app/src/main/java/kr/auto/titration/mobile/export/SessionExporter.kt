package kr.auto.titration.mobile.export

import java.io.File
import java.io.StringWriter
import kr.auto.titration.mobile.data.CsvFeatureRow
import kr.auto.titration.mobile.data.ExperimentConfig
import kr.auto.titration.mobile.data.LocalCsvWriter
import org.json.JSONObject

object SessionExporter {
    fun buildCsv(config: ExperimentConfig, rows: List<CsvFeatureRow>, predictionFields: Map<String, String> = emptyMap()): String {
        require(predictionFields.keys.all { it.startsWith("predicted_equivalence_") || it == "sample_concentration_from_predicted_equivalence_M" }) {
            "prediction annotations cannot overwrite raw sensor or volume fields"
        }
        val buffer = StringWriter()
        val writer = LocalCsvWriter(buffer)
        writer.writeHeaderIfNeeded()
        rows.forEach { row -> writer.appendRow(row.toCsvMap(config) + predictionFields) }
        writer.flush()
        return buffer.toString()
    }

    fun writeCsv(file: File, config: ExperimentConfig, rows: List<CsvFeatureRow>) {
        file.parentFile?.mkdirs()
        file.writer(Charsets.UTF_8).use { output ->
            val writer = LocalCsvWriter(output)
            rows.forEach { row -> writer.appendRow(row.toCsvMap(config)) }
        }
    }

    fun metadataJson(config: ExperimentConfig, rowCount: Int): JSONObject {
        return JSONObject()
            .put("experiment_id", config.experimentId)
            .put("schema_version", kr.auto.titration.mobile.data.CsvSchema.SCHEMA_VERSION)
            .put("row_count", rowCount)
            .put("equivalence_formula", config.equivalenceFormula)
            .put("calculated_theoretical_equivalence_volume_ml", config.calculatedTheoreticalEquivalenceVolumeMl)
            .put("sample_concentration_from_theoretical_equivalence_M", config.sampleConcentrationFromTheoreticalEquivalenceM)
            .put("phone_local", true)
            .put("thermal_calibration_policy", "no Celsius unless validated native backend")
            .put("roi_mask_metadata", true)
    }
}
