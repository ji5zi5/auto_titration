package kr.auto.titration.mobile.thermal.officialdex.radiometric;

import java.nio.ByteOrder;
import java.util.Arrays;

/** Package-private seam around official child-loader/reflection operations. */
interface OfficialF2RadiometricRuntime {
    void bootstrap(OfficialF2ModuleIdentity identity, int videoCodingType, int packetSize) throws Exception;

    OfficialF2ParsedOfflineConfig parseOfflineConfig(OfficialF2ParserCall call) throws Exception;

    Object createPaletteBean(OfficialF2PaletteSnapshot snapshot) throws Exception;

    Object resolveModuleType(OfficialF2ModuleSubtype subtype) throws Exception;

    byte[] renderRadiometricJpeg(OfficialF2RendererCall call) throws Exception;

    void prepareAnalyzer() throws Exception;

    boolean initAnalyzer(byte[] radiometricJpeg) throws Exception;

    Object buildMeasureRule(OfficialF2RuleSpec ruleSpec) throws Exception;

    OfficialF2MeasurementD3 measure(Object measureRule) throws Exception;

    float intd3ToFloat(int value) throws Exception;

    void releaseAnalyzer() throws Exception;
}

final class OfficialF2ParserCall {
    private final byte[] callbackHead;
    private final int videoCodingType;
    private final boolean forcePaletteMode14;
    private final ByteOrder byteOrder;
    private final int defaultMask;
    private final Object marker;

    OfficialF2ParserCall(byte[] callbackHead, int videoCodingType, boolean forcePaletteMode14) {
        this.callbackHead = Arrays.copyOf(callbackHead, callbackHead.length);
        this.videoCodingType = videoCodingType;
        this.forcePaletteMode14 = forcePaletteMode14;
        // Exact k3.b.d synthetic-default arguments in W9: null, 4, null.
        this.byteOrder = null;
        this.defaultMask = 4;
        this.marker = null;
    }

    byte[] getCallbackHead() {
        return Arrays.copyOf(callbackHead, callbackHead.length);
    }

    int getVideoCodingType() {
        return videoCodingType;
    }

    boolean isForcePaletteMode14() {
        return forcePaletteMode14;
    }

    ByteOrder getByteOrder() {
        return byteOrder;
    }

    int getDefaultMask() {
        return defaultMask;
    }

    Object getMarker() {
        return marker;
    }
}

final class OfficialF2ParsedOfflineConfig {
    private final Object offlineTempMeasureCfg;
    private final byte[] extendGeneralInfo;

    OfficialF2ParsedOfflineConfig(Object offlineTempMeasureCfg, byte[] extendGeneralInfo) {
        this.offlineTempMeasureCfg = offlineTempMeasureCfg;
        this.extendGeneralInfo = extendGeneralInfo == null
            ? null
            : Arrays.copyOf(extendGeneralInfo, extendGeneralInfo.length);
    }

    Object getOfflineTempMeasureCfg() {
        return offlineTempMeasureCfg;
    }

    byte[] getExtendGeneralInfo() {
        return extendGeneralInfo == null
            ? null
            : Arrays.copyOf(extendGeneralInfo, extendGeneralInfo.length);
    }
}

final class OfficialF2RendererCall {
    static final int EXACT_ARGUMENT_COUNT = 21;

    private final Object[] exactArguments;

    OfficialF2RendererCall(Object[] exactArguments) {
        if (exactArguments == null || exactArguments.length != EXACT_ARGUMENT_COUNT) {
            throw new IllegalArgumentException("d3.f.e requires exactly 21 arguments");
        }
        this.exactArguments = Arrays.copyOf(exactArguments, exactArguments.length);
    }

    Object[] getExactArguments() {
        return Arrays.copyOf(exactArguments, exactArguments.length);
    }
}

final class OfficialF2RuleSpec {
    private final OfficialF2RuleScope scope;
    private final int id;
    private final String name;
    private final int x0;
    private final int y0;
    private final int x1;
    private final int y1;

    OfficialF2RuleSpec(
        OfficialF2RuleScope scope,
        int id,
        String name,
        int x0,
        int y0,
        int x1,
        int y1
    ) {
        this.scope = scope;
        this.id = id;
        this.name = name;
        this.x0 = x0;
        this.y0 = y0;
        this.x1 = x1;
        this.y1 = y1;
    }

    OfficialF2RuleScope getScope() {
        return scope;
    }

    int getId() {
        return id;
    }

    String getName() {
        return name;
    }

    int getX0() {
        return x0;
    }

    int getY0() {
        return y0;
    }

    int getX1() {
        return x1;
    }

    int getY1() {
        return y1;
    }
}

final class OfficialF2MeasurementD3 {
    private final boolean success;
    private final Integer maxD3;
    private final Integer minD3;
    private final Integer centerD3;
    private final int averageD3;

    OfficialF2MeasurementD3(
        boolean success,
        Integer maxD3,
        Integer minD3,
        Integer centerD3,
        int averageD3
    ) {
        this.success = success;
        this.maxD3 = maxD3;
        this.minD3 = minD3;
        this.centerD3 = centerD3;
        this.averageD3 = averageD3;
    }

    boolean isSuccess() {
        return success;
    }

    Integer getMaxD3() {
        return maxD3;
    }

    Integer getMinD3() {
        return minD3;
    }

    Integer getCenterD3() {
        return centerD3;
    }

    int getAverageD3() {
        return averageD3;
    }
}
