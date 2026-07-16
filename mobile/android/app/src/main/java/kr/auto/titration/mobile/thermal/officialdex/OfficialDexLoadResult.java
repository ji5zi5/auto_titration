package kr.auto.titration.mobile.thermal.officialdex;

public final class OfficialDexLoadResult {
    private final OfficialDexClassLoader classLoader;
    private final OfficialDexIdentityReport identityReport;

    OfficialDexLoadResult(OfficialDexClassLoader classLoader, OfficialDexIdentityReport identityReport) {
        this.classLoader = classLoader;
        this.identityReport = identityReport;
    }

    public ClassLoader getClassLoader() {
        return classLoader;
    }

    public OfficialDexIdentityReport getIdentityReport() {
        return identityReport;
    }

    public Class<?> loadOfficialClass(String className) throws ClassNotFoundException {
        return Class.forName(className, false, classLoader);
    }
}
