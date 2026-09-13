#!/usr/bin/env python3
"""Hardware-safe F2 causal-frontier CLI.

This tool is intentionally conservative: it can create draft frontier documents
and ask the canonical critic to validate canonical evidence, but it never talks
to devices and never promotes a draft into the canonical ledger/frontier.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import secrets
import shutil
import stat
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

# Allow ``python tools/hik_whole_apk/g006_f2_frontier.py ...`` from a checkout
# without requiring PYTHONPATH to already contain the repository root.
if __package__ in {None, ""}:
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

from tools.hik_whole_apk import critic

DEFAULT_MAX_JSON_BYTES = 5 * 1024 * 1024
ALLOWED_OUTPUT_ROOT_REL = critic.RESEARCH_REL / "dynamic/g006"

class CliError(RuntimeError):
    """Raised for user-facing CLI contract failures."""


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _require_posix_anchored_write_support() -> None:
    if os.name != "posix":
        raise CliError("secure G006 output writing requires POSIX directory file descriptors")
    missing_flags = [name for name in ("O_DIRECTORY", "O_NOFOLLOW") if not hasattr(os, name)]
    if missing_flags:
        raise CliError(f"secure G006 output writing requires {', '.join(missing_flags)}")
    supports_dir_fd = getattr(os, "supports_dir_fd", ())
    for name in ("open", "mkdir", "stat", "unlink"):
        if getattr(os, name) not in supports_dir_fd:
            raise CliError(f"secure G006 output writing requires dir_fd support for os.{name}")
    if os.stat not in getattr(os, "supports_follow_symlinks", ()):
        raise CliError("secure G006 output writing requires no-follow os.stat support")
    try:
        replace_parameters = inspect.signature(os.replace).parameters
    except (TypeError, ValueError) as exc:
        raise CliError("cannot verify secure os.replace directory-FD support") from exc
    if not {"src_dir_fd", "dst_dir_fd"}.issubset(replace_parameters):
        raise CliError("secure G006 output writing requires directory-FD os.replace support")


def _open_output_parent_fd(root: Path, path: Path) -> tuple[int, str]:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise CliError("--output must remain lexically contained under --root") from exc
    allowed_parts = ALLOWED_OUTPUT_ROOT_REL.parts
    if relative.parts[:len(allowed_parts)] != allowed_parts or len(relative.parts) <= len(allowed_parts):
        raise CliError("--output must remain under the dedicated G006 output subtree")

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    opened_fds: list[int] = []
    try:
        opened_fds.append(os.open(root, directory_flags))
        for component in relative.parts[:-1]:
            parent_fd = opened_fds[-1]
            try:
                child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o777, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            opened_fds.append(child_fd)
        return opened_fds.pop(), relative.parts[-1]
    except (OSError, TypeError, NotImplementedError) as exc:
        raise CliError(f"cannot securely anchor --output parent: {exc}") from exc
    finally:
        for fd in reversed(opened_fds):
            try:
                os.close(fd)
            except OSError:
                pass


def _write_all(fd: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        try:
            written = os.write(fd, remaining)
        except InterruptedError:
            continue
        except OSError as exc:
            raise CliError(f"cannot write secure G006 temporary output: {exc}") from exc
        if written <= 0:
            raise CliError("cannot write secure G006 temporary output completely")
        remaining = remaining[written:]


def _write_canonical_json(root: Path, path: Path, value: Any) -> None:
    _require_posix_anchored_write_support()
    payload = _canonical_json_bytes(value)
    parent_fd, output_name = _open_output_parent_fd(root, path)
    temp_fd: int | None = None
    temp_name: str | None = None
    try:
        try:
            output_stat = os.stat(output_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            output_stat = None
        except (OSError, TypeError, NotImplementedError) as exc:
            raise CliError(f"cannot securely inspect existing --output entry: {exc}") from exc
        if output_stat is not None:
            if stat.S_ISLNK(output_stat.st_mode):
                raise CliError("--output must not be an existing symlink")
            if stat.S_ISDIR(output_stat.st_mode):
                raise CliError("--output must name a file, not a directory")
            if not stat.S_ISREG(output_stat.st_mode):
                raise CliError("--output must be absent or an existing regular file")

        temp_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        for _ in range(128):
            candidate = f".g006-tmp-{os.getpid()}-{secrets.token_hex(12)}"
            try:
                temp_fd = os.open(candidate, temp_flags, 0o600, dir_fd=parent_fd)
            except FileExistsError:
                continue
            except (OSError, TypeError, NotImplementedError) as exc:
                raise CliError(f"cannot securely create G006 temporary output: {exc}") from exc
            temp_name = candidate
            break
        if temp_fd is None or temp_name is None:
            raise CliError("cannot allocate a unique secure G006 temporary output")

        _write_all(temp_fd, payload)
        fd_to_close = temp_fd
        temp_fd = None
        try:
            os.close(fd_to_close)
        except OSError as exc:
            raise CliError(f"cannot close secure G006 temporary output: {exc}") from exc
        try:
            os.replace(
                temp_name,
                output_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
        except (OSError, TypeError, NotImplementedError) as exc:
            raise CliError(f"cannot atomically replace secure G006 output: {exc}") from exc
        temp_name = None
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if temp_name is not None:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        try:
            os.close(parent_fd)
        except OSError:
            pass


def _resolve_root(raw_root: str) -> Path:
    path = Path(raw_root).expanduser()
    if not path.is_absolute():
        raise CliError("--root must be an explicit absolute path")
    root = path.resolve()
    if not root.is_dir():
        raise CliError(f"--root must be an existing directory: {raw_root}")
    return root


def _absolute_lexical_path(raw_path: str, *, label: str) -> Path:
    if not raw_path:
        raise CliError(f"{label} is required")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise CliError(f"{label} must be explicit absolute path")
    return Path(os.path.normpath(os.fspath(path)))


def _contained_path(root: Path, raw_path: str, *, label: str, must_exist: bool = False) -> Path:
    if not raw_path:
        raise CliError(f"{label} is required")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise CliError(f"{label} must be explicit absolute path")
    resolved = path.resolve(strict=must_exist)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CliError(f"{label} must be contained under --root") from exc
    return resolved


def _reject_symlinked_existing_components(base: Path, relative: Path, *, label: str) -> None:
    current = base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise CliError(f"{label} contains a symlinked path component: {current}")
        if not current.exists():
            return
        if not current.is_dir():
            raise CliError(f"{label} contains a non-directory path component: {current}")


def _require_allowed_output(root: Path, output: Path) -> None:
    _require_posix_anchored_write_support()
    output = Path(os.path.normpath(os.fspath(output)))
    allowed_root = root / ALLOWED_OUTPUT_ROOT_REL

    _reject_symlinked_existing_components(root, ALLOWED_OUTPUT_ROOT_REL, label="allowed output root")
    if allowed_root.exists():
        if not allowed_root.is_dir():
            raise CliError(
                "dedicated G006 draft/output root must be a directory: "
                f"{ALLOWED_OUTPUT_ROOT_REL.as_posix()}"
            )
        if allowed_root.resolve(strict=True) != allowed_root:
            raise CliError(
                "dedicated G006 draft/output root must not resolve outside its lexical path: "
                f"{ALLOWED_OUTPUT_ROOT_REL.as_posix()}"
            )

    try:
        output_relative = output.relative_to(allowed_root)
    except ValueError as exc:
        raise CliError(
            "--output must be under dedicated G006 draft/output subtree: "
            f"{ALLOWED_OUTPUT_ROOT_REL.as_posix()}"
        ) from exc
    if output_relative == Path("."):
        raise CliError(
            "--output must name a file under dedicated G006 draft/output subtree: "
            f"{ALLOWED_OUTPUT_ROOT_REL.as_posix()}"
        )

    parent_relative = ALLOWED_OUTPUT_ROOT_REL / output_relative.parent
    _reject_symlinked_existing_components(root, parent_relative, label="--output parent")
    if output.is_symlink():
        raise CliError("--output must not be an existing symlink")
    if output.exists() and output.is_dir():
        raise CliError("--output must name a file, not a directory")
    if output.exists() and output.resolve(strict=True) != output:
        raise CliError("--output must not resolve outside its lexical path")


def _read_bounded_json(path: Path, *, label: str, max_bytes: int) -> Mapping[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise CliError(f"cannot stat {label}: {exc}") from exc
    if size > max_bytes:
        raise CliError(f"{label} exceeds max JSON size of {max_bytes} bytes")
    try:
        with path.open("rb") as handle:
            payload = handle.read(max_bytes + 1)
    except OSError as exc:
        raise CliError(f"cannot read {label}: {exc}") from exc
    if len(payload) > max_bytes:
        raise CliError(f"{label} exceeds max JSON size of {max_bytes} bytes")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CliError(f"invalid JSON {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise CliError(f"{label} must be a JSON object")
    return value


def _missing_checkpoint_rows() -> list[dict[str, Any]]:
    return [
        {
            "checkpoint_id": checkpoint,
            "status": "missing",
            "claim_id": None,
            "run_id": None,
            "evidence_bundle_ids": [],
            "event_refs": [],
        }
        for checkpoint in critic.F2_CHECKPOINTS
    ]


def _frontier_draft_base(kind: str, owner: str, next_experiment: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "envelope": kind,
        "status": "draft_untrusted_unsigned_non_live",
        "frontier_id": "F2-first-frame",
        "owner": owner,
        "last_proven_checkpoint": "none",
        "first_missing_checkpoint": critic.F2_CHECKPOINTS[0],
        "supporting_bundle_ids": [],
        "next_discriminating_experiment": next_experiment,
        "updated_by_run_id": None,
        "accepted": False,
        "canonical": False,
        "mutates_canonical_frontier": False,
        "mutates_canonical_ledger": False,
        "evidence_backed": False,
        "checkpoint_order": list(critic.F2_CHECKPOINTS),
        "checkpoints": _missing_checkpoint_rows(),
        "claims": {
            "template_only": True,
            "terminal_proof": False,
            "radiometric_publication": False,
            "device_interaction": False,
        },
    }


def command_probe(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    output = _absolute_lexical_path(args.output, label="--output")
    _require_allowed_output(root, output)
    tools = {name: shutil.which(name) for name in ("adb", "frida", "frida-ps")}
    usb_bus_exists = os.path.exists("/dev/bus/usb")
    missing = [name for name, found in tools.items() if not found]
    if not usb_bus_exists:
        missing.append("/dev/bus/usb")
    doc = {
        "schema_version": 1,
        "envelope": "frontier_probe",
        "status": "ready" if not missing else "nonterminal_readiness",
        "passive": True,
        "deterministic": True,
        "device_writes": False,
        "subprocess_used": False,
        "tools": {name: {"available": bool(path), "path": path} for name, path in tools.items()},
        "usb_bus": {"path": "/dev/bus/usb", "available": usb_bus_exists},
        "missing": missing,
    }
    _write_canonical_json(root, output, doc)
    return 0 if not missing else 1


def command_prepare_frontier(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    output = _absolute_lexical_path(args.output, label="--output")
    _require_allowed_output(root, output)
    owner = args.owner or "UNASSIGNED"
    next_experiment = args.next_discriminating_experiment or "UNSPECIFIED_DISCRIMINATING_EXPERIMENT_REQUIRED"
    doc = _frontier_draft_base("frontier_draft_template", owner, next_experiment)
    _write_canonical_json(root, output, doc)
    return 0


def _require_non_empty(value: str | None, label: str) -> str:
    if value is None or not value.strip():
        raise CliError(f"{label} is required and must be non-empty")
    return value.strip()


def command_record_frontier(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    output = _absolute_lexical_path(args.output, label="--output")
    _require_allowed_output(root, output)
    if args.max_json_bytes <= 0:
        raise CliError("--max-json-bytes must be greater than 0")
    proof_ref_path = _contained_path(
        root,
        args.checkpoint_proof_ref,
        label="--checkpoint-proof-ref",
        must_exist=True,
    )
    proof_ref = _read_bounded_json(proof_ref_path, label="checkpoint proof reference", max_bytes=args.max_json_bytes)
    try:
        proof, bundle_ids, last_proven, first_missing, proof_sha256 = critic._validate_f2_checkpoint_proof(
            root,
            proof_ref,
            require_terminal=False,
        )
    except critic.ContractError as exc:
        raise CliError(f"invalid F2 checkpoint proof: {exc}") from exc
    doc = _frontier_draft_base(
        "frontier_draft_recorded",
        _require_non_empty(args.owner, "--owner"),
        _require_non_empty(args.next_discriminating_experiment, "--next-discriminating-experiment"),
    )
    doc.update(
        {
            "last_proven_checkpoint": last_proven,
            "first_missing_checkpoint": first_missing,
            "supporting_bundle_ids": sorted(bundle_ids),
            "updated_by_run_id": proof.get("updated_by_run_id"),
            "evidence_backed": bool(bundle_ids),
            "checkpoint_proof": proof_ref,
            "checkpoint_proof_sha256": proof_sha256,
            "checkpoints": proof.get("checkpoints"),
        }
    )
    _write_canonical_json(root, output, doc)
    return 0


def command_validate(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    output = _absolute_lexical_path(args.output, label="--output")
    _require_allowed_output(root, output)
    checks: list[tuple[str, Any]] = [
        ("validate_f2_frontier", critic.validate_f2_frontier),
        ("validate_f2_live_e2e", critic.validate_f2_live_e2e),
        ("validate_radiometric_truthfulness", critic.validate_radiometric_truthfulness),
    ]
    results: dict[str, Any] = {}
    failures: dict[str, str] = {}
    for name, func in checks:
        try:
            result = func(root)
        except critic.ContractError as exc:
            failures[name] = str(exc)
        else:
            results[name] = list(result)
    accepted = not failures and len(results) == len(checks)
    doc = {
        "schema_version": 1,
        "envelope": "frontier_validation",
        "status": "accepted" if accepted else "rejected",
        "accepted": accepted,
        "delegated_critics": [name for name, _ in checks],
        "results": results,
        "failures": failures,
        "self_attestation_bypass": False,
        "replay_synthetic_static_native_start_only_live_proof_accepted": False,
    }
    _write_canonical_json(root, output, doc)
    return 0 if accepted else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="G006 hardware-safe F2 frontier CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe")
    probe.add_argument("--root", required=True)
    probe.add_argument("--output", required=True)
    probe.set_defaults(func=command_probe)

    prepare = subparsers.add_parser("prepare-frontier")
    prepare.add_argument("--root", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--owner")
    prepare.add_argument("--next-discriminating-experiment")
    prepare.set_defaults(func=command_prepare_frontier)

    record = subparsers.add_parser("record-frontier")
    record.add_argument("--root", required=True)
    record.add_argument("--output", required=True)
    record.add_argument("--checkpoint-proof-ref", required=True)
    record.add_argument("--owner", required=True)
    record.add_argument("--next-discriminating-experiment", required=True)
    record.add_argument("--max-json-bytes", type=int, default=DEFAULT_MAX_JSON_BYTES)
    record.set_defaults(func=command_record_frontier)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--root", required=True)
    validate.add_argument("--output", required=True)
    validate.set_defaults(func=command_validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CliError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
