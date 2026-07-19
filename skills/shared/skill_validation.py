#!/usr/bin/env python3
"""Dependency-free validation for the maintained skill evidence extension."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path


EVIDENCE_DIMENSIONS = (
    "integration_mock",
    "live_read_only",
    "live_apply_e2e",
)
EVIDENCE_STATUSES = {
    "not-recorded",
    "pass",
    "partial",
    "fail",
    "blocked",
    "not-applicable",
}
EVIDENCE_FIELDS = {
    "status",
    "targets",
    "last_verified",
    "evidence",
    "notes",
}
RECORDED_RESULT_STATUSES = {"pass", "partial", "fail"}
CALENDAR_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _string_list(
    value: object,
    *,
    field: str,
    context: str,
    findings: list[str],
) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        for item in value
    ):
        findings.append(f"{context}.{field}: must be a list of non-empty strings")
        return []
    if len(value) != len(set(value)):
        findings.append(f"{context}.{field}: must not contain duplicate values")
    return sorted(value)


def _evidence_reference_is_valid(reference: str, repo_root: Path) -> bool:
    if reference.startswith(("https://", "http://")):
        return True
    path = Path(reference)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and (repo_root / path).is_file()
    )


def normalize_evidence_record(
    *,
    skill: str,
    dimension: str,
    value: object,
    repo_root: Path,
) -> tuple[dict[str, object], list[str]]:
    """Validate one evidence record and return its deterministic representation."""

    findings: list[str] = []
    context = f"evidence.{skill}.{dimension}"
    if not isinstance(value, dict):
        return {"status": "not-recorded"}, [f"{context}: must be an object"]

    unknown_fields = sorted(set(value) - EVIDENCE_FIELDS)
    missing_fields = sorted(EVIDENCE_FIELDS - set(value))
    if unknown_fields:
        findings.append(f"{context}: unknown fields: {', '.join(unknown_fields)}")
    if missing_fields:
        findings.append(f"{context}: missing fields: {', '.join(missing_fields)}")

    status = value.get("status")
    if not isinstance(status, str) or status not in EVIDENCE_STATUSES:
        findings.append(
            f"{context}.status: expected one of {', '.join(sorted(EVIDENCE_STATUSES))}"
        )
        status = "not-recorded"

    targets = _string_list(
        value.get("targets", []),
        field="targets",
        context=context,
        findings=findings,
    )
    evidence = _string_list(
        value.get("evidence", []),
        field="evidence",
        context=context,
        findings=findings,
    )
    for reference in evidence:
        if not _evidence_reference_is_valid(reference, repo_root):
            findings.append(
                f"{context}.evidence: {reference!r} must be an HTTP(S) URL or an "
                "existing repository-relative file"
            )

    last_verified = value.get("last_verified")
    if last_verified is not None and not isinstance(last_verified, str):
        findings.append(f"{context}.last_verified: must be an ISO date or null")
        last_verified = None
    if isinstance(last_verified, str):
        try:
            parsed_date = date.fromisoformat(last_verified)
        except ValueError:
            parsed_date = None
        if (
            not CALENDAR_DATE_RE.fullmatch(last_verified)
            or parsed_date is None
            or parsed_date.isoformat() != last_verified
        ):
            findings.append(f"{context}.last_verified: must use YYYY-MM-DD")

    notes = value.get("notes", "")
    if not isinstance(notes, str):
        findings.append(f"{context}.notes: must be a string")
        notes = ""
    elif notes != notes.strip():
        findings.append(f"{context}.notes: must not have leading or trailing whitespace")
        notes = notes.strip()

    if status in RECORDED_RESULT_STATUSES:
        if not targets:
            findings.append(f"{context}: {status} requires at least one target")
        if not evidence:
            findings.append(f"{context}: {status} requires sanitized evidence")
        if not last_verified:
            findings.append(f"{context}: {status} requires last_verified")
    if status in {"blocked", "not-applicable"} and not notes:
        findings.append(f"{context}: {status} requires notes")

    return (
        {
            "status": status,
            "targets": targets,
            "last_verified": last_verified,
            "evidence": evidence,
            "notes": notes,
        },
        findings,
    )


def normalize_evidence_extension(
    value: object,
    *,
    known_skills: set[str],
    repo_root: Path,
) -> tuple[dict[str, dict[str, dict[str, object]]], list[str]]:
    """Validate and deterministically order the complete evidence mapping."""

    if not isinstance(value, dict):
        return {}, ["skill validation registry evidence must be an object"]
    findings: list[str] = []
    unknown_skills = sorted(set(value) - known_skills)
    if unknown_skills:
        findings.append(
            "skill validation evidence has unknown skills: "
            + ", ".join(unknown_skills)
        )

    normalized: dict[str, dict[str, dict[str, object]]] = {}
    for skill in sorted(set(value) & known_skills):
        skill_evidence = value[skill]
        if not isinstance(skill_evidence, dict):
            findings.append(f"evidence.{skill}: must be an object")
            continue
        unknown_dimensions = sorted(
            set(skill_evidence) - set(EVIDENCE_DIMENSIONS)
        )
        if unknown_dimensions:
            findings.append(
                f"evidence.{skill}: unknown dimensions: "
                + ", ".join(unknown_dimensions)
            )
        normalized[skill] = {}
        for dimension in EVIDENCE_DIMENSIONS:
            if dimension not in skill_evidence:
                continue
            record, record_findings = normalize_evidence_record(
                skill=skill,
                dimension=dimension,
                value=skill_evidence[dimension],
                repo_root=repo_root,
            )
            findings.extend(record_findings)
            normalized[skill][dimension] = record
    return normalized, findings
