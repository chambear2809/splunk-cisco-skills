#!/usr/bin/env python3
"""Run pinned, redacted Gitleaks scans over tracked files and full history."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / ".gitleaks-baseline.json"
HISTORY_IGNORE_PATH = REPO_ROOT / ".gitleaksignore"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_FINGERPRINT_RE = re.compile(
    r"^[0-9a-f]{40}:[^:\r\n]+:[a-z0-9-]+:[1-9][0-9]*$"
)


class SecretScanError(ValueError):
    """Raised when scanner provenance or a reviewed baseline is invalid."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_baseline() -> dict[str, Any]:
    try:
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecretScanError(f"cannot load {BASELINE_PATH.name}: {exc}") from exc
    if not isinstance(baseline, dict) or baseline.get("schema_version") != 1:
        raise SecretScanError("unsupported or missing Gitleaks baseline schema")
    return baseline


def _validate_history_ignore(baseline: dict[str, Any]) -> None:
    try:
        payload = HISTORY_IGNORE_PATH.read_bytes()
    except OSError as exc:
        raise SecretScanError(f"cannot read {HISTORY_IGNORE_PATH.name}: {exc}") from exc

    expected_sha256 = baseline.get("history_fingerprints_sha256")
    expected_count = baseline.get("history_fingerprint_count")
    lines = payload.decode("utf-8").splitlines()
    if _sha256(payload) != expected_sha256:
        raise SecretScanError(
            ".gitleaksignore changed without a reviewed baseline update"
        )
    if len(lines) != expected_count:
        raise SecretScanError(
            ".gitleaksignore count does not match the reviewed baseline"
        )
    if len(lines) != len(set(lines)):
        raise SecretScanError(".gitleaksignore contains duplicate fingerprints")
    invalid = [line for line in lines if not COMMIT_FINGERPRINT_RE.fullmatch(line)]
    if invalid:
        raise SecretScanError(
            ".gitleaksignore may contain only commit-bound Gitleaks fingerprints"
        )


