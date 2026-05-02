#!/usr/bin/env python3
"""Regression tests for Splunk platform service skill renderers."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


AGENT_RENDERER = REPO_ROOT / "skills/splunk-agent-management-setup/scripts/render_assets.py"
WORKLOAD_RENDERER = REPO_ROOT / "skills/splunk-workload-management-setup/scripts/render_assets.py"
HEC_RENDERER = REPO_ROOT / "skills/splunk-hec-service-setup/scripts/render_assets.py"
AGENT_SETUP = REPO_ROOT / "skills/splunk-agent-management-setup/scripts/setup.sh"
WORKLOAD_SETUP = REPO_ROOT / "skills/splunk-workload-management-setup/scripts/setup.sh"
HEC_SETUP = REPO_ROOT / "skills/splunk-hec-service-setup/scripts/setup.sh"


class SplunkPlatformServiceRendererTests(unittest.TestCase):
    def run_renderer(self, renderer: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(renderer), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_service_setup_wrappers_return_success_for_render_phase(self) -> None:
        cases = [
            (AGENT_SETUP, ["--mode", "agent-manager"], "agent-management/serverclass.conf"),
            (WORKLOAD_SETUP, [], "workload-management/workload_pools.conf"),
            (HEC_SETUP, [], "hec-service/inputs.conf.template"),
        ]
        for setup_script, extra_args, expected_asset in cases:
            with self.subTest(setup_script=setup_script.name), tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    ["bash", str(setup_script), "--output-dir", tmpdir, *extra_args],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                self.assertTrue((Path(tmpdir) / expected_asset).exists())

    def test_agent_management_renders_serverclass_and_deployment_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                AGENT_RENDERER,
                "--output-dir",
                tmpdir,
                "--mode",
                "both",
                "--agent-manager-uri",
                "https://am01.example.com:8089",
                "--serverclass-name",
                "linux_forwarders",
                "--deployment-app-name",
                "ZZZ_linux_base",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "agent-management"
            serverclass = (render_dir / "serverclass.conf").read_text(encoding="utf-8")
            deploymentclient = (render_dir / "deploymentclient.conf").read_text(encoding="utf-8")

            self.assertIn("[serverClass:linux_forwarders]", serverclass)
            self.assertIn("[serverClass:linux_forwarders:app:ZZZ_linux_base]", serverclass)
            self.assertEqual(serverclass.count("filterType = whitelist"), 2)
            self.assertIn("targetUri = https://am01.example.com:8089", deploymentclient)
            self.assertIn("serverRepositoryLocationPolicy = rejectAlways", deploymentclient)

    def test_agent_management_agent_manager_mode_omits_blank_deployment_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                AGENT_RENDERER,
                "--output-dir",
                tmpdir,
                "--mode",
                "agent-manager",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "agent-management"

            self.assertTrue((render_dir / "serverclass.conf").exists())
            self.assertFalse((render_dir / "deploymentclient.conf").exists())

    def test_workload_management_renders_documented_rule_state_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                WORKLOAD_RENDERER,
                "--output-dir",
                tmpdir,
                "--profile",
                "ingest-protect",
                "--enable-workload-management",
                "--enable-admission-rules",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "workload-management"
            pools = (render_dir / "workload_pools.conf").read_text(encoding="utf-8")
            rules = (render_dir / "workload_rules.conf").read_text(encoding="utf-8")
            policy = (render_dir / "workload_policy.conf").read_text(encoding="utf-8")

            self.assertIn("enabled = true", pools)
            self.assertIn("workload_pool_base_dir_name = splunk", pools)
            self.assertIn("cpu_weight = 35", pools)
            self.assertIn("[workload_rules_order]", rules)
            self.assertIn("rules = critical_role_to_search_critical,long_running_search_guardrail", rules)
            self.assertIn("disabled = 0", rules)
            self.assertNotIn("enabled = 1", rules)
            self.assertIn("[search_filter_rule:block_alltime_searches]", rules)
            self.assertIn("action = filter", rules)
            self.assertIn("admission_rules_enabled = 1", policy)
            guardrail_stanza = rules.split("[workload_rule:long_running_search_guardrail]", 1)[1].split("\n\n", 1)[0]
            self.assertIn("action = abort", guardrail_stanza)
            self.assertNotIn("workload_pool =", guardrail_stanza)

    def test_workload_management_move_action_includes_destination_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                WORKLOAD_RENDERER,
                "--output-dir",
                tmpdir,
                "--long-running-action",
                "move",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            rules = (Path(tmpdir) / "workload-management" / "workload_rules.conf").read_text(encoding="utf-8")
            guardrail_stanza = rules.split("[workload_rule:long_running_search_guardrail]", 1)[1].split("\n\n", 1)[0]

            self.assertIn("action = move", guardrail_stanza)
            self.assertIn("workload_pool = search_standard", guardrail_stanza)

    def test_workload_management_rejects_invalid_alltime_queue_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                WORKLOAD_RENDERER,
                "--output-dir",
                tmpdir,
                "--admission-alltime-action",
                "queue",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid choice", result.stderr)

    def test_workload_setup_wrapper_renders_with_default_optional_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "skills/splunk-workload-management-setup/scripts/setup.sh"),
                    "--output-dir",
                    tmpdir,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertTrue((Path(tmpdir) / "workload-management" / "workload_pools.conf").exists())

    def test_hec_enterprise_render_keeps_token_values_out_of_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "token.secret"
            token_file.write_text("SUPER_SECRET_HEC_TOKEN\n", encoding="utf-8")
            output_dir = Path(tmpdir) / "rendered"
            result = self.run_renderer(
                HEC_RENDERER,
                "--platform",
                "enterprise",
                "--output-dir",
                str(output_dir),
                "--token-name",
                "app_hec",
                "--default-index",
                "app",
                "--allowed-indexes",
                "app,summary",
                "--token-file",
                str(token_file),
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = output_dir / "hec-service"
            template = (render_dir / "inputs.conf.template").read_text(encoding="utf-8")
            apply_script = (render_dir / "apply-enterprise-files.sh").read_text(encoding="utf-8")
            all_assets = "\n".join(
                path.read_text(encoding="utf-8")
                for path in render_dir.iterdir()
                if path.is_file()
            )

            self.assertIn("[http://app_hec]", template)
            self.assertIn("token = __HEC_TOKEN_FROM_FILE__", template)
            self.assertIn("indexes = app,summary", template)
            self.assertIn("token_path.read_text", apply_script)
            self.assertIn("uuid.UUID(token)", apply_script)
            self.assertNotIn("SUPER_SECRET_HEC_TOKEN", all_assets)

    def test_hec_cloud_render_includes_acs_payloads_and_command_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                HEC_RENDERER,
                "--platform",
                "cloud",
                "--output-dir",
                tmpdir,
                "--token-name",
                "cloud_hec",
                "--default-index",
                "netops",
                "--allowed-indexes",
                "netops,summary",
                "--source",
                "cloud-source",
                "--sourcetype",
                "cloud:json",
                "--use-ack",
                "true",
                "--write-token-file",
                "/tmp/cloud_hec_token",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "hec-service"
            payload = json.loads((render_dir / "acs-hec-token.json").read_text(encoding="utf-8"))
            cloud_script = (render_dir / "apply-cloud-acs.sh").read_text(encoding="utf-8")

            self.assertEqual(payload["name"], "cloud_hec")
            self.assertEqual(payload["allowedIndexes"], ["netops", "summary"])
            self.assertEqual(payload["defaultIndex"], "netops")
            self.assertTrue(payload["useACK"])
            self.assertIn("hec-token", cloud_script)
            self.assertIn("http-event-collectors", cloud_script)
            self.assertIn("write_token_from_output", cloud_script)
            self.assertIn("add_allowed_indexes_if_supported", cloud_script)

    def test_hec_cloud_render_omits_blank_optional_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                HEC_RENDERER,
                "--platform",
                "cloud",
                "--output-dir",
                tmpdir,
                "--token-name",
                "cloud_hec",
                "--default-index",
                "netops",
                "--allowed-indexes",
                "netops",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = json.loads((Path(tmpdir) / "hec-service" / "acs-hec-token.json").read_text(encoding="utf-8"))
            cloud_script = (Path(tmpdir) / "hec-service" / "apply-cloud-acs.sh").read_text(encoding="utf-8")

            self.assertNotIn("defaultSource", payload)
            self.assertNotIn("defaultSourcetype", payload)
            self.assertIn("add_optional_flag_if_supported", cloud_script)

    def test_hec_rejects_newline_in_token_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                HEC_RENDERER,
                "--output-dir",
                tmpdir,
                "--token-file",
                "/tmp/good\nbad",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not contain newlines", result.stderr)


if __name__ == "__main__":
    unittest.main()
