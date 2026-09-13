import hashlib
import re
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "mobile/android/app/src/test/evidence/HIKMICRO_VIEWER_2_6_0_OFFICIAL_ARTIFACT_SHA256.tsv"
SOURCE_APK_HASHES = ROOT / ".omx/goals/autoresearch/hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti/evidence/hashes.txt"
PRODUCTION_CONSTANTS = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/officialdex/OfficialDexArtifacts.java"


@dataclass(frozen=True)
class ManifestEntry:
    line: int
    sha256: str
    official: Path
    bundled: Path
    role: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_entries() -> list[ManifestEntry]:
    entries: list[ManifestEntry] = []
    for line_no, raw_line in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line or raw_line.startswith("#"):
            continue
        columns = raw_line.split("\t")
        if len(columns) != 4:
            raise AssertionError(f"manifest line {line_no} must have four tab-separated columns: {raw_line!r}")
        expected_hash, official, bundled, role = columns
        entries.append(
            ManifestEntry(
                line=line_no,
                sha256=expected_hash,
                official=ROOT / official,
                bundled=ROOT / bundled,
                role=role,
            )
        )
    return entries


class G009OfficialArtifactManifestTests(unittest.TestCase):
    def test_manifest_is_line_backed_to_extracted_viewer_260_artifacts(self):
        self.assertTrue(SOURCE_APK_HASHES.is_file(), "official source APK hash evidence must exist")
        self.assertIn("HIKMICRO Viewer_2.6.0_APKPure.xapk", SOURCE_APK_HASHES.read_text(encoding="utf-8"))
        entries = manifest_entries()
        self.assertGreaterEqual(len(entries), 20)
        self.assertEqual(len(entries), len({entry.official.as_posix() for entry in entries}))
        self.assertEqual(len(entries), len({entry.bundled.as_posix() for entry in entries}))
        for entry in entries:
            with self.subTest(manifest_line=entry.line, role=entry.role):
                self.assertRegex(entry.sha256, r"^[0-9a-f]{64}$")
                self.assertTrue(entry.official.is_file(), f"missing official extraction artifact at line {entry.line}: {entry.official}")
                self.assertTrue(entry.bundled.is_file(), f"missing bundled app artifact at line {entry.line}: {entry.bundled}")
                self.assertTrue(entry.official.as_posix().find(".omx/goals/autoresearch/hikmicro-viewer-2-6-0") >= 0)

    def test_official_extraction_and_bundled_assets_match_manifest_hashes(self):
        for entry in manifest_entries():
            with self.subTest(manifest_line=entry.line, artifact=entry.bundled.name):
                self.assertEqual(entry.sha256, sha256(entry.official), f"official extraction hash mismatch at manifest line {entry.line}")
                self.assertEqual(entry.sha256, sha256(entry.bundled), f"bundled app hash mismatch at manifest line {entry.line}")

    def test_manifest_covers_dex_and_critical_f2_radiometric_native_surface(self):
        bundled_names = {entry.bundled.name for entry in manifest_entries()}
        self.assertEqual({"classes.dex", "classes2.dex", "classes3.dex", "classes4.dex"}, {name for name in bundled_names if name.startswith("classes")})
        for required in [
            "libHCUSBSDK.so",
            "libSJNI.so",
            "libMicroJITA_Release_v8a.so",
            "libMicroJPEG_Release_v8a.so",
            "libMicroTA_Release_v8a.so",
            "libMTlib.so",
            "libOfflinePic.so",
            "libOffline_Pic.so",
            "libanalyzer_rid.so",
            "libgyuv.so",
        ]:
            self.assertIn(required, bundled_names)

    def test_production_hash_constants_are_subset_of_manifest_not_the_source_of_truth(self):
        constants = PRODUCTION_CONSTANTS.read_text(encoding="utf-8")
        manifest_hashes = {entry.sha256 for entry in manifest_entries()}
        for constant_name in ["CLASSES_SHA256", "CLASSES2_SHA256", "CLASSES3_SHA256", "CLASSES4_SHA256", "NATIVE_LIBRARY_SHA256"]:
            with self.subTest(constant=constant_name):
                match = re.search(rf'{constant_name}\s*=\s*"([0-9a-f]{{64}})"', constants)
                self.assertIsNotNone(match)
                self.assertIn(match.group(1), manifest_hashes)


if __name__ == "__main__":
    unittest.main()
