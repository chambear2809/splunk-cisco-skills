"""Regression coverage for the repo-local MCP agent core."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent.splunk_cisco_skills_mcp import core


class AgentMCPCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)
        os.environ["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
        os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION", None)
        os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)

    def test_list_skills_includes_catalog_and_script_metadata(self) -> None:
        payload = core.list_skills()
        skills = {item["name"]: item for item in payload["skills"]}

        self.assertIn("cisco-product-setup", skills)
        self.assertIn("setup.sh", skills["cisco-product-setup"]["scripts"])
        self.assertFalse(skills["cisco-product-setup"]["has_template"])

    def test_operator_catalog_matches_skill_catalog(self) -> None:
        readme = (core.REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("SKILL_UX_CATALOG.md", readme)

        catalog = (core.REPO_ROOT / "SKILL_UX_CATALOG.md").read_text(encoding="utf-8")
        catalog_doc_skills = set(
            re.findall(r"^\| `([^`]+)` \|", catalog, flags=re.MULTILINE)
        )
        catalog_skills = {item["name"] for item in core.list_skills()["skills"]}

        self.assertEqual(catalog_doc_skills, catalog_skills)

    def test_list_skills_exposes_references_directory(self) -> None:
        payload = core.list_skills()
        skills = {item["name"]: item for item in payload["skills"]}
        dashboard_skill = skills["splunk-observability-dashboard-builder"]

        self.assertTrue(dashboard_skill["has_reference"])
        self.assertEqual(
            dashboard_skill["reference_files"],
            [
                "reference.md",
                "references/classic-api.md",
                "references/coverage.md",
            ],
        )
        reference_text = core.read_skill_file(
            "splunk-observability-dashboard-builder", "reference"
        )
        self.assertIn("# reference.md", reference_text)
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
                "alert_rules": "12345",
            },
        )

        self.assertEqual(
            plan["dry_run"]["resolved_product"]["id"], "cisco_thousandeyes"
        )
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
        with self.assertRaisesRegex(
            core.SkillMCPError, "secret_files must be an object"
        ):
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
            (
                "splunk-observability-aws-integration",
                ["--aws-access-key-id", "AKIA..."],
            ),
            (
                "splunk-observability-aws-integration",
                ["--aws-secret-access-key=secret-value"],
            ),
            (
                "splunk-observability-aws-integration",
                ["--aws-secret-key", "secret-value"],
            ),
            (
                "splunk-observability-aws-integration",
                ["--external-id", "sensitive-external-id"],
            ),
            (
                "splunk-observability-database-monitoring-setup",
                ["--db-password", "secret-value"],
            ),
            (
                "splunk-observability-database-monitoring-setup",
                ["--connection-string=postgres://user:pass@db"],
            ),
            (
                "splunk-observability-database-monitoring-setup",
                ["--datasource", "postgres://user:pass@db"],
            ),
            (
                "splunk-observability-k8s-frontend-rum-setup",
                ["--rum-token", "secret-value"],
            ),
            ("galileo-platform-setup", ["--galileo-api-key", "secret-value"]),
            ("galileo-platform-setup", ["--splunk-hec-token=secret-value"]),
            (
                "galileo-agent-control-setup",
                ["--agent-control-api-key", "secret-value"],
            ),
            ("galileo-agent-control-setup", ["--agent-control-admin-key=secret-value"]),
            (
                "splunk-appdynamics-controller-admin-setup",
                ["--controller-password", "secret-value"],
            ),
            ("splunk-appdynamics-analytics-setup", ["--events-api-key=secret-value"]),
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

    def test_generic_script_plans_are_always_mutation_gated(self) -> None:
        cases = (
            ("splunk-oncall-setup", "setup.sh", ["--render"]),
            ("splunk-oncall-setup", "setup.sh", ["--apply", "--dry-run"]),
            ("cisco-product-setup", "resolve_product.sh", ["--help"]),
            ("cisco-product-setup", "setup.sh", ["--list-products"]),
            ("splunk-cloud-acs-admin-setup", "smoke_offline.sh", []),
            ("splunk-universal-forwarder-setup", "setup.sh", []),
            (
                "splunk-observability-mobile-rum-setup",
                "setup.sh",
                ["--source-mode", "apply-patches"],
            ),
        )
        # This test enumerates every script and is concerned only with the
        # authorization classification. Avoid recomputing the whole-tree
        # integrity snapshot hundreds of times here; dedicated tests cover it.
        with mock.patch.object(core, "_skills_snapshot_sha256", return_value="1" * 64):
            for skill, script, args in cases:
                with self.subTest(skill=skill, script=script, args=args):
                    plan = core.plan_skill_script(skill, script, args)
                    self.assertFalse(plan["read_only"])

            planned = 0
            for skill_dir in core._skill_dirs():
                scripts_dir = skill_dir / "scripts"
                if not scripts_dir.is_dir():
                    continue
                for path in scripts_dir.iterdir():
                    supported = path.suffix.lower() in {
                        ".sh",
                        ".py",
                        ".rb",
                    } or os.access(path, os.X_OK)
                    if not path.is_file() or not supported:
                        continue
                    with self.subTest(skill=skill_dir.name, script=path.name):
                        plan = core.plan_skill_script(skill_dir.name, path.name, [])
                        self.assertFalse(plan["read_only"])
                        planned += 1
            self.assertGreater(planned, 0)

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
        self.assertIn(
            "'/tmp/x; touch /tmp/agent_review_injected_password'", command["command"]
        )

    def test_generic_script_plan_uses_script_interpreter(self) -> None:
        python_plan = core.plan_skill_script(
            "cisco-product-setup", "build_catalog.py", ["--check"]
        )
        ruby_plan = core.plan_skill_script(
            "splunk-itsi-config", "spec_to_json.rb", ["--help"]
        )

        self.assertEqual(python_plan["command"][0], sys.executable)
        self.assertEqual(ruby_plan["command"][0], "ruby")

    def test_all_execution_requires_explicit_enable_gate(self) -> None:
        plan = core._store_plan(
            kind="typed_read_only_test",
            command=[
                "bash",
                "skills/cisco-product-setup/scripts/resolve_product.sh",
                "--help",
            ],
            summary="read-only execution gate test",
            read_only=True,
        )
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPLUNK_SKILLS_MCP_ENABLE_EXECUTION", None)
            os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)
            with self.assertRaisesRegex(
                core.SkillMCPError, "Subprocess execution is disabled"
            ):
                core.execute_plan(plan["plan_hash"], confirm=True)

            os.environ["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
            result = core.execute_plan(plan["plan_hash"], confirm=True)

        self.assertEqual(result["returncode"], 0)
        self.assertIn("Usage:", result["stdout"] + result["stderr"])

    def test_product_validate_only_plan_remains_mutation_gated(self) -> None:
        plan = core.plan_cisco_product_setup("Cisco ACI", phase="validate")

        self.assertFalse(plan["read_only"])
        with self.assertRaisesRegex(
            core.SkillMCPError, "Mutating execution is disabled"
        ):
            core.execute_plan(
                plan["plan_hash"],
                confirm=True,
                expected_kind="cisco_product_setup",
            )

    def test_execute_mutating_plan_requires_mutation_gate(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION"] = "1"
            os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)
            plan = core.plan_skill_script(
                "cisco-catalyst-ta-setup",
                "configure_account.sh",
                [],
            )
            with self.assertRaisesRegex(
                core.SkillMCPError, "Mutating execution is disabled"
            ):
                core.execute_plan(plan["plan_hash"], confirm=True)

    def test_generic_plan_requires_its_separate_execution_gate(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
            os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION", None)
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = "1"
            plan = core.plan_skill_script(
                "cisco-product-setup",
                "resolve_product.sh",
                ["--help"],
            )
            with self.assertRaisesRegex(
                core.SkillMCPError,
                "Generic skill-script execution is disabled",
            ):
                core.execute_plan(plan["plan_hash"], confirm=True)

    def test_execute_mutating_plan_runs_when_gate_is_open(self) -> None:
        # Complement to test_execute_mutating_plan_requires_mutation_gate:
        # confirms that setting SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1 opens the
        # gate and the planned mutating command actually runs. We use
        # configure_account.sh with empty args so the script fails fast on
        # missing required flags (returncode != 0) without contacting Splunk
        # — what we are asserting is that the gate did NOT block execution.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = "1"
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

    def test_runner_reports_missing_mcp_dependency_without_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, "-I", "agent/run-splunk-cisco-skills-mcp.py"],
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
                payload = json.loads(
                    (core.REPO_ROOT / rel_path).read_text(encoding="utf-8")
                )
                server = payload["mcpServers"]["splunk-cisco-skills"]
                self.assertRegex(server["command"], r"python3?(\b|$)")
                self.assertIn("-I", server["args"])
                self.assertTrue(
                    any(
                        "run-splunk-cisco-skills-mcp.py" in argument
                        for argument in server["args"]
                    )
                )
                self.assertEqual(
                    server["env"],
                    {
                        "SPLUNK_SKILLS_MCP_ENABLE_EXECUTION": "1",
                        "SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION": "0",
                        "SPLUNK_SKILLS_MCP_ALLOW_MUTATION": "0",
                    },
                )

    def test_codex_registration_helper_points_at_local_agent_server(self) -> None:
        script = core.REPO_ROOT / "agent/register-codex-splunk-cisco-skills-mcp.sh"
        text = script.read_text(encoding="utf-8")

        self.assertTrue(os.access(script, os.X_OK))
        self.assertIn("codex mcp add", text)
        self.assertIn("run-splunk-cisco-skills-mcp.py", text)
        self.assertIn("PYTHON_BIN", text)
        self.assertIn('"${PYTHON_BIN}" -I', text)

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
            {
                product["automation_state"]
                for product in core.list_cisco_products()["products"]
            },
        )
        self.assertIn("unsupported_roadmap", core._VALID_PRODUCT_STATES)

    def test_claude_rule_uses_secret_writer_helper(self) -> None:
        text = (core.REPO_ROOT / ".claude/rules/credential-handling.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("skills/shared/scripts/write_secret_file.sh", text)
        self.assertNotIn('echo "the_secret"', text)

    def test_execute_plan_consumes_plan_on_success(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = "1"
            plan = core.plan_skill_script(
                "cisco-product-setup",
                "resolve_product.sh",
                ["--help"],
            )
            plan_hash = plan["plan_hash"]
            core.execute_plan(plan_hash, confirm=True)
            with self.assertRaisesRegex(core.SkillMCPError, "Unknown plan_hash"):
                core.execute_plan(plan_hash, confirm=True)

    def test_execute_plan_keeps_plan_when_confirm_missing(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = "1"
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
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION"] = "1"
            os.environ.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)
            plan = core.plan_skill_script(
                "cisco-catalyst-ta-setup",
                "configure_account.sh",
                [],
            )
            plan_hash = plan["plan_hash"]
            with self.assertRaisesRegex(
                core.SkillMCPError, "Mutating execution is disabled"
            ):
                core.execute_plan(plan_hash, confirm=True)
            # A blocked mutation should not destroy the plan; the operator
            # can fix the env var and retry.
            with self.assertRaisesRegex(
                core.SkillMCPError, "Mutating execution is disabled"
            ):
                core.execute_plan(plan_hash, confirm=True)

    def test_execute_plan_rejects_malformed_hash(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "64-character lowercase hex"):
            core.execute_plan("not-a-hash", confirm=True)
        with self.assertRaisesRegex(core.SkillMCPError, "64-character lowercase hex"):
            core.execute_plan("A" * 64, confirm=True)

    def test_timeout_rejects_bool(self) -> None:
        with self.assertRaisesRegex(
            core.SkillMCPError, "timeout_seconds must be an integer"
        ):
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

    def test_replanning_identical_command_uses_random_single_use_ids(self) -> None:
        first = core.plan_skill_script(
            "cisco-product-setup",
            "resolve_product.sh",
            ["--help"],
        )
        second = core.plan_skill_script(
            "cisco-product-setup",
            "resolve_product.sh",
            ["--help"],
        )

        self.assertRegex(first["plan_hash"], core.PLAN_HASH_RE)
        self.assertRegex(second["plan_hash"], core.PLAN_HASH_RE)
        self.assertNotEqual(first["plan_hash"], second["plan_hash"])
        self.assertEqual(first["executable_sha256"], second["executable_sha256"])
        self.assertEqual(first["repository_sha256"], second["repository_sha256"])

    def test_generic_plan_records_executable_digest(self) -> None:
        plan = core.plan_skill_script(
            "cisco-product-setup",
            "resolve_product.sh",
            ["--help"],
        )

        executable = Path(plan["executable_path"])
        self.assertTrue(executable.is_file())
        self.assertEqual(plan["executable_sha256"], core._file_sha256(executable))
        self.assertEqual(plan["repository_sha256"], core._skills_snapshot_sha256())

    def test_execute_invalidates_plan_when_executable_digest_changes(self) -> None:
        plan = core.plan_skill_script(
            "cisco-product-setup",
            "resolve_product.sh",
            ["--help"],
        )
        plan_hash = plan["plan_hash"]

        with (
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(core, "_file_sha256", return_value="0" * 64),
        ):
            os.environ["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = "1"
            with self.assertRaisesRegex(core.SkillMCPError, "changed after review"):
                core.execute_plan(plan_hash, confirm=True)

        self.assertNotIn(plan_hash, core._PLANS)

    def test_execute_invalidates_plan_when_skill_repository_changes(self) -> None:
        plan = core.plan_skill_script(
            "cisco-product-setup",
            "resolve_product.sh",
            ["--help"],
        )
        plan_hash = plan["plan_hash"]

        with (
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(core, "_skills_snapshot_sha256", return_value="0" * 64),
        ):
            os.environ["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = "1"
            with self.assertRaisesRegex(core.SkillMCPError, "repository changed"):
                core.execute_plan(plan_hash, confirm=True)

        self.assertNotIn(plan_hash, core._PLANS)

    def test_generic_script_argument_limits_fail_closed(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "more than"):
            core.plan_skill_script(
                "cisco-product-setup",
                "resolve_product.sh",
                ["x"] * (core.MAX_ARG_COUNT + 1),
            )
        with self.assertRaisesRegex(core.SkillMCPError, "character limit"):
            core.plan_skill_script(
                "cisco-product-setup",
                "resolve_product.sh",
                ["x" * (core.MAX_ARG_CHARS + 1)],
            )
        per_arg = "x" * core.MAX_ARG_CHARS
        count = core.MAX_TOTAL_ARG_CHARS // core.MAX_ARG_CHARS + 1
        with self.assertRaisesRegex(core.SkillMCPError, "aggregate limit"):
            core.plan_skill_script(
                "cisco-product-setup",
                "resolve_product.sh",
                [per_arg] * count,
            )

    def test_generic_script_rejects_inline_secret_payloads(self) -> None:
        secret_payloads = (
            "Authorization: Bearer abcdefghijklmnop",
            '{"clientSecret":"abcdefghijklmnop"}',
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.signature",
            "-----BEGIN PRIVATE KEY-----secret",
        )
        for payload in secret_payloads:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(core.SkillMCPError, "inline secret"):
                    core.plan_skill_script(
                        "cisco-product-setup",
                        "resolve_product.sh",
                        ["--header", payload],
                    )

    def test_typed_mapping_limits_fail_closed(self) -> None:
        with self.assertRaisesRegex(core.SkillMCPError, "more than"):
            core.plan_cisco_product_setup(
                "Cisco ACI",
                set_values={
                    f"key_{index}": "value"
                    for index in range(core.MAX_MAPPING_ENTRIES + 1)
                },
            )
        with self.assertRaisesRegex(core.SkillMCPError, "character limit"):
            core.plan_cisco_product_setup(
                "Cisco ACI",
                set_values={"hostname": "x" * (core.MAX_ARG_CHARS + 1)},
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
        with self.assertRaisesRegex(
            core.SkillMCPError, "template.example or templates"
        ):
            core.read_skill_file("cisco-product-setup", "template")

    def test_execute_plan_keeps_plan_when_kind_mismatches(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION"] = "1"
            os.environ["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = "1"
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

    def test_run_command_isolates_stdin_and_process_group(self) -> None:
        class FakeProc:
            pid = 12345

            def __init__(self) -> None:
                self.stdout = io.BytesIO(b"ok\n")
                self.stderr = io.BytesIO(b"")

            def wait(self, timeout: int | None = None) -> int:
                return 0

        fake_proc = FakeProc()
        with mock.patch.object(
            core.subprocess, "Popen", return_value=fake_proc
        ) as popen:
            result = core._run_command(["fake"], timeout_seconds=1)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "ok\n")
        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs["stdin"], core.subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])

    def test_child_environment_removes_code_injection_hooks_and_unsafe_path(
        self,
    ) -> None:
        hostile = {
            "BASH_ENV": "/tmp/bash-env",
            "PYTHONPATH": "/tmp/python",
            "PYTHONWARNINGS": "all:evil:Warning:evil",
            "RUBYOPT": "-revil",
            "NODE_OPTIONS": "--require=/tmp/evil.js",
            "JAVA_TOOL_OPTIONS": "-javaagent:/tmp/evil.jar",
            "LD_PRELOAD": "/tmp/evil.so",
            "DYLD_INSERT_LIBRARIES": "/tmp/evil.dylib",
            "PROMPT_COMMAND": "touch /tmp/evil",
            "PS4": "$(touch /tmp/evil)",
            "SPLUNK_SKILLS_MCP_ALLOW_MUTATION": "1",
            "BASH_FUNC_evil%%": "() { :; }",
            "PATH": f"/tmp{os.pathsep}/usr/bin",
        }
        with mock.patch.dict(os.environ, hostile, clear=False):
            child = core._child_environment()

        for key in hostile:
            if key != "PATH":
                self.assertNotIn(key, child)
        self.assertNotIn("/tmp", child["PATH"].split(os.pathsep))
        self.assertTrue(
            all(Path(item).is_absolute() for item in child["PATH"].split(os.pathsep))
        )

    def test_cancelled_plan_creation_cannot_leave_an_undisclosed_plan(self) -> None:
        cancellation = core.CommandCancellation()
        entered_snapshot = threading.Event()
        release_snapshot = threading.Event()
        initial_plans = set(core._PLANS)
        outcome: dict[str, object] = {}

        def delayed_snapshot() -> str:
            entered_snapshot.set()
            self.assertTrue(release_snapshot.wait(timeout=5))
            return "1" * 64

        def create_plan() -> None:
            try:
                outcome["plan"] = core.plan_skill_script(
                    "cisco-product-setup",
                    "resolve_product.sh",
                    ["--help"],
                    cancellation=cancellation,
                )
            except Exception as exc:  # noqa: BLE001 - captured for thread assertion
                outcome["error"] = exc

        with mock.patch.object(core, "_skills_snapshot_sha256", delayed_snapshot):
            worker = threading.Thread(target=create_plan, daemon=True)
            worker.start()
            self.assertTrue(entered_snapshot.wait(timeout=5))
            cancellation.cancel()
            release_snapshot.set()
            worker.join(timeout=10)

        self.assertFalse(worker.is_alive())
        self.assertIsInstance(outcome.get("error"), core.SkillMCPError)
        self.assertNotIn("plan", outcome)
        self.assertEqual(set(core._PLANS), initial_plans)

    def test_credential_status_rejects_symlink_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "credentials.target"
            target.write_text("SPLUNK_PASSWORD=not-read-by-test\n", encoding="utf-8")
            target.chmod(0o600)
            linked = Path(tmpdir) / "credentials"
            linked.symlink_to(target)
            with mock.patch.dict(
                os.environ,
                {"SPLUNK_CREDENTIALS_FILE": str(linked)},
                clear=False,
            ):
                payload = core.credential_status()

        entry = payload["candidates"][0]
        self.assertTrue(entry["exists"])
        self.assertFalse(entry["regular_file"])
        self.assertFalse(entry["secure_mode"])
        self.assertIn("symbolic link", entry["reasons"])
        self.assertIsNot(payload["active"], entry)

    def test_run_command_returns_structured_error_when_spawn_fails(self) -> None:
        with mock.patch.object(
            core.subprocess,
            "Popen",
            side_effect=FileNotFoundError("missing-binary"),
        ):
            result = core._run_command(["missing-binary"], timeout_seconds=1)

        self.assertEqual(result.returncode, 127)
        self.assertIn("Failed to start command", result.stderr)

    def test_run_command_requires_enable_execution_gate(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(core.subprocess, "Popen") as popen,
        ):
            os.environ.pop("SPLUNK_SKILLS_MCP_ENABLE_EXECUTION", None)
            with self.assertRaisesRegex(
                core.SkillMCPError, "Subprocess execution is disabled"
            ):
                core._run_command(["never-started"], timeout_seconds=1)
        popen.assert_not_called()

    def test_command_cancellation_terminates_active_process(self) -> None:
        cancellation = core.CommandCancellation()
        outcome: dict[str, object] = {}

        def run() -> None:
            outcome["result"] = core._run_command(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout_seconds=60,
                cancellation=cancellation,
            )

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with cancellation._lock:
                if cancellation._process is not None:
                    break
            time.sleep(0.01)
        else:
            cancellation.cancel()
            self.fail("subprocess was not attached to its cancellation handle")

        cancellation.cancel()
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), "cancelled subprocess did not terminate")
        result = outcome["result"]
        self.assertIsInstance(result, core._BoundedResult)
        self.assertTrue(result.cancelled)  # type: ignore[union-attr]
        self.assertFalse(result.timed_out)  # type: ignore[union-attr]

    @unittest.skipUnless(os.name == "posix", "POSIX signals are required")
    def test_command_cancellation_kills_sigterm_ignoring_process(self) -> None:
        cancellation = core.CommandCancellation()
        outcome: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            ready = Path(tmpdir) / "ready"
            command = [
                sys.executable,
                "-c",
                (
                    "import pathlib,signal,time; "
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    f"pathlib.Path({str(ready)!r}).write_text('ready'); "
                    "time.sleep(30)"
                ),
            ]

            def run() -> None:
                outcome["result"] = core._run_command(
                    command,
                    timeout_seconds=60,
                    cancellation=cancellation,
                )

            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not ready.exists():
                time.sleep(0.01)
            self.assertTrue(ready.exists(), "child never installed its SIGTERM handler")

            started = time.monotonic()
            cancellation.cancel()
            worker.join(timeout=5)
            elapsed = time.monotonic() - started

        self.assertFalse(
            worker.is_alive(), "SIGTERM-ignoring child survived cancellation"
        )
        self.assertLess(elapsed, 3)
        result = outcome["result"]
        self.assertIsInstance(result, core._BoundedResult)
        self.assertTrue(result.cancelled)  # type: ignore[union-attr]

    @unittest.skipUnless(os.name == "posix", "POSIX process groups are required")
    def test_command_cancellation_kills_descendant_after_leader_exits(self) -> None:
        cancellation = core.CommandCancellation()
        outcome: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            ready = Path(tmpdir) / "descendant-ready"
            survived = Path(tmpdir) / "descendant-survived"
            child_code = (
                "import pathlib,signal,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"pathlib.Path({str(ready)!r}).write_text('ready'); "
                "time.sleep(2); "
                f"pathlib.Path({str(survived)!r}).write_text('survived'); "
                "time.sleep(30)"
            )
            parent_code = (
                "import subprocess,sys,time; "
                f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
                "time.sleep(30)"
            )

            def run() -> None:
                outcome["result"] = core._run_command(
                    [sys.executable, "-c", parent_code],
                    timeout_seconds=60,
                    cancellation=cancellation,
                )

            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not ready.exists():
                time.sleep(0.01)
            self.assertTrue(
                ready.exists(), "descendant never installed its SIGTERM handler"
            )

            cancellation.cancel()
            worker.join(timeout=5)
            self.assertFalse(
                worker.is_alive(), "cancelled process group did not terminate"
            )
            time.sleep(1.25)
            self.assertFalse(
                survived.exists(),
                "SIGTERM-ignoring descendant survived after its group leader exited",
            )

        result = outcome["result"]
        self.assertIsInstance(result, core._BoundedResult)
        self.assertTrue(result.cancelled)  # type: ignore[union-attr]

    def test_bounded_resource_reader_does_not_load_entire_file(self) -> None:
        path = mock.Mock()
        path.name = "oversized.txt"
        path.stat.return_value.st_size = 10_000
        handle = mock.mock_open(read_data=b"x" * 10_000)
        path.open = handle

        text = core._read_bounded_text(path, 64)

        handle().read.assert_called_once_with(65)
        self.assertTrue(text.startswith("x" * 64))
        self.assertIn("truncated", text)

    def test_resource_file_count_limit_fails_closed(self) -> None:
        skill_dir = core.SKILLS_DIR / "splunk-observability-dashboard-builder"
        with mock.patch.object(core, "MAX_RESOURCE_FILES", 1):
            with self.assertRaisesRegex(core.SkillMCPError, "too many reference files"):
                core._skill_reference_files(skill_dir)

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
                normalized = core.re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").lower()
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
        self.assertIn("[REDACTED-PRIVATE-KEY]", redacted)

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
