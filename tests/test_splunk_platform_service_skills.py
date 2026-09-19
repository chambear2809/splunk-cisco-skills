#!/usr/bin/env python3
"""Regression tests for Splunk platform service skill renderers."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT, write_executable


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

    def render_cloud_hec_apply(
        self,
        tmp_path: Path,
        cloud_stack: str = "example-stack",
        acs_server: str = "https://admin.splunk.com",
    ) -> Path:
        result = self.run_renderer(
            HEC_RENDERER,
            "--platform",
            "cloud",
            "--stack",
            cloud_stack,
            "--acs-server",
            acs_server,
            "--output-dir",
            str(tmp_path / "rendered"),
            "--token-name",
            "cloud_hec",
            "--default-index",
            "netops",
            "--allowed-indexes",
            "netops,summary",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return tmp_path / "rendered" / "hec-service" / "apply-cloud-acs.sh"

    def cloud_hec_test_env(self, tmp_path: Path, bin_dir: Path) -> dict[str, str]:
        credentials_file = tmp_path / "credentials"
        credentials_file.write_text(
            "\n".join(
                (
                    'SPLUNK_PLATFORM="cloud"',
                    'SPLUNK_CLOUD_STACK="example-stack"',
                    'SPLUNK_SEARCH_API_URI="https://example.invalid:8089"',
                    'SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"',
                    'SPLUNK_USER="synthetic-user"',
                    'SPLUNK_PASS="synthetic-password"',
                )
            )
            + "\n",
            encoding="utf-8",
        )
        credentials_file.chmod(0o600)
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("SPLUNK_", "STACK_", "SB_", "ACS_"))
        }
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
        env["SPLUNK_PLATFORM"] = "cloud"
        return env

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
            preflight = (render_dir / "preflight.sh").read_text(encoding="utf-8")
            self.assertIn("spv_require_supported_splunk_home", preflight)
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
            self.assertIn("token = read_private_secret", apply_script)
            self.assertNotIn("token_path.read_text", apply_script)
            self.assertIn("uuid.UUID(token)", apply_script)
            self.assertIn("spv_require_supported_splunk_home", apply_script)
            self.assertNotIn("SUPER_SECRET_HEC_TOKEN", all_assets)

    def test_hec_cloud_render_includes_acs_payloads_and_command_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                HEC_RENDERER,
                "--platform",
                "cloud",
                "--stack",
                "example-stack",
                "--search-head",
                "sh1",
                "--acs-server",
                "https://admin.splunk.com",
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
            metadata = json.loads((render_dir / "metadata.json").read_text(encoding="utf-8"))
            cloud_script = (render_dir / "apply-cloud-acs.sh").read_text(encoding="utf-8")
            status_script = (render_dir / "status-cloud-acs.sh").read_text(encoding="utf-8")

            self.assertEqual(payload["name"], "cloud_hec")
            self.assertEqual(payload["allowedIndexes"], ["netops", "summary"])
            self.assertEqual(payload["defaultIndex"], "netops")
            self.assertTrue(payload["useACK"])
            self.assertEqual(metadata["cloud_stack"], "example-stack")
            self.assertEqual(metadata["cloud_search_head"], "sh1")
            self.assertEqual(metadata["acs_server"], "https://admin.splunk.com")
            self.assertIn("hec-token", cloud_script)
            self.assertIn("http-event-collectors", cloud_script)
            self.assertIn("write_token_from_output", cloud_script)
            self.assertIn("add_allowed_indexes_if_supported", cloud_script)
            self.assertIn("refusing to print a potentially sensitive response", cloud_script)
            self.assertNotIn("printf '%s\\n' \"${output}\"", cloud_script)
            for script in (cloud_script, status_script):
                self.assertIn("ACS_BOUND_TARGET_CONTEXT=true", script)
                self.assertIn("ACS_BOUND_REQUIRE_CONFIG_MATCH=true", script)
                self.assertIn("ACS_BOUND_SERVER=https://admin.splunk.com", script)
                self.assertIn("ACS_BOUND_SPLUNK_CLOUD_STACK=example-stack", script)
                self.assertIn("ACS_BOUND_SPLUNK_CLOUD_SEARCH_HEAD=sh1", script)

    def test_hec_cloud_renderer_requires_and_reports_bound_target(self) -> None:
        """Deferred regression: direct Cloud plans cannot omit their target."""
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = self.run_renderer(
                HEC_RENDERER,
                "--platform",
                "cloud",
                "--output-dir",
                tmpdir,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("--stack", missing.stderr)

            planned = self.run_renderer(
                HEC_RENDERER,
                "--platform",
                "cloud",
                "--stack",
                "example-stack",
                "--search-head",
                "sh1",
                "--acs-server",
                "https://admin.splunk.com",
                "--output-dir",
                tmpdir,
                "--dry-run",
                "--json",
            )
            self.assertEqual(planned.returncode, 0, msg=planned.stdout + planned.stderr)
            plan = json.loads(planned.stdout)
            self.assertEqual(plan["cloud_stack"], "example-stack")
            self.assertEqual(plan["cloud_search_head"], "sh1")
            self.assertEqual(plan["acs_server"], "https://admin.splunk.com")

    def test_hec_cloud_render_omits_blank_optional_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                HEC_RENDERER,
                "--platform",
                "cloud",
                "--stack",
                "example-stack",
                "--acs-server",
                "https://admin.splunk.com",
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

    def test_hec_cloud_apply_refuses_bound_target_readback_mismatch_before_mutation(self) -> None:
        """Deferred regression: a rendered target mismatch cannot reach HEC mutation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            apply_script = self.render_cloud_hec_apply(tmp_path, cloud_stack="bound-stack")
            mutation_marker = tmp_path / "hec-mutation-reached"
            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = " ".join(sys.argv[1:])
                if "config current-stack" in command:
                    print("Stack: other-stack")
                    raise SystemExit(0)
                if "hec-token create" in command or "hec-token update" in command:
                    Path(os.environ["HEC_MUTATION_MARKER"]).touch()
                raise SystemExit(0)
                """,
            )
            env = self.cloud_hec_test_env(tmp_path, bin_dir)
            env["HEC_MUTATION_MARKER"] = str(mutation_marker)

            result = subprocess.run(
                ["bash", str(apply_script)],
                cwd=apply_script.parent,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, msg=output)
            self.assertIn("configured ACS stack changed", output)
            self.assertFalse(mutation_marker.exists())

    def test_hec_cloud_apply_refuses_same_name_stack_on_other_acs_origin(self) -> None:
        """Deferred regression: prod/staging origin is part of the bound target."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            apply_script = self.render_cloud_hec_apply(
                tmp_path,
                cloud_stack="example-stack",
                acs_server="https://staging.admin.splunk.com",
            )
            mutation_marker = tmp_path / "hec-mutation-reached"
            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = " ".join(sys.argv[1:])
                if "hec-token create" in command or "hec-token update" in command:
                    Path(os.environ["HEC_MUTATION_MARKER"]).touch()
                raise SystemExit(0)
                """,
            )
            env = self.cloud_hec_test_env(tmp_path, bin_dir)
            env["HEC_MUTATION_MARKER"] = str(mutation_marker)

            result = subprocess.run(
                ["bash", str(apply_script)],
                cwd=apply_script.parent,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, msg=output)
            self.assertIn("control-plane origin changed", output)
            self.assertFalse(mutation_marker.exists())

    def test_hec_cloud_status_phase_rejects_stale_target_metadata_before_acs(self) -> None:
        """Deferred regression: status-only cannot reuse assets from another Cloud target."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "rendered"
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            acs_marker = tmp_path / "acs-reached"
            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                from pathlib import Path

                Path(os.environ["ACS_MARKER"]).touch()
                raise SystemExit(0)
                """,
            )
            env = self.cloud_hec_test_env(tmp_path, bin_dir)
            env["ACS_MARKER"] = str(acs_marker)
            rendered = subprocess.run(
                [
                    "bash",
                    str(HEC_SETUP),
                    "--platform",
                    "cloud",
                    "--stack",
                    "example-stack",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(rendered.returncode, 0, msg=rendered.stdout + rendered.stderr)

            status = subprocess.run(
                [
                    "bash",
                    str(HEC_SETUP),
                    "--platform",
                    "cloud",
                    "--phase",
                    "status",
                    "--stack",
                    "example-stack",
                    "--acs-server",
                    "https://staging.admin.splunk.com",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            output = status.stdout + status.stderr
            self.assertNotEqual(status.returncode, 0, msg=output)
            self.assertIn("do not match the requested ACS origin", output)
            self.assertFalse(acs_marker.exists())

    def test_hec_cloud_apply_rejects_malformed_inventory_before_mutation(self) -> None:
        """Deferred regression: malformed successful ACS output is not absence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            apply_script = self.render_cloud_hec_apply(tmp_path)
            mutation_marker = tmp_path / "hec-mutation-reached"
            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = " ".join(sys.argv[1:])
                if "config current-stack" in command:
                    print("Stack: example-stack")
                    raise SystemExit(0)
                if "hec-token list" in command:
                    print(os.environ["HEC_INVENTORY_PAYLOAD"])
                    raise SystemExit(0)
                if "hec-token create" in command or "hec-token update" in command:
                    Path(os.environ["HEC_MUTATION_MARKER"]).touch()
                if "http-event-collectors" in command:
                    raise SystemExit(1)
                raise SystemExit(0)
                """,
            )
            env = self.cloud_hec_test_env(tmp_path, bin_dir)
            env["HEC_MUTATION_MARKER"] = str(mutation_marker)

            for payload in (
                "not-json",
                "[]",
                '[{"type":"http","status":500,"response":"{\\"tokens\\":[]}"}]',
            ):
                with self.subTest(payload=payload):
                    env["HEC_INVENTORY_PAYLOAD"] = payload
                    result = subprocess.run(
                        ["bash", str(apply_script)],
                        cwd=apply_script.parent,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=60,
                    )

                    output = result.stdout + result.stderr
                    self.assertNotEqual(result.returncode, 0, msg=output)
                    self.assertIn("trustworthy HEC token inventory", output)
                    self.assertFalse(
                        mutation_marker.exists(),
                        msg="Malformed or empty ACS inventory authorized an HEC mutation",
                    )

    def test_hec_cloud_apply_requires_post_mutation_readback(self) -> None:
        """Deferred regression: create and update success require state readback."""
        for operation, initially_present in (("create", False), ("update", True)):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                bin_dir = tmp_path / "bin"
                bin_dir.mkdir()
                apply_script = self.render_cloud_hec_apply(tmp_path)
                mutation_marker = tmp_path / "hec-mutation-reached"
                write_executable(
                    bin_dir / "acs",
                    """\
                    #!/usr/bin/env python3
                    import json
                    import os
                    import sys
                    from pathlib import Path

                    command = " ".join(sys.argv[1:])
                    marker = Path(os.environ["HEC_MUTATION_MARKER"])
                    if "config current-stack" in command:
                        print("Stack: example-stack")
                        raise SystemExit(0)
                    if "hec-token list" in command:
                        if marker.exists() and "--count 100" in command:
                            print("not-json")
                            raise SystemExit(0)
                        tokens = []
                        if os.environ["HEC_INITIAL_PRESENT"] == "true":
                            tokens.append({"name": "cloud_hec", "disabled": False})
                        print(json.dumps({"tokens": tokens}))
                        raise SystemExit(0)
                    if "--help" in command and (
                        "hec-token create" in command or "hec-token update" in command
                    ):
                        print(
                            "--default-index --allowed-indexes --default-source "
                            "--default-sourcetype --disabled --use-ack"
                        )
                        raise SystemExit(0)
                    if "hec-token create" in command or "hec-token update" in command:
                        marker.touch()
                        print(json.dumps({"token": "synthetic-token-value"}))
                        raise SystemExit(0)
                    if "http-event-collectors" in command:
                        raise SystemExit(1)
                    raise SystemExit(0)
                    """,
                )
                env = self.cloud_hec_test_env(tmp_path, bin_dir)
                env["HEC_MUTATION_MARKER"] = str(mutation_marker)
                env["HEC_INITIAL_PRESENT"] = "true" if initially_present else "false"

                result = subprocess.run(
                    ["bash", str(apply_script)],
                    cwd=apply_script.parent,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, msg=output)
                self.assertTrue(mutation_marker.exists(), msg="Fixture did not reach mutation")
                self.assertIn("could not be read back", output)
                self.assertNotIn("Created and read back", output)
                self.assertNotIn("Updated and read back", output)

    def test_hec_cloud_apply_accepts_verified_absence_and_create_readback(self) -> None:
        """Deferred regression: trustworthy absence still permits verified create."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            apply_script = self.render_cloud_hec_apply(tmp_path)
            mutation_marker = tmp_path / "hec-create-reached"
            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                command = " ".join(sys.argv[1:])
                marker = Path(os.environ["HEC_MUTATION_MARKER"])
                if "config current-stack" in command:
                    print("Stack: example-stack")
                    raise SystemExit(0)
                if "hec-token list" in command:
                    tokens = []
                    if marker.exists():
                        tokens.append({"name": "cloud_hec", "disabled": False})
                    print(json.dumps({"tokens": tokens}))
                    raise SystemExit(0)
                if "--help" in command and "hec-token create" in command:
                    print(
                        "--default-index --allowed-indexes --default-source "
                        "--default-sourcetype --disabled --use-ack"
                    )
                    raise SystemExit(0)
                if "hec-token create" in command:
                    marker.touch()
                    print(json.dumps({"token": "synthetic-token-value"}))
                    raise SystemExit(0)
                if "http-event-collectors" in command:
                    raise SystemExit(1)
                raise SystemExit(0)
                """,
            )
            env = self.cloud_hec_test_env(tmp_path, bin_dir)
            env["HEC_MUTATION_MARKER"] = str(mutation_marker)

            result = subprocess.run(
                ["bash", str(apply_script)],
                cwd=apply_script.parent,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertTrue(mutation_marker.exists(), msg="Verified absence did not reach create")
            self.assertIn("Created and read back HEC token", output)

    def test_hec_cloud_apply_legacy_group_requires_exact_describe_signal(self) -> None:
        """Deferred regression: legacy absence is an exact 404, never a short list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            apply_script = self.render_cloud_hec_apply(tmp_path)
            create_marker = tmp_path / "legacy-hec-create-reached"
            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                command = " ".join(args)
                marker = Path(os.environ["HEC_CREATE_MARKER"])
                if "config current-stack" in command:
                    print("Stack: example-stack")
                    raise SystemExit(0)
                if "hec-token list" in command and "--help" in args:
                    raise SystemExit(1)
                if "http-event-collectors describe" in command and "--help" in args:
                    raise SystemExit(0)
                if "http-event-collectors describe" in command:
                    if marker.exists():
                        print(
                            json.dumps(
                                {
                                    "http-event-collector": {
                                        "spec": {"name": "cloud_hec", "disabled": False}
                                    }
                                }
                            )
                        )
                        raise SystemExit(0)
                    if os.environ["HEC_ABSENCE_MODE"] == "ambiguous":
                        print(json.dumps({"error": {"status": 404}}))
                        raise SystemExit(1)
                    print(json.dumps([{"type": "http", "status": 404}]))
                    raise SystemExit(1)
                if "http-event-collectors list" in command:
                    raise SystemExit(9)
                if "http-event-collectors create" in command and "--help" in args:
                    print(
                        "--default-index --allowed-indexes --default-source "
                        "--default-sourcetype --disabled --use-ack"
                    )
                    raise SystemExit(0)
                if "http-event-collectors create" in command:
                    marker.touch()
                    print(json.dumps({"token": "synthetic-token-value"}))
                    raise SystemExit(0)
                raise SystemExit(1)
                """,
            )
            env = self.cloud_hec_test_env(tmp_path, bin_dir)
            env["HEC_CREATE_MARKER"] = str(create_marker)

            env["HEC_ABSENCE_MODE"] = "ambiguous"
            ambiguous = subprocess.run(
                ["bash", str(apply_script)],
                cwd=apply_script.parent,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            ambiguous_output = ambiguous.stdout + ambiguous.stderr
            self.assertNotEqual(ambiguous.returncode, 0, msg=ambiguous_output)
            self.assertFalse(
                create_marker.exists(),
                msg="An unrelated nested 404 authorized legacy create",
            )

            env["HEC_ABSENCE_MODE"] = "exact"
            result = subprocess.run(
                ["bash", str(apply_script)],
                cwd=apply_script.parent,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertTrue(create_marker.exists(), msg="Exact legacy 404 did not permit create")
            self.assertIn("Created and read back HEC token", output)

    def test_hec_cloud_apply_paginates_before_deciding_token_is_missing(self) -> None:
        """Deferred regression: a token after record 100 must not be duplicated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            apply_script = self.render_cloud_hec_apply(tmp_path)
            create_marker = tmp_path / "hec-create-reached"
            update_marker = tmp_path / "hec-update-reached"
            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                command = " ".join(args)
                if "config current-stack" in command:
                    print("Stack: example-stack")
                    raise SystemExit(0)
                if "hec-token list" in command:
                    if "--help" in args:
                        raise SystemExit(0)
                    if "--count" in args and args[args.index("--count") + 1] == "1":
                        print(json.dumps({"tokens": [{"name": "probe", "disabled": False}]}))
                        raise SystemExit(0)
                    offset = int(args[args.index("--offset") + 1])
                    if offset == 0:
                        tokens = [
                            {"name": f"decoy-{number}", "disabled": False}
                            for number in range(100)
                        ]
                    elif offset == 100:
                        tokens = [{"name": "cloud_hec", "disabled": False}]
                    else:
                        tokens = []
                    print(json.dumps({"tokens": tokens}))
                    raise SystemExit(0)
                if "--help" in command and "hec-token update" in command:
                    print(
                        "--default-index --allowed-indexes --default-source "
                        "--default-sourcetype --disabled --use-ack"
                    )
                    raise SystemExit(0)
                if "hec-token create" in command:
                    Path(os.environ["HEC_CREATE_MARKER"]).touch()
                    raise SystemExit(0)
                if "hec-token update" in command:
                    Path(os.environ["HEC_UPDATE_MARKER"]).touch()
                    raise SystemExit(0)
                if "http-event-collectors" in command:
                    raise SystemExit(1)
                raise SystemExit(0)
                """,
            )
            env = self.cloud_hec_test_env(tmp_path, bin_dir)
            env["HEC_CREATE_MARKER"] = str(create_marker)
            env["HEC_UPDATE_MARKER"] = str(update_marker)

            result = subprocess.run(
                ["bash", str(apply_script)],
                cwd=apply_script.parent,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertFalse(create_marker.exists(), msg="Page-two token was duplicated")
            self.assertTrue(update_marker.exists(), msg="Fixture did not reconcile the found token")
            self.assertIn("Updated and read back HEC token", output)

    def test_hec_cloud_status_requires_exact_identity_and_redacts_secret_keys(self) -> None:
        """Deferred regression: status proves identity and never emits secret-like fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            apply_script = self.render_cloud_hec_apply(tmp_path)
            status_script = apply_script.parent / "status-cloud-acs.sh"
            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys

                command = " ".join(sys.argv[1:])
                if "config current-stack" in command:
                    print("Stack: example-stack")
                    raise SystemExit(0)
                if "hec-token describe" in command:
                    mode = os.environ["HEC_STATUS_MATCH"]
                    name = "cloud_hec" if mode in {"true", "failed"} else "other"
                    payload = {
                        "http-event-collector": {
                            "spec": {"name": name, "disabled": False},
                            "tokenValue": "TOKEN-VALUE-CANARY",
                            "clientSecret": "SECRET-CANARY",
                            "passwordHint": "PASSWORD-CANARY",
                            "credentialBlob": "CREDENTIAL-CANARY",
                        }
                    }
                    if mode == "failed":
                        print(json.dumps([{"type": "http", "status": 500, "response": json.dumps(payload)}]))
                        raise SystemExit(0)
                    print(
                        json.dumps(payload)
                    )
                    raise SystemExit(0)
                if "http-event-collectors describe" in command:
                    raise SystemExit(1)
                raise SystemExit(0)
                """,
            )
            env = self.cloud_hec_test_env(tmp_path, bin_dir)

            env["HEC_STATUS_MATCH"] = "failed"
            failed = subprocess.run(
                ["bash", str(status_script)],
                cwd=status_script.parent,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            failed_output = failed.stdout + failed.stderr
            self.assertNotEqual(failed.returncode, 0, msg=failed_output)
            self.assertIn("unreadable HEC token description", failed_output)
            self.assertNotIn("TOKEN-VALUE-CANARY", failed_output)

            env["HEC_STATUS_MATCH"] = "false"
            mismatch = subprocess.run(
                ["bash", str(status_script)],
                cwd=status_script.parent,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            mismatch_output = mismatch.stdout + mismatch.stderr
            self.assertNotEqual(mismatch.returncode, 0, msg=mismatch_output)
            self.assertIn("did not identify the requested token", mismatch_output)

            env["HEC_STATUS_MATCH"] = "true"
            matched = subprocess.run(
                ["bash", str(status_script)],
                cwd=status_script.parent,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            matched_output = matched.stdout + matched.stderr
            self.assertEqual(matched.returncode, 0, msg=matched_output)
            self.assertIn("cloud_hec", matched_output)
            self.assertIn("<redacted>", matched_output)
            for canary in (
                "TOKEN-VALUE-CANARY",
                "SECRET-CANARY",
                "PASSWORD-CANARY",
                "CREDENTIAL-CANARY",
            ):
                self.assertNotIn(canary, matched_output)

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

    def test_hec_apply_rejects_forced_bundle_without_control_plane_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            credentials_file = temp_root / "credentials"
            credentials_file.write_text(
                "\n".join(
                    (
                        'SPLUNK_PLATFORM="enterprise"',
                        'SPLUNK_DELIVERY_PLANE="bundle"',
                        'SPLUNK_TARGET_ROLE="standalone"',
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            credentials_file.chmod(0o600)
            output_dir = temp_root / "rendered"
            env = {
                **os.environ,
                "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
            }
            for key in (
                "SPLUNK_PROFILE",
                "SPLUNK_SEARCH_PROFILE",
                "SPLUNK_INGEST_PROFILE",
                "SPLUNK_DEPLOYER_PROFILE",
                "SPLUNK_CLUSTER_MANAGER_PROFILE",
                "SPLUNK_PLATFORM",
                "SPLUNK_DELIVERY_PLANE",
                "SPLUNK_TARGET_ROLE",
            ):
                env.pop(key, None)

            result = subprocess.run(
                [
                    "bash",
                    str(HEC_SETUP),
                    "--platform",
                    "enterprise",
                    "--phase",
                    "apply",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing direct apply", result.stdout + result.stderr)
            self.assertFalse(output_dir.exists())

    def test_hec_default_standalone_apply_reaches_rendered_apply_script(self) -> None:
        """Deferred regression: the implicit standalone role remains a direct target."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            credentials_file = temp_root / "credentials"
            credentials_file.write_text(
                "\n".join(
                    (
                        'SPLUNK_PLATFORM="enterprise"',
                        'SPLUNK_DELIVERY_PLANE="direct"',
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            credentials_file.chmod(0o600)

            splunk_home = temp_root / "splunk"
            splunk_bin = splunk_home / "bin" / "splunk"
            splunk_bin.parent.mkdir(parents=True)
            write_executable(
                splunk_bin,
                """\
                #!/usr/bin/env bash
                if [[ "${1:-}" == "version" ]]; then
                    printf '%s\n' 'Splunk 10.4.0'
                    exit 0
                fi
                exit 1
                """,
            )

            output_dir = temp_root / "rendered"
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("SPLUNK_", "STACK_", "SB_", "ACS_"))
            }
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = subprocess.run(
                [
                    "bash",
                    str(HEC_SETUP),
                    "--platform",
                    "enterprise",
                    "--phase",
                    "apply",
                    "--output-dir",
                    str(output_dir),
                    "--splunk-home",
                    str(splunk_home),
                    "--restart-splunk",
                    "false",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            combined_output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=combined_output)
            self.assertNotIn("refusing direct apply", combined_output)
            self.assertTrue(
                (
                    splunk_home
                    / "etc/apps/splunk_httpinput/local/inputs.conf"
                ).is_file()
            )
            self.assertTrue(
                (output_dir / "hec-service/.cisco_skills_hec.token").is_file()
            )


if __name__ == "__main__":
    unittest.main()
