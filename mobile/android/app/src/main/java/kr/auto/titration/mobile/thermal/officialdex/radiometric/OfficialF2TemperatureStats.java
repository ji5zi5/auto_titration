package kr.auto.titration.mobile.thermal.officialdex.radiometric;

/**
 * Official rule/global scalar temperatures converted from d3 ints. No full
 * temperature matrix/vector is represented or exposed by this model.
 */
public final class OfficialF2TemperatureStats {
    private final Float maxCelsius;
    private final Float minCelsius;
    private final Float centerCelsius;
    private final Float averageCelsius;

    public OfficialF2TemperatureStats(
        Float maxCelsius,
        Float minCelsius,
        Float centerCelsius,
        Float averageCelsius
    ) {
        this.maxCelsius = maxCelsius;
        this.minCelsius = minCelsius;
        this.centerCelsius = centerCelsius;
        this.averageCelsius = averageCelsius;
    }

    public Float getMaxCelsius() {
        return maxCelsius;
    }

    public Float getMinCelsius() {
        return minCelsius;
    }

    public Float getCenterCelsius() {
        return centerCelsius;
    }

    public Float getAverageCelsius() {
        return averageCelsius;
    }
}
