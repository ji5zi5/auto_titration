package kr.auto.titration.mobile.export

data class ExportManifest(
    val runId: String,
    val csvFileName: String,
    val metadataFileName: String,
    val thermalEvidenceFileName: String? = null,
)
