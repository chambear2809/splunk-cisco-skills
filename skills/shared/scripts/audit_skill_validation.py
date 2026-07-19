#!/usr/bin/env python3
"""Audit repository-wide skill validation surfaces and recorded evidence."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.shared.skill_catalog import SkillCatalog, load_catalog  # noqa: E402
from skills.shared.skill_validation import (  # noqa: E402
    EVIDENCE_DIMENSIONS,
    EVIDENCE_STATUSES,
    normalize_evidence_record,
)


SKILLS_DIR = REPO_ROOT / "skills"
TESTS_DIR = REPO_ROOT / "tests"
REGISTRY_PATH = SKILLS_DIR / "shared" / "skill_validation_registry.json"

SCHEMA_VERSION = 1
FLAG_RE = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete audit payload as JSON.",
    )
    return parser.parse_args()


def skill_dirs(catalog: SkillCatalog | None = None) -> list[Path]:
    manifest = catalog or load_catalog()
    return sorted((REPO_ROOT / record.path).parent for record in manifest.skills)


def test_files() -> list[Path]:
    return sorted(
        path
        for path in TESTS_DIR.glob("test_*")
        if path.is_file()
        and path.suffix in {".py", ".bats"}
        and path.name != "test_skill_validation_matrix.py"
    )


def _validate_evidence_record(
    *,
    skill: str,
    dimension: str,
    value: object,
    findings: list[str],
) -> dict[str, object]:
    normalized, record_findings = normalize_evidence_record(
        skill=skill,
        dimension=dimension,
        value=value,
        repo_root=REPO_ROOT,
    )
    findings.extend(record_findings)
    return normalized


def load_registry(
    actual_skills: list[str], findings: list[str], catalog: SkillCatalog
) -> dict[str, dict[str, dict[str, object]]]:
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        findings.append(f"{REGISTRY_PATH.relative_to(REPO_ROOT)}: {exc}")
        return {}

    if not isinstance(registry, dict):
        findings.append("skill validation registry root must be an object")
        return {}
    if registry.get("schema_version") != SCHEMA_VERSION:
        findings.append(
            f"skill validation registry schema_version must be {SCHEMA_VERSION}"
        )
    expected_provenance = {
        "path": "skills/catalog.yaml",
        "schema_version": catalog.schema_version,
        "sha256": catalog.checksum,
    }
    if registry.get("generated_from") != expected_provenance:
        findings.append(
            "skill validation registry generated_from does not match "
            "skills/catalog.yaml"
        )

    catalog = registry.get("skills")
    if not isinstance(catalog, list) or any(
        not isinstance(item, str) or not item for item in catalog
    ):
        findings.append("skill validation registry skills must be a string list")
        catalog = []
    if len(catalog) != len(set(catalog)):
        findings.append("skill validation registry contains duplicate skill names")
    if catalog != sorted(catalog):
        findings.append("skill validation registry skills must be sorted")

    actual_set = set(actual_skills)
    catalog_set = set(catalog)
    missing = sorted(actual_set - catalog_set)
    extra = sorted(catalog_set - actual_set)
    if missing:
        findings.append(f"skill validation registry missing: {', '.join(missing)}")
    if extra:
        findings.append(f"skill validation registry has unknown skills: {', '.join(extra)}")

    raw_evidence = registry.get("evidence", {})
    if not isinstance(raw_evidence, dict):
        findings.append("skill validation registry evidence must be an object")
        raw_evidence = {}
    unknown_evidence_skills = sorted(set(raw_evidence) - actual_set)
    if unknown_evidence_skills:
        findings.append(
            "skill validation evidence has unknown skills: "
            + ", ".join(unknown_evidence_skills)
        )

    normalized: dict[str, dict[str, dict[str, object]]] = {}
    for skill, skill_evidence in raw_evidence.items():
        if skill not in actual_set:
            continue
        if not isinstance(skill_evidence, dict):
            findings.append(f"evidence.{skill}: must be an object")
            continue
        unknown_dimensions = sorted(set(skill_evidence) - set(EVIDENCE_DIMENSIONS))
        if unknown_dimensions:
            findings.append(
                f"evidence.{skill}: unknown dimensions: {', '.join(unknown_dimensions)}"
            )
        normalized[skill] = {}
        for dimension, value in skill_evidence.items():
            if dimension not in EVIDENCE_DIMENSIONS:
                continue
            normalized[skill][dimension] = _validate_evidence_record(
                skill=skill,
                dimension=dimension,
                value=value,
                findings=findings,
            )
    return normalized


def _validation_help(
    skill: str,
    validator: Path,
    findings: list[str],
) -> tuple[list[str], list[str], bool]:
    rel = validator.relative_to(REPO_ROOT).as_posix()
    command = ["bash", rel, "--help"]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        findings.append(f"{skill}: validator help failed: {exc}")
        return command, [], False
    help_ok = completed.returncode == 0
    if completed.returncode != 0:
        output = (completed.stdout + completed.stderr).strip().replace("\n", " ")
        findings.append(
            f"{skill}: validator help exited {completed.returncode}: {output[:300]}"
        )
    flags = sorted(set(FLAG_RE.findall(completed.stdout + completed.stderr)))
    return command, flags, help_ok


def _test_references(
    skill: str,
    test_corpus: list[tuple[Path, str]],
) -> tuple[list[str], list[str]]:
    normalized_name = f"test_{skill.replace('-', '_')}"
    literal = re.compile(
        rf"(?<![a-z0-9-]){re.escape(skill)}(?![a-z0-9-])",
        re.IGNORECASE,
    )
    references: list[str] = []
    dedicated: list[str] = []
    for path, text in test_corpus:
        rel = path.relative_to(REPO_ROOT).as_posix()
        is_dedicated = path.stem == normalized_name
        if is_dedicated:
            dedicated.append(rel)
        if is_dedicated or literal.search(text):
            references.append(rel)
    return sorted(set(references)), sorted(set(dedicated))


def _default_evidence() -> dict[str, object]:
    return {
        "status": "not-recorded",
        "targets": [],
        "last_verified": None,
        "evidence": [],
        "notes": "",
    }


@lru_cache(maxsize=1)
def audit() -> dict[str, Any]:
    findings: list[str] = []
    catalog = load_catalog()
    directories = skill_dirs(catalog)
    names = [path.name for path in directories]
    recorded_evidence = load_registry(names, findings, catalog)
    corpus = [
        (path, path.read_text(encoding="utf-8", errors="replace"))
        for path in test_files()
    ]

    rows: list[dict[str, Any]] = []
    for skill_dir in directories:
        skill = skill_dir.name
        validator = skill_dir / "scripts" / "validate.sh"
        if not validator.is_file():
            findings.append(f"{skill}: missing scripts/validate.sh")
            validation_command: list[str] = []
            flags: list[str] = []
            validator_help_ok = False
        else:
            validation_command, flags, validator_help_ok = _validation_help(
                skill, validator, findings
            )

        references, dedicated = _test_references(skill, corpus)
        smoke_path = skill_dir / "scripts" / "smoke_offline.sh"
        skill_text = (skill_dir / "SKILL.md").read_text(
            encoding="utf-8", errors="replace"
        )
        probe_flags = sorted(
            flag for flag in flags if flag == "--probe" or flag.startswith("--check-")
        )
        modes = {
            "live": "--live" in flags,
            "strict_flags": [
                flag for flag in ("--completion", "--strict") if flag in flags
            ],
            "doctor": "--doctor" in flags,
            "probe_flags": probe_flags,
        }
        evidence = {
            dimension: {
                **_default_evidence(),
                **recorded_evidence.get(skill, {}).get(dimension, {}),
            }
            for dimension in EVIDENCE_DIMENSIONS
        }
        rows.append(
            {
                "skill": skill,
                "validation_command": validation_command,
                "validator": validator.relative_to(REPO_ROOT).as_posix()
                if validator.is_file()
                else None,
                "validator_help_ok": validator_help_ok,
                "advertised_flags": flags,
                "advertised_modes": modes,
                "direct_test_files": references,
                "dedicated_test_files": dedicated,
                "offline_smoke": smoke_path.relative_to(REPO_ROOT).as_posix()
                if smoke_path.is_file()
                else None,
                "ta_completion_gate": "ta_completion_gate.md" in skill_text,
                "recorded_evidence": evidence,
            }
        )

    summary = {
        "skills": len(rows),
        "interface_contract": sum(row["validator_help_ok"] for row in rows),
        "direct_test_references": sum(bool(row["direct_test_files"]) for row in rows),
        "dedicated_test_modules": sum(bool(row["dedicated_test_files"]) for row in rows),
        "offline_smoke": sum(bool(row["offline_smoke"]) for row in rows),
        "advertised_live": sum(row["advertised_modes"]["live"] for row in rows),
        "strict_or_completion": sum(
            bool(row["advertised_modes"]["strict_flags"]) for row in rows
        ),
        "ta_completion_gate": sum(row["ta_completion_gate"] for row in rows),
        "recorded_results": {
            dimension: {
                status: sum(
                    row["recorded_evidence"][dimension]["status"] == status
                    for row in rows
                )
                for status in sorted(EVIDENCE_STATUSES)
            }
            for dimension in EVIDENCE_DIMENSIONS
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_sha256": catalog.checksum,
        "ok": not findings,
        "findings": findings,
        "summary": summary,
        "skills": rows,
    }


def main() -> int:
    args = parse_args()
    payload = audit()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif payload["ok"]:
        summary = payload["summary"]
        print(
            "Skill validation audit passed: "
            f"{summary['skills']} skills, "
            f"{summary['direct_test_references']} with direct test references, "
            f"{summary['offline_smoke']} with offline smoke scripts."
        )
    else:
        for finding in payload["findings"]:
            print(f"ERROR: {finding}", file=sys.stderr)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
