package kr.auto.titration.mobile.chemistry

data class IndicatorRange(
    val name: String,
    val lowPh: Double,
    val highPh: Double,
    val warning: String,
)

object IndicatorModels {
    val phenolphthalein = IndicatorRange(
        name = "Phenolphthalein",
        lowPh = 8.2,
        highPh = 10.0,
        warning = "Color endpoint is an experimental signal, not the true equivalence point.",
    )

    val methylOrange = IndicatorRange(
        name = "Methyl orange",
        lowPh = 3.1,
        highPh = 4.4,
        warning = "Choose indicator range near the expected pH jump; ML/thermal evidence still compares against equivalence volume.",
    )
}