def _gitleaks_version(executable: str, baseline: dict[str, Any]) -> None:
    expected = str(baseline.get("scanner", {}).get("version", ""))
    if not expected:
        raise SecretScanError("baseline does not declare a scanner version")
    result = subprocess.run(
        [executable, "version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    actual = result.stdout.strip()
    if actual != expected:
        raise SecretScanError(
            f"Gitleaks version mismatch: expected {expected}, got {actual!r}"
        )


def _tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    paths = sorted(
        item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    )
    if not paths:
        raise SecretScanError("git reported no tracked files")
    return paths


def _validated_exemptions(
    baseline: dict[str, Any],
) -> dict[str, dict[int, bytes]]:
    categories = baseline.get("current_tree_categories")
    entries = baseline.get("current_tree_exemptions")
    if not isinstance(categories, dict) or not categories:
        raise SecretScanError("baseline current-tree categories are missing")
    if not isinstance(entries, list):
        raise SecretScanError("baseline current-tree exemptions must be a list")

    by_path: dict[str, dict[int, bytes]] = {}
    identities: set[tuple[str, int, str]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SecretScanError(f"current_tree_exemptions[{index}] is not an object")
        rel_path = str(entry.get("path", ""))
        line_number = entry.get("line")
        rule_id = str(entry.get("rule_id", ""))
        digest = str(entry.get("line_sha256", ""))
        category = str(entry.get("category", ""))

        pure_path = PurePosixPath(rel_path)
        if (
            not rel_path
            or pure_path.is_absolute()
            or ".." in pure_path.parts
            or "\\" in rel_path
        ):
            raise SecretScanError(
                f"current_tree_exemptions[{index}] has an unsafe path"
            )
        if not isinstance(line_number, int) or line_number < 1:
            raise SecretScanError(
                f"current_tree_exemptions[{index}] has an invalid line"
            )
        if not rule_id or not SHA256_RE.fullmatch(digest):
            raise SecretScanError(
                f"current_tree_exemptions[{index}] has invalid rule/hash metadata"
            )
        if category not in categories:
            raise SecretScanError(
                f"current_tree_exemptions[{index}] uses an unknown category"
            )
        identity = (rel_path, line_number, rule_id)
        if identity in identities:
            raise SecretScanError(f"duplicate current-tree exemption: {identity}")
        identities.add(identity)

        source = REPO_ROOT / rel_path
        try:
            lines = source.read_bytes().splitlines(keepends=True)
        except OSError as exc:
            raise SecretScanError(f"cannot read reviewed path {rel_path}: {exc}") from exc
        if line_number > len(lines):
            raise SecretScanError(
                f"reviewed line no longer exists: {rel_path}:{line_number}"
            )
        source_line = lines[line_number - 1]
        if _sha256(source_line) != digest:
            raise SecretScanError(
                "reviewed false-positive line changed; remove or re-review "
                f"the exemption: {rel_path}:{line_number} ({rule_id})"
            )
        by_path.setdefault(rel_path, {})[line_number] = source_line
    return by_path


def _copy_tracked_tree(
    destination: Path,
    exemptions: dict[str, dict[int, bytes]],
) -> None:
    root_resolved = REPO_ROOT.resolve()
    tracked = _tracked_paths()
    unknown_exemptions = sorted(set(exemptions) - set(tracked))
    if unknown_exemptions:
        raise SecretScanError(
            "current-tree exemptions reference untracked paths: "
            + ", ".join(unknown_exemptions)
        )

    for rel_path in tracked:
        source = REPO_ROOT / rel_path
        target = destination / rel_path
        try:
            source_mode = source.lstat().st_mode
        except OSError as exc:
            raise SecretScanError(f"tracked path is unavailable: {rel_path}: {exc}") from exc
        target.parent.mkdir(parents=True, exist_ok=True)

        if stat.S_ISLNK(source_mode):
            target.write_text(os.readlink(source), encoding="utf-8")
            continue
        if not stat.S_ISREG(source_mode):
            raise SecretScanError(f"unsupported tracked file type: {rel_path}")
        if not source.resolve(strict=True).is_relative_to(root_resolved):
            raise SecretScanError(f"tracked file resolves outside the repository: {rel_path}")

        payload = source.read_bytes()
        reviewed_lines = exemptions.get(rel_path)
        if reviewed_lines:
            lines = payload.splitlines(keepends=True)
            for line_number, expected_line in reviewed_lines.items():
                if lines[line_number - 1] != expected_line:
                    raise SecretScanError(
                        f"reviewed line changed while snapshotting: {rel_path}:{line_number}"
                    )
                newline = b""
                if expected_line.endswith(b"\r\n"):
                    newline = b"\r\n"
                elif expected_line.endswith(b"\n"):
                    newline = b"\n"
                lines[line_number - 1] = (
                    b"gitleaks-reviewed-false-positive" + newline
                )
            payload = b"".join(lines)
        target.write_bytes(payload)


def _run_tree_scan(executable: str, baseline: dict[str, Any]) -> None:
    exemptions = _validated_exemptions(baseline)
    with tempfile.TemporaryDirectory(prefix="splunk-cisco-skills-gitleaks-") as temp:
        snapshot = Path(temp)
        _copy_tracked_tree(snapshot, exemptions)
        subprocess.run(
            [
                executable,
                "dir",
                "--redact=100",
                "--no-banner",
                "--no-color",
                "--verbose",
                "--timeout=300",
                ".",
            ],
            cwd=snapshot,
            check=True,
        )


def _run_history_scan(executable: str) -> None:
    subprocess.run(
        [
            executable,
            "git",
            "--redact=100",
            "--no-banner",
            "--no-color",
            "--verbose",
            "--timeout=300",
            "--gitleaks-ignore-path",
            str(HISTORY_IGNORE_PATH),
            "--log-opts=--all",
            ".",
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gitleaks",
        default="gitleaks",
        help="path to the Gitleaks executable (default: gitleaks on PATH)",
    )
    parser.add_argument(
        "--mode",
        choices=("all", "tree", "history"),
        default="all",
        help="scan surface (default: all)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    executable = shutil.which(args.gitleaks)
    if executable is None:
        print(f"ERROR: Gitleaks executable not found: {args.gitleaks}", file=sys.stderr)
        return 1

    try:
        baseline = _load_baseline()
        _validate_history_ignore(baseline)
        _gitleaks_version(executable, baseline)
        if args.mode in {"all", "tree"}:
            _run_tree_scan(executable, baseline)
        if args.mode in {"all", "history"}:
            _run_history_scan(executable)
    except (OSError, SecretScanError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: secret scan failed: {exc}", file=sys.stderr)
        return 1

    print(f"Redacted Gitleaks {args.mode} scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
