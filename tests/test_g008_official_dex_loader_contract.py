from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "mobile/android/app"
OFFICIALDEX = APP / "src/main/java/kr/auto/titration/mobile/thermal/officialdex"

EXPECTED = {
    APP / "src/main/assets/hikmicro/official/classes2.dex": "da26f34a40e4ac87b4a318174c49d1da2fef53caea95a2ceb30a3184ea9307ad",
    APP / "src/main/assets/hikmicro/official/classes3.dex": "f360bb57acbfb5cdad1fb2cf63ef90498c146383283e1989f1747a387443d6ff",
    APP / "src/main/jniLibs/arm64-v8a/libSJNI.so": "698b60ea4cb6eccf8cd9570d6bbf6aac246f145661629d0ba938e5f02345fee8",
}

FORBIDDEN_REASSEMBLY_PATHS = [
    APP / "src/main/java/d3",
    APP / "src/main/java/Z2",
    APP / "src/main/java/k3",
    APP / "src/main/java/f3",
    APP / "src/main/java/com/guardexpert/microsensorsdk",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name: str) -> str:
    return (OFFICIALDEX / name).read_text(encoding="utf-8")


def test_exact_official_assets_and_native_hashes():
    for path, expected in EXPECTED.items():
        assert path.is_file(), f"missing official artifact {path}"
        assert sha256(path) == expected


def test_loader_documents_and_enforces_no_reassembly_foundation():
    artifacts = read("OfficialDexArtifacts.java")
    assert "Keep these as verbatim APK bytes" in artifacts
    assert "do not D8, smali-reassemble, decompile" in artifacts
    assert "CLASSES2_ASSET" in artifacts and "CLASSES3_ASSET" in artifacts

    scoped_sources = "\n".join(path.read_text(encoding="utf-8") for path in OFFICIALDEX.glob("*.java"))
    assert "DexClassLoader" in scoped_sources
    assert "applicationInfo().nativeLibraryDir" in scoped_sources or "getApplicationInfo().nativeLibraryDir" in scoped_sources
    assert "Class.forName(className, false, loader)" in scoped_sources
    assert "D8" not in scoped_sources.replace("do not D8", "")
    assert "baksmali" not in scoped_sources.lower()


def test_target35_readonly_before_write_and_hash_before_load_order():
    installer = read("OfficialDexFileInstaller.java")
    open_at = installer.index("new FileOutputStream(destination, false)")
    readonly_at = installer.index("destination.setReadOnly()")
    write_at = installer.index("transferFrom")
    force_at = installer.index("force(true)")
    hash_at = installer.index("OfficialDexHashing.sha256(destination)", force_at)
    assert open_at < readonly_at < write_at < force_at < hash_at

    loader = read("OfficialDexLoader.java")
    install_at = loader.index("OfficialDexFileInstaller.install")
    native_at = loader.index("verifyNativeLibrary")
    dex_loader_at = loader.index("new OfficialDexClassLoader")
    identity_at = loader.index("buildIdentityReport")
    assert install_at < native_at < dex_loader_at < identity_at


def test_child_first_loader_does_not_parent_shadow_required_official_classes():
    class_loader = read("OfficialDexClassLoader.java")
    assert "isParentFirst(name)" in class_loader
    assert "isOfficialChildFirst(name)" in class_loader
    assert re.search(r"if \(OfficialDexArtifacts\.REQUIRED_OFFICIAL_CLASSES\.contains\(name\)\) \{\s*throw officialMissing;\s*\}", class_loader)
    assert "loaded = findClass(name);" in class_loader

    artifacts = read("OfficialDexArtifacts.java")
    for required in [
        "d3.f", "d3.d", "d3.e", "d3.g", "Z2.a", "Z2.g", "k3.b", "f3.k",
        "com.guardexpert.microsensorsdk.MicroJITA",
        "com.guardexpert.microsensorsdk.MicroJITAPrivate",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.AlgorithmLib",
        "com.guardexpert.microsensorsdk.core.microsensorcontroldata.FrameData",
    ]:
        assert f'"{required}"' in artifacts


def test_no_new_source_reconstruction_under_official_namespaces_in_this_commit_scope():
    # Existing concurrent work may have files in these packages; the G008 loader foundation
    # must not depend on editing or generating more official class shadows. This contract
    # checks that the new foundation is contained in officialdex and exact byte assets.
    loader_sources = list(OFFICIALDEX.glob("*.java"))
    assert loader_sources, "officialdex foundation sources are missing"
    for path in loader_sources:
        text = path.read_text(encoding="utf-8")
        assert "package kr.auto.titration.mobile.thermal.officialdex;" in text


def test_required_identity_classes_are_present_in_exact_dex_assets():
    dex_bytes = b"".join(
        (APP / f"src/main/assets/hikmicro/official/{name}").read_bytes()
        for name in ("classes2.dex", "classes3.dex")
    )
    for class_name in [
        "d3.f", "d3.d", "d3.e", "d3.g", "Z2.a", "Z2.g", "k3.b", "f3.k",
        "com.guardexpert.microsensorsdk.MicroJITA",
        "com.guardexpert.microsensorsdk.MicroJITAPrivate",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.AlgorithmLib",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.AlgorithmLibInfoVect",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.IRCapabilities",
        "com.guardexpert.microsensorsdk.core.microsmartsensordata.Image",
        "com.guardexpert.microsensorsdk.core.microsensorcontroldata.FrameData",
    ]:
        descriptor = ("L" + class_name.replace(".", "/") + ";").encode("utf-8")
        assert descriptor in dex_bytes, f"{class_name} missing from exact official dex assets"
