#!/usr/bin/env python3
"""Create and verify a local-only public-history remediation dry run.

The program never fetches, pushes, or modifies the source repository.  History
rewriting is delegated exclusively to a caller-supplied, SHA256-pinned copy of
the official git-filter-repo tool.
"""

from __future__ import annotations

import argparse
import atexit
import ast
import ctypes
import errno
import fcntl
import hashlib
import io
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


EXPECTED_FILTER_REPO_SHA256 = (
    "67447413e273fc76809289111748870b6f6072f08b17efe94863a92d810b7d94"
)
MAX_CAPTURE_BYTES = 16 * 1024 * 1024
MAX_TOOL_BYTES = 8 * 1024 * 1024
MAX_REFS = 20_000
MAX_BLOB_BYTES = 1024 * 1024 * 1024
MAX_SOURCE_FILES = 200_000
# Source inventories stream regular files in 1 MiB chunks.  The bounds are
# deliberately high enough for this workspace's research artifacts while
# remaining fail-closed and finite: 8 GiB per file and 64 GiB aggregate.
SOURCE_HASH_CHUNK_BYTES = 1024 * 1024
MAX_SOURCE_FILE_BYTES = 8 * 1024 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 64 * 1024 * 1024 * 1024
# Sparse-layout traversal is independently bounded.  Each accepted extent
# requires one SEEK_DATA and one SEEK_HOLE operation; one final SEEK_DATA may
# establish end-of-file.  Inventories retain only fixed-size samples and a
# canonical digest, never the complete extent list.
MAX_SPARSE_EXTENTS = 16_384
MAX_SPARSE_TRAVERSAL_OPERATIONS = (MAX_SPARSE_EXTENTS * 2) + 1
MAX_SPARSE_EXTENT_SAMPLES = 4
MAX_LOGICAL_OBJECT_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
MAX_TREE_ENTRIES = 2_000_000
MAX_G007_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_G007_ENTRY_BYTES = 64 * 1024 * 1024
MAX_G007_ENTRIES = 10_000
G007_PUBLICATION_MANIFEST_NAME = "PUBLICATION-MANIFEST.json"
G007_PUBLICATION_SCHEMA = "g007-public-clean-room-publication/v1"
G007_ACCEPTED_ARCHIVE_SHA256 = (
    "796ce4db130862f7ffa726f5e28b3a94d30c4fd5dc3209bc4a8e0be1239a8d97"
)
G007_ACCEPTED_ARCHIVES: dict[str, dict[str, Any]] = {
    G007_ACCEPTED_ARCHIVE_SHA256: {
        "profile_id": "g007-clean-room-public-spec-20260730",
        "archive_size_bytes": 720_228,
        "member_count": 68,
        "member_names_sha256": (
            "933cb2e53a0a42aa4d272b18faea02b5a625ba5427a23dd9cbbcfef02583f7c0"
        ),
        "publication_manifest_sha256": (
            "cad945fb6bd08ee09732a91fcef1d2a9e6c6515a92ab238c6976e96f7cae9b7d"
        ),
        "payload_file_count": 66,
        "scope": (
            "Deterministic source-independent G007 specification publication set."
        ),
        "nonclaims": [
            "No live F2 execution or hardware result is claimed.",
            "No radiometric or Celsius result is claimed.",
            "No Android application build is included or claimed.",
            "No redistribution authority is granted or claimed.",
        ],
    }
}
MIN_GIT_OBJECT_ABBREVIATION = 7
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
ADMIN_OBJECT_TOKEN_RE = re.compile(
    rb"(?<![0-9A-Fa-f])[0-9A-Fa-f]{7,64}(?![0-9A-Fa-f])"
)

OFFICIAL_JSON_REL = Path(
    ".omx/research/hikmicro-viewer-2.6.0/governance/official-artifacts.json"
)
OFFICIAL_TSV_REL = Path(
    "mobile/android/app/src/test/evidence/"
    "HIKMICRO_VIEWER_2_6_0_OFFICIAL_ARTIFACT_SHA256.tsv"
)
G007_EXPORT_REL = Path("tools/hik_whole_apk/g007_public_export.py")
G007_VALIDATOR_REL = Path("tools/hik_whole_apk/g007_spec_validator.py")
CLEAN_ROOM_POLICY_REL = Path(
    ".omx/research/hikmicro-viewer-2.6.0/governance/clean-room-policy.md"
)
AUTHORIZATION_SCOPE_REL = Path(
    ".omx/research/hikmicro-viewer-2.6.0/governance/authorization-scope.md"
)

# These are minimum G012 families.  The overlapping G007 families are also
# parsed from G007_PUBLIC_EXPORT.py and recorded in policy.json.
MANDATORY_FAMILY_PARTS = (
    ("assets", "hikmicro", "official"),
    ("com", "hcusbsdk"),
    ("com", "hik"),
    ("com", "hikmicro"),
    ("hik", "common"),
    ("src", "main", "jniLibs"),
    ("vendor", "hikmicro_analyzer"),
    ("mobile", "android", "app", "src", "test", "resources", "f2fixtures"),
)
MANDATORY_ROOT_GLOBS = (
    "lib/**",
    "_workspace/hikmicro-*",
    "_workspace/hikmicro-*/**",
)
FORBIDDEN_REF_PREFIXES = (
    "refs/original/",
    "refs/replace/",
    "refs/rewritten/",
    "refs/filter-repo/",
)
SYNTHETIC_EVIDENCE_REF_PREFIX = "refs/g012-captured/"
PSEUDOREF_NAMES = (
    "HEAD",
    "ORIG_HEAD",
    "FETCH_HEAD",
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "REBASE_HEAD",
    "AUTO_MERGE",
    "BISECT_HEAD",
)
KNOWN_GIT_ADMIN_FILES = {
    "HEAD",
    "config",
    "config.worktree",
    "description",
    "index",
    "packed-refs",
    "shallow",
    "commondir",
    "gitdir",
    "FETCH_HEAD",
    "ORIG_HEAD",
    "MERGE_HEAD",
    "MERGE_MSG",
    "MERGE_MODE",
    "MERGE_RR",
    "AUTO_MERGE",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "REBASE_HEAD",
    "SQUASH_MSG",
    "COMMIT_EDITMSG",
    "BISECT_HEAD",
}


@dataclass(frozen=True)
class RepositoryLayout:
    source: Path
    git_dir: Path
    common_dir: Path
    object_dirs: tuple[Path, ...]
    alternate_files: tuple[Path, ...]
    admin_paths: tuple[Path, ...]
    source_anchor: "SourceRepositoryAnchor"

    def revalidate(self, label: str) -> None:
        self.source_anchor.revalidate(label)

    def close(self) -> None:
        self.source_anchor.close()


@dataclass
class SealedFilterRepoTool:
    fd: int
    evidence_path: Path
    supplied_path: Path
    sha256: str
    evidence_substitution_detected: bool = False


@dataclass(frozen=True)
class SparseExtentSummary:
    extent_count: int
    data_bytes: int
    traversal_operations: int
    records_sha256: str
    first_extents: tuple[tuple[int, int], ...]
    last_extents: tuple[tuple[int, int], ...]

    def inventory(self) -> dict[str, Any]:
        return {
            "format": "g012-sparse-extents-v1",
            "extent_count": self.extent_count,
            "data_bytes": self.data_bytes,
            "traversal_operations": self.traversal_operations,
            "records_sha256": self.records_sha256,
            "first_extents": [list(extent) for extent in self.first_extents],
            "last_extents": [list(extent) for extent in self.last_extents],
        }


@dataclass(frozen=True)
class InventoryPath:
    label: str
    path: Path
    required: bool = True


@dataclass
class LogicalByteBudget:
    maximum_bytes: int
    consumed_bytes: int = 0
    charges: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.maximum_bytes, int)
            or isinstance(self.maximum_bytes, bool)
            or self.maximum_bytes < 0
        ):
            raise RemediationError("logical-byte budget must be a nonnegative integer")
        if self.charges is None:
            self.charges = []

    def consume(self, size_bytes: int, label: str) -> None:
        if (
            not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes < 0
        ):
            raise RemediationError(f"invalid logical byte charge for {label}")
        if self.consumed_bytes + size_bytes > self.maximum_bytes:
            raise RemediationError(
                "global source-state logical-byte budget exceeded before reading "
                f"{label}: consumed={self.consumed_bytes}, next={size_bytes}, "
                f"maximum={self.maximum_bytes}"
            )
        self.consumed_bytes += size_bytes
        assert self.charges is not None
        if len(self.charges) >= MAX_SOURCE_FILES * 8:
            raise RemediationError("logical-byte budget charge count exceeded")
        self.charges.append({"label": label, "size_bytes": size_bytes})

    def snapshot(self) -> dict[str, Any]:
        assert self.charges is not None
        return {
            "maximum_bytes": self.maximum_bytes,
            "consumed_bytes": self.consumed_bytes,
            "remaining_bytes": self.maximum_bytes - self.consumed_bytes,
            "charge_count": len(self.charges),
            "charges": list(self.charges),
            "charges_sha256": _sha256_bytes(_canonical_json(self.charges)),
        }


class RemediationError(RuntimeError):
    """A fail-closed validation or execution error."""


