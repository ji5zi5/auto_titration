package kr.auto.titration.mobile.thermal.officialdex;

import android.content.Context;

import java.io.File;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Explicit-only loader for G008 official HIKMICRO Mini2 dex bytes.
 *
 * This class performs no automatic startup work. Future Mini2 code must call
 * load(context) explicitly and keep all host/child interaction reflective.
 */
public final class OfficialDexLoader {
    private static OfficialDexLoadResult singleton;

    private OfficialDexLoader() {
    }

    public static synchronized OfficialDexLoadResult load(Context context) throws OfficialDexLoadException {
        if (singleton != null) {
            return singleton;
        }
        Context appContext = context.getApplicationContext() != null ? context.getApplicationContext() : context;
        try {
            OfficialDexFileInstaller.InstalledDexSet installedDexSet = OfficialDexFileInstaller.install(appContext);
            String nativeLibraryDir = appContext.getApplicationInfo().nativeLibraryDir;
            verifyNativeLibrary(nativeLibraryDir);

            OfficialDexClassLoader loader = new OfficialDexClassLoader(
                installedDexSet.dexPath(),
                installedDexSet.optimizedDirectory.getAbsolutePath(),
                nativeLibraryDir,
                OfficialDexLoader.class.getClassLoader()
            );
            OfficialDexIdentityReport report = buildIdentityReport(installedDexSet.dexPath(), nativeLibraryDir, loader);
            if (!report.allDefinedBy(loader)) {
                throw new OfficialDexLoadException("Official identity report includes non-official defining loader: " + report.getDefiningLoadersByClass());
            }
            singleton = new OfficialDexLoadResult(loader, report);
            return singleton;
        } catch (LinkageError e) {
            singleton = null;
            throw new OfficialDexLoadException("Official dex linkage failed closed", e);
        } catch (RuntimeException e) {
            singleton = null;
            throw new OfficialDexLoadException("Official dex runtime load failed closed", e);
        }
    }

    public static synchronized void resetForTests(Context context) {
        singleton = null;
        if (context != null) {
            Context appContext = context.getApplicationContext() != null ? context.getApplicationContext() : context;
            OfficialDexFileInstaller.reset(appContext);
        }
    }

    private static void verifyNativeLibrary(String nativeLibraryDir) throws OfficialDexLoadException {
        if (nativeLibraryDir == null || nativeLibraryDir.isEmpty()) {
            throw new OfficialDexLoadException("Application nativeLibraryDir is unavailable");
        }
        File nativeLibrary = new File(nativeLibraryDir, OfficialDexArtifacts.NATIVE_LIBRARY_NAME);
        if (!nativeLibrary.isFile()) {
            throw new OfficialDexLoadException("Missing official native library: " + nativeLibrary);
        }
        try {
            String actualHash = OfficialDexHashing.sha256(nativeLibrary);
            if (!OfficialDexHashing.constantTimeEquals(OfficialDexArtifacts.NATIVE_LIBRARY_SHA256, actualHash)) {
                throw new OfficialDexLoadException(
                    "Official native library hash mismatch: expected " + OfficialDexArtifacts.NATIVE_LIBRARY_SHA256 + " got " + actualHash
                );
            }
        } catch (IOException e) {
            throw new OfficialDexLoadException("Cannot hash official native library: " + nativeLibrary, e);
        }
    }

    private static OfficialDexIdentityReport buildIdentityReport(
        String dexPath,
        String nativeLibraryDir,
        OfficialDexClassLoader loader
    ) throws OfficialDexLoadException {
        Map<String, String> identities = new LinkedHashMap<>();
        for (String className : OfficialDexArtifacts.REQUIRED_OFFICIAL_CLASSES) {
            try {
                Class<?> loaded = Class.forName(className, false, loader);
                identities.put(className, OfficialDexIdentityReport.loaderIdentity(loaded.getClassLoader()));
            } catch (ClassNotFoundException e) {
                throw new OfficialDexLoadException("Required official class is absent from official dex assets: " + className, e);
            } catch (NoClassDefFoundError e) {
                throw new OfficialDexLoadException("Required official class dependency is absent: " + className, e);
            } catch (UnsatisfiedLinkError e) {
                throw new OfficialDexLoadException("Required official class native link failed: " + className, e);
            } catch (LinkageError e) {
                throw new OfficialDexLoadException("Required official class linkage failed: " + className, e);
            }
        }
        return new OfficialDexIdentityReport(dexPath, nativeLibraryDir, identities);
    }
}
