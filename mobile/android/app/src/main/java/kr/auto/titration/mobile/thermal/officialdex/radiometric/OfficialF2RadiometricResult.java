package kr.auto.titration.mobile.thermal.officialdex.radiometric;

import java.util.Arrays;

/** Exact official radiometric JPEG plus scalar rule/global temperature stats. */
public final class OfficialF2RadiometricResult {
    private final byte[] radiometricJpeg;
    private final OfficialF2RuleScope measuredScope;
    private final OfficialF2TemperatureStats ruleTemperatureStats;
    private final OfficialF2TemperatureStats globalTemperatureStats;

    public OfficialF2RadiometricResult(
        byte[] radiometricJpeg,
        OfficialF2RuleScope measuredScope,
        OfficialF2TemperatureStats ruleTemperatureStats,
        OfficialF2TemperatureStats globalTemperatureStats
    ) {
        if (radiometricJpeg == null || radiometricJpeg.length == 0) {
            throw new IllegalArgumentException("radiometricJpeg must be non-empty");
        }
        if (measuredScope == null) {
            throw new IllegalArgumentException("measuredScope is required");
        }
        if (ruleTemperatureStats == null) {
            throw new IllegalArgumentException("ruleTemperatureStats is required");
        }
        this.radiometricJpeg = Arrays.copyOf(radiometricJpeg, radiometricJpeg.length);
        this.measuredScope = measuredScope;
        this.ruleTemperatureStats = ruleTemperatureStats;
        this.globalTemperatureStats = globalTemperatureStats;
    }

    public byte[] getRadiometricJpeg() {
        return Arrays.copyOf(radiometricJpeg, radiometricJpeg.length);
    }

    public OfficialF2RuleScope getMeasuredScope() {
        return measuredScope;
    }

    /** Stats for the exact ROI/fullscreen MeasureRule passed to AnalyzerII.measure. */
    public OfficialF2TemperatureStats getRuleTemperatureStats() {
        return ruleTemperatureStats;
    }

    /** Present only when the exact measured rule was fullscreen/global. */
    public OfficialF2TemperatureStats getGlobalTemperatureStats() {
        return globalTemperatureStats;
    }
}
