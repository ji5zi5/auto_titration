package kr.auto.titration.mobile.ml

object BaselineTrainer {
    fun constantMean(targetValuesMl: List<Double>): EquivalenceJsonModel {
        require(targetValuesMl.isNotEmpty()) { "at least one target value is required" }
        val mean = targetValuesMl.average()
        val warning = if (targetValuesMl.size < 3) {
            "Sparse labeled data: ${targetValuesMl.size} row(s); using constant mean model."
        } else {
            "Constant mean baseline; collect more runs before claiming ML accuracy."
        }
        return EquivalenceJsonModel.constantMean(mean, warning)
    }
}
