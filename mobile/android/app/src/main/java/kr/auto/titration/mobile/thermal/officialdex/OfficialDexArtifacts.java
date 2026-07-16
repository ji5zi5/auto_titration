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
 * source-reconstruct them. The loader copies the dex assets into private app
 * storage and verifies these hashes before DexClassLoader sees them.
 */
public final class OfficialDexArtifacts {
    public static final String ASSET_ROOT = "hikmicro/official";
    public static final String CLASSES2_ASSET = ASSET_ROOT + "/classes2.dex";
    public static final String CLASSES3_ASSET = ASSET_ROOT + "/classes3.dex";
    public static final String CLASSES2_SHA256 = "da26f34a40e4ac87b4a318174c49d1da2fef53caea95a2ceb30a3184ea9307ad";
    public static final String CLASSES3_SHA256 = "f360bb57acbfb5cdad1fb2cf63ef90498c146383283e1989f1747a387443d6ff";
    public static final String NATIVE_LIBRARY_NAME = "libSJNI.so";
    public static final String NATIVE_LIBRARY_SHA256 = "698b60ea4cb6eccf8cd9570d6bbf6aac246f145661629d0ba938e5f02345fee8";

    public static final List<DexAsset> DEX_ASSETS = Collections.unmodifiableList(Arrays.asList(
        new DexAsset(CLASSES2_ASSET, "classes2.dex", CLASSES2_SHA256),
        new DexAsset(CLASSES3_ASSET, "classes3.dex", CLASSES3_SHA256)
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
        "com.guardexpert.microsensorsdk.MicroJITA",
        "com.guardexpert.microsensorsdk.MicroJITAPrivate",
        // Representative official SWIG wrappers used by the MicroJITA SDK surface.
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.AlgorithmLib",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.AlgorithmLibInfoVect",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.IRCapabilities",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.Image",
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

    public static final List<String> OFFICIAL_CHILD_FIRST_PREFIXES = Collections.unmodifiableList(Arrays.asList(
        "d3.",
        "Z2.",
        "k3.",
        "f3.",
        "com.guardexpert.microsensorsdk."
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
