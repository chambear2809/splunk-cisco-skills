#!/usr/bin/env python3
"""Regression tests for Splunk Enterprise host bootstrap shell scripts."""

import json
import os
import subprocess
import tarfile
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from tests.regression_helpers import (
    REPO_ROOT,
    ShellScriptRegressionBase,
    sha512_hex,
    write_executable,
    write_mock_curl,
    write_remote_shell_mocks,
)


class HostBootstrapRegressionTests(ShellScriptRegressionBase):
    def test_host_bootstrap_validate_local_mode_uses_localhost_for_rest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)
            curl_log = tmp_path / "curl.log"
            credentials_file = tmp_path / "credentials"
            password_file = tmp_path / "admin_password"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()

            credentials_file.write_text('SPLUNK_HOST="wrong.example.com"\n', encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                url = ""
                for arg in reversed(sys.argv[1:]):
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                        break
                with Path(os.environ["CURL_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")
                if url.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                elif "/services/server/info" in url:
                    sys.stdout.write('{"entry":[{"name":"server-info"}]}')
                """,
            )
            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    status) echo "splunkd is running"; exit 0 ;;
                    version) echo "Splunk 10.0.0"; exit 0 ;;
                    btool) exit 0 ;;
                    show) exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/validate.sh",
                "--execution",
                "local",
                "--host-bootstrap-role",
                "standalone-search-tier",
                "--splunk-home",
                str(splunk_home),
                "--service-user",
                current_user,
                "--admin-password-file",
                str(password_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://localhost:8089/services/auth/login", curl_requests)
            self.assertIn(
                "https://localhost:8089/services/server/info?output_mode=json",
                curl_requests,
            )
            self.assertNotIn("wrong.example.com", curl_requests)

    def test_host_bootstrap_validate_heavy_forwarder_accepts_server_list_without_mode_flag(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)
            curl_log = tmp_path / "curl.log"
            credentials_file = tmp_path / "credentials"
            password_file = tmp_path / "admin_password"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()

            credentials_file.write_text("", encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                url = ""
                for arg in reversed(sys.argv[1:]):
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                        break
                with Path(os.environ["CURL_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")
                if url.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                elif "/services/server/info" in url:
                    sys.stdout.write('{"entry":[{"name":"server-info"}]}')
                """,
            )
            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                if [[ "$1" == "status" ]]; then
                    echo "splunkd is running"
                    exit 0
                fi
                if [[ "$1" == "version" ]]; then
                    echo "Splunk 10.0.0"
                    exit 0
                fi
                if [[ "$1" == "btool" && "$2" == "outputs" ]]; then
                    cat <<'EOF'
[tcpout]
defaultGroup = default-autolb-group
indexAndForward = false
[tcpout:default-autolb-group]
server = idx01.example.com:9997,idx02.example.com:9997
EOF
                    exit 0
                fi
                exit 0
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/validate.sh",
                "--execution",
                "local",
                "--host-bootstrap-role",
                "heavy-forwarder",
                "--splunk-home",
                str(splunk_home),
                "--service-user",
                current_user,
                "--admin-password-file",
                str(password_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("outputs.conf uses a static server list", result.stdout)

    def test_host_bootstrap_setup_requires_current_shc_member_for_existing_cluster(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"
            credentials_file.write_text("", encoding="utf-8")
            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "cluster",
                "--execution",
                "local",
                "--deployment-mode",
                "clustered",
                "--host-bootstrap-role",
                "shc-member",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--current-shc-member-uri", result.stdout + result.stderr)

    def test_host_bootstrap_setup_cluster_adds_shc_member_without_inline_auth(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)
            credentials_file = tmp_path / "credentials"
            password_file = tmp_path / "admin_password"
            shc_secret_file = tmp_path / "shc_secret"
            cmd_log = tmp_path / "splunk_args.log"
            stdin_log = tmp_path / "splunk_stdin.log"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()

            credentials_file.write_text("", encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")
            shc_secret_file.write_text("shc-secret\n", encoding="utf-8")

            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                stdin_data = sys.stdin.read()
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(args) + "\\n")
                with Path(os.environ["SPLUNK_STDIN_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"args": args, "stdin": stdin_data}) + "\\n")
                if args and args[0] == "status":
                    sys.stdout.write("splunkd is running")
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_CMD_LOG": str(cmd_log),
                    "SPLUNK_STDIN_LOG": str(stdin_log),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "cluster",
                "--execution",
                "local",
                "--deployment-mode",
                "clustered",
                "--host-bootstrap-role",
                "shc-member",
                "--splunk-home",
                str(splunk_home),
                "--service-user",
                current_user,
                "--admin-password-file",
                str(password_file),
                "--shc-secret-file",
                str(shc_secret_file),
                "--deployer-uri",
                "https://deployer.example.com:8089",
                "--current-shc-member-uri",
                "https://sh1.example.com:8089",
                "--advertise-host",
                "sh2.example.com",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            command_lines = cmd_log.read_text(encoding="utf-8").splitlines()
            self.assertTrue(
                any("init" in line and "shcluster-config" in line for line in command_lines),
                msg=f"Expected init shcluster-config command, got: {command_lines}",
            )
            self.assertTrue(
                any("add" in line and "shcluster-member" in line for line in command_lines),
                msg=f"Expected add shcluster-member command, got: {command_lines}",
            )
            self.assertTrue(
                all("-auth" not in line for line in command_lines),
                msg=f"Did not expect inline -auth arguments, got: {command_lines}",
            )

            stdin_lines = stdin_log.read_text(encoding="utf-8")
            self.assertIn("admin\\nchangeme", stdin_lines)
            self.assertIn("current_member_uri", command_lines[-1] if command_lines else "")

    def test_host_bootstrap_setup_rejects_deb_auto_with_custom_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.0.0-linux-amd64.deb"
            password_file = tmp_path / "admin_password"

            credentials_file.write_text("", encoding="utf-8")
            package_file.write_text("deb-package-placeholder", encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")

            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "install",
                "--execution",
                "local",
                "--host-bootstrap-role",
                "standalone-search-tier",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--package-type",
                "auto",
                "--splunk-home",
                str(tmp_path / "custom-splunk"),
                "--admin-password-file",
                str(password_file),
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("DEB installs only support /opt/splunk", result.stdout + result.stderr)

    def test_host_bootstrap_setup_rejects_existing_non_splunk_custom_tgz_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.0.0-linux-x86_64.tgz"
            password_file = tmp_path / "admin_password"
            target_home = tmp_path / "existing-target"

            credentials_file.write_text("", encoding="utf-8")
            package_file.write_text("tgz-package-placeholder", encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")
            target_home.mkdir()

            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "install",
                "--execution",
                "local",
                "--host-bootstrap-role",
                "standalone-search-tier",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--package-type",
                "auto",
                "--splunk-home",
                str(target_home),
                "--admin-password-file",
                str(password_file),
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "already exists but is not a Splunk install",
                result.stdout + result.stderr,
            )

    def test_host_bootstrap_remote_staging_uses_user_tmp_before_privileged_tmpdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            local_file = tmp_path / "pkg.tgz"
            local_file.write_text("package", encoding="utf-8")
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            cmd_log = tmp_path / "cmd.log"
            sshpass_log = tmp_path / "sshpass.log"

            write_executable(
                bin_dir / "sshpass",
                """\
                #!/usr/bin/env bash
                printf '%s\n' "$*" >> "${SSHPASS_LOG}"
                exit 0
                """,
            )

            helper_script = textwrap.dedent(
                f"""\
                source "{REPO_ROOT / "skills/shared/lib/host_bootstrap_helpers.sh"}"
                load_splunk_ssh_credentials() {{ :; }}
                hbs_run_target_cmd() {{
                    printf '%s\\n' "$2" >> "{cmd_log}"
                    return 0
                }}
                export SPLUNK_SSH_USER="bootstrap"
                export SPLUNK_SSH_HOST="hf.example.com"
                export SPLUNK_SSH_PORT="22"
                export SPLUNK_SSH_PASS="secret"
                export SPLUNK_REMOTE_TMPDIR="/var/tmp/splunk"
                result="$(hbs_stage_file_for_execution ssh "{local_file}" "pkg.tgz")"
                printf '%s\\n' "$result"
                """
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "SSHPASS_LOG": str(sshpass_log),
                }
            )

            result = subprocess.run(
                ["bash", "-c", helper_script],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "/var/tmp/splunk/pkg.tgz")

            sshpass_text = sshpass_log.read_text(encoding="utf-8")
            self.assertIn("scp", sshpass_text)
            self.assertIn("/tmp/pkg.tgz.stage.", sshpass_text)
            self.assertNotIn("hf.example.com:/var/tmp/splunk/pkg.tgz", sshpass_text)

            cmd_text = cmd_log.read_text(encoding="utf-8")
            self.assertIn("mkdir -p /var/tmp/splunk", cmd_text)
            self.assertIn("install -m 600 /tmp/pkg.tgz.stage.", cmd_text)
            self.assertIn("/var/tmp/splunk/pkg.tgz", cmd_text)

    def test_host_bootstrap_remote_staging_reports_noninteractive_sudo_requirement(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            local_file = tmp_path / "pkg.tgz"
            local_file.write_text("package", encoding="utf-8")
            bin_dir = tmp_path / "bin"
            remote_root = tmp_path / "remote-root"
            bin_dir.mkdir()

            write_remote_shell_mocks(bin_dir)
            write_executable(
                bin_dir / "sshpass",
                """\
                #!/usr/bin/env bash
                shift 2
                if [[ "${1:-}" == "scp" ]]; then
                    exit 0
                fi
                if [[ "${1:-}" == "ssh" ]]; then
                    shift
                    exec "$(dirname "$0")/ssh" "$@"
                fi
                exec "$@"
                """,
            )

            helper_script = textwrap.dedent(
                f"""\
                source "{REPO_ROOT / "skills/shared/lib/host_bootstrap_helpers.sh"}"
                load_splunk_ssh_credentials() {{ :; }}
                export SPLUNK_SSH_USER="bootstrap"
                export SPLUNK_SSH_HOST="hf.example.com"
                export SPLUNK_SSH_PORT="22"
                export SPLUNK_SSH_PASS="secret"
                export REMOTE_ROOT="{remote_root}"
                hbs_stage_file_for_execution ssh "{local_file}" "pkg.tgz"
                """
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "REMOTE_ROOT": str(remote_root),
                    "REMOTE_SUDO_MODE": "require_stdin",
                }
            )

            result = subprocess.run(
                ["bash", "-lc", helper_script],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("either use the -S option", result.stdout + result.stderr)

    def test_host_bootstrap_install_preserves_local_package_and_cleans_user_seed_artifacts(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            password_file = tmp_path / "admin_password"
            package_file = tmp_path / "splunk-10.0.0-linux-x86_64.tgz"
            splunk_home = tmp_path / "installed-splunk"
            package_root = tmp_path / "package-root" / "splunk"
            (package_root / "bin").mkdir(parents=True)

            credentials_file.write_text("", encoding="utf-8")
            password_file.write_text("changeme\n", encoding="utf-8")

            write_executable(
                bin_dir / "sudo",
                """\
                #!/usr/bin/env bash
                exec "$@"
                """,
            )
            write_executable(
                bin_dir / "chown",
                """\
                #!/usr/bin/env bash
                exit 0
                """,
            )
            write_executable(
                package_root / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    start|restart) echo "started"; exit 0 ;;
                    status) echo "splunkd is running"; exit 0 ;;
                    version) echo "Splunk 10.0.0"; exit 0 ;;
                    enable) exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            with tarfile.open(package_file, "w:gz") as archive:
                archive.add(package_root, arcname="splunk")

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                }
            )

            install_args = (
                "--phase",
                "install",
                "--execution",
                "local",
                "--host-bootstrap-role",
                "standalone-search-tier",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--splunk-home",
                str(splunk_home),
                "--service-user",
                current_user,
                "--admin-password-file",
                str(password_file),
                "--no-boot-start",
            )

            first_result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                *install_args,
                env=env,
            )
            self.assertEqual(
                first_result.returncode,
                0,
                msg=first_result.stdout + first_result.stderr,
            )
            self.assertTrue(
                package_file.exists(),
                msg="Local package should not be deleted after install",
            )
            self.assertFalse((splunk_home / "etc/system/local/user-seed.conf").exists())
            self.assertEqual(
                list((splunk_home / "etc/system/local").glob("user-seed.conf.bak.*")),
                [],
            )

            stale_backup = splunk_home / "etc/system/local/user-seed.conf.bak.stale"
            stale_backup.parent.mkdir(parents=True, exist_ok=True)
            stale_backup.write_text("stale", encoding="utf-8")
            package_file.write_text("not-a-tarball\n", encoding="utf-8")

            second_result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                *install_args,
                env=env,
            )
            self.assertEqual(
                second_result.returncode,
                0,
                msg=second_result.stdout + second_result.stderr,
            )
            self.assertTrue(
                package_file.exists(),
                msg="Local package should remain after repeated install runs",
            )
            self.assertIn("already matches the requested package", second_result.stdout)
            self.assertFalse(
                stale_backup.exists(),
                msg="Repeated same-version install should clean stale user-seed backups",
            )

    def test_host_bootstrap_install_upgrades_tgz_without_admin_password_and_preserves_local_files(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.1.0-linux-x86_64.tgz"
            splunk_home = tmp_path / "installed-splunk"
            package_root = tmp_path / "package-root" / "splunk"
            cmd_log = tmp_path / "splunk.log"

            credentials_file.write_text("", encoding="utf-8")
            (splunk_home / "bin").mkdir(parents=True)
            (splunk_home / "etc/test").mkdir(parents=True)
            (package_root / "bin").mkdir(parents=True)
            (package_root / "etc/test").mkdir(parents=True)

            (splunk_home / "etc/test/default.txt").write_text("old-default\n", encoding="utf-8")
            (splunk_home / "etc/test/local-only.conf").write_text("keep-me\n", encoding="utf-8")
            (package_root / "etc/test/default.txt").write_text("new-default\n", encoding="utf-8")

            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"old:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.0.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )
            write_executable(
                package_root / "bin" / "splunk",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"new:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.1.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )

            with tarfile.open(package_file, "w:gz") as archive:
                archive.add(package_root, arcname="splunk")

            env = os.environ.copy()
            env.update(
                {
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                    "SPLUNK_CMD_LOG": str(cmd_log),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "install",
                "--execution",
                "local",
                "--host-bootstrap-role",
                "standalone-search-tier",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--splunk-home",
                str(splunk_home),
                "--service-user",
                current_user,
                "--no-boot-start",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Upgrading Splunk from 10.0.0 to 10.1.0", result.stdout)
            self.assertEqual(
                (splunk_home / "etc/test/default.txt").read_text(encoding="utf-8"),
                "new-default\n",
            )
            self.assertEqual(
                (splunk_home / "etc/test/local-only.conf").read_text(encoding="utf-8"),
                "keep-me\n",
            )

            commands = cmd_log.read_text(encoding="utf-8").splitlines()
            self.assertIn("old:version", commands)
            self.assertIn("old:stop", commands)
            self.assertIn("new:start", commands)
            self.assertLess(commands.index("old:stop"), commands.index("new:start"))

    def test_host_bootstrap_install_warns_that_clustered_upgrades_are_per_host_only(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.1.0-linux-x86_64.tgz"
            splunk_home = tmp_path / "cluster-manager"
            package_root = tmp_path / "package-root" / "splunk"

            credentials_file.write_text("", encoding="utf-8")
            (splunk_home / "bin").mkdir(parents=True)
            (package_root / "bin").mkdir(parents=True)

            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    version) echo "Splunk 10.0.0"; exit 0 ;;
                    status) echo "splunkd is running"; exit 0 ;;
                    stop|start|restart) echo "$1"; exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )
            write_executable(
                package_root / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    version) echo "Splunk 10.1.0"; exit 0 ;;
                    status) echo "splunkd is running"; exit 0 ;;
                    stop|start|restart) echo "$1"; exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            with tarfile.open(package_file, "w:gz") as archive:
                archive.add(package_root, arcname="splunk")

            env = os.environ.copy()
            env.update(
                {
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "install",
                "--execution",
                "local",
                "--host-bootstrap-role",
                "cluster-manager",
                "--deployment-mode",
                "clustered",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--splunk-home",
                str(splunk_home),
                "--service-user",
                current_user,
                "--no-boot-start",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Clustered upgrades are per-host only", result.stdout)

    def test_host_bootstrap_install_upgrades_remote_rpm_without_admin_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            remote_root = tmp_path / "remote-root"
            remote_home = remote_root / "opt/splunk"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.1.0-linux-x86_64.rpm"
            cmd_log = tmp_path / "splunk.log"
            install_log = tmp_path / "rpm.log"
            new_splunk = tmp_path / "new-rpm-splunk"

            bin_dir.mkdir()
            (remote_home / "bin").mkdir(parents=True)
            credentials_file.write_text("", encoding="utf-8")
            package_file.write_text("rpm-package-placeholder", encoding="utf-8")

            write_remote_shell_mocks(bin_dir)
            write_executable(
                remote_home / "bin" / "splunk",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"old:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.0.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )
            write_executable(
                new_splunk,
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"new:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.1.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "rpm",
                f"""\
                #!/usr/bin/env bash
                printf '%s\\n' "$*" >> "{install_log}"
                install -m 755 "{new_splunk}" "${{REMOTE_ROOT}}/opt/splunk/bin/splunk"
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "REMOTE_ROOT": str(remote_root),
                    "SPLUNK_CMD_LOG": str(cmd_log),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_SSH_HOST": "idx01.example.com",
                    "SPLUNK_SSH_PORT": "22",
                    "SPLUNK_SSH_USER": current_user,
                    "SPLUNK_SSH_PASS": "ssh-password",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "install",
                "--execution",
                "ssh",
                "--host-bootstrap-role",
                "standalone-search-tier",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--package-type",
                "rpm",
                "--advertise-host",
                "idx01.example.com",
                "--service-user",
                current_user,
                "--no-boot-start",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Upgrading Splunk from 10.0.0 to 10.1.0", result.stdout)
            self.assertIn("-Uvh", install_log.read_text(encoding="utf-8"))

            commands = cmd_log.read_text(encoding="utf-8").splitlines()
            self.assertIn("old:stop", commands)
            self.assertIn("new:start", commands)

    def test_host_bootstrap_install_upgrades_remote_deb_without_admin_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            remote_root = tmp_path / "remote-root"
            remote_home = remote_root / "opt/splunk"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.1.0-linux-amd64.deb"
            cmd_log = tmp_path / "splunk.log"
            install_log = tmp_path / "dpkg.log"
            new_splunk = tmp_path / "new-deb-splunk"

            bin_dir.mkdir()
            (remote_home / "bin").mkdir(parents=True)
            credentials_file.write_text("", encoding="utf-8")
            package_file.write_text("deb-package-placeholder", encoding="utf-8")

            write_remote_shell_mocks(bin_dir)
            write_executable(
                remote_home / "bin" / "splunk",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"old:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.0.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )
            write_executable(
                new_splunk,
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                command = sys.argv[1] if len(sys.argv) > 1 else ""
                with Path(os.environ["SPLUNK_CMD_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(f"new:{command}\\n")
                if command == "version":
                    sys.stdout.write("Splunk 10.1.0")
                elif command == "status":
                    sys.stdout.write("splunkd is running")
                elif command in {"stop", "start", "restart"}:
                    sys.stdout.write(command)
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "dpkg",
                f"""\
                #!/usr/bin/env bash
                printf '%s\\n' "$*" >> "{install_log}"
                install -m 755 "{new_splunk}" "${{REMOTE_ROOT}}/opt/splunk/bin/splunk"
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "REMOTE_ROOT": str(remote_root),
                    "SPLUNK_CMD_LOG": str(cmd_log),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_SSH_HOST": "sh01.example.com",
                    "SPLUNK_SSH_PORT": "22",
                    "SPLUNK_SSH_USER": current_user,
                    "SPLUNK_SSH_PASS": "ssh-password",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "install",
                "--execution",
                "ssh",
                "--host-bootstrap-role",
                "standalone-search-tier",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--package-type",
                "deb",
                "--advertise-host",
                "sh01.example.com",
                "--service-user",
                current_user,
                "--no-boot-start",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Upgrading Splunk from 10.0.0 to 10.1.0", result.stdout)
            self.assertIn("-i", install_log.read_text(encoding="utf-8"))

            commands = cmd_log.read_text(encoding="utf-8").splitlines()
            self.assertIn("old:stop", commands)
            self.assertIn("new:start", commands)

    def test_host_bootstrap_install_remote_deb_reports_noninteractive_sudo_requirement(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            remote_root = tmp_path / "remote-root"
            remote_home = remote_root / "opt/splunk"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-10.1.0-linux-amd64.deb"

            bin_dir.mkdir()
            (remote_home / "bin").mkdir(parents=True)
            credentials_file.write_text("", encoding="utf-8")
            package_file.write_text("deb-package-placeholder", encoding="utf-8")

            write_remote_shell_mocks(bin_dir)
            write_executable(
                remote_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    version) echo "Splunk 10.0.0"; exit 0 ;;
                    status) echo "splunkd is running"; exit 0 ;;
                    stop|start|restart) echo "$1"; exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "REMOTE_ROOT": str(remote_root),
                    "REMOTE_SUDO_MODE": "require_stdin",
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_SSH_HOST": "sh01.example.com",
                    "SPLUNK_SSH_PORT": "22",
                    "SPLUNK_SSH_USER": current_user,
                    "SPLUNK_SSH_PASS": "ssh-password",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "install",
                "--execution",
                "ssh",
                "--host-bootstrap-role",
                "standalone-search-tier",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--package-type",
                "deb",
                "--advertise-host",
                "sh01.example.com",
                "--service-user",
                current_user,
                "--no-boot-start",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("assumes", result.stdout)
            self.assertIn("either use the -S option", result.stdout + result.stderr)

    def test_host_bootstrap_configure_heavy_forwarder_does_not_require_admin_password(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)
            credentials_file = tmp_path / "credentials"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()

            credentials_file.write_text("", encoding="utf-8")

            write_executable(
                bin_dir / "sudo",
                """\
                #!/usr/bin/env bash
                exec "$@"
                """,
            )
            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    status) echo "splunkd is running"; exit 0 ;;
                    restart|start) exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "configure",
                "--execution",
                "local",
                "--host-bootstrap-role",
                "heavy-forwarder",
                "--splunk-home",
                str(splunk_home),
                "--service-user",
                current_user,
                "--server-list",
                "idx01.example.com:9997",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            outputs_conf = (splunk_home / "etc/system/local/outputs.conf").read_text(encoding="utf-8")
            self.assertIn("server = idx01.example.com:9997", outputs_conf)

    def test_host_bootstrap_cluster_manager_does_not_require_admin_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)
            credentials_file = tmp_path / "credentials"
            idxc_secret_file = tmp_path / "idxc_secret"
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()

            credentials_file.write_text("", encoding="utf-8")
            idxc_secret_file.write_text("idxc-secret\n", encoding="utf-8")

            write_executable(
                bin_dir / "sudo",
                """\
                #!/usr/bin/env bash
                exec "$@"
                """,
            )
            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                case "$1" in
                    status) echo "splunkd is running"; exit 0 ;;
                    restart|start) exit 0 ;;
                    *) exit 0 ;;
                esac
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_LOCAL_SUDO": "false",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "cluster",
                "--execution",
                "local",
                "--deployment-mode",
                "clustered",
                "--host-bootstrap-role",
                "cluster-manager",
                "--splunk-home",
                str(splunk_home),
                "--service-user",
                current_user,
                "--idxc-secret-file",
                str(idxc_secret_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            server_conf = (splunk_home / "etc/system/local/server.conf").read_text(encoding="utf-8")
            self.assertIn("mode = manager", server_conf)

    def test_host_bootstrap_download_without_url_resolves_latest_official_tgz_and_verifies_sha512(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.tgz"
            old_package_name = "splunk-10.1.0-abcdef123456-linux-amd64.tgz"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            old_package_url = f"https://download.splunk.com/products/splunk/releases/10.1.0/linux/{old_package_name}"
            sha_url = f"{package_url}.sha512"
            old_sha_url = f"{old_package_url}.sha512"
            package_content = "tgz-package"
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-tgz.json"
            package_path = REPO_ROOT / "splunk-ta" / package_name

            self.addCleanup(lambda: package_path.unlink(missing_ok=True))
            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "text": {
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html": textwrap.dedent(
                                f"""\
                                Splunk Enterprise 10.2.1
                                wget -O {old_package_name} "{old_package_url}"
                                {old_package_url}
                                {old_sha_url}
                                wget -O {package_name} "{package_url}"
                                {package_url}
                                {sha_url}
                                """
                            ),
                            sha_url: f"{sha512_hex(package_content)}  {package_name}\n",
                            old_sha_url: f"{sha512_hex('older-package')}  {old_package_name}\n",
                        },
                        "files": {
                            package_url: package_content,
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "download",
                "--execution",
                "local",
                "--source",
                "auto",
                "--package-type",
                "tgz",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Resolved latest Splunk Enterprise 10.2.1 package", result.stdout)
            self.assertIn("Verifying", result.stdout)
            self.assertTrue(package_path.exists())
            self.assertTrue(metadata_path.exists())

            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["version"], "10.2.1")
            self.assertEqual(metadata["package_url"], package_url)
            self.assertEqual(metadata["sha512"], sha512_hex(package_content))

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                curl_requests,
            )
            self.assertIn(package_url, curl_requests)
            self.assertIn(sha_url, curl_requests)
            self.assertNotIn(old_package_url, curl_requests)

    def test_host_bootstrap_download_without_url_resolves_latest_official_deb_when_requested(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.deb"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            sha_url = f"{package_url}.sha512"
            package_content = "deb-package"
            package_path = REPO_ROOT / "splunk-ta" / package_name
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-deb.json"

            self.addCleanup(lambda: package_path.unlink(missing_ok=True))
            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "text": {
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html": textwrap.dedent(
                                f"""\
                                Splunk Enterprise 10.2.1
                                wget -O {package_name} "{package_url}"
                                {package_url}
                                {sha_url}
                                """
                            ),
                            sha_url: f"{sha512_hex(package_content)}  {package_name}\n",
                        },
                        "files": {
                            package_url: package_content,
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "download",
                "--execution",
                "local",
                "--source",
                "remote",
                "--package-type",
                "deb",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Resolved latest Splunk Enterprise 10.2.1 package", result.stdout)
            self.assertTrue(package_path.exists())
            self.assertTrue(metadata_path.exists())

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                curl_requests,
            )
            self.assertIn(package_url, curl_requests)
            self.assertIn(sha_url, curl_requests)

    def test_host_bootstrap_download_without_url_auto_selects_deb_from_remote_target_os(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.deb"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            sha_url = f"{package_url}.sha512"
            package_path = REPO_ROOT / "splunk-ta" / package_name
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-deb.json"

            self.addCleanup(lambda: package_path.unlink(missing_ok=True))
            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            write_executable(
                bin_dir / "sshpass",
                """\
                #!/usr/bin/env bash
                shift 2
                exec "$@"
                """,
            )
            write_executable(
                bin_dir / "ssh",
                """\
                #!/usr/bin/env bash
                printf 'ID=ubuntu\nID_LIKE=debian\n'
                """,
            )
            mock_state_file.write_text(
                json.dumps(
                    {
                        "text": {
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html": textwrap.dedent(
                                f"""\
                                Splunk Enterprise 10.2.1
                                wget -O {package_name} "{package_url}"
                                {package_url}
                                {sha_url}
                                """
                            ),
                            sha_url: f"{sha512_hex('deb-package-remote')}  {package_name}\n",
                        },
                        "files": {
                            package_url: "deb-package-remote",
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "SPLUNK_SSH_HOST": "cm01.example.com",
                    "SPLUNK_SSH_USER": "splunk",
                    "SPLUNK_SSH_PASS": "ssh-password",
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "download",
                "--execution",
                "ssh",
                "--source",
                "remote",
                "--package-type",
                "auto",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Auto-selected deb", result.stdout)
            self.assertIn("Resolved latest Splunk Enterprise 10.2.1 package", result.stdout)
            self.assertTrue(package_path.exists())

    def test_host_bootstrap_download_without_url_fails_when_page_version_disagrees_with_package_version(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.1.0-abcdef123456-linux-amd64.tgz"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.1.0/linux/{package_name}"
            sha_url = f"{package_url}.sha512"

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "text": {
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html": textwrap.dedent(
                                f"""\
                                Splunk Enterprise 10.2.1
                                wget -O {package_name} "{package_url}"
                                {package_url}
                                {sha_url}
                                """
                            ),
                            sha_url: f"{sha512_hex('bad-package')}  {package_name}\n",
                        },
                        "files": {
                            package_url: "bad-package",
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "download",
                "--execution",
                "local",
                "--source",
                "remote",
                "--package-type",
                "tgz",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "Failed to resolve the latest official Splunk Enterprise tgz package",
                result.stdout + result.stderr,
            )

    def test_host_bootstrap_download_without_url_can_use_stale_latest_metadata_when_allowed(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.tgz"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            sha_url = f"{package_url}.sha512"
            package_content = "stale-tgz-package"
            package_path = REPO_ROOT / "splunk-ta" / package_name
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-tgz.json"

            self.addCleanup(lambda: package_path.unlink(missing_ok=True))
            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            metadata_path.write_text(
                json.dumps(
                    {
                        "cached_at": "2026-03-22T00:00:00Z",
                        "cached_at_epoch": int(time.time()),
                        "package_type": "tgz",
                        "package_url": package_url,
                        "sha512": sha512_hex(package_content),
                        "sha512_url": sha_url,
                        "source_page_url": "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                        "version": "10.2.1",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "fail": [
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                        ],
                        "files": {
                            package_url: package_content,
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "download",
                "--execution",
                "local",
                "--source",
                "remote",
                "--package-type",
                "tgz",
                "--allow-stale-latest",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("attempting stale metadata fallback", result.stdout)
            self.assertTrue(package_path.exists())
            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                curl_requests,
            )
            self.assertIn(package_url, curl_requests)
            self.assertNotIn(sha_url, curl_requests)

    def test_host_bootstrap_download_without_url_fails_without_allow_stale_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            mock_state_file = tmp_path / "mock-curl-state.json"

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "fail": [
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "download",
                "--execution",
                "local",
                "--source",
                "remote",
                "--package-type",
                "tgz",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--allow-stale-latest", result.stdout + result.stderr)

    def test_host_bootstrap_download_without_url_rejects_stale_metadata_older_than_30_days(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.tgz"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-tgz.json"

            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            metadata_path.write_text(
                json.dumps(
                    {
                        "cached_at": "2026-01-01T00:00:00Z",
                        "cached_at_epoch": int(time.time()) - (31 * 24 * 60 * 60),
                        "package_type": "tgz",
                        "package_url": package_url,
                        "sha512": sha512_hex("stale-package"),
                        "sha512_url": f"{package_url}.sha512",
                        "source_page_url": "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                        "version": "10.2.1",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "fail": [
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase",
                "download",
                "--execution",
                "local",
                "--source",
                "remote",
                "--package-type",
                "tgz",
                "--allow-stale-latest",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("older than 30 days", result.stdout + result.stderr)

    def test_host_bootstrap_smoke_latest_resolution_checks_live_metadata_without_downloading_package(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            mock_state_file = tmp_path / "mock-curl-state.json"
            package_name = "splunk-10.2.1-c892b66d163d-linux-amd64.tgz"
            package_url = f"https://download.splunk.com/products/splunk/releases/10.2.1/linux/{package_name}"
            sha_url = f"{package_url}.sha512"
            package_path = REPO_ROOT / "splunk-ta" / package_name
            metadata_path = REPO_ROOT / "splunk-ta" / ".latest-splunk-enterprise-tgz.json"

            package_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            self.addCleanup(lambda: package_path.unlink(missing_ok=True))
            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))

            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            mock_state_file.write_text(
                json.dumps(
                    {
                        "text": {
                            "https://www.splunk.com/en_us/download/splunk-enterprise.html": textwrap.dedent(
                                f"""\
                                <h1>Splunk Enterprise 10.2.1</h1>
                                <a data-link="{package_url}" data-wget='wget -O {package_name} &#34;{package_url}&#34;' data-sha512="{sha_url}" data-version="10.2.1" href="#">
                                  Download Now
                                </a>
                                """
                            ),
                            sha_url: f"{sha512_hex('smoke-only')}  {package_name}\n",
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "CURL_LOG": str(curl_log),
                    "MOCK_CURL_STATE": str(mock_state_file),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                }
            )

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/smoke_latest_resolution.sh",
                "--package-type",
                "tgz",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Smoke check passed for tgz (live)", result.stdout)
            self.assertIn(package_url, result.stdout)
            self.assertIn(sha_url, result.stdout)
            self.assertFalse(package_path.exists())
            self.assertFalse(metadata_path.exists())

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://www.splunk.com/en_us/download/splunk-enterprise.html",
                curl_requests,
            )
            self.assertIn(sha_url, curl_requests)
            self.assertNotIn(package_url + "\n", curl_requests)


if __name__ == "__main__":
    unittest.main()
