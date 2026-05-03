"""Validation tests for the splunk-oncall-setup spec validator."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-oncall-setup/scripts/setup.sh"


def run_setup(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def write_spec(path: Path, **overrides) -> Path:
    spec = {
        "api_version": "splunk-oncall-setup/v1",
        "users": [],
        "teams": [],
        "rotations": [],
        "escalation_policies": [],
        "routing_keys": [],
        "scheduled_overrides": [],
        "alert_rules": [],
        "maintenance_mode": [],
        "incidents": [],
        "notes": [],
        "chat_messages": [],
        "stakeholder_messages": [],
        "webhooks": [],
        "reporting": [],
        "schedules": [],
        "rest_alerts": [],
        "email_alerts": [],
        "integrations": [],
        "reports": [],
        "calendars": [],
        "mobile": [],
    }
    spec.update(overrides)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return path


def test_direct_secret_flag_is_rejected(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json", users=[])
    result = run_setup("--render", "--spec", str(spec), "--api-key", "INLINE_SECRET")
    assert result.returncode == 1
    assert "--api-key-file" in combined_output(result)


def test_inline_secret_field_in_spec_is_rejected(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        users=[
            {
                "kind": "create",
                "username": "alice",
                "role": "user",
                "api_key": "INLINE_SECRET",
            }
        ],
    )
    result = run_setup("--validate", "--spec", str(spec))
    assert result.returncode == 1
    assert "Inline secret field" in combined_output(result)


def test_role_allowlist_rejects_unknown_role(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        users=[{"kind": "create", "username": "alice", "role": "super_admin"}],
    )
    result = run_setup("--validate", "--spec", str(spec))
    assert result.returncode == 1
    assert "role" in combined_output(result)


def test_message_type_allowlist_is_enforced(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        rest_alerts=[{"alert_name": "x", "message_type": "PANIC", "entity_id": "z"}],
    )
    result = run_setup("--validate", "--spec", str(spec))
    assert result.returncode == 1
    assert "message_type" in combined_output(result)


def test_annotation_value_length_limit_is_enforced(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        rest_alerts=[
            {
                "alert_name": "long",
                "message_type": "INFO",
                "entity_id": "z",
                "annotations": [
                    {"kind": "note", "title": "Huge", "value": "x" * 1200},
                ],
            }
        ],
    )
    result = run_setup("--validate", "--spec", str(spec))
    assert result.returncode == 1
    assert "1124-char" in combined_output(result)


def test_escalation_policy_target_type_allowlist(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        teams=[{"kind": "create", "name": "Team A"}],
        escalation_policies=[
            {
                "kind": "create",
                "team": "Team A",
                "name": "Policy A",
                "steps": [
                    {
                        "timeout_minutes": 0,
                        "targets": [{"type": "DepartmentHead", "slug": "boss"}],
                    }
                ],
            }
        ],
    )
    result = run_setup("--validate", "--spec", str(spec))
    assert result.returncode == 1
    output = combined_output(result).lower()
    assert "user | team | escalationpolicy | rotationgroup" in output


def test_referential_integrity_rotation_must_reference_known_team(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        teams=[{"kind": "create", "name": "Existing Team"}],
        rotations=[
            {
                "kind": "create",
                "team": "Unknown Team",
                "name": "rot",
                "shifts": [{"name": "shift1"}],
            }
        ],
    )
    result = run_setup("--validate", "--spec", str(spec))
    assert result.returncode == 1
    assert "unknown team" in combined_output(result)


def test_webhook_event_type_allowlist(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        webhooks=[
            {
                "kind": "planned",
                "url": "https://example.com",
                "method": "POST",
                "eventType": "Bogus-Event",
            }
        ],
    )
    result = run_setup("--validate", "--spec", str(spec))
    assert result.returncode == 1
    assert "eventType" in combined_output(result)


def test_alert_rule_match_type_allowlist(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        alert_rules=[{"kind": "create", "alertField": "monitoring_tool", "matchType": "FUZZY"}],
    )
    result = run_setup("--validate", "--spec", str(spec))
    assert result.returncode == 1
    assert "matchType" in combined_output(result)


def test_validate_passes_for_minimal_spec(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--validate", "--spec", str(spec))
    assert result.returncode == 0, combined_output(result)


def test_username_with_whitespace_or_path_separator_is_rejected(tmp_path: Path) -> None:
    for bad_username in ("alice bob", "alice/admin", "..\\..\\etc"):
        spec = write_spec(
            tmp_path / "spec.json",
            users=[{"kind": "create", "username": bad_username, "role": "user"}],
        )
        result = run_setup("--validate", "--spec", str(spec))
        assert result.returncode == 1
        assert "username" in combined_output(result).lower()


def test_contact_methods_email_or_phone_is_required_string(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        users=[
            {
                "kind": "create",
                "username": "alice",
                "role": "user",
                "contact_methods": {"emails": [{"rank": 1}]},
            }
        ],
    )
    result = run_setup("--validate", "--spec", str(spec))
    assert result.returncode == 1
    assert "email" in combined_output(result).lower()


def test_devices_contact_method_is_rejected(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "spec.json",
        users=[
            {
                "kind": "create",
                "username": "alice",
                "role": "user",
                "contact_methods": {"devices": [{"deviceId": "ios-1"}]},
            }
        ],
    )
    result = run_setup("--validate", "--spec", str(spec))
    assert result.returncode == 1
    assert "devices" in combined_output(result).lower()


def test_rendered_output_validator_rejects_angle_bracket_placeholders(tmp_path: Path) -> None:
    """The rendered output validator must catch ``<...>`` placeholders the
    same way it catches ``{...}`` placeholders, because we now use both
    forms to mark unresolved slugs.
    """
    output_dir = tmp_path / "rendered"
    output_dir.mkdir()
    (output_dir / "metadata.json").write_text(
        json.dumps({"mode": "splunk-oncall", "api_version": "splunk-oncall-setup/v1"}),
        encoding="utf-8",
    )
    (output_dir / "coverage-report.json").write_text(
        json.dumps({"api_version": "splunk-oncall-setup/v1", "objects": []}),
        encoding="utf-8",
    )
    (output_dir / "deeplinks.json").write_text("{}", encoding="utf-8")
    (output_dir / "handoff.md").write_text("placeholder\n", encoding="utf-8")
    (output_dir / "apply-plan.json").write_text(
        json.dumps({
            "mode": "splunk-oncall",
            "actions": [
                {
                    "action": "x",
                    "service": "on_call",
                    "method": "GET",
                    "path": "/api-public/v1/team/<team_slug>/members",
                    "coverage": "api_validate",
                }
            ],
        }),
        encoding="utf-8",
    )
    result = run_setup("--validate", "--output-dir", str(output_dir))
    assert result.returncode == 1
    assert "unresolved placeholder" in combined_output(result)
