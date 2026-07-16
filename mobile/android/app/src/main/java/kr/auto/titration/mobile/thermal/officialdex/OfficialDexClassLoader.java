package kr.auto.titration.mobile.thermal.officialdex;

import dalvik.system.DexClassLoader;

/**
 * Dedicated child-first loader for exact official HIKMICRO bytecode.
 *
 * Platform/runtime namespaces stay parent-first. Every other class attempts
 * findClass() first so reconstructed app classes with the same FQCN cannot shadow
 * official dex definitions. Parent fallback is only for classes absent from the
 * supplied official dex set; required identity probes never fall back.
 */
public final class OfficialDexClassLoader extends DexClassLoader {
    OfficialDexClassLoader(
        String dexPath,
        String optimizedDirectory,
        String librarySearchPath,
        ClassLoader parent
    ) {
        super(dexPath, optimizedDirectory, librarySearchPath, parent);
    }

    @Override
    protected Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {
        synchronized (this) {
            Class<?> loaded = findLoadedClass(name);
            if (loaded == null) {
                if (isParentFirst(name)) {
                    loaded = super.loadClass(name, false);
                } else {
                    try {
                        loaded = findClass(name);
                    } catch (ClassNotFoundException officialMissing) {
                        if (isRequiredOfficialIdentityClass(name)) {
                            throw officialMissing;
                        }
                        loaded = super.loadClass(name, false);
                    }
                }
            }
            if (resolve) {
                resolveClass(loaded);
            }
            return loaded;
        }
    }

    public static boolean isParentFirst(String className) {
        for (String prefix : OfficialDexArtifacts.PLATFORM_PARENT_FIRST_PREFIXES) {
            if (className.startsWith(prefix)) {
                return true;
            }
        }
        return false;
    }

    public static boolean isChildFirst(String className) {
        return !isParentFirst(className);
    }

    public static boolean isRequiredOfficialIdentityClass(String className) {
        return OfficialDexArtifacts.REQUIRED_OFFICIAL_CLASSES.contains(className);
    }
}
