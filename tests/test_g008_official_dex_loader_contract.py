from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "mobile/android/app"
OFFICIALDEX = APP / "src/main/java/kr/auto/titration/mobile/thermal/officialdex"

EXPECTED = {
    APP / "src/main/assets/hikmicro/official/classes.dex": "2bd1971bc914fc5a35084137ec97274bd69316403f020f52995526ab77019e20",
    APP / "src/main/assets/hikmicro/official/classes2.dex": "da26f34a40e4ac87b4a318174c49d1da2fef53caea95a2ceb30a3184ea9307ad",
    APP / "src/main/assets/hikmicro/official/classes3.dex": "f360bb57acbfb5cdad1fb2cf63ef90498c146383283e1989f1747a387443d6ff",
    APP / "src/main/assets/hikmicro/official/classes4.dex": "d40331731cb6731e208bc92815b970e51fc69c25a904b29d1616d9cd3ca57fd9",
    APP / "src/main/jniLibs/arm64-v8a/libSJNI.so": "698b60ea4cb6eccf8cd9570d6bbf6aac246f145661629d0ba938e5f02345fee8",
}

REQUIRED_IDENTITY_CLASSES = [
    "d3.f", "d3.d", "d3.e", "d3.g", "Z2.a", "Z2.g", "k3.b", "f3.k",
    "com.hik.f2module.IFR_INFO$OFFLINE_TEMP_MEASURE_CFG",
    "com.hikmicro.analyzer.sdk.palette.bean.PaletteBean",
    "hik.common.yyrj.uicommon.data.ModuleType",
    "com.hikvision.microjita.AnalyzerII",
    "com.hikvision.microjita.bean.AnalyzerInfoPic",
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
    "com.guardexpert.microsensorsdk.core.microsensorcontroldata.FrameData",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name: str) -> str:
    return (OFFICIALDEX / name).read_text(encoding="utf-8")


def dex_descriptor(class_name: str) -> bytes:
    return ("L" + class_name.replace(".", "/") + ";").encode("utf-8")


def all_exact_dex_bytes() -> bytes:
    return b"".join(
        (APP / f"src/main/assets/hikmicro/official/{name}").read_bytes()
        for name in ("classes.dex", "classes2.dex", "classes3.dex", "classes4.dex")
    )


def test_exact_official_assets_and_native_hashes():
    for path, expected in EXPECTED.items():
        assert path.is_file(), f"missing official artifact {path}"
        assert sha256(path) == expected


def test_all_supplied_dex_assets_are_packaged_in_apk_order():
    artifacts = read("OfficialDexArtifacts.java")
    ordered = [
        'new DexAsset(CLASSES_ASSET, "classes.dex", CLASSES_SHA256)',
        'new DexAsset(CLASSES2_ASSET, "classes2.dex", CLASSES2_SHA256)',
        'new DexAsset(CLASSES3_ASSET, "classes3.dex", CLASSES3_SHA256)',
        'new DexAsset(CLASSES4_ASSET, "classes4.dex", CLASSES4_SHA256)',
    ]
    positions = [artifacts.index(item) for item in ordered]
    assert positions == sorted(positions)


def test_loader_documents_and_enforces_no_reassembly_foundation():
    artifacts = read("OfficialDexArtifacts.java")
    assert "Keep these as verbatim APK bytes" in artifacts
    assert "do not D8, smali-reassemble, decompile" in artifacts
    assert all(token in artifacts for token in ["CLASSES_ASSET", "CLASSES2_ASSET", "CLASSES3_ASSET", "CLASSES4_ASSET"])

    scoped_sources = "\n".join(path.read_text(encoding="utf-8") for path in OFFICIALDEX.glob("*.java"))
    assert "DexClassLoader" in scoped_sources
    assert "getApplicationInfo().nativeLibraryDir" in scoped_sources
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


def test_dedicated_loader_is_child_first_for_every_non_runtime_class():
    class_loader = read("OfficialDexClassLoader.java")
    assert "if (isParentFirst(name))" in class_loader
    assert "loaded = findClass(name);" in class_loader
    assert "loaded = super.loadClass(name, false);" in class_loader
    assert "isRequiredOfficialIdentityClass(name)" in class_loader
    assert re.search(r"if \(isRequiredOfficialIdentityClass\(name\)\) \{\s*throw officialMissing;\s*\}", class_loader)
    assert "OFFICIAL_CHILD_FIRST_PREFIXES" not in read("OfficialDexArtifacts.java")
    assert "isChildFirst" in class_loader and "return !isParentFirst(className);" in class_loader


def test_required_identity_classes_cover_entry_path_transitives_and_are_declared():
    artifacts = read("OfficialDexArtifacts.java")
    for required in REQUIRED_IDENTITY_CLASSES:
        assert f'"{required}"' in artifacts


def test_required_identity_classes_are_present_in_exact_four_dex_assets():
    dex_bytes = all_exact_dex_bytes()
    for class_name in REQUIRED_IDENTITY_CLASSES:
        assert dex_descriptor(class_name) in dex_bytes, f"{class_name} missing from exact official dex assets"


def test_classes_dex_and_classes4_are_not_redundantly_omitted():
    # classes.dex carries com/hikvision/microjita support such as MicroJITAUtil;
    # classes4.dex is supplied official bytecode and is included to avoid masking
    # unresolved call-graph dependencies with parent shadows.
    assert dex_descriptor("com.hikvision.microjita.util.MicroJITAUtil") in all_exact_dex_bytes()
    assert EXPECTED[APP / "src/main/assets/hikmicro/official/classes.dex"] == "2bd1971bc914fc5a35084137ec97274bd69316403f020f52995526ab77019e20"
    assert EXPECTED[APP / "src/main/assets/hikmicro/official/classes4.dex"] == "d40331731cb6731e208bc92815b970e51fc69c25a904b29d1616d9cd3ca57fd9"


def test_no_new_source_reconstruction_under_official_namespaces_in_this_commit_scope():
    loader_sources = list(OFFICIALDEX.glob("*.java"))
    assert loader_sources, "officialdex foundation sources are missing"
    for path in loader_sources:
        text = path.read_text(encoding="utf-8")
        assert "package kr.auto.titration.mobile.thermal.officialdex;" in text
