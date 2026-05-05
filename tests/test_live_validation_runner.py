"""Regression tests for the continuous live validation runner."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

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
        self.assertIn("splunk-admin-doctor:apply-safe-packet", by_id)
        self.assertFalse(by_id["splunk-admin-doctor:apply-safe-packet"].mutates)
        self.assertIn("splunk-observability-dashboard-builder:apply-live-smoke", by_id)
        self.assertTrue(by_id["splunk-observability-dashboard-builder:apply-live-smoke"].mutates)
        self.assertIn("splunk-observability-dashboard-builder:cleanup-live-smoke", by_id)
        cleanup = by_id["splunk-observability-dashboard-builder:cleanup-live-smoke"]
        self.assertTrue(cleanup.mutates)
        self.assertFalse(cleanup.read_only)
        self.assertEqual("apply-cleanup", cleanup.category)
        self.assertEqual("intentional-skip", cleanup.final_on_failure)
        self.assertIn("--cleanup", cleanup.command)
        self.assertIn("--apply-result", cleanup.command)
        for step_id in {
            "splunk-hec-service-setup:cleanup-ssh-validation-token",
            "splunk-workload-management-setup:cleanup-ssh-validation-app",
        }:
            with self.subTest(step=step_id):
                step = by_id[step_id]
                self.assertEqual("apply-cleanup", step.category)
                self.assertTrue(step.mutates)
                self.assertFalse(step.read_only)
                self.assertEqual("intentional-skip", step.final_on_failure)
                self.assertIn("codex_live_validation", " ".join(step.command))
                self.assertIn("rollback_or_validation", step.metadata)
                self.assertFalse(runner.command_uses_direct_secret(step.command), step.command)
        for step_id in {
            "splunk-hec-service-setup:post-cleanup-ssh-check",
            "splunk-workload-management-setup:post-cleanup-ssh-check",
        }:
            with self.subTest(step=step_id):
                step = by_id[step_id]
                self.assertEqual("apply-cleanup-validation", step.category)
                self.assertFalse(step.mutates)
                self.assertTrue(step.read_only)
                self.assertEqual("intentional-skip", step.final_on_failure)
                self.assertFalse(runner.command_uses_direct_secret(step.command), step.command)
        for step in steps:
            self.assertIn("rollback_or_validation", step.metadata) if step.category == "apply" and not step.skip_reason else None

    def test_plan_includes_ssh_baseline_and_remote_apply_steps(self) -> None:
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

        apply_by_id = {step.step_id: step for step in apply_steps}
        for step_id in {
            "splunk-monitoring-console-setup:apply-ssh-no-restart",
            "splunk-hec-service-setup:apply-ssh-token-no-restart",
            "splunk-workload-management-setup:apply-ssh-no-enable",
        }:
            with self.subTest(step=step_id):
                step = apply_by_id[step_id]
                self.assertEqual("ssh-apply", step.mode)
                self.assertTrue(step.mutates)
                self.assertFalse(step.read_only)
                self.assertEqual("intentional-skip", step.final_on_failure)
                self.assertIn("rollback_or_validation", step.metadata)
                self.assertEqual("remote-rendered-apply", step.command[3])
                self.assertFalse(runner.command_uses_direct_secret(step.command), step.command)

        for step_id in {
            "splunk-enterprise:post-apply-ssh-status",
            "splunk-monitoring-console-setup:post-apply-ssh-check",
            "splunk-hec-service-setup:post-apply-ssh-check",
            "splunk-workload-management-setup:post-apply-ssh-check",
        }:
            with self.subTest(step=step_id):
                step = apply_by_id[step_id]
                self.assertEqual("apply-validation", step.category)
                self.assertFalse(step.mutates)
                self.assertTrue(step.read_only)
                self.assertIn("rollback_or_validation", step.metadata)
                self.assertFalse(runner.command_uses_direct_secret(step.command), step.command)

        hec_check = apply_by_id["splunk-hec-service-setup:post-apply-ssh-check"]
        self.assertIn("btool inputs list --debug", " ".join(hec_check.command))
        self.assertNotIn("token =", " ".join(hec_check.command).lower())

        hec_cleanup = apply_by_id["splunk-hec-service-setup:cleanup-ssh-validation-token"]
        hec_cleanup_text = " ".join(hec_cleanup.command).lower()
        self.assertIn("codex_live_validation_hec", hec_cleanup_text)
        self.assertNotIn("token =", hec_cleanup_text)

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
            ]
        )
        redacted = runner.redact(text)
        self.assertNotIn("abcdefghijklmnop", redacted)
        self.assertNotIn("123456789abcdef", redacted)
        self.assertNotIn("SUPER_SECRET_VALUE_12345", redacted)
        self.assertNotIn("hunter2hunter2", redacted)
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

    def test_checkpoint_reuse_ignores_legacy_redacted_string_rows(self) -> None:
        self.assertFalse(
            runner.checkpoint_result_is_reusable("[REDACTED]", force_rerun=False, category="apply")
        )
        self.assertTrue(
            runner.checkpoint_result_is_reusable({"status": "pass"}, force_rerun=False, category="apply")
        )
        self.assertFalse(
            runner.checkpoint_result_is_reusable({"status": "pass"}, force_rerun=True, category="apply")
        )
        self.assertFalse(
            runner.checkpoint_result_is_reusable({"status": "pass"}, force_rerun=False, category="read-only")
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

    def test_generated_o11y_dashboard_spec_uses_codex_live_validation_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = runner.write_o11y_dashboard_spec(Path(tmpdir), realm="us1")
            text = spec_path.read_text(encoding="utf-8")

        self.assertIn("codex_live_validation_skill_checks", text)
        self.assertIn("codex_live_validation_dashboard", text)
        self.assertIn('"realm": "us1"', text)

    def test_default_spec_discovers_templates_directory_examples(self) -> None:
        spec_path = runner.default_spec_for_skill("splunk-observability-dashboard-builder")
        self.assertIsNotNone(spec_path)
        assert spec_path is not None
        self.assertIn("templates", spec_path.as_posix())
        self.assertTrue(spec_path.name.endswith((".json", ".yaml", ".yml")))


if __name__ == "__main__":
    unittest.main()
