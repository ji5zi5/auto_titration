package kr.auto.titration.mobile.thermal.officialdex;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Exact official HIKMICRO Mini2 bytecode/native artifacts approved for G008.
 *
 * Keep these as verbatim APK bytes: do not D8, smali-reassemble, decompile, or
 * source-reconstruct them. The loader copies every supplied APK dex asset into
 * private app storage in original APK order and verifies these hashes before
 * DexClassLoader sees them.
 */
public final class OfficialDexArtifacts {
    public static final String ASSET_ROOT = "hikmicro/official";
    public static final String CLASSES_ASSET = ASSET_ROOT + "/classes.dex";
    public static final String CLASSES2_ASSET = ASSET_ROOT + "/classes2.dex";
    public static final String CLASSES3_ASSET = ASSET_ROOT + "/classes3.dex";
    public static final String CLASSES4_ASSET = ASSET_ROOT + "/classes4.dex";
    public static final String CLASSES_SHA256 = "2bd1971bc914fc5a35084137ec97274bd69316403f020f52995526ab77019e20";
    public static final String CLASSES2_SHA256 = "da26f34a40e4ac87b4a318174c49d1da2fef53caea95a2ceb30a3184ea9307ad";
    public static final String CLASSES3_SHA256 = "f360bb57acbfb5cdad1fb2cf63ef90498c146383283e1989f1747a387443d6ff";
    public static final String CLASSES4_SHA256 = "d40331731cb6731e208bc92815b970e51fc69c25a904b29d1616d9cd3ca57fd9";
    public static final String NATIVE_LIBRARY_NAME = "libSJNI.so";
    public static final String NATIVE_LIBRARY_SHA256 = "698b60ea4cb6eccf8cd9570d6bbf6aac246f145661629d0ba938e5f02345fee8";

    public static final List<DexAsset> DEX_ASSETS = Collections.unmodifiableList(Arrays.asList(
        new DexAsset(CLASSES_ASSET, "classes.dex", CLASSES_SHA256),
        new DexAsset(CLASSES2_ASSET, "classes2.dex", CLASSES2_SHA256),
        new DexAsset(CLASSES3_ASSET, "classes3.dex", CLASSES3_SHA256),
        new DexAsset(CLASSES4_ASSET, "classes4.dex", CLASSES4_SHA256)
    ));

    public static final Set<String> REQUIRED_OFFICIAL_CLASSES = Collections.unmodifiableSet(new LinkedHashSet<>(Arrays.asList(
        "d3.f",
        "d3.d",
        "d3.e",
        "d3.g",
        "Z2.a",
        "Z2.g",
        "k3.b",
        "f3.k",
        // d3.f.e exact signature probes: parameters/return-path objects that must not bind host shadows.
        "com.hik.f2module.IFR_INFO$OFFLINE_TEMP_MEASURE_CFG",
        "com.hikmicro.analyzer.sdk.palette.bean.PaletteBean",
        "hik.common.yyrj.uicommon.data.ModuleType",
        "com.hikvision.microjita.AnalyzerII",
        "com.hikvision.microjita.bean.AnalyzerInfoPic",
        // MicroJITA and representative measurement/SWIG parameter and return classes.
        "com.guardexpert.microsensorsdk.MicroJITA",
        "com.guardexpert.microsensorsdk.MicroJITAPrivate",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.MicroJITASWIG",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.MicroJITASWIGJNI",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.MicroJITAPrivateSWIG",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.MicroJITAPrivateSWIGJNI",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasureRule",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementStats",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementEnvParams",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasureRuleDict",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.MicroSmartSensorDataExtension$JPEG",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.SharedByteBuffer",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.RawDataInfo",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.mResolution",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.mRangeInt",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.Image",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.PseudoColorParams",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.IRCapabilities",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.AlgorithmLib",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.AlgorithmLibInfoVect",
        "com.guardexpert.microsensorsdk.core.microsensorcontroldata.FrameData"
    )));

    public static final List<String> PLATFORM_PARENT_FIRST_PREFIXES = Collections.unmodifiableList(Arrays.asList(
        "java.",
        "javax.",
        "android.",
        "androidx.",
        "kotlin.",
        "kotlinx.",
        "org.json.",
        "dalvik."
    ));

    private OfficialDexArtifacts() {
    }

    public static final class DexAsset {
        public final String assetPath;
        public final String fileName;
        public final String sha256;

        public DexAsset(String assetPath, String fileName, String sha256) {
            this.assetPath = assetPath;
            this.fileName = fileName;
            this.sha256 = sha256;
        }
    }
}
