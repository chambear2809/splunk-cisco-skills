"""Regression tests for the continuous live validation runner."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.regression_helpers import REPO_ROOT


RUNNER_PATH = REPO_ROOT / "skills/splunk-admin-doctor/scripts/live_validate_all.py"

spec = importlib.util.spec_from_file_location("splunk_live_validation", RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


class LiveValidationRunnerTests(unittest.TestCase):
    def test_plan_covers_every_skill_with_read_only_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            steps = runner.build_plan(
                profile="onprem_2535",
                run_dir=run_dir,
                allow_apply=True,
            )

        skills = {
            path.name
            for path in (REPO_ROOT / "skills").iterdir()
            if path.is_dir() and path.name != "shared" and (path / "SKILL.md").is_file()
        }
        planned_skills = {step.skill for step in steps if step.skill}

        self.assertTrue(skills.issubset(planned_skills))
        self.assertTrue(any(step.category == "baseline" for step in steps))
        self.assertTrue(any(step.category == "doctor" for step in steps))
        self.assertTrue(any(step.category == "apply" for step in steps))
        self.assertIn("splunk-admin-doctor:doctor-live-evidence", {step.step_id for step in steps})

    def test_apply_steps_are_checkpointable_and_explicitly_mark_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = runner.build_apply_steps(Path(tmpdir), allow_apply=True)

        by_id = {step.step_id: step for step in steps}
        self.assertEqual(set(by_id), {"splunk-admin-doctor:render-fix-plan"})
        step = by_id["splunk-admin-doctor:render-fix-plan"]
        self.assertFalse(step.mutates)
        self.assertIn("--phase", step.command)
        self.assertIn("fix-plan", step.command)
        self.assertIn("rollback_or_validation", step.metadata)
        for step in steps:
            self.assertIn("rollback_or_validation", step.metadata) if step.category == "apply" and not step.skip_reason else None

    def test_plan_includes_ssh_baseline_but_no_remote_apply_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            baseline_steps = runner.build_baseline_steps("onprem_2535", run_dir)
            apply_steps = runner.build_apply_steps(run_dir, allow_apply=True)

        baseline_by_id = {step.step_id: step for step in baseline_steps}
        self.assertIn("baseline-ssh-splunk-version", baseline_by_id)
        self.assertIn("baseline-ssh-splunk-status", baseline_by_id)
        self.assertIn("baseline-ssh-btool-check", baseline_by_id)
        self.assertTrue(baseline_by_id["baseline-ssh-splunk-version"].required)
        self.assertFalse(baseline_by_id["baseline-ssh-btool-check"].required)
        self.assertEqual("intentional-skip", baseline_by_id["baseline-ssh-btool-check"].final_on_failure)

        self.assertTrue(apply_steps)
        self.assertFalse(any(step.mutates for step in apply_steps))
        self.assertFalse(any(step.mode.startswith("ssh") for step in apply_steps))

    def test_selected_and_skipped_skill_scope_cannot_expand_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            doctor_only = runner.build_plan(
                profile="onprem_2535",
                run_dir=run_dir,
                allow_apply=True,
                selected_skills={"splunk-admin-doctor"},
            )
            other_only = runner.build_plan(
                profile="onprem_2535",
                run_dir=run_dir,
                allow_apply=True,
                selected_skills={"splunk-hec-service-setup"},
            )
            doctor_skipped = runner.build_plan(
                profile="onprem_2535",
                run_dir=run_dir,
                allow_apply=True,
                skip_skills={"splunk-admin-doctor"},
            )

        self.assertIn("splunk-admin-doctor:render-fix-plan", {step.step_id for step in doctor_only})
        self.assertNotIn("splunk-admin-doctor:render-fix-plan", {step.step_id for step in other_only})
        self.assertNotIn("splunk-admin-doctor:render-fix-plan", {step.step_id for step in doctor_skipped})
        self.assertFalse(any(step.mutates for step in doctor_only + other_only + doctor_skipped))

    def test_cloud_plan_omits_enterprise_ssh_and_targets_cloud_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = runner.build_plan(
                profile="cloud_profile",
                run_dir=Path(tmpdir),
                allow_apply=True,
                platform="cloud",
                selected_skills={"splunk-admin-doctor"},
            )

        self.assertFalse(any(step.mode.startswith("ssh") for step in steps))
        self.assertFalse(any(step.mutates for step in steps))
        doctor_step = next(step for step in steps if step.step_id == "splunk-admin-doctor:doctor-live-evidence")
        platform_index = doctor_step.command.index("--platform")
        self.assertEqual(doctor_step.command[platform_index + 1], "cloud")

    def test_commands_do_not_use_direct_secret_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = runner.build_plan(profile="onprem_2535", run_dir=Path(tmpdir), allow_apply=True)

        for step in steps:
            with self.subTest(step=step.step_id):
                self.assertFalse(runner.command_uses_direct_secret(step.command), step.command)
                rendered = runner.shell_join(step.command)
                self.assertNotIn("SPLUNK_PASS=", rendered)
                self.assertNotIn("STACK_TOKEN=", rendered)
                self.assertNotIn("SPLUNK_O11Y_TOKEN=", rendered)

    def test_redaction_covers_common_secret_shapes(self) -> None:
        text = "\n".join(
            [
                "Authorization: Bearer abcdefghijklmnop",
                "sessionKey=123456789abcdef",
                '"token": "SUPER_SECRET_VALUE_12345"',
                "password = hunter2hunter2",
                "https://admin:uri-password@example.test:8089/services",
                '"pass4SymmKey": "symmetric-secret-value"',
                '"sslPassword": "ssl-password-value"',
                '"privateKeyPassword": "private-key-password-value"',
            ]
        )
        redacted = runner.redact(text)
        self.assertNotIn("abcdefghijklmnop", redacted)
        self.assertNotIn("123456789abcdef", redacted)
        self.assertNotIn("SUPER_SECRET_VALUE_12345", redacted)
        self.assertNotIn("hunter2hunter2", redacted)
        self.assertNotIn("uri-password", redacted)
        self.assertNotIn("symmetric-secret-value", redacted)
        self.assertNotIn("ssl-password-value", redacted)
        self.assertNotIn("private-key-password-value", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_redaction_preserves_structural_checkpoint_step_ids_with_token(self) -> None:
        step_id = "splunk-hec-service-setup:apply-ssh-token-no-restart"
        payload = {
            "steps": {
                step_id: {
                    "status": "pass",
                    "metadata": {"hec_token": "SUPER_SECRET_TOKEN_VALUE"},
                }
            }
        }

        redacted = runner.redact_obj(payload)
        row = redacted["steps"][step_id]
        self.assertIsInstance(row, dict)
        self.assertEqual("pass", row["status"])
        self.assertEqual("[REDACTED]", row["metadata"]["hec_token"])

    def test_json_artifacts_are_redacted_and_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "evidence.json"
            runner.write_json(
                path,
                {
                    "clientSecret": "CLIENT_SECRET_VALUE",
                    "uri": "https://admin:URI_PASSWORD@example.test:8089/services",
                },
            )
            rendered = path.read_text(encoding="utf-8")
            mode = path.stat().st_mode & 0o777

        self.assertEqual(mode, 0o600)
        self.assertNotIn("CLIENT_SECRET_VALUE", rendered)
        self.assertNotIn("URI_PASSWORD", rendered)

    def test_checkpoint_reuse_ignores_legacy_redacted_string_rows(self) -> None:
        self.assertFalse(
            runner.checkpoint_result_is_reusable("[REDACTED]", force_rerun=False, category="apply")
        )
        self.assertTrue(
            runner.checkpoint_result_is_reusable(
                {"status": "pass", "command": "render-current-plan"},
                force_rerun=False,
                category="apply",
                command="render-current-plan",
            )
        )
        self.assertFalse(
            runner.checkpoint_result_is_reusable(
                {"status": "pass", "command": "old-plan"},
                force_rerun=False,
                category="apply",
                command="new-plan",
            )
        )
        self.assertFalse(
            runner.checkpoint_result_is_reusable(
                {"status": "pass", "command": "render-current-plan"},
                force_rerun=True,
                category="apply",
                command="render-current-plan",
            )
        )
        self.assertFalse(
            runner.checkpoint_result_is_reusable(
                {"status": "intentional-skip", "command": "render-current-plan"},
                force_rerun=False,
                category="apply",
                command="render-current-plan",
            )
        )

    def test_btool_findings_are_live_environment_constraints_not_auth_failures(self) -> None:
        step = runner.ValidationStep(
            step_id="baseline-ssh-btool-check",
            category="baseline",
            command=["bash", "-c", "splunk btool check"],
            mode="ssh:btool-check",
        )
        invalid_key = (
            "Checking: /opt/splunk/etc/apps/search/local/passwords.conf\n"
            "Invalid key in stanza [organization] in /opt/splunk/etc/apps/"
            "Splunk_TA_cisco_meraki/local/splunk_ta_cisco_meraki_organization.conf, line 4: base_url"
        )
        no_spec = "No spec file for: /opt/splunk/etc/apps/vendor/local/example.conf"

        self.assertEqual(
            "live_environment_constraint",
            runner.classify_failure(step, 1, invalid_key, ""),
        )
        self.assertEqual(
            "live_environment_constraint",
            runner.classify_failure(step, 1, no_spec, ""),
        )

    def test_connectivity_failures_are_environment_constraints(self) -> None:
        step = runner.ValidationStep(
            step_id="splunk-hec-service-setup:cleanup-ssh-validation-token",
            category="apply-cleanup",
            command=["bash", "-c", "ssh cleanup"],
            mode="ssh:cleanup-hec",
        )

        self.assertEqual(
            "live_environment_constraint",
            runner.classify_failure(step, 255, "", ""),
        )
        self.assertEqual(
            "live_environment_constraint",
            runner.classify_failure(step, 1, "ERROR: Cannot reach 10.0.0.1:8089 (connection refused or timed out).", ""),
        )

    def test_code_bugs_cannot_be_downgraded_to_intentional_skip(self) -> None:
        step = runner.ValidationStep(
            step_id="broken-command",
            category="read-only",
            command=["missing-command"],
            required=False,
            final_on_failure="intentional-skip",
        )
        classification = runner.classify_failure(step, 127, "", "missing-command: command not found")

        self.assertEqual(classification, "code_bug")
        self.assertFalse(runner.should_intentional_skip(step, classification))

    def test_plan_only_does_not_collect_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = runner.parse_args(["--plan-only", "--output-dir", tmpdir, "--quiet"])
            with mock.patch.object(runner, "collect_live_evidence") as collect:
                payload = runner.run_once(args)

        collect.assert_not_called()
        self.assertTrue(payload["steps"])

    def test_default_spec_discovers_templates_directory_examples(self) -> None:
        spec_path = runner.default_spec_for_skill("splunk-observability-dashboard-builder")
        self.assertIsNotNone(spec_path)
        assert spec_path is not None
        self.assertIn("templates", spec_path.as_posix())
        self.assertTrue(spec_path.name.endswith((".json", ".yaml", ".yml")))


if __name__ == "__main__":
    unittest.main()
