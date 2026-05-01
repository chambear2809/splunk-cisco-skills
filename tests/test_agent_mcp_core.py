"""Regression coverage for the repo-local MCP agent core."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from agent.splunk_cisco_skills_mcp import core


class AgentMCPCoreTests(unittest.TestCase):
    def test_list_skills_includes_catalog_and_script_metadata(self) -> None:
        payload = core.list_skills()
        skills = {item["name"]: item for item in payload["skills"]}

        self.assertIn("cisco-product-setup", skills)
        self.assertIn("setup.sh", skills["cisco-product-setup"]["scripts"])
        self.assertFalse(skills["cisco-product-setup"]["has_template"])

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

    def test_resolve_product_list_products_is_read_only(self) -> None:
        plan = core.plan_skill_script(
            "cisco-product-setup",
            "resolve_product.sh",
            ["--list-products"],
        )
        self.assertTrue(plan["read_only"])

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


if __name__ == "__main__":
    unittest.main()
