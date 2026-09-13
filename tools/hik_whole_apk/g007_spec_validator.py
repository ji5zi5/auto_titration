#!/usr/bin/env python3
"""Validate the G007 source-independent publication candidate.

This validator is intentionally separate from the legacy G003 dossier validator
and from the final critic gate.  It accepts an authored, publication-ready
candidate with G008 execution still pending, and rejects artifacts that try to
turn pending traceability into terminal/live/radiometric proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

RESEARCH_REL = Path(".omx/research/hikmicro-viewer-2.6.0")
G007_REL = RESEARCH_REL / "specs/g007"
FIXTURE_REL = RESEARCH_REL / "reproduction/g007-fixtures-manifest.json"
G007_REVIEW_INDEX_REL = RESEARCH_REL / "reviews/g007-index.json"
DOSSIER_IDS = tuple(f"D{i:02d}" for i in range(1, 14))
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CLAIM_RE = re.compile(r"^CLM-G003-D(0[1-9]|1[0-3])-[A-F0-9]{16}$")
EVB_RE = re.compile(r"^EVB-G00[2-7]-[A-Z0-9._-]+$")
SPEC_RE = re.compile(r"^SPEC-G003-D(0[1-9]|1[0-3])-[A-F0-9]{12}$")
RPRO_RE = re.compile(r"^RPRO-G003-D(0[1-9]|1[0-3])-[A-F0-9]{12}$")
SOURCE_CONTRACT_RE = re.compile(r"^(?:CONTRACT|SIC)-G003-D(0[1-9]|1[0-3])-[A-Z0-9._-]+$")
CONTRACT_RE = re.compile(r"^CONTRACT-G007-D(0[1-9]|1[0-3])-PUBLICATION$")
AT_RE = re.compile(r"^AT-G007-D(0[1-9]|1[0-3])-[A-F0-9]{12}$")
FIX_RE = re.compile(r"^FIX-G007-D(0[1-9]|1[0-3])-DEFINITION$")
UNKNOWN_RE = re.compile(r"^UNK-G003-D(0[1-9]|1[0-3])-[A-Z0-9._-]+$")
ASSERT_RE = re.compile(r"^ASSERT-G007-D(0[1-9]|1[0-3])-[A-F0-9]{12}-[A-Z0-9._-]+$")
RUN_RE = re.compile(r"^RUN-[A-Z0-9][A-Z0-9._-]*$")

PROHIBITED_SOURCE_RE = re.compile(
    r"(?is)(\bjadx\b|\bsmali\b|\binvoke-(?:virtual|static|direct)\b|\.method\s|\.class\s|"
    r"package\s+com\.hik|source[-_ ]?(?:body|excerpt|listing)|copied\s+(?:source|code|control[-_ ]?flow)|"
    r"control[-_ ]?flow\s+(?:excerpt|listing|copy)|decompil(?:ed|er|ation))"
)
TERMINAL_CLAIM_RE = re.compile(
    r"(?is)(\bpassed\b|\bsuccess(?:ful)?\b|\bverified\b|\bcompleted\b|\bterminal\b|\bapproved\b|\bgreen\b|\bproof\b|\bresult\b)"
)
LIVE_CLAIM_RE = re.compile(r"(?is)(?<![A-Za-z0-9_])(live\s+f2|hardware(?:\s+run|\s+evidence)?|radiometric|celsius|°c|degc)(?![A-Za-z0-9_])")
SUBJECT_BOUND_NONTERMINAL_RE = re.compile(
    r"(?is)(?:"
    r"\bG008\s+execution\s+fields\s+pending\b"
    r"|"
    r"\b(?:no|not|without)\b[^.!?\n]{0,120}"
    r"(?:live\s+f2|hardware(?:\s+(?:run|runs|result|results|evidence|bundle|bundles))?|radiometric|calibrated\s+celsius|celsius|°c|degc|"
    r"standalone\s+F2|F2(?:[^.!?\n]{0,50}\b(?:execution|run|runs|result|results|evidence|bundle|bundles)\b)?|"
    r"E4\s*/\s*E5|E4\s+or\s+E5|E4\s+and\s+E5|E4/E5|E4|E5|G008)"
    r"[^.!?\n]{0,120}\b(?:claimed|claim|verified|passed|approved|completed|successful|green|proof|terminal|result|results)\b"
    r"|(?:live\s+f2|hardware(?:\s+(?:run|runs|result|results|evidence|bundle|bundles))?|radiometric|calibrated\s+celsius|celsius|°c|degc|"
    r"standalone\s+F2|F2[^.!?\n]{0,50}\b(?:execution|run|runs|result|results|evidence|bundle|bundles)\b|"
    r"E4(?:\s*/\s*E5|\s+or\s+E5|\s+and\s+E5|/E5)?[^.!?\n]{0,50}\b(?:run|runs|result|results|evidence|bundle|bundles)\b|"
    r"E5[^.!?\n]{0,50}\b(?:run|runs|result|results|evidence|bundle|bundles)\b|"
    r"G008(?:[^.!?\n]{0,50}\b(?:execution|run|runs|result|results|evidence|bundle|bundles)\b)?)"
    r"[^.!?\n]{0,80}\b(?:is|are|remains|remain|stays|stay|keeps|keep)\b[^.!?\n]{0,30}\b(?:pending|nonterminal|null|empty|not\s+claimed|not\s+verified|not\s+passed|not\s+approved|not\s+completed)\b"
    r"|(?:live\s+f2|hardware(?:\s+(?:run|runs|result|results|evidence|bundle|bundles))?|radiometric|calibrated\s+celsius|celsius|°c|degc|"
    r"standalone\s+F2|F2[^.!?\n]{0,50}\b(?:execution|run|runs|result|results|evidence|bundle|bundles)\b|"
    r"E4(?:\s*/\s*E5|\s+or\s+E5|\s+and\s+E5|/E5)?[^.!?\n]{0,50}\b(?:run|runs|result|results|evidence|bundle|bundles)\b|"
    r"E5[^.!?\n]{0,50}\b(?:run|runs|result|results|evidence|bundle|bundles)\b|"
    r"G008(?:[^.!?\n]{0,50}\b(?:execution|run|runs|result|results|evidence|bundle|bundles)\b)?)"
    r"[^.!?\n]{0,80}\b(?:is|are)?\s*not\s+(?:claimed|verified|passed|approved|completed|successful|green)\b"
    r")"
)
DIRECT_FAKE_LIVE_RE = re.compile(
    r"(?is)(?<![A-Za-z0-9_])(?:live\s+f2|hardware(?:\s+run|\s+evidence)?|radiometric|calibrated\s+celsius|celsius|°c|degc)(?![A-Za-z0-9_])"
    r"[^.!?\\n]{0,40}(?:passed|success(?:ful)?|verified|completed|approved|green|proof|result)"
)
FAKE_TERMINAL_SUBJECTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "live/F2/hardware/radiometric/Celsius",
        LIVE_CLAIM_RE,
    ),
    (
        "standalone F2 result",
        re.compile(
            r"(?is)(?<![A-Za-z0-9_])(?:standalone\s+F2|F2\s+(?:execution|run|runs|result|results|evidence|bundle|bundles))(?![A-Za-z0-9_])"
        ),
    ),
    (
        "E4/E5 result/evidence bundle",
        re.compile(
            r"(?is)(?<![A-Za-z0-9_-])(?:E4\s*/\s*E5|E4\s+or\s+E5|E4\s+and\s+E5|E4/E5|E4|E5)(?![A-Za-z0-9_-])"
            r"[^.!?\\n]{0,80}\b(?:run|runs|result|results|evidence|bundle|bundles)\b|"
            r"\b(?:run|runs|result|results|evidence|bundle|bundles)\b[^.!?\\n]{0,80}"
            r"(?<![A-Za-z0-9_-])(?:E4\s*/\s*E5|E4\s+or\s+E5|E4\s+and\s+E5|E4/E5|E4|E5)(?![A-Za-z0-9_-])"
        ),
    ),
    (
        "G008 execution/run/result/evidence",
        re.compile(
            r"(?is)(?<![A-Za-z0-9_])G008(?![A-Za-z0-9_])[^.!?\\n]{0,80}\b(?:execution|run|runs|result|results|evidence|bundle|bundles)\b|"
            r"\b(?:execution|run|runs|result|results|evidence|bundle|bundles)\b[^.!?\\n]{0,80}(?<![A-Za-z0-9_])G008(?![A-Za-z0-9_])"
        ),
    ),
)
REVIEW_SCHEMA_KEYS = {
    "schema_version",
    "schema",
    "review_id",
    "reviewer_id",
    "reviewer_role",
    "independent_from_author_id",
    "independent_from_producers",
    "subject_specification_id",
    "subject_artifact_hashes",
    "covered_contract_ids",
    "covered_acceptance_test_ids",
    "covered_fixture_ids",
    "checks",
    "verdict",
    "passed",
    "reviewed_at",
}
REVIEW_CHECK_KEYS = {
    "source_independence",
    "no_decompiler_or_source_body_leakage",
    "no_terminal_live_f2_radiometric_or_celsius_claims",
    "authority_traceability",
    "artifact_hashes_match_indexed_subjects",
}
REVIEW_SUBJECT_RELS = (
    G007_REL / "index.json",
    G007_REL / "README.md",
    FIXTURE_REL,
)
PATH_KEY_RE = re.compile(r"(^|_)(path|attachment|source_path)$")


class DuplicateKeyError(ValueError):
    pass


class ValidationError(RuntimeError):
    pass


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_files: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    seen_nfc: dict[str, str] = {}
    for key, value in pairs:
        if key in out:
            raise DuplicateKeyError(f"duplicate JSON key {key!r}")
        nkey = unicodedata.normalize("NFC", key)
        if nkey in seen_nfc and seen_nfc[nkey] != key:
            raise DuplicateKeyError(f"post-NFC-colliding JSON keys {seen_nfc[nkey]!r}/{key!r}")
        seen_nfc[nkey] = key
        out[key] = value
    return out


def _split_safe_rel(raw: str | Path, label: str, *, allowed: Path | None = None) -> tuple[str, ...]:
    raw_text = raw.as_posix() if isinstance(raw, Path) else raw
    if not isinstance(raw_text, str) or not raw_text:
        raise ValidationError(f"{label} must be a non-empty relative path")
    pure = PurePosixPath(raw_text)
    if pure.is_absolute() or ".." in pure.parts or any(part in {"", "."} for part in pure.parts) or "\\" in raw_text or "\x00" in raw_text:
        raise ValidationError(f"{label} is unsafe: {raw_text!r}")
    parts = tuple(pure.parts)
    if allowed is not None:
        allowed_parts = tuple(PurePosixPath(allowed.as_posix()).parts)
        if parts[: len(allowed_parts)] != allowed_parts:
            raise ValidationError(f"{label} escapes permitted research root: {raw_text}")
    return parts


def _read_rel_bytes(root: Path, raw: str | Path, label: str, *, allowed: Path | None = RESEARCH_REL) -> tuple[bytes, os.stat_result]:
    """Read a repository-relative file without following symlink ancestors/leaves.

    The file descriptor is anchored at ``root``; every ancestor is opened with
    ``O_DIRECTORY|O_NOFOLLOW``, the leaf is opened with ``O_NOFOLLOW``, and the
    stat used by callers is taken from the same descriptor before and after the
    read to close path-swap/hash TOCTOU gaps.
    """
    parts = _split_safe_rel(raw, label, allowed=allowed)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    fd: int | None = None
    current_fd = root_fd
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current_fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValidationError(f"{label} is not a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValidationError(f"{label} changed while being read")
        return b"".join(chunks), after
    except OSError as exc:
        raise ValidationError(f"secure read failed for {raw}: {exc}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        os.close(current_fd)


def load_json(path: Path, root: Path | None = None, rel: Path | None = None) -> Any:
    try:
        if root is not None and rel is not None:
            payload = _read_rel_bytes(root, rel, rel.as_posix())[0].decode("utf-8")
        else:
            payload = path.read_text(encoding="utf-8")
        return json.loads(payload, object_pairs_hook=_pairs_no_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
        raise ValidationError(f"invalid JSON {path.as_posix()}: {exc}") from exc


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError("JSON object key is not a string")
            nkey = unicodedata.normalize("NFC", key)
            if nkey in out:
                raise ValidationError(f"post-NFC-colliding JSON key {nkey!r}")
            out[nkey] = _normalize(item)
        return out
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("non-finite JSON number")
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(_normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_file(root: Path, rel: str | Path, label: str = "artifact") -> tuple[str, int]:
    payload, st = _read_rel_bytes(root, rel, label)
    return hashlib.sha256(payload).hexdigest(), st.st_size


def exact_keys(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} is not an object")
    missing = sorted(keys - set(value))
    extra = sorted(set(value) - keys)
    if missing or extra:
        raise ValidationError(f"{label} key mismatch; missing={missing}, extra={extra}")
    return value


def string_list(value: Any, label: str, *, nonempty: bool = True, pattern: re.Pattern[str] | None = None) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValidationError(f"{label} must be {'a non-empty' if nonempty else 'an'} array")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValidationError(f"{label} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ValidationError(f"{label} contains duplicates")
    if pattern and any(not pattern.fullmatch(item) for item in value):
        raise ValidationError(f"{label} contains malformed IDs")
    if pattern and value != sorted(value):
        raise ValidationError(f"{label} must be sorted canonically")
    return value


def safe_rel(root: Path, raw: Any, label: str, *, must_exist: bool = True, allowed: Path = RESEARCH_REL) -> Path:
    parts = _split_safe_rel(raw, label, allowed=allowed)
    if must_exist:
        _read_rel_bytes(root, raw, label, allowed=allowed)
    return root.joinpath(*parts)


def scan_for_leakage(value: Any, label: str) -> None:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if PROHIBITED_SOURCE_RE.search(blob):
        raise ValidationError(f"{label} contains source-body/decompiler leakage markers")
    scan_for_fake_terminal_claims_recursive(value, label)




def _has_subject_bound_nonterminal_context(text: str) -> bool:
    return SUBJECT_BOUND_NONTERMINAL_RE.search(text) is not None


def _containing_clause(text: str, start: int, end: int) -> str:
    left = max(text.rfind(mark, 0, start) for mark in ".!?\n") + 1
    rights = [pos for mark in ".!?\n" if (pos := text.find(mark, end)) != -1]
    right = min(rights) if rights else len(text)
    return text[left:right]


_PAIR_MAX_GAP = 120
_HARD_PAIR_SEPARATOR_RE = re.compile(r"[.!?\n;,]")
_EXPLICIT_LEADING_NEGATION_RE = re.compile(r"(?is)\b(?:no|not|without)\b")
_MAJOR_LEADING_NEGATION_RE = re.compile(r"(?is)\b(?:no|without)\b")
_CLAIM_WORD_RE = re.compile(r"(?is)\b(?:claims?|claimed)\b")
_PAIR_TAIL_NONTERMINAL_RE = re.compile(
    r"(?is)^\s*"
    r"(?:execution|run|runs|result|results|evidence|bundle|bundles|hardware|radiometric|celsius|calibrated|F2|E4|E5|G008|fields|field|/|and|or|\s){0,80}"
    r"(?:"
    r"(?:is|are|remains|remain|stays|stay|keeps|keep)?\s*"
    r"(?:pending|nonterminal|null|empty)\b"
    r"|(?:is|are)?\s*not\s+(?:claimed|verified|passed|approved|completed|successful|green)\b"
    r"|(?:is|are)?\s*not\s+claimed\b"
    r")"
)
_PAIR_INFIX_NONTERMINAL_RE = re.compile(
    r"(?is)(?:"
    r"(?:is|are|remains|remain|stays|stay|keeps|keep)?\s*(?:pending|nonterminal|null|empty)\b"
    r"|(?:is|are)?\s*not\s+(?:claimed|verified|passed|approved|completed|successful|green)\b"
    r"|(?:is|are)?\s*not\s+claimed\b"
    r")"
)


def _has_hard_pair_separator(text: str) -> bool:
    return _HARD_PAIR_SEPARATOR_RE.search(text) is not None


def _is_terminal_inside_subject_noun(terminal: re.Match[str], subject: re.Match[str]) -> bool:
    """Ignore terminal words that are part of the subject phrase itself.

    Phrases such as ``E4 result bundle remains pending`` contain the word
    ``result`` inside the subject descriptor.  Treating that noun as the
    terminal claim would make truthful pending wording fail before the scanner
    reaches the pair-local nonterminal tail.  Terminal verbs/adjectives outside
    the subject span (``verified``, ``passed``, ``green``, etc.) remain checked.
    """
    if not (subject.start() <= terminal.start() and terminal.end() <= subject.end()):
        return False
    word = terminal.group(0).lower()
    return word in {"result", "results"}


def _pair_has_bound_nonterminal_context(clause: str, subject: re.Match[str], terminal: re.Match[str]) -> bool:
    pair_start = min(subject.start(), terminal.start())
    pair_end = max(subject.end(), terminal.end())
    prefix = clause[:pair_start]
    tail = clause[pair_end:]
    local_prefix_start = max((prefix.rfind(mark) for mark in ".!?\n;,"), default=-1) + 1
    major_prefix_start = max((prefix.rfind(mark) for mark in ".!?\n;"), default=-1) + 1
    local_prefix = prefix[local_prefix_start:]
    major_prefix = prefix[major_prefix_start:]
    if _EXPLICIT_LEADING_NEGATION_RE.search(local_prefix) is not None:
        return True
    major_negation = _MAJOR_LEADING_NEGATION_RE.search(major_prefix)
    if major_negation is not None:
        major_to_local = major_prefix[major_negation.end() : local_prefix_start - major_prefix_start]
        if _CLAIM_WORD_RE.search(major_to_local) is None:
            return True
    if _PAIR_TAIL_NONTERMINAL_RE.search(tail) is not None:
        return True
    if subject.end() <= terminal.start():
        infix = clause[subject.end() : terminal.start()]
        return _PAIR_INFIX_NONTERMINAL_RE.search(infix) is not None
    return False


def _iter_unnegated_terminal_subject_pairs(
    clause: str,
    subject_re: re.Pattern[str],
) -> list[tuple[re.Match[str], re.Match[str]]]:
    subjects = list(subject_re.finditer(clause))
    terminals = list(TERMINAL_CLAIM_RE.finditer(clause))
    unnegated: list[tuple[re.Match[str], re.Match[str]]] = []
    for subject in subjects:
        for terminal in terminals:
            if _is_terminal_inside_subject_noun(terminal, subject):
                continue
            between = clause[min(subject.end(), terminal.end()) : max(subject.start(), terminal.start())]
            if len(between) > _PAIR_MAX_GAP or _has_hard_pair_separator(between):
                continue
            if not _pair_has_bound_nonterminal_context(clause, subject, terminal):
                unnegated.append((subject, terminal))
    return unnegated


def scan_for_fake_terminal_claims(text: str, label: str) -> None:
    for subject_name, subject_re in FAKE_TERMINAL_SUBJECTS:
        for idx, match in enumerate(subject_re.finditer(text)):
            clause = _containing_clause(text, match.start(), match.end())
            pairs = _iter_unnegated_terminal_subject_pairs(clause, subject_re)
            if pairs:
                raise ValidationError(f"{label} contains explicit fake terminal {subject_name} claim near segment {idx}")

def scan_for_fake_terminal_claims_recursive(value: Any, label: str) -> None:
    if isinstance(value, str):
        scan_for_fake_terminal_claims(value, label)
    elif isinstance(value, dict):
        for key, item in value.items():
            scan_for_fake_terminal_claims(str(key), f"{label}.{key} key")
            scan_for_fake_terminal_claims_recursive(item, f"{label}.{key}")
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            scan_for_fake_terminal_claims_recursive(item, f"{label}[{idx}]")


def scan_paths(root: Path, value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and PATH_KEY_RE.search(key) and item:
                safe_rel(root, item, f"{label}.{key}", must_exist=key != "result_attachment")
            else:
                scan_paths(root, item, f"{label}.{key}")
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            scan_paths(root, item, f"{label}[{idx}]")


class G007SpecValidator:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.result = ValidationResult()
        self.artifact_set_id = ""
        self.claim_ids: set[str] = set()
        self.evidence_ids: set[str] = set()
        self.spec_ids: set[str] = set()
        self.repro_ids: set[str] = set()
        self.unknown_ids_by_dossier: dict[str, set[str]] = {}
        self.source_contract_ids_by_dossier: dict[str, set[str]] = {}
        self.fixture_ids: set[str] = set()
        self.index_counts: dict[str, int] = {}
        self.index_approved = False
        self.index_review_id: str | None = None
        self.review_paths: set[str] = set()
        self.fixture_approved = False
        self.fixture_review_id: str | None = None

    def validate(self) -> ValidationResult:
        try:
            self._load_authority_indexes()
            index = self._load_required_json(G007_REL / "index.json")
            fixtures = self._load_required_json(FIXTURE_REL)
            status = self._load_required_json(G007_REL / "status.json")
            readme_bytes, _ = _read_rel_bytes(self.root, G007_REL / "README.md", "G007 README.md")
            readme_text = readme_bytes.decode("utf-8")
            if not readme_text.strip():
                raise ValidationError("G007 README.md is missing or empty")
            self.result.checked_files.add(str(G007_REL / "README.md"))
            self._scan_public_g007_artifacts()
            self._validate_fixture_manifest(fixtures)
            self._validate_index(index)
            self._validate_status(status)
            scan_for_leakage(index, "G007 index")
            scan_for_leakage(fixtures, "G007 fixture manifest")
            scan_for_leakage(status, "G007 status")
            scan_for_fake_terminal_claims(readme_text, "G007 README.md")
            scan_paths(self.root, index, "G007 index")
            scan_paths(self.root, fixtures, "G007 fixture manifest")
            scan_paths(self.root, status, "G007 status")
        except ValidationError as exc:
            self.result.error("g007", str(exc))
        return self.result

    def _load_required_json(self, rel: Path) -> Mapping[str, Any]:
        path = self.root / rel
        data = load_json(path, self.root, rel)
        if not isinstance(data, dict):
            raise ValidationError(f"{rel.as_posix()} must be a JSON object")
        self.result.checked_files.add(rel.as_posix())
        return data

    def _scan_public_g007_artifacts(self) -> None:
        for rel in self._iter_secure_tree_files(G007_REL):
            payload, _ = _read_rel_bytes(self.root, rel, rel.as_posix())
            self.result.checked_files.add(rel.as_posix())
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValidationError(f"public G007 artifact is not UTF-8 text: {rel.as_posix()}") from exc
            if PROHIBITED_SOURCE_RE.search(text):
                raise ValidationError(f"{rel.as_posix()} contains source/decompiler/copied-control-flow leakage markers")
            if rel.suffix == ".json":
                scan_for_fake_terminal_claims_recursive(load_json(self.root / rel, self.root, rel), rel.as_posix())
            else:
                scan_for_fake_terminal_claims(text, rel.as_posix())

    def _iter_secure_tree_files(self, rel_dir: Path) -> list[Path]:
        files: list[Path] = []

        def walk(dir_fd: int, rel: Path) -> None:
            for name in sorted(os.listdir(dir_fd)):
                if name in {"", ".", ".."}:
                    raise ValidationError(f"unsafe directory entry under {rel.as_posix()}: {name!r}")
                st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                child = rel / name
                if stat.S_ISLNK(st.st_mode):
                    raise ValidationError(f"public G007 artifact tree contains symlink: {child.as_posix()}")
                if stat.S_ISDIR(st.st_mode):
                    child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
                    try:
                        walk(child_fd, child)
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(st.st_mode):
                    files.append(child)
                else:
                    raise ValidationError(f"public G007 artifact tree contains non-file entry: {child.as_posix()}")

        _split_safe_rel(rel_dir, rel_dir.as_posix(), allowed=RESEARCH_REL)
        root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        current_fd = root_fd
        try:
            for part in rel_dir.parts:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            walk(current_fd, rel_dir)
        except OSError as exc:
            raise ValidationError(f"secure G007 artifact scan failed: {exc}") from exc
        finally:
            os.close(current_fd)
        return files

    def _load_authority_indexes(self) -> None:
        research = self.root / RESEARCH_REL
        dossiers = self._load_required_json(RESEARCH_REL / "dossiers/index.json")
        claims = self._load_required_json(RESEARCH_REL / "claims/index.json")
        evidence = self._load_required_json(RESEARCH_REL / "evidence/index.json")
        specs = self._load_required_json(RESEARCH_REL / "specs/index.json")
        repro = self._load_required_json(RESEARCH_REL / "reproduction/index.json")
        self.artifact_set_id = str(dossiers.get("artifact_set_id"))
        for name, data in (("claims", claims), ("evidence", evidence), ("specs", specs), ("reproduction", repro)):
            if data.get("artifact_set_id") != self.artifact_set_id:
                raise ValidationError(f"{name} index artifact_set_id mismatch")
        self.claim_ids = {str(row.get("claim_id")) for row in claims.get("claims", []) if isinstance(row, dict)}
        self.evidence_ids = {str(row.get("evidence_bundle_id")) for row in evidence.get("evidence_bundles", []) if isinstance(row, dict)}
        self.spec_ids = {str(row.get("specification_id")) for row in specs.get("specifications", []) if isinstance(row, dict)}
        self.repro_ids = {str(row.get("reproduction_id")) for row in repro.get("reproductions", []) if isinstance(row, dict)}
        dossier_rows = dossiers.get("dossiers")
        if not isinstance(dossier_rows, list) or {row.get("dossier_id") for row in dossier_rows if isinstance(row, dict)} != set(DOSSIER_IDS):
            raise ValidationError("authoritative dossier index is not exactly D01-D13")
        for dossier in DOSSIER_IDS:
            manifest_rel = RESEARCH_REL / "dossiers" / dossier / "manifest.json"
            manifest = load_json(research / "dossiers" / dossier / "manifest.json", self.root, manifest_rel)
            self.unknown_ids_by_dossier[dossier] = {str(row.get("unknown_id")) for row in manifest.get("unknowns", []) if isinstance(row, dict)}
            contracts_rel = RESEARCH_REL / "dossiers" / dossier / "source_independent_contracts.json"
            contracts = load_json(research / "dossiers" / dossier / "source_independent_contracts.json", self.root, contracts_rel)
            if not isinstance(contracts, list) or not contracts:
                raise ValidationError(f"{dossier} source_independent_contracts.json must contain authoritative contract rows")
            contract_ids: set[str] = set()
            for row in contracts:
                if not isinstance(row, dict):
                    raise ValidationError(f"{dossier} source independent contract row is malformed")
                contract_id = row.get("contract_id")
                if not isinstance(contract_id, str) or not SOURCE_CONTRACT_RE.fullmatch(contract_id):
                    raise ValidationError(f"{dossier} source independent contract ID is malformed: {contract_id}")
                match = SOURCE_CONTRACT_RE.fullmatch(contract_id)
                if match is None or f"D{match.group(1)}" != dossier:
                    raise ValidationError(f"{dossier} source independent contract ID does not match dossier: {contract_id}")
                if contract_id in contract_ids:
                    raise ValidationError(f"{dossier} source independent contract IDs contain duplicates")
                specs_for_contract = string_list(row.get("specification_ids"), f"{dossier} source contract specification IDs", pattern=SPEC_RE)
                if any(sid not in self.spec_ids for sid in specs_for_contract):
                    raise ValidationError(f"{dossier} source independent contract cites unknown specification ID")
                contract_ids.add(contract_id)
            self.source_contract_ids_by_dossier[dossier] = contract_ids

    def _validate_fixture_manifest(self, data: Mapping[str, Any]) -> None:
        exact_keys(data, {"schema_version", "schema", "fixture_set_id", "artifact_set_id", "status", "approved", "independent_review_id", "fixtures", "execution_fields", "safety_boundaries"}, "fixture manifest")
        if data.get("schema_version") != 1 or data.get("schema") != "g007-fixture-definitions/v1" or data.get("artifact_set_id") != self.artifact_set_id:
            raise ValidationError("fixture manifest identity/schema is invalid")
        if data.get("status") != "definition_only_g008_pending":
            raise ValidationError("fixture manifest must remain a G008-pending definition")
        if data.get("approved") is False and data.get("independent_review_id") is None:
            self.fixture_approved = False
            self.fixture_review_id = None
        elif data.get("approved") is True and isinstance(data.get("independent_review_id"), str) and data.get("independent_review_id"):
            self.fixture_approved = True
            self.fixture_review_id = str(data.get("independent_review_id"))
        else:
            raise ValidationError("fixture manifest review lifecycle is invalid")
        exact_keys(data.get("execution_fields"), {"run_manifest_ids", "result_bundle_ids", "hardware_fixture_ids"}, "fixture manifest execution fields")
        if data["execution_fields"] != {"run_manifest_ids": [], "result_bundle_ids": [], "hardware_fixture_ids": []}:
            raise ValidationError("fixture manifest fabricates execution fields")
        rows = data.get("fixtures")
        if not isinstance(rows, list) or len(rows) != 13:
            raise ValidationError("fixture manifest must contain exactly 13 deterministic fixture definitions")
        if [row.get("fixture_id") for row in rows if isinstance(row, dict)] != sorted(row.get("fixture_id") for row in rows if isinstance(row, dict)):
            raise ValidationError("fixture definitions are not in canonical fixture_id order")
        seen: set[str] = set()
        for row in rows:
            exact_keys(row, {"fixture_id", "dossier_id", "contract_ids", "definition_kind", "fixture_state", "source_paths", "source_claim_ids", "source_evidence_bundle_ids", "source_specification_ids", "source_reproduction_ids", "normalization", "definition_sha256"}, "fixture row")
            fixture_id = str(row.get("fixture_id"))
            dossier_id = str(row.get("dossier_id"))
            if not FIX_RE.fullmatch(fixture_id) or fixture_id in seen or dossier_id not in DOSSIER_IDS or fixture_id != f"FIX-G007-{dossier_id}-DEFINITION":
                raise ValidationError(f"fixture row has invalid identity: {fixture_id}")
            seen.add(fixture_id)
            if row.get("definition_kind") != "deterministic_static_traceability_fixture" or row.get("fixture_state") != "definition_only_g008_pending":
                raise ValidationError(f"fixture {fixture_id} is not a deterministic pending definition")
            contract_ids = string_list(row.get("contract_ids"), f"fixture {fixture_id} contract IDs", pattern=CONTRACT_RE)
            if contract_ids != [f"CONTRACT-G007-{dossier_id}-PUBLICATION"]:
                raise ValidationError(f"fixture {fixture_id} does not map to its dossier contract")
            for cid in string_list(row.get("source_claim_ids"), f"fixture {fixture_id} claim IDs", pattern=CLAIM_RE):
                if cid not in self.claim_ids:
                    raise ValidationError(f"fixture {fixture_id} references unknown claim {cid}")
            for eid in string_list(row.get("source_evidence_bundle_ids"), f"fixture {fixture_id} evidence IDs", pattern=EVB_RE):
                if eid not in self.evidence_ids:
                    raise ValidationError(f"fixture {fixture_id} references unknown evidence {eid}")
            for sid in string_list(row.get("source_specification_ids"), f"fixture {fixture_id} specification IDs", pattern=SPEC_RE):
                if sid not in self.spec_ids:
                    raise ValidationError(f"fixture {fixture_id} references unknown specification {sid}")
            for rid in string_list(row.get("source_reproduction_ids"), f"fixture {fixture_id} reproduction IDs", pattern=RPRO_RE):
                if rid not in self.repro_ids:
                    raise ValidationError(f"fixture {fixture_id} references unknown reproduction {rid}")
            source_paths = row.get("source_paths")
            if not isinstance(source_paths, list) or not source_paths:
                raise ValidationError(f"fixture {fixture_id} lacks deterministic source paths")
            if [entry.get("path") for entry in source_paths if isinstance(entry, dict)] != sorted(entry.get("path") for entry in source_paths if isinstance(entry, dict)):
                raise ValidationError(f"fixture {fixture_id} source paths are not in canonical path order")
            for entry in source_paths:
                exact_keys(entry, {"path", "sha256", "size_bytes"}, f"fixture {fixture_id} source path")
                safe_rel(self.root, entry.get("path"), f"fixture {fixture_id} source path")
                actual_hash, actual_size = sha256_file(self.root, entry.get("path"), f"fixture {fixture_id} source path")
                if entry.get("sha256") != actual_hash or entry.get("size_bytes") != actual_size:
                    raise ValidationError(f"fixture {fixture_id} source hash/size is stale")
            recorded = row.get("definition_sha256")
            if not isinstance(recorded, str) or not SHA256_RE.fullmatch(recorded):
                raise ValidationError(f"fixture {fixture_id} is unhashed")
            copy = dict(row)
            copy.pop("definition_sha256", None)
            if hashlib.sha256(canonical_bytes(copy)).hexdigest() != recorded:
                raise ValidationError(f"fixture {fixture_id} definition hash is not deterministic")
        self.fixture_ids = seen

    def _validate_index(self, data: Mapping[str, Any]) -> None:
        exact_keys(data, {"schema_version", "schema", "specification_id", "artifact_set_id", "author_id", "approved", "clean_room_review_id", "review_ids", "evidence_bundle_ids", "claim_ids", "source_index_path", "publication_state", "contracts", "acceptance_tests", "g008_execution_summary", "safety_boundaries"}, "G007 index")
        if data.get("schema_version") != 1 or data.get("schema") != "g007-source-independent-publication/v1" or data.get("artifact_set_id") != self.artifact_set_id:
            raise ValidationError("G007 index identity/schema is invalid")
        if data.get("specification_id") != "SPEC-G007-HIKMICRO-VIEWER-2.6.0-PUBLICATION" or not data.get("author_id"):
            raise ValidationError("G007 index specification/author identity is invalid")
        summary = exact_keys(data.get("g008_execution_summary"), {"status", "run_ids", "result_bundle_ids", "result_attachments"}, "G008 summary")
        if summary != {"status": "pending", "run_ids": [], "result_bundle_ids": [], "result_attachments": []}:
            raise ValidationError("G007 index fabricates G008 execution summary")
        for eid in string_list(data.get("evidence_bundle_ids"), "G007 evidence IDs", pattern=EVB_RE):
            if eid not in self.evidence_ids:
                raise ValidationError(f"G007 index references unknown evidence {eid}")
        for cid in string_list(data.get("claim_ids"), "G007 claim IDs", pattern=CLAIM_RE):
            if cid not in self.claim_ids:
                raise ValidationError(f"G007 index references unknown claim {cid}")
        safe_rel(self.root, data.get("source_index_path"), "G007 source_index_path")
        contracts = data.get("contracts")
        tests = data.get("acceptance_tests")
        if not isinstance(contracts, list) or len(contracts) != 13:
            raise ValidationError("G007 index must contain exactly 13 dossier contracts")
        if not isinstance(tests, list) or not tests:
            raise ValidationError("G007 index must contain acceptance tests")
        if [row.get("contract_id") for row in contracts if isinstance(row, dict)] != sorted(row.get("contract_id") for row in contracts if isinstance(row, dict)):
            raise ValidationError("G007 contracts are not in canonical contract_id order")
        if [row.get("test_id") for row in tests if isinstance(row, dict)] != sorted(row.get("test_id") for row in tests if isinstance(row, dict)):
            raise ValidationError("G007 acceptance tests are not in canonical test_id order")
        contract_ids: set[str] = set()
        contract_to_tests: dict[str, set[str]] = {}
        contract_to_fixture: dict[str, set[str]] = {}
        for row in contracts:
            self._validate_contract(row, contract_ids, contract_to_tests, contract_to_fixture)
        test_ids: set[str] = set()
        test_to_contracts: dict[str, set[str]] = {}
        test_to_fixtures: dict[str, set[str]] = {}
        for row in tests:
            self._validate_acceptance(row, contract_ids, test_ids, test_to_contracts, test_to_fixtures)
        declared_test_ids = set().union(*contract_to_tests.values())
        if declared_test_ids != test_ids:
            raise ValidationError("contract/test traceability is not exact")
        for contract_id, tids in contract_to_tests.items():
            for tid in tids:
                if contract_id not in test_to_contracts.get(tid, set()):
                    raise ValidationError(f"acceptance test {tid} lacks reverse contract mapping for {contract_id}")
        all_fixture_refs = set().union(*contract_to_fixture.values()) | set().union(*test_to_fixtures.values())
        if all_fixture_refs != self.fixture_ids:
            raise ValidationError("fixture traceability is not exact across contracts/tests")
        contract_claims = {claim for row in contracts for claim in row["evidence_claim_ids"]}
        contract_evidence = {eid for row in contracts for eid in row["evidence_bundle_ids"]}
        if set(data["claim_ids"]) != contract_claims or set(data["evidence_bundle_ids"]) != contract_evidence:
            raise ValidationError("G007 top-level claim/evidence coverage does not exactly match contracts")
        self.index_counts = {
            "dossiers": len(DOSSIER_IDS),
            "contracts": len(contract_ids),
            "acceptance_tests": len(test_ids),
            "fixture_definitions": len(self.fixture_ids),
            "claims": len(contract_claims),
            "evidence_bundles": len(contract_evidence),
            "unknowns_preserved": len({uid for row in contracts for uid in row["unknown_ids"]}),
        }
        self._validate_review_lifecycle(data, contract_ids, test_ids)

    def _validate_review_lifecycle(self, data: Mapping[str, Any], contract_ids: set[str], test_ids: set[str]) -> None:
        approved = data.get("approved")
        review_id = data.get("clean_room_review_id")
        review_ids = data.get("review_ids")
        author_id = data.get("author_id")
        if approved is False:
            if review_id is not None or review_ids != []:
                raise ValidationError("G007 current candidate must be approved=false with no valid review linkage")
            if self.fixture_approved or self.fixture_review_id is not None:
                raise ValidationError("G007 current candidate fixture manifest must not cite a valid review")
            self.index_approved = False
            self.index_review_id = None
            return
        if approved is not True:
            raise ValidationError("G007 approved must be a boolean")
        if not isinstance(review_id, str) or not review_id or review_ids != [review_id]:
            raise ValidationError("G007 reviewed state requires one clean_room_review_id mirrored in review_ids")
        if not self.fixture_approved or self.fixture_review_id != review_id:
            raise ValidationError("G007 reviewed state requires fixture manifest to cite the same independent review")
        review_index = self._load_required_json(G007_REVIEW_INDEX_REL)
        rows = review_index.get("reviews")
        if review_index.get("artifact_set_id") != self.artifact_set_id or not isinstance(rows, list):
            raise ValidationError("G007 review index is not authoritative for this artifact set")
        matches = [row for row in rows if isinstance(row, dict) and row.get("review_id") == review_id]
        if len(matches) != 1:
            raise ValidationError(f"review {review_id} is not uniquely indexed")
        row = matches[0]
        for key in {"review_id", "path", "sha256", "size_bytes", "subject_ids"}:
            if key not in row:
                raise ValidationError(f"review index row {review_id} lacks {key}")
        if row.get("artifact_set_id", self.artifact_set_id) != self.artifact_set_id:
            raise ValidationError(f"review {review_id} artifact set mismatch")
        safe_rel(self.root, row.get("path"), f"review {review_id} path")
        actual_hash, actual_size = sha256_file(self.root, row.get("path"), f"review {review_id} path")
        if row.get("sha256") != actual_hash or row.get("size_bytes") != actual_size:
            raise ValidationError(f"review {review_id} hash/size is stale")
        subject_ids = string_list(row.get("subject_ids"), f"review {review_id} subject IDs")
        if subject_ids != [data["specification_id"]]:
            raise ValidationError(f"review {review_id} subject IDs do not exactly cover the G007 spec subject")
        review_doc = load_json(self.root / Path(str(row["path"])), self.root, Path(str(row["path"])))
        review_doc = exact_keys(review_doc, REVIEW_SCHEMA_KEYS, f"review {review_id} document")
        if review_doc.get("schema_version") != 1 or review_doc.get("schema") != "g007-independent-publication-review/v1":
            raise ValidationError(f"review {review_id} schema identity is invalid")
        if review_doc.get("review_id") != review_id:
            raise ValidationError(f"review {review_id} document ID does not match index")
        verdict = str(review_doc.get("verdict", "")).lower()
        if verdict != "pass" or review_doc.get("passed") is not True:
            raise ValidationError(f"review {review_id} verdict is not pass")
        checks = exact_keys(review_doc.get("checks"), REVIEW_CHECK_KEYS, f"review {review_id} checks")
        if any(value != "pass" for value in checks.values()):
            raise ValidationError(f"review {review_id} checks are not all pass")
        if review_doc.get("independent_from_producers") is not True or review_doc.get("independent_from_author_id") != author_id:
            raise ValidationError(f"review {review_id} independence declaration is invalid")
        reviewer = review_doc.get("reviewer_id")
        if not isinstance(reviewer, str) or not reviewer:
            raise ValidationError(f"review {review_id} lacks reviewer identity")
        if reviewer == author_id:
            raise ValidationError(f"review {review_id} reviewer is not independent from author/producers")
        if review_doc.get("subject_specification_id") != data["specification_id"]:
            raise ValidationError(f"review {review_id} does not target exact G007 specification subject")
        subject_artifact_hashes = review_doc.get("subject_artifact_hashes")
        if not isinstance(subject_artifact_hashes, dict):
            raise ValidationError(f"review {review_id} subject_artifact_hashes must be an object")
        expected_subject_hash_paths = [rel.as_posix() for rel in REVIEW_SUBJECT_RELS]
        if set(subject_artifact_hashes) != set(expected_subject_hash_paths):
            raise ValidationError(
                f"review {review_id} subject artifact hash coverage is not exact: "
                f"expected={sorted(expected_subject_hash_paths)}, actual={sorted(subject_artifact_hashes)}"
            )
        for rel in REVIEW_SUBJECT_RELS:
            rel_text = rel.as_posix()
            recorded_hash = subject_artifact_hashes.get(rel_text)
            if not isinstance(recorded_hash, str) or not SHA256_RE.fullmatch(recorded_hash):
                raise ValidationError(f"review {review_id} subject hash is malformed for {rel_text}")
            actual_subject_hash, _ = sha256_file(self.root, rel, f"review {review_id} subject artifact {rel_text}")
            if recorded_hash != actual_subject_hash:
                raise ValidationError(f"review {review_id} subject artifact hash is stale for {rel_text}")
        if set(string_list(review_doc.get("covered_contract_ids"), f"review {review_id} covered contract IDs", pattern=CONTRACT_RE)) != contract_ids:
            raise ValidationError(f"review {review_id} contract coverage is not exact")
        if set(string_list(review_doc.get("covered_acceptance_test_ids"), f"review {review_id} covered acceptance test IDs", pattern=AT_RE)) != test_ids:
            raise ValidationError(f"review {review_id} acceptance-test coverage is not exact")
        if set(string_list(review_doc.get("covered_fixture_ids"), f"review {review_id} covered fixture IDs", pattern=FIX_RE)) != self.fixture_ids:
            raise ValidationError(f"review {review_id} fixture/evidence-bundle coverage is not exact")
        self.index_approved = True
        self.index_review_id = review_id
        self.review_paths = {G007_REVIEW_INDEX_REL.as_posix(), str(row["path"])}

    def _validate_contract(self, row: Any, seen: set[str], ctests: dict[str, set[str]], cfixtures: dict[str, set[str]]) -> None:
        exact_keys(row, {"contract_id", "schema_version", "dossier_id", "title", "category", "source_contract_ids", "source_specification_ids", "evidence_claim_ids", "evidence_bundle_ids", "acceptance_test_ids", "fixture_ids", "unknown_ids", "observable_inputs", "observable_outputs", "state_transitions", "timing_lifetime", "errors_recovery", "boundaries", "g008_execution"}, "contract")
        cid = str(row.get("contract_id")); dossier = str(row.get("dossier_id"))
        if not CONTRACT_RE.fullmatch(cid) or cid in seen or dossier not in DOSSIER_IDS or cid != f"CONTRACT-G007-{dossier}-PUBLICATION":
            raise ValidationError(f"invalid/duplicate contract identity {cid}")
        seen.add(cid)
        if row.get("schema_version") != 1:
            raise ValidationError(f"contract {cid} schema_version must be 1")
        if not isinstance(row.get("title"), str) or not row["title"] or not isinstance(row.get("category"), str) or not row["category"]:
            raise ValidationError(f"contract {cid} lacks semantic title/category")
        source_contract_ids = set(string_list(row.get("source_contract_ids"), f"contract {cid} source contract IDs", pattern=SOURCE_CONTRACT_RE))
        if source_contract_ids != self.source_contract_ids_by_dossier.get(dossier, set()):
            raise ValidationError(f"contract {cid} source_contract_ids do not exactly match authoritative dossier contracts")
        spec_ids = string_list(row.get("source_specification_ids"), f"contract {cid} spec IDs", pattern=SPEC_RE)
        claim_ids = string_list(row.get("evidence_claim_ids"), f"contract {cid} claim IDs", pattern=CLAIM_RE)
        ev_ids = string_list(row.get("evidence_bundle_ids"), f"contract {cid} evidence IDs", pattern=EVB_RE)
        test_ids = set(string_list(row.get("acceptance_test_ids"), f"contract {cid} acceptance IDs", pattern=AT_RE))
        fixture_ids = set(string_list(row.get("fixture_ids"), f"contract {cid} fixture IDs", pattern=FIX_RE))
        unknown_ids = string_list(row.get("unknown_ids"), f"contract {cid} unknown IDs", nonempty=False, pattern=UNKNOWN_RE)
        if any(sid not in self.spec_ids for sid in spec_ids) or any(claim not in self.claim_ids for claim in claim_ids) or any(eid not in self.evidence_ids for eid in ev_ids):
            raise ValidationError(f"contract {cid} references unknown authoritative IDs")
        if any(uid not in self.unknown_ids_by_dossier[dossier] for uid in unknown_ids):
            raise ValidationError(f"contract {cid} references unknown unknown/nonterminal IDs")
        if fixture_ids != {f"FIX-G007-{dossier}-DEFINITION"}:
            raise ValidationError(f"contract {cid} does not map to its deterministic fixture")
        for key, id_key in (("observable_inputs", "input_id"), ("observable_outputs", "output_id"), ("state_transitions", "transition_id"), ("timing_lifetime", "requirement_id"), ("errors_recovery", "error_id")):
            values = row.get(key)
            if not isinstance(values, list) or not values:
                raise ValidationError(f"contract {cid} {key} is empty")
            for item in values:
                if not isinstance(item, dict) or id_key not in item or "claim_ids" not in item:
                    raise ValidationError(f"contract {cid} {key} descriptor is malformed")
                descriptor_claims = set(string_list(item.get("claim_ids"), f"contract {cid} {key} descriptor claims", pattern=CLAIM_RE))
                if not descriptor_claims.issubset(set(claim_ids)):
                    raise ValidationError(f"contract {cid} descriptor cites claims outside its contract")
        boundaries = row.get("boundaries")
        if not isinstance(boundaries, dict):
            raise ValidationError(f"contract {cid} boundaries are missing")
        needed_boundaries = {"behavior", "lifecycle", "protocol_data", "thread_ref_buffer_ownership", "ui_storage_network", "privacy", "no_fake_celsius"}
        if not needed_boundaries.issubset(boundaries):
            raise ValidationError(f"contract {cid} lacks required boundary coverage")
        g008 = exact_keys(row.get("g008_execution"), {"status", "run_id", "result_bundle_ids", "result_attachment"}, f"contract {cid} G008 execution")
        if g008 != {"status": "pending", "run_id": None, "result_bundle_ids": [], "result_attachment": None}:
            raise ValidationError(f"contract {cid} fabricates terminal G008 execution")
        ctests[cid] = test_ids
        cfixtures[cid] = fixture_ids

    def _validate_acceptance(self, row: Any, contract_ids: set[str], seen: set[str], tcontracts: dict[str, set[str]], tfixtures: dict[str, set[str]]) -> None:
        exact_keys(row, {"test_id", "schema_version", "reproduction_id", "dossier_id", "contract_ids", "verification_claim_ids", "official_comparison_bundle_ids", "fixture_ids", "command", "assertion_ids", "expected_assertions", "run_id", "result_bundle_ids", "result_attachment", "execution_status"}, "acceptance test")
        tid = str(row.get("test_id")); rid = str(row.get("reproduction_id")); dossier = str(row.get("dossier_id"))
        if not AT_RE.fullmatch(tid) or tid in seen or not RPRO_RE.fullmatch(rid) or rid not in self.repro_ids or dossier not in DOSSIER_IDS:
            raise ValidationError(f"acceptance test has invalid identity {tid}")
        expected_tid = f"AT-G007-{rid.replace('RPRO-G003-', '')}"
        if tid != expected_tid:
            raise ValidationError(f"acceptance test {tid} is not derived from reproduction ID {rid}")
        seen.add(tid)
        if row.get("schema_version") != 1 or row.get("execution_status") != "pending_g008":
            raise ValidationError(f"acceptance test {tid} schema/status is invalid")
        cids = set(string_list(row.get("contract_ids"), f"acceptance {tid} contract IDs", pattern=CONTRACT_RE))
        fids = set(string_list(row.get("fixture_ids"), f"acceptance {tid} fixture IDs", pattern=FIX_RE))
        if not cids.issubset(contract_ids) or fids != {f"FIX-G007-{dossier}-DEFINITION"}:
            raise ValidationError(f"acceptance test {tid} traceability is invalid")
        for claim in string_list(row.get("verification_claim_ids"), f"acceptance {tid} claim IDs", pattern=CLAIM_RE):
            if claim not in self.claim_ids:
                raise ValidationError(f"acceptance test {tid} references unknown claim {claim}")
        for evidence in string_list(row.get("official_comparison_bundle_ids"), f"acceptance {tid} evidence IDs", pattern=EVB_RE):
            if evidence not in self.evidence_ids:
                raise ValidationError(f"acceptance test {tid} references unknown evidence {evidence}")
        if not isinstance(row.get("command"), str) or not row["command"].startswith("python3 tools/hik_whole_apk/g007_spec_validator.py --root ."):
            raise ValidationError(f"acceptance test {tid} command is not a replayable publication validation command")
        string_list(row.get("assertion_ids"), f"acceptance {tid} assertion IDs", pattern=ASSERT_RE)
        if not isinstance(row.get("expected_assertions"), list) or not row["expected_assertions"]:
            raise ValidationError(f"acceptance test {tid} lacks expected assertions")
        if row.get("run_id") is not None or row.get("result_bundle_ids") != [] or row.get("result_attachment") is not None:
            raise ValidationError(f"acceptance test {tid} fabricates G008 execution results")
        scan_for_fake_terminal_claims_recursive(row, f"acceptance test {tid}")
        tcontracts[tid] = cids
        tfixtures[tid] = fids

    def _validate_status(self, data: Mapping[str, Any]) -> None:
        exact_keys(data, {"schema_version", "schema", "specification_id", "artifact_set_id", "approved", "independent_review", "g008_execution", "counts", "terminal_claims", "artifact_hashes"}, "status")
        if data.get("schema_version") != 1 or data.get("schema") != "g007-publication-status/v1" or data.get("artifact_set_id") != self.artifact_set_id:
            raise ValidationError("status identity/schema is invalid")
        if data.get("approved") is not self.index_approved:
            raise ValidationError("status approved flag does not match G007 index review lifecycle")
        expected_review_state = "passed" if self.index_approved else "pending"
        if data.get("independent_review") != expected_review_state or data.get("g008_execution") != "pending":
            raise ValidationError("status review/G008 lifecycle is inconsistent with G007 index")
        counts = exact_keys(data.get("counts"), {"dossiers", "contracts", "acceptance_tests", "fixture_definitions", "claims", "evidence_bundles", "unknowns_preserved"}, "status counts")
        if counts != self.index_counts:
            raise ValidationError(f"status counts do not match parsed contracts/tests/fixtures/unknowns: expected={self.index_counts}, actual={counts}")
        terminal = exact_keys(data.get("terminal_claims"), {"e4_e5_result_bundles", "live_f2_runs", "hardware_runs", "radiometric_or_celsius_claims"}, "status terminal claims")
        if any(value != [] for value in terminal.values()):
            raise ValidationError("status fabricates terminal/live/radiometric claims")
        hashes = data.get("artifact_hashes")
        if not isinstance(hashes, list) or not hashes:
            raise ValidationError("status lacks artifact hashes")
        expected_paths = [
            (G007_REL / "README.md").as_posix(),
            (G007_REL / "index.json").as_posix(),
            FIXTURE_REL.as_posix(),
        ]
        if self.index_approved:
            expected_paths.extend(sorted(self.review_paths))
        actual_paths = [row.get("path") for row in hashes if isinstance(row, dict)]
        if set(actual_paths) != set(expected_paths) or len(actual_paths) != len(set(actual_paths)):
            raise ValidationError(f"status artifact hash coverage must be exact and unique: expected={sorted(expected_paths)}, actual={actual_paths}")
        for row in hashes:
            exact_keys(row, {"path", "sha256", "size_bytes"}, "status artifact hash")
            if row.get("path") == (G007_REL / "status.json").as_posix():
                raise ValidationError("status must not include a self-hash")
            safe_rel(self.root, row.get("path"), "status artifact path")
            actual_hash, actual_size = sha256_file(self.root, row.get("path"), "status artifact path")
            if row.get("sha256") != actual_hash or row.get("size_bytes") != actual_size:
                raise ValidationError(f"status hash is stale for {row.get('path')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate G007 source-independent publication artifacts")
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    result = G007SpecValidator(Path(args.root)).validate()
    payload = {
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
        "checked_files": sorted(result.checked_files),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        if result.ok:
            print(f"G007 publication validation passed ({len(result.checked_files)} files checked)")
        else:
            print("G007 publication validation failed", file=sys.stderr)
            for error in result.errors:
                print(f"ERROR: {error}", file=sys.stderr)
        for warning in result.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
