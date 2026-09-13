package kr.auto.titration.mobile.thermal.officialdex.radiometric;

import java.util.Arrays;

/**
 * Host-side snapshot of the exact {@code PaletteBean} fields consumed by
 * {@code d3.f.e}. W9 supplies {@code previewManager.Q()} as renderer argument
 * 17; that object is either captured here or explicitly proved absent.
 */
public final class OfficialF2PaletteSnapshot {
    public enum AbsenceProof {
        PREVIEW_MANAGER_Q_RETURNED_NULL
    }

    private final boolean present;
    private final int paletteMode;
    private final int customPseudoColorHexArrSize;
    private final String[] customPseudoColorHexArr;
    private final int pseudoColor;
    private final float maxTmp;
    private final float minTmp;
    private final int ispMode;
    private final int agcMode;
    private final float wideTempUpThreshold;
    private final float wideTempDownThreshold;
    private final int rawGrayMax;
    private final int rawGrayMin;
    private final int agcGrayMax;
    private final int agcGrayMin;
    private final int colorAlarmMax;
    private final int colorAlarmMin;
    private final int colorAlarm14bitMax;
    private final int colorAlarm14bitMin;
    private final AbsenceProof absenceProof;

    private OfficialF2PaletteSnapshot(
        boolean present,
        int paletteMode,
        int customPseudoColorHexArrSize,
        String[] customPseudoColorHexArr,
        int pseudoColor,
        float maxTmp,
        float minTmp,
        int ispMode,
        int agcMode,
        float wideTempUpThreshold,
        float wideTempDownThreshold,
        int rawGrayMax,
        int rawGrayMin,
        int agcGrayMax,
        int agcGrayMin,
        int colorAlarmMax,
        int colorAlarmMin,
        int colorAlarm14bitMax,
        int colorAlarm14bitMin,
        AbsenceProof absenceProof
    ) {
        this.present = present;
        this.paletteMode = paletteMode;
        this.customPseudoColorHexArrSize = customPseudoColorHexArrSize;
        this.customPseudoColorHexArr = copy(customPseudoColorHexArr);
        this.pseudoColor = pseudoColor;
        this.maxTmp = maxTmp;
        this.minTmp = minTmp;
        this.ispMode = ispMode;
        this.agcMode = agcMode;
        this.wideTempUpThreshold = wideTempUpThreshold;
        this.wideTempDownThreshold = wideTempDownThreshold;
        this.rawGrayMax = rawGrayMax;
        this.rawGrayMin = rawGrayMin;
        this.agcGrayMax = agcGrayMax;
        this.agcGrayMin = agcGrayMin;
        this.colorAlarmMax = colorAlarmMax;
        this.colorAlarmMin = colorAlarmMin;
        this.colorAlarm14bitMax = colorAlarm14bitMax;
        this.colorAlarm14bitMin = colorAlarm14bitMin;
        this.absenceProof = absenceProof;
    }

    public static OfficialF2PaletteSnapshot present(
        int paletteMode,
        int customPseudoColorHexArrSize,
        String[] customPseudoColorHexArr
    ) {
        return new OfficialF2PaletteSnapshot(
            true,
            paletteMode,
            customPseudoColorHexArrSize,
            customPseudoColorHexArr,
            0,
            0f,
            0f,
            0,
            0,
            0f,
            0f,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            null
        );
    }

    public static OfficialF2PaletteSnapshot present(
        int paletteMode,
        int customPseudoColorHexArrSize,
        String[] customPseudoColorHexArr,
        int pseudoColor,
        float maxTmp,
        float minTmp,
        int ispMode,
        int agcMode,
        float wideTempUpThreshold,
        float wideTempDownThreshold,
        int rawGrayMax,
        int rawGrayMin,
        int agcGrayMax,
        int agcGrayMin,
        int colorAlarmMax,
        int colorAlarmMin,
        int colorAlarm14bitMax,
        int colorAlarm14bitMin
    ) {
        return new OfficialF2PaletteSnapshot(
            true,
            paletteMode,
            customPseudoColorHexArrSize,
            customPseudoColorHexArr,
            pseudoColor,
            maxTmp,
            minTmp,
            ispMode,
            agcMode,
            wideTempUpThreshold,
            wideTempDownThreshold,
            rawGrayMax,
            rawGrayMin,
            agcGrayMax,
            agcGrayMin,
            colorAlarmMax,
            colorAlarmMin,
            colorAlarm14bitMax,
            colorAlarm14bitMin,
            null
        );
    }

    public static OfficialF2PaletteSnapshot absent(AbsenceProof proof) {
        return new OfficialF2PaletteSnapshot(
            false, 0, 0, null, 0, 0f, 0f, 0, 0, 0f, 0f, 0, 0, 0, 0, 0, 0, 0, 0, proof
        );
    }

    public boolean isPresent() {
        return present;
    }

    public int getPaletteMode() {
        return paletteMode;
    }

    public int getCustomPseudoColorHexArrSize() {
        return customPseudoColorHexArrSize;
    }

    public String[] getCustomPseudoColorHexArr() {
        return copy(customPseudoColorHexArr);
    }


    public int getPseudoColor() {
        return pseudoColor;
    }

    public float getMaxTmp() {
        return maxTmp;
    }

    public float getMinTmp() {
        return minTmp;
    }

    public int getIspMode() {
        return ispMode;
    }

    public int getAgcMode() {
        return agcMode;
    }

    public float getWideTempUpThreshold() {
        return wideTempUpThreshold;
    }

    public float getWideTempDownThreshold() {
        return wideTempDownThreshold;
    }

    public int getRawGrayMax() {
        return rawGrayMax;
    }

    public int getRawGrayMin() {
        return rawGrayMin;
    }

    public int getAgcGrayMax() {
        return agcGrayMax;
    }

    public int getAgcGrayMin() {
        return agcGrayMin;
    }

    public int getColorAlarmMax() {
        return colorAlarmMax;
    }

    public int getColorAlarmMin() {
        return colorAlarmMin;
    }

    public int getColorAlarm14bitMax() {
        return colorAlarm14bitMax;
    }

    public int getColorAlarm14bitMin() {
        return colorAlarm14bitMin;
    }

    public AbsenceProof getAbsenceProof() {
        return absenceProof;
    }

    private static String[] copy(String[] value) {
        return value == null ? null : Arrays.copyOf(value, value.length);
    }
}
