"""Regression coverage for the repo-local MCP agent core."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from agent.splunk_cisco_skills_mcp import core


class AgentMCPCoreTests(unittest.TestCase):
    def test_list_skills_includes_catalog_and_script_metadata(self) -> None:
        payload = core.list_skills()
        skills = {item["name"]: item for item in payload["skills"]}

        self.assertIn("cisco-product-setup", skills)
        self.assertIn("setup.sh", skills["cisco-product-setup"]["scripts"])
        self.assertFalse(skills["cisco-product-setup"]["has_template"])

    def test_readme_supported_skills_table_matches_skill_catalog(self) -> None:
        readme = (core.REPO_ROOT / "README.md").read_text(encoding="utf-8")
        readme_skills = set(re.findall(r"\| `([^`]+)` \|", readme))
        catalog_skills = {item["name"] for item in core.list_skills()["skills"]}

        self.assertEqual(readme_skills, catalog_skills)

    def test_list_skills_exposes_references_directory(self) -> None:
        payload = core.list_skills()
        skills = {item["name"]: item for item in payload["skills"]}
        dashboard_skill = skills["splunk-observability-dashboard-builder"]

        self.assertTrue(dashboard_skill["has_reference"])
        self.assertEqual(
            dashboard_skill["reference_files"],
            ["references/classic-api.md", "references/coverage.md"],
        )
        reference_text = core.read_skill_file("splunk-observability-dashboard-builder", "reference")
        self.assertIn("# references/classic-api.md", reference_text)
        self.assertIn("# references/coverage.md", reference_text)

    def test_cisco_product_plan_uses_json_dry_run(self) -> None:
        with tempfile.NamedTemporaryFile() as password_file:
            plan = core.plan_cisco_product_setup(
                "Cisco ACI",
                set_values={
                    "hostname": "apic1.example.local",
                    "name": "ACI_PROD",
                    "username": "splunk-api",
                },
                secret_files={"password": password_file.name},
            )

        self.assertEqual(plan["kind"], "cisco_product_setup")
        self.assertIn("--dry-run", plan["dry_run_command"])
        self.assertNotIn("--dry-run", plan["command"])
        self.assertEqual(plan["dry_run"]["resolved_product"]["id"], "cisco_aci")
        self.assertEqual(plan["dry_run"]["missing_values_for_configure"], [])
        self.assertEqual(plan["dry_run"]["route"]["type"], "dc_networking")

    def test_cisco_product_plan_allows_thousandeyes_hec_token_name(self) -> None:
        plan = core.plan_cisco_product_setup(
            "Cisco ThousandEyes",
            set_values={
                "account_group": "Default",
                "hec_token": "custom_token_name",
            },
        )

        self.assertEqual(plan["dry_run"]["resolved_product"]["id"], "cisco_thousandeyes")
        self.assertEqual(plan["dry_run"]["missing_values_for_configure"], [])

    def test_cisco_product_plan_rejects_secret_like_set_values(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "looks secret-bearing"):
            core.plan_cisco_product_setup(
                "Cisco Meraki",
                set_values={"api_key": "secret-value"},
            )

    def test_cisco_product_plan_rejects_failed_dry_run(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "dry-run failed"):
            core.plan_cisco_product_setup(
                "Cisco ACI",
                set_values={"unsupported": "value"},
            )

    def test_cisco_spaces_plan_surfaces_required_activation_token_file(self) -> None:
        missing_plan = core.plan_cisco_product_setup(
            "Cisco Spaces",
            set_values={"name": "production", "region": "io"},
        )
        self.assertIn(
            "activation_token (secret-file)",
            missing_plan["dry_run"]["missing_values_for_configure"],
        )

        with tempfile.NamedTemporaryFile() as token_file:
            plan = core.plan_cisco_product_setup(
                "Cisco Spaces",
                set_values={"name": "production", "region": "io"},
                secret_files={"activation_token": token_file.name},
            )
        self.assertEqual(plan["dry_run"]["route"]["type"], "spaces")
        self.assertEqual(plan["dry_run"]["missing_values_for_configure"], [])
        self.assertIn(
            "skills/cisco-spaces-setup/scripts/configure_stream.sh",
            plan["dry_run"]["workflow_scripts"],
        )

    def test_cisco_product_plan_surfaces_missing_secret_file_path(self) -> None:
        missing_path = "/tmp/splunk_cisco_missing_spaces_token"
        plan = core.plan_cisco_product_setup(
            "Cisco Spaces",
            set_values={"name": "production", "region": "io"},
            secret_files={"activation_token": missing_path},
        )

        self.assertIn(
            f"activation_token (secret-file missing: {missing_path})",
            plan["dry_run"]["missing_values_for_configure"],
        )

    def test_generic_script_plan_rejects_direct_secret_flags(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "Direct secret flag"):
            core.plan_skill_script(
                "cisco-catalyst-ta-setup",
                "configure_account.sh",
                ["--password", "secret-value"],
            )

    def test_generic_script_plan_requires_args_list(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "args must be a list"):
            core.plan_skill_script(
                "cisco-product-setup",
                "resolve_product.sh",
                "--help",  # type: ignore[arg-type]
            )

    def test_product_plan_requires_mapping_inputs(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "set_values must be an object"):
            core.plan_cisco_product_setup(
                "Cisco ACI",
                set_values=["hostname", "apic1.example.local"],  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(core.SkillMCPError, "secret_files must be an object"):
            core.plan_cisco_product_setup(
                "Cisco ACI",
                secret_files=["password", "/tmp/p"],  # type: ignore[arg-type]
            )

    def test_generic_script_plan_rejects_oncall_direct_secret_flags(self) -> None:
        cases = [
            ["--oncall-api-key", "secret-value"],
            ["--on-call-api-key=secret-value"],
            ["--x-vo-api-key", "secret-value"],
            ["--vo-api-key", "secret-value"],
            ["--integration-key", "secret-value"],
            ["--rest-key=secret-value"],
            ["--api-key", "secret-value"],
        ]
        for args in cases:
            with self.subTest(args=args):
                with self.assertRaisesRegex(core.SkillMCPError, "Direct secret flag"):
                    core.plan_skill_script(
                        "splunk-oncall-setup",
                        "setup.sh",
                        args,
                    )

    def test_generic_script_plan_rejects_newer_direct_secret_flags(self) -> None:
        cases = [
            ("splunk-observability-aws-integration", ["--aws-access-key-id", "AKIA..."]),
            ("splunk-observability-aws-integration", ["--aws-secret-access-key=secret-value"]),
            ("splunk-observability-aws-integration", ["--aws-secret-key", "secret-value"]),
            ("splunk-observability-aws-integration", ["--external-id", "sensitive-external-id"]),
            ("splunk-observability-database-monitoring-setup", ["--db-password", "secret-value"]),
            ("splunk-observability-database-monitoring-setup", ["--connection-string=postgres://user:pass@db"]),
            ("splunk-observability-database-monitoring-setup", ["--datasource", "postgres://user:pass@db"]),
            ("splunk-observability-k8s-frontend-rum-setup", ["--rum-token", "secret-value"]),
            ("splunk-galileo-integration", ["--galileo-api-key", "secret-value"]),
            ("splunk-galileo-integration", ["--splunk-hec-token=secret-value"]),
        ]
        for skill, args in cases:
            with self.subTest(skill=skill, args=args):
                with self.assertRaisesRegex(core.SkillMCPError, "Direct secret flag"):
                    core.plan_skill_script(skill, "setup.sh", args)

    def test_generic_script_plan_requires_file_secret_paths(self) -> None:
        cases = [
            ["--password-file"],
            ["--password-file", ""],
            ["--token-file="],
        ]
        for args in cases:
            with self.subTest(args=args):
                with self.assertRaisesRegex(core.SkillMCPError, "requires a file path"):
                    core.plan_skill_script(
                        "cisco-catalyst-ta-setup",
                        "configure_account.sh",
                        args,
                    )

    def test_oncall_setup_render_only_invocations_are_read_only(self) -> None:
        # No mutation flag → read-only.
        plan = core.plan_skill_script(
            "splunk-oncall-setup",
            "setup.sh",
            ["--render", "--spec", "skills/splunk-oncall-setup/templates/oncall.example.yaml"],
        )
        self.assertTrue(plan["read_only"])

    def test_oncall_setup_apply_invocations_are_treated_as_mutating(self) -> None:
        # --self-test is a mutation flag because the script's own argv parser
        # flips SEND_ALERT=true on --self-test, which fires synthetic INFO +
        # RECOVERY alerts against the live On-Call REST endpoint.
        mutation_flags = (
            "--apply",
            "--send-alert",
            "--install-splunk-app",
            "--uninstall",
            "--self-test",
        )
        for mutation_flag in mutation_flags:
            with self.subTest(mutation_flag=mutation_flag):
                plan = core.plan_skill_script(
                    "splunk-oncall-setup",
                    "setup.sh",
                    [mutation_flag, "--spec", "skills/splunk-oncall-setup/templates/oncall.example.yaml"],
                )
                self.assertFalse(plan["read_only"])
        # --dry-run downgrades any of the above mutation invocations to a
        # read-only preview because the scripts honour DRY_RUN end-to-end.
        for mutation_flag in mutation_flags:
            with self.subTest(mutation_flag=mutation_flag, dry_run=True):
                plan = core.plan_skill_script(
                    "splunk-oncall-setup",
                    "setup.sh",
                    [
                        mutation_flag,
                        "--dry-run",
                        "--spec",
                        "skills/splunk-oncall-setup/templates/oncall.example.yaml",
                    ],
                )
                self.assertTrue(plan["read_only"])

    def test_native_ops_apply_invocations_are_treated_as_mutating(self) -> None:
        plan = core.plan_skill_script(
            "splunk-observability-native-ops",
            "setup.sh",
            ["--apply", "--spec", "skills/splunk-observability-native-ops/templates/native-ops.example.yaml"],
        )
        self.assertFalse(plan["read_only"])

    def test_generic_script_plan_allows_file_based_secret_flags(self) -> None:
        plan = core.plan_skill_script(
            "cisco-catalyst-ta-setup",
            "configure_account.sh",
            [
                "--type",
                "catalyst_center",
                "--name",
                "DNAC_PROD",
                "--host",
                "https://dnac.example.local",
                "--username",
                "splunk-api",
                "--password-file",
                "/tmp/catalyst_password",
            ],
        )

        self.assertEqual(plan["kind"], "skill_script")
        self.assertIn("--password-file", plan["command"])

    def test_secret_file_instructions_quote_prefix_and_return_argv(self) -> None:
        payload = core.secret_file_instructions(
            ["password"],
            prefix="/tmp/x; touch /tmp/agent_review_injected",
        )
        command = payload["commands"][0]

        self.assertEqual(
            command["argv"],
            [
                "bash",
                "skills/shared/scripts/write_secret_file.sh",
                "/tmp/x; touch /tmp/agent_review_injected_password",
            ],
        )
        self.assertIn("'/tmp/x; touch /tmp/agent_review_injected_password'", command["command"])

    def test_generic_script_plan_uses_script_interpreter(self) -> None:
        python_plan = core.plan_skill_script("cisco-product-setup", "build_catalog.py", ["--check"])
        ruby_plan = core.plan_skill_script("splunk-itsi-config", "spec_to_json.rb", ["--help"])

        self.assertEqual(python_plan["command"][0], "python3")
        self.assertEqual(ruby_plan["command"][0], "ruby")

    def test_execute_read_only_plan_does_not_require_mutation_gate(self) -> None:
        previous = os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)
        try:
            plan = core.plan_skill_script(
                "cisco-product-setup",
                "resolve_product.sh",
                ["--help"],
            )
            result = core.execute_plan(plan["plan_hash"], confirm=True)
            self.assertEqual(result["returncode"], 0)
            self.assertIn("Usage:", result["stdout"] + result["stderr"])
        finally:
            if previous is not None:
                os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = previous

    def test_product_validate_only_plan_is_read_only(self) -> None:
        plan = core.plan_cisco_product_setup("Cisco ACI", phase="validate")

        self.assertTrue(plan["read_only"])

    def test_execute_mutating_plan_requires_mutation_gate(self) -> None:
        previous = os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)
        try:
            plan = core.plan_skill_script(
                "cisco-catalyst-ta-setup",
                "configure_account.sh",
                [],
            )
            with self.assertRaisesRegex(core.SkillMCPError, "Mutating execution is disabled"):
                core.execute_plan(plan["plan_hash"], confirm=True)
        finally:
            if previous is not None:
                os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = previous

    def test_execute_mutating_plan_runs_when_gate_is_open(self) -> None:
        # Complement to test_execute_mutating_plan_requires_mutation_gate:
        # confirms that setting SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1 opens the
        # gate and the planned mutating command actually runs. We use
        # configure_account.sh with empty args so the script fails fast on
        # missing required flags (returncode != 0) without contacting Splunk
        # — what we are asserting is that the gate did NOT block execution.
        previous = os.environ.get("SPLUNK_SKILLS_MCP_ALLOW_MUTATION")
        os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = "1"
        try:
            plan = core.plan_skill_script(
                "cisco-catalyst-ta-setup",
                "configure_account.sh",
                [],
            )
            self.assertFalse(plan["read_only"])
            result = core.execute_plan(plan["plan_hash"], confirm=True)
            # Script ran (we got stdout/stderr back) instead of being blocked
            # at the gate. Returncode is non-zero because we omitted required
            # args, which is the expected behavior for this guard test.
            self.assertNotEqual(result["returncode"], 0)
            self.assertIn("returncode", result)
        finally:
            if previous is None:
                os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)
            else:
                os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = previous

    def test_runner_reports_missing_mcp_dependency_without_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, "agent/run-splunk-cisco-skills-mcp.py"],
            cwd=core.REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            self.skipTest("mcp dependency is installed in this environment")
        self.assertIn("pip install -r requirements-agent.txt", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_mcp_configs_include_local_agent_server(self) -> None:
        for rel_path in [".mcp.json", ".cursor/mcp.json"]:
            with self.subTest(path=rel_path):
                payload = json.loads((core.REPO_ROOT / rel_path).read_text(encoding="utf-8"))
                server = payload["mcpServers"]["splunk-cisco-skills"]
                self.assertRegex(server["command"], r"python3?(\b|$)")
                self.assertIn("run-splunk-cisco-skills-mcp.py", server["args"][0])

    def test_codex_registration_helper_points_at_local_agent_server(self) -> None:
        script = core.REPO_ROOT / "agent/register-codex-splunk-cisco-skills-mcp.sh"
        text = script.read_text(encoding="utf-8")

        self.assertTrue(os.access(script, os.X_OK))
        self.assertIn("codex mcp add", text)
        self.assertIn("run-splunk-cisco-skills-mcp.py", text)
        self.assertIn("-- python3", text)

    def test_list_cisco_products_rejects_invalid_state(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "Invalid state"):
            core.list_cisco_products(state="bogus_state")

    def test_list_cisco_products_accepts_valid_states(self) -> None:
        for state in core._VALID_PRODUCT_STATES:
            with self.subTest(state=state):
                payload = core.list_cisco_products(state=state)
                self.assertIn("products", payload)

    def test_list_cisco_products_accepts_unsupported_catalog_states(self) -> None:
        self.assertIn(
            "unsupported_legacy",
            {product["automation_state"] for product in core.list_cisco_products()["products"]},
        )
        self.assertIn("unsupported_roadmap", core._VALID_PRODUCT_STATES)

    def test_claude_rule_uses_secret_writer_helper(self) -> None:
        text = (core.REPO_ROOT / ".claude/rules/credential-handling.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("skills/shared/scripts/write_secret_file.sh", text)
        self.assertNotIn('echo "the_secret"', text)

    def test_execute_plan_consumes_plan_on_success(self) -> None:
        previous = os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)
        try:
            plan = core.plan_skill_script(
                "cisco-product-setup",
                "resolve_product.sh",
                ["--help"],
            )
            plan_hash = plan["plan_hash"]
            core.execute_plan(plan_hash, confirm=True)
            with self.assertRaisesRegex(core.SkillMCPError, "Unknown plan_hash"):
                core.execute_plan(plan_hash, confirm=True)
        finally:
            if previous is not None:
                os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = previous

    def test_execute_plan_keeps_plan_when_confirm_missing(self) -> None:
        plan = core.plan_skill_script(
            "cisco-product-setup",
            "resolve_product.sh",
            ["--help"],
        )
        plan_hash = plan["plan_hash"]
        with self.assertRaisesRegex(core.SkillMCPError, "confirm=true"):
            core.execute_plan(plan_hash, confirm=False)
        # Plan must still exist so the operator can retry with confirm=True.
        result = core.execute_plan(plan_hash, confirm=True)
        self.assertEqual(result["returncode"], 0)

    def test_execute_plan_keeps_plan_when_mutation_gate_blocks(self) -> None:
        previous = os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)
        try:
            plan = core.plan_skill_script(
                "cisco-catalyst-ta-setup",
                "configure_account.sh",
                [],
            )
            plan_hash = plan["plan_hash"]
            with self.assertRaisesRegex(core.SkillMCPError, "Mutating execution is disabled"):
                core.execute_plan(plan_hash, confirm=True)
            # A blocked mutation should not destroy the plan; the operator
            # can fix the env var and retry.
            with self.assertRaisesRegex(core.SkillMCPError, "Mutating execution is disabled"):
                core.execute_plan(plan_hash, confirm=True)
        finally:
            if previous is not None:
                os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = previous

    def test_execute_plan_rejects_malformed_hash(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "64-character lowercase hex"):
            core.execute_plan("not-a-hash", confirm=True)
        with self.assertRaisesRegex(core.SkillMCPError, "64-character lowercase hex"):
            core.execute_plan("A" * 64, confirm=True)

    def test_timeout_rejects_bool(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "timeout_seconds must be an integer"):
            core.plan_skill_script(
                "cisco-product-setup",
                "resolve_product.sh",
                ["--help"],
                timeout_seconds=True,  # type: ignore[arg-type]
            )

    def test_invalid_integer_env_values_do_not_break_import(self) -> None:
        env = os.environ.copy()
        env["MCP_MAX_TIMEOUT_SECONDS"] = "not-an-int"
        env["MCP_RESOLVE_TIMEOUT_SECONDS"] = "also-bad"
        env["MCP_PLAN_TTL_SECONDS"] = "bad"

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from agent.splunk_cisco_skills_mcp import core; "
                    "print(core.MAX_TIMEOUT_SECONDS, core.RESOLVE_TIMEOUT_SECONDS, core.PLAN_TTL_SECONDS)"
                ),
            ],
            cwd=core.REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "7200 60 3600")

    def test_dry_run_flag_does_not_make_arbitrary_scripts_read_only(self) -> None:
        # A script that does not actually implement --dry-run must NOT be
        # classified as read-only just because the caller passed --dry-run.
        plan = core.plan_skill_script(
            "splunk-app-install",
            "install_app.sh",
            ["--dry-run"],
        )
        self.assertFalse(plan["read_only"])

    def test_cisco_product_setup_dry_run_is_read_only_via_allowlist(self) -> None:
        plan = core.plan_skill_script(
            "cisco-product-setup",
            "setup.sh",
            ["--dry-run", "--product", "Cisco ACI"],
        )
        self.assertTrue(plan["read_only"])

    def test_render_first_setup_phases_are_read_only_via_allowlist(self) -> None:
        render_plan = core.plan_skill_script(
            "splunk-agent-management-setup",
            "setup.sh",
            ["--phase", "render"],
        )
        uf_download_plan = core.plan_skill_script(
            "splunk-universal-forwarder-setup",
            "setup.sh",
            ["--phase", "download"],
        )
        preflight_plan = core.plan_skill_script(
            "splunk-workload-management-setup",
            "setup.sh",
            ["--phase=preflight"],
        )
        apply_plan = core.plan_skill_script(
            "splunk-hec-service-setup",
            "setup.sh",
            ["--phase", "apply"],
        )

        self.assertTrue(render_plan["read_only"])
        self.assertTrue(uf_download_plan["read_only"])
        self.assertTrue(preflight_plan["read_only"])
        self.assertFalse(apply_plan["read_only"])

    def test_new_render_first_skills_read_only_phases(self) -> None:
        # Covers skills added after the initial READ_ONLY_PHASE_SCRIPTS map:
        # ACS allowlist, Edge Processor, Indexer Cluster, License Manager, SOAR.
        cases = [
            ("splunk-cloud-acs-allowlist-setup", ["--phase", "audit"], True),
            ("splunk-cloud-acs-allowlist-setup", ["--phase", "validate"], True),
            ("splunk-cloud-acs-allowlist-setup", ["--phase", "apply"], False),
            ("splunk-edge-processor-setup", ["--phase", "preflight"], True),
            ("splunk-edge-processor-setup", ["--phase", "apply"], False),
            ("splunk-indexer-cluster-setup", ["--phase", "bundle-validate"], True),
            ("splunk-indexer-cluster-setup", ["--phase", "bundle-status"], True),
            ("splunk-indexer-cluster-setup", ["--phase", "rolling-restart"], False),
            ("splunk-license-manager-setup", ["--phase", "validate"], True),
            ("splunk-license-manager-setup", ["--phase", "apply"], False),
            ("splunk-soar-setup", ["--phase", "cloud-onboard"], True),
            ("splunk-soar-setup", ["--phase", "apply"], False),
        ]
        for skill, args, expected_read_only in cases:
            plan = core.plan_skill_script(skill, "setup.sh", args)
            self.assertEqual(
                plan["read_only"],
                expected_read_only,
                msg=f"{skill} {args} read_only expected {expected_read_only}",
            )

    def test_flag_based_mode_skills_read_only_unless_apply(self) -> None:
        # Observability native ops and dashboard builder use --apply as the
        # mutation gate rather than a --phase arg.
        native_render = core.plan_skill_script(
            "splunk-observability-native-ops",
            "setup.sh",
            ["--render", "--spec", "spec.yaml"],
        )
        native_apply = core.plan_skill_script(
            "splunk-observability-native-ops",
            "setup.sh",
            ["--apply", "--spec", "spec.yaml", "--token-file", "/tmp/t"],
        )
        dashboard_render = core.plan_skill_script(
            "splunk-observability-dashboard-builder",
            "setup.sh",
            ["--spec", "dashboard.json"],
        )

        self.assertTrue(native_render["read_only"])
        self.assertFalse(native_apply["read_only"])
        self.assertTrue(dashboard_render["read_only"])

        galileo_render = core.plan_skill_script(
            "splunk-galileo-integration",
            "setup.sh",
            ["--render", "--output-dir", "splunk-galileo-rendered"],
        )
        galileo_apply = core.plan_skill_script(
            "splunk-galileo-integration",
            "setup.sh",
            [
                "--apply",
                "hec-export",
                "--galileo-api-key-file",
                "/tmp/galileo",
                "--splunk-hec-token-file",
                "/tmp/hec",
            ],
        )
        self.assertTrue(galileo_render["read_only"])
        self.assertFalse(galileo_apply["read_only"])

    def test_universal_forwarder_latest_smoke_is_read_only(self) -> None:
        plan = core.plan_skill_script(
            "splunk-universal-forwarder-setup",
            "smoke_latest_resolution.sh",
            ["--target-os", "linux", "--package-type", "tgz"],
        )

        self.assertTrue(plan["read_only"])

    def test_observability_dashboard_apply_dry_run_is_read_only(self) -> None:
        plan = core.plan_skill_script(
            "splunk-observability-dashboard-builder",
            "setup.sh",
            ["--apply", "--dry-run", "--spec", "dashboard.json"],
        )

        self.assertTrue(plan["read_only"])

    def test_observability_native_ops_apply_dry_run_is_read_only(self) -> None:
        plan = core.plan_skill_script(
            "splunk-observability-native-ops",
            "setup.sh",
            [
                "--apply",
                "--dry-run",
                "--spec",
                "skills/splunk-observability-native-ops/templates/native-ops.example.yaml",
            ],
        )

        self.assertTrue(plan["read_only"])

    def test_render_first_phase_skills_dry_run_downgrades_apply(self) -> None:
        # Each of these skills has a --phase apply / similar mutating phase
        # AND honours --dry-run as a clean short-circuit (rendered scripts
        # are logged, never executed). The MCP must classify those previews
        # as read-only so operators can see what apply would do without
        # opening the SPLUNK_SKILLS_MCP_ALLOW_MUTATION gate.
        cases = [
            ("splunk-cloud-acs-allowlist-setup", ["--phase", "apply"]),
            ("splunk-edge-processor-setup", ["--phase", "apply"]),
            ("splunk-federated-search-setup", ["--phase", "apply"]),
            ("splunk-indexer-cluster-setup", ["--phase", "rolling-restart"]),
            ("splunk-license-manager-setup", ["--phase", "apply"]),
            ("splunk-soar-setup", ["--phase", "onprem-single"]),
        ]
        for skill, args in cases:
            with self.subTest(skill=skill):
                # Without --dry-run the apply phase is mutating.
                mutating = core.plan_skill_script(skill, "setup.sh", args)
                self.assertFalse(mutating["read_only"], msg=f"{skill} {args}")
                # With --dry-run it must downgrade to read-only.
                preview = core.plan_skill_script(
                    skill, "setup.sh", [*args, "--dry-run"]
                )
                self.assertTrue(preview["read_only"], msg=f"{skill} {args} --dry-run")

    def test_resolve_product_list_products_is_read_only(self) -> None:
        plan = core.plan_skill_script(
            "cisco-product-setup",
            "resolve_product.sh",
            ["--list-products"],
        )
        self.assertTrue(plan["read_only"])

    def test_federated_search_phases_classify_correctly(self) -> None:
        cases = [
            (["--phase", "render"], True),
            (["--phase", "preflight"], True),
            (["--phase", "status"], True),
            (["--phase", "apply"], False),
            (["--phase", "render", "--apply"], False),
            (["--phase", "global-toggle"], False),
        ]
        for args, expected_read_only in cases:
            with self.subTest(args=args):
                plan = core.plan_skill_script(
                    "splunk-federated-search-setup", "setup.sh", args
                )
                self.assertEqual(plan["read_only"], expected_read_only)

    def test_edge_processor_status_validate_phases_are_read_only(self) -> None:
        for phase in ("status", "validate"):
            with self.subTest(phase=phase):
                plan = core.plan_skill_script(
                    "splunk-edge-processor-setup", "setup.sh", ["--phase", phase]
                )
                self.assertTrue(plan["read_only"])
        # install-instance / uninstall-instance / all remain mutating.
        for phase in ("install-instance", "uninstall-instance", "all"):
            with self.subTest(phase=phase):
                plan = core.plan_skill_script(
                    "splunk-edge-processor-setup", "setup.sh", ["--phase", phase]
                )
                self.assertFalse(plan["read_only"])

    def test_security_dry_run_skills_are_read_only_with_dry_run(self) -> None:
        # All of these surface --dry-run as a read-only preview path.
        skills = [
            "splunk-asset-risk-intelligence-setup",
            "splunk-attack-analyzer-setup",
            "splunk-security-essentials-setup",
            "splunk-security-portfolio-setup",
            "splunk-itsi-setup",
            "splunk-uba-setup",
        ]
        for skill in skills:
            with self.subTest(skill=skill):
                read_only_plan = core.plan_skill_script(
                    skill, "setup.sh", ["--dry-run"]
                )
                self.assertTrue(read_only_plan["read_only"])
                # Without --dry-run these scripts do mutate Splunk, so the
                # plan must remain mutating by default.
                mutating_plan = core.plan_skill_script(skill, "setup.sh", [])
                self.assertFalse(mutating_plan["read_only"])

    def test_sc4s_render_only_is_read_only_apply_or_prep_is_mutating(self) -> None:
        cases = [
            (["--render-host", "--hec-token-file", "/tmp/t"], True),
            (["--render-k8s", "--hec-token-file", "/tmp/t"], True),
            (
                ["--render-host", "--apply-host", "--hec-token-file", "/tmp/t"],
                False,
            ),
            (
                ["--render-k8s", "--apply-k8s", "--hec-token-file", "/tmp/t"],
                False,
            ),
            (["--splunk-prep"], False),
        ]
        for args, expected_read_only in cases:
            with self.subTest(args=args):
                plan = core.plan_skill_script(
                    "splunk-connect-for-syslog-setup", "setup.sh", args
                )
                self.assertEqual(plan["read_only"], expected_read_only)

    def test_sc4snmp_render_only_is_read_only_apply_or_prep_is_mutating(self) -> None:
        cases = [
            (["--render-compose", "--hec-token-file", "/tmp/t"], True),
            (["--render-k8s", "--hec-token-file", "/tmp/t"], True),
            (
                ["--render-compose", "--apply-compose", "--hec-token-file", "/tmp/t"],
                False,
            ),
            (
                ["--render-k8s", "--apply-k8s", "--hec-token-file", "/tmp/t"],
                False,
            ),
            (["--splunk-prep"], False),
        ]
        for args, expected_read_only in cases:
            with self.subTest(args=args):
                plan = core.plan_skill_script(
                    "splunk-connect-for-snmp-setup", "setup.sh", args
                )
                self.assertEqual(plan["read_only"], expected_read_only)

    def test_otel_collector_render_is_read_only_apply_is_mutating(self) -> None:
        cases = [
            (["--render-k8s"], True),
            (["--render-linux"], True),
            (["--render-k8s", "--apply-k8s", "--platform-hec-token-file", "/tmp/t"], False),
            (["--render-linux", "--apply-linux", "--platform-hec-token-file", "/tmp/t"], False),
            # --dry-run keeps it read-only even with --apply-k8s.
            (
                [
                    "--render-k8s",
                    "--apply-k8s",
                    "--dry-run",
                    "--platform-hec-token-file",
                    "/tmp/t",
                ],
                True,
            ),
        ]
        for args, expected_read_only in cases:
            with self.subTest(args=args):
                plan = core.plan_skill_script(
                    "splunk-observability-otel-collector-setup", "setup.sh", args
                )
                self.assertEqual(plan["read_only"], expected_read_only)

    def test_smoke_offline_scripts_are_read_only(self) -> None:
        for skill in (
            "splunk-cloud-acs-allowlist-setup",
            "splunk-edge-processor-setup",
            "splunk-enterprise-public-exposure-hardening",
            "splunk-indexer-cluster-setup",
            "splunk-license-manager-setup",
            "splunk-observability-cloud-integration-setup",
            "splunk-oncall-setup",
            "splunk-soar-setup",
        ):
            with self.subTest(skill=skill):
                plan = core.plan_skill_script(skill, "smoke_offline.sh", [])
                self.assertTrue(plan["read_only"])

    def test_enterprise_public_exposure_phase_classification(self) -> None:
        cases = [
            (["--phase", "render"], True),
            (["--phase", "preflight"], True),
            (["--phase", "validate"], True),
            (["--phase", "apply"], False),
            (["--phase", "all"], False),
            (["--phase", "render", "--apply"], False),
            (["--dry-run", "--phase", "apply"], True),
        ]
        for args, expected_read_only in cases:
            with self.subTest(args=args):
                plan = core.plan_skill_script(
                    "splunk-enterprise-public-exposure-hardening", "setup.sh", args
                )
                self.assertEqual(plan["read_only"], expected_read_only)

    def test_observability_cloud_integration_setup_classification(self) -> None:
        # Render-only / inspect-only modes stay read-only.
        for args in (
            [],
            ["--render", "--spec", "spec.yaml"],
            ["--validate", "--spec", "spec.yaml"],
            ["--doctor", "--spec", "spec.yaml"],
            ["--discover", "--spec", "spec.yaml"],
            ["--explain", "--spec", "spec.yaml"],
            ["--list-sim-templates"],
            ["--render-sim-templates", "k8s_metrics_aggregation"],
            ["--rollback", "pairing", "--spec", "spec.yaml"],
            ["--make-default-deeplink", "--realm", "us0"],
        ):
            with self.subTest(args=args):
                plan = core.plan_skill_script(
                    "splunk-observability-cloud-integration-setup", "setup.sh", args
                )
                self.assertTrue(plan["read_only"], msg=f"{args}")
        # Mutation modes flip to read_only=False.
        for args in (
            ["--apply", "pairing", "--spec", "spec.yaml"],
            ["--quickstart", "--spec", "spec.yaml"],
            ["--quickstart-enterprise", "--spec", "spec.yaml"],
            ["--enable-token-auth", "--spec", "spec.yaml"],
        ):
            with self.subTest(args=args):
                plan = core.plan_skill_script(
                    "splunk-observability-cloud-integration-setup", "setup.sh", args
                )
                self.assertFalse(plan["read_only"], msg=f"{args}")
        # --dry-run downgrades a mutating mode to a read-only preview.
        for args in (
            ["--apply", "pairing", "--dry-run", "--spec", "spec.yaml"],
            ["--quickstart", "--dry-run", "--spec", "spec.yaml"],
        ):
            with self.subTest(args=args, dry_run=True):
                plan = core.plan_skill_script(
                    "splunk-observability-cloud-integration-setup", "setup.sh", args
                )
                self.assertTrue(plan["read_only"], msg=f"{args}")

    def test_apply_aware_integration_setups_classification(self) -> None:
        # Skills with an --apply mode in their setup.sh wrapper.
        for skill in (
            "cisco-thousandeyes-mcp-setup",
            "splunk-observability-thousandeyes-integration",
            "cisco-isovalent-platform-setup",
        ):
            with self.subTest(skill=skill, mode="render"):
                plan = core.plan_skill_script(skill, "setup.sh", ["--render"])
                self.assertTrue(plan["read_only"])
            with self.subTest(skill=skill, mode="apply"):
                plan = core.plan_skill_script(skill, "setup.sh", ["--apply"])
                self.assertFalse(plan["read_only"])
            with self.subTest(skill=skill, mode="apply+dry-run"):
                plan = core.plan_skill_script(
                    skill, "setup.sh", ["--apply", "--dry-run"]
                )
                self.assertTrue(plan["read_only"])

    def test_render_only_observability_integrations_are_always_read_only(self) -> None:
        # These five wrappers do not expose --apply at all; the rendered
        # helpers (helm install, kubectl apply, etc.) are run separately
        # by the operator, so any invocation through the MCP is read-only.
        skills = (
            "splunk-observability-cisco-nexus-integration",
            "splunk-observability-cisco-intersight-integration",
            "splunk-observability-isovalent-integration",
            "splunk-observability-nvidia-gpu-integration",
            "splunk-observability-cisco-ai-pod-integration",
        )
        for skill in skills:
            for args in (
                [],
                ["--render"],
                ["--validate"],
                ["--dry-run"],
                ["--render", "--explain"],
            ):
                with self.subTest(skill=skill, args=args):
                    plan = core.plan_skill_script(skill, "setup.sh", args)
                    self.assertTrue(plan["read_only"])

    def test_newer_render_first_observability_setups_classify_correctly(self) -> None:
        aws_read_only = (
            [],
            ["--render"],
            ["--validate"],
            ["--doctor"],
            ["--discover"],
            ["--quickstart-from-live"],
            ["--explain"],
            ["--rollback", "integration"],
            ["--list-namespaces"],
            ["--list-recommended-stats"],
        )
        for args in aws_read_only:
            with self.subTest(skill="aws", args=args):
                plan = core.plan_skill_script(
                    "splunk-observability-aws-integration", "setup.sh", list(args)
                )
                self.assertTrue(plan["read_only"])
        for args in (["--apply"], ["--quickstart"], ["--quickstart", "--dry-run"]):
            with self.subTest(skill="aws", args=args):
                plan = core.plan_skill_script(
                    "splunk-observability-aws-integration", "setup.sh", args
                )
                self.assertFalse(plan["read_only"])

        for args in ([], ["--render"], ["--validate"], ["--validate", "--api"], ["--explain"], ["--dry-run"]):
            with self.subTest(skill="dbmon", args=args):
                plan = core.plan_skill_script(
                    "splunk-observability-database-monitoring-setup", "setup.sh", args
                )
                self.assertTrue(plan["read_only"])

        rum_read_only = (
            [],
            ["--render"],
            ["--discover-frontend-workloads"],
            ["--validate"],
            ["--guided"],
            ["--explain"],
            ["--gitops-mode"],
            ["--dry-run"],
        )
        for args in rum_read_only:
            with self.subTest(skill="rum", args=args):
                plan = core.plan_skill_script(
                    "splunk-observability-k8s-frontend-rum-setup", "setup.sh", list(args)
                )
                self.assertTrue(plan["read_only"])
        for args in (["--apply-injection"], ["--uninstall-injection"], ["--apply-injection", "--dry-run"]):
            with self.subTest(skill="rum", args=args):
                plan = core.plan_skill_script(
                    "splunk-observability-k8s-frontend-rum-setup", "setup.sh", args
                )
                self.assertFalse(plan["read_only"])

    def test_matches_mutation_flag_handles_prefix_and_equals_form(self) -> None:
        patterns = ("--apply-", "--splunk-prep")
        # Prefix match catches --apply-host, --apply-k8s, etc.
        self.assertTrue(core._matches_mutation_flag(["--apply-host"], patterns))
        self.assertTrue(
            core._matches_mutation_flag(["--apply-k8s=true"], patterns)
        )
        # Exact match for --splunk-prep, including --flag=value form.
        self.assertTrue(core._matches_mutation_flag(["--splunk-prep"], patterns))
        # Patterns ending in '-' must NOT match the unsuffixed flag.
        self.assertFalse(core._matches_mutation_flag(["--apply"], patterns))
        # Other args pass through cleanly.
        self.assertFalse(
            core._matches_mutation_flag(["--render-host", "--spec", "x"], patterns)
        )

    def test_list_skills_surfaces_templates_directory_files(self) -> None:
        payload = core.list_skills()
        skills = {item["name"]: item for item in payload["skills"]}

        # itsi-config has only templates/ (no template.example).
        itsi_config = skills["splunk-itsi-config"]
        self.assertTrue(itsi_config["has_template"])
        self.assertNotIn("template.example", itsi_config["template_files"])
        self.assertIn("templates/native.example.yaml", itsi_config["template_files"])
        self.assertIn(
            "templates/beginner.content-pack.yaml", itsi_config["template_files"]
        )

        # SC4S has both template.example AND templates/ host + k8s assets.
        sc4s = skills["splunk-connect-for-syslog-setup"]
        self.assertTrue(sc4s["has_template"])
        self.assertEqual(sc4s["template_files"][0], "template.example")
        self.assertIn("templates/host/docker-compose.yml", sc4s["template_files"])
        self.assertIn("templates/kubernetes/values.yaml", sc4s["template_files"])

        # cisco-product-setup has neither and must report has_template=False.
        cisco_product = skills["cisco-product-setup"]
        self.assertFalse(cisco_product["has_template"])
        self.assertEqual(cisco_product["template_files"], [])

    def test_read_skill_template_aggregates_multi_file_templates(self) -> None:
        text = core.read_skill_file("splunk-itsi-config", "template")
        self.assertIn("# templates/native.example.yaml", text)
        self.assertIn("# templates/beginner.content-pack.yaml", text)

    def test_read_skill_template_for_single_template_example(self) -> None:
        # cisco-catalyst-ta-setup has only template.example (no templates/).
        text = core.read_skill_file("cisco-catalyst-ta-setup", "template")
        self.assertNotIn("# template.example", text)
        # template.example file must contain something sensible; we just
        # assert non-empty here so the test does not couple to phrasing.
        self.assertTrue(text.strip())

    def test_read_skill_template_raises_when_neither_form_present(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "template.example or templates"):
            core.read_skill_file("cisco-product-setup", "template")

    def test_execute_plan_keeps_plan_when_kind_mismatches(self) -> None:
        previous = os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)
        try:
            plan = core.plan_skill_script(
                "cisco-product-setup",
                "resolve_product.sh",
                ["--help"],
            )
            plan_hash = plan["plan_hash"]
            # Wrong expected_kind must NOT consume the plan.
            with self.assertRaisesRegex(core.SkillMCPError, "is skill_script, not"):
                core.execute_plan(
                    plan_hash, confirm=True, expected_kind="cisco_product_setup"
                )
            # Plan must still be runnable under the right kind.
            result = core.execute_plan(
                plan_hash, confirm=True, expected_kind="skill_script"
            )
            self.assertEqual(result["returncode"], 0)
        finally:
            if previous is not None:
                os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = previous

    def test_run_command_isolates_stdin_and_process_group(self) -> None:
        class FakeProc:
            pid = 12345

            def __init__(self) -> None:
                self.stdout = io.BytesIO(b"ok\n")
                self.stderr = io.BytesIO(b"")

            def wait(self, timeout: int | None = None) -> int:
                return 0

        fake_proc = FakeProc()
        with mock.patch.object(core.subprocess, "Popen", return_value=fake_proc) as popen:
            result = core._run_command(["fake"], timeout_seconds=1)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "ok\n")
        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs["stdin"], core.subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])

    def test_run_command_returns_structured_error_when_spawn_fails(self) -> None:
        with mock.patch.object(
            core.subprocess,
            "Popen",
            side_effect=FileNotFoundError("missing-binary"),
        ):
            result = core._run_command(["missing-binary"], timeout_seconds=1)

        self.assertEqual(result.returncode, 127)
        self.assertIn("Failed to start command", result.stderr)

    def test_catalog_non_secret_keys_do_not_match_secret_regex(self) -> None:
        """Defense against future catalog edits.

        If a catalog entry ever adds a secret-shaped key (e.g. ``api_key``)
        to ``accepted_non_secret_keys``, the MCP catalog allowlist would
        bypass the regex check and let that value through as ``--set KEY
        VALUE`` (i.e., on the command line). Catch that at test time.
        """
        catalog = json.loads(core.CATALOG_PATH.read_text(encoding="utf-8"))
        offenders: list[str] = []
        for product in catalog.get("products", []):
            product_id = product.get("id", "<unknown>")
            keys: set[str] = set()
            keys.update(product.get("accepted_non_secret_keys") or [])
            keys.update(product.get("required_non_secret_keys") or [])
            keys.update(product.get("optional_non_secret_keys") or [])
            route = product.get("route") or {}
            for variant in (route.get("variants") or {}).values():
                if not isinstance(variant, dict):
                    continue
                keys.update(variant.get("accepted_non_secret_keys") or [])
                keys.update(variant.get("required_non_secret_keys") or [])
                keys.update(variant.get("optional_non_secret_keys") or [])
            for key in keys:
                if not isinstance(key, str):
                    continue
                normalized = (
                    core.re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").lower()
                )
                if normalized in core.NON_SECRET_VALUE_KEYS:
                    continue
                if core._looks_secret_key(key):
                    offenders.append(f"{product_id}.{key}")
        self.assertEqual(
            offenders,
            [],
            msg=(
                "These catalog non-secret keys match the MCP secret-key regex; "
                "either add them to NON_SECRET_VALUE_KEYS in core.py, rename "
                "them, or move them to secret_keys. Offenders: " + ", ".join(offenders)
            ),
        )


class SecretRedactionTests(unittest.TestCase):
    """Defense-in-depth redaction of MCP subprocess output."""

    def test_redacts_authorization_bearer_header(self) -> None:
        text = "GET /api HTTP/1.1\nAuthorization: Bearer abcdef1234567890token\n"
        redacted = core._redact_secrets(text)
        self.assertNotIn("abcdef1234567890token", redacted)
        self.assertIn("Authorization: Bearer [REDACTED]", redacted)

    def test_redacts_authorization_splunk_session(self) -> None:
        text = 'curl -H "Authorization: Splunk abc123sessiondef456"'
        redacted = core._redact_secrets(text)
        self.assertNotIn("abc123sessiondef456", redacted)
        self.assertIn("Authorization: Splunk [REDACTED]", redacted)

    def test_redacts_kv_pairs_with_secret_names(self) -> None:
        text = (
            "ERROR: failed login for password=hunter2supersecret on host x\n"
            "client_secret = 'abc123def456ghi789' from config"
        )
        redacted = core._redact_secrets(text)
        self.assertNotIn("hunter2supersecret", redacted)
        self.assertNotIn("abc123def456ghi789", redacted)
        self.assertIn("password=[REDACTED]", redacted)
        self.assertIn("client_secret = '[REDACTED]", redacted)

    def test_redacts_splunk_password_environment_names(self) -> None:
        text = "SPLUNK_PASS=abcdef123456 SB_PASS='fedcba654321'"
        redacted = core._redact_secrets(text)
        self.assertNotIn("abcdef123456", redacted)
        self.assertNotIn("fedcba654321", redacted)
        self.assertIn("SPLUNK_PASS=[REDACTED]", redacted)
        self.assertIn("SB_PASS='[REDACTED]", redacted)

    def test_redacts_jwt(self) -> None:
        # Synthetic three-segment JWT-shaped string.
        text = "token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        redacted = core._redact_secrets(text)
        self.assertNotIn("SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", redacted)
        self.assertIn("[REDACTED-JWT]", redacted)

    def test_redacts_pem_private_key_block(self) -> None:
        text = (
            "Found cert and key:\n"
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQ\n"
            "VERY_SENSITIVE_KEY_MATERIAL_HERE\n"
            "-----END RSA PRIVATE KEY-----\n"
            "OK\n"
        )
        redacted = core._redact_secrets(text)
        self.assertNotIn("VERY_SENSITIVE_KEY_MATERIAL_HERE", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_does_not_mangle_short_or_non_secret_values(self) -> None:
        # Short values (<6 chars after KEY=) and unrelated text pass through.
        text = "name=alice region=usa retries=3 timeout=30s\nLooks fine here.\n"
        self.assertEqual(core._redact_secrets(text), text)

    def test_redaction_is_applied_in_truncate_helper(self) -> None:
        text = "Authorization: Bearer abcdef1234567890token"
        out = core._truncate_and_redact(text)
        self.assertNotIn("abcdef1234567890token", out)
        self.assertIn("[REDACTED]", out)

    def test_truncate_and_redact_handles_empty(self) -> None:
        self.assertEqual(core._truncate_and_redact(""), "")


if __name__ == "__main__":
    unittest.main()
