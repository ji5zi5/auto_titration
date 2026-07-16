package kr.auto.titration.mobile.thermal.officialdex;

import dalvik.system.DexClassLoader;

/**
 * Narrow child-first loader for exact official HIKMICRO namespaces only.
 *
 * Platform/runtime namespaces remain parent-first. Official namespaces attempt
 * findClass() first so app-side reconstructed/shadow classes cannot satisfy the
 * Mini2 official-bytecode identity contract. Required identity classes are never
 * parent-resolved: absence in the official dex set is a closed failure.
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
        synchronized (getClassLoadingLock(name)) {
            Class<?> loaded = findLoadedClass(name);
            if (loaded == null) {
                if (isParentFirst(name)) {
                    loaded = super.loadClass(name, false);
                } else if (isOfficialChildFirst(name)) {
                    try {
                        loaded = findClass(name);
                    } catch (ClassNotFoundException officialMissing) {
                        if (OfficialDexArtifacts.REQUIRED_OFFICIAL_CLASSES.contains(name)) {
                            throw officialMissing;
                        }
                        loaded = super.loadClass(name, false);
                    }
                } else {
                    loaded = super.loadClass(name, false);
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

    public static boolean isOfficialChildFirst(String className) {
        if (OfficialDexArtifacts.REQUIRED_OFFICIAL_CLASSES.contains(className)) {
            return true;
        }
        for (String prefix : OfficialDexArtifacts.OFFICIAL_CHILD_FIRST_PREFIXES) {
            if (className.startsWith(prefix)) {
                return true;
            }
        }
        return false;
    }
}
