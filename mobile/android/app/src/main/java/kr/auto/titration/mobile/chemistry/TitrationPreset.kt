package kr.auto.titration.mobile.chemistry

data class ChemicalPreset(
    val displayName: String,
    val formula: String,
    val role: String,
    val defaultConcentrationM: Double,
    val pKa: Double? = null,
    val pKb: Double? = null,
)

object TitrationPresets {
    val hydrochloricAcid = ChemicalPreset("Hydrochloric acid", "HCl", "strong_acid", 0.1)
    val sodiumHydroxide = ChemicalPreset("Sodium hydroxide", "NaOH", "strong_base", 0.1)
    val aceticAcid = ChemicalPreset("Acetic acid", "CH3COOH", "weak_acid", 0.1, pKa = 4.76)
    val ammonia = ChemicalPreset("Ammonia", "NH3", "weak_base", 0.1, pKb = 4.75)

    val defaults = listOf(hydrochloricAcid, sodiumHydroxide, aceticAcid, ammonia)
}
