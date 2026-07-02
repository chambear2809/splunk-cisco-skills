from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "splunk-itsi-config" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.common import ValidationError, bool_from_any, compact  # noqa: E402
from lib.spec_validation import validate_spec  # noqa: E402


class StrictBooleanTests(unittest.TestCase):
    def test_unknown_boolean_strings_never_fall_back_to_truthiness(self) -> None:
        for value in ("flase", "tru", "disable", "garbage", 2, -1, [], {}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                bool_from_any(value, field="cleanup.allow_destroy")

    def test_documented_boolean_vocabulary_is_explicit(self) -> None:
        for value in (True, 1, "true", "yes", "on", "enabled"):
            with self.subTest(value=value):
                self.assertTrue(bool_from_any(value))
        for value in (False, 0, "false", "no", "off", "disabled"):
            with self.subTest(value=value):
                self.assertFalse(bool_from_any(value, default=True))

    def test_destructive_guard_typos_are_path_specific_lint_errors(self) -> None:
        guarded_fields = (
            "allow_destroy",
            "allow_high_risk_deletes",
            "allow_restore",
            "allow_operational_action",
            "allow_episode_export_delete",
            "allow_bulk_update",
            "disconnect_all",
            "retire_all_retirable",
        )
        for field in guarded_fields:
            spec = {
                "schema_version": 1,
                "operational_actions": [{"action": "entity_restore", field: "flase"}],
            }
            with self.subTest(field=field), self.assertRaisesRegex(ValidationError, field):
                validate_spec(spec, "native")

    def test_compact_preserves_explicit_empty_lists_for_reconciliation(self) -> None:
        self.assertEqual(compact({"entity_rules": [], "kpis": [], "unset": None}), {"entity_rules": [], "kpis": []})


class SpecValidationTests(unittest.TestCase):
    def test_rejects_unknown_top_level_fields(self) -> None:
        with self.assertRaisesRegex(ValidationError, "servcies"):
            validate_spec({"schema_version": 1, "servcies": []}, "native")

    def test_rejects_duplicate_services_and_kpis(self) -> None:
        with self.assertRaisesRegex(ValidationError, "duplicates"):
            validate_spec(
                {
                    "schema_version": 1,
                    "services": [{"title": "API"}, {"title": "api"}],
                },
                "native",
            )
        with self.assertRaisesRegex(ValidationError, "duplicates KPI"):
            validate_spec(
                {
                    "schema_version": 1,
                    "services": [
                        {"title": "API", "kpis": [{"title": "Latency"}, {"title": "latency"}]}
                    ],
                },
                "native",
            )

    def test_rejects_self_dependencies_and_cycles(self) -> None:
        with self.assertRaisesRegex(ValidationError, "cannot depend on itself"):
            validate_spec(
                {"schema_version": 1, "services": [{"title": "A", "depends_on": ["A"]}]},
                "native",
            )
        with self.assertRaisesRegex(ValidationError, "cycle detected"):
            validate_spec(
                {
                    "schema_version": 1,
                    "services": [
                        {"title": "A", "depends_on": ["B"]},
                        {"title": "B", "depends_on": ["C"]},
                        {"title": "C", "depends_on": ["A"]},
                    ],
                },
                "native",
            )

    def test_entities_must_remain_global(self) -> None:
        with self.assertRaisesRegex(ValidationError, "Global objects"):
            validate_spec(
                {"schema_version": 1, "entities": [{"title": "host-1", "sec_grp": "private-team"}]},
                "native",
            )

    def test_itsi_presence_gate_cannot_be_disabled(self) -> None:
        with self.assertRaisesRegex(ValidationError, "requires an existing ITSI"):
            validate_spec(
                {"schema_version": 1, "itsi": {"require_present": False}, "services": []},
                "native",
            )

    def test_template_and_placeholder_specs_cannot_apply(self) -> None:
        with self.assertRaisesRegex(ValidationError, "metadata.template is true"):
            validate_spec(
                {"schema_version": 1, "metadata": {"template": True}, "services": [{"title": "API"}]},
                "native",
                for_apply=True,
            )
        with self.assertRaisesRegex(ValidationError, "placeholder"):
            validate_spec(
                {"schema_version": 1, "services": [{"title": "replace-with-service"}]},
                "native",
                for_apply=True,
            )

    def test_operational_records_and_experimental_schemas_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValidationError, "operational Event iQ records"):
            validate_spec(
                {"schema_version": 1, "summarization_feedback": [{"title": "feedback-1"}]},
                "native",
                for_apply=True,
            )
        with self.assertRaisesRegex(ValidationError, "blocked by default"):
            validate_spec(
                {"schema_version": 1, "sandboxes": [{"title": "sandbox-1"}]},
                "native",
                for_apply=True,
            )
        with self.assertRaisesRegex(ValidationError, "summarization_rules"):
            validate_spec(
                {"schema_version": 1, "summarization_rules": [{"title": "Diagnose"}]},
                "native",
                for_apply=True,
            )
        validate_spec(
            {
                "schema_version": 1,
                "metadata": {"allow_experimental_api": True},
                "sandboxes": [{"title": "sandbox-1"}],
            },
            "native",
            for_apply=True,
        )

    def test_neap_priority_range_is_enforced(self) -> None:
        for priority in (-1, 1000, "5", True):
            with self.subTest(priority=priority), self.assertRaisesRegex(ValidationError, "0 through 999"):
                validate_spec(
                    {"schema_version": 1, "neaps": [{"title": "Policy", "priority": priority}]},
                    "native",
                )


class OfflineLintCliTests(unittest.TestCase):
    def test_all_starters_lint_from_repository_root_without_credentials(self) -> None:
        cases = (
            ("native", "native.example.yaml"),
            ("content-packs", "beginner.content-pack.yaml"),
            ("topology", "beginner.topology.yaml"),
        )
        environment = {key: value for key, value in os.environ.items() if not key.startswith("SPLUNK_")}
        for workflow, filename in cases:
            with self.subTest(workflow=workflow):
                completed = subprocess.run(
                    [
                        "bash",
                        "skills/splunk-itsi-config/scripts/setup.sh",
                        "--workflow",
                        workflow,
                        "--spec",
                        f"skills/splunk-itsi-config/templates/{filename}",
                        "--mode",
                        "lint",
                    ],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                payload = json.loads(completed.stdout)
                self.assertEqual(payload["network_requests"], 0)

    def test_mode_apply_is_rejected_before_credentials_or_network(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            spec_path = Path(tempdir) / "spec.json"
            spec_path.write_text('{"schema_version":1,"services":[{"title":"API"}]}', encoding="utf-8")
            completed = subprocess.run(
                [
                    "bash",
                    "skills/splunk-itsi-config/scripts/setup.sh",
                    "--workflow",
                    "native",
                    "--spec",
                    str(spec_path),
                    "--mode",
                    "apply",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("use the explicit --apply flag", completed.stderr)


if __name__ == "__main__":
    unittest.main()