@dataclass
class HeldPathParent:
    path: Path
    root_descriptor: int
    directory_descriptors: list[int]
    ancestor_names: list[str]
    root_identity: tuple[int, ...]
    ancestor_identities: list[tuple[int, ...]]
    leaf_name: str
    closed: bool = False

    @property
    def parent_descriptor(self) -> int:
        return self.directory_descriptors[-1]

    def revalidate(self, label: str) -> None:
        if self.closed:
            raise RemediationError(f"held path topology is already closed: {label}")
        if (
            _directory_topology_identity(os.fstat(self.root_descriptor))
            != self.root_identity
        ):
            raise RemediationError(f"filesystem root topology changed: {label}")
        for index, (name, expected) in enumerate(
            zip(self.ancestor_names, self.ancestor_identities, strict=True)
        ):
            parent_descriptor = self.directory_descriptors[index]
            child_descriptor = self.directory_descriptors[index + 1]
            try:
                entry_stat = os.stat(
                    name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                descriptor_stat = os.fstat(child_descriptor)
            except OSError as exc:
                raise RemediationError(
                    f"ancestor topology disappeared during secure traversal: {label}"
                ) from exc
            if (
                not stat.S_ISDIR(entry_stat.st_mode)
                or not stat.S_ISDIR(descriptor_stat.st_mode)
                or _directory_topology_identity(entry_stat) != expected
                or _directory_topology_identity(descriptor_stat) != expected
            ):
                raise RemediationError(
                    f"ancestor topology changed during secure traversal: {label}"
                )

    def leaf_lstat(self, label: str) -> os.stat_result:
        self.revalidate(label)
        try:
            result = os.stat(
                self.leaf_name,
                dir_fd=self.parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise RemediationError(
                f"required path leaf disappeared during secure traversal: {label}"
            ) from exc
        self.revalidate(label)
        return result

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for descriptor in reversed(self.directory_descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


@dataclass
class HeldRegularFile:
    parent: HeldPathParent
    descriptor: int
    identity: tuple[int, ...]
    closed: bool = False

    def revalidate(self, label: str) -> None:
        if self.closed:
            raise RemediationError(f"held regular file is already closed: {label}")
        self.parent.revalidate(label)
        try:
            entry_stat = os.stat(
                self.parent.leaf_name,
                dir_fd=self.parent.parent_descriptor,
                follow_symlinks=False,
            )
            descriptor_stat = os.fstat(self.descriptor)
        except OSError as exc:
            raise RemediationError(
                f"required regular-file path disappeared: {label}"
            ) from exc
        if (
            not stat.S_ISREG(entry_stat.st_mode)
            or not stat.S_ISREG(descriptor_stat.st_mode)
            or _source_stat_identity(entry_stat) != self.identity
            or _source_stat_identity(descriptor_stat) != self.identity
        ):
            raise RemediationError(
                f"regular-file path or topology changed during secure read: {label}"
            )
        self.parent.revalidate(label)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.close(self.descriptor)
        finally:
            self.parent.close()


@dataclass
class HeldDirectoryRoot:
    parent: HeldPathParent
    descriptor: int
    identity: tuple[int, ...]
    closed: bool = False

    def revalidate(self, label: str) -> None:
        if self.closed:
            raise RemediationError(f"held directory root is already closed: {label}")
        self.parent.revalidate(label)
        try:
            entry_stat = os.stat(
                self.parent.leaf_name,
                dir_fd=self.parent.parent_descriptor,
                follow_symlinks=False,
            )
            descriptor_stat = os.fstat(self.descriptor)
        except OSError as exc:
            raise RemediationError(
                f"directory inventory root disappeared: {label}"
            ) from exc
        if (
            not stat.S_ISDIR(entry_stat.st_mode)
            or not stat.S_ISDIR(descriptor_stat.st_mode)
            or _source_stat_identity(entry_stat) != self.identity
            or _source_stat_identity(descriptor_stat) != self.identity
        ):
            raise RemediationError(
                f"directory inventory root topology changed: {label}"
            )
        self.parent.revalidate(label)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.close(self.descriptor)
        finally:
            self.parent.close()


@dataclass
class SourceRepositoryAnchor:
    original_path: Path
    held: HeldDirectoryRoot
    closed: bool = False

    @property
    def command_path(self) -> Path:
        if self.closed:
            raise RemediationError("source repository anchor is already closed")
        return Path(f"/proc/self/fd/{self.held.descriptor}")

    @property
    def pass_fds(self) -> tuple[int, ...]:
        if self.closed:
            raise RemediationError("source repository anchor is already closed")
        return (self.held.descriptor,)

    def revalidate(self, label: str) -> None:
        if self.closed:
            raise RemediationError(f"source repository anchor is already closed: {label}")
        self.held.revalidate(label)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.held.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


@dataclass(frozen=True)
class HeldDirectoryEdge:
    parent_descriptor: int
    name: str
    descriptor: int
    identity: tuple[int, ...]


@dataclass
class RunRootAnchor:
    original_path: Path
    held: HeldDirectoryRoot
    identity: tuple[int, ...]
    closed: bool = False

    @property
    def command_path(self) -> Path:
        if self.closed:
            raise RemediationError("run-root anchor is already closed")
        return Path(f"/proc/self/fd/{self.held.descriptor}")

    @property
    def pass_fds(self) -> tuple[int, ...]:
        if self.closed:
            raise RemediationError("run-root anchor is already closed")
        return (self.held.descriptor,)

    def descriptor_revalidate(self, label: str) -> None:
        if self.closed:
            raise RemediationError(f"run-root anchor is already closed: {label}")
        observed = os.fstat(self.held.descriptor)
        if (
            not stat.S_ISDIR(observed.st_mode)
            or _directory_topology_identity(observed) != self.identity
        ):
            raise RemediationError(f"held run-root descriptor changed: {label}")

    def revalidate(self, label: str) -> None:
        self.descriptor_revalidate(label)
        self.held.parent.revalidate(label)
        try:
            entry = os.stat(
                self.held.parent.leaf_name,
                dir_fd=self.held.parent.parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise RemediationError(
                f"run-root pathname disappeared or was substituted: {label}"
            ) from exc
        if (
            not stat.S_ISDIR(entry.st_mode)
            or _directory_topology_identity(entry) != self.identity
        ):
            raise RemediationError(
                f"run-root pathname topology changed: {label}"
            )
        self.held.parent.revalidate(label)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        _ACTIVE_RUN_ROOT_ANCHORS.pop(self.held.descriptor, None)
        self.held.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


@dataclass
class HeldOutputParent:
    path: Path
    leaf_name: str
    parent_descriptor: int
    anchor: RunRootAnchor | None
    external_parent: HeldPathParent | None
    edges: list[HeldDirectoryEdge]
    closed: bool = False

    @property
    def pass_fds(self) -> tuple[int, ...]:
        descriptors = {self.parent_descriptor}
        if self.anchor is not None:
            descriptors.add(self.anchor.held.descriptor)
        return tuple(sorted(descriptors))

    @property
    def command_path(self) -> Path:
        if self.closed:
            raise RemediationError("held output parent is already closed")
        return Path(f"/proc/self/fd/{self.parent_descriptor}") / self.leaf_name

    def revalidate(self, label: str) -> None:
        if self.closed:
            raise RemediationError(f"held output parent is already closed: {label}")
        if self.anchor is not None:
            self.anchor.descriptor_revalidate(label)
        if self.external_parent is not None:
            self.external_parent.revalidate(label)
        for edge in self.edges:
            try:
                entry = os.stat(
                    edge.name,
                    dir_fd=edge.parent_descriptor,
                    follow_symlinks=False,
                )
                opened = os.fstat(edge.descriptor)
            except OSError as exc:
                raise RemediationError(
                    f"output ancestor disappeared during held traversal: {label}"
                ) from exc
            if (
                not stat.S_ISDIR(entry.st_mode)
                or not stat.S_ISDIR(opened.st_mode)
                or _directory_topology_identity(entry) != edge.identity
                or _directory_topology_identity(opened) != edge.identity
            ):
                raise RemediationError(
                    f"output ancestor topology changed: {label}"
                )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for edge in reversed(self.edges):
            try:
                os.close(edge.descriptor)
            except OSError:
                pass
        if self.external_parent is not None:
            self.external_parent.close()


@dataclass
class SecureOutputFile:
    parent: HeldOutputParent
    descriptor: int
    device: int
    inode: int
    mode: int
    closed: bool = False

    @property
    def command_path(self) -> Path:
        if self.closed:
            raise RemediationError("secure output file is already closed")
        return Path(f"/proc/self/fd/{self.descriptor}")

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return tuple(sorted({*self.parent.pass_fds, self.descriptor}))

    def revalidate(self, label: str) -> os.stat_result:
        if self.closed:
            raise RemediationError(f"secure output file is already closed: {label}")
        self.parent.revalidate(label)
        try:
            entry = os.stat(
                self.parent.leaf_name,
                dir_fd=self.parent.parent_descriptor,
                follow_symlinks=False,
            )
            opened = os.fstat(self.descriptor)
        except OSError as exc:
            raise RemediationError(
                f"secure output leaf disappeared: {label}"
            ) from exc
        for observed in (entry, opened):
            if (
                not stat.S_ISREG(observed.st_mode)
                or observed.st_dev != self.device
                or observed.st_ino != self.inode
                or stat.S_IMODE(observed.st_mode) != self.mode
            ):
                raise RemediationError(
                    "secure output leaf was replaced or changed type: "
                    f"{label}; expected=({self.device},{self.inode},"
                    f"{oct(self.mode)}), observed=({observed.st_dev},"
                    f"{observed.st_ino},{oct(stat.S_IMODE(observed.st_mode))})"
                )
        return opened

    def fsync(self, label: str) -> os.stat_result:
        observed = self.revalidate(label)
        os.fsync(self.descriptor)
        self.parent.revalidate(label)
        os.fsync(self.parent.parent_descriptor)
        return observed

    def cleanup_if_owned(self, label: str) -> bool:
        """Remove a failed output only while its leaf still names this inode."""
        if self.closed:
            raise RemediationError(
                f"secure output file is already closed during cleanup: {label}"
            )
        return _quarantine_owned_output_leaf(
            self.parent,
            (self.device, self.inode, stat.S_IFREG),
            label,
            descriptor=self.descriptor,
            directory=False,
            remove_contents=False,
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.close(self.descriptor)
        finally:
            self.parent.close()


@dataclass
class HeldExclusiveDestination:
    parent: HeldOutputParent
    descriptor: int
    device: int
    inode: int
    mode: int
    label: str
    closed: bool = False

    @property
    def command_path(self) -> Path:
        if self.closed:
            raise RemediationError("exclusive destination is already closed")
        return Path(f"/proc/self/fd/{self.descriptor}")

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return tuple(sorted({*self.parent.pass_fds, self.descriptor}))

    def revalidate(self) -> os.stat_result:
        if self.closed:
            raise RemediationError("exclusive destination is already closed")
        self.parent.revalidate(self.label)
        try:
            entry = os.stat(
                self.parent.leaf_name,
                dir_fd=self.parent.parent_descriptor,
                follow_symlinks=False,
            )
            opened = os.fstat(self.descriptor)
        except OSError as exc:
            raise RemediationError(
                f"secure Git destination disappeared: {self.label}"
            ) from exc
        for observed in (entry, opened):
            if (
                not stat.S_ISDIR(observed.st_mode)
                or observed.st_dev != self.device
                or observed.st_ino != self.inode
                or stat.S_IMODE(observed.st_mode) != self.mode
            ):
                raise RemediationError(
                    "secure Git destination was replaced or changed type: "
                    f"{self.label}; expected=({self.device},{self.inode},"
                    f"{oct(self.mode)}), observed=({observed.st_dev},"
                    f"{observed.st_ino},{oct(stat.S_IMODE(observed.st_mode))})"
                )
        return opened

    def verify_created_directory(self) -> None:
        self.revalidate()
        os.fsync(self.descriptor)
        self.parent.revalidate(self.label)
        os.fsync(self.parent.parent_descriptor)
        self.revalidate()

    def cleanup_if_owned(self) -> bool:
        """Remove a failed clone only if the final leaf still names this dir."""
        if self.closed:
            raise RemediationError(
                f"exclusive destination is already closed: {self.label}"
            )
        return _quarantine_owned_output_leaf(
            self.parent,
            (self.device, self.inode, stat.S_IFDIR),
            self.label,
            descriptor=self.descriptor,
            directory=True,
            remove_contents=True,
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.close(self.descriptor)
        finally:
            self.parent.close()


_ACTIVE_RUN_ROOT_ANCHORS: dict[int, RunRootAnchor] = {}


_EMPTY_HOOKS_DIRECTORY: Path | None = None


def _empty_hooks_directory() -> Path:
    global _EMPTY_HOOKS_DIRECTORY
    if _EMPTY_HOOKS_DIRECTORY is None:
        path = Path(tempfile.mkdtemp(prefix="g012-empty-hooks-"))
        path.chmod(0o500)
        _EMPTY_HOOKS_DIRECTORY = path

        def cleanup() -> None:
            try:
                path.chmod(0o700)
                path.rmdir()
            except OSError:
                pass

        atexit.register(cleanup)
    if not _EMPTY_HOOKS_DIRECTORY.is_dir() or any(_EMPTY_HOOKS_DIRECTORY.iterdir()):
        raise RemediationError("trusted empty Git hooks directory was altered")
    return _EMPTY_HOOKS_DIRECTORY


def _git_safety_arguments() -> list[str]:
    return [
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={_empty_hooks_directory()}",
        "-c",
        "credential.helper=",
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.file.allow=always",
        "-c",
        "protocol.ext.allow=never",
        "-c",
        "core.pager=cat",
        "-c",
        "pager.branch=false",
        "-c",
        "pager.log=false",
        "-c",
        "pager.show=false",
        "-c",
        "interactive.diffFilter=",
        "-c",
        f"fsck.skipList={os.devnull}",
        "-c",
        f"fetch.fsck.skipList={os.devnull}",
        "-c",
        f"receive.fsck.skipList={os.devnull}",
    ]


def _git_context(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
) -> tuple[Path, tuple[int, ...]]:
    if isinstance(repo, RepositoryLayout):
        repo = repo.source_anchor
    if isinstance(repo, SourceRepositoryAnchor):
        repo.revalidate("source repository before Git operation")
        return repo.command_path, repo.pass_fds
    anchored = _active_run_root_relative(repo)
    if anchored is not None:
        anchor, _relative = anchored
        anchor.descriptor_revalidate("run-root Git operation")
        return repo, anchor.pass_fds
    return repo, ()


def _git_argv(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
    *arguments: str,
) -> list[str]:
    command_path, _pass_fds = _git_context(repo)
    return ["git", *_git_safety_arguments(), "-C", str(command_path), *arguments]


def _git_pass_fds(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
) -> tuple[int, ...]:
    _command_path, pass_fds = _git_context(repo)
    return pass_fds


def _json_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RemediationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_nonstandard_json_constant(value: str) -> Any:
    raise RemediationError(f"nonstandard JSON numeric constant is forbidden: {value}")


def _load_json_bytes(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_json_no_duplicates,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemediationError(f"invalid JSON in {label}: {exc}") from exc


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _write_json(path: Path, value: Any) -> None:
    _secure_create_output(
        path,
        _canonical_json(value),
        f"JSON output {path.name}",
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _directory_topology_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
    )


def _absolute_path_components(path: Path, label: str) -> tuple[str, ...]:
    if not path.is_absolute() or path.anchor != os.sep:
        raise RemediationError(f"{label} must use a canonical absolute POSIX path")
    components = path.parts[1:]
    if (
        not components
        or any(component in {"", ".", ".."} for component in components)
    ):
        raise RemediationError(f"{label} has unsafe path components: {path}")
    return components


def _hold_path_parent(path: Path, label: str) -> HeldPathParent:
    components = _absolute_path_components(path, label)
    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    root_descriptor: int | None = None
    directory_descriptors: list[int] = []
    ancestor_names: list[str] = []
    ancestor_identities: list[tuple[int, ...]] = []
    try:
        root_descriptor = os.open(os.sep, directory_flags)
        root_stat = os.fstat(root_descriptor)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise RemediationError("filesystem root descriptor is not a directory")
        directory_descriptors.append(root_descriptor)
        for component in components[:-1]:
            parent_descriptor = directory_descriptors[-1]
            descriptor: int | None = None
            try:
                descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=parent_descriptor,
                )
                descriptor_stat = os.fstat(descriptor)
                entry_stat = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                if descriptor is not None:
                    os.close(descriptor)
                raise RemediationError(
                    f"descriptor-relative no-symlink traversal failed for {label}"
                ) from exc
            identity = _directory_topology_identity(descriptor_stat)
            if (
                not stat.S_ISDIR(descriptor_stat.st_mode)
                or not stat.S_ISDIR(entry_stat.st_mode)
                or _directory_topology_identity(entry_stat) != identity
            ):
                os.close(descriptor)
                raise RemediationError(
                    f"ancestor is not a stable non-symlink directory: {label}"
                )
            ancestor_names.append(component)
            ancestor_identities.append(identity)
            directory_descriptors.append(descriptor)
        held = HeldPathParent(
            path=path,
            root_descriptor=root_descriptor,
            directory_descriptors=directory_descriptors,
            ancestor_names=ancestor_names,
            root_identity=_directory_topology_identity(root_stat),
            ancestor_identities=ancestor_identities,
            leaf_name=components[-1],
        )
        held.revalidate(label)
        return held
    except Exception:
        for descriptor in reversed(directory_descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _active_run_root_relative(
    path: Path,
) -> tuple[RunRootAnchor, PurePosixPath] | None:
    candidate = Path(os.path.normpath(os.fspath(path)))
    for anchor in tuple(_ACTIVE_RUN_ROOT_ANCHORS.values()):
        if anchor.closed:
            continue
        try:
            relative = candidate.relative_to(anchor.command_path)
        except ValueError:
            continue
        pure = PurePosixPath(relative.as_posix())
        if (
            not pure.parts
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise RemediationError(f"unsafe anchored run-root path: {path}")
        return anchor, pure
    return None


def _open_output_parent(path: Path, label: str) -> HeldOutputParent:
    anchored = _active_run_root_relative(path)
    if anchored is None:
        external = _hold_path_parent(path, label)
        return HeldOutputParent(
            path=path,
            leaf_name=external.leaf_name,
            parent_descriptor=external.parent_descriptor,
            anchor=None,
            external_parent=external,
            edges=[],
        )
    anchor, relative = anchored
    anchor.descriptor_revalidate(label)
    descriptor = anchor.held.descriptor
    edges: list[HeldDirectoryEdge] = []
    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        for component in relative.parts[:-1]:
            child: int | None = None
            try:
                entry = os.stat(
                    component,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
                child = os.open(
                    component,
                    directory_flags,
                    dir_fd=descriptor,
                )
                opened = os.fstat(child)
            except OSError as exc:
                if child is not None:
                    os.close(child)
                raise RemediationError(
                    f"anchored output ancestor failed no-symlink open: {label}"
                ) from exc
            identity = _directory_topology_identity(opened)
            if (
                not stat.S_ISDIR(entry.st_mode)
                or not stat.S_ISDIR(opened.st_mode)
                or _directory_topology_identity(entry) != identity
            ):
                os.close(child)
                raise RemediationError(
                    f"anchored output ancestor is unsafe: {label}"
                )
            edges.append(
                HeldDirectoryEdge(
                    parent_descriptor=descriptor,
                    name=component,
                    descriptor=child,
                    identity=identity,
                )
            )
            descriptor = child
        held = HeldOutputParent(
            path=path,
            leaf_name=relative.parts[-1],
            parent_descriptor=descriptor,
            anchor=anchor,
            external_parent=None,
            edges=edges,
        )
        held.revalidate(label)
        return held
    except Exception:
        for edge in reversed(edges):
            try:
                os.close(edge.descriptor)
            except OSError:
                pass
        raise


def _secure_output_directory(
    path: Path,
    label: str,
    *,
    mode: int = 0o700,
) -> None:
    parent = _open_output_parent(path, label)
    descriptor: int | None = None
    created_identity: tuple[int, int, int] | None = None
    try:
        parent.revalidate(label)
        try:
            os.mkdir(
                parent.leaf_name,
                mode=mode,
                dir_fd=parent.parent_descriptor,
            )
        except FileExistsError as exc:
            raise RemediationError(
                f"secure output directory already exists: {label}"
            ) from exc
        except OSError as exc:
            raise RemediationError(
                f"could not create secure output directory: {label}"
            ) from exc
        parent_after_mkdir = _construction_parent_identity(
            os.fstat(parent.parent_descriptor)
        )
        try:
            created = os.stat(
                parent.leaf_name,
                dir_fd=parent.parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            try:
                created_identity = (
                    _recover_directory_identity_after_metadata_failure(
                        parent,
                        parent_after_mkdir,
                        label,
                    )
                )
            except RemediationError as recovery_exc:
                raise RemediationError(
                    "initial secure output directory identity acquisition "
                    f"failed and ownership could not be re-established: {label}"
                ) from recovery_exc
            raise RemediationError(
                "initial secure output directory identity acquisition failed: "
                f"{label}"
            ) from exc
        created_identity = _created_output_identity(created)
        if created_identity[2] != stat.S_IFDIR:
            raise RemediationError(
                f"secure output directory creation was substituted: {label}"
            )
        descriptor = os.open(
            parent.leaf_name,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent.parent_descriptor,
        )
        os.fchmod(descriptor, mode)
        opened = os.fstat(descriptor)
        entry = os.stat(
            parent.leaf_name,
            dir_fd=parent.parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(entry.st_mode)
            or _created_output_identity(opened) != created_identity
            or _created_output_identity(entry) != created_identity
            or stat.S_IMODE(opened.st_mode) != mode
            or stat.S_IMODE(entry.st_mode) != mode
        ):
            raise RemediationError(
                f"secure output directory changed during creation: {label}"
            )
        os.fsync(descriptor)
        os.fsync(parent.parent_descriptor)
        opened_after = os.fstat(descriptor)
        entry_after = os.stat(
            parent.leaf_name,
            dir_fd=parent.parent_descriptor,
            follow_symlinks=False,
        )
        if (
            _created_output_identity(opened_after) != created_identity
            or _created_output_identity(entry_after) != created_identity
            or stat.S_IMODE(opened_after.st_mode) != mode
            or stat.S_IMODE(entry_after.st_mode) != mode
        ):
            raise RemediationError(
                f"secure output directory changed during final validation: {label}"
            )
        parent.revalidate(label)
    except Exception:
        if created_identity is not None:
            _cleanup_constructing_output_leaf(
                parent,
                created_identity,
                f"{label} construction cleanup",
                descriptor=descriptor,
                directory=True,
            )
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        parent.close()


def _created_output_identity(
    observed: os.stat_result,
) -> tuple[int, int, int]:
    return (
        observed.st_dev,
        observed.st_ino,
        stat.S_IFMT(observed.st_mode),
    )


def _construction_parent_identity(
    observed: os.stat_result,
) -> tuple[int, ...]:
    return (
        observed.st_dev,
        observed.st_ino,
        observed.st_mode,
        observed.st_nlink,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
    )


def _recover_descriptor_identity_after_metadata_failure(
    descriptor: int,
    expected_type: int,
    label: str,
) -> tuple[int, int, int]:
    failures: list[OSError] = []
    for reader in (os.fstat, os.stat):
        try:
            observed = reader(descriptor)
        except OSError as exc:
            failures.append(exc)
            continue
        identity = _created_output_identity(observed)
        if identity[2] != expected_type:
            raise RemediationError(
                f"recovered construction identity has the wrong type: {label}"
            )
        return identity
    detail = failures[-1] if failures else OSError("no metadata reader available")
    raise RemediationError(
        f"could not safely recover construction identity: {label}"
    ) from detail


def _recover_directory_identity_after_metadata_failure(
    parent: HeldOutputParent | HeldPathParent,
    parent_identity: tuple[int, ...],
    label: str,
) -> tuple[int, int, int]:
    """Retry only while the held parent proves no namespace mutation occurred."""
    parent.revalidate(label)
    before_retry = _construction_parent_identity(
        os.stat(parent.parent_descriptor)
    )
    if before_retry != parent_identity:
        raise RemediationError(
            f"directory namespace changed before identity recovery: {label}"
        )
    try:
        observed = os.stat(
            parent.leaf_name,
            dir_fd=parent.parent_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise RemediationError(
            f"could not retry directory construction identity: {label}"
        ) from exc
    after_retry = _construction_parent_identity(
        os.stat(parent.parent_descriptor)
    )
    if after_retry != parent_identity:
        raise RemediationError(
            f"directory namespace changed during identity recovery: {label}"
        )
    identity = _created_output_identity(observed)
    if identity[2] != stat.S_IFDIR:
        raise RemediationError(
            f"recovered directory construction identity has wrong type: {label}"
        )
    return identity


_RENAME_NOREPLACE = 1
_RENAMEAT2 = None
_RENAMEAT2_LIBRARY = None


def _rename_noreplace(
    source_parent_descriptor: int,
    source_name: str,
    destination_parent_descriptor: int,
    destination_name: str,
) -> None:
    """Linux renameat2(RENAME_NOREPLACE), required for atomic quarantine."""
    global _RENAMEAT2, _RENAMEAT2_LIBRARY
    for name in (source_name, destination_name):
        if (
            not name
            or name in {".", ".."}
            or "/" in name
            or "\x00" in name
        ):
            raise RemediationError("unsafe atomic quarantine leaf name")
    if _RENAMEAT2 is None:
        libc = ctypes.CDLL(None, use_errno=True)
        function = getattr(libc, "renameat2", None)
        if function is None:
            raise RemediationError(
                "renameat2(RENAME_NOREPLACE) is required for safe cleanup"
            )
        function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        function.restype = ctypes.c_int
        _RENAMEAT2_LIBRARY = libc
        _RENAMEAT2 = function
    result = _RENAMEAT2(
        source_parent_descriptor,
        os.fsencode(source_name),
        destination_parent_descriptor,
        os.fsencode(destination_name),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        error = ctypes.get_errno()
        if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
            raise RemediationError(
                "atomic no-replace rename is unavailable for safe cleanup"
            )
        raise OSError(
            error,
            os.strerror(error),
            f"{source_name} -> {destination_name}",
        )


def _restore_quarantined_leaf(
    parent: HeldOutputParent | HeldPathParent,
    quarantine_name: str,
    label: str,
) -> bool:
    try:
        _rename_noreplace(
            parent.parent_descriptor,
            quarantine_name,
            parent.parent_descriptor,
            parent.leaf_name,
        )
    except FileExistsError:
        os.fsync(parent.parent_descriptor)
        parent.revalidate(label)
        return False
    except FileNotFoundError as exc:
        raise RemediationError(
            f"quarantined cleanup leaf disappeared before restoration: {label}"
        ) from exc
    os.fsync(parent.parent_descriptor)
    parent.revalidate(label)
    return True


def _quarantine_owned_output_leaf(
    parent: HeldOutputParent | HeldPathParent,
    expected_identity: tuple[int, int, int],
    label: str,
    *,
    descriptor: int | None,
    directory: bool,
    remove_contents: bool,
) -> bool:
    """Atomically isolate a candidate before validating or deleting it."""
    parent.revalidate(label)
    quarantine_name: str | None = None
    for _attempt in range(16):
        candidate = f".g012-quarantine-{secrets.token_hex(24)}"
        try:
            _rename_noreplace(
                parent.parent_descriptor,
                parent.leaf_name,
                parent.parent_descriptor,
                candidate,
            )
        except FileExistsError:
            continue
        except FileNotFoundError:
            parent.revalidate(label)
            return False
        quarantine_name = candidate
        break
    if quarantine_name is None:
        raise RemediationError(
            f"could not reserve an unpredictable cleanup quarantine: {label}"
        )
    os.fsync(parent.parent_descriptor)
    parent.revalidate(label)

    try:
        quarantined = os.stat(
            quarantine_name,
            dir_fd=parent.parent_descriptor,
            follow_symlinks=False,
        )
        exact = _created_output_identity(quarantined) == expected_identity
        if descriptor is not None:
            opened = os.stat(descriptor)
            exact = (
                exact
                and _created_output_identity(opened) == expected_identity
            )
    except OSError as exc:
        restored = _restore_quarantined_leaf(
            parent,
            quarantine_name,
            label,
        )
        if not restored:
            raise RemediationError(
                "cleanup quarantine could not be validated and was retained "
                f"without overwrite as {quarantine_name}: {label}"
            ) from exc
        raise RemediationError(
            f"cleanup quarantine metadata validation failed: {label}"
        ) from exc

    if not exact:
        restored = _restore_quarantined_leaf(
            parent,
            quarantine_name,
            label,
        )
        if restored:
            return False
        raise RemediationError(
            "substituted cleanup leaf was retained without overwrite as "
            f"{quarantine_name}: {label}"
        )

    if directory:
        if remove_contents:
            if descriptor is None:
                raise RemediationError(
                    f"recursive quarantine cleanup lacks held descriptor: {label}"
                )
            _remove_held_directory_contents(descriptor, label)
        final = os.stat(
            quarantine_name,
            dir_fd=parent.parent_descriptor,
            follow_symlinks=False,
        )
        if _created_output_identity(final) != expected_identity:
            restored = _restore_quarantined_leaf(
                parent,
                quarantine_name,
                label,
            )
            if restored:
                return False
            raise RemediationError(
                "directory cleanup quarantine changed and was retained without "
                f"overwrite as {quarantine_name}: {label}"
            )
        os.rmdir(
            quarantine_name,
            dir_fd=parent.parent_descriptor,
        )
    else:
        final = os.stat(
            quarantine_name,
            dir_fd=parent.parent_descriptor,
            follow_symlinks=False,
        )
        if _created_output_identity(final) != expected_identity:
            restored = _restore_quarantined_leaf(
                parent,
                quarantine_name,
                label,
            )
            if restored:
                return False
            raise RemediationError(
                "file cleanup quarantine changed and was retained without "
                f"overwrite as {quarantine_name}: {label}"
            )
        os.unlink(
            quarantine_name,
            dir_fd=parent.parent_descriptor,
        )
    os.fsync(parent.parent_descriptor)
    parent.revalidate(label)
    return True


def _cleanup_constructing_output_leaf(
    parent: HeldOutputParent | HeldPathParent,
    identity: tuple[int, int, int],
    label: str,
    *,
    descriptor: int | None,
    directory: bool,
) -> bool:
    """Remove a construction failure only while the created inode is named."""
    expected_type = stat.S_IFDIR if directory else stat.S_IFREG
    if identity[2] != expected_type:
        raise RemediationError(
            f"construction cleanup identity has the wrong type: {label}"
        )
    return _quarantine_owned_output_leaf(
        parent,
        identity,
        label,
        descriptor=descriptor,
        directory=directory,
        remove_contents=False,
    )


def _open_exclusive_output_file(
    path: Path,
    label: str,
    *,
    mode: int,
) -> SecureOutputFile:
    parent = _open_output_parent(path, label)
    descriptor: int | None = None
    created_identity: tuple[int, int, int] | None = None
    try:
        parent.revalidate(label)
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            descriptor = os.open(
                parent.leaf_name,
                flags,
                mode,
                dir_fd=parent.parent_descriptor,
            )
        except FileExistsError as exc:
            raise RemediationError(
                f"secure output leaf already exists: {label}"
            ) from exc
        except OSError as exc:
            raise RemediationError(
                f"secure output leaf failed O_EXCL|O_NOFOLLOW creation: {label}"
            ) from exc
        try:
            created = os.stat(descriptor)
        except OSError as exc:
            try:
                created_identity = (
                    _recover_descriptor_identity_after_metadata_failure(
                        descriptor,
                        stat.S_IFREG,
                        label,
                    )
                )
            except RemediationError as recovery_exc:
                raise RemediationError(
                    "initial secure output identity acquisition failed and "
                    f"ownership could not be re-established: {label}"
                ) from recovery_exc
            raise RemediationError(
                f"initial secure output identity acquisition failed: {label}"
            ) from exc
        created_identity = _created_output_identity(created)
        if not stat.S_ISREG(created.st_mode):
            raise RemediationError(
                f"secure output creation did not produce a regular file: {label}"
            )
        os.fchmod(descriptor, mode)
        opened = os.fstat(descriptor)
        entry = os.stat(
            parent.leaf_name,
            dir_fd=parent.parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(entry.st_mode)
            or _created_output_identity(opened) != created_identity
            or _created_output_identity(entry) != created_identity
            or stat.S_IMODE(opened.st_mode) != mode
            or stat.S_IMODE(entry.st_mode) != mode
        ):
            raise RemediationError(
                f"secure output changed during initial identity validation: "
                f"{label}"
            )
        result = SecureOutputFile(
            parent=parent,
            descriptor=descriptor,
            device=opened.st_dev,
            inode=opened.st_ino,
            mode=mode,
        )
        result.revalidate(label)
        return result
    except Exception:
        if created_identity is not None:
            _cleanup_constructing_output_leaf(
                parent,
                created_identity,
                f"{label} construction cleanup",
                descriptor=descriptor,
                directory=False,
            )
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        parent.close()
        raise


def _hash_open_descriptor(
    descriptor: int,
    maximum: int,
    label: str,
) -> tuple[str, int]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise RemediationError(f"secure output exceeds byte limit: {label}")
        digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest(), total


def _remove_held_directory_contents(descriptor: int, label: str) -> None:
    """Recursively remove entries beneath an already-held directory."""
    root = os.fstat(descriptor)
    if not stat.S_ISDIR(root.st_mode):
        raise RemediationError(
            f"cleanup root is not a held directory: {label}"
        )
    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        names = sorted(os.listdir(descriptor))
    except OSError as exc:
        raise RemediationError(
            f"could not enumerate failed Git destination: {label}"
        ) from exc
    for name in names:
        if name in {"", ".", ".."} or "/" in name or "\x00" in name:
            raise RemediationError(
                f"unsafe entry in failed Git destination: {label}"
            )
        try:
            entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(entry.st_mode):
            child: int | None = None
            try:
                child = os.open(name, directory_flags, dir_fd=descriptor)
                opened = os.fstat(child)
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or opened.st_dev != entry.st_dev
                    or opened.st_ino != entry.st_ino
                ):
                    raise RemediationError(
                        f"failed Git destination child was substituted: {label}"
                    )
                _remove_held_directory_contents(child, label)
                current = os.stat(
                    name,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISDIR(current.st_mode)
                    or current.st_dev != opened.st_dev
                    or current.st_ino != opened.st_ino
                ):
                    raise RemediationError(
                        f"failed Git destination child changed during cleanup: "
                        f"{label}"
                    )
                os.rmdir(name, dir_fd=descriptor)
                os.fsync(descriptor)
            finally:
                if child is not None:
                    os.close(child)
        else:
            current = os.stat(
                name,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            if (
                current.st_dev != entry.st_dev
                or current.st_ino != entry.st_ino
                or stat.S_IFMT(current.st_mode) != stat.S_IFMT(entry.st_mode)
            ):
                raise RemediationError(
                    f"failed Git destination leaf changed during cleanup: {label}"
                )
            os.unlink(name, dir_fd=descriptor)
            os.fsync(descriptor)
    os.fsync(descriptor)


def _secure_create_output(
    path: Path,
    payload: bytes,
    label: str,
    *,
    mode: int = 0o600,
    maximum: int | None = None,
) -> dict[str, Any]:
    if maximum is not None and len(payload) > maximum:
        raise RemediationError(f"secure output exceeds byte limit: {label}")
    output = _open_exclusive_output_file(path, label, mode=mode)
    try:
        _write_all(output.descriptor, payload)
        output.fsync(label)
        digest, size = _hash_open_descriptor(
            output.descriptor,
            maximum if maximum is not None else len(payload),
            label,
        )
        observed = output.revalidate(label)
        if (
            size != len(payload)
            or observed.st_size != len(payload)
            or digest != _sha256_bytes(payload)
        ):
            raise RemediationError(
                f"secure output changed before descriptor validation: {label}"
            )
        output.fsync(label)
        return {"sha256": digest, "size_bytes": size}
    except Exception:
        output.cleanup_if_owned(f"{label} failed-output cleanup")
        raise
    finally:
        output.close()


def _secure_replace_output(
    path: Path,
    payload: bytes,
    label: str,
    *,
    mode: int = 0o600,
) -> dict[str, Any]:
    parent = _open_output_parent(path, label)
    temporary_name = (
        f".{parent.leaf_name}.g012-{secrets.token_hex(16)}"
    )
    temporary_path = parent.path.with_name(temporary_name)
    temporary: SecureOutputFile | None = None
    try:
        temporary = _open_exclusive_output_file(
            temporary_path,
            f"{label} replacement temporary",
            mode=mode,
        )
        _write_all(temporary.descriptor, payload)
        temporary.fsync(label)
        digest, size = _hash_open_descriptor(
            temporary.descriptor,
            len(payload),
            label,
        )
        if digest != _sha256_bytes(payload) or size != len(payload):
            raise RemediationError(f"replacement output hash mismatch: {label}")
        temporary.revalidate(label)
        parent.revalidate(label)
        os.replace(
            temporary_name,
            parent.leaf_name,
            src_dir_fd=parent.parent_descriptor,
            dst_dir_fd=parent.parent_descriptor,
        )
        os.fsync(parent.parent_descriptor)
        parent.revalidate(label)
        replaced = os.stat(
            parent.leaf_name,
            dir_fd=parent.parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(replaced.st_mode)
            or replaced.st_dev != temporary.device
            or replaced.st_ino != temporary.inode
        ):
            raise RemediationError(f"replacement output was substituted: {label}")
        return {"sha256": digest, "size_bytes": size}
    finally:
        if temporary is not None:
            temporary.cleanup_if_owned(
                f"{label} replacement temporary cleanup"
            )
            temporary.close()
        parent.close()


def _secure_write_if_absent_or_equal(
    path: Path,
    payload: bytes,
    label: str,
) -> None:
    try:
        _secure_create_output(path, payload, label)
        return
    except RemediationError as exc:
        if "secure output leaf already exists" not in str(exc):
            raise
    existing = _read_regular(path, label, max(len(payload), 1))
    if existing != payload:
        raise RemediationError(
            f"existing secure output differs from required content: {label}"
        )


def _read_optional_regular(
    path: Path,
    label: str,
    maximum: int,
) -> bytes | None:
    parent = _open_output_parent(path, label)
    try:
        parent.revalidate(label)
        try:
            observed = os.stat(
                parent.leaf_name,
                dir_fd=parent.parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            parent.revalidate(label)
            return None
        if not stat.S_ISREG(observed.st_mode):
            raise RemediationError(f"optional discovered output is unsafe: {label}")
        parent.revalidate(label)
    finally:
        parent.close()
    return _read_regular(path, label, maximum)


def _prepare_exclusive_destination(
    path: Path,
    label: str,
) -> HeldExclusiveDestination:
    parent = _open_output_parent(path, label)
    descriptor: int | None = None
    created_identity: tuple[int, int, int] | None = None
    try:
        parent.revalidate(label)
        try:
            os.mkdir(
                parent.leaf_name,
                mode=0o700,
                dir_fd=parent.parent_descriptor,
            )
        except FileExistsError as exc:
            raise RemediationError(
                f"exclusive Git destination already exists: {label}"
            ) from exc
        except OSError as exc:
            raise RemediationError(
                f"could not securely create exclusive Git destination: {label}"
            ) from exc
        parent_after_mkdir = _construction_parent_identity(
            os.fstat(parent.parent_descriptor)
        )
        try:
            created = os.stat(
                parent.leaf_name,
                dir_fd=parent.parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            try:
                created_identity = (
                    _recover_directory_identity_after_metadata_failure(
                        parent,
                        parent_after_mkdir,
                        label,
                    )
                )
            except RemediationError as recovery_exc:
                raise RemediationError(
                    "initial Git destination identity acquisition failed and "
                    f"ownership could not be re-established: {label}"
                ) from recovery_exc
            raise RemediationError(
                f"initial Git destination identity acquisition failed: {label}"
            ) from exc
        created_identity = _created_output_identity(created)
        if not stat.S_ISDIR(created.st_mode):
            raise RemediationError(
                f"exclusive Git destination creation was substituted: {label}"
            )
        descriptor = os.open(
            parent.leaf_name,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent.parent_descriptor,
        )
        os.fchmod(descriptor, 0o700)
        opened = os.fstat(descriptor)
        entry = os.stat(
            parent.leaf_name,
            dir_fd=parent.parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(entry.st_mode)
            or _created_output_identity(opened) != created_identity
            or _created_output_identity(entry) != created_identity
            or stat.S_IMODE(opened.st_mode) != 0o700
            or stat.S_IMODE(entry.st_mode) != 0o700
        ):
            raise RemediationError(
                f"exclusive Git destination changed during creation: {label}"
            )
        destination = HeldExclusiveDestination(
            parent=parent,
            descriptor=descriptor,
            device=opened.st_dev,
            inode=opened.st_ino,
            mode=0o700,
            label=label,
        )
        destination.verify_created_directory()
        return destination
    except Exception:
        if created_identity is not None:
            _cleanup_constructing_output_leaf(
                parent,
                created_identity,
                f"{label} construction cleanup",
                descriptor=descriptor,
                directory=True,
            )
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        parent.close()
        raise


@dataclass
class HeldAnchoredRegularFile:
    parent: HeldOutputParent
    descriptor: int
    identity: tuple[int, ...]
    closed: bool = False

    def revalidate(self, label: str) -> None:
        if self.closed:
            raise RemediationError(f"held regular file is already closed: {label}")
        self.parent.revalidate(label)
        entry = os.stat(
            self.parent.leaf_name,
            dir_fd=self.parent.parent_descriptor,
            follow_symlinks=False,
        )
        opened = os.fstat(self.descriptor)
        if (
            not stat.S_ISREG(entry.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or _source_stat_identity(entry) != self.identity
            or _source_stat_identity(opened) != self.identity
        ):
            raise RemediationError(
                f"anchored regular file changed during secure read: {label}"
            )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.close(self.descriptor)
        finally:
            self.parent.close()


def _open_anchored_regular(
    path: Path,
    label: str,
    expected_stat: os.stat_result | None,
) -> HeldAnchoredRegularFile:
    parent = _open_output_parent(path, label)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            parent.leaf_name,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent.parent_descriptor,
        )
        opened = os.fstat(descriptor)
        identity = _source_stat_identity(opened)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (
                expected_stat is not None
                and _source_stat_identity(expected_stat) != identity
            )
        ):
            raise RemediationError(f"anchored input is not stable: {label}")
        result = HeldAnchoredRegularFile(
            parent=parent,
            descriptor=descriptor,
            identity=identity,
        )
        result.revalidate(label)
        return result
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        parent.close()
        raise


def _open_secure_regular(
    path: Path,
    label: str,
    *,
    expected_stat: os.stat_result | None = None,
) -> HeldRegularFile | HeldAnchoredRegularFile:
    if _active_run_root_relative(path) is not None:
        return _open_anchored_regular(path, label, expected_stat)
    parent = _hold_path_parent(path, label)
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(
                parent.leaf_name,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent.parent_descriptor,
            )
        except FileNotFoundError as exc:
            parent.revalidate(label)
            raise RemediationError(
                f"required regular file disappeared before secure open: {label}"
            ) from exc
        except OSError as exc:
            raise RemediationError(
                f"regular file could not be opened with descriptor-relative "
                f"O_NOFOLLOW traversal: {label}"
            ) from exc
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise RemediationError(f"secure input is not a regular file: {label}")
        identity = _source_stat_identity(opened)
        if (
            expected_stat is not None
            and _source_stat_identity(expected_stat) != identity
        ):
            raise RemediationError(
                f"required regular file changed before secure open: {label}"
            )
        held = HeldRegularFile(
            parent=parent,
            descriptor=descriptor,
            identity=identity,
        )
        held.revalidate(label)
        return held
    except Exception:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        parent.close()
        raise


def _secure_lstat(
    path: Path,
    label: str,
    *,
    required: bool,
) -> os.stat_result | None:
    parent = _hold_path_parent(path, label)
    try:
        try:
            result = os.stat(
                parent.leaf_name,
                dir_fd=parent.parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            parent.revalidate(label)
            if not required:
                return None
            raise RemediationError(
                f"required discovered path disappeared: {label}"
            ) from exc
        except OSError as exc:
            raise RemediationError(
                f"descriptor-relative lstat failed for required path: {label}"
            ) from exc
        parent.revalidate(label)
        try:
            repeated = os.stat(
                parent.leaf_name,
                dir_fd=parent.parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise RemediationError(
                f"path disappeared during descriptor-relative lstat: {label}"
            ) from exc
        if _source_stat_identity(result) != _source_stat_identity(repeated):
            raise RemediationError(
                f"path changed during descriptor-relative lstat: {label}"
            )
        return result
    finally:
        parent.close()


def _secure_readlink(
    path: Path,
    label: str,
    expected_stat: os.stat_result,
) -> bytes:
    parent = _hold_path_parent(path, label)
    try:
        before = parent.leaf_lstat(label)
        identity = _source_stat_identity(expected_stat)
        if (
            not stat.S_ISLNK(before.st_mode)
            or _source_stat_identity(before) != identity
        ):
            raise RemediationError(
                f"required symlink changed before secure read: {label}"
            )
        try:
            target = os.readlink(
                parent.leaf_name,
                dir_fd=parent.parent_descriptor,
            )
        except OSError as exc:
            raise RemediationError(f"could not securely read symlink: {label}") from exc
        middle = parent.leaf_lstat(label)
        parent.revalidate(label)
        try:
            repeated_target = os.readlink(
                parent.leaf_name,
                dir_fd=parent.parent_descriptor,
            )
        except OSError as exc:
            raise RemediationError(
                f"symlink disappeared during repeated secure read: {label}"
            ) from exc
        after = parent.leaf_lstat(label)
        if (
            _source_stat_identity(middle) != identity
            or _source_stat_identity(after) != identity
            or target != repeated_target
        ):
            raise RemediationError(f"symlink changed during secure read: {label}")
        payload = target.encode("utf-8", "surrogateescape")
        if len(payload) != expected_stat.st_size:
            raise RemediationError(f"symlink size changed during secure read: {label}")
        return payload
    finally:
        parent.close()


def _secure_directory_stat(
    path: Path,
    label: str,
    expected_stat: os.stat_result | None = None,
) -> os.stat_result:
    parent = _hold_path_parent(path, label)
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(
                parent.leaf_name,
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent.parent_descriptor,
            )
        except OSError as exc:
            raise RemediationError(
                f"directory failed descriptor-relative no-symlink open: {label}"
            ) from exc
        opened = os.fstat(descriptor)
        entry = parent.leaf_lstat(label)
        identity = _directory_topology_identity(opened)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(entry.st_mode)
            or _directory_topology_identity(entry) != identity
            or (
                expected_stat is not None
                and _directory_topology_identity(expected_stat) != identity
            )
        ):
            raise RemediationError(f"directory topology changed: {label}")
        parent.revalidate(label)
        repeated = os.fstat(descriptor)
        if _directory_topology_identity(repeated) != identity:
            raise RemediationError(f"directory identity changed: {label}")
        return opened
    finally:
        if descriptor is not None:
            os.close(descriptor)
        parent.close()


@dataclass
class HeldAnchoredDirectoryRoot:
    parent: HeldOutputParent
    descriptor: int
    identity: tuple[int, ...]
    topology_identity: tuple[int, ...]
    closed: bool = False

    def revalidate(self, label: str) -> None:
        if self.closed:
            raise RemediationError(
                f"held anchored directory is already closed: {label}"
            )
        self.parent.revalidate(label)
        entry = os.stat(
            self.parent.leaf_name,
            dir_fd=self.parent.parent_descriptor,
            follow_symlinks=False,
        )
        opened = os.fstat(self.descriptor)
        if (
            not stat.S_ISDIR(entry.st_mode)
            or not stat.S_ISDIR(opened.st_mode)
            or _directory_topology_identity(entry) != self.topology_identity
            or _directory_topology_identity(opened) != self.topology_identity
        ):
            raise RemediationError(
                f"anchored directory topology changed: {label}"
            )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.close(self.descriptor)
        finally:
            self.parent.close()


@dataclass
class HeldAnchoredRunRootView:
    anchor: RunRootAnchor
    descriptor: int
    identity: tuple[int, ...]
    closed: bool = False

    def revalidate(self, label: str) -> None:
        if self.closed:
            raise RemediationError(
                f"held run-root view is already closed: {label}"
            )
        self.anchor.descriptor_revalidate(label)
        observed = os.fstat(self.descriptor)
        if (
            not stat.S_ISDIR(observed.st_mode)
            or _source_stat_identity(observed) != self.identity
        ):
            raise RemediationError(
                f"held run-root view changed during inventory: {label}"
            )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        os.close(self.descriptor)


def _open_held_directory_root(
    path: Path,
    label: str,
    *,
    required: bool,
) -> HeldDirectoryRoot | HeldAnchoredDirectoryRoot | HeldAnchoredRunRootView | None:
    normalized = Path(os.path.normpath(os.fspath(path)))
    for anchor in tuple(_ACTIVE_RUN_ROOT_ANCHORS.values()):
        if not anchor.closed and normalized == anchor.command_path:
            anchor.descriptor_revalidate(label)
            descriptor = os.dup(anchor.held.descriptor)
            opened = os.fstat(descriptor)
            result = HeldAnchoredRunRootView(
                anchor=anchor,
                descriptor=descriptor,
                identity=_source_stat_identity(opened),
            )
            result.revalidate(label)
            return result
    if _active_run_root_relative(path) is not None:
        parent = _open_output_parent(path, label)
        descriptor: int | None = None
        try:
            try:
                descriptor = os.open(
                    parent.leaf_name,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=parent.parent_descriptor,
                )
            except FileNotFoundError as exc:
                parent.revalidate(label)
                if not required:
                    parent.close()
                    return None
                raise RemediationError(
                    f"required anchored directory disappeared: {label}"
                ) from exc
            opened = os.fstat(descriptor)
            if not stat.S_ISDIR(opened.st_mode):
                raise RemediationError(
                    f"anchored inventory root is not a directory: {label}"
                )
            result = HeldAnchoredDirectoryRoot(
                parent=parent,
                descriptor=descriptor,
                identity=_source_stat_identity(opened),
                topology_identity=_directory_topology_identity(opened),
            )
            result.revalidate(label)
            return result
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            parent.close()
            raise
    parent = _hold_path_parent(path, label)
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(
                parent.leaf_name,
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent.parent_descriptor,
            )
        except FileNotFoundError as exc:
            parent.revalidate(label)
            if not required:
                parent.close()
                return None
            raise RemediationError(
                f"required directory inventory root disappeared: {label}"
            ) from exc
        except OSError as exc:
            raise RemediationError(
                f"directory inventory root failed O_DIRECTORY|O_NOFOLLOW open: "
                f"{label}"
            ) from exc
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise RemediationError(f"inventory root is not a directory: {label}")
        held = HeldDirectoryRoot(
            parent=parent,
            descriptor=descriptor,
            identity=_source_stat_identity(opened),
        )
        held.revalidate(label)
        return held
    except Exception:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        parent.close()
        raise


def _revalidate_directory_chain(
    root: HeldDirectoryRoot,
    edges: tuple[HeldDirectoryEdge, ...],
    label: str,
) -> None:
    root.revalidate(label)
    for edge in edges:
        try:
            entry_stat = os.stat(
                edge.name,
                dir_fd=edge.parent_descriptor,
                follow_symlinks=False,
            )
            descriptor_stat = os.fstat(edge.descriptor)
        except OSError as exc:
            raise RemediationError(
                f"directory inventory ancestor disappeared: {label}"
            ) from exc
        if (
            not stat.S_ISDIR(entry_stat.st_mode)
            or not stat.S_ISDIR(descriptor_stat.st_mode)
            or _source_stat_identity(entry_stat) != edge.identity
            or _source_stat_identity(descriptor_stat) != edge.identity
        ):
            raise RemediationError(
                f"directory inventory ancestor topology changed: {label}"
            )
    root.revalidate(label)


def _sha256_file(path: Path, maximum: int | None = None) -> str:
    held = _open_secure_regular(path, f"SHA256 input {path}")
    assert held is not None
    digest = hashlib.sha256()
    total = 0
    before = os.fstat(held.descriptor)
    try:
        held.revalidate(f"SHA256 input {path}")
        os.lseek(held.descriptor, 0, os.SEEK_SET)
        while True:
            chunk = os.read(held.descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if maximum is not None and total > maximum:
                raise RemediationError(f"file exceeds safety limit: {path}")
            digest.update(chunk)
        middle = os.fstat(held.descriptor)
        held.revalidate(f"SHA256 input {path}")
        after = os.fstat(held.descriptor)
        if (
            total != before.st_size
            or _source_stat_identity(before) != _source_stat_identity(middle)
            or _source_stat_identity(before) != _source_stat_identity(after)
        ):
            raise RemediationError(f"file changed while hashing: {path}")
    finally:
        held.close()
    return digest.hexdigest()


def _read_regular(
    path: Path,
    label: str,
    maximum: int = MAX_CAPTURE_BYTES,
) -> bytes:
    if (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum < 0
    ):
        raise RemediationError(f"{label} has an invalid byte limit")
    held = _open_secure_regular(path, label)
    try:
        before = os.fstat(held.descriptor)
        if before.st_size > maximum:
            raise RemediationError(f"{label} exceeds the byte limit: {path}")
        held.revalidate(label)
        payload = _read_bounded_fd(held.descriptor, maximum, label)
        middle = os.fstat(held.descriptor)
        if _source_stat_identity(middle) != _source_stat_identity(before):
            raise RemediationError(f"{label} changed during bounded read")
        held.revalidate(label)
        after = os.fstat(held.descriptor)
        if (
            len(payload) != before.st_size
            or _source_stat_identity(after) != _source_stat_identity(before)
        ):
            raise RemediationError(f"{label} changed after bounded read")
        held.revalidate(label)
        return payload
    finally:
        held.close()


def _read_regular_from_source_anchor(
    anchor: SourceRepositoryAnchor,
    relative: Path,
    label: str,
    maximum: int = MAX_CAPTURE_BYTES,
    *,
    required: bool = True,
) -> bytes | None:
    if (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum < 0
    ):
        raise RemediationError(f"{label} has an invalid byte limit")
    path = PurePosixPath(relative.as_posix())
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RemediationError(f"unsafe source-relative path: {relative}")
    root = anchor.held
    root.revalidate(label)
    descriptor = root.descriptor
    edges: list[HeldDirectoryEdge] = []
    leaf_descriptor: int | None = None
    try:
        for component in path.parts[:-1]:
            try:
                entry_stat = os.stat(
                    component,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
                child = os.open(
                    component,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=descriptor,
                )
            except FileNotFoundError as exc:
                if not required:
                    return None
                raise RemediationError(
                    f"required source authority ancestor disappeared: {label}"
                ) from exc
            except OSError as exc:
                raise RemediationError(
                    f"source authority ancestor failed secure open: {label}"
                ) from exc
            opened = os.fstat(child)
            identity = _source_stat_identity(opened)
            if (
                not stat.S_ISDIR(entry_stat.st_mode)
                or not stat.S_ISDIR(opened.st_mode)
                or _source_stat_identity(entry_stat) != identity
            ):
                os.close(child)
                raise RemediationError(
                    f"source authority ancestor topology changed: {label}"
                )
            edge = HeldDirectoryEdge(
                parent_descriptor=descriptor,
                name=component,
                descriptor=child,
                identity=identity,
            )
            edges.append(edge)
            descriptor = child
            _revalidate_directory_chain(root, tuple(edges), label)
        leaf = path.parts[-1]
        try:
            entry_before = os.stat(
                leaf,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            leaf_descriptor = os.open(
                leaf,
                os.O_RDONLY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=descriptor,
            )
        except FileNotFoundError as exc:
            if not required:
                return None
            raise RemediationError(
                f"required source authority disappeared: {label}"
            ) from exc
        except OSError as exc:
            raise RemediationError(
                f"required source authority disappeared or failed secure open: {label}"
            ) from exc
        before = os.fstat(leaf_descriptor)
        identity = _source_stat_identity(before)
        if (
            not stat.S_ISREG(entry_before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or _source_stat_identity(entry_before) != identity
        ):
            raise RemediationError(f"source authority is not a stable regular file: {label}")
        if before.st_size > maximum:
            raise RemediationError(f"{label} exceeds the byte limit")
        _revalidate_directory_chain(root, tuple(edges), label)
        payload = _read_bounded_fd(leaf_descriptor, maximum, label)
        middle = os.fstat(leaf_descriptor)
        entry_after = os.stat(
            leaf,
            dir_fd=descriptor,
            follow_symlinks=False,
        )
        _revalidate_directory_chain(root, tuple(edges), label)
        after = os.fstat(leaf_descriptor)
        if (
            len(payload) != before.st_size
            or _source_stat_identity(middle) != identity
            or _source_stat_identity(after) != identity
            or _source_stat_identity(entry_after) != identity
        ):
            raise RemediationError(f"source authority changed during secure read: {label}")
        return payload
    finally:
        if leaf_descriptor is not None:
            os.close(leaf_descriptor)
        for edge in reversed(edges):
            os.close(edge.descriptor)
        root.revalidate(label)


def _git_env() -> dict[str, str]:
    # Never inherit repository/config routing.  In particular, GIT_DIR,
    # GIT_WORK_TREE, GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY,
    # GIT_ALTERNATE_OBJECT_DIRECTORIES, GIT_COMMON_DIR, GIT_CONFIG_* and
    # GIT_CEILING_DIRECTORIES can all redirect an otherwise explicit command.
    return {
        "PATH": os.defpath,
        "HOME": os.devnull,
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": os.devnull,
        "GIT_SSH_COMMAND": "false",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "GIT_EDITOR": "false",
        "GIT_SEQUENCE_EDITOR": "false",
        "GIT_MERGE_AUTOEDIT": "no",
    }


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
    maximum_output: int = MAX_CAPTURE_BYTES,
    env: dict[str, str] | None = None,
    pass_fds: tuple[int, ...] = (),
) -> bytes:
    if not command:
        raise RemediationError("empty subprocess command")
    executable = Path(command[0]).name
    if executable in {"git", "git.exe"}:
        index = 1
        while index < len(command):
            part = command[index]
            if part in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
                index += 2
                continue
            if part.startswith("-"):
                index += 1
                continue
            break
        verb = command[index].lower() if index < len(command) else ""
        if verb in {
            "fetch",
            "push",
            "pull",
            "remote",
            "send-pack",
            "receive-pack",
            "ls-remote",
        }:
            raise RemediationError(
                f"network/remote Git operation is forbidden: {command!r}"
            )
    inherited_descriptors = set(pass_fds)
    inherited_descriptors.update(
        anchor.held.descriptor
        for anchor in tuple(_ACTIVE_RUN_ROOT_ANCHORS.values())
        if not anchor.closed
    )
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env or _git_env(),
        pass_fds=tuple(sorted(inherited_descriptors)),
    )
    if len(completed.stdout) > maximum_output or len(completed.stderr) > maximum_output:
        raise RemediationError(f"subprocess output exceeded the bounded capture limit: {command!r}")
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        if not detail:
            detail = completed.stdout.decode("utf-8", "replace").strip()
        raise RemediationError(
            f"command failed ({completed.returncode}): {' '.join(command)}: {detail}"
        )
    return completed.stdout


def _git(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
    *arguments: str,
    input_bytes: bytes | None = None,
    maximum_output: int = MAX_CAPTURE_BYTES,
    pass_fds: tuple[int, ...] = (),
) -> bytes:
    command_path, repository_pass_fds = _git_context(repo)
    return _run(
        [
            "git",
            *_git_safety_arguments(),
            "-C",
            str(command_path),
            *arguments,
        ],
        input_bytes=input_bytes,
        maximum_output=maximum_output,
        pass_fds=tuple(sorted({*repository_pass_fds, *pass_fds})),
    )


def _absolute_git_path(
    source: Path | SourceRepositoryAnchor | RepositoryLayout,
    *arguments: str,
) -> Path:
    text = _git(source, "rev-parse", "--path-format=absolute", *arguments).decode().strip()
    if not text:
        raise RemediationError(f"Git returned an empty path for {' '.join(arguments)}")
    path = Path(text)
    if not path.is_absolute():
        raise RemediationError(f"Git returned a non-absolute path for {' '.join(arguments)}")
    return Path(os.path.normpath(os.fspath(path)))


def _path_is_within(root: Path, path: Path) -> bool:
    root = Path(os.path.normpath(os.fspath(root)))
    path = Path(os.path.normpath(os.fspath(path)))
    return path == root or root in path.parents


def _require_internal_git_storage(
    source: Path,
    paths: Iterable[tuple[str, Path]],
) -> None:
    for label, path in paths:
        if not path.is_absolute() or not _path_is_within(source, path):
            raise RemediationError(
                f"{label} is outside the lifetime-anchored source worktree; "
                "external Git administration/object storage is unsupported: "
                f"{path}"
            )


def _discover_object_databases(
    primary: Path,
    *,
    anchored_source: Path,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    if not primary.is_absolute():
        raise RemediationError("primary Git object database path must be absolute")
    pending = [Path(os.path.normpath(os.fspath(primary)))]
    object_dirs: list[Path] = []
    alternate_files: list[Path] = []
    seen: set[Path] = set()
    while pending:
        object_dir = pending.pop()
        if object_dir in seen:
            continue
        if len(seen) >= 64:
            raise RemediationError("Git alternate object database graph exceeds 64 entries")
        _secure_directory_stat(
            object_dir,
            f"Git object database {object_dir}",
        )
        seen.add(object_dir)
        object_dirs.append(object_dir)
        alternates_file = object_dir / "info" / "alternates"
        discovered = _secure_lstat(
            alternates_file,
            f"Git object alternates for {object_dir}",
            required=False,
        )
        if discovered is None:
            continue
        payload = _read_regular(
            alternates_file,
            f"Git object alternates for {object_dir}",
        )
        assert payload is not None
        alternate_files.append(alternates_file)
        try:
            lines = payload.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise RemediationError(
                f"Git alternates file is not UTF-8: {alternates_file}"
            ) from exc
        if not lines:
            raise RemediationError(f"Git alternates file is empty: {alternates_file}")
        for number, raw in enumerate(lines, 1):
            if not raw or "\x00" in raw:
                raise RemediationError(
                    f"invalid alternate object path at {alternates_file}:{number}"
                )
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = object_dir / candidate
            candidate = Path(os.path.normpath(os.fspath(candidate)))
            _require_internal_git_storage(
                anchored_source,
                [("alternate Git object store", candidate)],
            )
            _secure_directory_stat(
                candidate,
                f"alternate object database at "
                f"{alternates_file}:{number}: {raw!r}",
            )
            pending.append(candidate)
    return (
        tuple(sorted(object_dirs, key=str)),
        tuple(sorted(set(alternate_files), key=str)),
    )


def _resolve_repository(source_arg: str) -> RepositoryLayout:
    supplied = Path(source_arg)
    if not supplied.is_absolute():
        raise RemediationError("--source must be an explicit absolute path")
    if not Path("/proc/self/fd").is_dir():
        raise RemediationError("/proc/self/fd is required for anchored source access")
    supplied = Path(os.path.normpath(os.path.abspath(os.fspath(supplied))))
    supplied_held = _open_held_directory_root(
        supplied,
        "supplied source repository path",
        required=True,
    )
    assert supplied_held is not None
    preliminary = SourceRepositoryAnchor(supplied, supplied_held)
    anchor: SourceRepositoryAnchor | None = None
    try:
        if _git(
            preliminary, "rev-parse", "--is-bare-repository"
        ).decode().strip() == "true":
            raise RemediationError("--source must name a non-bare repository worktree")
        prefix_text = _git(
            preliminary, "rev-parse", "--show-prefix"
        ).decode("utf-8", "strict").strip().strip("/")
        prefix = PurePosixPath(prefix_text) if prefix_text else PurePosixPath()
        if any(part in {"", ".", ".."} for part in prefix.parts):
            raise RemediationError("Git returned an unsafe repository-relative prefix")
        source = supplied
        for _part in prefix.parts:
            source = source.parent
        if source == supplied:
            anchor = preliminary
            preliminary = None  # type: ignore[assignment]
        else:
            preliminary.revalidate("supplied source before top-level anchoring")
            ascended_descriptor = os.dup(preliminary.held.descriptor)
            try:
                for _part in prefix.parts:
                    parent_descriptor = os.open(
                        "..",
                        os.O_RDONLY
                        | os.O_DIRECTORY
                        | os.O_NOFOLLOW
                        | getattr(os, "O_CLOEXEC", 0),
                        dir_fd=ascended_descriptor,
                    )
                    os.close(ascended_descriptor)
                    ascended_descriptor = parent_descriptor
                ascended_identity = _source_stat_identity(
                    os.fstat(ascended_descriptor)
                )
                held = _open_held_directory_root(
                    source,
                    "canonical source repository top-level",
                    required=True,
                )
                assert held is not None
                if (
                    _source_stat_identity(os.fstat(held.descriptor))
                    != ascended_identity
                ):
                    held.close()
                    raise RemediationError(
                        "canonical source top-level changed during descriptor anchoring"
                    )
                anchor = SourceRepositoryAnchor(source, held)
            except OSError as exc:
                raise RemediationError(
                    "could not securely ascend to the repository top-level"
                ) from exc
            finally:
                os.close(ascended_descriptor)
            preliminary.close()
            preliminary = None  # type: ignore[assignment]
        shown_top = Path(
            os.path.normpath(
                _git(anchor, "rev-parse", "--show-toplevel")
                .decode("utf-8", "strict")
                .strip()
            )
        )
        if shown_top != source:
            raise RemediationError(
                "anchored Git top-level does not match the canonical source path"
            )
        git_dir = _absolute_git_path(anchor, "--absolute-git-dir")
        common_raw = _git(
            anchor, "rev-parse", "--path-format=absolute", "--git-common-dir"
        ).decode().strip()
        common_dir = Path(os.path.normpath(common_raw))
        if not common_dir.is_absolute():
            raise RemediationError("Git returned a non-absolute common directory")
        _require_internal_git_storage(
            source,
            (
                ("Git directory", git_dir),
                ("Git common directory", common_dir),
            ),
        )
        object_dir = _absolute_git_path(anchor, "--git-path", "objects")
        _require_internal_git_storage(
            source,
            (("primary Git object store", object_dir),),
        )
        object_dirs, alternate_files = _discover_object_databases(
            object_dir,
            anchored_source=source,
        )
        _require_internal_git_storage(
            source,
            (
                ("Git object store", path)
                for path in object_dirs
            ),
        )
        admin_paths = {
            git_dir,
            common_dir,
            object_dir,
            *alternate_files,
            _absolute_git_path(anchor, "--git-path", "index"),
            _absolute_git_path(anchor, "--git-path", "HEAD"),
            _absolute_git_path(anchor, "--git-path", "logs"),
            Path(os.path.normpath(os.fspath(common_dir / "hooks"))),
            _absolute_git_path(anchor, "--git-path", "config"),
            _absolute_git_path(anchor, "--git-path", "commondir"),
        }
        layout = RepositoryLayout(
            source=source,
            git_dir=git_dir,
            common_dir=common_dir,
            object_dirs=object_dirs,
            alternate_files=alternate_files,
            admin_paths=tuple(sorted(admin_paths, key=str)),
            source_anchor=anchor,
        )
        _reject_sibling_linked_worktrees(layout)
        layout.revalidate("resolved source repository")
        return layout
    except Exception:
        if anchor is not None:
            anchor.close()
        raise
    finally:
        if preliminary is not None:
            preliminary.close()


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve(strict=False)
    right = right.resolve(strict=False)
    return left == right or left in right.parents or right in left.parents


def _reject_sibling_linked_worktrees(layout: RepositoryLayout) -> None:
    worktrees_root = layout.common_dir / "worktrees"
    try:
        relative_git_dir = layout.git_dir.relative_to(worktrees_root)
    except ValueError:
        allowed_name = None
    else:
        if not relative_git_dir.parts:
            raise RemediationError("linked-worktree Git directory is malformed")
        allowed_name = relative_git_dir.parts[0]
    held = _open_held_directory_root(
        worktrees_root,
        "common Git linked-worktree administrative root",
        required=False,
    )
    if held is None:
        if allowed_name is not None:
            raise RemediationError(
                "current linked-worktree administrative directory disappeared"
            )
        return
    try:
        names = sorted(os.listdir(held.descriptor))
        held.revalidate("common Git linked-worktree administrative root")
        if len(names) != len(set(names)) or any(
            not isinstance(name, str)
            or name in {"", ".", ".."}
            or "/" in name
            or "\x00" in name
            for name in names
        ):
            raise RemediationError("invalid linked-worktree administrative entry")
        for name in names:
            try:
                entry = os.stat(
                    name,
                    dir_fd=held.descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise RemediationError(
                    "linked-worktree administrative entry disappeared"
                ) from exc
            if not stat.S_ISDIR(entry.st_mode):
                raise RemediationError(
                    "unsafe linked-worktree administrative entry: "
                    f"{worktrees_root / name}"
                )
        siblings = [name for name in names if name != allowed_name]
        if siblings:
            raise RemediationError(
                "sibling linked worktrees are conservatively unsupported; "
                f"remove them before remediation: {siblings}"
            )
        if allowed_name is not None and names != [allowed_name]:
            raise RemediationError(
                "current linked-worktree administrative directory is not exactly accounted"
            )
        if sorted(os.listdir(held.descriptor)) != names:
            raise RemediationError(
                "linked-worktree administrative root changed during inspection"
            )
        held.revalidate("common Git linked-worktree administrative root")
    finally:
        held.close()


def _prepare_run_root(
    run_arg: str,
    layout: RepositoryLayout,
) -> RunRootAnchor:
    run_root = Path(run_arg)
    if not run_root.is_absolute():
        raise RemediationError("--run-root must be an explicit absolute path")
    unresolved = run_root.resolve(strict=False)
    protected = {
        layout.source,
        layout.git_dir,
        layout.common_dir,
        *layout.object_dirs,
        *layout.admin_paths,
    }
    for path in protected:
        if _paths_overlap(unresolved, path):
            raise RemediationError(
                f"--run-root overlaps source repository storage/admin path: {path}"
            )
    parent = _hold_path_parent(run_root, "--run-root")
    descriptor: int | None = None
    anchor: RunRootAnchor | None = None
    created_identity: tuple[int, int, int] | None = None
    try:
        parent.revalidate("--run-root parent before exclusive creation")
        try:
            os.mkdir(
                parent.leaf_name,
                mode=0o700,
                dir_fd=parent.parent_descriptor,
            )
        except FileExistsError as exc:
            raise RemediationError(
                "--run-root must be absent; pre-existing directories are forbidden"
            ) from exc
        except OSError as exc:
            raise RemediationError(
                "--run-root could not be created under its held parent"
            ) from exc
        parent_after_mkdir = _construction_parent_identity(
            os.fstat(parent.parent_descriptor)
        )
        try:
            created = os.stat(
                parent.leaf_name,
                dir_fd=parent.parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            try:
                created_identity = (
                    _recover_directory_identity_after_metadata_failure(
                        parent,
                        parent_after_mkdir,
                        "--run-root",
                    )
                )
            except RemediationError as recovery_exc:
                raise RemediationError(
                    "initial run-root identity acquisition failed and "
                    "ownership could not be re-established"
                ) from recovery_exc
            raise RemediationError(
                "initial run-root identity acquisition failed"
            ) from exc
        created_identity = _created_output_identity(created)
        if created_identity[2] != stat.S_IFDIR:
            raise RemediationError(
                "--run-root creation was substituted before descriptor open"
            )
        descriptor = os.open(
            parent.leaf_name,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent.parent_descriptor,
        )
        os.fchmod(descriptor, 0o700)
        opened = os.fstat(descriptor)
        entry = os.stat(
            parent.leaf_name,
            dir_fd=parent.parent_descriptor,
            follow_symlinks=False,
        )
        source_identity = _source_stat_identity(opened)
        topology_identity = _directory_topology_identity(opened)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(entry.st_mode)
            or _created_output_identity(opened) != created_identity
            or _created_output_identity(entry) != created_identity
            or stat.S_IMODE(opened.st_mode) != 0o700
            or stat.S_IMODE(entry.st_mode) != 0o700
        ):
            raise RemediationError(
                "--run-root changed during descriptor-relative creation"
            )
        os.fsync(descriptor)
        os.fsync(parent.parent_descriptor)
        held = HeldDirectoryRoot(
            parent=parent,
            descriptor=descriptor,
            identity=source_identity,
        )
        anchor = RunRootAnchor(
            original_path=unresolved,
            held=held,
            identity=topology_identity,
        )
        _ACTIVE_RUN_ROOT_ANCHORS[descriptor] = anchor
        anchor.revalidate("new run-root anchor")
        return anchor
    except Exception:
        cleanup_failure: Exception | None = None
        try:
            if created_identity is not None:
                _cleanup_constructing_output_leaf(
                    parent,
                    created_identity,
                    "--run-root construction cleanup",
                    descriptor=descriptor,
                    directory=True,
                )
        except Exception as exc:
            cleanup_failure = exc
        if anchor is not None:
            anchor.close()
            descriptor = None
            parent_closed = True
        else:
            parent_closed = False
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if not parent_closed:
            parent.close()
        if cleanup_failure is not None:
            raise RemediationError(
                "run-root construction cleanup could not be completed safely"
            ) from cleanup_failure
        raise


def _anchor_existing_run_root(run_arg: str) -> RunRootAnchor:
    run_root = Path(run_arg)
    if not run_root.is_absolute():
        raise RemediationError(
            "verify --run-root must be an absolute non-symlink directory"
        )
    held = _open_held_directory_root(
        run_root,
        "verify run root",
        required=True,
    )
    assert held is not None
    if not isinstance(held, HeldDirectoryRoot):
        held.close()
        raise RemediationError("verify run-root anchor recursively overlapped itself")
    anchor = RunRootAnchor(
        original_path=Path(os.path.normpath(os.fspath(run_root))),
        held=held,
        identity=_directory_topology_identity(os.fstat(held.descriptor)),
    )
    try:
        _ACTIVE_RUN_ROOT_ANCHORS[held.descriptor] = anchor
        anchor.revalidate("verify run-root anchor")
        return anchor
    except Exception:
        anchor.close()
        raise


def _refs(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
) -> list[dict[str, str]]:
    payload = _git(
        repo,
        "for-each-ref",
        "--format=%(refname)%09%(objectname)%09%(objecttype)%09%(symref)",
    )
    rows: list[dict[str, str]] = []
    for line in payload.decode("utf-8", "strict").splitlines():
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 4:
            raise RemediationError("git returned a malformed ref record")
        row = {
            "ref": fields[0],
            "oid": fields[1],
            "object_type": fields[2],
            "symref": fields[3],
        }
        if (
            not row["ref"].startswith("refs/")
            or not OID_RE.fullmatch(row["oid"])
            or row["object_type"] not in {"blob", "commit", "tag", "tree"}
            or (
                row["symref"]
                and (
                    not row["symref"].startswith("refs/")
                    or any(character.isspace() for character in row["symref"])
                )
            )
        ):
            raise RemediationError("git returned an invalid ref record")
        rows.append(row)
    if len(rows) > MAX_REFS:
        raise RemediationError(f"repository has more than {MAX_REFS} refs")
    rows = sorted(rows, key=lambda row: row["ref"])
    by_ref = {row["ref"]: row for row in rows}
    if len(by_ref) != len(rows):
        raise RemediationError("git returned duplicate ref records")
    for row in rows:
        if row["symref"]:
            target = by_ref.get(row["symref"])
            if (
                target is None
                or target["oid"] != row["oid"]
                or target["object_type"] != row["object_type"]
            ):
                raise RemediationError(
                    f"git returned an unaccounted symbolic ref: "
                    f"{row['ref']} -> {row['symref']}"
                )
    return rows


def _ref_oid_map(refs: Iterable[dict[str, str]]) -> dict[str, str]:
    return {row["ref"]: row["oid"] for row in refs}


def _publishable_refs(refs: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in refs
        if not row["ref"].startswith(SYNTHETIC_EVIDENCE_REF_PREFIX)
    ]


def _evidence_refs(refs: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in refs
        if row["ref"].startswith(SYNTHETIC_EVIDENCE_REF_PREFIX)
    ]


def _require_exact_refs(
    expected: Iterable[dict[str, str]],
    actual: Iterable[dict[str, str]],
    label: str,
) -> None:
    expected_rows = list(expected)
    actual_rows = list(actual)
    expected_map = {row["ref"]: row for row in expected_rows}
    actual_map = {row["ref"]: row for row in actual_rows}
    if len(expected_map) != len(expected_rows) or len(actual_map) != len(actual_rows):
        raise RemediationError(f"{label} contains duplicate ref records")
    if expected_map != actual_map:
        shared = set(expected_map) & set(actual_map)
        changed = {
            ref: {
                field: {
                    "expected": expected_map[ref].get(field),
                    "actual": actual_map[ref].get(field),
                }
                for field in ("oid", "object_type", "symref")
                if expected_map[ref].get(field) != actual_map[ref].get(field)
            }
            for ref in sorted(shared)
            if expected_map[ref] != actual_map[ref]
        }
        raise RemediationError(
            f"{label} ref/OID mismatch (complete object_type/symref records): "
            f"missing={sorted(set(expected_map) - set(actual_map))}, "
            f"extra={sorted(set(actual_map) - set(expected_map))}, "
            f"changed={json.dumps(changed, sort_keys=True)}"
        )


def _restore_symbolic_refs(
    repo: Path,
    expected_refs: Iterable[dict[str, str]],
    label: str,
) -> None:
    expected = {row["ref"]: row for row in expected_refs}
    actual = {row["ref"]: row for row in _refs(repo)}
    for ref, row in sorted(expected.items()):
        target = row["symref"]
        if not target:
            if ref in actual and actual[ref]["symref"]:
                _git(repo, "update-ref", "--no-deref", ref, actual[ref]["oid"])
            continue
        if target not in expected:
            raise RemediationError(
                f"{label} symbolic ref target is outside the accounted ref set: "
                f"{ref} -> {target}"
            )
        if ref not in actual or target not in actual:
            raise RemediationError(
                f"{label} cannot restore missing symbolic ref/target: {ref} -> {target}"
            )
        if actual[ref]["oid"] != actual[target]["oid"]:
            raise RemediationError(
                f"{label} symbolic ref target OID diverged: {ref} -> {target}"
            )
        _git(repo, "symbolic-ref", ref, target)
    restored = {row["ref"]: row for row in _refs(repo)}
    for ref, expected_row in expected.items():
        actual_row = restored.get(ref)
        if actual_row is None:
            raise RemediationError(f"{label} lost ref while restoring symrefs: {ref}")
        if (
            actual_row["symref"] != expected_row["symref"]
            or actual_row["object_type"] != expected_row["object_type"]
        ):
            raise RemediationError(
                f"{label} did not preserve symbolic ref semantics: {ref}"
            )


def _pseudoref_path(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
    name: str,
) -> Path:
    return _absolute_git_path(repo, "--git-path", name)


def _parse_pseudoref_payload(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
    name: str,
    payload: bytes,
) -> list[str]:
    text = payload.decode("utf-8", "strict")
    if text.startswith("ref: "):
        ref = text[5:].strip()
        if not ref.startswith("refs/") or "\n" in ref:
            raise RemediationError(f"malformed symbolic pseudoref {name}")
        return [_git(repo, "rev-parse", "--verify", ref).decode().strip()]
    oids: list[str] = []
    for line in text.splitlines():
        if not line:
            continue
        oid = line.split("\t", 1)[0].split(" ", 1)[0]
        if not OID_RE.fullmatch(oid):
            raise RemediationError(f"malformed object ID in pseudoref {name}")
        _git(repo, "cat-file", "-e", f"{oid}^{{object}}")
        oids.append(oid)
    return sorted(set(oids))


def _known_git_admin_filename(name: str) -> bool:
    return name in KNOWN_GIT_ADMIN_FILES


def _git_admin_roots(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
) -> list[Path]:
    if isinstance(repo, RepositoryLayout):
        return sorted({repo.git_dir, repo.common_dir}, key=str)
    git_dir = Path(
        _git(repo, "rev-parse", "--absolute-git-dir").decode().strip()
    )
    common_dir = Path(
        _git(
            repo,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ).decode().strip()
    )
    return sorted({git_dir, common_dir}, key=str)


def _resolve_admin_object_token(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
    token: str,
) -> list[str]:
    normalized = token.lower()
    if (
        not MIN_GIT_OBJECT_ABBREVIATION <= len(normalized) <= 64
        or any(character not in "0123456789abcdef" for character in normalized)
    ):
        raise RemediationError(f"invalid Git object abbreviation token: {token!r}")
    payload = _git(repo, "rev-parse", f"--disambiguate={normalized}")
    matches = sorted(
        {
            line.decode("ascii", "strict")
            for line in payload.splitlines()
            if line
        }
    )
    if any(
        not OID_RE.fullmatch(oid) or not oid.startswith(normalized)
        for oid in matches
    ):
        raise RemediationError(
            f"Git returned malformed disambiguation output for {token!r}"
        )
    if len(matches) > MAX_REFS:
        raise RemediationError(
            f"Git object abbreviation has too many matches: {token!r}"
        )
    if not matches and OID_RE.fullmatch(normalized) and _object_exists(
        repo, normalized
    ):
        matches = [normalized]
    if len(matches) > 1:
        raise RemediationError(
            "ambiguous abbreviated object ID in unknown Git administrative "
            f"content: {token!r} matched {len(matches)} objects"
        )
    return matches


def _reachable_ref_object_ids(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
) -> set[str]:
    refs = _refs(repo)
    if not refs:
        return set()
    object_ids = _object_ids(repo, [row["ref"] for row in refs])
    if len(object_ids) > MAX_TREE_ENTRIES:
        raise RemediationError(
            "reachable administrative object accounting exceeds the object limit"
        )
    return set(object_ids)


def _reject_unknown_object_bearing_admin_files(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
    budget: LogicalByteBudget | None = None,
) -> None:
    active_budget = budget or LogicalByteBudget(MAX_SOURCE_TOTAL_BYTES)
    reachable_object_ids: set[str] | None = None
    for root in _git_admin_roots(repo):
        held = _open_held_directory_root(
            root,
            f"Git administrative root {root}",
            required=True,
        )
        assert held is not None
        entry_count = 0
        strict_recursive = isinstance(repo, RepositoryLayout)
        skip_relative_directories: set[tuple[str, ...]] = {
            ("objects",),
            ("refs",),
            ("logs",),
        }
        if isinstance(repo, RepositoryLayout) and root == repo.common_dir:
            # Ref/reflog/object roots are captured by their dedicated inventories.
            # All sibling linked worktrees were rejected separately; the current
            # linked worktree Git directory is scanned as its own held root.
            skip_relative_directories.add(("worktrees",))
        if isinstance(repo, RepositoryLayout):
            for object_dir in repo.object_dirs:
                try:
                    relative_object_dir = object_dir.relative_to(root)
                except ValueError:
                    continue
                if relative_object_dir.parts:
                    skip_relative_directories.add(
                        tuple(relative_object_dir.parts)
                    )

        def walk(
            descriptor: int,
            identity: tuple[int, ...],
            edges: tuple[HeldDirectoryEdge, ...],
            relative: tuple[str, ...],
        ) -> None:
            nonlocal entry_count, reachable_object_ids
            display = PurePosixPath(*relative).as_posix() if relative else "."
            label = f"Git administrative root {root}/{display}"
            _revalidate_directory_chain(held, edges, label)
            if _source_stat_identity(os.fstat(descriptor)) != identity:
                raise RemediationError(
                    f"Git administrative directory changed: {root / display}"
                )
            try:
                names = sorted(os.listdir(descriptor))
            except (OSError, TypeError) as exc:
                raise RemediationError(
                    f"could not enumerate Git administrative directory: "
                    f"{root / display}"
                ) from exc
            if len(names) != len(set(names)) or any(
                not isinstance(name, str)
                or name in {"", ".", ".."}
                or "/" in name
                or "\x00" in name
                for name in names
            ):
                raise RemediationError(
                    f"invalid Git administrative entry under {root / display}"
                )
            for name in names:
                child_relative = (*relative, name)
                if child_relative in skip_relative_directories:
                    continue
                entry_count += 1
                if entry_count > MAX_SOURCE_FILES:
                    raise RemediationError(
                        "Git administrative scan exceeds the entry-count limit"
                    )
                child_path = root.joinpath(*child_relative)
                child_label = (
                    "unknown Git administrative file "
                    f"{PurePosixPath(*child_relative).as_posix()}"
                )
                try:
                    entry_stat = os.stat(
                        name,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    raise RemediationError(
                        f"Git administrative entry disappeared: {child_path}"
                    ) from exc
                if stat.S_ISDIR(entry_stat.st_mode):
                    if not strict_recursive and not relative:
                        # Disposable mirrors are verified by exact refs, object
                        # inventories, bundles, and fsck.  The recursive
                        # unknown-admin root policy is source-specific; retain
                        # the legacy top-level pseudoref check for mirrors.
                        continue
                    child_descriptor: int | None = None
                    try:
                        try:
                            child_descriptor = os.open(
                                name,
                                os.O_RDONLY
                                | os.O_DIRECTORY
                                | os.O_NOFOLLOW
                                | getattr(os, "O_CLOEXEC", 0),
                                dir_fd=descriptor,
                            )
                        except OSError as exc:
                            raise RemediationError(
                                "Git administrative child directory failed "
                                f"secure open: {child_path}"
                            ) from exc
                        opened = os.fstat(child_descriptor)
                        child_identity = _source_stat_identity(opened)
                        if (
                            not stat.S_ISDIR(opened.st_mode)
                            or child_identity
                            != _source_stat_identity(entry_stat)
                        ):
                            raise RemediationError(
                                "Git administrative child directory changed: "
                                f"{child_path}"
                            )
                        edge = HeldDirectoryEdge(
                            parent_descriptor=descriptor,
                            name=name,
                            descriptor=child_descriptor,
                            identity=child_identity,
                        )
                        child_edges = (*edges, edge)
                        walk(
                            child_descriptor,
                            child_identity,
                            child_edges,
                            child_relative,
                        )
                        _revalidate_directory_chain(
                            held, child_edges, child_label
                        )
                    finally:
                        if child_descriptor is not None:
                            os.close(child_descriptor)
                    continue
                if stat.S_ISLNK(entry_stat.st_mode):
                    raise RemediationError(
                        "unknown symlinked Git administrative file is forbidden: "
                        f"{child_path}"
                    )
                if not stat.S_ISREG(entry_stat.st_mode):
                    family = child_relative[0] if child_relative else ""
                    if family in {"objects", "refs", "logs", "hooks"}:
                        raise RemediationError(
                            f"special Git {family} entry is forbidden: {child_path}"
                        )
                    raise RemediationError(
                        f"unsupported Git administrative entry: {child_path}"
                    )
                if not relative and _known_git_admin_filename(name):
                    continue
                if entry_stat.st_size > MAX_CAPTURE_BYTES:
                    raise RemediationError(
                        "unknown Git administrative file exceeds byte limit: "
                        f"{child_path}"
                    )
                prescan_label = (
                    "admin-prescan:"
                    f"{PurePosixPath(*child_relative).as_posix()}"
                )
                active_budget.consume(entry_stat.st_size, prescan_label)
                file_descriptor: int | None = None
                try:
                    try:
                        file_descriptor = os.open(
                            name,
                            os.O_RDONLY
                            | os.O_NOFOLLOW
                            | getattr(os, "O_CLOEXEC", 0),
                            dir_fd=descriptor,
                        )
                    except OSError as exc:
                        raise RemediationError(
                            "unknown Git administrative file failed secure open: "
                            f"{child_path}"
                        ) from exc
                    opened = os.fstat(file_descriptor)
                    opened_identity = _source_stat_identity(opened)
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or opened_identity
                        != _source_stat_identity(entry_stat)
                    ):
                        raise RemediationError(
                            f"unknown Git administrative file changed: {child_path}"
                        )
                    _revalidate_directory_chain(held, edges, child_label)
                    payload = _read_bounded_fd(
                        file_descriptor,
                        MAX_CAPTURE_BYTES,
                        child_label,
                    )
                    middle = os.fstat(file_descriptor)
                    after_entry = os.stat(
                        name,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                    _revalidate_directory_chain(held, edges, child_label)
                    if (
                        len(payload) != opened.st_size
                        or _source_stat_identity(middle) != opened_identity
                        or _source_stat_identity(after_entry) != opened_identity
                    ):
                        raise RemediationError(
                            f"unknown Git administrative file changed: {child_path}"
                        )
                finally:
                    if file_descriptor is not None:
                        os.close(file_descriptor)
                candidates = {
                    token.decode("ascii").lower()
                    for token in ADMIN_OBJECT_TOKEN_RE.findall(payload)
                }
                for token in sorted(candidates):
                    matches = _resolve_admin_object_token(repo, token)
                    if not matches:
                        continue
                    if reachable_object_ids is None:
                        reachable_object_ids = _reachable_ref_object_ids(repo)
                    for oid in matches:
                        if oid in reachable_object_ids:
                            continue
                        raise RemediationError(
                            "unaccounted object-bearing pseudoref/Git "
                            f"administrative file: {child_path} "
                            f"(token {token!r} -> {oid})"
                        )
            try:
                final_names = sorted(os.listdir(descriptor))
            except (OSError, TypeError) as exc:
                raise RemediationError(
                    f"Git administrative directory disappeared: {root / display}"
                ) from exc
            if names != final_names:
                raise RemediationError(
                    f"Git administrative directory changed: {root / display}"
                )
            if _source_stat_identity(os.fstat(descriptor)) != identity:
                raise RemediationError(
                    f"Git administrative directory metadata changed: "
                    f"{root / display}"
                )
            _revalidate_directory_chain(held, edges, label)

        try:
            walk(held.descriptor, held.identity, (), ())
            held.revalidate(f"Git administrative root {root}")
        finally:
            held.close()


def _pseudoref_roots(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
) -> list[dict[str, str]]:
    roots: list[dict[str, str]] = []
    _reject_unknown_object_bearing_admin_files(repo)
    for name in PSEUDOREF_NAMES:
        path = _pseudoref_path(repo, name)
        if isinstance(repo, RepositoryLayout):
            try:
                relative = path.relative_to(repo.source)
            except ValueError:
                payload = None
            else:
                payload = _read_regular_from_source_anchor(
                    repo.source_anchor,
                    relative,
                    f"Git pseudoref {name}",
                    required=False,
                )
            if payload is None and path.is_relative_to(repo.source):
                continue
            if payload is None:
                discovered = _secure_lstat(
                    path,
                    f"Git pseudoref {name}",
                    required=False,
                )
                if discovered is None:
                    continue
                payload = _read_regular(path, f"Git pseudoref {name}")
        else:
            discovered = _secure_lstat(
                path,
                f"Git pseudoref {name}",
                required=False,
            )
            if discovered is None:
                continue
            payload = _read_regular(path, f"Git pseudoref {name}")
        assert payload is not None
        for number, oid in enumerate(_parse_pseudoref_payload(repo, name, payload)):
            roots.append(
                {
                    "name": name,
                    "ordinal": str(number),
                    "oid": oid,
                    "path": str(path),
                }
            )
    return roots


def _copy_object_graph(
    source: Path | SourceRepositoryAnchor | RepositoryLayout,
    mirror: Path,
    oid: str,
    seen: set[str],
) -> None:
    if oid in seen or _object_exists(mirror, oid):
        seen.add(oid)
        return
    if len(seen) >= MAX_TREE_ENTRIES:
        raise RemediationError("pseudoref object graph exceeds the object-count limit")
    kind = _git(source, "cat-file", "-t", oid).decode().strip()
    payload = _git(
        source,
        "cat-file",
        kind,
        oid,
        maximum_output=MAX_BLOB_BYTES + 1024,
    )
    if kind == "tree":
        entries = _git(source, "ls-tree", "-z", oid)
        for record in entries.split(b"\x00"):
            if not record:
                continue
            metadata = record.split(b"\t", 1)[0].decode("ascii")
            _mode, child_kind, child_oid = metadata.split(" ")
            if child_kind != "commit":
                _copy_object_graph(source, mirror, child_oid, seen)
    elif kind == "commit":
        headers = payload.split(b"\n\n", 1)[0].splitlines()
        for line in headers:
            if line.startswith(b"tree ") or line.startswith(b"parent "):
                _copy_object_graph(source, mirror, line.split(b" ", 1)[1].decode(), seen)
    elif kind == "tag":
        first = payload.splitlines()[0]
        if not first.startswith(b"object "):
            raise RemediationError(f"malformed tag object in pseudoref graph: {oid}")
        _copy_object_graph(source, mirror, first.split(b" ", 1)[1].decode(), seen)
    elif kind != "blob":
        raise RemediationError(f"unsupported object in pseudoref graph: {kind}")
    copied = _git(
        mirror,
        "hash-object",
        "-t",
        kind,
        "-w",
        "--stdin",
        input_bytes=payload,
    ).decode().strip()
    if copied != oid:
        raise RemediationError(
            f"pseudoref object identity changed during local copy: {oid} -> {copied}"
        )
    seen.add(oid)


def _capture_pseudorefs(
    source: Path | SourceRepositoryAnchor | RepositoryLayout,
    mirror: Path,
) -> list[dict[str, str]]:
    roots = _pseudoref_roots(source)
    copied: set[str] = set()
    for row in roots:
        name = row["name"].lower().replace("_", "-")
        ref = f"refs/g012-captured/{name}-{row['ordinal']}"
        _copy_object_graph(source, mirror, row["oid"], copied)
        kind = _git(mirror, "cat-file", "-t", row["oid"]).decode().strip()
        captured_oid = row["oid"]
        if kind == "tree":
            env = _git_env()
            env.update(
                {
                    "GIT_AUTHOR_NAME": "G012 pseudoref capture",
                    "GIT_AUTHOR_EMAIL": "g012@invalid.local",
                    "GIT_COMMITTER_NAME": "G012 pseudoref capture",
                    "GIT_COMMITTER_EMAIL": "g012@invalid.local",
                    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
                    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
                }
            )
            captured_oid = _run(
                _git_argv(
                    mirror,
                    "commit-tree",
                    row["oid"],
                    "-m",
                    f"G012 synthetic capture for {row['name']}",
                ),
                env=env,
            ).decode().strip()
        elif kind not in {"commit", "tag"}:
            raise RemediationError(
                f"unsupported pseudoref object type for {row['name']}: {kind}"
            )
        _git(mirror, "update-ref", ref, captured_oid)
        row["captured_ref"] = ref
        row["captured_oid"] = captured_oid
        row["object_type"] = kind
    mirror_refs = {row["oid"] for row in _refs(mirror)}
    missing = sorted(
        {row["captured_oid"] for row in roots} - mirror_refs
    )
    if missing:
        raise RemediationError(f"pseudoref roots were not captured in mirror refs: {missing}")
    return roots


def _synchronize_hidden_source_refs(
    source: Path | SourceRepositoryAnchor | RepositoryLayout,
    mirror: Path,
    source_refs: list[dict[str, str]],
) -> None:
    actual = {row["ref"]: row for row in _refs(mirror)}
    expected = {row["ref"]: row for row in source_refs}
    extras = sorted(set(actual) - set(expected))
    if extras:
        raise RemediationError(
            f"initial mirror has refs absent from source snapshot: {extras}"
        )
    copied: set[str] = set()
    for row in source_refs:
        current = actual.get(row["ref"])
        if current is not None and current["oid"] == row["oid"]:
            continue
        _copy_object_graph(source, mirror, row["oid"], copied)
        _git(mirror, "update-ref", "--no-deref", row["ref"], row["oid"])
    _restore_symbolic_refs(mirror, source_refs, "synchronized local source refs")
    _require_exact_refs(source_refs, _refs(mirror), "synchronized local source refs")


def _assert_roots_accounted(repo: Path) -> None:
    ref_oids = {row["oid"] for row in _refs(repo)}
    for row in _pseudoref_roots(repo):
        if row["oid"] not in ref_oids:
            raise RemediationError(
                f"unaccounted reachable pseudoref root in {repo}: "
                f"{row['name']} {row['oid']}"
            )


def _validate_ref_roots(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
    refs: Iterable[dict[str, str]],
) -> None:
    for row in refs:
        pass_fds = _git_pass_fds(repo)
        completed = subprocess.run(
            _git_argv(repo, "rev-parse", "--verify", f"{row['ref']}^{{commit}}"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_git_env(),
            check=False,
            pass_fds=pass_fds,
        )
        if completed.returncode:
            raise RemediationError(
                f"unaccounted non-commit-ish ref root: {row['ref']} "
                f"({row['object_type']} {row['oid']})"
            )


def _source_stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        getattr(value, "st_blocks", -1),
    )


def _validate_streamed_regular_stat(
    value: os.stat_result,
    label: str,
    maximum_file_bytes: int,
) -> None:
    if not stat.S_ISREG(value.st_mode):
        raise RemediationError(f"source inventory entry is not regular: {label}")
    if value.st_size < 0 or value.st_size > maximum_file_bytes:
        raise RemediationError(
            f"source file exceeds the {maximum_file_bytes}-byte limit: {label}"
        )
    allocated_blocks = getattr(value, "st_blocks", None)
    if (
        allocated_blocks is None
        or not isinstance(allocated_blocks, int)
        or allocated_blocks < 0
    ):
        raise RemediationError(
            f"source file allocation metadata is unavailable or invalid: {label}"
        )


def _sparse_seek_constants() -> tuple[int, int] | None:
    seek_data = getattr(os, "SEEK_DATA", None)
    seek_hole = getattr(os, "SEEK_HOLE", None)
    if seek_data is None and seek_hole is None:
        return None
    if (
        not isinstance(seek_data, int)
        or isinstance(seek_data, bool)
        or seek_data < 0
        or not isinstance(seek_hole, int)
        or isinstance(seek_hole, bool)
        or seek_hole < 0
        or seek_data == seek_hole
    ):
        raise RemediationError(
            "sparse extent traversal constants are incomplete or invalid"
        )
    return seek_data, seek_hole


def _deterministic_extent_summary(
    descriptor: int,
    expected_stat: os.stat_result,
    label: str,
) -> SparseExtentSummary | None:
    constants = _sparse_seek_constants()
    records_digest = hashlib.sha256(b"g012-sparse-extents-v1\x00")
    if expected_stat.st_size == 0:
        return SparseExtentSummary(
            extent_count=0,
            data_bytes=0,
            traversal_operations=0,
            records_sha256=records_digest.hexdigest(),
            first_extents=(),
            last_extents=(),
        )
    if constants is None:
        return None
    seek_data, seek_hole = constants
    cursor = 0
    extent_count = 0
    traversal_operations = 0
    data_bytes = 0
    previous_end: int | None = None
    first_extents: list[tuple[int, int]] = []
    last_extents: list[tuple[int, int]] = []
    unsupported = {
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
        getattr(errno, "ENOSYS", errno.EINVAL),
    }

    def seek(offset: int, whence: int) -> int:
        nonlocal traversal_operations
        if traversal_operations >= MAX_SPARSE_TRAVERSAL_OPERATIONS:
            raise RemediationError(
                "sparse extent traversal-operation limit exceeded "
                f"({MAX_SPARSE_TRAVERSAL_OPERATIONS}): {label}"
            )
        traversal_operations += 1
        return os.lseek(descriptor, offset, whence)

    try:
        while cursor < expected_stat.st_size:
            try:
                data_start = seek(cursor, seek_data)
            except OSError as exc:
                if exc.errno == errno.ENXIO:
                    break
                if extent_count == 0 and cursor == 0 and exc.errno in unsupported:
                    return None
                raise RemediationError(
                    f"inconsistent SEEK_DATA semantics for {label}: {exc}"
                ) from exc
            if data_start < cursor or data_start >= expected_stat.st_size:
                raise RemediationError(
                    f"inconsistent SEEK_DATA offset for {label}: {data_start}"
                )
            if extent_count >= MAX_SPARSE_EXTENTS:
                raise RemediationError(
                    "sparse extent-count limit exceeded "
                    f"({MAX_SPARSE_EXTENTS}): {label}"
                )
            try:
                data_end = seek(data_start, seek_hole)
            except OSError as exc:
                raise RemediationError(
                    f"inconsistent SEEK_HOLE semantics for {label}: {exc}"
                ) from exc
            if (
                data_end <= data_start
                or data_end > expected_stat.st_size
                or (
                    previous_end is not None
                    and data_start <= previous_end
                )
            ):
                raise RemediationError(
                    f"inconsistent sparse extent for {label}: "
                    f"{data_start}-{data_end}"
                )
            extent = (data_start, data_end)
            extent_length = data_end - data_start
            records_digest.update(data_start.to_bytes(8, "big"))
            records_digest.update(extent_length.to_bytes(8, "big"))
            extent_count += 1
            data_bytes += extent_length
            if len(first_extents) < MAX_SPARSE_EXTENT_SAMPLES:
                first_extents.append(extent)
            if len(last_extents) == MAX_SPARSE_EXTENT_SAMPLES:
                del last_extents[0]
            last_extents.append(extent)
            previous_end = data_end
            cursor = data_end
    finally:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
        except OSError as exc:
            raise RemediationError(
                f"could not rewind source file after extent mapping: {label}"
            ) from exc
    if (
        expected_stat.st_blocks * 512 < expected_stat.st_size
        and data_bytes == expected_stat.st_size
    ):
        raise RemediationError(
            f"extent map contradicts sparse allocation metadata: {label}"
        )
    return SparseExtentSummary(
        extent_count=extent_count,
        data_bytes=data_bytes,
        traversal_operations=traversal_operations,
        records_sha256=records_digest.hexdigest(),
        first_extents=tuple(first_extents),
        last_extents=tuple(last_extents),
    )


def _hash_regular_descriptor_pass(
    descriptor: int,
    expected_size: int,
    label: str,
    maximum_file_bytes: int,
) -> tuple[int, str]:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as exc:
        raise RemediationError(f"source file cannot be rewound: {label}") from exc
    digest = hashlib.sha256()
    total = 0
    while True:
        try:
            chunk = os.read(descriptor, SOURCE_HASH_CHUNK_BYTES)
        except InterruptedError:
            continue
        if not chunk:
            break
        total += len(chunk)
        if total > expected_size or total > maximum_file_bytes:
            raise RemediationError(f"source file grew while being hashed: {label}")
        digest.update(chunk)
    if total != expected_size:
        raise RemediationError(f"source file changed while being hashed: {label}")
    return total, digest.hexdigest()


def _stream_hash_regular_descriptor(
    descriptor: int,
    expected_stat: os.stat_result,
    label: str,
    maximum_file_bytes: int = MAX_SOURCE_FILE_BYTES,
    *,
    check_extent_map: bool = True,
) -> tuple[int, str, SparseExtentSummary | None]:
    _validate_streamed_regular_stat(expected_stat, label, maximum_file_bytes)
    identity = _source_stat_identity(expected_stat)
    pre_extents = (
        _deterministic_extent_summary(descriptor, expected_stat, label)
        if check_extent_map
        else None
    )
    if _source_stat_identity(os.fstat(descriptor)) != identity:
        raise RemediationError(f"source file changed before first hash pass: {label}")
    first_size, first_digest = _hash_regular_descriptor_pass(
        descriptor,
        expected_stat.st_size,
        label,
        maximum_file_bytes,
    )
    mid_stat = os.fstat(descriptor)
    if _source_stat_identity(mid_stat) != identity:
        raise RemediationError(f"source file changed during first hash pass: {label}")
    mid_extents = (
        _deterministic_extent_summary(descriptor, mid_stat, label)
        if check_extent_map
        else None
    )
    if pre_extents != mid_extents:
        raise RemediationError(f"source sparse extent map changed: {label}")
    if _source_stat_identity(os.fstat(descriptor)) != identity:
        raise RemediationError(f"source file changed at the mid-hash check: {label}")
    second_size, second_digest = _hash_regular_descriptor_pass(
        descriptor,
        expected_stat.st_size,
        label,
        maximum_file_bytes,
    )
    post_stat = os.fstat(descriptor)
    if _source_stat_identity(post_stat) != identity:
        raise RemediationError(f"source file changed during second hash pass: {label}")
    post_extents = (
        _deterministic_extent_summary(descriptor, post_stat, label)
        if check_extent_map
        else None
    )
    if pre_extents != post_extents:
        raise RemediationError(f"source sparse extent map changed: {label}")
    if _source_stat_identity(os.fstat(descriptor)) != identity:
        raise RemediationError(f"source file changed at the post-hash check: {label}")
    if first_size != second_size or first_digest != second_digest:
        raise RemediationError(
            f"source file content differed between repeated hash passes: {label}"
        )
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as exc:
        raise RemediationError(f"source file cannot be finally rewound: {label}") from exc
    return first_size, first_digest, pre_extents


def _stream_hash_regular_path(
    path: Path,
    label: str,
    before: os.stat_result,
    maximum_file_bytes: int = MAX_SOURCE_FILE_BYTES,
) -> tuple[
    int,
    str,
    int,
    int,
    bool,
    SparseExtentSummary | None,
]:
    _validate_streamed_regular_stat(before, label, maximum_file_bytes)
    held = _open_secure_regular(
        path,
        label,
        expected_stat=before,
    )
    assert held is not None
    try:
        descriptor = held.descriptor
        opened = os.fstat(descriptor)
        if _source_stat_identity(before) != _source_stat_identity(opened):
            raise RemediationError(
                f"source file changed before streaming began: {label}"
            )
        held.revalidate(label)
        size, digest, extent_summary = _stream_hash_regular_descriptor(
            descriptor,
            opened,
            label,
            maximum_file_bytes,
        )
        held.revalidate(label)
        allocated_blocks = opened.st_blocks
        extent_data_bytes = (
            None if extent_summary is None else extent_summary.data_bytes
        )
        sparse = bool(
            size
            and (
                allocated_blocks * 512 < size
                or (
                    extent_data_bytes is not None
                    and extent_data_bytes < size
                )
            )
        )
        return (
            size,
            digest,
            stat.S_IMODE(opened.st_mode),
            allocated_blocks,
            sparse,
            extent_summary,
        )
    finally:
        held.close()


def _bounded_file_inventory(
    paths: Iterable[tuple[str, Path] | InventoryPath],
    *,
    maximum_file_bytes: int = MAX_SOURCE_FILE_BYTES,
    maximum_total_bytes: int = MAX_SOURCE_TOTAL_BYTES,
    budget: LogicalByteBudget | None = None,
) -> dict[str, Any]:
    active_budget = budget or LogicalByteBudget(maximum_total_bytes)
    rows: list[dict[str, Any]] = []
    total = 0
    for item in paths:
        if isinstance(item, InventoryPath):
            label = item.label
            path = item.path
            required = item.required
        else:
            label, path = item
            required = True
        if len(rows) >= MAX_SOURCE_FILES:
            raise RemediationError("source file inventory exceeds the file-count limit")
        before = _secure_lstat(
            path,
            label,
            required=required,
        )
        if before is None:
            continue
        if stat.S_ISLNK(before.st_mode):
            active_budget.consume(before.st_size, label)
            payload = _secure_readlink(path, label, before)
            kind = "symlink"
            size = len(payload)
            digest = _sha256_bytes(payload)
            mode = stat.S_IMODE(before.st_mode)
            allocated_blocks = None
            sparse = False
            extent_summary = None
        elif stat.S_ISREG(before.st_mode):
            active_budget.consume(before.st_size, label)
            (
                size,
                digest,
                mode,
                allocated_blocks,
                sparse,
                extent_summary,
            ) = _stream_hash_regular_path(
                path,
                label,
                before,
                maximum_file_bytes,
            )
            kind = "file"
        else:
            raise RemediationError(
                f"special source inventory entry is forbidden: {label}"
            )
        total += size
        rows.append(
            {
                "path": label,
                "kind": kind,
                "mode": mode,
                "size_bytes": size,
                "sha256": digest,
                "allocated_blocks": allocated_blocks,
                "sparse": sparse,
                "extent_summary": (
                    None
                    if extent_summary is None
                    else extent_summary.inventory()
                ),
            }
        )
    rows.sort(key=lambda row: row["path"])
    return {
        "count": len(rows),
        "total_bytes": total,
        "maximum_file_bytes": maximum_file_bytes,
        "maximum_total_bytes": active_budget.maximum_bytes,
        "global_budget_consumed_bytes_after_inventory": (
            active_budget.consumed_bytes
        ),
        "stream_chunk_bytes": SOURCE_HASH_CHUNK_BYTES,
        "maximum_sparse_extent_count": MAX_SPARSE_EXTENTS,
        "maximum_sparse_traversal_operations": (
            MAX_SPARSE_TRAVERSAL_OPERATIONS
        ),
        "maximum_sparse_extent_samples_per_side": MAX_SPARSE_EXTENT_SAMPLES,
        "sparse_files_allowed": True,
        "sparse_file_count": sum(
            row["kind"] == "file" and row["sparse"] for row in rows
        ),
        "entries": rows,
        "inventory_sha256": _sha256_bytes(_canonical_json(rows)),
    }


class DescriptorInventoryBuilder:
    def __init__(
        self,
        budget: LogicalByteBudget | None = None,
        path_aliases: dict[str, str] | None = None,
    ) -> None:
        self.budget = budget or LogicalByteBudget(MAX_SOURCE_TOTAL_BYTES)
        self.path_aliases = dict(path_aliases or {})
        self.rows: list[dict[str, Any]] = []
        self.total_bytes = 0
        self.entry_count = 0
        self.seen_labels: set[str] = set()

    def _label(self, prefix: str | None, relative: tuple[str, ...]) -> str:
        if relative:
            suffix = PurePosixPath(*relative).as_posix()
            label = suffix if prefix is None else f"{prefix}/{suffix}"
        else:
            label = "." if prefix is None else prefix
        return self.path_aliases.get(label, label)

    def _append_row(
        self,
        label: str,
        *,
        kind: str,
        mode: int,
        size: int,
        digest: str,
        allocated_blocks: int | None,
        sparse: bool,
        extent_summary: SparseExtentSummary | None,
    ) -> None:
        if label in self.seen_labels:
            raise RemediationError(
                f"duplicate descriptor inventory path: {label}"
            )
        if len(self.rows) >= MAX_SOURCE_FILES:
            raise RemediationError(
                "descriptor inventory exceeds the entry-count limit"
            )
        self.seen_labels.add(label)
        self.total_bytes += size
        self.rows.append(
            {
                "path": label,
                "kind": kind,
                "mode": mode,
                "size_bytes": size,
                "sha256": digest,
                "allocated_blocks": allocated_blocks,
                "sparse": sparse,
                "extent_summary": (
                    None
                    if extent_summary is None
                    else extent_summary.inventory()
                ),
            }
        )

    def _revalidate_leaf(
        self,
        root: HeldDirectoryRoot,
        edges: tuple[HeldDirectoryEdge, ...],
        parent_descriptor: int,
        name: str,
        descriptor: int,
        expected: os.stat_result,
        label: str,
    ) -> None:
        _revalidate_directory_chain(root, edges, label)
        try:
            entry_stat = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            descriptor_stat = os.fstat(descriptor)
        except OSError as exc:
            raise RemediationError(
                f"discovered inventory file disappeared: {label}"
            ) from exc
        identity = _source_stat_identity(expected)
        if (
            not stat.S_ISREG(entry_stat.st_mode)
            or not stat.S_ISREG(descriptor_stat.st_mode)
            or _source_stat_identity(entry_stat) != identity
            or _source_stat_identity(descriptor_stat) != identity
        ):
            raise RemediationError(
                f"inventory file topology changed: {label}"
            )
        _revalidate_directory_chain(root, edges, label)

    def _record_regular(
        self,
        root: HeldDirectoryRoot,
        edges: tuple[HeldDirectoryEdge, ...],
        parent_descriptor: int,
        name: str,
        entry_stat: os.stat_result,
        label: str,
    ) -> None:
        self.budget.consume(entry_stat.st_size, label)
        descriptor: int | None = None
        try:
            try:
                descriptor = os.open(
                    name,
                    os.O_RDONLY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=parent_descriptor,
                )
            except OSError as exc:
                raise RemediationError(
                    f"discovered inventory file failed O_NOFOLLOW open: {label}"
                ) from exc
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or _source_stat_identity(opened)
                != _source_stat_identity(entry_stat)
            ):
                raise RemediationError(
                    f"discovered inventory file changed before open: {label}"
                )
            self._revalidate_leaf(
                root,
                edges,
                parent_descriptor,
                name,
                descriptor,
                opened,
                label,
            )
            size, digest, extent_summary = _stream_hash_regular_descriptor(
                descriptor,
                opened,
                label,
                MAX_SOURCE_FILE_BYTES,
            )
            self._revalidate_leaf(
                root,
                edges,
                parent_descriptor,
                name,
                descriptor,
                opened,
                label,
            )
            allocated_blocks = opened.st_blocks
            extent_data_bytes = (
                None
                if extent_summary is None
                else extent_summary.data_bytes
            )
            sparse = bool(
                size
                and (
                    allocated_blocks * 512 < size
                    or (
                        extent_data_bytes is not None
                        and extent_data_bytes < size
                    )
                )
            )
            self._append_row(
                label,
                kind="file",
                mode=stat.S_IMODE(opened.st_mode),
                size=size,
                digest=digest,
                allocated_blocks=allocated_blocks,
                sparse=sparse,
                extent_summary=extent_summary,
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _record_symlink(
        self,
        root: HeldDirectoryRoot,
        edges: tuple[HeldDirectoryEdge, ...],
        parent_descriptor: int,
        name: str,
        entry_stat: os.stat_result,
        label: str,
    ) -> None:
        self.budget.consume(entry_stat.st_size, label)
        identity = _source_stat_identity(entry_stat)
        _revalidate_directory_chain(root, edges, label)
        try:
            first_target = os.readlink(name, dir_fd=parent_descriptor)
            middle = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            second_target = os.readlink(name, dir_fd=parent_descriptor)
            after = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise RemediationError(
                f"discovered inventory symlink disappeared: {label}"
            ) from exc
        _revalidate_directory_chain(root, edges, label)
        if (
            not stat.S_ISLNK(middle.st_mode)
            or not stat.S_ISLNK(after.st_mode)
            or _source_stat_identity(middle) != identity
            or _source_stat_identity(after) != identity
            or first_target != second_target
        ):
            raise RemediationError(
                f"inventory symlink topology changed: {label}"
            )
        payload = first_target.encode("utf-8", "surrogateescape")
        if len(payload) != entry_stat.st_size:
            raise RemediationError(f"inventory symlink size changed: {label}")
        self._append_row(
            label,
            kind="symlink",
            mode=stat.S_IMODE(entry_stat.st_mode),
            size=len(payload),
            digest=_sha256_bytes(payload),
            allocated_blocks=None,
            sparse=False,
            extent_summary=None,
        )

    def _walk(
        self,
        root: HeldDirectoryRoot,
        directory_descriptor: int,
        directory_identity: tuple[int, ...],
        edges: tuple[HeldDirectoryEdge, ...],
        relative: tuple[str, ...],
        prefix: str | None,
        skip_relative: frozenset[tuple[str, ...]],
        skip_directory_relative: frozenset[tuple[str, ...]],
    ) -> None:
        directory_label = self._label(prefix, relative)
        _revalidate_directory_chain(root, edges, directory_label)
        if _source_stat_identity(os.fstat(directory_descriptor)) != directory_identity:
            raise RemediationError(
                f"directory changed before descriptor enumeration: {directory_label}"
            )
        try:
            names = sorted(os.listdir(directory_descriptor))
        except (OSError, TypeError) as exc:
            raise RemediationError(
                f"descriptor-relative directory enumeration failed: {directory_label}"
            ) from exc
        if len(names) > MAX_SOURCE_FILES:
            raise RemediationError(
                f"directory entry count exceeds limit: {directory_label}"
            )
        if len(names) != len(set(names)) or any(
            not isinstance(name, str)
            or name in {"", ".", ".."}
            or "/" in name
            or "\x00" in name
            for name in names
        ):
            raise RemediationError(
                f"invalid descriptor directory entry: {directory_label}"
            )
        _revalidate_directory_chain(root, edges, directory_label)
        for name in names:
            child_relative = (*relative, name)
            if child_relative in skip_relative:
                continue
            self.entry_count += 1
            if self.entry_count > MAX_SOURCE_FILES:
                raise RemediationError(
                    "descriptor inventory exceeds the entry-count limit"
                )
            child_label = self._label(prefix, child_relative)
            try:
                entry_stat = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise RemediationError(
                    f"discovered directory entry disappeared: {child_label}"
                ) from exc
            if stat.S_ISDIR(entry_stat.st_mode):
                if child_relative in skip_directory_relative:
                    continue
                child_descriptor: int | None = None
                try:
                    try:
                        child_descriptor = os.open(
                            name,
                            os.O_RDONLY
                            | os.O_DIRECTORY
                            | os.O_NOFOLLOW
                            | getattr(os, "O_CLOEXEC", 0),
                            dir_fd=directory_descriptor,
                        )
                    except OSError as exc:
                        raise RemediationError(
                            f"child directory failed O_DIRECTORY|O_NOFOLLOW open: "
                            f"{child_label}"
                        ) from exc
                    opened = os.fstat(child_descriptor)
                    identity = _source_stat_identity(opened)
                    if (
                        not stat.S_ISDIR(opened.st_mode)
                        or identity != _source_stat_identity(entry_stat)
                    ):
                        raise RemediationError(
                            f"child directory changed before open: {child_label}"
                        )
                    edge = HeldDirectoryEdge(
                        parent_descriptor=directory_descriptor,
                        name=name,
                        descriptor=child_descriptor,
                        identity=identity,
                    )
                    child_edges = (*edges, edge)
                    _revalidate_directory_chain(root, child_edges, child_label)
                    self._append_row(
                        child_label,
                        kind="directory",
                        mode=stat.S_IMODE(opened.st_mode),
                        size=0,
                        digest=_sha256_bytes(b""),
                        allocated_blocks=None,
                        sparse=False,
                        extent_summary=None,
                    )
                    self._walk(
                        root,
                        child_descriptor,
                        identity,
                        child_edges,
                        child_relative,
                        prefix,
                        skip_relative,
                        skip_directory_relative,
                    )
                    _revalidate_directory_chain(root, child_edges, child_label)
                finally:
                    if child_descriptor is not None:
                        os.close(child_descriptor)
            elif stat.S_ISREG(entry_stat.st_mode):
                self._record_regular(
                    root,
                    edges,
                    directory_descriptor,
                    name,
                    entry_stat,
                    child_label,
                )
            elif stat.S_ISLNK(entry_stat.st_mode):
                self._record_symlink(
                    root,
                    edges,
                    directory_descriptor,
                    name,
                    entry_stat,
                    child_label,
                )
            else:
                if prefix is None:
                    detail = "special source inventory entry is forbidden"
                else:
                    family = prefix.split(":", 1)[0]
                    detail = f"special Git {family} entry is forbidden"
                raise RemediationError(f"{detail}: {child_label}")
        try:
            final_names = sorted(os.listdir(directory_descriptor))
        except (OSError, TypeError) as exc:
            raise RemediationError(
                f"descriptor directory final enumeration failed: {directory_label}"
            ) from exc
        if names != final_names:
            raise RemediationError(
                f"directory entries changed during inventory: {directory_label}"
            )
        if _source_stat_identity(os.fstat(directory_descriptor)) != directory_identity:
            raise RemediationError(
                f"directory metadata changed during inventory: {directory_label}"
            )
        _revalidate_directory_chain(root, edges, directory_label)

    def add_root(
        self,
        path: Path,
        prefix: str | None,
        *,
        required: bool = True,
        skip_relative: Iterable[tuple[str, ...]] = (),
        skip_directory_relative: Iterable[tuple[str, ...]] = (),
    ) -> bool:
        held = _open_held_directory_root(
            path,
            prefix or "worktree",
            required=required,
        )
        if held is None:
            return False
        try:
            return self.add_held_root(
                held,
                prefix,
                skip_relative=skip_relative,
                skip_directory_relative=skip_directory_relative,
            )
        finally:
            held.close()

    def add_held_root(
        self,
        held: HeldDirectoryRoot,
        prefix: str | None,
        *,
        skip_relative: Iterable[tuple[str, ...]] = (),
        skip_directory_relative: Iterable[tuple[str, ...]] = (),
    ) -> bool:
        root_stat = os.fstat(held.descriptor)
        self._append_row(
            self._label(prefix, ()),
            kind="directory",
            mode=stat.S_IMODE(root_stat.st_mode),
            size=0,
            digest=_sha256_bytes(b""),
            allocated_blocks=None,
            sparse=False,
            extent_summary=None,
        )
        self._walk(
            held,
            held.descriptor,
            held.identity,
            (),
            (),
            prefix,
            frozenset(skip_relative),
            frozenset(skip_directory_relative),
        )
        held.revalidate(prefix or "worktree")
        return True

    def result(self) -> dict[str, Any]:
        rows = sorted(self.rows, key=lambda row: row["path"])
        return {
            "count": len(rows),
            "directory_count": sum(
                row["kind"] == "directory" for row in rows
            ),
            "total_bytes": self.total_bytes,
            "maximum_file_bytes": MAX_SOURCE_FILE_BYTES,
            "maximum_total_bytes": self.budget.maximum_bytes,
            "global_budget_consumed_bytes_after_inventory": (
                self.budget.consumed_bytes
            ),
            "stream_chunk_bytes": SOURCE_HASH_CHUNK_BYTES,
            "maximum_sparse_extent_count": MAX_SPARSE_EXTENTS,
            "maximum_sparse_traversal_operations": (
                MAX_SPARSE_TRAVERSAL_OPERATIONS
            ),
            "maximum_sparse_extent_samples_per_side": (
                MAX_SPARSE_EXTENT_SAMPLES
            ),
            "sparse_files_allowed": True,
            "sparse_file_count": sum(
                row["kind"] == "file" and row["sparse"] for row in rows
            ),
            "entries": rows,
            "inventory_sha256": _sha256_bytes(_canonical_json(rows)),
        }


def _worktree_inventory(
    source: Path | RepositoryLayout,
    budget: LogicalByteBudget | None = None,
) -> dict[str, Any]:
    builder = DescriptorInventoryBuilder(
        budget,
        path_aliases={".git": "worktree-git-admin-pointer"},
    )
    if isinstance(source, RepositoryLayout):
        builder.add_held_root(
            source.source_anchor.held,
            None,
            skip_directory_relative={(".git",)},
        )
    else:
        builder.add_root(
            source,
            None,
            skip_directory_relative={(".git",)},
        )
    return builder.result()


def _directory_inventory(
    root: Path,
    label: str,
    budget: LogicalByteBudget | None = None,
    *,
    required_root: bool = True,
    skip_relative: Iterable[tuple[str, ...]] = (),
) -> dict[str, Any]:
    builder = DescriptorInventoryBuilder(budget)
    builder.add_root(
        root,
        label,
        required=required_root,
        skip_relative=skip_relative,
    )
    return builder.result()


def _descriptor_tree_listing(
    root_path: Path,
    label: str,
    *,
    excluded_root_names: frozenset[str] = frozenset(),
    reject_symlinks: bool,
    symlink_error: str = "internal symlink is forbidden",
) -> list[dict[str, str]]:
    held = _open_held_directory_root(root_path, label, required=True)
    assert held is not None
    rows: list[dict[str, str]] = []
    entry_count = 0

    def walk(
        descriptor: int,
        identity: tuple[int, ...],
        edges: tuple[HeldDirectoryEdge, ...],
        relative: tuple[str, ...],
    ) -> None:
        nonlocal entry_count
        display = PurePosixPath(*relative).as_posix() if relative else "."
        _revalidate_directory_chain(held, edges, f"{label}/{display}")
        if _source_stat_identity(os.fstat(descriptor)) != identity:
            raise RemediationError(
                f"listed directory changed before enumeration: {label}/{display}"
            )
        try:
            names = sorted(os.listdir(descriptor))
        except (OSError, TypeError) as exc:
            raise RemediationError(
                f"descriptor listing failed: {label}/{display}"
            ) from exc
        if len(names) != len(set(names)) or any(
            not isinstance(name, str)
            or name in {"", ".", ".."}
            or "/" in name
            or "\x00" in name
            for name in names
        ):
            raise RemediationError(
                f"invalid descriptor listing entry: {label}/{display}"
            )
        _revalidate_directory_chain(held, edges, f"{label}/{display}")
        for name in names:
            if not relative and name in excluded_root_names:
                continue
            entry_count += 1
            if entry_count > MAX_SOURCE_FILES:
                raise RemediationError(
                    f"descriptor listing exceeds entry limit: {label}"
                )
            child_relative = (*relative, name)
            child_display = PurePosixPath(*child_relative).as_posix()
            try:
                entry_stat = os.stat(
                    name,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise RemediationError(
                    f"listed entry disappeared: {label}/{child_display}"
                ) from exc
            if stat.S_ISDIR(entry_stat.st_mode):
                child_descriptor: int | None = None
                try:
                    child_descriptor = os.open(
                        name,
                        os.O_RDONLY
                        | os.O_DIRECTORY
                        | os.O_NOFOLLOW
                        | getattr(os, "O_CLOEXEC", 0),
                        dir_fd=descriptor,
                    )
                    opened = os.fstat(child_descriptor)
                    child_identity = _source_stat_identity(opened)
                    if (
                        not stat.S_ISDIR(opened.st_mode)
                        or child_identity != _source_stat_identity(entry_stat)
                    ):
                        raise RemediationError(
                            f"listed directory changed before open: "
                            f"{label}/{child_display}"
                        )
                    edge = HeldDirectoryEdge(
                        parent_descriptor=descriptor,
                        name=name,
                        descriptor=child_descriptor,
                        identity=child_identity,
                    )
                    child_edges = (*edges, edge)
                    rows.append({"path": child_display, "kind": "directory"})
                    walk(
                        child_descriptor,
                        child_identity,
                        child_edges,
                        child_relative,
                    )
                    _revalidate_directory_chain(
                        held,
                        child_edges,
                        f"{label}/{child_display}",
                    )
                finally:
                    if child_descriptor is not None:
                        os.close(child_descriptor)
            elif stat.S_ISREG(entry_stat.st_mode):
                rows.append({"path": child_display, "kind": "file"})
            elif stat.S_ISLNK(entry_stat.st_mode):
                if reject_symlinks:
                    raise RemediationError(
                        f"{symlink_error}: {label}/{child_display}"
                    )
                rows.append({"path": child_display, "kind": "symlink"})
            else:
                raise RemediationError(
                    f"special listing entry is forbidden: {label}/{child_display}"
                )
        try:
            final_names = sorted(os.listdir(descriptor))
        except (OSError, TypeError) as exc:
            raise RemediationError(
                f"descriptor final listing failed: {label}/{display}"
            ) from exc
        if names != final_names:
            raise RemediationError(
                f"directory changed during descriptor listing: {label}/{display}"
            )
        if _source_stat_identity(os.fstat(descriptor)) != identity:
            raise RemediationError(
                f"directory metadata changed during listing: {label}/{display}"
            )
        _revalidate_directory_chain(held, edges, f"{label}/{display}")

    try:
        walk(held.descriptor, held.identity, (), ())
        held.revalidate(label)
        return sorted(rows, key=lambda row: row["path"])
    finally:
        held.close()


def _git_admin_state_inventory(
    layout: RepositoryLayout,
    budget: LogicalByteBudget | None = None,
) -> dict[str, Any]:
    builder = DescriptorInventoryBuilder(budget)
    separated_directories = {
        ("objects",),
        ("refs",),
        ("logs",),
        ("hooks",),
    }
    git_specific_files = {
        ("HEAD",),
        ("index",),
        ("config.worktree",),
    }
    common_specific_files = {
        ("config",),
        ("packed-refs",),
        ("shallow",),
        ("info", "grafts"),
    }
    if layout.git_dir == layout.common_dir:
        builder.add_root(
            layout.git_dir,
            "git-dir",
            skip_relative={
                *separated_directories,
                *git_specific_files,
                *common_specific_files,
            },
        )
    else:
        builder.add_root(
            layout.git_dir,
            "git-dir",
            skip_relative={
                *separated_directories,
                *git_specific_files,
            },
        )
        common_skips = {
            *separated_directories,
            *common_specific_files,
        }
        try:
            current_worktree_relative = layout.git_dir.relative_to(
                layout.common_dir
            )
        except ValueError:
            current_worktree_relative = None
        if (
            current_worktree_relative is not None
            and current_worktree_relative.parts
        ):
            common_skips.add(tuple(current_worktree_relative.parts))
        builder.add_root(
            layout.common_dir,
            "common-dir",
            skip_relative=common_skips,
        )
    return builder.result()


def _all_object_metadata_rows(
    source: Path | SourceRepositoryAnchor | RepositoryLayout,
) -> list[dict[str, Any]]:
    payload = _git(
        source,
        "cat-file",
        "--batch-all-objects",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
    )
    raw_rows = payload.splitlines()
    if len(raw_rows) > MAX_TREE_ENTRIES:
        raise RemediationError("source object inventory exceeds the object-count limit")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_row in raw_rows:
        fields = raw_row.decode("ascii", "strict").split(" ")
        if (
            len(fields) != 3
            or not OID_RE.fullmatch(fields[0])
            or fields[0] in seen
            or fields[1] not in {"blob", "commit", "tag", "tree"}
            or not fields[2].isdigit()
        ):
            raise RemediationError("Git returned a malformed object inventory record")
        seen.add(fields[0])
        rows.append(
            {
                "oid": fields[0],
                "object_type": fields[1],
                "size_bytes": int(fields[2]),
            }
        )
    return sorted(rows, key=lambda row: row["oid"])


def _object_inventory(
    source: Path | SourceRepositoryAnchor | RepositoryLayout,
) -> dict[str, Any]:
    rows = _all_object_metadata_rows(source)
    return {
        "count": len(rows),
        "inventory_sha256": _sha256_bytes(_canonical_json(rows)),
    }


def _logical_object_inventory(
    repo: Path,
    refs: Iterable[dict[str, str]],
) -> dict[str, Any]:
    ref_names = sorted({row["ref"] for row in refs})
    if ref_names:
        payload = _git(
            repo,
            "rev-list",
            "--objects",
            "--no-object-names",
            "--stdin",
            input_bytes=("".join(f"{ref}\n" for ref in ref_names)).encode("utf-8"),
        )
        oids = sorted(
            {
                line.decode("ascii", "strict")
                for line in payload.splitlines()
                if line
            }
        )
    else:
        oids = []
    if len(oids) > MAX_TREE_ENTRIES or any(not OID_RE.fullmatch(oid) for oid in oids):
        raise RemediationError("Git returned an invalid logical object traversal")
    physical = {row["oid"]: row for row in _all_object_metadata_rows(repo)}
    rows: list[dict[str, Any]] = []
    total = 0
    for oid in oids:
        metadata = physical.get(oid)
        if metadata is None:
            raise RemediationError(f"reachable Git object is physically absent: {oid}")
        maximum = min(MAX_BLOB_BYTES, MAX_LOGICAL_OBJECT_TOTAL_BYTES - total)
        payload = _git(
            repo,
            "cat-file",
            metadata["object_type"],
            oid,
            maximum_output=maximum + 1,
        )
        if len(payload) != metadata["size_bytes"]:
            raise RemediationError(f"Git object size changed while inventoried: {oid}")
        total += len(payload)
        if total > MAX_LOGICAL_OBJECT_TOTAL_BYTES:
            raise RemediationError(
                "logical object content exceeds the total byte limit"
            )
        rows.append(
            {
                **metadata,
                "content_sha256": _sha256_bytes(payload),
            }
        )
    return {
        "object_count": len(rows),
        "total_content_bytes": total,
        "objects": rows,
        "inventory_sha256": _sha256_bytes(_canonical_json(rows)),
    }


def _require_exact_logical_inventory(
    expected: dict[str, Any],
    actual: dict[str, Any],
    label: str,
) -> None:
    if expected != actual:
        expected_oids = {row["oid"] for row in expected.get("objects", [])}
        actual_oids = {row["oid"] for row in actual.get("objects", [])}
        raise RemediationError(
            f"{label} logical object inventory mismatch: "
            f"missing={sorted(expected_oids - actual_oids)}, "
            f"extra={sorted(actual_oids - expected_oids)}"
        )


def _validate_logical_object_inventory(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "object_count",
        "total_content_bytes",
        "objects",
        "inventory_sha256",
    }:
        raise RemediationError(f"invalid logical object inventory shape: {label}")
    rows = value["objects"]
    if not isinstance(rows, list) or len(rows) > MAX_TREE_ENTRIES:
        raise RemediationError(f"invalid logical object rows: {label}")
    seen: set[str] = set()
    total = 0
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row)
            != {"oid", "object_type", "size_bytes", "content_sha256"}
            or not isinstance(row["oid"], str)
            or not OID_RE.fullmatch(row["oid"])
            or row["oid"] in seen
            or row["object_type"] not in {"blob", "commit", "tag", "tree"}
            or not isinstance(row["size_bytes"], int)
            or isinstance(row["size_bytes"], bool)
            or row["size_bytes"] < 0
            or not isinstance(row["content_sha256"], str)
            or not SHA256_RE.fullmatch(row["content_sha256"])
        ):
            raise RemediationError(f"invalid logical object record: {label}")
        seen.add(row["oid"])
        total += row["size_bytes"]
    if (
        rows != sorted(rows, key=lambda row: row["oid"])
        or value["object_count"] != len(rows)
        or value["total_content_bytes"] != total
        or value["inventory_sha256"] != _sha256_bytes(_canonical_json(rows))
    ):
        raise RemediationError(f"inconsistent logical object inventory: {label}")
    return value


def _validate_cleaned_object_inventory(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "publishable", "evidence", "combined"}
        or value.get("schema") != "g012-cleaned-logical-object-inventory/v1"
    ):
        raise RemediationError("invalid cleaned logical object inventory schema")
    for scope in ("publishable", "evidence", "combined"):
        _validate_logical_object_inventory(value[scope], scope)
    union = {
        row["oid"]: row
        for row in [
            *value["publishable"]["objects"],
            *value["evidence"]["objects"],
        ]
    }
    combined = {row["oid"]: row for row in value["combined"]["objects"]}
    if union != combined:
        raise RemediationError(
            "cleaned publishable/evidence inventories do not form the combined set"
        )
    return value


def _require_physical_objects_match_logical(
    repo: Path,
    expected: dict[str, Any],
    label: str,
) -> None:
    expected_rows = {
        row["oid"]: {
            "oid": row["oid"],
            "object_type": row["object_type"],
            "size_bytes": row["size_bytes"],
        }
        for row in expected["objects"]
    }
    actual_rows = {row["oid"]: row for row in _all_object_metadata_rows(repo)}
    if expected_rows != actual_rows:
        raise RemediationError(
            f"{label} extra/missing physical Git objects: "
            f"missing={sorted(set(expected_rows) - set(actual_rows))}, "
            f"extra={sorted(set(actual_rows) - set(expected_rows))}"
        )


def _establish_cleaned_object_inventory(
    repo: Path,
    publishable_refs: list[dict[str, str]],
    evidence_refs: list[dict[str, str]],
) -> dict[str, Any]:
    publishable = _logical_object_inventory(repo, publishable_refs)
    evidence = _logical_object_inventory(repo, evidence_refs)
    combined_refs = sorted(
        [*publishable_refs, *evidence_refs], key=lambda row: row["ref"]
    )
    combined = _logical_object_inventory(repo, combined_refs)
    union = {
        row["oid"]: row
        for row in [*publishable["objects"], *evidence["objects"]]
    }
    combined_rows = {row["oid"]: row for row in combined["objects"]}
    if union != combined_rows:
        raise RemediationError(
            "publishable/evidence logical object scopes do not form the cleaned set"
        )
    _require_physical_objects_match_logical(
        repo, combined, "pre-sealing cleaned mirror"
    )
    return _validate_cleaned_object_inventory({
        "schema": "g012-cleaned-logical-object-inventory/v1",
        "publishable": publishable,
        "evidence": evidence,
        "combined": combined,
    })


def _verify_cleaned_object_scope(
    repo: Path,
    refs: list[dict[str, str]],
    expected: dict[str, Any],
    label: str,
) -> None:
    actual = _logical_object_inventory(repo, refs)
    _require_exact_logical_inventory(expected, actual, label)
    _require_physical_objects_match_logical(repo, expected, label)


def _source_fsck(
    source: Path | SourceRepositoryAnchor | RepositoryLayout,
) -> dict[str, Any]:
    pass_fds = _git_pass_fds(source)
    completed = subprocess.run(
        _git_argv(source, "fsck", "--full", "--strict"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_git_env(),
        check=False,
        pass_fds=pass_fds,
    )
    if len(completed.stdout) + len(completed.stderr) > MAX_CAPTURE_BYTES:
        raise RemediationError("source git fsck output exceeded the capture limit")
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).decode("utf-8", "replace")
        raise RemediationError(f"source git fsck --full --strict failed: {detail.strip()}")
    return {
        "returncode": completed.returncode,
        "stdout_sha256": _sha256_bytes(completed.stdout),
        "stderr_sha256": _sha256_bytes(completed.stderr),
    }


def _source_state(
    layout: RepositoryLayout,
    maximum_total_bytes: int = MAX_SOURCE_TOTAL_BYTES,
) -> dict[str, Any]:
    layout.revalidate("source-state snapshot start")
    _reject_sibling_linked_worktrees(layout)
    source = layout
    git_dir = layout.git_dir
    budget = LogicalByteBudget(maximum_total_bytes)
    _reject_unknown_object_bearing_admin_files(layout, budget)
    bare = False
    head = _git(source, "rev-parse", "--verify", "HEAD").decode().strip()
    symbolic_pass_fds = _git_pass_fds(source)
    symbolic = subprocess.run(
        _git_argv(source, "symbolic-ref", "-q", "HEAD"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_git_env(),
        check=False,
        pass_fds=symbolic_pass_fds,
    )
    if len(symbolic.stdout) > MAX_CAPTURE_BYTES:
        raise RemediationError("symbolic HEAD capture exceeded limit")
    config = _git(
        source,
        "config",
        "--local",
        "--null",
        "--list",
        "--show-origin",
    )
    index = git_dir / "index"
    index_hash = None
    index_inventory = _bounded_file_inventory(
        [InventoryPath("git-index", index, required=False)],
        budget=budget,
    )
    if index_inventory["entries"]:
        index_hash = index_inventory["entries"][0]["sha256"]
    alternate_rows = []
    for path in layout.alternate_files:
        inventory = _bounded_file_inventory(
            [(f"alternates:{path}", path)],
            budget=budget,
        )
        if len(inventory["entries"]) != 1:
            raise RemediationError(f"Git alternates file disappeared: {path}")
        entry = inventory["entries"][0]
        alternate_rows.append(
            {
                "path": str(path),
                "sha256": entry["sha256"],
                "size_bytes": entry["size_bytes"],
                "allocated_blocks": entry["allocated_blocks"],
                "sparse": entry["sparse"],
                "extent_summary": entry["extent_summary"],
            }
        )
    raw_object_storage = [
        {
            "path": str(path),
            **_directory_inventory(
                path,
                f"objects:{path}",
                budget,
                skip_relative={("info", "alternates")},
            ),
        }
        for path in layout.object_dirs
    ]
    metadata_paths = [
        InventoryPath("git-config", layout.common_dir / "config"),
        InventoryPath(
            "worktree-config",
            layout.git_dir / "config.worktree",
            required=False,
        ),
        InventoryPath(
            "packed-refs",
            layout.common_dir / "packed-refs",
            required=False,
        ),
        InventoryPath("shallow", layout.common_dir / "shallow", required=False),
        InventoryPath(
            "grafts",
            layout.common_dir / "info" / "grafts",
            required=False,
        ),
        InventoryPath("worktree-head", layout.git_dir / "HEAD"),
    ]
    common_ref_inventory = _directory_inventory(
        layout.common_dir / "refs",
        "refs",
        budget,
        required_root=False,
    )
    common_reflog_inventory = _directory_inventory(
        layout.common_dir / "logs",
        "logs",
        budget,
        required_root=False,
    )
    common_hook_inventory = _directory_inventory(
        layout.common_dir / "hooks",
        "hooks",
        budget,
        required_root=False,
    )
    worktree_ref_inventory = None
    worktree_reflog_inventory = None
    worktree_hook_inventory = None
    if layout.git_dir != layout.common_dir:
        worktree_ref_inventory = _directory_inventory(
            layout.git_dir / "refs",
            "worktree-refs",
            budget,
            required_root=False,
        )
        worktree_reflog_inventory = _directory_inventory(
            layout.git_dir / "logs",
            "worktree-logs",
            budget,
            required_root=False,
        )
        worktree_hook_inventory = _directory_inventory(
            layout.git_dir / "hooks",
            "worktree-hooks",
            budget,
            required_root=False,
        )
    state = {
        "bare": bare,
        "config_sha256": _sha256_bytes(config),
        "head_oid": head,
        "head_symbolic_ref": symbolic.stdout.decode("utf-8", "replace").strip() or None,
        "index_sha256": index_hash,
        "refs": _refs(source),
        "status_command_executed": False,
        "status_command_reason": (
            "Git status is intentionally not invoked because source-local "
            "attributes/filters can execute; direct tracked/untracked content "
            "inventory is authoritative."
        ),
        "worktree_content_inventory": _worktree_inventory(layout, budget),
        "object_inventory": _object_inventory(source),
        "raw_object_storage": raw_object_storage,
        "git_metadata_inventory": _bounded_file_inventory(
            metadata_paths, budget=budget
        ),
        "git_admin_state_inventory": _git_admin_state_inventory(layout, budget),
        "ref_storage_inventory": common_ref_inventory,
        "worktree_ref_storage_inventory": worktree_ref_inventory,
        "source_fsck": _source_fsck(source),
        "reflog_inventory": common_reflog_inventory,
        "worktree_reflog_inventory": worktree_reflog_inventory,
        "hook_inventory": common_hook_inventory,
        "worktree_hook_inventory": worktree_hook_inventory,
        "alternates": alternate_rows,
        "repository_layout": {
            "source": str(layout.source),
            "source_access": "held-no-symlink-directory-fd-via-proc-self-fd",
            "source_anchor_identity": list(layout.source_anchor.held.identity),
            "source_git_subprocess_fd_inheritance": True,
            "external_git_administration_supported": False,
            "external_alternate_object_stores_supported": False,
            "git_dir": str(layout.git_dir),
            "common_dir": str(layout.common_dir),
            "object_dirs": [str(path) for path in layout.object_dirs],
            "alternate_files": [str(path) for path in layout.alternate_files],
            "admin_paths": [str(path) for path in layout.admin_paths],
        },
        "logical_byte_budget": budget.snapshot(),
    }
    layout.revalidate("source-state snapshot end")
    state["guard_sha256"] = _sha256_bytes(_canonical_json(state))
    return state


def _literal_assignment(tree: ast.AST, name: str) -> Any:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                value = node.value
                if value is None:
                    break
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "compile"
                    and value.args
                ):
                    value = value.args[0]
                return ast.literal_eval(value)
    raise RemediationError(f"canonical authority lacks {name}")


def _safe_repo_path(raw: str) -> str | None:
    if not raw or "\\" in raw or "\x00" in raw:
        return None
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix() if path.as_posix() == raw else None


def _derive_policy(source: Path | RepositoryLayout) -> dict[str, Any]:
    rels = (
        OFFICIAL_JSON_REL,
        OFFICIAL_TSV_REL,
        G007_EXPORT_REL,
        CLEAN_ROOM_POLICY_REL,
        AUTHORIZATION_SCOPE_REL,
        G007_VALIDATOR_REL,
    )
    payloads: dict[str, bytes] = {}
    for rel in rels:
        if isinstance(source, RepositoryLayout):
            payload = _read_regular_from_source_anchor(
                source.source_anchor,
                rel,
                rel.as_posix(),
            )
        else:
            payload = _read_regular(source / rel, rel.as_posix())
        assert payload is not None
        payloads[rel.as_posix()] = payload
    official = _load_json_bytes(
        payloads[OFFICIAL_JSON_REL.as_posix()], OFFICIAL_JSON_REL.as_posix()
    )
    artifacts = official.get("artifacts") if isinstance(official, dict) else None
    if not isinstance(artifacts, list) or not artifacts:
        raise RemediationError("official-artifacts.json has no artifacts")
    observed = official.get("observed_counts_by_kind")
    expected = official.get("expected_counts")
    if not isinstance(observed, dict) or not observed:
        raise RemediationError("official-artifacts.json lacks observed_counts_by_kind")
    if not isinstance(expected, dict) or not expected:
        raise RemediationError("official-artifacts.json lacks expected_counts")
    if any(
        not isinstance(key, str)
        or not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        for key, value in {**observed, **expected}.items()
    ):
        raise RemediationError("official artifact count authorities are malformed")
    hashes: set[str] = set()
    artifact_ids: set[str] = set()
    kind_counts: dict[str, int] = {}
    hash_rows: dict[str, list[tuple[str, str, int]]] = {}
    for row in artifacts:
        if not isinstance(row, dict):
            raise RemediationError("official-artifacts.json contains a non-object artifact")
        artifact_id = row.get("artifact_id")
        digest = row.get("sha256")
        kind = row.get("kind")
        size = row.get("size_bytes")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise RemediationError("official artifact has an invalid artifact_id")
        if artifact_id in artifact_ids:
            raise RemediationError(f"duplicate official artifact_id: {artifact_id}")
        artifact_ids.add(artifact_id)
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise RemediationError("official-artifacts.json contains a malformed SHA256")
        if not isinstance(kind, str) or not kind:
            raise RemediationError(f"official artifact {artifact_id} has an invalid kind")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise RemediationError(f"official artifact {artifact_id} has an invalid size")
        hashes.add(digest)
        hash_rows.setdefault(digest, []).append((artifact_id, kind, size))
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    for digest, aliases in hash_rows.items():
        if len(aliases) == 1:
            continue
        kinds = {row[1] for row in aliases}
        sizes = {row[2] for row in aliases}
        if len(aliases) != 2 or kinds != {"apk_member", "extracted_apk"} or len(sizes) != 1:
            raise RemediationError(
                f"duplicate official artifact SHA256 is not the canonical "
                f"container/extracted alias: {digest}"
            )
    if kind_counts != observed:
        raise RemediationError(
            "observed_counts_by_kind does not exactly match artifact rows"
        )
    expected_to_kind = {
        "apk_members": "apk_member",
        "arm64_native_libraries_in_extracted_base": "native_library",
        "dex_files_in_extracted_base": "dex",
        "known_official_fixtures": "official_fixture",
    }
    if set(expected) != set(expected_to_kind):
        raise RemediationError("expected_counts has unexpected or missing count kinds")
    for expected_key, kind in expected_to_kind.items():
        if expected[expected_key] != kind_counts.get(kind, 0):
            raise RemediationError(
                f"expected count {expected_key} does not match kind {kind}"
            )

    exact_paths: set[str] = set()
    try:
        tsv_lines = payloads[OFFICIAL_TSV_REL.as_posix()].decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise RemediationError("official artifact TSV is not UTF-8") from exc
    tsv_rows = 0
    tsv_hashes: set[str] = set()
    for number, line in enumerate(tsv_lines, 1):
        if not line or line.startswith("#"):
            continue
        columns = line.split("\t")
        if len(columns) != 4 or not SHA256_RE.fullmatch(columns[0]):
            raise RemediationError(f"malformed official artifact TSV row {number}")
        if columns[0] in tsv_hashes:
            raise RemediationError(f"duplicate SHA256 in official artifact TSV row {number}")
        tsv_hashes.add(columns[0])
        tsv_rows += 1
        hashes.add(columns[0])
        for raw in columns[1:3]:
            safe = _safe_repo_path(raw)
            if safe is None:
                raise RemediationError(
                    f"unsafe/noncanonical path in official artifact TSV row {number}: {raw!r}"
                )
            exact_paths.add(safe)
    if not tsv_rows:
        raise RemediationError("official artifact TSV contains no rows")

    export_text = payloads[G007_EXPORT_REL.as_posix()].decode("utf-8")
    validator_text = payloads[G007_VALIDATOR_REL.as_posix()].decode("utf-8")
    try:
        export_tree = ast.parse(export_text)
        validator_tree = ast.parse(validator_text)
        g007_families = _literal_assignment(export_tree, "GUARDED_PATH_PARTS")
        prohibited_pattern = _literal_assignment(validator_tree, "PROHIBITED_SOURCE_RE")
        re.compile(prohibited_pattern)
    except (SyntaxError, ValueError, TypeError, re.error) as exc:
        raise RemediationError(f"canonical Python policy authority is invalid: {exc}") from exc
    family_parts = {tuple(parts) for parts in MANDATORY_FAMILY_PARTS}
    for parts in g007_families:
        if not isinstance(parts, (tuple, list)) or not all(
            isinstance(part, str) and part for part in parts
        ):
            raise RemediationError("G007 guarded path family is malformed")
        family_parts.add(tuple(parts))

    clean_room = payloads[CLEAN_ROOM_POLICY_REL.as_posix()].decode("utf-8").lower()
    authorization = payloads[AUTHORIZATION_SCOPE_REL.as_posix()].decode("utf-8").lower()
    for phrase in ("prohibited promotion", "decompiler output", "vendor binaries"):
        if phrase not in clean_room:
            raise RemediationError(f"clean-room policy lacks required boundary: {phrase}")
    for phrase in ("separate authorization gates", "public distribution", "stay local"):
        if phrase not in authorization:
            raise RemediationError(f"authorization scope lacks required boundary: {phrase}")

    return {
        "schema": "g012-history-remediation-policy/v1",
        "deny_sha256": sorted(hashes),
        "exact_guarded_paths": sorted(exact_paths),
        "family_parts": [list(parts) for parts in sorted(family_parts)],
        "root_globs": list(MANDATORY_ROOT_GLOBS),
        "prohibited_source_regex": prohibited_pattern,
        "authorities": [
            {
                "path": rel.as_posix(),
                "sha256": _sha256_bytes(payloads[rel.as_posix()]),
                "size_bytes": len(payloads[rel.as_posix()]),
            }
            for rel in rels
        ],
        "nonclaims": [
            "This policy is a conservative technical publication boundary, not legal advice.",
            "No redistribution, ownership, license, or public-distribution authority is claimed.",
        ],
    }


def _is_guarded_path(path_text: str, policy: dict[str, Any]) -> bool:
    if path_text in set(policy["exact_guarded_paths"]):
        return True
    path = PurePosixPath(path_text)
    parts = path.parts
    if parts and parts[0] == "lib":
        return True
    if len(parts) >= 2 and parts[0] == "_workspace" and parts[1].startswith("hikmicro-"):
        return True
    for family in policy["family_parts"]:
        family_tuple = tuple(family)
        width = len(family_tuple)
        if any(
            parts[offset : offset + width] == family_tuple
            for offset in range(len(parts) - width + 1)
        ):
            return True
    return False


def _historical_guard_inventory(
    repo: Path, policy: dict[str, Any]
) -> tuple[list[str], list[str]]:
    commits = _git(repo, "rev-list", "--all").decode("ascii").splitlines()
    paths: set[str] = set()
    guarded_blob_oids: set[str] = set()
    entry_count = 0
    for commit in commits:
        payload = _git(repo, "ls-tree", "-r", "-z", commit)
        for record in payload.split(b"\x00"):
            if not record:
                continue
            entry_count += 1
            if entry_count > MAX_TREE_ENTRIES:
                raise RemediationError("historical tree scan exceeds the entry-count limit")
            try:
                metadata, raw_path = record.split(b"\t", 1)
                mode, kind, oid = metadata.decode("ascii").split(" ")
            except (ValueError, UnicodeDecodeError) as exc:
                raise RemediationError("Git returned a malformed historical tree row") from exc
            if not OID_RE.fullmatch(oid) or not mode:
                raise RemediationError("Git returned an invalid historical tree object ID")
            path = raw_path.decode("utf-8", "surrogateescape")
            paths.add(path)
            if _is_guarded_path(path, policy) and kind == "blob":
                guarded_blob_oids.add(oid)
    return sorted(paths), sorted(guarded_blob_oids)


def _object_ids(repo: Path, revisions: Iterable[str]) -> list[str]:
    revision_list = list(revisions)
    revision_lines = b"".join((revision + "\n").encode("utf-8") for revision in revision_list)
    payload = _git(
        repo,
        "rev-list",
        "--objects",
        "--stdin",
        input_bytes=revision_lines,
        maximum_output=MAX_CAPTURE_BYTES,
    )
    result = {line.split(b" ", 1)[0].decode("ascii") for line in payload.splitlines()}
    for revision in revision_list:
        result.add(_git(repo, "rev-parse", "--verify", revision).decode().strip())
    return sorted(result)


def _blob_ids(repo: Path, object_ids: Iterable[str]) -> list[str]:
    result: list[str] = []
    for oid in object_ids:
        kind = _git(repo, "cat-file", "-t", oid).decode().strip()
        if kind == "blob":
            result.append(oid)
    return result


def _scan_blob(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
    oid: str,
    deny_hashes: set[str],
    prohibited: re.Pattern[str],
) -> dict[str, Any]:
    size = int(_git(repo, "cat-file", "-s", oid).decode().strip())
    if size > MAX_BLOB_BYTES:
        raise RemediationError(f"blob {oid} exceeds the {MAX_BLOB_BYTES}-byte scan limit")
    process = subprocess.Popen(
        _git_argv(repo, "cat-file", "blob", oid),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_git_env(),
        pass_fds=_git_pass_fds(repo),
    )
    assert process.stdout is not None
    digest = hashlib.sha256()
    matched = False
    tail = ""
    total = 0
    while True:
        chunk = process.stdout.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        digest.update(chunk)
        text = tail + chunk.decode("latin-1")
        if prohibited.search(text):
            matched = True
        tail = text[-4096:]
    process.stdout.close()
    stderr = process.stderr.read() if process.stderr else b""
    if process.stderr:
        process.stderr.close()
    returncode = process.wait()
    if returncode:
        raise RemediationError(
            f"could not scan blob {oid}: {stderr.decode('utf-8', 'replace')}"
        )
    if total != size:
        raise RemediationError(f"blob {oid} changed or was truncated during scan")
    sha256 = digest.hexdigest()
    return {
        "oid": oid,
        "sha256": sha256,
        "size_bytes": size,
        "deny_hash_match": sha256 in deny_hashes,
        "prohibited_content_match": matched,
    }


def _scan_reachable_blobs(
    repo: Path, refs: Iterable[str], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    object_ids = _object_ids(repo, refs)
    blobs = _blob_ids(repo, object_ids)
    deny_hashes = set(policy["deny_sha256"])
    prohibited = re.compile(policy["prohibited_source_regex"])
    return [_scan_blob(repo, oid, deny_hashes, prohibited) for oid in blobs]


def _metadata_findings(
    repo: Path, refs: Iterable[str], policy: dict[str, Any]
) -> list[dict[str, str]]:
    prohibited = re.compile(policy["prohibited_source_regex"])
    findings: list[dict[str, str]] = []
    for oid in _object_ids(repo, refs):
        kind = _git(repo, "cat-file", "-t", oid).decode().strip()
        if kind not in {"commit", "tag"}:
            continue
        payload = _git(repo, "cat-file", kind, oid)
        text = payload.decode("utf-8", "replace")
        if prohibited.search(text):
            findings.append(
                {"kind": "prohibited_metadata", "object_type": kind, "oid": oid}
            )
        headers = text.split("\n\n", 1)[0]
        if kind == "commit" and re.search(r"(?m)^gpgsig(?:-sha256)? ", headers):
            findings.append(
                {"kind": "signed_commit", "object_type": kind, "oid": oid}
            )
        if kind == "tag" and (
            re.search(
                r"-----BEGIN (?:PGP |SSH |X509 )?SIGNATURE-----",
                text,
            )
            or "-----BEGIN SIGNED MESSAGE-----" in text
        ):
            findings.append(
                {"kind": "signed_annotated_tag", "object_type": kind, "oid": oid}
            )
    return findings


def _reject_prohibited_metadata(
    repo: Path, refs: Iterable[str], policy: dict[str, Any]
) -> None:
    findings = _metadata_findings(repo, refs, policy)
    if findings:
        raise RemediationError(
            "history metadata requires manual remediation before rewrite: "
            + json.dumps(findings, sort_keys=True)
        )


def _verify_ref(repo: Path, ref: str, policy: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    paths_payload = _git(repo, "log", ref, "--format=", "--name-only", "-z")
    for raw in paths_payload.split(b"\x00"):
        if not raw:
            continue
        path = raw.decode("utf-8", "surrogateescape")
        if _is_guarded_path(path, policy):
            findings.append({"kind": "guarded_path", "ref": ref, "path": path})
    for row in _scan_reachable_blobs(repo, [ref], policy):
        if row["deny_hash_match"]:
            findings.append(
                {
                    "kind": "deny_sha256",
                    "ref": ref,
                    "oid": row["oid"],
                    "sha256": row["sha256"],
                }
            )
        if row["prohibited_content_match"]:
            findings.append(
                {"kind": "prohibited_content", "ref": ref, "oid": row["oid"]}
            )
    for row in _metadata_findings(repo, [ref], policy):
        findings.append({"ref": ref, **row})
    return findings


def _object_exists(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
    oid: str,
) -> bool:
    completed = subprocess.run(
        _git_argv(repo, "cat-file", "-e", f"{oid}^{{object}}"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_git_env(),
        check=False,
        pass_fds=_git_pass_fds(repo),
    )
    return completed.returncode == 0


def _verify_repository(
    repo: Path,
    policy: dict[str, Any],
    label: str,
    remediation: dict[str, Any],
) -> dict[str, Any]:
    refs = _refs(repo)
    findings: list[dict[str, str]] = []
    try:
        _assert_roots_accounted(repo)
        _validate_ref_roots(repo, refs)
    except RemediationError as exc:
        findings.append({"kind": "unaccounted_root", "detail": str(exc)})
    for row in refs:
        if any(row["ref"].startswith(prefix) for prefix in FORBIDDEN_REF_PREFIXES):
            findings.append({"kind": "leftover_rewrite_ref", "ref": row["ref"]})
    for row in refs:
        findings.extend(_verify_ref(repo, row["ref"], policy))
    reachable_blob_rows = _scan_reachable_blobs(
        repo, [row["ref"] for row in refs], policy
    )
    absent_oids = set(remediation["expected_absent_blob_oids"])
    absent_hashes = set(remediation["expected_absent_sha256"])
    for row in reachable_blob_rows:
        if row["oid"] in absent_oids:
            findings.append(
                {"kind": "stripped_oid_still_reachable", "oid": row["oid"]}
            )
        if row["sha256"] in absent_hashes:
            findings.append(
                {
                    "kind": "stripped_content_hash_still_reachable",
                    "oid": row["oid"],
                    "sha256": row["sha256"],
                }
            )
    for oid in sorted(absent_oids):
        if _object_exists(repo, oid):
            findings.append({"kind": "stripped_oid_still_present", "oid": oid})
    fsck = subprocess.run(
        _git_argv(repo, "fsck", "--full", "--strict"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_git_env(),
        check=False,
        pass_fds=_git_pass_fds(repo),
    )
    if len(fsck.stdout) + len(fsck.stderr) > MAX_CAPTURE_BYTES:
        raise RemediationError("git fsck output exceeded the capture limit")
    if fsck.returncode:
        findings.append(
            {
                "kind": "git_fsck_failure",
                "detail": (fsck.stderr or fsck.stdout)
                .decode("utf-8", "replace")
                .strip(),
            }
        )
    return {
        "label": label,
        "ok": not findings,
        "ref_count": len(refs),
        "refs": refs,
        "object_inventory": _object_inventory(repo),
        "findings": findings,
        "fsck_stdout": fsck.stdout.decode("utf-8", "replace"),
        "fsck_stderr": fsck.stderr.decode("utf-8", "replace"),
    }


def _read_bounded_fd(descriptor: int, maximum: int, label: str) -> bytes:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as exc:
        raise RemediationError(f"{label} descriptor is not seekable") from exc
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise RemediationError(f"{label} exceeds the byte limit")
        chunks.append(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return b"".join(chunks)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise RemediationError("short write while preserving git-filter-repo")
        view = view[written:]


def _required_memfd_seals() -> int:
    required_names = (
        "F_ADD_SEALS",
        "F_GET_SEALS",
        "F_SEAL_WRITE",
        "F_SEAL_GROW",
        "F_SEAL_SHRINK",
        "F_SEAL_SEAL",
    )
    if not callable(getattr(os, "memfd_create", None)) or not hasattr(
        os, "MFD_ALLOW_SEALING"
    ):
        raise RemediationError("sealed memfd support is required for tool execution")
    missing = [name for name in required_names if not hasattr(fcntl, name)]
    if missing:
        raise RemediationError(
            f"sealed memfd support is incomplete (missing {', '.join(missing)})"
        )
    proc_fd = Path("/proc/self/fd")
    if not proc_fd.is_dir():
        raise RemediationError("/proc/self/fd is required for sealed tool execution")
    return (
        fcntl.F_SEAL_WRITE
        | fcntl.F_SEAL_GROW
        | fcntl.F_SEAL_SHRINK
        | fcntl.F_SEAL_SEAL
    )


def _verify_sealed_tool(tool: SealedFilterRepoTool) -> None:
    required_seals = _required_memfd_seals()
    try:
        actual_seals = fcntl.fcntl(tool.fd, fcntl.F_GET_SEALS)
        descriptor_stat = os.fstat(tool.fd)
    except OSError as exc:
        raise RemediationError("sealed git-filter-repo descriptor is unavailable") from exc
    if actual_seals & required_seals != required_seals:
        raise RemediationError("git-filter-repo memfd is not fully sealed")
    if not stat.S_ISREG(descriptor_stat.st_mode):
        raise RemediationError("git-filter-repo memfd is not a regular file")
    descriptor_payload = _read_bounded_fd(
        tool.fd, MAX_TOOL_BYTES, "sealed git-filter-repo"
    )
    if _sha256_bytes(descriptor_payload) != EXPECTED_FILTER_REPO_SHA256:
        raise RemediationError("sealed git-filter-repo descriptor hash mismatch")

    proc_path = f"/proc/self/fd/{tool.fd}"
    proc_descriptor: int | None = None
    try:
        proc_descriptor = os.open(proc_path, os.O_RDONLY)
        proc_stat = os.fstat(proc_descriptor)
        if (
            proc_stat.st_dev,
            proc_stat.st_ino,
            proc_stat.st_size,
        ) != (
            descriptor_stat.st_dev,
            descriptor_stat.st_ino,
            descriptor_stat.st_size,
        ):
            raise RemediationError(
                "/proc/self/fd does not resolve to the sealed tool descriptor"
            )
        proc_payload = _read_bounded_fd(
            proc_descriptor, MAX_TOOL_BYTES, "/proc/self/fd git-filter-repo"
        )
    except OSError as exc:
        raise RemediationError(
            "/proc/self/fd is unavailable for sealed tool execution"
        ) from exc
    finally:
        if proc_descriptor is not None:
            os.close(proc_descriptor)
    if _sha256_bytes(proc_payload) != EXPECTED_FILTER_REPO_SHA256:
        raise RemediationError("/proc/self/fd git-filter-repo hash mismatch")
    os.lseek(tool.fd, 0, os.SEEK_SET)


def _write_tool_evidence(path: Path, payload: bytes, *, exclusive: bool) -> None:
    if exclusive:
        _secure_create_output(
            path,
            payload,
            "git-filter-repo evidence",
            mode=0o500,
            maximum=MAX_TOOL_BYTES,
        )
    else:
        _secure_replace_output(
            path,
            payload,
            "git-filter-repo evidence",
            mode=0o500,
        )


def _evidence_tool_matches(path: Path) -> bool:
    try:
        return (
            not path.is_symlink()
            and path.is_file()
            and stat.S_IMODE(path.stat().st_mode) == 0o500
            and _sha256_file(path, MAX_TOOL_BYTES) == EXPECTED_FILTER_REPO_SHA256
        )
    except (OSError, RemediationError):
        return False


def _restore_tool_evidence(tool: SealedFilterRepoTool) -> None:
    if _evidence_tool_matches(tool.evidence_path):
        return
    tool.evidence_substitution_detected = True
    payload = _read_bounded_fd(
        tool.fd, MAX_TOOL_BYTES, "sealed git-filter-repo evidence source"
    )
    if _sha256_bytes(payload) != EXPECTED_FILTER_REPO_SHA256:
        raise RemediationError("sealed evidence source hash mismatch")
    _write_tool_evidence(tool.evidence_path, payload, exclusive=False)
    if not _evidence_tool_matches(tool.evidence_path):
        raise RemediationError("could not restore quarantined tool evidence")


def _quarantine_filter_repo_tool(
    tool_arg: str, run_root: Path
) -> SealedFilterRepoTool:
    tool = Path(tool_arg)
    if not tool.is_absolute():
        raise RemediationError("--filter-repo-tool must be an explicit absolute path")
    tool_label = "--filter-repo-tool"
    held = _open_secure_regular(tool, tool_label)
    assert held is not None
    try:
        descriptor = held.descriptor
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_TOOL_BYTES:
            raise RemediationError("git-filter-repo tool is not a bounded regular file")
        if not before.st_mode & stat.S_IXUSR:
            raise RemediationError("--filter-repo-tool must be executable by its owner")
        held.revalidate(tool_label)
        payload = _read_bounded_fd(
            descriptor, MAX_TOOL_BYTES, "git-filter-repo tool"
        )
        middle = os.fstat(descriptor)
        held.revalidate(tool_label)
        after = os.fstat(descriptor)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        for observed in (middle, after):
            observed_identity = (
                observed.st_dev,
                observed.st_ino,
                observed.st_size,
                observed.st_mtime_ns,
                observed.st_ctime_ns,
            )
            if before_identity != observed_identity:
                raise RemediationError("git-filter-repo changed while being read")
        held.revalidate(tool_label)
        if len(payload) != before.st_size:
            raise RemediationError("git-filter-repo changed while being read")
    finally:
        held.close()
    actual = _sha256_bytes(payload)
    if actual != EXPECTED_FILTER_REPO_SHA256:
        raise RemediationError(
            "git-filter-repo SHA256 mismatch: "
            f"expected {EXPECTED_FILTER_REPO_SHA256}, found {actual}"
        )
    private_dir = run_root / "private-tool"
    _secure_output_directory(
        private_dir,
        "private git-filter-repo evidence directory",
    )
    preserved = private_dir / "git-filter-repo-v2.47.0"
    memfd: int | None = None
    try:
        _write_tool_evidence(preserved, payload, exclusive=True)
        if not _evidence_tool_matches(preserved):
            raise RemediationError("quarantined git-filter-repo evidence hash mismatch")
        required_seals = _required_memfd_seals()
        memfd_flags = os.MFD_ALLOW_SEALING | getattr(os, "MFD_CLOEXEC", 0)
        memfd = os.memfd_create("g012-git-filter-repo-v2.47.0", memfd_flags)
        _write_all(memfd, payload)
        os.fsync(memfd)
        fcntl.fcntl(memfd, fcntl.F_ADD_SEALS, required_seals)
        sealed = SealedFilterRepoTool(
            fd=memfd,
            evidence_path=preserved,
            supplied_path=tool,
            sha256=actual,
        )
        _verify_sealed_tool(sealed)
        return sealed
    except Exception:
        if memfd is not None:
            os.close(memfd)
        raise


def _verify_tool_evidence(tool: Path) -> None:
    if not _evidence_tool_matches(tool):
        raise RemediationError("quarantined git-filter-repo evidence changed")


def _clone_mirror(
    source: Path | SourceRepositoryAnchor | RepositoryLayout,
    mirror: Path,
) -> None:
    command_path, pass_fds = _git_context(source)
    destination = _prepare_exclusive_destination(
        mirror,
        f"local mirror destination {mirror.name}",
    )
    try:
        _run(
            [
                "git",
                *_git_safety_arguments(),
                "-c",
                "transfer.hideRefs=",
                "-c",
                "uploadpack.hideRefs=",
                "clone",
                "--mirror",
                "--local",
                "--no-hardlinks",
                str(command_path),
                str(destination.command_path),
            ],
            pass_fds=tuple(sorted({*pass_fds, *destination.pass_fds})),
        )
        destination.verify_created_directory()
    except Exception:
        destination.cleanup_if_owned()
        raise
    finally:
        destination.close()


def _clone_bundle(bundle: Path, mirror: Path) -> None:
    destination = _prepare_exclusive_destination(
        mirror,
        f"bundle clone destination {mirror.name}",
    )
    try:
        _run(
            [
                "git",
                *_git_safety_arguments(),
                "clone",
                "--mirror",
                str(bundle),
                str(destination.command_path),
            ],
            pass_fds=destination.pass_fds,
        )
        destination.verify_created_directory()
    except Exception:
        destination.cleanup_if_owned()
        raise
    finally:
        destination.close()


def _materialize_mirror_objects(mirror: Path) -> None:
    _git(mirror, "repack", "-a", "-d")
    alternates = mirror / "objects" / "info" / "alternates"
    if alternates.exists():
        if alternates.is_symlink() or not alternates.is_file():
            raise RemediationError("mirror object alternates file is unsafe")
        alternates.unlink()
    _git(mirror, "fsck", "--full", "--strict")


def _run_git_bundle_to_fd(
    repo: Path | SourceRepositoryAnchor | RepositoryLayout,
    refs: list[str],
    output: SecureOutputFile,
) -> None:
    """Stream a bundle directly into the already-open output descriptor."""
    output.parent.revalidate("Git bundle subprocess output")
    os.ftruncate(output.descriptor, 0)
    os.lseek(output.descriptor, 0, os.SEEK_SET)
    inherited_descriptors = {
        *_git_pass_fds(repo),
        *output.pass_fds,
        *(
            anchor.held.descriptor
            for anchor in tuple(_ACTIVE_RUN_ROOT_ANCHORS.values())
            if not anchor.closed
        ),
    }
    completed = subprocess.run(
        _git_argv(repo, "bundle", "create", "-", *refs),
        stdin=subprocess.DEVNULL,
        stdout=output.descriptor,
        stderr=subprocess.PIPE,
        check=False,
        env=_git_env(),
        pass_fds=tuple(sorted(inherited_descriptors)),
    )
    stderr = completed.stderr or b""
    if len(stderr) > MAX_CAPTURE_BYTES:
        raise RemediationError(
            "Git bundle stderr exceeded the bounded capture limit"
        )
    if completed.returncode:
        detail = stderr.decode("utf-8", "replace").strip()
        raise RemediationError(
            f"Git bundle creation failed ({completed.returncode}): {detail}"
        )


def _bundle(repo: Path, destination: Path, refs: Iterable[str]) -> None:
    ref_list = sorted(set(refs))
    if not ref_list:
        raise RemediationError(f"cannot create a bundle without explicit refs: {destination}")
    output = _open_exclusive_output_file(
        destination,
        f"Git bundle output {destination.name}",
        mode=0o600,
    )
    try:
        _run_git_bundle_to_fd(repo, ref_list, output)
        output.fsync(f"Git bundle output {destination.name}")
        digest, size = _hash_open_descriptor(
            output.descriptor,
            MAX_SOURCE_FILE_BYTES,
            f"Git bundle output {destination.name}",
        )
        observed = output.revalidate(
            f"Git bundle output {destination.name}"
        )
        if size <= 0 or observed.st_size != size:
            raise RemediationError(
                f"Git created an unsafe or empty bundle: {destination}"
            )
        os.lseek(output.descriptor, 0, os.SEEK_SET)
        _git(
            repo,
            "bundle",
            "verify",
            str(output.command_path),
            pass_fds=output.pass_fds,
        )
        verified_digest, verified_size = _hash_open_descriptor(
            output.descriptor,
            MAX_SOURCE_FILE_BYTES,
            f"verified Git bundle output {destination.name}",
        )
        if (
            verified_digest != digest
            or verified_size != size
        ):
            raise RemediationError(
                f"Git bundle changed during same-descriptor verification: "
                f"{destination}"
            )
        output.fsync(f"verified Git bundle output {destination.name}")
    except Exception:
        output.cleanup_if_owned(
            f"failed Git bundle output {destination.name}"
        )
        raise
    finally:
        output.close()


def _verify_bundle_restoration(
    bundle: Path,
    expected_refs: list[dict[str, str]],
    label: str,
    expected_objects: dict[str, Any] | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="g012-bundle-restore-") as temporary:
        restored = Path(temporary) / "restored.git"
        _clone_bundle(bundle, restored)
        _reject_internal_symlinks(restored)
        _restore_symbolic_refs(restored, expected_refs, label)
        _require_exact_refs(expected_refs, _refs(restored), label)
        if expected_objects is not None:
            _verify_cleaned_object_scope(
                restored,
                expected_refs,
                expected_objects,
                label,
            )
        _git(restored, "fsck", "--full", "--strict")


def _write_refs(path: Path, refs: list[dict[str, str]]) -> None:
    lines = ["ref\toid\tobject_type\tsymref"]
    lines.extend(
        "\t".join((row["ref"], row["oid"], row["object_type"], row["symref"]))
        for row in refs
    )
    _secure_create_output(
        path,
        ("\n".join(lines) + "\n").encode("utf-8"),
        f"ref inventory {path.name}",
    )


def _read_refs(path: Path) -> list[dict[str, str]]:
    payload = _read_regular(path, path.name)
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise RemediationError(f"ref TSV is not UTF-8: {path}") from exc
    if not lines or lines[0] != "ref\toid\tobject_type\tsymref":
        raise RemediationError(f"invalid ref TSV header: {path}")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for number, line in enumerate(lines[1:], 2):
        fields = line.split("\t")
        if (
            len(fields) != 4
            or not fields[0].startswith("refs/")
            or fields[0] in seen
            or not OID_RE.fullmatch(fields[1])
            or fields[2] not in {"commit", "tag", "tree", "blob"}
            or (
                fields[3]
                and (
                    not fields[3].startswith("refs/")
                    or "\x00" in fields[3]
                    or any(character.isspace() for character in fields[3])
                )
            )
        ):
            raise RemediationError(f"invalid ref TSV row {number}: {path}")
        seen.add(fields[0])
        rows.append(
            {
                "ref": fields[0],
                "oid": fields[1],
                "object_type": fields[2],
                "symref": fields[3],
            }
        )
    if rows != sorted(rows, key=lambda row: row["ref"]):
        raise RemediationError(f"ref TSV rows are not sorted: {path}")
    by_ref = {row["ref"]: row for row in rows}
    for row in rows:
        if row["symref"]:
            target = by_ref.get(row["symref"])
            if (
                target is None
                or target["oid"] != row["oid"]
                or target["object_type"] != row["object_type"]
            ):
                raise RemediationError(
                    f"unaccounted or inconsistent symbolic ref in {path}: "
                    f"{row['ref']} -> {row['symref']}"
                )
    return rows


def _reject_internal_symlinks(repo: Path) -> None:
    _descriptor_tree_listing(
        repo,
        f"Git repository {repo}",
        reject_symlinks=True,
        symlink_error="internal Git symlink is forbidden",
    )


def _remove_remote_configuration(repo: Path) -> None:
    payload = _git(repo, "config", "--null", "--list")
    keys = []
    for record in payload.decode("utf-8", "replace").split("\x00"):
        if not record:
            continue
        key = record.split("\n", 1)[0]
        if (
            re.fullmatch(r"remote\..*\.(?:url|pushurl|push)", key)
            or key == "remote.pushdefault"
            or key.startswith("push.")
        ):
            keys.append(key)
    for key in sorted(set(keys)):
        completed = subprocess.run(
            _git_argv(repo, "config", "--unset-all", key),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_git_env(),
            check=False,
            pass_fds=_git_pass_fds(repo),
        )
        if completed.returncode not in {0, 5}:
            raise RemediationError(f"could not remove local remote configuration key {key}")


def _invoke_filter_repo(
    tool: SealedFilterRepoTool,
    mirror: Path,
    policy: dict[str, Any],
    bad_paths: list[str],
    strip_ids_path: Path,
) -> list[str]:
    _verify_sealed_tool(tool)
    executable_descriptor_path = f"/proc/self/fd/{tool.fd}"
    command = [
        sys.executable,
        executable_descriptor_path,
        "--force",
        "--invert-paths",
        "--strip-blobs-with-ids",
        str(strip_ids_path),
        "--replace-refs",
        "delete-no-add",
    ]
    for path in bad_paths:
        command.extend(["--path", path])
    for glob in policy["root_globs"]:
        command.extend(["--path-glob", glob])
    # Match canonical namespaces regardless of their source-root prefix.
    for family in policy["family_parts"]:
        joined = "/".join(family)
        command.extend(["--path-glob", f"{joined}/**"])
        command.extend(["--path-glob", f"*/{joined}/**"])
    _run(
        command,
        cwd=mirror,
        maximum_output=MAX_CAPTURE_BYTES,
        pass_fds=(tool.fd,),
    )
    _verify_sealed_tool(tool)
    _restore_tool_evidence(tool)
    return command


def _copy_filter_repo_maps(mirror: Path, manifests: Path) -> list[str]:
    copied: list[str] = []
    metadata = mirror / "filter-repo"
    for name in ("commit-map", "ref-map", "changed-refs", "first-changed-commits"):
        source = metadata / name
        payload = _read_optional_regular(
            source,
            f"git-filter-repo mapping {name}",
            MAX_CAPTURE_BYTES,
        )
        if payload is None:
            continue
        target = manifests / f"filter-repo-{name}.txt"
        _secure_create_output(
            target,
            payload,
            f"git-filter-repo mapping copy {name}",
            maximum=MAX_CAPTURE_BYTES,
        )
        copied.append(target.name)
    return copied


def _delete_rewrite_refs(repo: Path) -> list[str]:
    removed: list[str] = []
    for row in _refs(repo):
        if any(row["ref"].startswith(prefix) for prefix in FORBIDDEN_REF_PREFIXES):
            _git(repo, "update-ref", "-d", row["ref"])
            removed.append(row["ref"])
    return removed


def _validate_g007_archive_bytes(
    archive_bytes: bytes,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if len(archive_bytes) > MAX_G007_ARCHIVE_BYTES:
        raise RemediationError("G007 clean-room archive exceeds the byte limit")
    archive_sha256 = _sha256_bytes(archive_bytes)
    accepted_profile = G007_ACCEPTED_ARCHIVES.get(archive_sha256)
    if accepted_profile is None:
        # The exact positive-allowlist hash is the outer authority.  Unknown
        # bytes are rejected before ZIP metadata or compressed data is parsed.
        raise RemediationError(
            "G007 archive SHA256 is not in the explicit positive allowlist: "
            f"{archive_sha256}"
        )
    deny_hashes = set(policy["deny_sha256"])
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as handle:
            if handle.comment:
                raise RemediationError("G007 archive comment is forbidden")
            infos = handle.infolist()
            if not infos or len(infos) > MAX_G007_ENTRIES:
                raise RemediationError("G007 archive entry count is invalid")
            names = [info.filename for info in infos]
            if names != sorted(names) or len(names) != len(set(names)):
                raise RemediationError("G007 archive entries must be unique and sorted")
            entries: dict[str, bytes] = {}
            total = 0
            for info in infos:
                path = _manifest_relative_path(info.filename)
                if info.is_dir() or info.filename.endswith("/"):
                    raise RemediationError("G007 archive directory entries are forbidden")
                mode = (info.external_attr >> 16) & 0o177777
                if info.create_system != 3 or not stat.S_ISREG(mode):
                    if stat.S_ISLNK(mode):
                        raise RemediationError("G007 archive symlink entry is forbidden")
                    raise RemediationError(
                        "G007 archive members must be Unix regular files"
                    )
                if info.extra or info.comment:
                    raise RemediationError(
                        "G007 archive member extra fields/comments are forbidden"
                    )
                if info.flag_bits & 0x1:
                    raise RemediationError("encrypted G007 archive entries are forbidden")
                if info.compress_type != zipfile.ZIP_STORED:
                    raise RemediationError("G007 archive compression method is forbidden")
                if (
                    info.file_size > MAX_G007_ENTRY_BYTES
                    or info.compress_size > MAX_G007_ARCHIVE_BYTES
                ):
                    raise RemediationError("G007 archive entry exceeds size limits")
                payload = handle.read(info)
                total += len(payload)
                if total > MAX_G007_ARCHIVE_BYTES:
                    raise RemediationError("G007 archive extracted size exceeds limit")
                path_text = path.as_posix()
                if _is_guarded_path(path_text, policy):
                    raise RemediationError(f"G007 archive contains guarded path: {path_text}")
                digest = _sha256_bytes(payload)
                if digest in deny_hashes:
                    raise RemediationError(
                        f"G007 archive contains denied exact bytes: {path_text}"
                    )
                entries[path_text] = payload
    except zipfile.BadZipFile as exc:
        raise RemediationError(f"invalid G007 ZIP archive: {exc}") from exc
    manifest_name = G007_PUBLICATION_MANIFEST_NAME
    if manifest_name not in entries:
        raise RemediationError("G007 archive lacks PUBLICATION-MANIFEST.json")
    publication = _load_json_bytes(entries[manifest_name], manifest_name)
    expected_publication_keys = {
        "files",
        "nonclaims",
        "payload_file_count",
        "schema",
        "schema_version",
        "scope",
    }
    if not isinstance(publication, dict) or set(publication) != expected_publication_keys:
        raise RemediationError("G007 publication manifest schema is invalid")
    if (
        publication["schema"] != G007_PUBLICATION_SCHEMA
        or publication["schema_version"] != 1
        or isinstance(publication["schema_version"], bool)
        or not isinstance(publication["files"], list)
        or not isinstance(publication["scope"], str)
        or not publication["scope"]
        or not isinstance(publication["nonclaims"], list)
        or not publication["nonclaims"]
        or not all(
            isinstance(item, str) and item for item in publication["nonclaims"]
        )
        or not isinstance(publication["payload_file_count"], int)
        or isinstance(publication["payload_file_count"], bool)
        or publication["payload_file_count"] < 0
    ):
        raise RemediationError("G007 publication manifest declaration is invalid")
    manifest_rows: dict[str, tuple[str, int]] = {}
    for number, row in enumerate(publication["files"], 1):
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "size_bytes"}:
            raise RemediationError(f"malformed G007 publication row {number}")
        path = _manifest_relative_path(row["path"]).as_posix()
        digest = row["sha256"]
        size = row["size_bytes"]
        if (
            path == manifest_name
            or path in manifest_rows
            or not isinstance(digest, str)
            or not SHA256_RE.fullmatch(digest)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise RemediationError(f"invalid G007 publication row {number}")
        manifest_rows[path] = (digest, size)
    if list(manifest_rows) != sorted(manifest_rows):
        raise RemediationError("G007 publication manifest rows are not sorted")
    publication_payload_rows = [
        path
        for path in manifest_rows
        if path != "README.md"
    ]
    if (
        "README.md" not in manifest_rows
        or publication["payload_file_count"] != len(publication_payload_rows)
    ):
        raise RemediationError(
            "G007 publication payload_file_count does not match its governed "
            "payload rows"
        )
    payload_names = set(entries) - {manifest_name}
    if set(manifest_rows) != payload_names:
        raise RemediationError("G007 publication manifest coverage is not exact")
    if len(entries) != len(manifest_rows) + 1:
        raise RemediationError("G007 archive member count is not exact")
    for path, (digest, size) in manifest_rows.items():
        payload = entries[path]
        if len(payload) != size or _sha256_bytes(payload) != digest:
            raise RemediationError(f"G007 publication digest/size mismatch: {path}")
    member_names_sha256 = _sha256_bytes(_canonical_json(sorted(entries)))
    if (
        len(archive_bytes) != accepted_profile["archive_size_bytes"]
        or len(entries) != accepted_profile["member_count"]
        or member_names_sha256 != accepted_profile["member_names_sha256"]
        or _sha256_bytes(entries[manifest_name])
        != accepted_profile["publication_manifest_sha256"]
        or publication["payload_file_count"]
        != accepted_profile["payload_file_count"]
        or publication["scope"] != accepted_profile["scope"]
        or publication["nonclaims"] != accepted_profile["nonclaims"]
    ):
        raise RemediationError(
            "G007 archive does not match its pinned publication profile"
        )
    return {
        "sha256": archive_sha256,
        "size_bytes": len(archive_bytes),
        "profile_id": accepted_profile["profile_id"],
        "member_count": len(entries),
        "manifest_file_count": len(manifest_rows),
        "payload_file_count": publication["payload_file_count"],
        "publication_manifest_sha256": _sha256_bytes(entries[manifest_name]),
        "validated_with": (
            "trusted internal G012 exact-SHA256 positive-allowlist and "
            "ZIP/publication-manifest validator"
        ),
    }


def _preserve_g007_archive(
    source: Path,
    archive_arg: str | None,
    run_root: Path,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if archive_arg is None:
        return {"available": False, "reason": "no --g007-archive was supplied"}
    archive = Path(archive_arg)
    if not archive.is_absolute():
        raise RemediationError("--g007-archive must be an explicit absolute path")
    archive = archive.resolve()
    if archive == source or archive in source.parents or source in archive.parents:
        raise RemediationError("--g007-archive must be outside the source repository")
    archive_bytes = _read_regular(
        archive, "G007 clean-room archive", MAX_G007_ARCHIVE_BYTES
    )
    validation = _validate_g007_archive_bytes(archive_bytes, policy)
    target = run_root / "preserved-g007-clean-room.zip"
    copied = _secure_create_output(
        target,
        archive_bytes,
        "preserved G007 clean-room archive",
        maximum=MAX_G007_ARCHIVE_BYTES,
    )
    if copied != {
        "sha256": validation["sha256"],
        "size_bytes": validation["size_bytes"],
    }:
        raise RemediationError(
            "preserved G007 archive descriptor copy does not match validation"
        )
    return {
        "available": True,
        "source_path": str(archive),
        "preserved_path": target.name,
        **validation,
    }


def _write_documents(run_root: Path, manifest: dict[str, Any]) -> None:
    _secure_create_output(
        run_root / "VERIFYING.md",
        """# Verifying the G012 dry run

This directory is a local technical dry run. It grants no legal, licensing,
redistribution, or publication authority.

1. Review `manifests/policy.json`, `refs-before.tsv`, and `refs-after.tsv`.
   These two TSVs contain only original publishable refs. Synthetic detached
   HEAD/pseudoref evidence is isolated in `evidence-refs-*.tsv`.
2. Review the official git-filter-repo commit/ref maps in `manifests/`.
3. Review `manifests/cleaned-object-inventory.json`. Its publishable and
   evidence scopes must form the exact combined cleaned logical object set.
4. Run the same pinned G012 program with `verify --run-root ABSOLUTE_PATH`.
5. Check `manifests/verification.json` and verify `SHA256SUMS`.
6. Treat `rollback-before.bundle` as sensitive pre-remediation evidence.

Both the rewritten disposable mirror and an independently cloned mirror were
scanned ref-by-ref for guarded historical paths, exact denied SHA256 content,
the canonical forbidden-source regex, rewrite/original/replacement refs, and
strict full Git fsck failures.

The pinned git-filter-repo bytes were read and hashed once, copied into a
write/grow/shrink/seal-sealed Linux memfd, re-hashed through that descriptor,
and executed only as `/proc/self/fd/<inherited-fd>`. The file under
`private-tool/` is checksum evidence only and was never an execution input.

When supplied, the preserved G007 clean-room archive is accepted only at the
explicit SHA256 recorded by this G012 release. Its ZIP topology, exact member
set/count, strict publication declaration, and every declared member size/hash
are validated internally. Guarded paths and official exact-deny hashes remain
forbidden. The generic source-content regex is intentionally not applied
inside this separately governed, exact-hash positive-allowlist artifact.

The run root must not exist before the dry run. It is created beneath held,
no-symlink ancestor descriptors and remains lifetime-anchored by its directory
descriptor. Predictable files use descriptor-relative
`O_CREAT|O_EXCL|O_NOFOLLOW`; content is hashed, identity-checked, and fsynced
through the same held file descriptor. Git clone destinations are created
descriptor-relatively and populated only through a held directory descriptor.
Bundles are streamed with `git bundle create -` directly into one exclusively
created held file descriptor; that same descriptor is fsynced, hashed, and
verified. Failed outputs are first moved descriptor-relatively to an
unpredictable quarantine with atomic no-replace semantics. Only an exact match
to the held created identity is deleted; substitutions are atomically restored
without overwrite or retained under quarantine when restoration is unsafe.
All Git paths under the run root use inherited `/proc/self/fd/<root-fd>` paths,
so pathname ABA cannot redirect them to a replacement directory.

The canonical source repository top-level is opened once with no-symlink
descriptor traversal before run-root creation and remains held through the
outer post-run mutation guard. Every source Git subprocess and the initial
local mirror clone use `/proc/self/fd/<inherited-source-fd>` with that exact
descriptor inherited via `pass_fds`; those operations never reopen the mutable
source pathname. Canonical authority and worktree-content reads are likewise
rooted at the held descriptor. Separately located Git administration/object
stores are not accepted: the Git directory, common directory, primary object
store, and every recursive alternate object store must remain lexically and
topologically beneath the anchored source worktree.

Security-critical regular files, including canonical authorities and recursive
alternate metadata, are opened component-by-component from a held filesystem
root descriptor. Every ancestor uses descriptor-relative
`O_DIRECTORY|O_NOFOLLOW`; the leaf uses descriptor-relative `O_NOFOLLOW`.
Root, ancestor, leaf, and descriptor identities are revalidated before,
during, and after reads. Discovered files are required; only callsites
explicitly marked optional may be absent before discovery. Ancestor rename,
symlink replacement, leaf replacement, and post-discovery disappearance fail
closed.

Security-critical directory trees are recursively enumerated only through held
directory descriptors. Child directories use descriptor-relative
`O_DIRECTORY|O_NOFOLLOW`, leaves are opened relative to their held parent, and
each directory is re-enumerated before close. Worktree, object/alternate, ref,
reflog, hook, and administrative roots remain held and path-revalidated for
their complete walk. Linked-worktree local refs/logs/hooks are inventoried in
separate non-overlapping scopes and share the same global byte budget. Unknown
`BISECT_*` or other administrative files receive no wildcard exemption;
object-bearing unknown files fail closed. Hexadecimal tokens from 7 through 64
characters are resolved through anchored Git; ambiguous abbreviations fail
closed, and a resolved object is accepted only when already reachable from an
accounted ref.

Source regular files are hashed through race-checked descriptors in 1 MiB
chunks, with an 8 GiB per-file limit and a 64 GiB aggregate inventory limit.
Sparse files are supported through exact logical reads (holes hash as zero
bytes); sparse status and allocated block count are recorded and guarded.
One monotonic 64 GiB budget is shared by every source-state inventory root,
including the recursive administrative pre-scan and recursive alternates.
Administrative files read by the pre-scan consume budget again when the
independent complete admin inventory reads them. Each regular file is hashed
twice through the
same `O_NOFOLLOW` descriptor with pre/mid/post stat comparison. Deterministic
`SEEK_DATA`/`SEEK_HOLE` layouts are compared through constant-memory canonical
summaries when supported. Each summary retains counts, total data bytes, a
SHA256 over canonical start/length records, and at most four first/final
samples. Traversal fails closed above 16,384 extents or 32,769 sparse-seek
operations, so serialized inventories and traversal resources remain bounded.
Special files, pathname substitutions, inconsistent extent semantics,
allocation-layout changes, and metadata/content changes fail closed.
""".encode("utf-8"),
        "VERIFYING.md",
    )
    _secure_create_output(
        run_root / "FORCE-PUSH-RUNBOOK.md",
        """# Force-push runbook (manual, separately authorized operation)

This dry-run tool never pushes and never changes a remote. It does not establish
authority to publish or redistribute anything. Before any remote action, obtain
separate legal/organizational approval, archive the current remote refs, freeze
merges, notify collaborators, independently review all mappings and scans, and
test restoration from `rollback-before.bundle`.

If separately authorized, an operator should construct an explicit ref-by-ref
lease-protected update from `refs-before.tsv` and `refs-after.tsv`; do not use a
blanket mirror push. Re-run remote-side verification after the update. Abort if
any expected old ref differs, any hidden/protected ref is unaccounted for, or
branch protection/audit requirements are unresolved.

The ref TSV records include object type and symbolic-ref target. Git bundle
format stores direct ref tips rather than arbitrary symbolic-ref relationships,
so exact local restoration must reapply the recorded symbolic relationships and
then compare every refname/OID/type/symref field. Do not translate a symbolic
ref into a publishable direct update without separate review and authorization.

`refs/g012-captured/*`, `evidence-refs-before.tsv`, `evidence-refs-after.tsv`,
`rollback-evidence-before.bundle`, and `rewritten-evidence.bundle` are
non-publishable audit evidence. They must never be included in a remote update.

No push command is provided or executed by this artifact.
""".encode("utf-8"),
        "FORCE-PUSH-RUNBOOK.md",
    )
    _secure_create_output(
        run_root / "COLLABORATOR-RECOVERY.md",
        """# Collaborator recovery

After a separately approved public-history replacement, collaborators must not
merge old clones back into rewritten refs. Preserve local work as patches or
new commits, obtain a fresh clone, and reapply only reviewed safe changes.

Before disposal, compare local branches/tags against the published ref mapping.
Use `rollback-before.bundle` only in a quarantined local repository for audit or
authorized rollback. Do not publish that bundle: it intentionally preserves the
pre-remediation history and may contain denied material.
""".encode("utf-8"),
        "COLLABORATOR-RECOVERY.md",
    )


def _sha_manifest(run_root: Path, paths: Iterable[Path]) -> None:
    rows = []
    for path in sorted(paths, key=lambda item: item.relative_to(run_root).as_posix()):
        rows.append(f"{_sha256_file(path)}  {path.relative_to(run_root).as_posix()}")
    _secure_create_output(
        run_root / "SHA256SUMS",
        ("\n".join(rows) + "\n").encode("utf-8"),
        "SHA256SUMS",
    )


def _manifest_relative_path(raw: str) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise RemediationError(f"unsafe SHA256SUMS path: {raw!r}")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RemediationError(f"unsafe SHA256SUMS path: {raw!r}")
    if path.as_posix() != raw:
        raise RemediationError(f"noncanonical SHA256SUMS path: {raw!r}")
    return path


def _artifact_files_on_disk(run_root: Path) -> set[str]:
    rows = _descriptor_tree_listing(
        run_root,
        "G012 run root",
        excluded_root_names=frozenset(
            {"disposable-mirror.git", "independent-sanitized.git"}
        ),
        reject_symlinks=True,
        symlink_error="symlinked artifact path is forbidden",
    )
    return {
        row["path"]
        for row in rows
        if row["kind"] == "file" and row["path"] != "SHA256SUMS"
    }


def _validate_sha256_manifest(run_root: Path) -> dict[str, Any]:
    payload = _read_regular(run_root / "SHA256SUMS", "SHA256SUMS")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RemediationError("SHA256SUMS is not UTF-8") from exc
    if not text.endswith("\n"):
        raise RemediationError("SHA256SUMS must end with exactly formatted records")
    rows: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise RemediationError(f"malformed SHA256SUMS row {number}")
        digest, raw_path = match.groups()
        path = _manifest_relative_path(raw_path).as_posix()
        if path == "SHA256SUMS":
            raise RemediationError("SHA256SUMS must not list itself")
        if path in rows:
            raise RemediationError(f"duplicate SHA256SUMS path: {path}")
        rows[path] = digest
    if not rows:
        raise RemediationError("SHA256SUMS is empty")
    run_manifest_rel = "manifests/run-manifest.json"
    if run_manifest_rel not in rows:
        raise RemediationError("SHA256SUMS lacks the run manifest")
    for relative, expected in rows.items():
        path = run_root.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink() or not path.is_file():
            raise RemediationError(f"SHA256SUMS entry is missing/nonregular: {relative}")
        actual = _sha256_file(path)
        if actual != expected:
            raise RemediationError(
                f"SHA256SUMS digest mismatch for {relative}: expected {expected}, found {actual}"
            )
    run_manifest_payload = _read_regular(
        run_root / run_manifest_rel,
        run_manifest_rel,
    )
    assert run_manifest_payload is not None
    run_manifest = _load_json_bytes(run_manifest_payload, run_manifest_rel)
    declared = run_manifest.get("sha256_manifest_paths") if isinstance(run_manifest, dict) else None
    if (
        not isinstance(declared, list)
        or not all(isinstance(item, str) for item in declared)
        or declared != sorted(set(declared))
    ):
        raise RemediationError("run manifest has an invalid SHA256 artifact allowlist")
    for item in declared:
        _manifest_relative_path(item)
    if set(declared) != set(rows):
        raise RemediationError("SHA256SUMS does not match the run-manifest artifact allowlist")
    on_disk = _artifact_files_on_disk(run_root)
    if on_disk != set(declared):
        raise RemediationError(
            "run-root artifact set is incomplete or has extras: "
            f"missing={sorted(set(declared) - on_disk)}, "
            f"extra={sorted(on_disk - set(declared))}"
        )
    return run_manifest


def _validate_remediation_inputs(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != "g012-remediation-inputs/v1":
        raise RemediationError("invalid remediation-inputs schema")
    for key, pattern in (
        ("expected_absent_blob_oids", OID_RE),
        ("expected_absent_sha256", SHA256_RE),
        ("guarded_path_blob_oids", OID_RE),
    ):
        rows = value.get(key)
        if (
            not isinstance(rows, list)
            or not all(isinstance(item, str) and pattern.fullmatch(item) for item in rows)
            or rows != sorted(set(rows))
        ):
            raise RemediationError(f"invalid remediation-inputs field: {key}")
    paths = value.get("guarded_historical_paths")
    if (
        not isinstance(paths, list)
        or not all(isinstance(item, str) and _safe_repo_path(item) == item for item in paths)
        or paths != sorted(set(paths))
    ):
        raise RemediationError("invalid guarded historical path inputs")
    return value


def _dry_run_with_sealed_tool(
    args: argparse.Namespace,
    layout: RepositoryLayout,
    run_root_anchor: RunRootAnchor,
    tool: SealedFilterRepoTool,
) -> dict[str, Any]:
    run_root_anchor.descriptor_revalidate("dry-run held run root")
    run_root = run_root_anchor.command_path
    layout.revalidate("dry-run start")
    source = layout
    manifests = run_root / "manifests"
    before = _source_state(layout)
    _write_json(manifests / "source-state-before.json", before)
    layout.revalidate("before canonical authority reads")
    policy = _derive_policy(layout)
    layout.revalidate("after canonical authority reads")
    _write_json(manifests / "policy.json", policy)
    g007 = _preserve_g007_archive(
        layout.source, args.g007_archive, run_root, policy
    )

    mirror = run_root / "disposable-mirror.git"
    rollback_bundle = run_root / "rollback-before.bundle"
    rollback_evidence_bundle = run_root / "rollback-evidence-before.bundle"
    source_refs = _refs(source)
    _validate_ref_roots(source, source_refs)
    layout.revalidate("before anchored source clone")
    _clone_mirror(source, mirror)
    layout.revalidate("after anchored source clone")
    _synchronize_hidden_source_refs(source, mirror, source_refs)
    initial_mirror_refs = _refs(mirror)
    _require_exact_refs(
        source_refs,
        initial_mirror_refs,
        "initial local mirror (including transfer.hideRefs refs)",
    )
    pseudorefs = _capture_pseudorefs(source, mirror)
    _materialize_mirror_objects(mirror)
    _assert_roots_accounted(mirror)
    all_refs_before = _refs(mirror)
    refs_before = _publishable_refs(all_refs_before)
    evidence_refs_before = _evidence_refs(all_refs_before)
    _require_exact_refs(source_refs, refs_before, "publishable refs before rewrite")
    _validate_ref_roots(mirror, all_refs_before)
    _write_refs(run_root / "refs-before.tsv", refs_before)
    _write_refs(run_root / "evidence-refs-before.tsv", evidence_refs_before)
    _reject_prohibited_metadata(
        mirror, [row["ref"] for row in all_refs_before], policy
    )
    _bundle(mirror, rollback_bundle, [row["ref"] for row in refs_before])
    _verify_bundle_restoration(
        rollback_bundle,
        refs_before,
        "rollback bundle restoration",
    )
    _bundle(
        mirror,
        rollback_evidence_bundle,
        [row["ref"] for row in evidence_refs_before],
    )
    _verify_bundle_restoration(
        rollback_evidence_bundle,
        evidence_refs_before,
        "rollback evidence bundle restoration",
    )
    _remove_remote_configuration(mirror)

    historical_paths, guarded_blob_oids = _historical_guard_inventory(mirror, policy)
    bad_paths = [path for path in historical_paths if _is_guarded_path(path, policy)]
    pre_blob_scan = _scan_reachable_blobs(
        mirror, [row["ref"] for row in all_refs_before], policy
    )
    pre_blob_by_oid = {row["oid"]: row for row in pre_blob_scan}
    strip_ids = sorted(
        set(guarded_blob_oids)
        | {
            row["oid"]
            for row in pre_blob_scan
            if row["deny_hash_match"] or row["prohibited_content_match"]
        }
    )
    missing_guarded_blobs = sorted(set(guarded_blob_oids) - set(pre_blob_by_oid))
    if missing_guarded_blobs:
        raise RemediationError(
            f"guarded historical blobs were not reachable/accounted: {missing_guarded_blobs}"
        )
    remediation = _validate_remediation_inputs({
        "schema": "g012-remediation-inputs/v1",
        "captured_pseudorefs": pseudorefs,
        "guarded_historical_paths": bad_paths,
        "guarded_path_blob_oids": guarded_blob_oids,
        "expected_absent_blob_oids": strip_ids,
        "expected_absent_sha256": sorted(
            {pre_blob_by_oid[oid]["sha256"] for oid in strip_ids}
        ),
    })
    _write_json(manifests / "remediation-inputs.json", remediation)
    strip_ids_path = manifests / "strip-blob-ids.txt"
    _secure_create_output(
        strip_ids_path,
        "".join(f"{oid}\n" for oid in strip_ids).encode("ascii"),
        "git-filter-repo strip blob IDs",
    )
    _write_json(
        manifests / "before-scan.json",
        {
            "historical_path_count": len(historical_paths),
            "guarded_paths": bad_paths,
            "reachable_blob_count": len(pre_blob_scan),
            "strip_blob_count": len(strip_ids),
            "strip_blobs": [
                {
                    **pre_blob_by_oid[oid],
                    "guarded_path_blob": oid in set(guarded_blob_oids),
                }
                for oid in strip_ids
            ],
        },
    )
    command = _invoke_filter_repo(tool, mirror, policy, bad_paths, strip_ids_path)
    _restore_symbolic_refs(
        mirror, source_refs, "rewritten mirror symbolic refs"
    )
    copied_maps = _copy_filter_repo_maps(mirror, manifests)
    for required_map in ("filter-repo-commit-map.txt", "filter-repo-ref-map.txt"):
        if required_map not in copied_maps:
            raise RemediationError(
                f"git-filter-repo did not produce required mapping evidence: {required_map}"
            )
    removed_refs = _delete_rewrite_refs(mirror)
    _git(mirror, "reflog", "expire", "--expire=now", "--all")
    _git(mirror, "gc", "--prune=now")

    all_refs_after = _refs(mirror)
    refs_after = _publishable_refs(all_refs_after)
    evidence_refs_after = _evidence_refs(all_refs_after)
    _write_refs(run_root / "refs-after.tsv", refs_after)
    _write_refs(run_root / "evidence-refs-after.tsv", evidence_refs_after)
    cleaned_object_inventory = _establish_cleaned_object_inventory(
        mirror,
        refs_after,
        evidence_refs_after,
    )
    _write_json(
        manifests / "cleaned-object-inventory.json",
        cleaned_object_inventory,
    )
    before_by_ref = _ref_oid_map(all_refs_before)
    after_by_ref = _ref_oid_map(all_refs_after)
    ref_map = [
        {
            "ref": ref,
            "old_oid": before_by_ref.get(ref),
            "new_oid": after_by_ref.get(ref),
            "status": (
                "deleted"
                if ref not in after_by_ref
                else "unchanged"
                if before_by_ref.get(ref) == after_by_ref[ref]
                else "rewritten"
            ),
        }
        for ref in sorted(set(before_by_ref) | set(after_by_ref))
    ]
    _write_json(manifests / "ref-map.json", ref_map)

    _reject_internal_symlinks(mirror)
    mirror_verification = _verify_repository(
        mirror, policy, "rewritten-mirror", remediation
    )
    if not mirror_verification["ok"]:
        _write_json(manifests / "verification.json", mirror_verification)
        raise RemediationError("rewritten mirror failed policy verification")

    independent = run_root / "independent-sanitized.git"
    _clone_mirror(mirror, independent)
    _remove_remote_configuration(independent)
    _restore_symbolic_refs(
        independent, all_refs_after, "independent mirror clone"
    )
    _require_exact_refs(all_refs_after, _refs(independent), "independent mirror clone")
    _verify_cleaned_object_scope(
        independent,
        all_refs_after,
        cleaned_object_inventory["combined"],
        "independent sanitized clone",
    )
    _reject_internal_symlinks(independent)
    independent_verification = _verify_repository(
        independent, policy, "independent-sanitized-clone", remediation
    )
    if not independent_verification["ok"]:
        _write_json(manifests / "verification.json", independent_verification)
        raise RemediationError("independent sanitized clone failed verification")

    rewritten_bundle = run_root / "rewritten-sanitized.bundle"
    rewritten_evidence_bundle = run_root / "rewritten-evidence.bundle"
    _bundle(mirror, rewritten_bundle, [row["ref"] for row in refs_after])
    _verify_bundle_restoration(
        rewritten_bundle,
        refs_after,
        "rewritten bundle restoration",
        cleaned_object_inventory["publishable"],
    )
    _bundle(
        mirror,
        rewritten_evidence_bundle,
        [row["ref"] for row in evidence_refs_after],
    )
    _verify_bundle_restoration(
        rewritten_evidence_bundle,
        evidence_refs_after,
        "rewritten evidence bundle restoration",
        cleaned_object_inventory["evidence"],
    )
    after = _source_state(layout)
    _write_json(manifests / "source-state-after.json", after)
    if before["guard_sha256"] != after["guard_sha256"]:
        raise RemediationError("source mutation guard failed: source Git state changed")

    verification = {
        "ok": True,
        "source_mutation_guard": "pass",
        "rewritten_mirror": mirror_verification,
        "independent_sanitized_clone": independent_verification,
    }
    _write_json(manifests / "verification.json", verification)
    manifest = {
        "schema": "g012-history-remediation-dry-run/v1",
        "completed": True,
        "source": str(layout.source),
        "run_root": str(run_root_anchor.original_path),
        "filter_repo": {
            "supplied_path": str(tool.supplied_path),
            "evidence_path": tool.evidence_path.relative_to(run_root).as_posix(),
            "execution_source": "sealed memfd via /proc/self/fd",
            "evidence_substitution_detected": tool.evidence_substitution_detected,
            "sha256": tool.sha256,
            "official_expected_sha256": EXPECTED_FILTER_REPO_SHA256,
        },
        "rewrite_invocation": {
            "program": (
                "trusted Python interpreter reading a sealed, inherited "
                "git-filter-repo memfd"
            ),
            "arguments": command[2:],
            "network_allowed": False,
            "push_performed": False,
        },
        "publishable_ref_count_before": len(refs_before),
        "publishable_ref_count_after": len(refs_after),
        "synthetic_evidence_ref_count_before": len(evidence_refs_before),
        "synthetic_evidence_ref_count_after": len(evidence_refs_after),
        "synthetic_evidence_refs_publishable": False,
        "symbolic_ref_count_after": sum(
            1 for row in all_refs_after if row["symref"]
        ),
        "bundle_symbolic_refs_require_refs_tsv_restoration": True,
        "guarded_path_count": len(bad_paths),
        "stripped_blob_count": len(strip_ids),
        "removed_rewrite_refs": removed_refs,
        "filter_repo_mapping_files": copied_maps,
        "g007_clean_room_archive": g007,
        "nonclaims": policy["nonclaims"],
    }
    _write_documents(run_root, manifest)
    manifest_listing = _descriptor_tree_listing(
        manifests,
        "G012 manifests",
        reject_symlinks=True,
        symlink_error="symlinked manifest path is forbidden",
    )
    if any(
        row["kind"] != "file" or "/" in row["path"]
        for row in manifest_listing
    ):
        raise RemediationError(
            "G012 manifests directory must contain only regular top-level files"
        )
    hash_paths = [
        rollback_bundle,
        rollback_evidence_bundle,
        rewritten_bundle,
        rewritten_evidence_bundle,
        run_root / "refs-before.tsv",
        run_root / "refs-after.tsv",
        run_root / "evidence-refs-before.tsv",
        run_root / "evidence-refs-after.tsv",
        tool.evidence_path,
        run_root / "VERIFYING.md",
        run_root / "FORCE-PUSH-RUNBOOK.md",
        run_root / "COLLABORATOR-RECOVERY.md",
        *(manifests / row["path"] for row in manifest_listing),
    ]
    if g007["available"]:
        hash_paths.append(run_root / g007["preserved_path"])
    run_manifest_path = manifests / "run-manifest.json"
    hash_paths.append(run_manifest_path)
    manifest["sha256_manifest_paths"] = sorted(
        path.relative_to(run_root).as_posix() for path in hash_paths
    )
    _write_json(run_manifest_path, manifest)
    _sha_manifest(run_root, hash_paths)
    return manifest


def dry_run(
    args: argparse.Namespace,
    layout: RepositoryLayout | None = None,
    run_root_anchor: RunRootAnchor | None = None,
) -> dict[str, Any]:
    owns_layout = layout is None
    owns_run_root = run_root_anchor is None
    if layout is None:
        layout = _resolve_repository(args.source)
    tool: SealedFilterRepoTool | None = None
    try:
        if run_root_anchor is None:
            layout.revalidate("before run-root creation")
            run_root_anchor = _prepare_run_root(args.run_root, layout)
            layout.revalidate("after run-root creation")
        run_root_anchor.revalidate("before dry-run output creation")
        run_root = run_root_anchor.command_path
        _secure_output_directory(
            run_root / "manifests",
            "G012 manifests directory",
        )
        tool = _quarantine_filter_repo_tool(args.filter_repo_tool, run_root)
        result = _dry_run_with_sealed_tool(
            args,
            layout,
            run_root_anchor,
            tool,
        )
        run_root_anchor.revalidate("after dry-run output creation")
        return result
    finally:
        if tool is not None:
            os.close(tool.fd)
        if owns_run_root and run_root_anchor is not None:
            run_root_anchor.close()
        if owns_layout:
            layout.close()


def guarded_dry_run(args: argparse.Namespace) -> dict[str, Any]:
    """Apply an outer source guard even when a rewrite/verification step fails."""
    layout = _resolve_repository(args.source)
    run_root_anchor: RunRootAnchor | None = None
    try:
        layout.revalidate("outer dry-run guard start")
        before = _source_state(layout)
        pending_error: Exception | None = None
        result: dict[str, Any] | None = None
        try:
            layout.revalidate("outer guard before run-root creation")
            run_root_anchor = _prepare_run_root(args.run_root, layout)
            layout.revalidate("outer guard after run-root creation")
            result = dry_run(args, layout, run_root_anchor)
        except Exception as exc:
            pending_error = exc
        layout.revalidate("outer dry-run guard before final snapshot")
        after = _source_state(layout)
        layout.revalidate("outer dry-run guard end")
        if run_root_anchor is not None:
            manifests = run_root_anchor.command_path / "manifests"
            held_manifests = _open_held_directory_root(
                manifests,
                "G012 manifests after guarded dry run",
                required=False,
            )
            if held_manifests is not None:
                held_manifests.close()
                if pending_error is not None:
                    _secure_write_if_absent_or_equal(
                        manifests / "source-state-after.json",
                        _canonical_json(after),
                        "guarded dry-run source-state-after",
                    )
            run_root_anchor.revalidate("outer dry-run guard run-root end")
        if before["guard_sha256"] != after["guard_sha256"]:
            raise RemediationError("source mutation guard failed: source Git state changed")
        if pending_error is not None:
            raise pending_error
        assert result is not None
        return result
    finally:
        if run_root_anchor is not None:
            run_root_anchor.close()
        layout.close()


def _verify_g007_record(
    run_root: Path,
    policy: dict[str, Any],
    run_manifest: dict[str, Any],
) -> dict[str, Any]:
    stored = run_manifest.get("g007_clean_room_archive")
    artifact_paths = run_manifest.get("sha256_manifest_paths")
    if not isinstance(stored, dict) or not isinstance(artifact_paths, list):
        raise RemediationError("run manifest lacks strict G007 availability metadata")
    preserved_name = "preserved-g007-clean-room.zip"
    if stored.get("available") is False:
        if stored != {
            "available": False,
            "reason": "no --g007-archive was supplied",
        }:
            raise RemediationError("unavailable G007 run record is malformed")
        if preserved_name in artifact_paths:
            raise RemediationError(
                "G007 is unavailable but its preserved artifact is declared"
            )
        return stored
    expected_keys = {
        "available",
        "source_path",
        "preserved_path",
        "sha256",
        "size_bytes",
        "profile_id",
        "member_count",
        "manifest_file_count",
        "payload_file_count",
        "publication_manifest_sha256",
        "validated_with",
    }
    if set(stored) != expected_keys or stored.get("available") is not True:
        raise RemediationError("available G007 run record is malformed")
    if (
        stored.get("preserved_path") != preserved_name
        or preserved_name not in artifact_paths
        or not isinstance(stored.get("source_path"), str)
        or not Path(stored["source_path"]).is_absolute()
    ):
        raise RemediationError(
            "G007 availability and preserved artifact declaration disagree"
        )
    archive_bytes = _read_regular(
        run_root / preserved_name,
        "preserved G007 clean-room archive during verify",
        MAX_G007_ARCHIVE_BYTES,
    )
    actual = _validate_g007_archive_bytes(archive_bytes, policy)
    stored_validation = {
        key: stored[key]
        for key in actual
    }
    if stored_validation != actual:
        raise RemediationError(
            "strict G007 reverification result differs from the immutable "
            "run-manifest record"
        )
    return stored


def _verify_anchored_run_root(
    args: argparse.Namespace,
    run_root_anchor: RunRootAnchor,
) -> dict[str, Any]:
    run_root_anchor.revalidate("verify start")
    run_root = run_root_anchor.command_path
    run_manifest = _validate_sha256_manifest(run_root)
    policy_path = run_root / "manifests/policy.json"
    policy = _load_json_bytes(_read_regular(policy_path, "G012 policy"), "G012 policy")
    remediation_path = run_root / "manifests/remediation-inputs.json"
    remediation = _validate_remediation_inputs(
        _load_json_bytes(
            _read_regular(remediation_path, "G012 remediation inputs"),
            "G012 remediation inputs",
        )
    )
    cleaned_object_inventory = _validate_cleaned_object_inventory(
        _load_json_bytes(
            _read_regular(
                run_root / "manifests/cleaned-object-inventory.json",
                "cleaned logical object inventory",
            ),
            "cleaned logical object inventory",
        )
    )
    if run_manifest.get("completed") is not True:
        raise RemediationError("stored G012 run manifest is not complete")
    g007_verification = _verify_g007_record(run_root, policy, run_manifest)
    evidence_tool = run_root.joinpath(
        *_manifest_relative_path(
            run_manifest.get("filter_repo", {}).get("evidence_path")
        ).parts
    )
    _verify_tool_evidence(evidence_tool)
    mirror = run_root / "disposable-mirror.git"
    independent = run_root / "independent-sanitized.git"
    _reject_internal_symlinks(mirror)
    _reject_internal_symlinks(independent)
    refs_before = _read_refs(run_root / "refs-before.tsv")
    refs_after = _read_refs(run_root / "refs-after.tsv")
    evidence_before = _read_refs(run_root / "evidence-refs-before.tsv")
    evidence_after = _read_refs(run_root / "evidence-refs-after.tsv")
    if any(
        row["ref"].startswith(SYNTHETIC_EVIDENCE_REF_PREFIX)
        for row in [*refs_before, *refs_after]
    ):
        raise RemediationError("publishable ref TSV contains synthetic evidence refs")
    if any(
        not row["ref"].startswith(SYNTHETIC_EVIDENCE_REF_PREFIX)
        for row in [*evidence_before, *evidence_after]
    ):
        raise RemediationError("evidence ref TSV contains publishable refs")
    expected_all_after = sorted(
        [*refs_after, *evidence_after], key=lambda row: row["ref"]
    )
    _require_exact_refs(expected_all_after, _refs(mirror), "rewritten mirror")
    _require_exact_refs(expected_all_after, _refs(independent), "independent clone")
    _verify_cleaned_object_scope(
        mirror,
        expected_all_after,
        cleaned_object_inventory["combined"],
        "rewritten mirror",
    )
    _verify_cleaned_object_scope(
        independent,
        expected_all_after,
        cleaned_object_inventory["combined"],
        "independent clone",
    )
    for bundle_name in (
        "rollback-before.bundle",
        "rollback-evidence-before.bundle",
        "rewritten-sanitized.bundle",
        "rewritten-evidence.bundle",
    ):
        _git(mirror, "bundle", "verify", str(run_root / bundle_name))
    stored_verification = _load_json_bytes(
        _read_regular(
            run_root / "manifests/verification.json",
            "stored verification manifest",
        ),
        "stored verification manifest",
    )
    results = [
        _verify_repository(
            mirror,
            policy,
            "rewritten-mirror",
            remediation,
        ),
        _verify_repository(
            independent,
            policy,
            "independent-sanitized-clone",
            remediation,
        ),
    ]
    stored_by_label = {
        stored_verification["rewritten_mirror"]["label"]: stored_verification[
            "rewritten_mirror"
        ],
        stored_verification["independent_sanitized_clone"]["label"]: stored_verification[
            "independent_sanitized_clone"
        ],
    }
    for row in results:
        stored = stored_by_label.get(row["label"])
        if not isinstance(stored, dict):
            raise RemediationError(f"stored canonical inventory lacks {row['label']}")
        if (
            stored.get("refs") != row["refs"]
            or stored.get("object_inventory") != row["object_inventory"]
        ):
            raise RemediationError(
                f"canonical ref/object inventory changed for {row['label']}"
            )
    with tempfile.TemporaryDirectory(prefix="g012-verify-bundles-") as temporary:
        temporary_root = Path(temporary)
        rewritten_restore = temporary_root / "rewritten.git"
        _clone_bundle(run_root / "rewritten-sanitized.bundle", rewritten_restore)
        _reject_internal_symlinks(rewritten_restore)
        _restore_symbolic_refs(
            rewritten_restore,
            refs_after,
            "fresh rewritten bundle restoration",
        )
        _require_exact_refs(
            refs_after,
            _refs(rewritten_restore),
            "fresh rewritten bundle restoration",
        )
        _verify_cleaned_object_scope(
            rewritten_restore,
            refs_after,
            cleaned_object_inventory["publishable"],
            "fresh rewritten bundle restoration",
        )
        _git(rewritten_restore, "fsck", "--full", "--strict")
        evidence_restore = temporary_root / "evidence.git"
        _clone_bundle(run_root / "rewritten-evidence.bundle", evidence_restore)
        _reject_internal_symlinks(evidence_restore)
        _restore_symbolic_refs(
            evidence_restore,
            evidence_after,
            "fresh rewritten evidence bundle restoration",
        )
        _require_exact_refs(
            evidence_after,
            _refs(evidence_restore),
            "fresh rewritten evidence bundle restoration",
        )
        _verify_cleaned_object_scope(
            evidence_restore,
            evidence_after,
            cleaned_object_inventory["evidence"],
            "fresh rewritten evidence bundle restoration",
        )
        _git(evidence_restore, "fsck", "--full", "--strict")
        rollback_restore = temporary_root / "rollback.git"
        _clone_bundle(run_root / "rollback-before.bundle", rollback_restore)
        _reject_internal_symlinks(rollback_restore)
        _restore_symbolic_refs(
            rollback_restore,
            refs_before,
            "fresh rollback bundle restoration",
        )
        _require_exact_refs(
            refs_before,
            _refs(rollback_restore),
            "fresh rollback bundle restoration",
        )
        _git(rollback_restore, "fsck", "--full", "--strict")
    result = {
        "ok": all(row["ok"] for row in results),
        "repositories": results,
        "g007_clean_room_archive": g007_verification,
    }
    if not result["ok"]:
        raise RemediationError(
            "G012 reverification found prohibited history: "
            + json.dumps(result, sort_keys=True)
        )
    run_root_anchor.revalidate("verify end")
    return result


def verify(args: argparse.Namespace) -> dict[str, Any]:
    anchor = _anchor_existing_run_root(args.run_root)
    try:
        return _verify_anchored_run_root(args, anchor)
    finally:
        anchor.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local-only, source-independent G012 public-history remediation dry run"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry = subparsers.add_parser("dry-run")
    dry.add_argument("--source", required=True)
    dry.add_argument("--run-root", required=True)
    dry.add_argument("--filter-repo-tool", required=True)
    dry.add_argument("--g007-archive")
    check = subparsers.add_parser("verify")
    check.add_argument("--run-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = guarded_dry_run(args) if args.command == "dry-run" else verify(args)
    except (RemediationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
