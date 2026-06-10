package kr.auto.titration.mobile.ml

object YoloTensorContractValidator {
    const val tensor_contract_fixture = "yolo11n_seg_256_fp32_two_output_contract_v1"

    private const val EXPECTED_INPUT_SIZE = 256
    private const val DETECTION_TENSOR = "detection_tensor"
    private const val PROTOTYPE_TENSOR = "prototype_tensor"

    fun validateTensorContract(metadata: VisibleRoiModelMetadata): YoloModelAvailability {
        if (metadata.liteRtVersion != VisibleRoiModelMetadata.EXPECTED_LITERT_VERSION) {
            return YoloModelAvailability.unavailable(
                "yolo_tensor_contract_mismatch",
                "metadata litert_version=${metadata.liteRtVersion} expected=${VisibleRoiModelMetadata.EXPECTED_LITERT_VERSION}",
            )
        }
        if (metadata.inputSize != EXPECTED_INPUT_SIZE) {
            return YoloModelAvailability.unavailable(
                "yolo_tensor_contract_mismatch",
                "metadata input_size=${metadata.inputSize} expected=$EXPECTED_INPUT_SIZE",
            )
        }
        val detection = metadata.outputTensorContract[DETECTION_TENSOR].orEmpty()
        val prototype = metadata.outputTensorContract[PROTOTYPE_TENSOR].orEmpty()
        if (!detection.contains("4 + classes + mask_dim") || !detection.contains("predictions")) {
            return YoloModelAvailability.unavailable(
                "yolo_tensor_contract_mismatch",
                "missing YOLO detection tensor contract in $tensor_contract_fixture",
            )
        }
        if (!prototype.contains("mask_dim") || !prototype.contains("proto_h")) {
            return YoloModelAvailability.unavailable(
                "yolo_tensor_contract_mismatch",
                "missing YOLO prototype tensor contract in $tensor_contract_fixture",
            )
        }
        if ("cup" !in metadata.acceptedClasses) {
            return YoloModelAvailability.unavailable(
                "yolo_tensor_contract_mismatch",
                "accepted_classes must include cup for titration vessel detection",
            )
        }
        return YoloModelAvailability.available("metadata tensor contract matches $tensor_contract_fixture")
    }
}
