package kr.auto.titration.mobile.pump

object PumpCommandContract {
    val supportedCommands = listOf(
        "a left/reverse",
        "b right/forward",
        "c stop",
        "s status",
        "r reset",
    )
    private val supportedLetters = setOf("a", "b", "c", "s", "r")

    /** Pump commands are allowed only from explicit user actions, never ML/status automation. */
    fun commandMayComeFromAutomation(command: String): Boolean = false

    fun requireSupported(line: String) {
        val letter = line.trim().take(1).lowercase()
        require(letter in supportedLetters) { "unsupported pump command: $line" }
    }
}
