import hashlib
import json
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "tools/hik_whole_apk/g007_public_export.py"
G007_STATUS = ".omx/research/hikmicro-viewer-2.6.0/specs/g007/status.json"
G007_README = ".omx/research/hikmicro-viewer-2.6.0/specs/g007/README.md"
G007_INDEX = ".omx/research/hikmicro-viewer-2.6.0/specs/g007/index.json"
G007_FIXTURES = (
    ".omx/research/hikmicro-viewer-2.6.0/reproduction/"
    "g007-fixtures-manifest.json"
)
OFFICIAL_HASHES = (
    ROOT
    / "mobile/android/app/src/test/evidence/"
    / "HIKMICRO_VIEWER_2_6_0_OFFICIAL_ARTIFACT_SHA256.tsv"
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical_json(value):
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(EXPORTER), *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def rewrite_archive(source, destination, transform):
    with zipfile.ZipFile(source, "r") as archive:
        entries = [(info, archive.read(info)) for info in archive.infolist()]
    entries = transform(entries)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for info, payload in entries:
            archive.writestr(info, payload)


class G007PublicExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="g007-public-export-")
        self.addCleanup(self.temporary.cleanup)
        self.temp = Path(self.temporary.name)
        self.archive = self.temp / "publication.zip"
        self.protected_bytes = {
            relative: (ROOT / relative).read_bytes()
            for relative in (
                G007_INDEX,
                G007_STATUS,
                G007_README,
                G007_FIXTURES,
                OFFICIAL_HASHES.relative_to(ROOT).as_posix(),
            )
        }
        result = run_cli("build", "--root", ROOT, "--archive", self.archive)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def validate(self, archive=None):
        return run_cli(
            "validate",
            "--root",
            ROOT,
            "--archive",
            archive or self.archive,
        )

    def test_two_builds_are_byte_identical_and_exact_clean_archive_validates(self):
        second = self.temp / "publication-second.zip"
        result = run_cli("build", "--root", ROOT, "--archive", second)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(sha256(self.archive.read_bytes()), sha256(second.read_bytes()))

        with zipfile.ZipFile(self.archive) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            manifest = json.loads(archive.read("PUBLICATION-MANIFEST.json"))
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), 68)
        self.assertEqual(manifest["payload_file_count"], 66)
        self.assertEqual(
            set(names),
            {"PUBLICATION-MANIFEST.json", "README.md"}
            | {row["path"] for row in manifest["files"]},
        )
        self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in infos))
        self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos))
        self.assertTrue(
            all((info.external_attr >> 16) == (stat.S_IFREG | 0o644) for info in infos)
        )

        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("68 archive entries", result.stdout)

    def test_official_bytes_are_rejected_even_when_renamed_to_a_canonical_path(self):
        row = next(
            line.split("\t")
            for line in OFFICIAL_HASHES.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        )
        official_bytes = (ROOT / row[2]).read_bytes()

        def transform(entries):
            manifest = json.loads(next(data for info, data in entries if info.filename == "PUBLICATION-MANIFEST.json"))
            target = next(item["path"] for item in manifest["files"] if item["path"] != "README.md")
            for item in manifest["files"]:
                if item["path"] == target:
                    item["sha256"] = sha256(official_bytes)
                    item["size_bytes"] = len(official_bytes)
            output = []
            for info, data in entries:
                if info.filename == target:
                    data = official_bytes
                elif info.filename == "PUBLICATION-MANIFEST.json":
                    data = json.dumps(
                        manifest,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode() + b"\n"
                output.append((info, data))
            return output

        mutated = self.temp / "official-renamed.zip"
        rewrite_archive(self.archive, mutated, transform)
        result = self.validate(mutated)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("official artifact bytes", result.stderr)

    def test_guarded_vendor_or_native_archive_path_is_rejected(self):
        def transform(entries):
            old = next(
                info.filename
                for info, _ in entries
                if info.filename.startswith(".omx/") and info.filename.endswith(".json")
            )
            guarded = "payload/com/hik/renamed-spec.json"
            manifest = json.loads(next(data for info, data in entries if info.filename == "PUBLICATION-MANIFEST.json"))
            for item in manifest["files"]:
                if item["path"] == old:
                    item["path"] = guarded
            output = []
            for info, data in entries:
                if info.filename == old:
                    replacement = zipfile.ZipInfo(guarded, info.date_time)
                    replacement.create_system = info.create_system
                    replacement.compress_type = info.compress_type
                    replacement.external_attr = info.external_attr
                    info = replacement
                elif info.filename == "PUBLICATION-MANIFEST.json":
                    data = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                output.append((info, data))
            return sorted(output, key=lambda row: row[0].filename)

        mutated = self.temp / "guarded.zip"
        rewrite_archive(self.archive, mutated, transform)
        result = self.validate(mutated)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("guarded vendor/native path", result.stderr)

    def test_traversal_duplicate_symlink_and_tampered_manifest_are_rejected(self):
        cases = {}

        def add_traversal(entries):
            info = zipfile.ZipInfo("../escape", (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            return entries + [(info, b"escape")]

        cases["traversal"] = (add_traversal, "unsafe")

        def add_duplicate(entries):
            return entries + [entries[-1]]

        cases["duplicate"] = (add_duplicate, "duplicate")

        def add_unicode_equivalent_duplicates(entries):
            additions = []
            for name in ("payload/caf\u00e9", "payload/cafe\u0301"):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                additions.append((info, b"same-normalized-name"))
            return entries + additions

        cases["unicode duplicate"] = (
            add_unicode_equivalent_duplicates,
            "duplicate",
        )

        def add_symlink(entries):
            info = zipfile.ZipInfo("payload-link", (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            return entries + [(info, b"README.md")]

        cases["symlink"] = (add_symlink, "symlink")

        def tamper_manifest(entries):
            output = []
            for info, data in entries:
                if info.filename == "PUBLICATION-MANIFEST.json":
                    manifest = json.loads(data)
                    manifest["files"][0]["sha256"] = "0" * 64
                    data = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                output.append((info, data))
            return output

        cases["manifest hash"] = (tamper_manifest, "manifest hash")

        def reorder_manifest_rows(entries):
            output = []
            for info, data in entries:
                if info.filename == "PUBLICATION-MANIFEST.json":
                    manifest = json.loads(data)
                    manifest["files"] = list(reversed(manifest["files"]))
                    data = json.dumps(
                        manifest,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode() + b"\n"
                output.append((info, data))
            return output

        cases["manifest order"] = (reorder_manifest_rows, "file rows are not sorted")

        for name, (transform, expected_error) in cases.items():
            with self.subTest(name=name):
                mutated = self.temp / f"{name.replace(' ', '-')}.zip"
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    rewrite_archive(self.archive, mutated, transform)
                result = self.validate(mutated)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(expected_error, result.stderr.lower())

    def test_coordinated_payload_and_manifest_tampering_is_rejected(self):
        target = ".omx/research/hikmicro-viewer-2.6.0/claims/index.json"

        def transform(entries):
            manifest = json.loads(
                next(
                    data
                    for info, data in entries
                    if info.filename == "PUBLICATION-MANIFEST.json"
                )
            )
            output = []
            for info, data in entries:
                if info.filename == target:
                    payload = json.loads(data)
                    payload["_coordinated_tampering"] = True
                    data = canonical_json(payload)
                    row = next(item for item in manifest["files"] if item["path"] == target)
                    row["sha256"] = sha256(data)
                    row["size_bytes"] = len(data)
                output.append((info, data))
            for number, (info, data) in enumerate(output):
                if info.filename == "PUBLICATION-MANIFEST.json":
                    output[number] = (info, canonical_json(manifest))
            return output

        mutated = self.temp / "coordinated-payload-tampering.zip"
        rewrite_archive(self.archive, mutated, transform)
        result = self.validate(mutated)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("differs from canonical repository bytes", result.stderr)

    def test_noncanonical_zip_trailer_and_version_metadata_are_rejected(self):
        trailer = self.temp / "trailing-hidden-bytes.zip"
        trailer.write_bytes(self.archive.read_bytes() + b"HIDDEN_VENDOR_BYTES")
        result = self.validate(trailer)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("exact deterministic canonical serialization", result.stderr)

        def mutate_version(entries):
            info, data = entries[0]
            info.create_version = 63
            info.extract_version = 63
            info.reserved = 1
            return [(info, data), *entries[1:]]

        versioned = self.temp / "noncanonical-version-metadata.zip"
        rewrite_archive(self.archive, versioned, mutate_version)
        result = self.validate(versioned)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("exact deterministic canonical serialization", result.stderr)

    def test_public_nonclaim_readme_cannot_be_rewritten_with_matching_manifest(self):
        def transform(entries):
            manifest = json.loads(
                next(
                    data
                    for info, data in entries
                    if info.filename == "PUBLICATION-MANIFEST.json"
                )
            )
            output = []
            for info, data in entries:
                if info.filename == "README.md":
                    data = data.replace(
                        b"It does not claim live F2 execution",
                        b"It claims live F2 execution",
                    )
                    row = next(
                        item for item in manifest["files"] if item["path"] == "README.md"
                    )
                    row["sha256"] = sha256(data)
                    row["size_bytes"] = len(data)
                output.append((info, data))
            for number, (info, data) in enumerate(output):
                if info.filename == "PUBLICATION-MANIFEST.json":
                    output[number] = (info, canonical_json(manifest))
            return output

        mutated = self.temp / "rewritten-public-nonclaims.zip"
        rewrite_archive(self.archive, mutated, transform)
        result = self.validate(mutated)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("README.md scope/nonclaims text is not exact", result.stderr)

    def test_nonterminal_claims_are_preserved_and_private_tree_is_untouched(self):
        with zipfile.ZipFile(self.archive) as archive:
            manifest = json.loads(archive.read("PUBLICATION-MANIFEST.json"))
            status = json.loads(archive.read(G007_STATUS))
            archived_readme = archive.read(G007_README)
            public_readme = archive.read("README.md").decode("utf-8")

        self.assertEqual(status["g008_execution"], "pending")
        self.assertTrue(all(value == [] for value in status["terminal_claims"].values()))
        self.assertEqual(archived_readme, (ROOT / G007_README).read_bytes())
        self.assertIn("does not claim live F2", public_readme)
        self.assertIn("does not grant redistribution authority", public_readme)
        self.assertEqual(
            manifest["nonclaims"],
            [
                "No live F2 execution or hardware result is claimed.",
                "No radiometric or Celsius result is claimed.",
                "No Android application build is included or claimed.",
                "No redistribution authority is granted or claimed.",
            ],
        )
        for row in manifest["files"]:
            if row["path"] == "README.md":
                continue
            source = ROOT / row["path"]
            self.assertTrue(source.is_file(), row["path"])
            self.assertEqual(sha256(source.read_bytes()), row["sha256"], row["path"])
        self.assertEqual(
            self.protected_bytes,
            {
                relative: (ROOT / relative).read_bytes()
                for relative in self.protected_bytes
            },
        )

    def test_cli_requires_absolute_root_and_archive_and_keeps_output_outside_root(self):
        for args in (
            ("build", "--root", ".", "--archive", self.temp / "relative-root.zip"),
            ("build", "--root", ROOT, "--archive", Path("relative.zip")),
            ("build", "--root", ROOT, "--archive", ROOT / "unsafe-output.zip"),
        ):
            with self.subTest(args=args):
                result = run_cli(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("absolute" if "." in map(str, args) or "relative.zip" in map(str, args) else "outside", result.stderr)

    def test_cli_rejects_symlinked_root_archive_parent_and_archive_leaf(self):
        root_link = self.temp / "root-link"
        root_link.symlink_to(ROOT, target_is_directory=True)
        result = run_cli(
            "build",
            "--root",
            root_link,
            "--archive",
            self.temp / "root-link-output.zip",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlinked path component", result.stderr)

        real_parent = self.temp / "real-parent"
        real_parent.mkdir()
        parent_link = self.temp / "parent-link"
        parent_link.symlink_to(real_parent, target_is_directory=True)
        result = run_cli(
            "build",
            "--root",
            ROOT,
            "--archive",
            parent_link / "parent-link-output.zip",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlinked path component", result.stderr)

        archive_link = self.temp / "archive-link.zip"
        archive_link.symlink_to(self.archive)
        result = self.validate(archive_link)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-symlink regular ZIP file", result.stderr)


if __name__ == "__main__":
    unittest.main()
