#!/usr/bin/env python3
"""Generate the repository-wide skill validation matrix."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_skill_validation import (  # noqa: E402
    EVIDENCE_DIMENSIONS,
    RECORDED_RESULT_STATUSES,
    REPO_ROOT,
    audit,
)


OUTPUT_PATH = REPO_ROOT / "SKILL_VALIDATION_MATRIX.md"
GENERATED_BANNER = (
    "_Generated from the checked-in skill/test surfaces and "
    "`skills/shared/skill_validation_registry.json` by "
    "`skills/shared/scripts/generate_skill_validation_matrix.py`; "
    "do not edit manually._"
)
STATUS_LABELS = {
    "not-recorded": "Not recorded",
    "pass": "Pass",
    "partial": "Partial",
    "fail": "Fail",
    "blocked": "Blocked",
    "not-applicable": "Not applicable",
}
DIMENSION_LABELS = {
    "integration_mock": "Integration/mock",
    "live_read_only": "Live read-only",
    "live_apply_e2e": "Live apply/E2E",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if SKILL_VALIDATION_MATRIX.md is stale.",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Write SKILL_VALIDATION_MATRIX.md.",
    )
    return parser.parse_args()


def escape(value: object) -> str:
    return str(value).replace("|", r"\|").replace("\n", "<br>")


def link(path: str, label: str | None = None) -> str:
    return f"[{escape(label or Path(path).name)}]({path})"


def compact_references(paths: list[str], *, limit: int = 2) -> str:
    if not paths:
        return "None beyond shared contracts"
    shown = ", ".join(link(path) for path in paths[:limit])
    remaining = len(paths) - limit
    suffix = f" +{remaining} more" if remaining > 0 else ""
    return f"{len(paths)} ref{'s' if len(paths) != 1 else ''}: {shown}{suffix}"


def validation_surface(row: dict[str, Any]) -> str:
    validator = row.get("validator")
    if not validator:
        return "Missing"
    details: list[str] = []
    modes = row["advertised_modes"]
    if modes["live"]:
        details.append("`--live`")
    details.extend(f"`{flag}`" for flag in modes["strict_flags"])
    if modes["doctor"]:
        details.append("`--doctor`")
    probe_flags = modes["probe_flags"]
    if probe_flags:
        details.append(
            f"{len(probe_flags)} explicit check/probe mode"
            f"{'s' if len(probe_flags) != 1 else ''}"
        )
    mode_text = "; ".join(details) if details else "default path only"
    return f"{link(validator)}<br>{mode_text}"


def evidence_links(references: list[str]) -> str:
    rendered: list[str] = []
    for reference in references:
        if reference.startswith(("https://", "http://")):
            rendered.append(f"[external evidence]({reference})")
        else:
            rendered.append(link(reference))
    return ", ".join(rendered)


def evidence_cell(record: dict[str, object]) -> str:
    status = str(record["status"])
    label = STATUS_LABELS.get(status, status)
    if status == "not-recorded":
        return label

    details: list[str] = []
    targets = [str(value) for value in record.get("targets", [])]
    if targets:
        details.append("targets: " + ", ".join(escape(value) for value in targets))
    last_verified = record.get("last_verified")
    if last_verified:
        details.append(f"verified: {escape(last_verified)}")
    references = [str(value) for value in record.get("evidence", [])]
    if references:
        details.append("evidence: " + evidence_links(references))
    notes = str(record.get("notes", "")).strip()
    if notes:
        details.append(escape(notes))
    return f"{label}<br>" + "<br>".join(details) if details else label


def render() -> str:
    payload = audit()
    if not payload["ok"]:
        raise RuntimeError(
            "skill validation audit failed:\n- " + "\n- ".join(payload["findings"])
        )
    summary = payload["summary"]
    recorded_counts = {
        dimension: sum(
            summary["recorded_results"][dimension][status]
            for status in RECORDED_RESULT_STATUSES
        )
        for dimension in EVIDENCE_DIMENSIONS
    }

    lines = [
        "# Skill Validation Matrix",
        "",
        GENERATED_BANNER,
        "",
        "This matrix separates checked-in validation capability from observed target",
        "results. A working `--help` interface is an interface contract; it is never",
        "reported as feature, ingest, dashboard, mutation, or end-to-end validation.",
        "Environment-specific results appear only when sanitized evidence is deliberately",
        "recorded in the registry. Gitignored local live-run reports are not promoted",
        "automatically.",
        "",
        "## Summary",
        "",
        "| Dimension | Skills | What the count means |",
        "| --- | ---: | --- |",
        f"| Interface contract | {summary['interface_contract']} / {summary['skills']} "
        "| CI can invoke the checked-in validator help surface. |",
        f"| Direct automated test reference | {summary['direct_test_references']} / "
        f"{summary['skills']} | At least one test file names the exact skill or is its "
        "dedicated module; this does not imply full behavioral coverage. |",
        f"| Dedicated test module | {summary['dedicated_test_modules']} / "
        f"{summary['skills']} | A `test_<skill_name>` Python or Bats module exists. |",
        f"| Standalone offline smoke | {summary['offline_smoke']} / {summary['skills']} "
        "| The skill ships `scripts/smoke_offline.sh`. |",
        f"| Advertised live mode | {summary['advertised_live']} / {summary['skills']} "
        "| Validator help explicitly exposes `--live`; availability is not a pass result. |",
        f"| Strict/completion mode | {summary['strict_or_completion']} / "
        f"{summary['skills']} | Validator help exposes `--strict` or `--completion`. |",
        f"| TA/app completion gate | {summary['ta_completion_gate']} / {summary['skills']} "
        "| The skill requires ingest plus dashboard/macro evidence, or no-dashboard proof. |",
        f"| Recorded integration/mock result | {recorded_counts['integration_mock']} / "
        f"{summary['skills']} | A sanitized result is checked into the evidence registry. |",
        f"| Recorded live read-only result | {recorded_counts['live_read_only']} / "
        f"{summary['skills']} | A sanitized target-backed read-only result is checked in. |",
        f"| Recorded live apply/E2E result | {recorded_counts['live_apply_e2e']} / "
        f"{summary['skills']} | A sanitized apply/readback/rollback or E2E result is checked in. |",
        "",
        "## Interpretation",
        "",
        "- Shared contract checks cover frontmatter, metadata, required files, strict shell",
        "  mode, executable setup/validation entrypoints, and working help interfaces.",
        "- Direct test references and offline smoke scripts are discoverable repository",
        "  evidence. They are not substitutes for target-backed validation.",
        "- `--live`, `--strict`, and `--completion` are advertised capabilities only. A",
        "  result remains **Not recorded** until target, date, and sanitized evidence are",
        "  added to `skills/shared/skill_validation_registry.json`.",
        "- TA/app completion follows",
        "  [`skills/shared/ta_completion_gate.md`](skills/shared/ta_completion_gate.md):",
        "  package installation alone is insufficient.",
        "- Recorded statuses are `pass`, `partial`, `fail`, `blocked`, or",
        "  `not-applicable`. Pass/partial/fail records require an ISO date, target, and",
        "  a checked-in file or HTTP(S) evidence link.",
        "",
        "## Recording Environment Evidence",
        "",
        "Add only sanitized evidence under one of `integration_mock`, `live_read_only`,",
        "or `live_apply_e2e`. For example:",
        "",
        "```json",
        "{",
        '  "evidence": {',
        '    "<skill-name>": {',
        '      "live_read_only": {',
        '        "status": "pass",',
        '        "targets": ["Splunk Enterprise 10.4 lab"],',
        '        "last_verified": "2026-07-05",',
        '        "evidence": ["https://ci.example.invalid/runs/123"],',
        '        "notes": "Read-only feature checks passed."',
        "      }",
        "    }",
        "  }",
        "}",
        "```",
        "",
        "Use `blocked` or `not-applicable` with a non-empty `notes` reason. Do not",
        "record secrets, local credential paths, or unsanitized live-run output.",
        "",
        "## Complete Matrix",
        "",
        "| Skill | Validator / advertised modes | Direct test references | Offline smoke "
        "| TA completion gate | Integration/mock | Live read-only | Live apply/E2E |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for row in payload["skills"]:
        skill = row["skill"]
        skill_link = f"[`{skill}`](skills/{skill}/SKILL.md)"
        smoke = link(row["offline_smoke"]) if row["offline_smoke"] else "Not provided"
        gate = (
            "[Required](skills/shared/ta_completion_gate.md)"
            if row["ta_completion_gate"]
            else "Not referenced"
        )
        recorded = row["recorded_evidence"]
        lines.append(
            f"| {skill_link} | {validation_surface(row)} "
            f"| {compact_references(row['direct_test_files'])} | {smoke} | {gate} "
            f"| {evidence_cell(recorded['integration_mock'])} "
            f"| {evidence_cell(recorded['live_read_only'])} "
            f"| {evidence_cell(recorded['live_apply_e2e'])} |"
        )

    lines.extend(
        [
            "",
            "## Maintenance",
            "",
            "When a skill is added, add its name to the sorted `skills` array in",
            "`skills/shared/skill_validation_registry.json`; catalog parity is fail-closed.",
            "Test references, offline smoke scripts, validator modes, and completion-gate",
            "references are discovered automatically. Record only sanitized, reviewable",
            "environment evidence under the relevant skill and dimension, then regenerate:",
            "",
            "```bash",
            "python3 skills/shared/scripts/audit_skill_validation.py",
            "python3 skills/shared/scripts/generate_skill_validation_matrix.py --write",
            "python3 skills/shared/scripts/generate_skill_validation_matrix.py --check",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    rendered = render()
    if args.write:
        OUTPUT_PATH.write_text(rendered, encoding="utf-8")
        return 0
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current != rendered:
            print(
                "SKILL_VALIDATION_MATRIX.md is out of date. Run "
                "`python3 skills/shared/scripts/generate_skill_validation_matrix.py "
                "--write`.",
                file=sys.stderr,
            )
            return 1
        return 0
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
