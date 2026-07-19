"""Regression coverage for the generated skill validation matrix."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "skills/shared/scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import audit_skill_validation as validation_audit  # noqa: E402
import generate_skill_validation_matrix as matrix_generator  # noqa: E402
from skills.shared.skill_catalog import load_catalog  # noqa: E402


MATRIX_PATH = REPO_ROOT / "SKILL_VALIDATION_MATRIX.md"


def repository_skills() -> set[str]:
    return set(load_catalog().by_name)


def test_validation_audit_covers_every_skill_and_passes() -> None:
    payload = validation_audit.audit()
    rows = payload["skills"]
    names = [row["skill"] for row in rows]

    assert payload["ok"], payload["findings"]
    assert set(names) == repository_skills()
    assert len(names) == len(set(names))
    assert payload["summary"]["interface_contract"] == len(names)


def test_generated_validation_matrix_is_current() -> None:
    assert MATRIX_PATH.read_text(encoding="utf-8") == matrix_generator.render()


def test_matrix_has_exactly_one_row_per_skill() -> None:
    text = MATRIX_PATH.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\| \[`([^`]+)`\]\(skills/[^)]+/SKILL\.md\) \|",
        text,
        flags=re.MULTILINE,
    )

    assert set(rows) == repository_skills()
    assert len(rows) == len(set(rows))


def test_matrix_does_not_promote_interface_checks_to_feature_results() -> None:
    text = MATRIX_PATH.read_text(encoding="utf-8")

    assert "working `--help` interface is an interface contract" in text
    assert "it is never" in text
    assert "availability is not a pass result" in text
    assert "Gitignored local live-run reports are not promoted" in text


def test_alias_rows_are_help_only_and_delegate_validation() -> None:
    catalog = load_catalog()
    text = MATRIX_PATH.read_text(encoding="utf-8")

    for legacy, canonical in catalog.aliases.items():
        row = next(
            line
            for line in text.splitlines()
            if line.startswith(f"| [`{legacy}`](skills/{legacy}/SKILL.md) |")
        )
        assert f"**Deprecated** -> `{canonical}`" in row
        assert "Help-only alias; no independent validation" in row
        assert f"skills/{canonical}/SKILL.md" in row
        assert "test_deprecated_skill_aliases.py" in row
        assert "default path only" not in row


def test_recorded_results_require_target_date_and_sanitized_evidence() -> None:
    findings: list[str] = []
    validation_audit._validate_evidence_record(
        skill="example-skill",
        dimension="live_read_only",
        value={"status": "pass"},
        findings=findings,
    )

    assert any("requires at least one target" in finding for finding in findings)
    assert any("requires sanitized evidence" in finding for finding in findings)
    assert any("requires last_verified" in finding for finding in findings)


def test_recorded_result_date_requires_calendar_format() -> None:
    findings: list[str] = []
    validation_audit._validate_evidence_record(
        skill="example-skill",
        dimension="live_read_only",
        value={"status": "not-recorded", "last_verified": "20260705"},
        findings=findings,
    )

    assert any("must use YYYY-MM-DD" in finding for finding in findings)


def test_validator_help_success_is_not_inferred_from_command_presence(
    monkeypatch,
) -> None:
    def failed_help(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=["bash", "validator", "--help"],
            returncode=2,
            stdout="",
            stderr="bad help",
        )

    monkeypatch.setattr(validation_audit.subprocess, "run", failed_help)
    findings: list[str] = []
    validator = REPO_ROOT / "skills/cisco-product-setup/scripts/validate.sh"

    command, flags, help_ok = validation_audit._validation_help(
        "cisco-product-setup", validator, findings
    )

    assert command
    assert flags == []
    assert help_ok is False
    assert any("validator help exited 2" in finding for finding in findings)
