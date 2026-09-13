import errno
import hashlib
import importlib.util
import io
import json
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
import tracemalloc
import types
import unittest
import warnings
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "tools/hik_whole_apk/g012_history_remediation.py"
AUDITED_FILTER_REPO = Path(
    os.environ.get(
        "G012_FILTER_REPO_TOOL",
        "/home/jio/g012-history-remediation/"
        "audited-tools/git-filter-repo-v2.47.0",
    )
).resolve()
AUDITED_FILTER_REPO_SHA256 = (
    "67447413e273fc76809289111748870b6f6072f08b17efe94863a92d810b7d94"
)
ACCEPTED_G007_ARCHIVE = Path(
    os.environ.get(
        "G012_G007_ARCHIVE",
        "/home/jio/public_exports/"
        "AutoTitration-G007-clean-room-public-spec-20260730.zip",
    )
).resolve()
ACCEPTED_G007_ARCHIVE_SHA256 = (
    "796ce4db130862f7ffa726f5e28b3a94d30c4fd5dc3209bc4a8e0be1239a8d97"
)

SPEC = importlib.util.spec_from_file_location("g012_history_remediation", PROGRAM)
G012 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = G012
SPEC.loader.exec_module(G012)


def run(command, *, cwd=None, env=None, input_bytes=None, check=True):
    completed = subprocess.run(
        [str(part) for part in command],
        cwd=cwd,
        env=env,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode:
        raise AssertionError(
            f"command failed: {command!r}\n"
            f"stdout={completed.stdout.decode('utf-8', 'replace')}\n"
            f"stderr={completed.stderr.decode('utf-8', 'replace')}"
        )
    return completed


def git(repo, *args, env=None, input_bytes=None, check=True):
    return run(
        ["git", "-C", repo, *args],
        env=env,
        input_bytes=input_bytes,
        check=check,
    )


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_bytes(payload)


class G012HistoryRemediationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not AUDITED_FILTER_REPO.is_file():
            raise AssertionError(
                f"required audited git-filter-repo is unavailable: "
                f"{AUDITED_FILTER_REPO}"
            )
        actual = hashlib.sha256(AUDITED_FILTER_REPO.read_bytes()).hexdigest()
        if actual != AUDITED_FILTER_REPO_SHA256:
            raise AssertionError(
                f"audited git-filter-repo hash mismatch: {actual}"
            )

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.source = self.base / "source"
        self.run_root = self.base / "run"
        self.denied_payload = b"official-exact-binary-payload\x00\x01"
        self.denied_sha256 = hashlib.sha256(self.denied_payload).hexdigest()
        self._make_source()

    def tearDown(self):
        self.temporary.cleanup()

    def _make_source(self):
        self.source.mkdir()
        git(self.source, "init", "-b", "main")
        git(self.source, "config", "user.name", "G012 Test")
        git(self.source, "config", "user.email", "g012@example.invalid")

        authority_only = {
            "apk_member": hashlib.sha256(b"authority-apk-member").hexdigest(),
            "native_library": hashlib.sha256(b"authority-native-library").hexdigest(),
            "dex": hashlib.sha256(b"authority-dex").hexdigest(),
        }
        official = {
            "artifact_set_id": "synthetic-g012-test",
            "artifacts": [
                {
                    "artifact_id": "denied-test-blob",
                    "kind": "official_fixture",
                    "sha256": self.denied_sha256,
                    "size_bytes": len(self.denied_payload),
                },
                *[
                    {
                        "artifact_id": f"authority-{kind}",
                        "kind": kind,
                        "sha256": digest,
                        "size_bytes": 1,
                    }
                    for kind, digest in authority_only.items()
                ],
            ],
            "expected_counts": {
                "apk_members": 1,
                "arm64_native_libraries_in_extracted_base": 1,
                "dex_files_in_extracted_base": 1,
                "known_official_fixtures": 1,
            },
            "observed_counts_by_kind": {
                "apk_member": 1,
                "native_library": 1,
                "dex": 1,
                "official_fixture": 1,
            },
        }
        write(
            self.source
            / ".omx/research/hikmicro-viewer-2.6.0/governance/official-artifacts.json",
            json.dumps(official),
        )
        write(
            self.source
            / "mobile/android/app/src/test/evidence/"
            "HIKMICRO_VIEWER_2_6_0_OFFICIAL_ARTIFACT_SHA256.tsv",
            (
                "# sha256\tofficial_extraction_path\tbundled_app_path\trole\n"
                f"{self.denied_sha256}\t"
                ".omx/private/apk/lib/arm64-v8a/libDenied.so\t"
                "mobile/android/app/src/main/jniLibs/arm64-v8a/libDenied.so\t"
                "synthetic denied artifact\n"
            ),
        )
        write(
            self.source
            / ".omx/research/hikmicro-viewer-2.6.0/governance/clean-room-policy.md",
            """# Clean-room policy

## Prohibited promotion
Decompiler output, smali, disassembly, proprietary source bodies, copied
control flow, unredacted secrets, and vendor binaries remain local.
""",
        )
        write(
            self.source
            / ".omx/research/hikmicro-viewer-2.6.0/governance/authorization-scope.md",
            """# Authorization scope

## Separate authorization gates
Public distribution is separately authorized. Official evidence must stay local.
""",
        )
        write(
            self.source / "tools/hik_whole_apk/g007_public_export.py",
            "GUARDED_PATH_PARTS = "
            "(('assets', 'hikmicro', 'official'), ('com', 'hcusbsdk'), "
            "('com', 'hik'), ('com', 'hikmicro'), ('hik', 'common'), "
            "('src', 'main', 'jniLibs'))\n",
        )
        write(
            self.source / "tools/hik_whole_apk/g007_spec_validator.py",
            (
                "import re\n"
                "PROHIBITED_SOURCE_RE = re.compile("
                "r'(?is)(\\bjadx\\b|\\bsmali\\b|\\.method\\s|"
                "package\\s+com\\.hik|decompil(?:ed|er|ation))')\n"
            ),
        )
        write(self.source / "safe.txt", "safe root file\n")
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "canonical synthetic authorities")

    def _commit_positive_history(self):
        write(
            self.source / "vendor/hikmicro_analyzer/native/secret.bin",
            b"guarded by family",
        )
        write(self.source / "copied-under-safe-name.bin", b"guarded by family")
        write(self.source / "innocent-name.bin", self.denied_payload)
        write(self.source / "notes/leak.txt", "jadx decompiled source listing\n")
        write(self.source / "safe-main.txt", "safe main history\n")
        write(self.source / "safe-magic.bin", b"\x7fELFsynthetic-safe-content")
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "mixed safe and prohibited history")
        git(self.source, "tag", "-a", "release-before-cleanup", "-m", "annotated")

        git(self.source, "switch", "-c", "feature")
        write(
            self.source
            / "mobile/android/app/src/test/resources/f2fixtures/frame.bin",
            b"guarded fixture",
        )
        write(
            self.source / "_workspace/hikmicro-analysis/private.txt",
            "guarded workspace\n",
        )
        write(self.source / "feature-safe.txt", "safe feature\n")
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "feature guarded families")
        git(self.source, "tag", "feature-tag")
        git(self.source, "switch", "main")

    def _configure_real_alternate(self, *, internal=False):
        alternate = (
            self.source / ".git/g012-internal-alternate.git"
            if internal
            else self.base / "alternate.git"
        )
        run(
            [
                "git",
                "clone",
                "--bare",
                "--no-hardlinks",
                self.source,
                alternate,
            ]
        )
        objects = Path(
            git(self.source, "rev-parse", "--git-path", "objects")
            .stdout.decode()
            .strip()
        )
        if not objects.is_absolute():
            objects = self.source / objects
        alternates = objects / "info" / "alternates"
        write(alternates, str((alternate / "objects").resolve()) + "\n")
        object_ids = git(
            self.source, "rev-list", "--objects", "--all"
        ).stdout.decode().splitlines()
        for row in object_ids:
            oid = row.split(" ", 1)[0]
            loose = objects / oid[:2] / oid[2:]
            if loose.is_file():
                loose.unlink()
        git(self.source, "fsck", "--full", "--strict")
        return alternate, alternates

    def _accepted_g007_bytes(self):
        if not ACCEPTED_G007_ARCHIVE.is_file():
            self.fail(
                "required accepted G007 archive unavailable; "
                f"set G012_G007_ARCHIVE (looked at {ACCEPTED_G007_ARCHIVE})"
            )
        payload = ACCEPTED_G007_ARCHIVE.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        self.assertEqual(ACCEPTED_G007_ARCHIVE_SHA256, actual)
        return payload

    def _g007_policy(self):
        return {
            "deny_sha256": [self.denied_sha256],
            "exact_guarded_paths": [],
            "family_parts": [
                list(parts) for parts in G012.MANDATORY_FAMILY_PARTS
            ],
            "root_globs": list(G012.MANDATORY_ROOT_GLOBS),
            "prohibited_source_regex": (
                r"(?is)(\bjadx\b|\bsmali\b|\.method\s|"
                r"package\s+com\.hik|decompil(?:ed|er|ation))"
            ),
        }

    def _g007_entries(self):
        payload = self._accepted_g007_bytes()
        with zipfile.ZipFile(io.BytesIO(payload), "r") as handle:
            return [
                {
                    "name": info.filename,
                    "payload": handle.read(info),
                    "mode": (info.external_attr >> 16) & 0o177777,
                }
                for info in handle.infolist()
            ]

    def _write_g007_variant(
        self,
        name,
        entries,
        *,
        timestamp=(1980, 1, 1, 0, 0, 0),
    ):
        archive = self.base / name
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(
                archive,
                "w",
                compression=zipfile.ZIP_STORED,
            ) as handle:
                for row in entries:
                    info = zipfile.ZipInfo(row["name"], timestamp)
                    info.create_system = 3
                    info.external_attr = row["mode"] << 16
                    info.compress_type = zipfile.ZIP_STORED
                    handle.writestr(info, row["payload"])
        return archive

    def _replace_g007_payload(self, entries, path, payload):
        result = [dict(row) for row in entries]
        for row in result:
            if row["name"] == path:
                row["payload"] = payload
                return result
        raise AssertionError(f"missing accepted G007 member: {path}")

    def _coordinate_g007_manifest(self, entries, path, payload):
        result = self._replace_g007_payload(entries, path, payload)
        manifest_row = next(
            row
            for row in result
            if row["name"] == G012.G007_PUBLICATION_MANIFEST_NAME
        )
        manifest = json.loads(manifest_row["payload"].decode("utf-8"))
        file_row = next(row for row in manifest["files"] if row["path"] == path)
        file_row["sha256"] = hashlib.sha256(payload).hexdigest()
        file_row["size_bytes"] = len(payload)
        manifest_row["payload"] = (
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        return result

    def _preserve_g007_for_test(self, archive):
        target = self.base / "g007-validation-run"
        target.mkdir(exist_ok=True)
        return G012._preserve_g007_archive(
            self.source,
            str(Path(archive).resolve()),
            target,
            self._g007_policy(),
        )

    def _quarantine_race_injector(
        self,
        leaf_name,
        displaced_name,
        install_substitute,
        *,
        before_restore=None,
    ):
        real_rename = G012._rename_noreplace
        state = {"candidate_swapped": False, "restore_interposed": False}

        def inject(source_fd, source_name, destination_fd, destination_name):
            if (
                not state["candidate_swapped"]
                and source_name == leaf_name
                and destination_name.startswith(".g012-quarantine-")
            ):
                state["candidate_swapped"] = True
                os.rename(
                    leaf_name,
                    displaced_name,
                    src_dir_fd=source_fd,
                    dst_dir_fd=source_fd,
                )
                install_substitute(source_fd, leaf_name)
            elif (
                before_restore is not None
                and state["candidate_swapped"]
                and not state["restore_interposed"]
                and source_name.startswith(".g012-quarantine-")
                and destination_name == leaf_name
            ):
                state["restore_interposed"] = True
                before_restore(destination_fd, leaf_name)
            return real_rename(
                source_fd,
                source_name,
                destination_fd,
                destination_name,
            )

        return state, inject

    def _resign_run_artifacts(self, mutator):
        run_manifest_path = self.run_root / "manifests/run-manifest.json"
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        mutator(run_manifest)
        run_manifest_path.write_bytes(G012._canonical_json(run_manifest))
        rows = []
        for relative in sorted(run_manifest["sha256_manifest_paths"]):
            payload = (self.run_root / relative).read_bytes()
            rows.append(f"{hashlib.sha256(payload).hexdigest()}  {relative}")
        (self.run_root / "SHA256SUMS").write_text(
            "\n".join(rows) + "\n",
            encoding="utf-8",
        )

    def _dry_run(self, *, tool=AUDITED_FILTER_REPO, extra=None, env=None):
        command = [
            sys.executable,
            PROGRAM,
            "dry-run",
            "--source",
            self.source.resolve(),
            "--run-root",
            self.run_root.absolute(),
            "--filter-repo-tool",
            Path(tool).resolve(),
        ]
        if extra:
            command.extend(extra)
        return run(command, env=env, check=False)

    def test_removes_guarded_hash_and_content_across_branches_and_tags(self):
        self._commit_positive_history()
        before_source = git(self.source, "show-ref").stdout
        guarded_oid = git(
            self.source, "rev-parse", "HEAD:vendor/hikmicro_analyzer/native/secret.bin"
        ).stdout.decode().strip()

        completed = self._dry_run()
        self.assertEqual(
            0, completed.returncode, completed.stderr.decode("utf-8", "replace")
        )
        mirror = self.run_root / "disposable-mirror.git"
        for ref in (
            "refs/heads/main",
            "refs/heads/feature",
            "refs/tags/release-before-cleanup",
            "refs/tags/feature-tag",
        ):
            self.assertEqual(
                0, git(mirror, "rev-parse", "--verify", ref, check=False).returncode
            )

        prohibited_paths = (
            "vendor/hikmicro_analyzer/native/secret.bin",
            "mobile/android/app/src/test/resources/f2fixtures/frame.bin",
            "_workspace/hikmicro-analysis/private.txt",
            "innocent-name.bin",
            "notes/leak.txt",
            "copied-under-safe-name.bin",
        )
        for ref in ("refs/heads/main", "refs/heads/feature"):
            history = git(mirror, "log", ref, "--format=", "--name-only").stdout.decode()
            for path in prohibited_paths:
                self.assertNotIn(path, history)
        self.assertEqual(
            b"safe root file\n",
            git(mirror, "show", "refs/heads/main:safe.txt").stdout,
        )
        self.assertEqual(
            b"\x7fELFsynthetic-safe-content",
            git(mirror, "show", "refs/heads/main:safe-magic.bin").stdout,
        )
        self.assertEqual(
            b"safe feature\n",
            git(mirror, "show", "refs/heads/feature:feature-safe.txt").stdout,
        )
        self.assertNotEqual(
            0,
            git(mirror, "cat-file", "-e", guarded_oid, check=False).returncode,
        )
        self.assertNotEqual(
            0,
            git(
                self.run_root / "independent-sanitized.git",
                "cat-file",
                "-e",
                guarded_oid,
                check=False,
            ).returncode,
        )
        self.assertEqual(before_source, git(self.source, "show-ref").stdout)

        manifest = json.loads(
            (self.run_root / "manifests/run-manifest.json").read_text()
        )
        self.assertTrue(manifest["completed"])
        self.assertFalse(manifest["rewrite_invocation"]["network_allowed"])
        self.assertFalse(manifest["rewrite_invocation"]["push_performed"])
        self.assertEqual(
            AUDITED_FILTER_REPO_SHA256, manifest["filter_repo"]["sha256"]
        )
        self.assertIn(
            "filter-repo-commit-map.txt", manifest["filter_repo_mapping_files"]
        )
        self.assertIn("filter-repo-ref-map.txt", manifest["filter_repo_mapping_files"])
        self.assertTrue((self.run_root / "rollback-before.bundle").is_file())
        self.assertTrue((self.run_root / "rewritten-sanitized.bundle").is_file())
        self.assertTrue((self.run_root / "SHA256SUMS").is_file())
        restored = self.base / "rollback-restored.git"
        run(
            [
                "git",
                "clone",
                "--mirror",
                self.run_root / "rollback-before.bundle",
                restored,
            ]
        )
        expected_refs = {
            line.split("\t")[0]: line.split("\t")[1]
            for line in (self.run_root / "refs-before.tsv").read_text().splitlines()[1:]
        }
        restored_refs = {
            line.split(" ", 1)[1]: line.split(" ", 1)[0]
            for line in git(restored, "show-ref").stdout.decode().splitlines()
        }
        self.assertEqual(expected_refs, restored_refs)
        verification = json.loads(
            (self.run_root / "manifests/verification.json").read_text()
        )
        self.assertTrue(verification["ok"])

    def test_refuses_source_run_root_overlap(self):
        nested = self.source / "unsafe-run"
        completed = run(
            [
                sys.executable,
                PROGRAM,
                "dry-run",
                "--source",
                self.source.resolve(),
                "--run-root",
                nested.resolve(),
                "--filter-repo-tool",
                AUDITED_FILTER_REPO,
            ],
            check=False,
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn(b"overlaps source repository", completed.stderr)
        self.assertFalse(nested.exists())

    def test_rejects_separate_git_dir_before_run_root_creation(self):
        worktree = self.base / "separate-worktree"
        admin = self.base / "separate-admin"
        run(["git", "init", "--separate-git-dir", admin, worktree])
        git(worktree, "config", "user.name", "G012 Test")
        git(worktree, "config", "user.email", "g012@example.invalid")
        write(worktree / "tracked.txt", "tracked\n")
        git(worktree, "add", ".")
        git(worktree, "commit", "-m", "initial")
        completed = run(
            [
                sys.executable,
                PROGRAM,
                "dry-run",
                "--source",
                worktree.resolve(),
                "--run-root",
                self.run_root.resolve(),
                "--filter-repo-tool",
                AUDITED_FILTER_REPO,
            ],
            check=False,
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn(b"outside the lifetime-anchored source worktree", completed.stderr)
        self.assertFalse(self.run_root.exists())

    def test_separate_git_dir_aba_swap_still_rejects_external_admin(self):
        worktree = self.base / "separate-aba-worktree"
        admin = self.base / "separate-aba-admin"
        moved_admin = self.base / "separate-aba-admin-held"
        attacker_admin = self.base / "separate-aba-attacker.git"
        run(["git", "init", "--separate-git-dir", admin, worktree])
        run(["git", "init", "--bare", attacker_admin])
        actual_git = G012._git
        swapped = False

        def swap_after_common_dir(repo, *arguments, **kwargs):
            nonlocal swapped
            result = actual_git(repo, *arguments, **kwargs)
            if (
                not swapped
                and arguments
                == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-common-dir",
                )
            ):
                swapped = True
                admin.rename(moved_admin)
                admin.symlink_to(attacker_admin, target_is_directory=True)
            return result

        try:
            with mock.patch.object(
                G012,
                "_git",
                side_effect=swap_after_common_dir,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "outside the lifetime-anchored source worktree",
                ):
                    G012._resolve_repository(str(worktree.resolve()))
            self.assertTrue(swapped)
        finally:
            if admin.is_symlink():
                admin.unlink()
            if moved_admin.exists():
                moved_admin.rename(admin)

    def test_refuses_missing_or_mismatched_filter_repo(self):
        missing = self.base / "missing-filter-repo"
        completed = self._dry_run(tool=missing)
        self.assertEqual(2, completed.returncode)
        self.assertIn(b"filter-repo-tool", completed.stderr)

        self.run_root = self.base / "run-fake-tool"
        fake = self.base / "fake-filter-repo"
        write(fake, "#!/usr/bin/env python3\n")
        fake.chmod(0o755)
        completed = self._dry_run(tool=fake)
        self.assertEqual(2, completed.returncode)
        self.assertIn(b"SHA256 mismatch", completed.stderr)

    def test_hostile_remote_is_never_contacted_and_source_is_unchanged(self):
        self._commit_positive_history()
        marker = self.base / "network-contact-marker"
        hostile = self.base / "hostile-ssh"
        write(
            hostile,
            f"#!/bin/sh\nprintf contacted > {marker}\nexit 97\n",
        )
        hostile.chmod(0o755)
        git(
            self.source,
            "remote",
            "add",
            "hostile",
            "ssh://example.invalid/never/contact.git",
        )
        before = git(self.source, "config", "--local", "--list").stdout
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = str(hostile)
        hostile_repo = self.base / "hostile-routing.git"
        git(self.base, "init", "--bare", hostile_repo)
        hostile_index = self.base / "hostile.index"
        hostile_objects = hostile_repo / "objects"
        hostile_global = self.base / "hostile-global-config"
        write(
            hostile_global,
            "[url \"ssh://example.invalid/\"]\n\tinsteadOf = file://\n",
        )
        env.update(
            {
                "GIT_DIR": str(hostile_repo),
                "GIT_WORK_TREE": str(self.base),
                "GIT_INDEX_FILE": str(hostile_index),
                "GIT_OBJECT_DIRECTORY": str(hostile_objects),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(hostile_objects),
                "GIT_COMMON_DIR": str(hostile_repo),
                "GIT_CONFIG_GLOBAL": str(hostile_global),
                "GIT_CONFIG_SYSTEM": str(hostile_global),
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.hooksPath",
                "GIT_CONFIG_VALUE_0": str(self.base / "hostile-hooks"),
            }
        )
        hostile_before = sorted(path.relative_to(hostile_repo) for path in hostile_repo.rglob("*"))

        completed = self._dry_run(env=env)
        self.assertEqual(
            0, completed.returncode, completed.stderr.decode("utf-8", "replace")
        )
        self.assertFalse(marker.exists())
        self.assertFalse(hostile_index.exists())
        self.assertEqual(
            hostile_before,
            sorted(path.relative_to(hostile_repo) for path in hostile_repo.rglob("*")),
        )
        self.assertEqual(before, git(self.source, "config", "--local", "--list").stdout)
        runbook = (self.run_root / "FORCE-PUSH-RUNBOOK.md").read_text()
        self.assertNotIn("git push", runbook)

    def test_external_alternate_is_rejected_before_run_root_creation(self):
        alternate, _alternates_file = self._configure_real_alternate()
        with self.assertRaisesRegex(
            G012.RemediationError,
            "alternate Git object store is outside the lifetime-anchored",
        ):
            G012._resolve_repository(str(self.source.resolve()))
        completed = self._dry_run()
        self.assertEqual(2, completed.returncode)
        self.assertIn(
            b"alternate Git object store is outside the lifetime-anchored",
            completed.stderr,
        )
        self.assertFalse(self.run_root.exists())
        self.assertTrue((alternate / "objects").is_dir())

    def test_external_alternate_aba_swap_is_rejected_before_store_open(self):
        alternate, alternates_file = self._configure_real_alternate()
        moved = self.base / "alternate-held.git"
        attacker = self.base / "alternate-attacker.git"
        run(["git", "init", "--bare", attacker])
        actual_read = G012._read_regular
        swapped = False

        def swap_after_alternates_read(path, *args, **kwargs):
            nonlocal swapped
            payload = actual_read(path, *args, **kwargs)
            if not swapped and path == alternates_file:
                swapped = True
                alternate.rename(moved)
                alternate.symlink_to(attacker, target_is_directory=True)
            return payload

        try:
            with mock.patch.object(
                G012,
                "_read_regular",
                side_effect=swap_after_alternates_read,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "alternate Git object store is outside the lifetime-anchored",
                ):
                    G012._resolve_repository(str(self.source.resolve()))
            self.assertTrue(swapped)
        finally:
            if alternate.is_symlink():
                alternate.unlink()
            if moved.exists():
                moved.rename(alternate)

    def test_source_local_fsmonitor_hooks_and_hidden_refs_are_neutralized(self):
        marker = self.base / "local-config-executed"
        executable = self.base / "malicious-local-config.sh"
        write(
            executable,
            f"#!/bin/sh\nprintf executed >> {marker}\nexit 99\n",
        )
        executable.chmod(0o755)
        hooks = self.base / "malicious-hooks"
        hooks.mkdir()
        for name in ("post-checkout", "post-index-change", "reference-transaction"):
            hook = hooks / name
            write(hook, f"#!/bin/sh\nprintf {name} >> {marker}\nexit 99\n")
            hook.chmod(0o755)
        hidden_ref = "refs/hidden/review-only"
        git(self.source, "update-ref", hidden_ref, "HEAD")
        git(self.source, "config", "core.fsmonitor", str(executable))
        git(self.source, "config", "core.hooksPath", str(hooks))
        git(self.source, "config", "filter.malicious.process", str(executable))
        git(self.source, "config", "filter.malicious.required", "true")
        git(self.source, "config", "diff.malicious.textconv", str(executable))
        write(self.source / ".gitattributes", "* filter=malicious diff=malicious\n")
        git(self.source, "config", "--add", "transfer.hideRefs", "refs/hidden")
        git(self.source, "config", "--add", "uploadpack.hideRefs", "refs/hidden")

        completed = self._dry_run()
        self.assertEqual(
            0, completed.returncode, completed.stderr.decode("utf-8", "replace")
        )
        self.assertFalse(marker.exists())
        refs_before = G012._read_refs(self.run_root / "refs-before.tsv")
        self.assertIn(hidden_ref, {row["ref"] for row in refs_before})
        self.assertNotIn(
            "refs/g012-captured/head-0",
            {row["ref"] for row in refs_before},
        )
        evidence = G012._read_refs(self.run_root / "evidence-refs-before.tsv")
        self.assertTrue(
            all(
                row["ref"].startswith("refs/g012-captured/")
                for row in evidence
            )
        )
        runbook = (self.run_root / "FORCE-PUSH-RUNBOOK.md").read_text()
        self.assertIn("non-publishable audit evidence", runbook)
        self.assertIn("must never be included in a remote update", runbook)
        restored = self.base / "hidden-rollback.git"
        run(
            [
                "git",
                "clone",
                "--mirror",
                self.run_root / "rollback-before.bundle",
                restored,
            ]
        )
        self.assertEqual(
            {row["ref"]: row["oid"] for row in refs_before},
            {
                line.split(" ", 1)[1]: line.split(" ", 1)[0]
                for line in git(restored, "show-ref").stdout.decode().splitlines()
            },
        )
        verified = run(
            [
                sys.executable,
                PROGRAM,
                "verify",
                "--run-root",
                self.run_root.resolve(),
            ],
            check=False,
        )
        self.assertEqual(0, verified.returncode, verified.stderr.decode())

    def test_source_controlled_g007_python_is_never_executed(self):
        marker = self.base / "g007-source-python-executed"
        export = self.source / "tools/hik_whole_apk/g007_public_export.py"
        export.write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed')\n"
            "GUARDED_PATH_PARTS = "
            "(('assets', 'hikmicro', 'official'), ('com', 'hcusbsdk'), "
            "('com', 'hik'), ('com', 'hikmicro'), ('hik', 'common'), "
            "('src', 'main', 'jniLibs'))\n",
            encoding="utf-8",
        )
        self._accepted_g007_bytes()
        archive = ACCEPTED_G007_ARCHIVE
        completed = self._dry_run(
            extra=["--g007-archive", str(archive.resolve())]
        )
        self.assertEqual(
            0, completed.returncode, completed.stderr.decode("utf-8", "replace")
        )
        self.assertFalse(marker.exists())
        preserved = self.run_root / "preserved-g007-clean-room.zip"
        self.assertEqual(archive.read_bytes(), preserved.read_bytes())

    def test_g007_exact_pinned_archive_is_accepted(self):
        self._accepted_g007_bytes()
        result = self._preserve_g007_for_test(ACCEPTED_G007_ARCHIVE)
        self.assertTrue(result["available"])
        self.assertEqual(ACCEPTED_G007_ARCHIVE_SHA256, result["sha256"])
        self.assertEqual("g007-clean-room-public-spec-20260730", result["profile_id"])
        self.assertEqual(68, result["member_count"])
        self.assertEqual(66, result["payload_file_count"])

    def test_g007_evidence_json_forbidden_source_string_is_positive_allowlisted(self):
        archive_bytes = self._accepted_g007_bytes()
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as handle:
            evidence = handle.read(
                ".omx/research/hikmicro-viewer-2.6.0/"
                "dossiers/D02/manifest.json"
            )
        prohibited = re.compile(self._g007_policy()["prohibited_source_regex"])
        self.assertIsNotNone(prohibited.search(evidence.decode("latin-1")))
        result = self._preserve_g007_for_test(ACCEPTED_G007_ARCHIVE)
        self.assertEqual(ACCEPTED_G007_ARCHIVE_SHA256, result["sha256"])

    def test_g007_rejects_modified_member(self):
        entries = self._replace_g007_payload(
            self._g007_entries(),
            "README.md",
            b"modified without publication-manifest update\n",
        )
        archive = self._write_g007_variant("g007-modified-member.zip", entries)
        with mock.patch.object(
            G012.zipfile,
            "ZipFile",
            side_effect=AssertionError("ZIP parser must not run for unknown hash"),
        ):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "not in the explicit positive allowlist",
            ):
                self._preserve_g007_for_test(archive)

    def test_g007_rejects_coordinated_member_and_manifest_tamper(self):
        entries = self._coordinate_g007_manifest(
            self._g007_entries(),
            "README.md",
            b"coordinated payload and manifest tamper\n",
        )
        archive = self._write_g007_variant("g007-coordinated-tamper.zip", entries)
        with self.assertRaisesRegex(
            G012.RemediationError,
            "not in the explicit positive allowlist",
        ):
            self._preserve_g007_for_test(archive)

    def test_g007_rejects_duplicate_keys_and_nonstandard_json_constants(self):
        original = self._g007_entries()
        manifest_name = G012.G007_PUBLICATION_MANIFEST_NAME
        manifest_payload = next(
            row["payload"] for row in original if row["name"] == manifest_name
        )
        variants = {
            "duplicate-key": manifest_payload.replace(
                b"{",
                b'{"schema":"duplicate",',
                1,
            ),
            "nan": manifest_payload.replace(
                b'"schema_version":1',
                b'"schema_version":NaN',
                1,
            ),
        }
        expected = {
            "duplicate-key": "not in the explicit positive allowlist",
            "nan": "not in the explicit positive allowlist",
        }
        for label, payload in variants.items():
            with self.subTest(label=label):
                entries = self._replace_g007_payload(
                    original,
                    manifest_name,
                    payload,
                )
                archive = self._write_g007_variant(
                    f"g007-manifest-{label}.zip",
                    entries,
                )
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    expected[label],
                ):
                    self._preserve_g007_for_test(archive)

    def test_g007_rejects_extra_missing_and_duplicate_members(self):
        original = self._g007_entries()
        variants = {
            "extra": sorted(
                original
                + [
                    {
                        "name": "UNDECLARED.txt",
                        "payload": b"extra",
                        "mode": 0o100644,
                    }
                ],
                key=lambda row: row["name"],
            ),
            "missing": [
                dict(row) for row in original if row["name"] != "README.md"
            ],
            "duplicate": sorted(
                [dict(row) for row in original]
                + [
                    {
                        "name": "README.md",
                        "payload": b"duplicate",
                        "mode": 0o100644,
                    }
                ],
                key=lambda row: row["name"],
            ),
        }
        expected = {
            "extra": "not in the explicit positive allowlist",
            "missing": "not in the explicit positive allowlist",
            "duplicate": "not in the explicit positive allowlist",
        }
        for label, entries in variants.items():
            with self.subTest(label=label):
                archive = self._write_g007_variant(
                    f"g007-{label}.zip",
                    entries,
                )
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    expected[label],
                ):
                    self._preserve_g007_for_test(archive)

    def test_g007_rejects_traversal_and_symlink_members(self):
        original = self._g007_entries()
        variants = {
            "traversal": {
                "name": "../escape.txt",
                "payload": b"escape",
                "mode": 0o100644,
            },
            "symlink": {
                "name": "unsafe-link",
                "payload": b"README.md",
                "mode": 0o120777,
            },
        }
        expected = {
            "traversal": "not in the explicit positive allowlist",
            "symlink": "not in the explicit positive allowlist",
        }
        for label, injected in variants.items():
            with self.subTest(label=label):
                entries = sorted(
                    [dict(row) for row in original] + [injected],
                    key=lambda row: row["name"],
                )
                archive = self._write_g007_variant(
                    f"g007-{label}.zip",
                    entries,
                )
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    expected[label],
                ):
                    self._preserve_g007_for_test(archive)

    def test_g007_rejects_official_exact_hash_injection(self):
        entries = self._coordinate_g007_manifest(
            self._g007_entries(),
            "README.md",
            self.denied_payload,
        )
        archive = self._write_g007_variant(
            "g007-official-hash-injection.zip",
            entries,
        )
        with self.assertRaisesRegex(
            G012.RemediationError,
            "not in the explicit positive allowlist",
        ):
            self._preserve_g007_for_test(archive)

    def test_g007_rejects_internally_valid_archive_with_wrong_hash(self):
        archive = self._write_g007_variant(
            "g007-wrong-hash.zip",
            self._g007_entries(),
            timestamp=(1982, 1, 1, 0, 0, 0),
        )
        self.assertNotEqual(
            ACCEPTED_G007_ARCHIVE_SHA256,
            hashlib.sha256(archive.read_bytes()).hexdigest(),
        )
        with self.assertRaisesRegex(
            G012.RemediationError,
            "not in the explicit positive allowlist",
        ):
            self._preserve_g007_for_test(archive)

    def test_g007_unknown_sha_is_rejected_before_zipfile_parsing_directly(self):
        with mock.patch.object(
            G012.zipfile,
            "ZipFile",
            side_effect=AssertionError("ZipFile must not inspect unknown bytes"),
        ):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "not in the explicit positive allowlist",
            ):
                G012._validate_g007_archive_bytes(
                    b"unknown G007 bytes are rejected by SHA first",
                    self._g007_policy(),
                )

    def test_verify_rejects_coordinated_g007_archive_and_checksum_tamper(self):
        self._accepted_g007_bytes()
        completed = self._dry_run(
            extra=["--g007-archive", str(ACCEPTED_G007_ARCHIVE)]
        )
        self.assertEqual(
            0,
            completed.returncode,
            completed.stderr.decode("utf-8", "replace"),
        )
        preserved = self.run_root / "preserved-g007-clean-room.zip"
        original_archive = preserved.read_bytes()
        original_record = json.loads(
            (self.run_root / "manifests/run-manifest.json").read_text()
        )["g007_clean_room_archive"]

        replacement = b"not an allowlisted G007 ZIP archive"
        preserved.write_bytes(replacement)

        def coordinate_replacement(run_manifest):
            record = run_manifest["g007_clean_room_archive"]
            record["sha256"] = hashlib.sha256(replacement).hexdigest()
            record["size_bytes"] = len(replacement)
            record["profile_id"] = "attacker-coordinated-profile"

        self._resign_run_artifacts(coordinate_replacement)
        rejected = run(
            [
                sys.executable,
                PROGRAM,
                "verify",
                "--run-root",
                self.run_root,
            ],
            check=False,
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn(
            b"not in the explicit positive allowlist",
            rejected.stderr,
        )

        preserved.write_bytes(original_archive)

        def mismatch_immutable_record(run_manifest):
            run_manifest["g007_clean_room_archive"] = dict(original_record)
            run_manifest["g007_clean_room_archive"]["member_count"] += 1

        self._resign_run_artifacts(mismatch_immutable_record)
        mismatch = run(
            [
                sys.executable,
                PROGRAM,
                "verify",
                "--run-root",
                self.run_root,
            ],
            check=False,
        )
        self.assertEqual(2, mismatch.returncode)
        self.assertIn(b"immutable run-manifest record", mismatch.stderr)

        def inconsistent_availability(run_manifest):
            run_manifest["g007_clean_room_archive"] = {
                "available": False,
                "reason": "no --g007-archive was supplied",
            }

        self._resign_run_artifacts(inconsistent_availability)
        inconsistent = run(
            [
                sys.executable,
                PROGRAM,
                "verify",
                "--run-root",
                self.run_root,
            ],
            check=False,
        )
        self.assertEqual(2, inconsistent.returncode)
        self.assertIn(b"unavailable but its preserved artifact", inconsistent.stderr)

    def test_g007_preserved_target_symlink_cannot_modify_victim(self):
        self._accepted_g007_bytes()
        target = self.base / "g007-symlink-run"
        target.mkdir()
        victim = self.base / "g007-victim"
        victim.write_bytes(b"victim-must-not-change")
        (target / "preserved-g007-clean-room.zip").symlink_to(victim)
        with self.assertRaisesRegex(
            G012.RemediationError,
            "secure output leaf already exists",
        ):
            G012._preserve_g007_archive(
                self.source,
                str(ACCEPTED_G007_ARCHIVE),
                target,
                self._g007_policy(),
            )
        self.assertEqual(b"victim-must-not-change", victim.read_bytes())

    def test_g007_copy_detects_leaf_swap_while_held_descriptor_stays_exact(self):
        archive_bytes = self._accepted_g007_bytes()
        target = self.base / "g007-copy-swap-run"
        target.mkdir()
        preserved = target / "preserved-g007-clean-room.zip"
        displaced = target / "held-original.zip"
        real_write_all = G012._write_all
        swapped = False

        def swap_after_descriptor_write(descriptor, payload):
            nonlocal swapped
            real_write_all(descriptor, payload)
            if payload == archive_bytes and not swapped:
                swapped = True
                os.rename(preserved, displaced)
                preserved.write_bytes(b"pathname substitute")

        with mock.patch.object(G012, "_write_all", side_effect=swap_after_descriptor_write):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "secure output leaf was replaced",
            ):
                G012._preserve_g007_archive(
                    self.source,
                    str(ACCEPTED_G007_ARCHIVE),
                    target,
                    self._g007_policy(),
                )
        self.assertTrue(swapped)
        self.assertEqual(
            ACCEPTED_G007_ARCHIVE_SHA256,
            hashlib.sha256(displaced.read_bytes()).hexdigest(),
        )
        self.assertEqual(b"pathname substitute", preserved.read_bytes())

    def test_preexisting_run_root_is_rejected_before_output(self):
        self.run_root.mkdir(mode=0o700)
        completed = self._dry_run()
        self.assertEqual(2, completed.returncode)
        self.assertIn(b"pre-existing directories are forbidden", completed.stderr)
        self.assertEqual([], list(self.run_root.iterdir()))

    def test_initial_run_root_ancestor_symlink_is_rejected(self):
        victim = self.base / "ancestor-victim"
        victim.mkdir()
        linked_parent = self.base / "linked-run-parent"
        linked_parent.symlink_to(victim, target_is_directory=True)
        self.run_root = linked_parent / "run"
        completed = self._dry_run()
        self.assertEqual(2, completed.returncode)
        self.assertIn(b"no-symlink traversal failed", completed.stderr)
        self.assertFalse((victim / "run").exists())

    def test_run_root_anchor_confines_root_symlink_aba_outputs(self):
        victim = self.base / "root-aba-victim"
        victim.mkdir()
        moved = self.base / "held-run-root"

        def exercise_aba(args, layout, run_root_anchor, tool):
            os.rename(self.run_root, moved)
            self.run_root.symlink_to(victim, target_is_directory=True)
            try:
                result = G012._secure_create_output(
                    run_root_anchor.command_path / "anchored-proof.txt",
                    b"anchored bytes\n",
                    "run-root ABA proof",
                )
                self.assertEqual(
                    hashlib.sha256(b"anchored bytes\n").hexdigest(),
                    result["sha256"],
                )
                self.assertFalse((victim / "anchored-proof.txt").exists())
            finally:
                self.run_root.unlink()
                os.rename(moved, self.run_root)
            return {"anchored": True}

        args = Namespace(
            source=str(self.source.resolve()),
            run_root=str(self.run_root.absolute()),
            filter_repo_tool=str(AUDITED_FILTER_REPO),
            g007_archive=None,
        )
        with mock.patch.object(
            G012,
            "_dry_run_with_sealed_tool",
            side_effect=exercise_aba,
        ):
            result = G012.guarded_dry_run(args)
        self.assertEqual({"anchored": True}, result)
        self.assertEqual(
            b"anchored bytes\n",
            (self.run_root / "anchored-proof.txt").read_bytes(),
        )
        self.assertEqual([], list(victim.iterdir()))

    def test_run_root_anchor_confines_parent_aba_outputs(self):
        run_parent = self.base / "run-parent"
        run_parent.mkdir()
        self.run_root = run_parent / "run"
        moved_parent = self.base / "held-run-parent"

        def exercise_parent_aba(args, layout, run_root_anchor, tool):
            os.rename(run_parent, moved_parent)
            run_parent.mkdir()
            try:
                G012._secure_create_output(
                    run_root_anchor.command_path / "parent-aba-proof.txt",
                    b"held-parent bytes\n",
                    "run-root parent ABA proof",
                )
                self.assertEqual([], list(run_parent.iterdir()))
            finally:
                run_parent.rmdir()
                os.rename(moved_parent, run_parent)
            return {"parent_anchored": True}

        args = Namespace(
            source=str(self.source.resolve()),
            run_root=str(self.run_root.absolute()),
            filter_repo_tool=str(AUDITED_FILTER_REPO),
            g007_archive=None,
        )
        with mock.patch.object(
            G012,
            "_dry_run_with_sealed_tool",
            side_effect=exercise_parent_aba,
        ):
            result = G012.guarded_dry_run(args)
        self.assertEqual({"parent_anchored": True}, result)
        self.assertEqual(
            b"held-parent bytes\n",
            (self.run_root / "parent-aba-proof.txt").read_bytes(),
        )

    def test_secure_output_copy_is_exclusive_nofollow_and_fsynced(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            opened = []
            synced = []
            real_open = G012.os.open
            real_fsync = G012.os.fsync

            def track_open(path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                if path == "copy.bin":
                    opened.append((descriptor, flags))
                return descriptor

            def track_fsync(descriptor):
                synced.append(descriptor)
                return real_fsync(descriptor)

            payload = b"descriptor-bound secure output\n"
            with mock.patch.object(G012.os, "open", side_effect=track_open), mock.patch.object(
                G012.os,
                "fsync",
                side_effect=track_fsync,
            ):
                record = G012._secure_create_output(
                    anchor.command_path / "copy.bin",
                    payload,
                    "secure copy regression",
                )
            self.assertEqual(hashlib.sha256(payload).hexdigest(), record["sha256"])
            self.assertEqual(len(payload), record["size_bytes"])
            self.assertEqual(payload, (self.run_root / "copy.bin").read_bytes())
            self.assertTrue(opened)
            descriptor, flags = opened[-1]
            self.assertEqual(
                os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                flags & (os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW),
            )
            self.assertIn(descriptor, synced)
            with self.assertRaisesRegex(
                G012.RemediationError,
                "secure output leaf already exists",
            ):
                G012._secure_create_output(
                    anchor.command_path / "copy.bin",
                    b"overwrite",
                    "secure copy overwrite",
                )

            os.mkfifo("special-output", dir_fd=anchor.held.descriptor)
            with self.assertRaisesRegex(
                G012.RemediationError,
                "secure output leaf already exists",
            ):
                G012._secure_create_output(
                    anchor.command_path / "special-output",
                    b"must not write",
                    "special output victim",
                )
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_fixed_temp_symlink_and_precreated_git_destinations_are_safe(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            manifests = anchor.command_path / "manifests"
            G012._secure_output_directory(manifests, "test manifests")
            victim = self.base / "fixed-temp-victim"
            victim.write_bytes(b"fixed-temp-victim")
            (manifests / ".record.json.tmp").symlink_to(victim)
            G012._write_json(manifests / "record.json", {"safe": True})
            self.assertEqual(b"fixed-temp-victim", victim.read_bytes())
            self.assertTrue((self.run_root / "manifests/.record.json.tmp").is_symlink())

            clone_victim = self.base / "clone-victim"
            clone_victim.mkdir()
            (anchor.command_path / "blocked-mirror.git").symlink_to(
                clone_victim,
                target_is_directory=True,
            )
            with self.assertRaisesRegex(
                G012.RemediationError,
                "exclusive Git destination already exists",
            ):
                G012._clone_mirror(
                    self.source,
                    anchor.command_path / "blocked-mirror.git",
                )
            self.assertEqual([], list(clone_victim.iterdir()))

            os.mkfifo("blocked.bundle", dir_fd=anchor.held.descriptor)
            with self.assertRaisesRegex(
                G012.RemediationError,
                "secure output leaf already exists",
            ):
                G012._bundle(
                    self.source,
                    anchor.command_path / "blocked.bundle",
                    ["refs/heads/main"],
                )
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_clone_race_populates_held_directory_not_inserted_symlink(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            destination_name = "raced-mirror.git"
            displaced_name = "held-raced-mirror.git"
            victim = self.base / "clone-race-victim"
            victim.mkdir()
            real_run = G012._run
            raced = False

            def race_after_destination_preparation(command, *args, **kwargs):
                nonlocal raced
                self.assertFalse(raced)
                raced = True
                self.assertEqual("clone", command[-6])
                os.rename(
                    destination_name,
                    displaced_name,
                    src_dir_fd=anchor.held.descriptor,
                    dst_dir_fd=anchor.held.descriptor,
                )
                os.symlink(
                    str(victim),
                    destination_name,
                    dir_fd=anchor.held.descriptor,
                )
                return real_run(command, *args, **kwargs)

            with mock.patch.object(
                G012,
                "_run",
                side_effect=race_after_destination_preparation,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "secure Git destination was replaced",
                ):
                    G012._clone_mirror(
                        self.source,
                        anchor.command_path / destination_name,
                    )
            self.assertTrue(raced)
            self.assertEqual([], list(victim.iterdir()))
            self.assertTrue((self.run_root / destination_name).is_symlink())
            self.assertTrue(
                (self.run_root / displaced_name / "HEAD").is_file(),
                "Git must populate the held directory rather than the raced leaf",
            )
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_bundle_race_writes_held_fd_not_inserted_symlink_target(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            destination_name = "raced.bundle"
            displaced_name = "held-raced.bundle"
            victim = self.base / "bundle-race-victim"
            victim.write_bytes(b"victim-must-not-change")
            real_stream = G012._run_git_bundle_to_fd
            raced = False

            def race_after_output_open(repo, refs, output):
                nonlocal raced
                self.assertFalse(raced)
                raced = True
                os.rename(
                    destination_name,
                    displaced_name,
                    src_dir_fd=anchor.held.descriptor,
                    dst_dir_fd=anchor.held.descriptor,
                )
                os.symlink(
                    str(victim),
                    destination_name,
                    dir_fd=anchor.held.descriptor,
                )
                return real_stream(repo, refs, output)

            with mock.patch.object(
                G012,
                "_run_git_bundle_to_fd",
                side_effect=race_after_output_open,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "secure output leaf was replaced",
                ):
                    G012._bundle(
                        self.source,
                        anchor.command_path / destination_name,
                        ["refs/heads/main"],
                    )
            self.assertTrue(raced)
            self.assertEqual(b"victim-must-not-change", victim.read_bytes())
            self.assertTrue((self.run_root / destination_name).is_symlink())
            displaced = self.run_root / displaced_name
            self.assertGreater(displaced.stat().st_size, 0)
            git(self.source, "bundle", "verify", displaced)
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_failed_secure_outputs_remove_only_owned_partial_leaves(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)

            def partial_write(descriptor, payload):
                os.write(descriptor, payload[:7])
                raise OSError("injected partial write failure")

            partial_path = anchor.command_path / "partial-write.bin"
            synced = []
            real_fsync = G012.os.fsync

            def track_fsync(descriptor):
                synced.append(descriptor)
                return real_fsync(descriptor)

            with mock.patch.object(
                G012,
                "_write_all",
                side_effect=partial_write,
            ), mock.patch.object(
                G012.os,
                "fsync",
                side_effect=track_fsync,
            ):
                with self.assertRaisesRegex(OSError, "partial write"):
                    G012._secure_create_output(
                        partial_path,
                        b"partial write payload",
                        "partial write cleanup",
                    )
            self.assertFalse((self.run_root / "partial-write.bin").exists())
            self.assertIn(
                anchor.held.descriptor,
                synced,
                "failure cleanup must fsync the descriptor-held parent",
            )

            fsync_path = anchor.command_path / "fsync-failure.bin"
            with mock.patch.object(
                G012.SecureOutputFile,
                "fsync",
                side_effect=OSError("injected fsync failure"),
            ):
                with self.assertRaisesRegex(OSError, "fsync failure"):
                    G012._secure_create_output(
                        fsync_path,
                        b"fsync failure payload",
                        "fsync failure cleanup",
                    )
            self.assertFalse((self.run_root / "fsync-failure.bin").exists())

            hash_path = anchor.command_path / "hash-failure.bin"
            with mock.patch.object(
                G012,
                "_hash_open_descriptor",
                side_effect=OSError("injected hash failure"),
            ):
                with self.assertRaisesRegex(OSError, "hash failure"):
                    G012._secure_create_output(
                        hash_path,
                        b"hash failure payload",
                        "hash failure cleanup",
                    )
            self.assertFalse((self.run_root / "hash-failure.bin").exists())
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_file_output_construction_failures_remove_created_leaf(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)

            fchmod_name = "construct-file-fchmod.bin"
            with mock.patch.object(
                G012.os,
                "fchmod",
                side_effect=OSError("injected file fchmod failure"),
            ):
                with self.assertRaisesRegex(OSError, "file fchmod failure"):
                    G012._secure_create_output(
                        anchor.command_path / fchmod_name,
                        b"file fchmod construction",
                        "file fchmod construction failure",
                    )
            self.assertFalse((self.run_root / fchmod_name).exists())

            fstat_name = "construct-file-fstat.bin"
            real_open = G012.os.open
            real_fstat = G012.os.fstat
            created_descriptor = None
            fstat_failed = False

            def capture_file_descriptor(path, flags, *args, **kwargs):
                nonlocal created_descriptor
                descriptor = real_open(path, flags, *args, **kwargs)
                if path == fstat_name:
                    created_descriptor = descriptor
                return descriptor

            def fail_created_file_fstat(descriptor):
                nonlocal fstat_failed
                if descriptor == created_descriptor and not fstat_failed:
                    fstat_failed = True
                    raise OSError("injected file fstat failure")
                return real_fstat(descriptor)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=capture_file_descriptor,
            ), mock.patch.object(
                G012.os,
                "fstat",
                side_effect=fail_created_file_fstat,
            ):
                with self.assertRaisesRegex(OSError, "file fstat failure"):
                    G012._secure_create_output(
                        anchor.command_path / fstat_name,
                        b"file fstat construction",
                        "file fstat construction failure",
                    )
            self.assertTrue(fstat_failed)
            self.assertFalse((self.run_root / fstat_name).exists())

            revalidate_name = "construct-file-revalidate.bin"
            with mock.patch.object(
                G012.SecureOutputFile,
                "revalidate",
                side_effect=G012.RemediationError(
                    "injected file initial revalidation failure"
                ),
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "file initial revalidation failure",
                ):
                    G012._secure_create_output(
                        anchor.command_path / revalidate_name,
                        b"file revalidation construction",
                        "file initial revalidation failure",
                    )
            self.assertFalse((self.run_root / revalidate_name).exists())

            holder_name = "construct-file-holder.bin"
            with mock.patch.object(
                G012,
                "SecureOutputFile",
                side_effect=RuntimeError("injected file holder failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "file holder failure"):
                    G012._secure_create_output(
                        anchor.command_path / holder_name,
                        b"file holder construction",
                        "file holder construction failure",
                    )
            self.assertFalse((self.run_root / holder_name).exists())
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_directory_destination_construction_failures_remove_created_leaf(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)

            open_name = "construct-dir-open.git"
            real_open = G012.os.open

            def fail_created_directory_open(path, flags, *args, **kwargs):
                if path == open_name and flags & os.O_DIRECTORY:
                    raise OSError("injected directory open failure")
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=fail_created_directory_open,
            ):
                with self.assertRaisesRegex(OSError, "directory open failure"):
                    G012._prepare_exclusive_destination(
                        anchor.command_path / open_name,
                        "directory open construction failure",
                    )
            self.assertFalse((self.run_root / open_name).exists())

            fchmod_name = "construct-dir-fchmod.git"
            with mock.patch.object(
                G012.os,
                "fchmod",
                side_effect=OSError("injected directory fchmod failure"),
            ):
                with self.assertRaisesRegex(OSError, "directory fchmod failure"):
                    G012._prepare_exclusive_destination(
                        anchor.command_path / fchmod_name,
                        "directory fchmod construction failure",
                    )
            self.assertFalse((self.run_root / fchmod_name).exists())

            fstat_name = "construct-dir-fstat.git"
            real_fstat = G012.os.fstat
            created_descriptor = None
            fstat_failed = False

            def capture_directory_descriptor(path, flags, *args, **kwargs):
                nonlocal created_descriptor
                descriptor = real_open(path, flags, *args, **kwargs)
                if path == fstat_name and flags & os.O_DIRECTORY:
                    created_descriptor = descriptor
                return descriptor

            def fail_created_directory_fstat(descriptor):
                nonlocal fstat_failed
                if descriptor == created_descriptor and not fstat_failed:
                    fstat_failed = True
                    raise OSError("injected directory fstat failure")
                return real_fstat(descriptor)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=capture_directory_descriptor,
            ), mock.patch.object(
                G012.os,
                "fstat",
                side_effect=fail_created_directory_fstat,
            ):
                with self.assertRaisesRegex(OSError, "directory fstat failure"):
                    G012._prepare_exclusive_destination(
                        anchor.command_path / fstat_name,
                        "directory fstat construction failure",
                    )
            self.assertTrue(fstat_failed)
            self.assertFalse((self.run_root / fstat_name).exists())

            revalidate_name = "construct-dir-revalidate.git"
            with mock.patch.object(
                G012.HeldExclusiveDestination,
                "verify_created_directory",
                side_effect=G012.RemediationError(
                    "injected directory initial revalidation failure"
                ),
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "directory initial revalidation failure",
                ):
                    G012._prepare_exclusive_destination(
                        anchor.command_path / revalidate_name,
                        "directory initial revalidation failure",
                    )
            self.assertFalse((self.run_root / revalidate_name).exists())

            holder_name = "construct-dir-holder.git"
            with mock.patch.object(
                G012,
                "HeldExclusiveDestination",
                side_effect=RuntimeError("injected directory holder failure"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "directory holder failure",
                ):
                    G012._prepare_exclusive_destination(
                        anchor.command_path / holder_name,
                        "directory holder construction failure",
                    )
            self.assertFalse((self.run_root / holder_name).exists())
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_real_directory_replacement_before_open_is_rejected(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            destination_name = "construct-real-directory-race.git"
            displaced_name = "held-original-directory.git"
            real_open = G012.os.open
            replacement_identity = None

            def replace_with_real_directory_before_open(
                path,
                flags,
                *args,
                **kwargs,
            ):
                nonlocal replacement_identity
                if path == destination_name and flags & os.O_DIRECTORY:
                    os.rename(
                        destination_name,
                        displaced_name,
                        src_dir_fd=anchor.held.descriptor,
                        dst_dir_fd=anchor.held.descriptor,
                    )
                    os.mkdir(
                        destination_name,
                        mode=0o700,
                        dir_fd=anchor.held.descriptor,
                    )
                    replacement_identity = os.stat(
                        destination_name,
                        dir_fd=anchor.held.descriptor,
                        follow_symlinks=False,
                    ).st_ino
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=replace_with_real_directory_before_open,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "changed during creation",
                ):
                    G012._prepare_exclusive_destination(
                        anchor.command_path / destination_name,
                        "real-directory pre-open replacement",
                    )
            self.assertIsNotNone(replacement_identity)
            replacement = self.run_root / destination_name
            displaced = self.run_root / displaced_name
            self.assertTrue(replacement.is_dir())
            self.assertTrue(displaced.is_dir())
            self.assertNotEqual(
                replacement.stat().st_ino,
                displaced.stat().st_ino,
            )
            self.assertEqual([], list(replacement.iterdir()))
            self.assertEqual([], list(displaced.iterdir()))
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_first_identity_metadata_failure_cleans_file_and_directory(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)

            file_name = "construct-first-file-metadata.bin"
            real_open = G012.os.open
            real_stat = G012.os.stat
            file_descriptor = None
            file_metadata_failed = False

            def capture_first_file_descriptor(path, flags, *args, **kwargs):
                nonlocal file_descriptor
                descriptor = real_open(path, flags, *args, **kwargs)
                if path == file_name:
                    file_descriptor = descriptor
                return descriptor

            def fail_first_file_identity(path, *args, **kwargs):
                nonlocal file_metadata_failed
                if path == file_descriptor and not file_metadata_failed:
                    file_metadata_failed = True
                    raise OSError("injected first file identity failure")
                return real_stat(path, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=capture_first_file_descriptor,
            ), mock.patch.object(
                G012.os,
                "stat",
                side_effect=fail_first_file_identity,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "initial secure output identity acquisition failed",
                ):
                    G012._secure_create_output(
                        anchor.command_path / file_name,
                        b"first file metadata failure",
                        "first file metadata failure",
                    )
            self.assertTrue(file_metadata_failed)
            self.assertFalse((self.run_root / file_name).exists())

            directory_name = "construct-first-directory-metadata.git"
            directory_metadata_failed = False

            def fail_first_directory_identity(path, *args, **kwargs):
                nonlocal directory_metadata_failed
                if (
                    path == directory_name
                    and kwargs.get("dir_fd") == anchor.held.descriptor
                    and not directory_metadata_failed
                ):
                    directory_metadata_failed = True
                    raise OSError("injected first directory identity failure")
                return real_stat(path, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "stat",
                side_effect=fail_first_directory_identity,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "initial Git destination identity acquisition failed",
                ):
                    G012._prepare_exclusive_destination(
                        anchor.command_path / directory_name,
                        "first directory metadata failure",
                    )
            self.assertTrue(directory_metadata_failed)
            self.assertFalse((self.run_root / directory_name).exists())
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_first_directory_metadata_failure_does_not_delete_replacement(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            destination_name = "construct-first-metadata-race.git"
            displaced_name = "held-first-metadata-directory.git"
            real_stat = G012.os.stat
            replaced = False

            def replace_during_failed_first_identity(path, *args, **kwargs):
                nonlocal replaced
                if (
                    path == destination_name
                    and kwargs.get("dir_fd") == anchor.held.descriptor
                    and not replaced
                ):
                    replaced = True
                    os.rename(
                        destination_name,
                        displaced_name,
                        src_dir_fd=anchor.held.descriptor,
                        dst_dir_fd=anchor.held.descriptor,
                    )
                    os.mkdir(
                        destination_name,
                        mode=0o700,
                        dir_fd=anchor.held.descriptor,
                    )
                    raise OSError(
                        "injected first identity failure with replacement"
                    )
                return real_stat(path, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "stat",
                side_effect=replace_during_failed_first_identity,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "ownership could not be re-established",
                ):
                    G012._prepare_exclusive_destination(
                        anchor.command_path / destination_name,
                        "first metadata replacement",
                    )
            self.assertTrue(replaced)
            self.assertTrue((self.run_root / destination_name).is_dir())
            self.assertTrue((self.run_root / displaced_name).is_dir())
            self.assertEqual(
                [],
                list((self.run_root / destination_name).iterdir()),
            )
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_secure_output_directory_construction_failures_cleanup(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            real_open = G012.os.open
            real_fstat = G012.os.fstat
            real_stat = G012.os.stat
            real_fsync = G012.os.fsync

            open_name = "output-dir-open"

            def fail_output_directory_open(path, flags, *args, **kwargs):
                if path == open_name and flags & os.O_DIRECTORY:
                    raise OSError("injected output-directory open failure")
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=fail_output_directory_open,
            ):
                with self.assertRaisesRegex(OSError, "open failure"):
                    G012._secure_output_directory(
                        anchor.command_path / open_name,
                        "output-directory open failure",
                    )
            self.assertFalse((self.run_root / open_name).exists())

            fchmod_name = "output-dir-fchmod"
            with mock.patch.object(
                G012.os,
                "fchmod",
                side_effect=OSError("injected output-directory fchmod failure"),
            ):
                with self.assertRaisesRegex(OSError, "fchmod failure"):
                    G012._secure_output_directory(
                        anchor.command_path / fchmod_name,
                        "output-directory fchmod failure",
                    )
            self.assertFalse((self.run_root / fchmod_name).exists())

            fstat_name = "output-dir-fstat"
            fstat_descriptor = None
            fstat_failed = False

            def capture_output_directory_fstat_fd(path, flags, *args, **kwargs):
                nonlocal fstat_descriptor
                descriptor = real_open(path, flags, *args, **kwargs)
                if path == fstat_name and flags & os.O_DIRECTORY:
                    fstat_descriptor = descriptor
                return descriptor

            def fail_output_directory_fstat(descriptor):
                nonlocal fstat_failed
                if descriptor == fstat_descriptor and not fstat_failed:
                    fstat_failed = True
                    raise OSError("injected output-directory fstat failure")
                return real_fstat(descriptor)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=capture_output_directory_fstat_fd,
            ), mock.patch.object(
                G012.os,
                "fstat",
                side_effect=fail_output_directory_fstat,
            ):
                with self.assertRaisesRegex(OSError, "fstat failure"):
                    G012._secure_output_directory(
                        anchor.command_path / fstat_name,
                        "output-directory fstat failure",
                    )
            self.assertTrue(fstat_failed)
            self.assertFalse((self.run_root / fstat_name).exists())

            identity_name = "output-dir-identity"
            identity_failed = False

            def fail_first_output_directory_identity(path, *args, **kwargs):
                nonlocal identity_failed
                if (
                    path == identity_name
                    and kwargs.get("dir_fd") == anchor.held.descriptor
                    and not identity_failed
                ):
                    identity_failed = True
                    raise OSError("injected output-directory identity failure")
                return real_stat(path, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "stat",
                side_effect=fail_first_output_directory_identity,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "initial secure output directory identity acquisition failed",
                ):
                    G012._secure_output_directory(
                        anchor.command_path / identity_name,
                        "output-directory identity failure",
                    )
            self.assertTrue(identity_failed)
            self.assertFalse((self.run_root / identity_name).exists())

            fsync_name = "output-dir-fsync"
            fsync_descriptor = None
            descriptor_fsync_failed = False

            def capture_output_directory_fsync_fd(path, flags, *args, **kwargs):
                nonlocal fsync_descriptor
                descriptor = real_open(path, flags, *args, **kwargs)
                if path == fsync_name and flags & os.O_DIRECTORY:
                    fsync_descriptor = descriptor
                return descriptor

            def fail_output_directory_descriptor_fsync(descriptor):
                nonlocal descriptor_fsync_failed
                if descriptor == fsync_descriptor and not descriptor_fsync_failed:
                    descriptor_fsync_failed = True
                    raise OSError("injected output-directory fsync failure")
                return real_fsync(descriptor)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=capture_output_directory_fsync_fd,
            ), mock.patch.object(
                G012.os,
                "fsync",
                side_effect=fail_output_directory_descriptor_fsync,
            ):
                with self.assertRaisesRegex(OSError, "fsync failure"):
                    G012._secure_output_directory(
                        anchor.command_path / fsync_name,
                        "output-directory fsync failure",
                    )
            self.assertTrue(descriptor_fsync_failed)
            self.assertFalse((self.run_root / fsync_name).exists())

            parent_fsync_name = "output-dir-parent-fsync"
            parent_fsync_failed = False

            def fail_output_directory_parent_fsync(descriptor):
                nonlocal parent_fsync_failed
                if (
                    descriptor == anchor.held.descriptor
                    and not parent_fsync_failed
                ):
                    parent_fsync_failed = True
                    raise OSError("injected output-directory parent fsync failure")
                return real_fsync(descriptor)

            with mock.patch.object(
                G012.os,
                "fsync",
                side_effect=fail_output_directory_parent_fsync,
            ):
                with self.assertRaisesRegex(OSError, "parent fsync failure"):
                    G012._secure_output_directory(
                        anchor.command_path / parent_fsync_name,
                        "output-directory parent fsync failure",
                    )
            self.assertTrue(parent_fsync_failed)
            self.assertFalse((self.run_root / parent_fsync_name).exists())
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_secure_output_directory_preserves_real_and_symlink_substitutions(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            real_open = G012.os.open

            real_name = "output-dir-real-race"
            real_displaced = "held-output-dir-real"

            def replace_output_with_real_directory(path, flags, *args, **kwargs):
                if path == real_name and flags & os.O_DIRECTORY:
                    os.rename(
                        real_name,
                        real_displaced,
                        src_dir_fd=anchor.held.descriptor,
                        dst_dir_fd=anchor.held.descriptor,
                    )
                    os.mkdir(
                        real_name,
                        mode=0o700,
                        dir_fd=anchor.held.descriptor,
                    )
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=replace_output_with_real_directory,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "changed during creation",
                ):
                    G012._secure_output_directory(
                        anchor.command_path / real_name,
                        "output-directory real replacement",
                    )
            self.assertTrue((self.run_root / real_name).is_dir())
            self.assertTrue((self.run_root / real_displaced).is_dir())

            symlink_name = "output-dir-symlink-race"
            symlink_displaced = "held-output-dir-symlink"
            victim = self.base / "output-directory-symlink-victim"
            victim.mkdir()

            def replace_output_with_symlink(path, flags, *args, **kwargs):
                if path == symlink_name and flags & os.O_DIRECTORY:
                    os.rename(
                        symlink_name,
                        symlink_displaced,
                        src_dir_fd=anchor.held.descriptor,
                        dst_dir_fd=anchor.held.descriptor,
                    )
                    os.symlink(
                        str(victim),
                        symlink_name,
                        dir_fd=anchor.held.descriptor,
                    )
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=replace_output_with_symlink,
            ):
                with self.assertRaises(OSError):
                    G012._secure_output_directory(
                        anchor.command_path / symlink_name,
                        "output-directory symlink replacement",
                    )
            self.assertTrue((self.run_root / symlink_name).is_symlink())
            self.assertEqual([], list(victim.iterdir()))
            self.assertTrue((self.run_root / symlink_displaced).is_dir())
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_run_root_construction_failures_cleanup(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        try:
            real_open = G012.os.open
            real_fstat = G012.os.fstat
            real_stat = G012.os.stat
            real_fsync = G012.os.fsync

            open_root = self.base / "run-root-open-failure"

            def fail_run_root_open(path, flags, *args, **kwargs):
                if path == open_root.name and flags & os.O_DIRECTORY:
                    raise OSError("injected run-root open failure")
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=fail_run_root_open,
            ):
                with self.assertRaisesRegex(OSError, "open failure"):
                    G012._prepare_run_root(str(open_root), layout)
            self.assertFalse(open_root.exists())

            fchmod_root = self.base / "run-root-fchmod-failure"
            with mock.patch.object(
                G012.os,
                "fchmod",
                side_effect=OSError("injected run-root fchmod failure"),
            ):
                with self.assertRaisesRegex(OSError, "fchmod failure"):
                    G012._prepare_run_root(str(fchmod_root), layout)
            self.assertFalse(fchmod_root.exists())

            fstat_root = self.base / "run-root-fstat-failure"
            fstat_descriptor = None
            fstat_failed = False

            def capture_run_root_fstat_fd(path, flags, *args, **kwargs):
                nonlocal fstat_descriptor
                descriptor = real_open(path, flags, *args, **kwargs)
                if path == fstat_root.name and flags & os.O_DIRECTORY:
                    fstat_descriptor = descriptor
                return descriptor

            def fail_run_root_fstat(descriptor):
                nonlocal fstat_failed
                if descriptor == fstat_descriptor and not fstat_failed:
                    fstat_failed = True
                    raise OSError("injected run-root fstat failure")
                return real_fstat(descriptor)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=capture_run_root_fstat_fd,
            ), mock.patch.object(
                G012.os,
                "fstat",
                side_effect=fail_run_root_fstat,
            ):
                with self.assertRaisesRegex(OSError, "fstat failure"):
                    G012._prepare_run_root(str(fstat_root), layout)
            self.assertTrue(fstat_failed)
            self.assertFalse(fstat_root.exists())

            identity_root = self.base / "run-root-identity-failure"
            identity_failed = False

            def fail_first_run_root_identity(path, *args, **kwargs):
                nonlocal identity_failed
                if path == identity_root.name and not identity_failed:
                    identity_failed = True
                    raise OSError("injected run-root identity failure")
                return real_stat(path, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "stat",
                side_effect=fail_first_run_root_identity,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "initial run-root identity acquisition failed",
                ):
                    G012._prepare_run_root(str(identity_root), layout)
            self.assertTrue(identity_failed)
            self.assertFalse(identity_root.exists())

            fsync_root = self.base / "run-root-fsync-failure"
            fsync_descriptor = None
            fsync_failed = False

            def capture_run_root_fsync_fd(path, flags, *args, **kwargs):
                nonlocal fsync_descriptor
                descriptor = real_open(path, flags, *args, **kwargs)
                if path == fsync_root.name and flags & os.O_DIRECTORY:
                    fsync_descriptor = descriptor
                return descriptor

            def fail_run_root_descriptor_fsync(descriptor):
                nonlocal fsync_failed
                if descriptor == fsync_descriptor and not fsync_failed:
                    fsync_failed = True
                    raise OSError("injected run-root fsync failure")
                return real_fsync(descriptor)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=capture_run_root_fsync_fd,
            ), mock.patch.object(
                G012.os,
                "fsync",
                side_effect=fail_run_root_descriptor_fsync,
            ):
                with self.assertRaisesRegex(OSError, "fsync failure"):
                    G012._prepare_run_root(str(fsync_root), layout)
            self.assertTrue(fsync_failed)
            self.assertFalse(fsync_root.exists())

            parent_fsync_root = self.base / "run-root-parent-fsync-failure"
            parent_fsync_descriptor = None
            parent_fsync_failed = False

            def capture_parent_fsync_root_fd(path, flags, *args, **kwargs):
                nonlocal parent_fsync_descriptor
                descriptor = real_open(path, flags, *args, **kwargs)
                if path == parent_fsync_root.name and flags & os.O_DIRECTORY:
                    parent_fsync_descriptor = descriptor
                return descriptor

            def fail_run_root_parent_fsync(descriptor):
                nonlocal parent_fsync_failed
                if (
                    parent_fsync_descriptor is not None
                    and descriptor != parent_fsync_descriptor
                    and not parent_fsync_failed
                ):
                    parent_fsync_failed = True
                    raise OSError("injected run-root parent fsync failure")
                return real_fsync(descriptor)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=capture_parent_fsync_root_fd,
            ), mock.patch.object(
                G012.os,
                "fsync",
                side_effect=fail_run_root_parent_fsync,
            ):
                with self.assertRaisesRegex(OSError, "parent fsync failure"):
                    G012._prepare_run_root(str(parent_fsync_root), layout)
            self.assertTrue(parent_fsync_failed)
            self.assertFalse(parent_fsync_root.exists())
        finally:
            layout.close()

    def test_run_root_constructor_preserves_real_and_symlink_substitutions(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        try:
            real_open = G012.os.open
            real_root = self.base / "run-root-real-race"
            real_displaced = self.base / "held-run-root-real"

            def replace_run_root_with_real_directory(
                path,
                flags,
                *args,
                **kwargs,
            ):
                if path == real_root.name and flags & os.O_DIRECTORY:
                    parent_descriptor = kwargs["dir_fd"]
                    os.rename(
                        real_root.name,
                        real_displaced.name,
                        src_dir_fd=parent_descriptor,
                        dst_dir_fd=parent_descriptor,
                    )
                    os.mkdir(
                        real_root.name,
                        mode=0o700,
                        dir_fd=parent_descriptor,
                    )
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=replace_run_root_with_real_directory,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "changed during descriptor-relative creation",
                ):
                    G012._prepare_run_root(str(real_root), layout)
            self.assertTrue(real_root.is_dir())
            self.assertTrue(real_displaced.is_dir())

            symlink_root = self.base / "run-root-symlink-race"
            symlink_displaced = self.base / "held-run-root-symlink"
            victim = self.base / "run-root-symlink-victim"
            victim.mkdir()

            def replace_run_root_with_symlink(path, flags, *args, **kwargs):
                if path == symlink_root.name and flags & os.O_DIRECTORY:
                    parent_descriptor = kwargs["dir_fd"]
                    os.rename(
                        symlink_root.name,
                        symlink_displaced.name,
                        src_dir_fd=parent_descriptor,
                        dst_dir_fd=parent_descriptor,
                    )
                    os.symlink(
                        str(victim),
                        symlink_root.name,
                        dir_fd=parent_descriptor,
                    )
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=replace_run_root_with_symlink,
            ):
                with self.assertRaises(OSError):
                    G012._prepare_run_root(str(symlink_root), layout)
            self.assertTrue(symlink_root.is_symlink())
            self.assertEqual([], list(victim.iterdir()))
            self.assertTrue(symlink_displaced.is_dir())
        finally:
            layout.close()

    def test_file_cleanup_quarantines_final_window_substitution(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            leaf = "file-final-window.bin"
            displaced = "held-file-final-window.bin"
            victim = self.base / "file-final-window-victim"
            victim.write_bytes(b"file victim")

            def install_substitute(parent_fd, name):
                os.symlink(str(victim), name, dir_fd=parent_fd)

            state, injector = self._quarantine_race_injector(
                leaf,
                displaced,
                install_substitute,
            )

            def fail_after_partial_write(descriptor, payload):
                os.write(descriptor, payload[:5])
                raise OSError("injected file cleanup failure")

            with mock.patch.object(
                G012,
                "_write_all",
                side_effect=fail_after_partial_write,
            ), mock.patch.object(
                G012,
                "_rename_noreplace",
                side_effect=injector,
            ):
                with self.assertRaisesRegex(OSError, "file cleanup failure"):
                    G012._secure_create_output(
                        anchor.command_path / leaf,
                        b"owned partial file",
                        "file final-window cleanup",
                    )
            self.assertTrue(state["candidate_swapped"])
            self.assertTrue((self.run_root / leaf).is_symlink())
            self.assertEqual(b"file victim", victim.read_bytes())
            self.assertTrue((self.run_root / displaced).is_file())
            self.assertEqual(
                [],
                list(self.run_root.glob(".g012-quarantine-*")),
            )
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_directory_cleanup_quarantines_final_window_substitution(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            leaf = "directory-final-window"
            displaced = "held-directory-final-window"
            victim = self.base / "directory-final-window-victim"
            victim.mkdir()

            def install_substitute(parent_fd, name):
                os.symlink(str(victim), name, dir_fd=parent_fd)

            state, injector = self._quarantine_race_injector(
                leaf,
                displaced,
                install_substitute,
            )
            with mock.patch.object(
                G012.os,
                "fchmod",
                side_effect=OSError("injected directory cleanup failure"),
            ), mock.patch.object(
                G012,
                "_rename_noreplace",
                side_effect=injector,
            ):
                with self.assertRaisesRegex(OSError, "directory cleanup failure"):
                    G012._secure_output_directory(
                        anchor.command_path / leaf,
                        "directory final-window cleanup",
                    )
            self.assertTrue(state["candidate_swapped"])
            self.assertTrue((self.run_root / leaf).is_symlink())
            self.assertEqual([], list(victim.iterdir()))
            self.assertTrue((self.run_root / displaced).is_dir())
            self.assertEqual(
                [],
                list(self.run_root.glob(".g012-quarantine-*")),
            )
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_run_root_cleanup_quarantines_final_window_substitution(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        try:
            run_root = self.base / "run-root-final-window"
            displaced = self.base / "held-run-root-final-window"
            victim = self.base / "run-root-final-window-victim"
            victim.mkdir()

            def install_substitute(parent_fd, name):
                os.symlink(str(victim), name, dir_fd=parent_fd)

            state, injector = self._quarantine_race_injector(
                run_root.name,
                displaced.name,
                install_substitute,
            )
            with mock.patch.object(
                G012.os,
                "fchmod",
                side_effect=OSError("injected run-root cleanup failure"),
            ), mock.patch.object(
                G012,
                "_rename_noreplace",
                side_effect=injector,
            ):
                with self.assertRaisesRegex(OSError, "run-root cleanup failure"):
                    G012._prepare_run_root(str(run_root), layout)
            self.assertTrue(state["candidate_swapped"])
            self.assertTrue(run_root.is_symlink())
            self.assertEqual([], list(victim.iterdir()))
            self.assertTrue(displaced.is_dir())
            self.assertEqual(
                [],
                list(self.base.glob(".g012-quarantine-*")),
            )
        finally:
            layout.close()

    def test_clone_cleanup_quarantines_final_window_substitution(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            leaf = "clone-final-window.git"
            displaced = "held-clone-final-window.git"
            victim = self.base / "clone-final-window-victim"
            victim.mkdir()

            def install_substitute(parent_fd, name):
                os.symlink(str(victim), name, dir_fd=parent_fd)

            state, injector = self._quarantine_race_injector(
                leaf,
                displaced,
                install_substitute,
            )

            def fail_clone_with_partial(command, *args, **kwargs):
                destination_descriptor = int(Path(command[-1]).name)
                partial = os.open(
                    "partial",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=destination_descriptor,
                )
                try:
                    os.write(partial, b"partial clone")
                finally:
                    os.close(partial)
                raise G012.RemediationError("injected clone cleanup failure")

            with mock.patch.object(
                G012,
                "_run",
                side_effect=fail_clone_with_partial,
            ), mock.patch.object(
                G012,
                "_rename_noreplace",
                side_effect=injector,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "clone cleanup failure",
                ):
                    G012._clone_mirror(
                        self.source,
                        anchor.command_path / leaf,
                    )
            self.assertTrue(state["candidate_swapped"])
            self.assertTrue((self.run_root / leaf).is_symlink())
            self.assertEqual([], list(victim.iterdir()))
            self.assertTrue((self.run_root / displaced / "partial").is_file())
            self.assertEqual(
                [],
                list(self.run_root.glob(".g012-quarantine-*")),
            )
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_bundle_cleanup_quarantines_final_window_substitution(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            leaf = "bundle-final-window.bundle"
            displaced = "held-bundle-final-window.bundle"
            victim = self.base / "bundle-final-window-victim"
            victim.write_bytes(b"bundle victim")

            def install_substitute(parent_fd, name):
                os.symlink(str(victim), name, dir_fd=parent_fd)

            state, injector = self._quarantine_race_injector(
                leaf,
                displaced,
                install_substitute,
            )

            def fail_bundle_with_partial(repo, refs, output):
                os.write(output.descriptor, b"partial bundle")
                raise G012.RemediationError("injected bundle cleanup failure")

            with mock.patch.object(
                G012,
                "_run_git_bundle_to_fd",
                side_effect=fail_bundle_with_partial,
            ), mock.patch.object(
                G012,
                "_rename_noreplace",
                side_effect=injector,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "bundle cleanup failure",
                ):
                    G012._bundle(
                        self.source,
                        anchor.command_path / leaf,
                        ["refs/heads/main"],
                    )
            self.assertTrue(state["candidate_swapped"])
            self.assertTrue((self.run_root / leaf).is_symlink())
            self.assertEqual(b"bundle victim", victim.read_bytes())
            self.assertTrue((self.run_root / displaced).is_file())
            self.assertEqual(
                [],
                list(self.run_root.glob(".g012-quarantine-*")),
            )
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_unsafe_quarantine_restoration_retains_without_overwrite(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            leaf = "unsafe-restore.bin"
            displaced = "held-unsafe-restore.bin"
            first_victim = self.base / "unsafe-restore-first-victim"
            second_victim = self.base / "unsafe-restore-second-victim"
            first_victim.write_bytes(b"first victim")
            second_victim.write_bytes(b"second victim")

            def install_substitute(parent_fd, name):
                os.symlink(str(first_victim), name, dir_fd=parent_fd)

            def occupy_final_before_restore(parent_fd, name):
                os.symlink(str(second_victim), name, dir_fd=parent_fd)

            state, injector = self._quarantine_race_injector(
                leaf,
                displaced,
                install_substitute,
                before_restore=occupy_final_before_restore,
            )

            def fail_after_partial_write(descriptor, payload):
                os.write(descriptor, payload[:4])
                raise OSError("injected unsafe restoration failure")

            with mock.patch.object(
                G012,
                "_write_all",
                side_effect=fail_after_partial_write,
            ), mock.patch.object(
                G012,
                "_rename_noreplace",
                side_effect=injector,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "retained without overwrite",
                ):
                    G012._secure_create_output(
                        anchor.command_path / leaf,
                        b"owned unsafe restore partial",
                        "unsafe quarantine restoration",
                    )
            self.assertTrue(state["candidate_swapped"])
            self.assertTrue(state["restore_interposed"])
            self.assertTrue((self.run_root / leaf).is_symlink())
            self.assertEqual(
                str(second_victim),
                os.readlink(self.run_root / leaf),
            )
            quarantines = list(
                self.run_root.glob(".g012-quarantine-*")
            )
            self.assertEqual(1, len(quarantines))
            self.assertTrue(quarantines[0].is_symlink())
            self.assertEqual(str(first_victim), os.readlink(quarantines[0]))
            self.assertEqual(b"first victim", first_victim.read_bytes())
            self.assertEqual(b"second victim", second_victim.read_bytes())
            self.assertTrue((self.run_root / displaced).is_file())
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_construction_cleanup_never_removes_substituted_file_or_directory(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)

            file_name = "construct-file-substitute.bin"
            displaced_file_name = "held-construct-file.bin"
            file_victim = self.base / "construct-file-victim"
            file_victim.write_bytes(b"file victim")

            def substitute_file_before_fchmod(descriptor, mode):
                os.rename(
                    file_name,
                    displaced_file_name,
                    src_dir_fd=anchor.held.descriptor,
                    dst_dir_fd=anchor.held.descriptor,
                )
                os.symlink(
                    str(file_victim),
                    file_name,
                    dir_fd=anchor.held.descriptor,
                )
                raise OSError("injected substituted file construction failure")

            with mock.patch.object(
                G012.os,
                "fchmod",
                side_effect=substitute_file_before_fchmod,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "substituted file construction",
                ):
                    G012._secure_create_output(
                        anchor.command_path / file_name,
                        b"held file bytes",
                        "substituted file construction",
                    )
            self.assertTrue((self.run_root / file_name).is_symlink())
            self.assertEqual(b"file victim", file_victim.read_bytes())
            self.assertTrue((self.run_root / displaced_file_name).is_file())

            directory_name = "construct-dir-substitute.git"
            displaced_directory_name = "held-construct-dir.git"
            directory_victim = self.base / "construct-directory-victim"
            directory_victim.mkdir()
            real_open = G012.os.open

            def substitute_directory_before_open(path, flags, *args, **kwargs):
                if path == directory_name and flags & os.O_DIRECTORY:
                    os.rename(
                        directory_name,
                        displaced_directory_name,
                        src_dir_fd=anchor.held.descriptor,
                        dst_dir_fd=anchor.held.descriptor,
                    )
                    os.symlink(
                        str(directory_victim),
                        directory_name,
                        dir_fd=anchor.held.descriptor,
                    )
                    raise OSError(
                        "injected substituted directory construction failure"
                    )
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                G012.os,
                "open",
                side_effect=substitute_directory_before_open,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "substituted directory construction",
                ):
                    G012._prepare_exclusive_destination(
                        anchor.command_path / directory_name,
                        "substituted directory construction",
                    )
            self.assertTrue((self.run_root / directory_name).is_symlink())
            self.assertEqual([], list(directory_victim.iterdir()))
            self.assertTrue(
                (self.run_root / displaced_directory_name).is_dir()
            )
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_bundle_fsync_and_hash_failures_remove_owned_output(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            fsync_name = "bundle-fsync-failure.bundle"
            with mock.patch.object(
                G012.SecureOutputFile,
                "fsync",
                side_effect=OSError("injected bundle fsync failure"),
            ):
                with self.assertRaisesRegex(OSError, "bundle fsync failure"):
                    G012._bundle(
                        self.source,
                        anchor.command_path / fsync_name,
                        ["refs/heads/main"],
                    )
            self.assertFalse((self.run_root / fsync_name).exists())

            hash_name = "bundle-hash-failure.bundle"
            with mock.patch.object(
                G012,
                "_hash_open_descriptor",
                side_effect=OSError("injected bundle hash failure"),
            ):
                with self.assertRaisesRegex(OSError, "bundle hash failure"):
                    G012._bundle(
                        self.source,
                        anchor.command_path / hash_name,
                        ["refs/heads/main"],
                    )
            self.assertFalse((self.run_root / hash_name).exists())
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_failed_clone_and_bundle_remove_owned_partial_artifacts(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            mirror_name = "partial-mirror.git"

            def fail_clone_after_partial_write(command, *args, **kwargs):
                destination_descriptor = int(Path(command[-1]).name)
                partial = os.open(
                    "partial",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=destination_descriptor,
                )
                try:
                    os.write(partial, b"partial clone")
                finally:
                    os.close(partial)
                raise G012.RemediationError("injected clone failure")

            with mock.patch.object(
                G012,
                "_run",
                side_effect=fail_clone_after_partial_write,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "injected clone failure",
                ):
                    G012._clone_mirror(
                        self.source,
                        anchor.command_path / mirror_name,
                    )
            self.assertFalse((self.run_root / mirror_name).exists())

            bundle_name = "partial.bundle"

            def fail_bundle_after_partial_write(repo, refs, output):
                os.write(output.descriptor, b"partial bundle")
                raise G012.RemediationError("injected bundle failure")

            with mock.patch.object(
                G012,
                "_run_git_bundle_to_fd",
                side_effect=fail_bundle_after_partial_write,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "injected bundle failure",
                ):
                    G012._bundle(
                        self.source,
                        anchor.command_path / bundle_name,
                        ["refs/heads/main"],
                    )
            self.assertFalse((self.run_root / bundle_name).exists())
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_bundle_hashes_and_verifies_the_same_held_descriptor(self):
        layout = G012._resolve_repository(str(self.source.resolve()))
        anchor = None
        try:
            anchor = G012._prepare_run_root(str(self.run_root.absolute()), layout)
            real_stream = G012._run_git_bundle_to_fd
            real_hash = G012._hash_open_descriptor
            stream_descriptors = []
            hash_descriptors = []

            def capture_stream(repo, refs, output):
                stream_descriptors.append(output.descriptor)
                return real_stream(repo, refs, output)

            def capture_hash(descriptor, maximum, label):
                hash_descriptors.append(descriptor)
                return real_hash(descriptor, maximum, label)

            with mock.patch.object(
                G012,
                "_run_git_bundle_to_fd",
                side_effect=capture_stream,
            ), mock.patch.object(
                G012,
                "_hash_open_descriptor",
                side_effect=capture_hash,
            ):
                G012._bundle(
                    self.source,
                    anchor.command_path / "same-fd.bundle",
                    ["refs/heads/main"],
                )
            self.assertEqual(1, len(stream_descriptors))
            self.assertEqual(
                [stream_descriptors[0], stream_descriptors[0]],
                hash_descriptors,
            )
            git(
                self.source,
                "bundle",
                "verify",
                self.run_root / "same-fd.bundle",
            )
        finally:
            if anchor is not None:
                anchor.close()
            layout.close()

    def test_filter_repo_executes_sealed_memfd_after_evidence_copy_replacement(self):
        marker = self.base / "replacement-tool-executed"
        invoke = G012._invoke_filter_repo

        def replace_evidence_before_invocation(tool, *args, **kwargs):
            replacement = tool.evidence_path.with_name("atomic-replacement")
            replacement.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
                "raise SystemExit(97)\n",
                encoding="utf-8",
            )
            replacement.chmod(0o500)
            os.replace(replacement, tool.evidence_path)
            return invoke(tool, *args, **kwargs)

        args = Namespace(
            command="dry-run",
            source=str(self.source.resolve()),
            run_root=str(self.run_root.resolve()),
            filter_repo_tool=str(AUDITED_FILTER_REPO),
            g007_archive=None,
        )
        with mock.patch.object(
            G012,
            "_invoke_filter_repo",
            side_effect=replace_evidence_before_invocation,
        ):
            result = G012.guarded_dry_run(args)
        self.assertTrue(result["completed"])
        self.assertFalse(marker.exists())
        self.assertEqual(
            "sealed memfd via /proc/self/fd",
            result["filter_repo"]["execution_source"],
        )
        self.assertTrue(result["filter_repo"]["evidence_substitution_detected"])
        quarantined = self.run_root / result["filter_repo"]["evidence_path"]
        self.assertEqual(
            AUDITED_FILTER_REPO_SHA256,
            hashlib.sha256(quarantined.read_bytes()).hexdigest(),
        )
        self.assertEqual(0o500, quarantined.stat().st_mode & 0o777)
        self.assertTrue((self.run_root / "rewritten-sanitized.bundle").is_file())

    def test_symbolic_ref_records_and_bundle_restoration_are_exact(self):
        self._commit_positive_history()
        git(
            self.source,
            "symbolic-ref",
            "refs/heads/review-alias",
            "refs/heads/main",
        )
        completed = self._dry_run()
        self.assertEqual(
            0, completed.returncode, completed.stderr.decode("utf-8", "replace")
        )

        refs_before = G012._read_refs(self.run_root / "refs-before.tsv")
        refs_after = G012._read_refs(self.run_root / "refs-after.tsv")
        before_alias = next(
            row for row in refs_before if row["ref"] == "refs/heads/review-alias"
        )
        after_alias = next(
            row for row in refs_after if row["ref"] == "refs/heads/review-alias"
        )
        self.assertEqual("refs/heads/main", before_alias["symref"])
        self.assertEqual("refs/heads/main", after_alias["symref"])
        for repository_name in (
            "disposable-mirror.git",
            "independent-sanitized.git",
        ):
            G012._require_exact_refs(
                sorted(
                    [
                        *refs_after,
                        *G012._read_refs(
                            self.run_root / "evidence-refs-after.tsv"
                        ),
                    ],
                    key=lambda row: row["ref"],
                ),
                G012._refs(self.run_root / repository_name),
                repository_name,
            )

        restored = self.base / "symbolic-rewritten-restored.git"
        run(
            [
                "git",
                "clone",
                "--mirror",
                self.run_root / "rewritten-sanitized.bundle",
                restored,
            ]
        )
        self.assertEqual(
            "",
            next(
                row
                for row in G012._refs(restored)
                if row["ref"] == "refs/heads/review-alias"
            )["symref"],
        )
        G012._restore_symbolic_refs(restored, refs_after, "test bundle restore")
        G012._require_exact_refs(refs_after, G012._refs(restored), "test bundle restore")
        inventory = G012._validate_cleaned_object_inventory(
            json.loads(
                (
                    self.run_root / "manifests/cleaned-object-inventory.json"
                ).read_text(encoding="utf-8")
            )
        )
        G012._verify_cleaned_object_scope(
            restored,
            refs_after,
            inventory["publishable"],
            "test publishable bundle objects",
        )

        evidence_after = G012._read_refs(
            self.run_root / "evidence-refs-after.tsv"
        )
        evidence_restored = self.base / "symbolic-evidence-restored.git"
        run(
            [
                "git",
                "clone",
                "--mirror",
                self.run_root / "rewritten-evidence.bundle",
                evidence_restored,
            ]
        )
        G012._restore_symbolic_refs(
            evidence_restored, evidence_after, "test evidence bundle restore"
        )
        G012._require_exact_refs(
            evidence_after,
            G012._refs(evidence_restored),
            "test evidence bundle restore",
        )
        G012._verify_cleaned_object_scope(
            evidence_restored,
            evidence_after,
            inventory["evidence"],
            "test evidence bundle objects",
        )

        mirror = self.run_root / "disposable-mirror.git"
        alias_oid = git(
            mirror, "rev-parse", "refs/heads/review-alias"
        ).stdout.decode().strip()
        git(
            mirror,
            "update-ref",
            "--no-deref",
            "refs/heads/review-alias",
            alias_oid,
        )
        verified = run(
            [
                sys.executable,
                PROGRAM,
                "verify",
                "--run-root",
                self.run_root.resolve(),
            ],
            check=False,
        )
        self.assertEqual(2, verified.returncode)
        self.assertIn(b"complete object_type/symref records", verified.stderr)

    def test_presealing_unreachable_object_is_rejected(self):
        establish = G012._establish_cleaned_object_inventory

        def inject_before_inventory(repository, *args, **kwargs):
            G012._git(
                repository,
                "hash-object",
                "-w",
                "--stdin",
                input_bytes=b"unreachable pre-sealing object\n",
            )
            return establish(repository, *args, **kwargs)

        args = Namespace(
            command="dry-run",
            source=str(self.source.resolve()),
            run_root=str(self.run_root.resolve()),
            filter_repo_tool=str(AUDITED_FILTER_REPO),
            g007_archive=None,
        )
        with mock.patch.object(
            G012,
            "_establish_cleaned_object_inventory",
            side_effect=inject_before_inventory,
        ):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "pre-sealing cleaned mirror extra/missing physical Git objects",
            ):
                G012.guarded_dry_run(args)
        self.assertFalse((self.run_root / "rewritten-sanitized.bundle").exists())

    def test_verify_rejects_postrun_unreachable_object(self):
        completed = self._dry_run()
        self.assertEqual(
            0, completed.returncode, completed.stderr.decode("utf-8", "replace")
        )
        mirror = self.run_root / "disposable-mirror.git"
        git(
            mirror,
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=b"unreachable post-run object\n",
        )
        verified = run(
            [
                sys.executable,
                PROGRAM,
                "verify",
                "--run-root",
                self.run_root.resolve(),
            ],
            check=False,
        )
        self.assertEqual(2, verified.returncode)
        self.assertIn(b"extra/missing physical Git objects", verified.stderr)

    def test_detached_head_is_captured_sanitized_and_bundled(self):
        git(self.source, "switch", "--detach")
        write(self.source / "detached-safe.txt", "detached safe\n")
        write(
            self.source / "vendor/hikmicro_analyzer/detached-secret.bin",
            b"detached guarded bytes",
        )
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "detached history")
        detached_oid = git(self.source, "rev-parse", "HEAD").stdout.decode().strip()

        completed = self._dry_run()
        self.assertEqual(
            0, completed.returncode, completed.stderr.decode("utf-8", "replace")
        )
        mirror = self.run_root / "disposable-mirror.git"
        captured = "refs/g012-captured/head-0"
        self.assertEqual(
            b"detached safe\n",
            git(mirror, "show", f"{captured}:detached-safe.txt").stdout,
        )
        history = git(mirror, "log", captured, "--format=", "--name-only").stdout
        self.assertNotIn(b"detached-secret.bin", history)
        remediation = json.loads(
            (self.run_root / "manifests/remediation-inputs.json").read_text()
        )
        self.assertTrue(
            any(
                row["name"] == "HEAD"
                and row["oid"] == detached_oid
                and row["captured_ref"] == captured
                for row in remediation["captured_pseudorefs"]
            )
        )
        independent = self.run_root / "independent-sanitized.git"
        self.assertEqual(
            b"detached safe\n",
            git(independent, "show", f"{captured}:detached-safe.txt").stdout,
        )

    def test_auto_merge_tree_pseudoref_is_wrapped_and_sanitized(self):
        index = self.base / "auto-merge.index"
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(index)
        git(self.source, "read-tree", "HEAD", env=env)
        safe_blob = git(
            self.source,
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=b"auto-merge safe\n",
        ).stdout.decode().strip()
        guarded_blob = git(
            self.source,
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=b"auto-merge guarded\n",
        ).stdout.decode().strip()
        git(
            self.source,
            "update-index",
            "--add",
            "--cacheinfo",
            "100644",
            safe_blob,
            "auto-merge-safe.txt",
            env=env,
        )
        git(
            self.source,
            "update-index",
            "--add",
            "--cacheinfo",
            "100644",
            guarded_blob,
            "vendor/hikmicro_analyzer/auto-merge-secret.bin",
            env=env,
        )
        tree = git(self.source, "write-tree", env=env).stdout.decode().strip()
        git_dir = Path(
            git(self.source, "rev-parse", "--absolute-git-dir").stdout.decode().strip()
        )
        write(git_dir / "AUTO_MERGE", tree + "\n")

        completed = self._dry_run()
        self.assertEqual(
            0, completed.returncode, completed.stderr.decode("utf-8", "replace")
        )
        captured = "refs/g012-captured/auto-merge-0"
        mirror = self.run_root / "disposable-mirror.git"
        self.assertEqual(
            b"auto-merge safe\n",
            git(mirror, "show", f"{captured}:auto-merge-safe.txt").stdout,
        )
        history = git(mirror, "log", captured, "--format=", "--name-only").stdout
        self.assertNotIn(b"auto-merge-secret.bin", history)

    def test_rejects_unaccounted_object_bearing_pseudoref(self):
        unreferenced = git(
            self.source,
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=b"unreferenced unknown admin root\n",
        ).stdout.decode().strip()
        git_dir = Path(
            git(self.source, "rev-parse", "--absolute-git-dir").stdout.decode().strip()
        )
        write(git_dir / "secret-object-root", unreferenced + "\n")
        completed = self._dry_run()
        self.assertEqual(2, completed.returncode)
        self.assertIn(b"unaccounted object-bearing pseudoref", completed.stderr)

    def test_rejects_forbidden_commit_message_before_rewrite(self):
        write(self.source / "message-safe.txt", "safe bytes\n")
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "jadx decompiled source details")
        completed = self._dry_run()
        self.assertEqual(2, completed.returncode)
        self.assertIn(b"prohibited_metadata", completed.stderr)

    def test_rejects_forbidden_annotated_tag_metadata_before_rewrite(self):
        git(self.source, "tag", "-a", "bad-tag", "-m", "smali source listing")
        completed = self._dry_run()
        self.assertEqual(2, completed.returncode)
        self.assertIn(b"prohibited_metadata", completed.stderr)

    def test_rejects_signed_annotated_tag_before_rewrite(self):
        target = git(self.source, "rev-parse", "HEAD").stdout.decode().strip()
        tag_payload = (
            f"object {target}\n"
            "type commit\n"
            "tag synthetic-signed\n"
            "tagger G012 Test <g012@example.invalid> 946684800 +0000\n"
            "\n"
            "safe tag message\n"
            "-----BEGIN PGP SIGNATURE-----\n"
            "synthetic-test-signature\n"
            "-----END PGP SIGNATURE-----\n"
        ).encode()
        tag_oid = git(
            self.source,
            "hash-object",
            "-t",
            "tag",
            "-w",
            "--stdin",
            input_bytes=tag_payload,
        ).stdout.decode().strip()
        git(self.source, "update-ref", "refs/tags/synthetic-signed", tag_oid)
        completed = self._dry_run()
        self.assertEqual(2, completed.returncode)
        self.assertIn(b"signed_annotated_tag", completed.stderr)

    def test_source_mutation_guard_detects_change_during_rewrite(self):
        self._commit_positive_history()
        dirty = self.source / "safe.txt"
        dirty.write_text("dirty-A0\n", encoding="utf-8")
        original_stat = dirty.stat()
        status_before = git(
            self.source, "status", "--porcelain=v2", "-z", "--untracked-files=all"
        ).stdout
        invoke = G012._invoke_filter_repo

        def mutate_after_real_rewrite(*args, **kwargs):
            result = invoke(*args, **kwargs)
            dirty.write_text("dirty-B0\n", encoding="utf-8")
            os.utime(
                dirty,
                ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
            )
            return result

        args = Namespace(
            command="dry-run",
            source=str(self.source.resolve()),
            run_root=str(self.run_root.resolve()),
            filter_repo_tool=str(AUDITED_FILTER_REPO),
            g007_archive=None,
        )
        with mock.patch.object(
            G012, "_invoke_filter_repo", side_effect=mutate_after_real_rewrite
        ):
            with self.assertRaisesRegex(
                G012.RemediationError, "source mutation guard failed"
            ):
                G012.guarded_dry_run(args)
        status_after = git(
            self.source, "status", "--porcelain=v2", "-z", "--untracked-files=all"
        ).stdout
        self.assertEqual(status_before, status_after)

    def test_source_guard_detects_pseudoref_and_sequencer_state_changes(self):
        git_dir = Path(
            git(self.source, "rev-parse", "--absolute-git-dir").stdout.decode().strip()
        )
        layout = G012._resolve_repository(str(self.source.resolve()))
        baseline_admin = G012._source_state(layout)["git_admin_state_inventory"]

        empty_rebase = git_dir / "rebase-apply"
        empty_rebase.mkdir(mode=0o700)
        added_admin = G012._source_state(layout)["git_admin_state_inventory"]
        self.assertNotEqual(
            baseline_admin["inventory_sha256"],
            added_admin["inventory_sha256"],
            "adding an empty administrative directory must change the guard",
        )
        self.assertEqual(
            baseline_admin["directory_count"] + 1,
            added_admin["directory_count"],
        )
        empty_rebase.rmdir()
        removed_admin = G012._source_state(layout)["git_admin_state_inventory"]
        self.assertNotEqual(
            added_admin["inventory_sha256"],
            removed_admin["inventory_sha256"],
            "removing an empty administrative directory must change the guard",
        )
        self.assertEqual(
            baseline_admin["inventory_sha256"],
            removed_admin["inventory_sha256"],
        )

        sequencer = git_dir / "sequencer"
        sequencer.mkdir(mode=0o700)
        mode_before = G012._source_state(layout)["git_admin_state_inventory"]
        sequencer.chmod(0o500)
        mode_after = G012._source_state(layout)["git_admin_state_inventory"]
        self.assertNotEqual(
            mode_before["inventory_sha256"],
            mode_after["inventory_sha256"],
            "administrative directory mode changes must alter the guard",
        )
        sequencer.chmod(0o700)
        write(sequencer / "todo", "initial sequencer state\n")
        orig_head = git_dir / "ORIG_HEAD"
        self.assertFalse(orig_head.exists())
        invoke = G012._invoke_filter_repo

        def mutate_admin_state_after_rewrite(*args, **kwargs):
            result = invoke(*args, **kwargs)
            head = git(self.source, "rev-parse", "HEAD").stdout.decode().strip()
            write(orig_head, head + "\n")
            write(sequencer / "todo", "changed sequencer state\n")
            return result

        args = Namespace(
            command="dry-run",
            source=str(self.source.resolve()),
            run_root=str(self.run_root.resolve()),
            filter_repo_tool=str(AUDITED_FILTER_REPO),
            g007_archive=None,
        )
        with mock.patch.object(
            G012,
            "_invoke_filter_repo",
            side_effect=mutate_admin_state_after_rewrite,
        ):
            with self.assertRaisesRegex(
                G012.RemediationError, "source mutation guard failed"
            ):
                G012.guarded_dry_run(args)
        after = json.loads(
            (
                self.run_root / "manifests/source-state-after.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn("git_admin_state_inventory", after)

    def test_unknown_bisect_file_with_unreferenced_object_fails_closed(self):
        git_dir = Path(
            git(self.source, "rev-parse", "--absolute-git-dir")
            .stdout.decode()
            .strip()
        )
        unreferenced = git(
            self.source,
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=b"unreferenced bisect object\n",
        ).stdout.decode().strip()
        write(git_dir / "BISECT_EXPECTED_REV", unreferenced + "\n")
        layout = G012._resolve_repository(str(self.source.resolve()))
        with self.assertRaisesRegex(
            G012.RemediationError,
            "unaccounted object-bearing pseudoref/Git administrative file",
        ):
            G012._source_state(layout)

    def test_nested_sequencer_todo_with_unreferenced_commit_fails_closed(self):
        git_dir = Path(
            git(self.source, "rev-parse", "--absolute-git-dir")
            .stdout.decode()
            .strip()
        )
        tree = git(
            self.source, "rev-parse", "HEAD^{tree}"
        ).stdout.decode().strip()
        unreferenced = git(
            self.source,
            "commit-tree",
            tree,
            "-m",
            "unreferenced sequencer commit",
        ).stdout.decode().strip()
        write(
            git_dir / "sequencer/todo",
            f"pick {unreferenced} unreferenced sequencer commit\n",
        )
        layout = G012._resolve_repository(str(self.source.resolve()))
        with self.assertRaisesRegex(
            G012.RemediationError,
            "unaccounted object-bearing pseudoref/Git administrative file",
        ):
            G012._source_state(layout)

    def test_abbreviated_admin_object_ids_fail_closed_at_7_12_and_39_hex(self):
        git_dir = Path(
            git(self.source, "rev-parse", "--absolute-git-dir")
            .stdout.decode()
            .strip()
        )
        tree = git(
            self.source, "rev-parse", "HEAD^{tree}"
        ).stdout.decode().strip()
        unreferenced = git(
            self.source,
            "commit-tree",
            tree,
            "-m",
            "unreferenced abbreviated admin commit",
        ).stdout.decode().strip()
        layout = G012._resolve_repository(str(self.source.resolve()))
        cases = (
            (7, git_dir / "sequencer/todo", "pick {token} abbreviated\n"),
            (
                12,
                git_dir / "rebase-merge/git-rebase-todo",
                "pick {token} abbreviated\n",
            ),
            (
                39,
                git_dir / "rebase-apply/original-commit",
                "{token}\n",
            ),
        )
        for length, path, template in cases:
            with self.subTest(length=length, path=path):
                token = unreferenced[:length]
                self.assertEqual(
                    [unreferenced],
                    G012._resolve_admin_object_token(layout, token),
                )
                write(path, template.format(token=token))
                try:
                    with self.assertRaisesRegex(
                        G012.RemediationError,
                        "unaccounted object-bearing pseudoref/Git "
                        "administrative file",
                    ):
                        G012._source_state(layout)
                finally:
                    path.unlink()

    def test_ambiguous_abbreviated_admin_object_id_fails_closed(self):
        token = "abcdef0"
        first = token + ("0" * (40 - len(token)))
        second = token + ("1" * (40 - len(token)))
        with mock.patch.object(
            G012,
            "_git",
            return_value=f"{first}\n{second}\n".encode("ascii"),
        ):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "ambiguous abbreviated object ID",
            ):
                G012._resolve_admin_object_token(self.source, token)

    def test_reachable_abbreviated_admin_object_id_is_not_a_new_root(self):
        git_dir = Path(
            git(self.source, "rev-parse", "--absolute-git-dir")
            .stdout.decode()
            .strip()
        )
        head = git(self.source, "rev-parse", "HEAD").stdout.decode().strip()
        note = git_dir / "sequencer/reachable-note"
        write(note, f"pick {head[:12]} already reachable\n")
        layout = G012._resolve_repository(str(self.source.resolve()))
        state = G012._source_state(layout)
        self.assertEqual(head, state["head_oid"])

    def test_admin_prescan_and_inventory_share_one_global_budget(self):
        git_dir = Path(
            git(self.source, "rev-parse", "--absolute-git-dir")
            .stdout.decode()
            .strip()
        )
        payload = b"Z" * 8192
        note = git_dir / "sequencer/budget-note"
        write(note, payload)
        layout = G012._resolve_repository(str(self.source.resolve()))
        state = G012._source_state(layout)
        budget = state["logical_byte_budget"]
        charges = {
            row["label"]: row["size_bytes"]
            for row in budget["charges"]
        }
        self.assertEqual(
            len(payload),
            charges["admin-prescan:sequencer/budget-note"],
        )
        self.assertEqual(
            len(payload),
            charges["git-dir/sequencer/budget-note"],
        )
        with self.assertRaisesRegex(
            G012.RemediationError,
            "global source-state logical-byte budget exceeded before reading",
        ):
            G012._source_state(
                layout,
                maximum_total_bytes=(
                    budget["consumed_bytes"] - len(payload)
                ),
            )

    def test_sibling_linked_worktree_detached_head_is_rejected(self):
        current = self.base / "current-linked-worktree"
        sibling = self.base / "sibling-linked-worktree"
        git(
            self.source,
            "worktree",
            "add",
            "-b",
            "g012-current-linked",
            current,
        )
        git(
            self.source,
            "worktree",
            "add",
            "--detach",
            sibling,
            "HEAD",
        )
        sibling_head = git(
            sibling, "rev-parse", "HEAD"
        ).stdout.decode().strip()
        self.assertEqual(
            sibling_head,
            git(
                sibling, "rev-parse", "--verify", "HEAD"
            ).stdout.decode().strip(),
        )
        with self.assertRaisesRegex(
            G012.RemediationError,
            "outside the lifetime-anchored source worktree|"
            "sibling linked worktrees are conservatively unsupported",
        ):
            G012._resolve_repository(str(current.resolve()))

    def test_linked_worktree_external_admin_is_rejected(self):
        linked = self.base / "linked-worktree"
        git(
            self.source,
            "worktree",
            "add",
            "-b",
            "g012-linked-worktree",
            linked,
        )
        head_before = git(linked, "rev-parse", "HEAD").stdout
        with self.assertRaisesRegex(
            G012.RemediationError,
            "outside the lifetime-anchored source worktree",
        ):
            G012._resolve_repository(str(linked.resolve()))
        self.assertEqual(head_before, git(linked, "rev-parse", "HEAD").stdout)

    def test_whole_run_source_root_aba_cannot_redirect_initial_mirror(self):
        attacker = self.base / "attacker-source"
        attacker.mkdir()
        git(attacker, "init", "-b", "main")
        git(attacker, "config", "user.name", "G012 Attacker")
        git(attacker, "config", "user.email", "attacker@example.invalid")
        write(attacker / "attacker-only.txt", "attacker repository\n")
        git(attacker, "add", ".")
        git(attacker, "commit", "-m", "attacker history")

        held_source = self.base / "held-original-source"
        actual_run = G012._run
        swapped = False

        def swap_for_anchored_clone(command, *args, **kwargs):
            nonlocal swapped
            is_source_clone = (
                not swapped
                and "clone" in command
                and "--mirror" in command
                and "--local" in command
                and len(command) >= 2
                and str(command[-2]).startswith("/proc/self/fd/")
            )
            if not is_source_clone:
                return actual_run(command, *args, **kwargs)
            swapped = True
            self.source.rename(held_source)
            attacker.rename(self.source)
            try:
                return actual_run(command, *args, **kwargs)
            finally:
                self.source.rename(attacker)
                held_source.rename(self.source)

        args = Namespace(
            command="dry-run",
            source=str(self.source.resolve()),
            run_root=str(self.run_root.resolve()),
            filter_repo_tool=str(AUDITED_FILTER_REPO),
            g007_archive=None,
        )
        with mock.patch.object(G012, "_run", side_effect=swap_for_anchored_clone):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "topology changed|source repository",
            ):
                G012.guarded_dry_run(args)
        self.assertTrue(swapped, "the source clone ABA probe did not execute")
        mirror = self.run_root / "disposable-mirror.git"
        self.assertTrue(mirror.is_dir())
        self.assertEqual(
            b"safe root file\n",
            git(mirror, "show", "refs/heads/main:safe.txt").stdout,
        )
        self.assertNotEqual(
            0,
            git(
                mirror,
                "show",
                "refs/heads/main:attacker-only.txt",
                check=False,
            ).returncode,
            "a mutable source pathname redirected the initial mirror",
        )

    def test_source_guard_detects_same_size_raw_alternate_object_corruption(self):
        alternate, _alternates = self._configure_real_alternate(internal=True)
        loose_objects = [
            path
            for directory in (alternate / "objects").iterdir()
            if directory.is_dir()
            and len(directory.name) == 2
            and all(character in "0123456789abcdef" for character in directory.name)
            for path in directory.iterdir()
            if path.is_file()
        ]
        self.assertTrue(loose_objects)
        target = loose_objects[0]
        original = target.read_bytes()
        invoke = G012._invoke_filter_repo

        def corrupt_after_real_rewrite(*args, **kwargs):
            result = invoke(*args, **kwargs)
            changed = bytearray(original)
            changed[-1] ^= 0x01
            target.write_bytes(changed)
            self.assertEqual(len(original), target.stat().st_size)
            return result

        args = Namespace(
            command="dry-run",
            source=str(self.source.resolve()),
            run_root=str(self.run_root.resolve()),
            filter_repo_tool=str(AUDITED_FILTER_REPO),
            g007_archive=None,
        )
        with mock.patch.object(
            G012, "_invoke_filter_repo", side_effect=corrupt_after_real_rewrite
        ):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "source git fsck --full --strict failed|"
                "source mutation guard failed|"
                "loose object .* is corrupt",
            ):
                G012.guarded_dry_run(args)

    def test_verify_rejects_every_sha256sums_structure_and_integrity_defect(self):
        self._commit_positive_history()
        completed = self._dry_run()
        self.assertEqual(
            0, completed.returncode, completed.stderr.decode("utf-8", "replace")
        )
        sums = self.run_root / "SHA256SUMS"
        original = sums.read_text()
        lines = original.splitlines()

        def verify_failure(expected):
            result = run(
                [
                    sys.executable,
                    PROGRAM,
                    "verify",
                    "--run-root",
                    self.run_root.resolve(),
                ],
                check=False,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn(expected, result.stderr)

        cases = {
            "missing": ("\n".join(lines[1:]) + "\n", b"artifact allowlist"),
            "duplicate": (original + lines[0] + "\n", b"duplicate SHA256SUMS"),
            "malformed": (original + "not-a-record\n", b"malformed SHA256SUMS"),
            "absolute": (
                original + f"{'0' * 64}  /absolute/path\n",
                b"unsafe SHA256SUMS path",
            ),
            "traversal": (
                original + f"{'0' * 64}  ../escape\n",
                b"unsafe SHA256SUMS path",
            ),
            "digest": (
                f"{'0' * 64}{lines[0][64:]}\n" + "\n".join(lines[1:]) + "\n",
                b"digest mismatch",
            ),
        }
        for name, (payload, expected) in cases.items():
            with self.subTest(name=name):
                sums.write_text(payload)
                verify_failure(expected)
                sums.write_text(original)

        extra = self.run_root / "unexpected.txt"
        extra.write_text("unexpected\n")
        verify_failure(b"artifact set is incomplete or has extras")
        extra.unlink()
        sums.write_text(original)
        valid = run(
            [
                sys.executable,
                PROGRAM,
                "verify",
                "--run-root",
                self.run_root.resolve(),
            ],
            check=False,
        )
        self.assertEqual(0, valid.returncode, valid.stderr.decode())

    def test_verify_rejects_ref_object_and_internal_symlink_drift(self):
        self._commit_positive_history()
        completed = self._dry_run()
        self.assertEqual(
            0, completed.returncode, completed.stderr.decode("utf-8", "replace")
        )
        mirror = self.run_root / "disposable-mirror.git"
        independent = self.run_root / "independent-sanitized.git"

        def verify_failure(expected):
            result = run(
                [
                    sys.executable,
                    PROGRAM,
                    "verify",
                    "--run-root",
                    self.run_root.resolve(),
                ],
                check=False,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn(expected, result.stderr)

        main = git(mirror, "rev-parse", "refs/heads/main").stdout.decode().strip()
        git(mirror, "update-ref", "refs/heads/safe-extra", main)
        verify_failure(b"ref/OID mismatch")
        git(mirror, "update-ref", "-d", "refs/heads/safe-extra")

        git(independent, "update-ref", "refs/heads/safe-extra", main)
        verify_failure(b"ref/OID mismatch")
        git(independent, "update-ref", "-d", "refs/heads/safe-extra")

        internal_link = mirror / "unsafe-internal-link"
        internal_link.symlink_to(mirror / "HEAD")
        verify_failure(b"internal Git symlink is forbidden")
        internal_link.unlink()

        extra_oid = git(
            mirror,
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=b"safe but unaccounted object inventory drift\n",
        ).stdout.decode().strip()
        verify_failure(b"extra/missing physical Git objects")
        loose = mirror / "objects" / extra_oid[:2] / extra_oid[2:]
        self.assertTrue(loose.is_file())
        loose.unlink()
        if not any(loose.parent.iterdir()):
            loose.parent.rmdir()

        valid = run(
            [
                sys.executable,
                PROGRAM,
                "verify",
                "--run-root",
                self.run_root.resolve(),
            ],
            check=False,
        )
        self.assertEqual(0, valid.returncode, valid.stderr.decode())

    def test_authorities_fail_closed_on_duplicates_counts_sizes_and_unsafe_paths(self):
        official_path = (
            self.source
            / ".omx/research/hikmicro-viewer-2.6.0/governance/official-artifacts.json"
        )
        tsv_path = (
            self.source
            / "mobile/android/app/src/test/evidence/"
            "HIKMICRO_VIEWER_2_6_0_OFFICIAL_ARTIFACT_SHA256.tsv"
        )
        official_original = official_path.read_bytes()
        tsv_original = tsv_path.read_bytes()

        mutations = []
        duplicate_key = official_original.decode().replace(
            '{"artifact_set_id":',
            '{"artifact_set_id":"duplicate","artifact_set_id":',
            1,
        )
        mutations.append(("duplicate JSON key", duplicate_key.encode(), None))
        wrong_counts = json.loads(official_original)
        wrong_counts["observed_counts_by_kind"]["dex"] = 2
        mutations.append(("observed_counts_by_kind", json.dumps(wrong_counts).encode(), None))
        invalid_size = json.loads(official_original)
        invalid_size["artifacts"][0]["size_bytes"] = -1
        mutations.append(("invalid size", json.dumps(invalid_size).encode(), None))
        duplicate_id = json.loads(official_original)
        duplicate_id["artifacts"][1]["artifact_id"] = duplicate_id["artifacts"][0][
            "artifact_id"
        ]
        mutations.append(("duplicate official artifact_id", json.dumps(duplicate_id).encode(), None))
        duplicate_hash = json.loads(official_original)
        duplicate_hash["artifacts"][2]["sha256"] = duplicate_hash["artifacts"][1][
            "sha256"
        ]
        mutations.append(
            (
                "duplicate official artifact SHA256",
                json.dumps(duplicate_hash).encode(),
                None,
            )
        )
        unsafe_tsv = tsv_original.replace(
            b".omx/private/apk/lib/arm64-v8a/libDenied.so",
            b"/absolute/private/libDenied.so",
        )
        mutations.append(("unsafe/noncanonical path", None, unsafe_tsv))

        for expected, official_payload, tsv_payload in mutations:
            with self.subTest(expected=expected):
                official_path.write_bytes(official_payload or official_original)
                tsv_path.write_bytes(tsv_payload or tsv_original)
                with self.assertRaisesRegex(G012.RemediationError, expected):
                    G012._derive_policy(self.source)
                official_path.write_bytes(official_original)
                tsv_path.write_bytes(tsv_original)

    def test_authority_leaf_swap_is_rejected_by_held_descriptor_topology(self):
        authority = self.source / G012.OFFICIAL_JSON_REL
        replacement = self.base / "replacement-official-artifacts.json"
        replacement.write_bytes(b'{"attacker":true}\n')
        actual_read = G012.os.read
        swapped = False

        def swap_authority_leaf(descriptor, maximum):
            nonlocal swapped
            target = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
            if not swapped and target == authority:
                swapped = True
                os.replace(replacement, authority)
            return actual_read(descriptor, maximum)

        with mock.patch.object(G012.os, "read", new=swap_authority_leaf):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "changed during bounded read|regular-file path or topology changed",
            ):
                G012._derive_policy(self.source)
        self.assertTrue(swapped)
        self.assertEqual(b'{"attacker":true}\n', authority.read_bytes())

    def test_authority_ancestor_move_and_symlink_replacement_is_rejected(self):
        authority = self.source / G012.OFFICIAL_JSON_REL
        governance = authority.parent
        moved_governance = governance.with_name("governance-held-original")
        attacker_governance = self.base / "attacker-governance"
        attacker_authority = attacker_governance / authority.name
        write(attacker_authority, b'{"attacker":true}\n')
        actual_read = G012.os.read
        swapped = False

        def swap_authority_ancestor(descriptor, maximum):
            nonlocal swapped
            target = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
            if not swapped and target == authority:
                swapped = True
                governance.rename(moved_governance)
                governance.symlink_to(attacker_governance, target_is_directory=True)
            return actual_read(descriptor, maximum)

        with mock.patch.object(G012.os, "read", new=swap_authority_ancestor):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "ancestor topology changed",
            ):
                G012._derive_policy(self.source)
        self.assertTrue(swapped)
        self.assertTrue(governance.is_symlink())
        self.assertEqual(b'{"attacker":true}\n', authority.read_bytes())

    def test_negative_injection_causes_reverification_failure(self):
        self._commit_positive_history()
        completed = self._dry_run()
        self.assertEqual(
            0, completed.returncode, completed.stderr.decode("utf-8", "replace")
        )
        mirror = self.run_root / "disposable-mirror.git"
        index = self.base / "injection.index"
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(index)
        git(mirror, "read-tree", "refs/heads/main", env=env)
        blob = git(
            mirror,
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=b"jadx decompiled injected source\n",
        ).stdout.decode().strip()
        git(
            mirror,
            "update-index",
            "--add",
            "--cacheinfo",
            "100644",
            blob,
            "negative-injection.txt",
            env=env,
        )
        tree = git(mirror, "write-tree", env=env).stdout.decode().strip()
        parent = git(mirror, "rev-parse", "refs/heads/main").stdout.decode().strip()
        commit_env = env.copy()
        commit_env.update(
            {
                "GIT_AUTHOR_NAME": "Injector",
                "GIT_AUTHOR_EMAIL": "injector@example.invalid",
                "GIT_COMMITTER_NAME": "Injector",
                "GIT_COMMITTER_EMAIL": "injector@example.invalid",
            }
        )
        commit = git(
            mirror,
            "commit-tree",
            tree,
            "-p",
            parent,
            input_bytes=b"negative injection\n",
            env=commit_env,
        ).stdout.decode().strip()
        git(mirror, "update-ref", "refs/heads/main", commit, parent)

        verify = run(
            [
                sys.executable,
                PROGRAM,
                "verify",
                "--run-root",
                self.run_root.resolve(),
            ],
            check=False,
        )
        self.assertEqual(2, verify.returncode)
        self.assertIn(b"ref/OID mismatch", verify.stderr)
        self.assertFalse(
            (self.run_root / "manifests/reverification.json").exists()
        )


class G012LargeFileInventoryTest(unittest.TestCase):
    def test_discovered_required_file_disappearance_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            required = root / "required.bin"
            required.write_bytes(b"required bytes\n")
            actual_stream = G012._stream_hash_regular_path
            disappeared = False

            def disappear_after_discovery(path, *args, **kwargs):
                nonlocal disappeared
                if not disappeared:
                    disappeared = True
                    path.unlink()
                return actual_stream(path, *args, **kwargs)

            with mock.patch.object(
                G012,
                "_stream_hash_regular_path",
                new=disappear_after_discovery,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "required regular file disappeared",
                ):
                    G012._bounded_file_inventory(
                        [("required.bin", required)]
                    )
            self.assertTrue(disappeared)

            optional = root / "optional.bin"
            inventory = G012._bounded_file_inventory(
                [
                    G012.InventoryPath(
                        "optional.bin",
                        optional,
                        required=False,
                    )
                ]
            )
            self.assertEqual(0, inventory["count"])

    def test_external_alternate_ancestor_swap_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "primary-objects"
            external = root / "external-alternate"
            moved_external = root / "external-alternate-held"
            attacker_external = root / "attacker-external-alternate"
            nested = root / "nested-alternate"
            for object_dir in (
                primary,
                external / "objects",
                attacker_external / "objects",
                nested / "objects",
            ):
                (object_dir / "info").mkdir(parents=True)
            write(
                primary / "info/alternates",
                str((external / "objects").resolve()) + "\n",
            )
            external_alternates = external / "objects/info/alternates"
            write(
                external_alternates,
                str((nested / "objects").resolve()) + "\n",
            )
            write(
                attacker_external / "objects/info/alternates",
                str((nested / "objects").resolve()) + "\n",
            )
            actual_read = G012.os.read
            swapped = False

            def swap_external_ancestor(descriptor, maximum):
                nonlocal swapped
                target = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
                if not swapped and target == external_alternates:
                    swapped = True
                    external.rename(moved_external)
                    external.symlink_to(
                        attacker_external,
                        target_is_directory=True,
                    )
                return actual_read(descriptor, maximum)

            with mock.patch.object(
                G012.os,
                "read",
                new=swap_external_ancestor,
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "ancestor topology changed",
                ):
                    G012._discover_object_databases(
                        primary,
                        anchored_source=root,
                    )
            self.assertTrue(swapped)
            self.assertTrue(external.is_symlink())

    def test_each_critical_inventory_family_rejects_root_swap(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)

            def exercise(
                family,
                inventory_root,
                invoke,
            ):
                moved = inventory_root.with_name(
                    f"{inventory_root.name}-held"
                )
                attacker = inventory_root.with_name(
                    f"{inventory_root.name}-attacker"
                )
                attacker.mkdir(parents=True)
                write(attacker / "replacement.txt", "replacement\n")
                actual_listdir = G012.os.listdir
                swapped = False

                def swap_after_root_enumeration(descriptor):
                    nonlocal swapped
                    names = actual_listdir(descriptor)
                    target = Path(
                        os.readlink(f"/proc/self/fd/{descriptor}")
                    )
                    if not swapped and target == inventory_root:
                        swapped = True
                        inventory_root.rename(moved)
                        inventory_root.symlink_to(
                            attacker,
                            target_is_directory=True,
                        )
                    return names

                try:
                    with mock.patch.object(
                        G012.os,
                        "listdir",
                        new=swap_after_root_enumeration,
                    ):
                        with self.assertRaisesRegex(
                            G012.RemediationError,
                            "directory inventory root topology changed",
                        ):
                            invoke()
                    self.assertTrue(swapped, f"{family} root was not exercised")
                finally:
                    if inventory_root.is_symlink():
                        inventory_root.unlink()
                    if moved.exists():
                        moved.rename(inventory_root)

            for family in (
                "objects",
                "refs",
                "logs",
                "hooks",
                "alternate-store",
                "worktree",
            ):
                with self.subTest(family=family):
                    root = base / family
                    root.mkdir()
                    write(root / "entry.txt", f"{family}\n")
                    if family == "worktree":
                        invoke = lambda root=root: G012._worktree_inventory(root)
                    else:
                        invoke = lambda root=root, family=family: (
                            G012._directory_inventory(root, family)
                        )
                    exercise(family, root, invoke)

            repo = base / "admin-repository"
            repo.mkdir()
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.name", "Admin Root Swap")
            git(repo, "config", "user.email", "admin@example.invalid")
            write(repo / "tracked.txt", "tracked\n")
            git(repo, "add", "tracked.txt")
            git(repo, "commit", "-m", "admin root")
            layout = G012._resolve_repository(str(repo.resolve()))
            with self.subTest(family="admin"):
                exercise(
                    "admin",
                    layout.git_dir,
                    lambda: G012._git_admin_state_inventory(layout),
                )

    def test_streams_virtual_file_over_512mib_with_low_memory_and_stable_hash(self):
        size = 513 * 1024 * 1024 + 137
        chunk = b"L" * G012.SOURCE_HASH_CHUNK_BYTES
        file_stat = types.SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_mode=stat.S_IFREG | 0o640,
            st_size=size,
            st_mtime_ns=33,
            st_ctime_ns=44,
            st_blocks=(size + 511) // 512,
        )

        def hash_once():
            remaining = 0

            def virtual_lseek(_descriptor, offset, whence):
                nonlocal remaining
                if whence == os.SEEK_SET and offset == 0:
                    remaining = size
                    return 0
                raise AssertionError("unexpected virtual seek")

            def virtual_read(_descriptor, maximum):
                nonlocal remaining
                if not remaining:
                    return b""
                length = min(remaining, maximum)
                remaining -= length
                return chunk if length == len(chunk) else chunk[:length]

            with (
                mock.patch.object(G012.os, "lseek", new=virtual_lseek),
                mock.patch.object(G012.os, "read", new=virtual_read),
                mock.patch.object(G012.os, "fstat", new=lambda _fd: file_stat),
            ):
                return G012._stream_hash_regular_descriptor(
                    123,
                    file_stat,
                    "virtual-513MiB-file",
                    check_extent_map=False,
                )

        tracemalloc.start()
        first = hash_once()
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        second = hash_once()
        self.assertEqual(size, first[0])
        self.assertEqual(first, second)
        self.assertLess(
            peak,
            16 * 1024 * 1024,
            f"streaming hash peak memory was unexpectedly high: {peak}",
        )
        print(f"virtual_513mib_stream_peak_bytes={peak}")

    def test_hashes_over_512mib_sparse_file_with_low_memory_and_stable_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sparse-large.bin"
            with path.open("wb") as handle:
                handle.write(b"sparse-start")
                handle.seek(257 * 1024 * 1024)
                handle.write(b"sparse-middle")
                handle.truncate(513 * 1024 * 1024 + 1)
            file_stat = path.stat()
            self.assertLess(file_stat.st_blocks * 512, file_stat.st_size)

            tracemalloc.start()
            first = G012._bounded_file_inventory(
                [("sparse-large.bin", path)]
            )
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            second = G012._bounded_file_inventory(
                [("sparse-large.bin", path)]
            )
            self.assertEqual(first["inventory_sha256"], second["inventory_sha256"])
            self.assertEqual(1, first["sparse_file_count"])
            entry = first["entries"][0]
            self.assertTrue(entry["sparse"])
            self.assertEqual(file_stat.st_blocks, entry["allocated_blocks"])
            self.assertLess(peak, 16 * 1024 * 1024)
            print(f"sparse_513mib_stream_peak_bytes={peak}")

    def test_detects_same_size_mutation_during_streaming(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "changing.bin"
            path.write_bytes(b"A" * (2 * 1024 * 1024))
            before = path.lstat()
            actual_read = G012.os.read
            mutated = False

            def mutate_after_first_read(descriptor, maximum):
                nonlocal mutated
                payload = actual_read(descriptor, maximum)
                if not mutated:
                    mutated = True
                    with path.open("r+b") as handle:
                        handle.seek(0)
                        handle.write(b"B" * 4096)
                        handle.flush()
                        os.fsync(handle.fileno())
                return payload

            with mock.patch.object(G012.os, "read", new=mutate_after_first_read):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "changed .*hash|content differed between repeated hash passes",
                ):
                    G012._stream_hash_regular_path(
                        path,
                        "changing.bin",
                        before,
                    )

            sparse = Path(temporary) / "changing-layout.bin"
            with sparse.open("wb") as handle:
                handle.write(b"layout-start")
                handle.truncate(4 * 1024 * 1024)
            sparse_before = sparse.lstat()
            self.assertLess(
                sparse_before.st_blocks * 512, sparse_before.st_size
            )
            layout_mutated = False

            def materialize_hole_after_first_read(descriptor, maximum):
                nonlocal layout_mutated
                payload = actual_read(descriptor, maximum)
                if not layout_mutated:
                    layout_mutated = True
                    with sparse.open("r+b") as handle:
                        handle.seek(2 * 1024 * 1024)
                        handle.write(b"\x00" * 4096)
                        handle.flush()
                        os.fsync(handle.fileno())
                return payload

            with mock.patch.object(
                G012.os, "read", new=materialize_hole_after_first_read
            ):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "changed .*hash|sparse extent map changed",
                ):
                    G012._stream_hash_regular_path(
                        sparse,
                        "changing-layout.bin",
                        sparse_before,
                    )

    def test_enforces_new_file_and_aggregate_bounds_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_path = root / "first.bin"
            second_path = root / "second.bin"
            first_path.write_bytes(b"12345678")
            second_path.write_bytes(b"abcdefgh")
            paths = [("first.bin", first_path), ("second.bin", second_path)]

            first = G012._bounded_file_inventory(paths)
            second = G012._bounded_file_inventory(paths)
            self.assertEqual(first["inventory_sha256"], second["inventory_sha256"])
            self.assertEqual(8 * 1024 * 1024 * 1024, first["maximum_file_bytes"])
            self.assertEqual(
                64 * 1024 * 1024 * 1024, first["maximum_total_bytes"]
            )
            oversized_stat = types.SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600,
                st_size=G012.MAX_SOURCE_FILE_BYTES + 1,
                st_blocks=(G012.MAX_SOURCE_FILE_BYTES + 512) // 512,
            )
            with self.assertRaisesRegex(
                G012.RemediationError,
                str(G012.MAX_SOURCE_FILE_BYTES),
            ):
                G012._validate_streamed_regular_stat(
                    oversized_stat,
                    "over-eight-gib.bin",
                    G012.MAX_SOURCE_FILE_BYTES,
                )
            with self.assertRaisesRegex(
                G012.RemediationError, "7-byte limit"
            ):
                G012._bounded_file_inventory(
                    [("first.bin", first_path)],
                    maximum_file_bytes=7,
                )
            with self.assertRaisesRegex(
                G012.RemediationError, "global source-state logical-byte budget"
            ):
                G012._bounded_file_inventory(
                    paths,
                    maximum_file_bytes=16,
                    maximum_total_bytes=12,
                )
            fifo = root / "special.fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(
                G012.RemediationError,
                "special source inventory entry is forbidden",
            ):
                G012._bounded_file_inventory([("special.fifo", fifo)])

            sparse_equivalent = root / "sparse-equivalent.bin"
            logical_size = 4 * 1024 * 1024 + 19
            with sparse_equivalent.open("wb") as handle:
                handle.write(b"exact-start")
                handle.seek(2 * 1024 * 1024)
                handle.write(b"exact-middle")
                handle.truncate(logical_size)
            materialized = root / "materialized-equivalent.bin"
            with (
                sparse_equivalent.open("rb") as source_handle,
                materialized.open("wb") as target_handle,
            ):
                if hasattr(os, "posix_fallocate"):
                    os.posix_fallocate(target_handle.fileno(), 0, logical_size)
                while True:
                    payload = source_handle.read(G012.SOURCE_HASH_CHUNK_BYTES)
                    if not payload:
                        break
                    target_handle.write(payload)
            sparse_inventory = G012._bounded_file_inventory(
                [("sparse-equivalent.bin", sparse_equivalent)]
            )
            materialized_inventory = G012._bounded_file_inventory(
                [("materialized-equivalent.bin", materialized)]
            )
            sparse_entry = sparse_inventory["entries"][0]
            materialized_entry = materialized_inventory["entries"][0]
            self.assertTrue(sparse_entry["sparse"])
            self.assertFalse(materialized_entry["sparse"])
            self.assertEqual(
                sparse_entry["sha256"], materialized_entry["sha256"]
            )
            self.assertEqual(
                sparse_entry["sha256"], G012._sha256_file(materialized)
            )
            self.assertEqual(
                sparse_inventory["inventory_sha256"],
                G012._bounded_file_inventory(
                    [("sparse-equivalent.bin", sparse_equivalent)]
                )["inventory_sha256"],
            )

            source = root / "source-state-repository"
            source.mkdir()
            git(source, "init", "-b", "main")
            git(source, "config", "user.name", "Special Entry Test")
            git(source, "config", "user.email", "special@example.invalid")
            write(source / "safe.txt", "safe\n")
            git(source, "add", "safe.txt")
            git(source, "commit", "-m", "safe")
            layout = G012._resolve_repository(str(source.resolve()))
            families = {
                "objects": layout.object_dirs[0],
                "refs": layout.common_dir / "refs",
                "logs": G012._absolute_git_path(source, "--git-path", "logs"),
                "hooks": layout.common_dir / "hooks",
            }
            for family, directory in families.items():
                directory.mkdir(parents=True, exist_ok=True)
                for kind in ("fifo", "socket"):
                    with self.subTest(family=family, kind=kind):
                        special = directory / f"g012-special-{kind}"
                        if kind == "fifo":
                            os.mkfifo(special)
                        else:
                            unix_socket = socket.socket(
                                socket.AF_UNIX, socket.SOCK_STREAM
                            )
                            try:
                                unix_socket.bind(str(special))
                            finally:
                                unix_socket.close()
                        try:
                            with self.assertRaisesRegex(
                                G012.RemediationError,
                                f"special Git {family} entry is forbidden",
                            ):
                                G012._source_state(layout)
                        finally:
                            special.unlink(missing_ok=True)

    def test_source_state_uses_one_global_budget_across_recursive_alternates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            git(source, "init", "-b", "main")
            alternate = source / ".git/g012-budget-alternate.git"
            nested_alternate = source / ".git/g012-budget-nested.git"
            git(source, "config", "user.name", "Budget Test")
            git(source, "config", "user.email", "budget@example.invalid")
            write(source / "worktree-budget.bin", b"W" * 8192)
            git(source, "add", "worktree-budget.bin")
            git(source, "commit", "-m", "budget source")
            run(["git", "init", "--bare", alternate])
            git(
                alternate,
                "hash-object",
                "-w",
                "--stdin",
                input_bytes=b"alternate-object-budget\n",
            )
            run(["git", "init", "--bare", nested_alternate])
            git(
                nested_alternate,
                "hash-object",
                "-w",
                "--stdin",
                input_bytes=b"nested-alternate-object-budget\n",
            )
            write(
                alternate / "objects/info/alternates",
                str((nested_alternate / "objects").resolve()) + "\n",
            )
            alternates_file = (
                source / ".git/objects/info/alternates"
            )
            write(alternates_file, str((alternate / "objects").resolve()) + "\n")

            layout = G012._resolve_repository(str(source.resolve()))
            self.assertEqual(3, len(layout.object_dirs))
            state = G012._source_state(layout)
            budget = state["logical_byte_budget"]
            labels = [row["label"] for row in budget["charges"]]
            self.assertIn("worktree-budget.bin", labels)
            for object_dir in layout.object_dirs:
                self.assertTrue(
                    any(str(object_dir) in label for label in labels),
                    f"object database was not charged: {object_dir}",
                )
            self.assertGreater(budget["consumed_bytes"], 0)
            with self.assertRaisesRegex(
                G012.RemediationError,
                "global source-state logical-byte budget exceeded before reading",
            ):
                G012._source_state(
                    layout,
                    maximum_total_bytes=budget["consumed_bytes"] - 1,
                )

    def test_repeated_double_hash_and_extent_races_fail_20_iterations(self):
        size = 2 * G012.SOURCE_HASH_CHUNK_BYTES
        file_stat = types.SimpleNamespace(
            st_dev=101,
            st_ino=202,
            st_mode=stat.S_IFREG | 0o600,
            st_size=size,
            st_mtime_ns=303,
            st_ctime_ns=404,
            st_blocks=(size + 511) // 512,
        )
        for iteration in range(20):
            with self.subTest(race="content", iteration=iteration):
                pass_index = -1
                remaining = 0

                def fake_lseek(_fd, offset, whence):
                    nonlocal pass_index, remaining
                    if whence == os.SEEK_SET and offset == 0:
                        pass_index += 1
                        remaining = size
                        return 0
                    raise AssertionError("unexpected seek")

                def racing_read(_fd, maximum):
                    nonlocal remaining
                    if not remaining:
                        return b""
                    length = min(maximum, remaining)
                    remaining -= length
                    value = b"A" if pass_index == 0 else b"B"
                    return value * length

                with (
                    mock.patch.object(G012.os, "lseek", new=fake_lseek),
                    mock.patch.object(G012.os, "read", new=racing_read),
                    mock.patch.object(
                        G012.os, "fstat", new=lambda _fd: file_stat
                    ),
                ):
                    with self.assertRaisesRegex(
                        G012.RemediationError,
                        "content differed between repeated hash passes",
                    ):
                        G012._stream_hash_regular_descriptor(
                            456,
                            file_stat,
                            "timestamp-preserving-content-race",
                            check_extent_map=False,
                        )

            with self.subTest(race="extent", iteration=iteration):
                first_map = G012.SparseExtentSummary(
                    extent_count=2,
                    data_bytes=8192,
                    traversal_operations=4,
                    records_sha256="1" * 64,
                    first_extents=((0, 4096), (8192, 12288)),
                    last_extents=((0, 4096), (8192, 12288)),
                )
                relocated_map = G012.SparseExtentSummary(
                    extent_count=2,
                    data_bytes=8192,
                    traversal_operations=4,
                    records_sha256="2" * 64,
                    first_extents=((4096, 8192), (12288, 16384)),
                    last_extents=((4096, 8192), (12288, 16384)),
                )
                with (
                    mock.patch.object(
                        G012,
                        "_deterministic_extent_summary",
                        side_effect=[first_map, relocated_map],
                    ),
                    mock.patch.object(
                        G012,
                        "_hash_regular_descriptor_pass",
                        return_value=(size, "a" * 64),
                    ),
                    mock.patch.object(
                        G012.os, "fstat", new=lambda _fd: file_stat
                    ),
                ):
                    with self.assertRaisesRegex(
                        G012.RemediationError,
                        "sparse extent map changed",
                    ):
                        G012._stream_hash_regular_descriptor(
                            789,
                            file_stat,
                            "same-block-count-hole-relocation",
                        )

    def test_extent_summary_is_bounded_and_fragmentation_limits_fail_closed(self):
        accepted_extents = 12_000
        accepted_size = accepted_extents * 2
        accepted_stat = types.SimpleNamespace(
            st_size=accepted_size,
            st_blocks=0,
        )

        descriptor_sizes = {
            100: accepted_size,
            101: accepted_size,
            102: 400_000,
            103: 20,
        }

        def alternating_extents(descriptor, offset, whence):
            if whence == os.SEEK_SET:
                self.assertEqual(0, offset)
                return 0
            if whence == os.SEEK_DATA:
                result = offset if offset % 2 == 0 else offset + 1
                if result >= descriptor_sizes[descriptor]:
                    raise OSError(errno.ENXIO, "no more data")
                return result
            if whence == os.SEEK_HOLE:
                return offset + 1
            raise AssertionError(f"unexpected seek mode: {whence}")

        tracemalloc.start()
        with mock.patch.object(
            G012.os, "lseek", new=alternating_extents
        ):
            first = G012._deterministic_extent_summary(
                100,
                accepted_stat,
                "accepted-fragmentation",
            )
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(accepted_extents, first.extent_count)
        self.assertEqual(accepted_extents, first.data_bytes)
        self.assertLess(peak, 512 * 1024)
        serialized = json.dumps(
            first.inventory(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        self.assertLess(len(serialized), 1024)
        self.assertLessEqual(
            len(first.first_extents), G012.MAX_SPARSE_EXTENT_SAMPLES
        )
        self.assertLessEqual(
            len(first.last_extents), G012.MAX_SPARSE_EXTENT_SAMPLES
        )
        with mock.patch.object(
            G012.os, "lseek", new=alternating_extents
        ):
            second = G012._deterministic_extent_summary(
                101,
                accepted_stat,
                "accepted-fragmentation",
            )
        self.assertEqual(first, second)

        extreme_size = 400_000
        extreme_stat = types.SimpleNamespace(
            st_size=extreme_size,
            st_blocks=0,
        )
        calls = 0

        def extreme_extents(descriptor, offset, whence):
            nonlocal calls
            calls += 1
            return alternating_extents(descriptor, offset, whence)

        tracemalloc.start()
        with mock.patch.object(G012.os, "lseek", new=extreme_extents):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "sparse extent-count limit exceeded",
            ):
                G012._deterministic_extent_summary(
                    102,
                    extreme_stat,
                    "two-hundred-thousand-extents",
                )
        _current, limit_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertLessEqual(
            calls,
            (G012.MAX_SPARSE_EXTENTS * 2) + 2,
        )
        self.assertLess(limit_peak, 512 * 1024)

        with (
            mock.patch.object(G012, "MAX_SPARSE_EXTENTS", 100),
            mock.patch.object(G012, "MAX_SPARSE_TRAVERSAL_OPERATIONS", 3),
            mock.patch.object(G012.os, "lseek", new=alternating_extents),
        ):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "sparse extent traversal-operation limit exceeded",
            ):
                G012._deterministic_extent_summary(
                    103,
                    types.SimpleNamespace(st_size=20, st_blocks=0),
                    "operation-bounded-fragmentation",
                )
        print(
            "extent_summary_12000_peak_bytes="
            f"{peak} fragmentation_limit_peak_bytes={limit_peak}"
        )

    def test_extent_summary_unsupported_all_hole_and_contradictions(self):
        file_stat = types.SimpleNamespace(st_size=8192, st_blocks=0)
        with (
            mock.patch.object(G012.os, "SEEK_DATA", None),
            mock.patch.object(G012.os, "SEEK_HOLE", None),
        ):
            self.assertIsNone(
                G012._deterministic_extent_summary(
                    200,
                    file_stat,
                    "missing-seek-constants",
                )
            )
        with (
            mock.patch.object(G012.os, "SEEK_DATA", None),
            mock.patch.object(G012.os, "SEEK_HOLE", 4),
        ):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "constants are incomplete or invalid",
            ):
                G012._deterministic_extent_summary(
                    201,
                    file_stat,
                    "partial-seek-constants",
                )

        def unsupported_seek(_descriptor, offset, whence):
            if whence == os.SEEK_SET:
                self.assertEqual(0, offset)
                return 0
            raise OSError(errno.EINVAL, "unsupported")

        with mock.patch.object(G012.os, "lseek", new=unsupported_seek):
            self.assertIsNone(
                G012._deterministic_extent_summary(
                    202,
                    file_stat,
                    "unsupported-seek-error",
                )
            )

        def unsupported_hole_seek(_descriptor, offset, whence):
            if whence == os.SEEK_SET:
                self.assertEqual(0, offset)
                return 0
            if whence == os.SEEK_DATA:
                return 0
            if whence == os.SEEK_HOLE:
                raise OSError(errno.EOPNOTSUPP, "unsupported hole traversal")
            raise AssertionError(f"unexpected seek mode: {whence}")

        with mock.patch.object(G012.os, "lseek", new=unsupported_hole_seek):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "inconsistent SEEK_HOLE semantics",
            ):
                G012._deterministic_extent_summary(
                    206,
                    file_stat,
                    "unsupported-seek-hole-error",
                )

        def all_hole_seek(_descriptor, offset, whence):
            if whence == os.SEEK_SET:
                self.assertEqual(0, offset)
                return 0
            if whence == os.SEEK_DATA:
                raise OSError(errno.ENXIO, "no data")
            raise AssertionError("SEEK_HOLE must not be called for all-hole file")

        with mock.patch.object(G012.os, "lseek", new=all_hole_seek):
            all_hole = G012._deterministic_extent_summary(
                203,
                file_stat,
                "all-hole-file",
            )
        self.assertIsNotNone(all_hole)
        assert all_hole is not None
        self.assertEqual(0, all_hole.extent_count)
        self.assertEqual(0, all_hole.data_bytes)
        self.assertEqual(1, all_hole.traversal_operations)
        self.assertEqual((), all_hole.first_extents)
        self.assertEqual((), all_hole.last_extents)

        def contradictory_seek(_descriptor, offset, whence):
            if whence == os.SEEK_SET:
                return 0
            if whence == os.SEEK_DATA:
                return 0
            if whence == os.SEEK_HOLE:
                return file_stat.st_size
            raise AssertionError(f"unexpected seek mode: {whence}")

        with mock.patch.object(G012.os, "lseek", new=contradictory_seek):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "extent map contradicts sparse allocation metadata",
            ):
                G012._deterministic_extent_summary(
                    204,
                    file_stat,
                    "contradictory-all-data-sparse-blocks",
                )

        call_index = 0

        def late_unsupported_seek(_descriptor, offset, whence):
            nonlocal call_index
            if whence == os.SEEK_SET:
                return 0
            call_index += 1
            if call_index == 1 and whence == os.SEEK_DATA:
                return 0
            if call_index == 2 and whence == os.SEEK_HOLE:
                return 4096
            raise OSError(errno.EINVAL, "became unsupported")

        with mock.patch.object(G012.os, "lseek", new=late_unsupported_seek):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "inconsistent SEEK_DATA semantics",
            ):
                G012._deterministic_extent_summary(
                    205,
                    file_stat,
                    "late-unsupported-seek-error",
                )

    def test_mid_to_post_extent_summary_drift_fails_closed(self):
        size = 2 * G012.SOURCE_HASH_CHUNK_BYTES
        file_stat = types.SimpleNamespace(
            st_dev=301,
            st_ino=302,
            st_mode=stat.S_IFREG | 0o600,
            st_size=size,
            st_mtime_ns=303,
            st_ctime_ns=304,
            st_blocks=(size + 511) // 512,
        )
        stable = G012.SparseExtentSummary(
            extent_count=1,
            data_bytes=4096,
            traversal_operations=2,
            records_sha256="3" * 64,
            first_extents=((0, 4096),),
            last_extents=((0, 4096),),
        )
        drifted = G012.SparseExtentSummary(
            extent_count=1,
            data_bytes=4096,
            traversal_operations=2,
            records_sha256="4" * 64,
            first_extents=((8192, 12288),),
            last_extents=((8192, 12288),),
        )
        with (
            mock.patch.object(
                G012,
                "_deterministic_extent_summary",
                side_effect=[stable, stable, drifted],
            ),
            mock.patch.object(
                G012,
                "_hash_regular_descriptor_pass",
                return_value=(size, "5" * 64),
            ),
            mock.patch.object(G012.os, "fstat", return_value=file_stat),
        ):
            with self.assertRaisesRegex(
                G012.RemediationError,
                "source sparse extent map changed",
            ):
                G012._stream_hash_regular_descriptor(
                    300,
                    file_stat,
                    "mid-to-post-extent-drift",
                )

    def test_onofollow_rejects_atomic_symlink_substitution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.bin"
            replacement = root / "replacement.bin"
            source.write_bytes(b"trusted source bytes\n")
            replacement.write_bytes(b"substituted bytes\n")
            before = source.lstat()
            actual_open = G012.os.open
            substituted = False

            def substitute_before_open(path, flags, *args, **kwargs):
                nonlocal substituted
                if not substituted:
                    substituted = True
                    source.unlink()
                    source.symlink_to(replacement)
                return actual_open(path, flags, *args, **kwargs)

            with mock.patch.object(G012.os, "open", new=substitute_before_open):
                with self.assertRaisesRegex(
                    G012.RemediationError,
                    "descriptor-relative O_NOFOLLOW",
                ):
                    G012._stream_hash_regular_path(
                        source,
                        "atomic-symlink-substitution",
                        before,
                    )
            self.assertTrue(source.is_symlink())
            self.assertEqual(b"substituted bytes\n", replacement.read_bytes())


if __name__ == "__main__":
    unittest.main()
