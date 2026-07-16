package kr.auto.titration.mobile.thermal.officialdex;

import java.io.File;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

public final class OfficialDexIdentityReport {
    private final String dexPath;
    private final String nativeLibraryDir;
    private final Map<String, String> definingLoadersByClass;

    OfficialDexIdentityReport(String dexPath, String nativeLibraryDir, Map<String, String> definingLoadersByClass) {
        this.dexPath = dexPath;
        this.nativeLibraryDir = nativeLibraryDir;
        this.definingLoadersByClass = Collections.unmodifiableMap(new LinkedHashMap<>(definingLoadersByClass));
    }

    public String getDexPath() {
        return dexPath;
    }

    public String getNativeLibraryDir() {
        return nativeLibraryDir;
    }

    public Map<String, String> getDefiningLoadersByClass() {
        return definingLoadersByClass;
    }

    public boolean allDefinedBy(ClassLoader loader) {
        String expected = loaderIdentity(loader);
        for (String actual : definingLoadersByClass.values()) {
            if (!expected.equals(actual)) {
                return false;
            }
        }
        return true;
    }

    static String loaderIdentity(ClassLoader loader) {
        if (loader == null) {
            return "bootstrap";
        }
        return loader.getClass().getName() + "@" + Integer.toHexString(System.identityHashCode(loader));
    }
}
