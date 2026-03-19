#!/usr/bin/env python3
"""Regression tests for first-party shell entrypoints."""

import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class ShellScriptRegressionTests(unittest.TestCase):
    def run_script(self, script_rel_path: str, *args: str, env: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(REPO_ROOT / script_rel_path), *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_stream_indexes_only_cloud_mode_uses_acs_without_session_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            acs_log = tmp_path / "acs.log"
            credentials_file = tmp_path / "credentials"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                log_path = Path(os.environ["ACS_LOG"])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(" ".join(sys.argv[1:]) + "\\n")

                args = sys.argv[1:]
                if "indexes" in args and "describe" in args:
                    raise SystemExit(1)
                raise SystemExit(0)
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/setup.sh",
                "--indexes-only",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            acs_output = acs_log.read_text(encoding="utf-8")
            self.assertIn("indexes create --name netflow", acs_output)
            self.assertIn("indexes create --name stream", acs_output)

    def test_validators_report_auth_failures_without_unbound_variable_crashes(self):
        validator_scripts = [
            "skills/cisco-enterprise-networking-setup/scripts/validate.sh",
            "skills/cisco-dc-networking-setup/scripts/validate.sh",
            "skills/cisco-catalyst-ta-setup/scripts/validate.sh",
            "skills/cisco-intersight-setup/scripts/validate.sh",
            "skills/cisco-meraki-ta-setup/scripts/validate.sh",
            "skills/cisco-thousandeyes-setup/scripts/validate.sh",
            "skills/splunk-itsi-setup/scripts/validate.sh",
            "skills/splunk-stream-setup/scripts/validate.sh",
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import sys

                args = " ".join(sys.argv[1:])
                if "%{http_code}" in args:
                    sys.stdout.write("401")
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "nc",
                """\
                #!/usr/bin/env bash
                exit 0
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            for script in validator_scripts:
                with self.subTest(script=script):
                    result = self.run_script(script, env=env)
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode, 1, msg=output)
                    self.assertIn("Validation Summary", output)
                    self.assertNotIn("unbound variable", output.lower())

    def test_cloud_batch_scripts_use_local_scope_when_search_head_is_pinned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            acs_log = tmp_path / "acs.log"
            credentials_file = tmp_path / "credentials"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                log_path = Path(os.environ["ACS_LOG"])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(" ".join(sys.argv[1:]) + "\\n")
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import sys

                args = " ".join(sys.argv[1:])
                if "%{http_code}" in args:
                    sys.stdout.write("401")
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "nc",
                """\
                #!/usr/bin/env bash
                exit 0
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_CLOUD_STACK="example-stack"
                    SPLUNK_CLOUD_SEARCH_HEAD="shc1"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            install_result = self.run_script(
                "skills/shared/scripts/cloud_batch_install.sh",
                "--no-restart",
                "1234",
                env=env,
            )
            self.assertEqual(install_result.returncode, 0, msg=install_result.stdout + install_result.stderr)

            uninstall_result = self.run_script(
                "skills/shared/scripts/cloud_batch_uninstall.sh",
                "--no-restart",
                "example_app",
                env=env,
            )
            self.assertEqual(uninstall_result.returncode, 0, msg=uninstall_result.stdout + uninstall_result.stderr)

            acs_output = acs_log.read_text(encoding="utf-8")
            self.assertIn("apps install splunkbase --splunkbase-id 1234 --scope local", acs_output)
            self.assertIn("apps uninstall example_app --scope local", acs_output)

    def test_thousandeyes_setup_enables_path_visualization_by_default(self):
        script_text = (REPO_ROOT / "skills/cisco-thousandeyes-setup/scripts/setup.sh").read_text(encoding="utf-8")

        self.assertIn("PATHVIS_ENABLED=true", script_text)
        self.assertIn('related_paths "1"', script_text)
        self.assertIn("--no-pathvis", script_text)

    def test_thousandeyes_configure_account_avoids_eval_for_network_data(self):
        script_text = (
            REPO_ROOT / "skills/cisco-thousandeyes-setup/scripts/configure_account.sh"
        ).read_text(encoding="utf-8")

        self.assertNotIn('eval "$(parse_device_authorization_response', script_text)
        self.assertNotIn('eval "$(parse_token_success_response', script_text)
        self.assertNotIn('eval "$(parse_token_error_response', script_text)

    def test_mcp_loaders_follow_shared_tls_policy(self):
        loader_paths = [
            "skills/cisco-catalyst-ta-setup/scripts/load_mcp_tools.sh",
            "skills/cisco-dc-networking-setup/scripts/load_mcp_tools.sh",
            "skills/cisco-enterprise-networking-setup/scripts/load_mcp_tools.sh",
            "skills/cisco-intersight-setup/scripts/load_mcp_tools.sh",
            "skills/cisco-meraki-ta-setup/scripts/load_mcp_tools.sh",
            "skills/cisco-thousandeyes-setup/scripts/load_mcp_tools.sh",
        ]

        for rel_path in loader_paths:
            with self.subTest(script=rel_path):
                script_text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
                self.assertIn("splunk_export_python_tls_env", script_text)
                self.assertNotIn("ssl.CERT_NONE", script_text)
                self.assertNotIn("check_hostname = False", script_text)

    def test_cloud_uninstall_script_no_longer_uses_top_level_local_keyword(self):
        script_text = (REPO_ROOT / "skills/splunk-app-install/scripts/uninstall_app.sh").read_text(encoding="utf-8")
        self.assertNotIn("local delete_code", script_text)


if __name__ == "__main__":
    unittest.main()
