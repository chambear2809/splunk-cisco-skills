#!/usr/bin/env python3
"""Regression tests for app install, uninstall, cloud batch, and validator shell scripts."""

import base64
import getpass
import json
import os
import re
import tarfile
import tempfile
import textwrap
from pathlib import Path

from tests.regression_helpers import REPO_ROOT, ShellScriptRegressionBase, write_executable


class InstallRegressionTests(ShellScriptRegressionBase):
    def test_splunk_ai_assistant_cloud_install_uses_acs_without_preinstall_rest_auth(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            acs_log = tmp_path / "acs.log"
            curl_log = tmp_path / "curl.log"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                if args[:2] == ["--format", "structured"]:
                    args = args[2:]
                if args[:2] == ["--server", "https://staging.admin.splunk.com"]:
                    args = args[2:]

                cmd = " ".join(args)
                log_path = Path(os.environ["ACS_LOG"])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(cmd + "\\n")

                if cmd == "config current-stack":
                    print("Current Search Head: sh-i-123")
                    raise SystemExit(0)

                if cmd == "apps list --splunkbase --count 100":
                    print(json.dumps({"apps": []}))
                    raise SystemExit(0)

                if cmd.startswith("apps install splunkbase --splunkbase-id 7245"):
                    print(json.dumps({"name": "Splunk AI Assistant for SPL", "version": "1.5.1", "status": "installed"}))
                    raise SystemExit(0)

                if cmd == "status current-stack":
                    print(json.dumps({"infrastructure": {"status": "Ready"}, "messages": {"restartRequired": False}}))
                    raise SystemExit(0)

                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                url = ""
                for arg in args:
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg

                log_path = Path(os.environ["CURL_LOG"])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

                if url.endswith("/services/auth/login"):
                    raise SystemExit(99)

                if url == "https://checkip.amazonaws.com" or url == "https://api.ipify.org":
                    raise SystemExit(0)

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
                    SPLUNK_PLATFORM="cloud"
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    STACK_USERNAME="stack-user"
                    STACK_PASSWORD="stack-pass"
                    SPLUNK_SEARCH_API_URI="https://example-stack.stg.splunkcloud.com:8089"
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["SPLUNK_SKIP_ALLOWLIST"] = "true"

            result = self.run_script(
                "skills/splunk-ai-assistant-setup/scripts/setup.sh",
                "--install",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn(
                "apps install splunkbase --splunkbase-id 7245",
                acs_log.read_text(encoding="utf-8"),
            )
            curl_output = curl_log.read_text(encoding="utf-8") if curl_log.exists() else ""
            self.assertNotIn(
                "/services/auth/login",
                curl_output,
            )


    def test_splunk_ai_assistant_enterprise_install_uses_rest_precheck_and_passes_update(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            install_log = tmp_path / "install.log"
            fake_install = tmp_path / "fake_install_app.sh"

            write_executable(
                fake_install,
                """\
                #!/usr/bin/env bash
                printf '%s\n' "$*" >> "${INSTALL_LOG}"
                exit 0
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                args = sys.argv[1:]
                url = ""
                output_target = None
                write_format = ""
                for i, arg in enumerate(args):
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                    elif arg == "-w" and i + 1 < len(args):
                        write_format = args[i + 1]
                    elif arg.startswith("http://") or arg.startswith("https://"):
                        url = arg

                with Path(os.environ["CURL_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

                def emit(body: str = "", code: int | None = None) -> None:
                    if output_target == "/dev/null" and code is not None and "%{http_code}" in write_format:
                        sys.stdout.write(str(code))
                        raise SystemExit(0)
                    if body:
                        sys.stdout.write(body)
                    if code is not None and "%{http_code}" in write_format:
                        sys.stdout.write("\\n" + str(code))
                    raise SystemExit(0)

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    emit("<response><sessionKey>test-session</sessionKey></response>")
                if path.endswith("/services/apps/local/Splunk_AI_Assistant_Cloud"):
                    emit(json.dumps({"entry": [{"name": "Splunk_AI_Assistant_Cloud", "content": {"version": "1.5.1"}}]}), 200)

                emit("", 200)
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
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["CURL_LOG"] = str(curl_log)
            env["INSTALL_LOG"] = str(install_log)
            env["APP_INSTALL_SCRIPT"] = str(fake_install)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-ai-assistant-setup/scripts/setup.sh",
                "--install",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            install_output = install_log.read_text(encoding="utf-8")
            self.assertIn("--source splunkbase --app-id 7245 --update", install_output)
            curl_output = curl_log.read_text(encoding="utf-8")
            self.assertIn("/services/auth/login", curl_output)
            self.assertIn("/services/apps/local/Splunk_AI_Assistant_Cloud", curl_output)


    def test_splunk_ai_assistant_submit_onboarding_posts_expected_json_and_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            request_log = tmp_path / "requests.jsonl"

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                args = sys.argv[1:]
                url = ""
                headers = []
                data = ""
                output_target = None
                write_format = ""
                method = "GET"

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-X" and i + 1 < len(args):
                        method = args[i + 1]
                        i += 2
                        continue
                    if arg == "-H" and i + 1 < len(args):
                        headers.append(args[i + 1])
                        i += 2
                        continue
                    if arg == "-d" and i + 1 < len(args):
                        data = args[i + 1]
                        i += 2
                        continue
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if arg == "-w" and i + 1 < len(args):
                        write_format = args[i + 1]
                        i += 2
                        continue
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with Path(os.environ["REQUEST_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"url": url, "headers": headers, "data": data, "method": method}) + "\\n")

                def emit(body: str = "", code: int | None = None) -> None:
                    if output_target == "/dev/null" and code is not None and "%{http_code}" in write_format:
                        sys.stdout.write(str(code))
                        raise SystemExit(0)
                    if body:
                        sys.stdout.write(body)
                    if code is not None and "%{http_code}" in write_format:
                        sys.stdout.write("\\n" + str(code))
                    raise SystemExit(0)

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    emit("<response><sessionKey>test-session</sessionKey></response>")
                if path.endswith("/services/server/info"):
                    emit(json.dumps({"entry": [{"content": {"version": "10.2.2"}}]}), 200)
                if path.endswith("/services/kvstore/status"):
                    emit(json.dumps({"entry": [{"content": {"current": {"status": "ready"}}}]}), 200)
                if path.endswith("/services/apps/local/Splunk_AI_Assistant_Cloud"):
                    emit(json.dumps({"entry": [{"name": "Splunk_AI_Assistant_Cloud", "content": {"version": "1.5.1", "visible": True, "configured": False}}]}), 200)
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/version"):
                    emit(json.dumps({"version": "1.0.0"}), 200)
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/submitonboardingform"):
                    emit(json.dumps({"value": "encoded-onboarding-data"}), 200)
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/storage/collections/data/cloud_connected_configurations"):
                    emit(json.dumps([{"scs_region": "usa", "encoded_onboarding_data": "{onboarding_blob}"}]), 200)
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/cloudconnectedproxysettings"):
                    emit(json.dumps({"proxy_settings": {}}), 200)
                emit("", 200)
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
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_PLATFORM="enterprise"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["REQUEST_LOG"] = str(request_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-ai-assistant-setup/scripts/setup.sh",
                "--submit-onboarding-form",
                "--email",
                "ops@example.com",
                "--region",
                "us",
                "--company-name",
                "Example Co",
                "--tenant-name",
                "example-prod",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            requests = [json.loads(line) for line in request_log.read_text(encoding="utf-8").splitlines()]
            submit_request = next(
                item for item in requests if item["url"].endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/submitonboardingform?output_mode=json")
            )
            self.assertEqual(submit_request["method"], "POST")
            self.assertIn("Source-App-ID: Splunk_AI_Assistant_Cloud", submit_request["headers"])
            self.assertEqual(
                json.loads(submit_request["data"]),
                {
                    "email": "ops@example.com",
                    "region": "usa",
                    "company_name": "Example Co",
                    "tenant_name": "example-prod",
                },
            )
            self.assertIn("Normalizing onboarding region 'us' to 'usa'.", result.stdout)
            self.assertIn("Validation will now confirm the pending setup state.", result.stdout)
            self.assertIn("Onboarding form has been submitted but activation is still pending", result.stdout)
            self.assertIn("Remaining blocker: apply the Splunk-issued activation code/token", result.stdout)


    def test_splunk_ai_assistant_set_proxy_posts_expected_json_and_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            request_log = tmp_path / "requests.jsonl"
            proxy_password_file = tmp_path / "proxy_password"
            proxy_password_file.write_text("proxy-pass\n", encoding="utf-8")

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                args = sys.argv[1:]
                url = ""
                headers = []
                data = ""
                output_target = None
                write_format = ""
                method = "GET"

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-X" and i + 1 < len(args):
                        method = args[i + 1]
                        i += 2
                        continue
                    if arg == "-H" and i + 1 < len(args):
                        headers.append(args[i + 1])
                        i += 2
                        continue
                    if arg == "-d" and i + 1 < len(args):
                        data = args[i + 1]
                        i += 2
                        continue
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if arg == "-w" and i + 1 < len(args):
                        write_format = args[i + 1]
                        i += 2
                        continue
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with Path(os.environ["REQUEST_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"url": url, "headers": headers, "data": data, "method": method}) + "\\n")

                def emit(body: str = "", code: int | None = None) -> None:
                    if output_target == "/dev/null" and code is not None and "%{http_code}" in write_format:
                        sys.stdout.write(str(code))
                        raise SystemExit(0)
                    if body:
                        sys.stdout.write(body)
                    if code is not None and "%{http_code}" in write_format:
                        sys.stdout.write("\\n" + str(code))
                    raise SystemExit(0)

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    emit("<response><sessionKey>test-session</sessionKey></response>")
                if path.endswith("/services/apps/local/Splunk_AI_Assistant_Cloud"):
                    emit(json.dumps({"entry": [{"name": "Splunk_AI_Assistant_Cloud", "content": {"version": "1.5.1", "visible": True, "configured": False}}]}), 200)
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/cloudconnectedproxysettings"):
                    emit(json.dumps({"status": "success"}), 200)
                emit("", 200)
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
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_PLATFORM="enterprise"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["REQUEST_LOG"] = str(request_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-ai-assistant-setup/scripts/setup.sh",
                "--set-proxy",
                "--proxy-url",
                "https://proxy.example.com:8443",
                "--proxy-username",
                "proxy-user",
                "--proxy-password-file",
                str(proxy_password_file),
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            requests = [json.loads(line) for line in request_log.read_text(encoding="utf-8").splitlines()]
            proxy_request = next(
                item for item in requests if item["url"].endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/cloudconnectedproxysettings?output_mode=json")
            )
            self.assertEqual(proxy_request["method"], "POST")
            self.assertIn("Source-App-ID: Splunk_AI_Assistant_Cloud", proxy_request["headers"])
            self.assertEqual(
                json.loads(proxy_request["data"]),
                {
                    "proxy_settings": {
                        "type": "https",
                        "hostname": "proxy.example.com",
                        "port": "8443",
                        "username": "proxy-user",
                        "password": "proxy-pass",
                    }
                },
            )
            self.assertIn("Configured cloud-connected proxy: https://proxy.example.com:8443 with auth.", result.stdout)


    def test_splunk_ai_assistant_complete_onboarding_reads_activation_code_file_and_auto_validates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            request_log = tmp_path / "requests.jsonl"
            state_file = tmp_path / "state.json"
            activation_file = tmp_path / "activation_code"
            state_file.write_text(json.dumps({"activated": False}), encoding="utf-8")
            activation_file.write_text("encoded-activation-code\n", encoding="utf-8")

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                state_path = Path(os.environ["STATE_FILE"])
                state = json.loads(state_path.read_text(encoding="utf-8"))
                args = sys.argv[1:]
                url = ""
                headers = []
                data = ""
                output_target = None
                write_format = ""
                method = "GET"

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-X" and i + 1 < len(args):
                        method = args[i + 1]
                        i += 2
                        continue
                    if arg == "-H" and i + 1 < len(args):
                        headers.append(args[i + 1])
                        i += 2
                        continue
                    if arg == "-d" and i + 1 < len(args):
                        data = args[i + 1]
                        i += 2
                        continue
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if arg == "-w" and i + 1 < len(args):
                        write_format = args[i + 1]
                        i += 2
                        continue
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with Path(os.environ["REQUEST_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"url": url, "headers": headers, "data": data, "method": method}) + "\\n")

                def emit(body: str = "", code: int | None = None) -> None:
                    if output_target == "/dev/null" and code is not None and "%{http_code}" in write_format:
                        sys.stdout.write(str(code))
                        raise SystemExit(0)
                    if body:
                        sys.stdout.write(body)
                    if code is not None and "%{http_code}" in write_format:
                        sys.stdout.write("\\n" + str(code))
                    raise SystemExit(0)

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    emit("<response><sessionKey>test-session</sessionKey></response>")
                if path.endswith("/services/server/info"):
                    emit(json.dumps({"entry": [{"content": {"version": "10.2.2"}}]}), 200)
                if path.endswith("/services/kvstore/status"):
                    emit(json.dumps({"entry": [{"content": {"current": {"status": "ready"}}}]}), 200)
                if path.endswith("/services/apps/local/Splunk_AI_Assistant_Cloud"):
                    emit(
                        json.dumps(
                            {
                                "entry": [
                                    {
                                        "name": "Splunk_AI_Assistant_Cloud",
                                        "content": {
                                            "version": "1.5.1",
                                            "visible": True,
                                            "configured": state["activated"],
                                        },
                                    }
                                ]
                            }
                        ),
                        200,
                    )
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/version"):
                    emit(json.dumps({"version": "1.0.0"}), 200)
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/completeonboarding"):
                    state["activated"] = True
                    state_path.write_text(json.dumps(state), encoding="utf-8")
                    emit(
                        json.dumps(
                            {
                                "tenant_name": "example-prod",
                                "tenant_hostname": "example-prod.api.us.scs.splunk.com",
                            }
                        ),
                        200,
                    )
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/cloudconnectedproxysettings"):
                    emit(json.dumps({"proxy_settings": {}}), 200)
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/storage/collections/data/cloud_connected_configurations"):
                    if state["activated"]:
                        emit(
                            json.dumps(
                                [
                                    {
                                        "tenant_name": "example-prod",
                                        "tenant_hostname": "example-prod.api.us.scs.splunk.com",
                                        "scs_region": "us",
                                        "service_principal": "spn-123",
                                        "scs_token": "token-123",
                                        "scs_token_expiry": "1712345678",
                                        "last_setup_timestamp": "1712340000",
                                        "encoded_onboarding_data": "",
                                    }
                                ]
                            ),
                            200,
                        )
                    emit(json.dumps([{}]), 200)
                emit("", 200)
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
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_PLATFORM="enterprise"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["REQUEST_LOG"] = str(request_log)
            env["STATE_FILE"] = str(state_file)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-ai-assistant-setup/scripts/setup.sh",
                "--complete-onboarding",
                "--activation-code-file",
                str(activation_file),
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            requests = [json.loads(line) for line in request_log.read_text(encoding="utf-8").splitlines()]
            activation_request = next(
                item for item in requests if item["url"].endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/completeonboarding?output_mode=json")
            )
            self.assertEqual(
                json.loads(activation_request["data"]),
                {"activation_code": "encoded-activation-code"},
            )
            self.assertIn("Completed cloud-connected activation for example-prod", result.stdout)
            self.assertIn("configured state matches expected state (true)", result.stdout)
            self.assertIn("onboarded state matches expected state (true)", result.stdout)


    def test_splunk_ai_assistant_validate_reports_pending_onboarding_state_and_expectations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            request_log = tmp_path / "requests.jsonl"
            onboarding_blob = base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "tenant_name": "example-prod",
                        "region": "usa",
                        "email": "ops@example.com",
                    }
                ).encode("utf-8")
            ).decode("utf-8").rstrip("=")

            write_executable(
                bin_dir / "curl",
                f"""\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                args = sys.argv[1:]
                url = ""
                headers = []
                output_target = None
                write_format = ""
                method = "GET"

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-X" and i + 1 < len(args):
                        method = args[i + 1]
                        i += 2
                        continue
                    if arg == "-H" and i + 1 < len(args):
                        headers.append(args[i + 1])
                        i += 2
                        continue
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if arg == "-w" and i + 1 < len(args):
                        write_format = args[i + 1]
                        i += 2
                        continue
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with Path(os.environ["REQUEST_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({{"url": url, "headers": headers, "method": method}}) + "\\n")

                def emit(body: str = "", code: int | None = None) -> None:
                    if output_target == "/dev/null" and code is not None and "%{{http_code}}" in write_format:
                        sys.stdout.write(str(code))
                        raise SystemExit(0)
                    if body:
                        sys.stdout.write(body)
                    if code is not None and "%{{http_code}}" in write_format:
                        sys.stdout.write("\\n" + str(code))
                    raise SystemExit(0)

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    emit("<response><sessionKey>test-session</sessionKey></response>")
                if path.endswith("/services/server/info"):
                    emit(json.dumps({{"entry": [{{"content": {{"version": "10.2.2"}}}}]}}), 200)
                if path.endswith("/services/kvstore/status"):
                    emit(json.dumps({{"entry": [{{"content": {{"current": {{"status": "ready"}}}}}}]}}), 200)
                if path.endswith("/services/apps/local/Splunk_AI_Assistant_Cloud"):
                    emit(json.dumps({{"entry": [{{"name": "Splunk_AI_Assistant_Cloud", "content": {{"version": "1.5.1", "visible": True, "configured": False}}}}]}}), 200)
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/version"):
                    emit(json.dumps({{"version": "1.0.0"}}), 200)
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/storage/collections/data/cloud_connected_configurations"):
                    emit(json.dumps([{{"scs_region": "usa", "encoded_onboarding_data": "{onboarding_blob}"}}]), 200)
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/cloudconnectedproxysettings"):
                    emit(json.dumps({{"proxy_settings": {{}}}}), 200)
                emit("", 200)
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
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_PLATFORM="enterprise"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["REQUEST_LOG"] = str(request_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-ai-assistant-setup/scripts/validate.sh",
                "--expect-configured",
                "false",
                "--expect-onboarded",
                "false",
                "--expect-proxy-enabled",
                "false",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Onboarding form has been submitted but activation is still pending", result.stdout)
            self.assertIn("Remaining blocker: apply the Splunk-issued activation code/token", result.stdout)
            self.assertIn("Pending onboarding tenant: example-prod", result.stdout)
            self.assertIn("Pending onboarding region: usa", result.stdout)
            self.assertIn("configured state matches expected state (false)", result.stdout)
            self.assertIn("onboarded state matches expected state (false)", result.stdout)
            self.assertIn("proxy-enabled state matches expected state (false)", result.stdout)

            requests = [json.loads(line) for line in request_log.read_text(encoding="utf-8").splitlines()]
            custom_requests = [
                item
                for item in requests
                if item["url"].endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/version?output_mode=json")
                or item["url"].endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/cloudconnectedproxysettings?output_mode=json")
            ]
            for request in custom_requests:
                self.assertIn("Source-App-ID: Splunk_AI_Assistant_Cloud", request["headers"])


    def test_validators_report_auth_failures_without_unbound_variable_crashes(self):
        validator_scripts = [
            "skills/cisco-enterprise-networking-setup/scripts/validate.sh",
            "skills/cisco-catalyst-enhanced-netflow-setup/scripts/validate.sh",
            "skills/cisco-security-cloud-setup/scripts/validate.sh",
            "skills/cisco-secure-access-setup/scripts/validate.sh",
            "skills/cisco-dc-networking-setup/scripts/validate.sh",
            "skills/cisco-catalyst-ta-setup/scripts/validate.sh",
            "skills/cisco-intersight-setup/scripts/validate.sh",
            "skills/cisco-meraki-ta-setup/scripts/validate.sh",
            "skills/cisco-thousandeyes-setup/scripts/validate.sh",
            "skills/splunk-itsi-setup/scripts/validate.sh",
            "skills/splunk-ai-assistant-setup/scripts/validate.sh",
            "skills/splunk-connect-for-syslog-setup/scripts/validate.sh",
            "skills/splunk-connect-for-snmp-setup/scripts/validate.sh",
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


    def test_gitignore_excludes_pytest_cache(self):
        gitignore_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".pytest_cache/", gitignore_text)


    def test_cloud_batch_install_expands_enterprise_networking_dependency(self):
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

            result = self.run_script(
                "skills/shared/scripts/cloud_batch_install.sh",
                "--no-restart",
                "7539",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            install_lines = [
                line
                for line in acs_log.read_text(encoding="utf-8").splitlines()
                if "apps install splunkbase" in line
            ]
            install_ids = [
                re.search(r"--splunkbase-id (\d+)", line).group(1)
                for line in install_lines
                if re.search(r"--splunkbase-id (\d+)", line)
            ]
            self.assertEqual(install_ids, ["7538", "7539"])


    def test_cloud_batch_install_hybrid_uses_search_tier_role_and_cloud_verification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            acs_log = tmp_path / "acs.log"
            curl_log = tmp_path / "curl.log"
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

                cmd = " ".join(sys.argv[1:])
                if cmd == "config current-stack":
                    print("Current Search Head: shc1")
                    raise SystemExit(0)
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path
                from urllib.parse import unquote, urlparse

                log_path = Path(os.environ["CURL_LOG"])
                args = sys.argv[1:]
                url = ""
                output_target = None
                write_code = False

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if "%{http_code}" in arg:
                        write_code = True
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                if "/configs/conf-app/package" in path:
                    app = unquote(path.split("/servicesNS/nobody/", 1)[1].split("/", 1)[0])
                    sys.stdout.write(json.dumps({"entry": [{"content": {"id": app}}]}))
                    raise SystemExit(0)

                if output_target == "/dev/null" and write_code:
                    sys.stdout.write("200")
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
                    SPLUNK_PROFILE="cloud"
                    SPLUNK_SEARCH_PROFILE="hf"
                    PROFILE_cloud__SPLUNK_PLATFORM="cloud"
                    PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
                    PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"
                    PROFILE_cloud__STACK_TOKEN="token"
                    PROFILE_cloud__STACK_USERNAME="stack-user"
                    PROFILE_cloud__STACK_PASSWORD="stack-pass"
                    PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
                    PROFILE_hf__SPLUNK_PLATFORM="enterprise"
                    PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
                    PROFILE_hf__SPLUNK_USER="hf-user"
                    PROFILE_hf__SPLUNK_PASS="hf-pass"
                    PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
                    SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/shared/scripts/cloud_batch_install.sh",
                "--no-restart",
                "7539",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertNotIn("not modeled for role 'heavy-forwarder'", output)
            self.assertIn(
                "https://shc1.example-stack.stg.splunkcloud.com:8089/services/auth/login",
                curl_log.read_text(encoding="utf-8"),
            )


    def test_cloud_batch_install_returns_nonzero_when_any_install_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import sys

                args = sys.argv[1:]
                cmd = " ".join(args)

                if "config current-stack" in cmd:
                    print("Current Search Head: sh-i-abc", end="")
                    raise SystemExit(0)
                if "status current-stack" in cmd:
                    print(
                        '[{"type":"http","response":"{\\"infrastructure\\":{\\"status\\":\\"Ready\\"},\\"messages\\":{\\"restartRequired\\":false}}"}]',
                        end="",
                    )
                    raise SystemExit(0)
                if "apps install splunkbase --splunkbase-id bad-app" in cmd:
                    print('{"statusCode":500}', file=sys.stderr)
                    raise SystemExit(2)
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import sys

                args = " ".join(sys.argv[1:])
                if "/services/auth/login" in args and "-d @-" in args:
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                elif "/configs/conf-app/package" in args:
                    sys.stdout.write('{"entry":[{"content":{"id":"whatever"}}]}')
                raise SystemExit(0)
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="cloud"
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    SPLUNK_SEARCH_API_URI="https://example-stack.splunkcloud.com:8089"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/shared/scripts/cloud_batch_install.sh",
                "--no-restart",
                "bad-app",
                "good-app",
                env=env,
            )

            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertIn("1 app(s) failed to install", result.stdout)


    def test_install_app_auto_installs_enterprise_networking_dependency(self):
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
                "skills/splunk-app-install/scripts/install_app.sh",
                "--source",
                "splunkbase",
                "--app-id",
                "7539",
                "--app-version",
                "3.0.0",
                "--no-update",
                "--no-restart",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            install_lines = [
                line
                for line in acs_log.read_text(encoding="utf-8").splitlines()
                if "apps install splunkbase" in line
            ]
            install_ids = [
                re.search(r"--splunkbase-id (\d+)", line).group(1)
                for line in install_lines
                if re.search(r"--splunkbase-id (\d+)", line)
            ]
            self.assertEqual(install_ids, ["7538", "7539"])
            self.assertNotIn("--version 3.0.0", install_lines[0])
            self.assertIn("--version 3.0.0", install_lines[1])

    def test_install_app_cloud_update_finds_existing_splunkbase_app_on_later_acs_page(self):
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
                import json
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                if args[:2] == ["--format", "structured"]:
                    args = args[2:]
                if args[:2] == ["--server", "https://staging.admin.splunk.com"]:
                    args = args[2:]

                cmd = " ".join(args)
                log_path = Path(os.environ["ACS_LOG"])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(cmd + "\\n")

                if cmd == "apps list --splunkbase --count 100 --offset 0":
                    print(json.dumps({"apps": [{"name": f"app-{i}", "splunkbaseID": str(i)} for i in range(100)]}))
                    raise SystemExit(0)

                if cmd == "apps list --splunkbase --count 100 --offset 100":
                    print(json.dumps({"apps": [{"name": "Splunk_AI_Assistant_Cloud", "splunkbaseID": "7245"}]}))
                    raise SystemExit(0)

                if cmd == "apps update Splunk_AI_Assistant_Cloud":
                    print(json.dumps({"name": "Splunk_AI_Assistant_Cloud", "status": "updated"}))
                    raise SystemExit(0)

                if cmd.startswith("apps install splunkbase --splunkbase-id 7245"):
                    raise SystemExit(91)

                if cmd == "status current-stack":
                    print(json.dumps({"infrastructure": {"status": "Ready"}, "messages": {"restartRequired": False}}))
                    raise SystemExit(0)

                raise SystemExit(0)
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="cloud"
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    STACK_USERNAME="stack-user"
                    STACK_PASSWORD="stack-pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-app-install/scripts/install_app.sh",
                "--source",
                "splunkbase",
                "--app-id",
                "7245",
                "--update",
                "--no-restart",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            acs_output = acs_log.read_text(encoding="utf-8")
            self.assertIn("apps list --splunkbase --count 100 --offset 0", acs_output)
            self.assertIn("apps list --splunkbase --count 100 --offset 100", acs_output)
            self.assertIn("apps update Splunk_AI_Assistant_Cloud", acs_output)
            self.assertNotIn("apps install splunkbase --splunkbase-id 7245", acs_output)

    def test_install_app_prefers_highest_versioned_cached_dependency_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            acs_log = tmp_path / "acs.log"
            credentials_file = tmp_path / "credentials"
            ta_cache = tmp_path / "ta-cache"
            ta_cache.mkdir()
            older_package = ta_cache / "cisco-catalyst-add-on-for-splunk_1.9.0.tgz"
            newer_package = ta_cache / "cisco-catalyst-add-on-for-splunk_2.4.1.tgz"
            older_package.write_text("older", encoding="utf-8")
            newer_package.write_text("newer", encoding="utf-8")

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                if args[:2] == ["--format", "structured"]:
                    args = args[2:]
                if args[:2] == ["--server", "https://staging.admin.splunk.com"]:
                    args = args[2:]

                cmd = " ".join(args)
                log_path = Path(os.environ["ACS_LOG"])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(cmd + "\\n")

                if cmd.startswith("apps install splunkbase --splunkbase-id "):
                    print(json.dumps({"status": "installed"}))
                    raise SystemExit(0)

                if cmd == "apps list --splunkbase --count 100 --offset 0":
                    print(json.dumps({"apps": []}))
                    raise SystemExit(0)

                if cmd == "status current-stack":
                    print(json.dumps({"infrastructure": {"status": "Ready"}, "messages": {"restartRequired": False}}))
                    raise SystemExit(0)

                raise SystemExit(0)
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="cloud"
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    STACK_USERNAME="stack-user"
                    STACK_PASSWORD="stack-pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["TA_CACHE"] = str(ta_cache)

            result = self.run_script(
                "skills/splunk-app-install/scripts/install_app.sh",
                "--source",
                "splunkbase",
                "--app-id",
                "7539",
                "--no-update",
                "--no-restart",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn(
                f"Installing required companion app Cisco Catalyst Add-on for Splunk from {newer_package.resolve()}",
                output,
            )
            self.assertNotIn(
                f"Installing required companion app Cisco Catalyst Add-on for Splunk from {older_package.resolve()}",
                output,
            )


    def test_install_app_remote_splunkbase_download_stages_package_on_enterprise_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            ta_cache = tmp_path / "ta-cache"
            ta_cache.mkdir()
            curl_log = tmp_path / "curl.log"
            sshpass_log = tmp_path / "sshpass.log"

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import io
                import json
                import os
                import sys
                import tarfile
                from pathlib import Path
                from urllib.parse import urlparse

                args = sys.argv[1:]
                url = ""
                method = "GET"
                output_target = None
                cookie_target = None
                write_format = ""

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-X" and i + 1 < len(args):
                        method = args[i + 1]
                        i += 2
                        continue
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if arg == "-c" and i + 1 < len(args):
                        cookie_target = args[i + 1]
                        i += 2
                        continue
                    if arg == "-w" and i + 1 < len(args):
                        write_format = args[i + 1]
                        i += 2
                        continue
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with Path(os.environ["CURL_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(" ".join(args) + "\\n")

                def emit_text(body: str = "", code: int | None = None, effective_url: str = "") -> None:
                    if output_target and output_target != "/dev/null" and body:
                        Path(output_target).write_text(body, encoding="utf-8")
                    elif body:
                        sys.stdout.write(body)

                    if write_format and code is not None:
                        rendered = bytes(write_format, "utf-8").decode("unicode_escape")
                        rendered = rendered.replace("%{http_code}", str(code)).replace(
                            "%{url_effective}", effective_url
                        )
                        sys.stdout.write(rendered)
                    raise SystemExit(0)

                path = urlparse(url).path

                if path.endswith("/services/auth/login"):
                    emit_text("<response><sessionKey>test-session</sessionKey></response>")

                if "/api/account:login" in path:
                    if cookie_target:
                        Path(cookie_target).write_text(
                            "# Netscape HTTP Cookie File\\n"
                            ".splunkbase.splunk.com\\tTRUE\\t/\\tFALSE\\t0\\tsessionid\\tdummy-session\\n",
                            encoding="utf-8",
                        )
                    emit_text("<response><id>sb-session</id></response>", code=200)

                if "/api/v1/app/99999/release" in path:
                    emit_text(json.dumps([{"name": "1.2.3", "filename": "remote-test-app_123.tgz"}]))

                if "/app/99999/release/1.2.3/download" in path:
                    buffer = io.BytesIO()
                    payload = b"[launcher]\\nversion = 1.2.3\\n"
                    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                        info = tarfile.TarInfo("remote_test_app/default/app.conf")
                        info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))
                    if not output_target:
                        raise SystemExit(1)
                    Path(output_target).write_bytes(buffer.getvalue())
                    emit_text("", code=200, effective_url="https://cdn.splunkbase.invalid/remote-test-app_123.tgz")

                if path.endswith("/services/apps/local") and method == "POST":
                    emit_text(json.dumps({"entry": [{"name": "remote_test_app"}]}), code=201)

                if "/services/apps/local/remote_test_app" in path:
                    emit_text(
                        json.dumps(
                            {
                                "entry": [
                                    {
                                        "name": "remote_test_app",
                                        "content": {"version": "1.2.3"},
                                    }
                                ]
                            }
                        ),
                        code=200 if output_target == "/dev/null" else None,
                    )

                emit_text("", code=200)
                """,
            )
            write_executable(
                bin_dir / "sshpass",
                """\
                #!/usr/bin/env bash
                printf '%s\n' "$*" >> "${SSHPASS_LOG}"
                exit 0
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
                    SPLUNK_PROFILE="onprem"
                    SB_USER="sb-user"
                    SB_PASS="sb-pass"
                    PROFILE_onprem__SPLUNK_PLATFORM="enterprise"
                    PROFILE_onprem__SPLUNK_TARGET_ROLE="search-tier"
                    PROFILE_onprem__SPLUNK_HOST="10.110.253.5"
                    PROFILE_onprem__SPLUNK_SEARCH_API_URI="https://${SPLUNK_HOST}:8089"
                    PROFILE_onprem__SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    PROFILE_onprem__SPLUNK_USER="splunk"
                    PROFILE_onprem__SPLUNK_PASS="Intersight01!"
                    PROFILE_onprem__SPLUNK_SSH_HOST="${SPLUNK_HOST}"
                    PROFILE_onprem__SPLUNK_SSH_PORT="22"
                    PROFILE_onprem__SPLUNK_SSH_USER="splunk"
                    PROFILE_onprem__SPLUNK_SSH_PASS="Intersight01!"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["TA_CACHE"] = str(ta_cache)
            env["CURL_LOG"] = str(curl_log)
            env["SSHPASS_LOG"] = str(sshpass_log)

            result = self.run_script(
                "skills/splunk-app-install/scripts/install_app.sh",
                "--source",
                "splunkbase",
                "--app-id",
                "99999",
                "--no-update",
                "--no-restart",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("Resolved version: 1.2.3", output)
            self.assertIn("Downloading app 99999 v1.2.3 from Splunkbase...", output)
            self.assertIn("Source URL: https://splunkbase.splunk.com/app/99999/release/1.2.3/download/", output)
            self.assertIn("Resolved URL: https://cdn.splunkbase.invalid/remote-test-app_123.tgz", output)
            self.assertIn("Copying package to splunk@10.110.253.5:/tmp/", output)
            self.assertIn("Installing staged package from /tmp/", output)
            self.assertIn("Version: 1.2.3", output)
            self.assertTrue((ta_cache / "remote-test-app_123.tgz").exists())

            curl_text = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://splunkbase.splunk.com/api/account:login", curl_text)
            self.assertIn("https://splunkbase.splunk.com/api/v1/app/99999/release/", curl_text)
            self.assertIn("https://10.110.253.5:8089/services/apps/local", curl_text)
            self.assertIn("filename=true", curl_text)
            self.assertIn("name=/tmp/", curl_text)

            sshpass_text = sshpass_log.read_text(encoding="utf-8")
            self.assertIn("scp", sshpass_text)
            self.assertIn("splunk@10.110.253.5:/tmp/", sshpass_text)
            self.assertIn("ssh", sshpass_text)


    def test_install_app_reuses_cached_latest_package_before_splunkbase_download(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            ta_cache = tmp_path / "ta-cache"
            ta_cache.mkdir()
            curl_log = tmp_path / "curl.log"
            sshpass_log = tmp_path / "sshpass.log"
            cached_package = ta_cache / "remote-test-app_123.tgz"

            package_root = tmp_path / "pkg-root" / "remote_test_app" / "default"
            package_root.mkdir(parents=True)
            (package_root / "app.conf").write_text("[launcher]\nversion = 1.2.3\n", encoding="utf-8")
            with tarfile.open(cached_package, "w:gz") as archive:
                archive.add(package_root.parent.parent / "remote_test_app", arcname="remote_test_app")

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                args = sys.argv[1:]
                url = ""
                method = "GET"
                output_target = None
                write_format = ""

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-X" and i + 1 < len(args):
                        method = args[i + 1]
                        i += 2
                        continue
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if arg == "-w" and i + 1 < len(args):
                        write_format = args[i + 1]
                        i += 2
                        continue
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with Path(os.environ["CURL_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(" ".join(args) + "\\n")

                def emit(body: str = "", code: int | None = None) -> None:
                    if output_target and output_target != "/dev/null" and body:
                        Path(output_target).write_text(body, encoding="utf-8")
                    elif body:
                        sys.stdout.write(body)
                    if write_format and code is not None:
                        rendered = bytes(write_format, "utf-8").decode("unicode_escape")
                        rendered = rendered.replace("%{http_code}", str(code))
                        sys.stdout.write(rendered)
                    raise SystemExit(0)

                path = urlparse(url).path

                if path.endswith("/services/auth/login"):
                    emit("<response><sessionKey>test-session</sessionKey></response>")

                if "/api/v1/app/99998/release" in path:
                    emit(json.dumps([{"name": "1.2.3", "filename": "remote-test-app_123.tgz"}]))

                if path.endswith("/services/apps/local") and method == "POST":
                    emit(json.dumps({"entry": [{"name": "remote_test_app"}]}), code=201)

                if "/services/apps/local/remote_test_app" in path:
                    emit(
                        json.dumps(
                            {"entry": [{"name": "remote_test_app", "content": {"version": "1.2.3"}}]}
                        ),
                        code=200 if output_target == "/dev/null" else None,
                    )

                emit("", code=200)
                """,
            )
            write_executable(
                bin_dir / "sshpass",
                """\
                #!/usr/bin/env bash
                printf '%s\n' "$*" >> "${SSHPASS_LOG}"
                exit 0
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
                    SPLUNK_PROFILE="onprem"
                    SB_USER="sb-user"
                    SB_PASS="sb-pass"
                    PROFILE_onprem__SPLUNK_PLATFORM="enterprise"
                    PROFILE_onprem__SPLUNK_TARGET_ROLE="search-tier"
                    PROFILE_onprem__SPLUNK_HOST="10.110.253.5"
                    PROFILE_onprem__SPLUNK_SEARCH_API_URI="https://${SPLUNK_HOST}:8089"
                    PROFILE_onprem__SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    PROFILE_onprem__SPLUNK_USER="splunk"
                    PROFILE_onprem__SPLUNK_PASS="Intersight01!"
                    PROFILE_onprem__SPLUNK_SSH_HOST="${SPLUNK_HOST}"
                    PROFILE_onprem__SPLUNK_SSH_PORT="22"
                    PROFILE_onprem__SPLUNK_SSH_USER="splunk"
                    PROFILE_onprem__SPLUNK_SSH_PASS="Intersight01!"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["TA_CACHE"] = str(ta_cache)
            env["CURL_LOG"] = str(curl_log)
            env["SSHPASS_LOG"] = str(sshpass_log)

            result = self.run_script(
                "skills/splunk-app-install/scripts/install_app.sh",
                "--source",
                "splunkbase",
                "--app-id",
                "99998",
                "--no-update",
                "--no-restart",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("Resolved version: 1.2.3", output)
            self.assertIn(f"Existing package found: {cached_package}", output)
            self.assertNotIn("Authenticated to Splunkbase", output)
            self.assertNotIn("Downloading app 99998 v1.2.3 from Splunkbase...", output)
            self.assertIn("Copying package to splunk@10.110.253.5:/tmp/", output)
            self.assertIn("Installing staged package from /tmp/", output)
            self.assertIn("Version: 1.2.3", output)

            curl_text = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://splunkbase.splunk.com/api/v1/app/99998/release/", curl_text)
            self.assertNotIn("https://splunkbase.splunk.com/api/account:login", curl_text)
            self.assertNotIn("/app/99998/release/1.2.3/download/", curl_text)
            self.assertIn("https://10.110.253.5:8089/services/apps/local", curl_text)

            sshpass_text = sshpass_log.read_text(encoding="utf-8")
            self.assertIn("scp", sshpass_text)
            self.assertIn("ssh", sshpass_text)


    def test_install_app_warns_for_known_unsupported_role_but_continues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            package_file = tmp_path / "itsi_4.20.0.tgz"
            package_file.write_text("placeholder", encoding="utf-8")
            env = self._build_mock_install_env(
                tmp_path,
                app_name="SA-ITOA",
                app_version="4.20.0",
                target_role="universal-forwarder",
            )

            result = self.run_script(
                "skills/splunk-app-install/scripts/install_app.sh",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--no-update",
                "--no-restart",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("not modeled for role 'universal-forwarder'", output)
            self.assertIn("search-time knowledge objects", output)


    def test_install_app_skips_role_warning_for_supported_role(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            package_file = tmp_path / "cisco-catalyst-add-on-for-splunk_1.0.0.tgz"
            package_file.write_text("placeholder", encoding="utf-8")
            env = self._build_mock_install_env(
                tmp_path,
                app_name="TA_cisco_catalyst",
                app_version="1.0.0",
                target_role="heavy-forwarder",
            )

            result = self.run_script(
                "skills/splunk-app-install/scripts/install_app.sh",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--no-update",
                "--no-restart",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertNotIn("not modeled for role", output)


    def test_install_app_reports_missing_role_metadata_for_unknown_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            package_file = tmp_path / "unknown-app.tgz"
            package_file.write_text("placeholder", encoding="utf-8")
            env = self._build_mock_install_env(
                tmp_path,
                app_name="unknown_app",
                app_version="1.0.0",
                target_role="heavy-forwarder",
            )

            result = self.run_script(
                "skills/splunk-app-install/scripts/install_app.sh",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--no-update",
                "--no-restart",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("No deployment-role metadata found for the requested package", output)


    def test_install_app_returns_nonzero_on_http_failure_without_error_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "fake-app.tgz"
            package_file.write_text("placeholder", encoding="utf-8")

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import sys

                args = " ".join(sys.argv[1:])
                if "/services/auth/login" in args and "-d @-" in args:
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                elif "/services/apps/local" in args and "%{http_code}" in args:
                    sys.stdout.write("\\n401")
                raise SystemExit(0)
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_SEARCH_API_URI="https://localhost:8089"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-app-install/scripts/install_app.sh",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--no-update",
                "--no-restart",
                env=env,
            )

            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertIn("Installation failed (HTTP 401)", result.stdout + result.stderr)
            self.assertNotIn("Skipping Splunk restart", result.stdout)


    def test_install_app_treats_timeout_after_presence_as_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            package_file = tmp_path / "splunk-mcp-server_110.tgz"
            state_file = tmp_path / "installed.flag"
            package_file.write_text("placeholder", encoding="utf-8")

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                app_name = "Splunk_MCP_Server"
                app_version = "1.1.0"
                state_file = Path(os.environ["MOCK_INSTALL_STATE"])
                args = sys.argv[1:]
                method = "GET"
                url = ""
                write_code = False
                output_target = None

                def out(body: str = "", code: int | None = None) -> None:
                    if output_target == "/dev/null" and write_code and code is not None:
                        sys.stdout.write(str(code))
                        raise SystemExit(0)
                    if body:
                        sys.stdout.write(body)
                    if write_code and code is not None:
                        sys.stdout.write(f"\\n{code}")
                    raise SystemExit(0)

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-X" and i + 1 < len(args):
                        method = args[i + 1]
                        i += 2
                        continue
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if "%{http_code}" in arg:
                        write_code = True
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                path = urlparse(url).path

                if "/services/auth/login" in path:
                    out("<response><sessionKey>test-session</sessionKey></response>")

                if path.endswith("/services/apps/local") and method == "POST":
                    state_file.write_text("installed", encoding="utf-8")
                    raise SystemExit(28)

                if f"/services/apps/local/{app_name}" in path:
                    if output_target == "/dev/null" and write_code:
                        out(code=200 if state_file.exists() else 404)
                    if state_file.exists():
                        out(json.dumps({"entry": [{"name": app_name, "content": {"version": app_version}}]}))
                    out(json.dumps({"entry": []}))

                out("", 200)
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
                    SPLUNK_SEARCH_API_URI="https://localhost:8089"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["MOCK_INSTALL_STATE"] = str(state_file)

            result = self.run_script(
                "skills/splunk-app-install/scripts/install_app.sh",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--no-update",
                "--no-restart",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("Install request did not finish cleanly, but the app is present", output)
            self.assertIn("SUCCESS: App 'Splunk_MCP_Server' installed (HTTP 200)", output)
            self.assertIn("Skipping Splunk restart (--no-restart)", output)


    def test_install_app_help_does_not_require_profile_selection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    PROFILE_cloud__SPLUNK_PLATFORM="cloud"
                    PROFILE_cloud__SPLUNK_SEARCH_API_URI="https://stack.stg.splunkcloud.com:8089"
                    PROFILE_cloud__SPLUNK_CLOUD_STACK="stack"
                    PROFILE_onprem__SPLUNK_PLATFORM="enterprise"
                    PROFILE_onprem__SPLUNK_SEARCH_API_URI="https://onprem.example.com:8089"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-app-install/scripts/install_app.sh",
                "--help",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("Usage:", result.stdout)
            self.assertNotIn("Multiple credential profiles are defined", output)


    def test_install_app_uses_deployer_bundle_for_search_head_cluster_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            package_root = tmp_path / "package-root" / "TestApp" / "default"
            package_root.mkdir(parents=True)
            (package_root / "app.conf").write_text("[ui]\nis_visible = false\n", encoding="utf-8")
            package_file = tmp_path / "TestApp.tgz"
            apply_log = tmp_path / "bundle-apply.log"
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)

            with tarfile.open(package_file, "w:gz") as archive:
                archive.add(package_root.parent.parent / "TestApp", arcname="TestApp")

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import json
                import sys
                from urllib.parse import urlparse

                args = sys.argv[1:]
                url = ""
                for arg in args:
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)
                if "/services/apps/local/TestApp" in path:
                    sys.stdout.write(json.dumps({"entry": [{"name": "TestApp", "content": {"version": "1.0.0"}}]}))
                    raise SystemExit(0)
                raise SystemExit(0)
                """,
            )
            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                printf '%s\\n' "$*" >> "${BUNDLE_APPLY_LOG}"
                exit 0
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="enterprise"
                    SPLUNK_TARGET_ROLE="search-tier"
                    SPLUNK_SEARCH_API_URI="https://localhost:8089"
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_DEPLOYER_PROFILE="deployer"
                    PROFILE_deployer__SPLUNK_PLATFORM="enterprise"
                    PROFILE_deployer__SPLUNK_SEARCH_API_URI="https://localhost:8089"
                    PROFILE_deployer__SPLUNK_URI="${PROFILE_deployer__SPLUNK_SEARCH_API_URI}"
                    PROFILE_deployer__SPLUNK_USER="user"
                    PROFILE_deployer__SPLUNK_PASS="pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["SPLUNK_HOME"] = str(splunk_home)
            env["SPLUNK_LOCAL_SUDO"] = "false"
            env["SPLUNK_BUNDLE_OS_USER"] = getpass.getuser()
            env["BUNDLE_APPLY_LOG"] = str(apply_log)

            result = self.run_script(
                "skills/splunk-app-install/scripts/install_app.sh",
                "--source",
                "local",
                "--file",
                str(package_file),
                "--no-update",
                "--no-restart",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("deployer bundle delivery", output)
            self.assertTrue(
                (splunk_home / "etc" / "shcluster" / "apps" / "TestApp" / "default" / "app.conf").exists()
            )
            self.assertIn("apply shcluster-bundle", apply_log.read_text(encoding="utf-8"))


    def test_cloud_uninstall_script_no_longer_uses_top_level_local_keyword(self):
        script_text = (REPO_ROOT / "skills/splunk-app-install/scripts/uninstall_app.sh").read_text(encoding="utf-8")
        self.assertNotIn("local delete_code", script_text)


    def test_install_app_defaults_splunkbase_to_latest_without_version_prompt(self):
        script_text = (REPO_ROOT / "skills/splunk-app-install/scripts/install_app.sh").read_text(encoding="utf-8")
        self.assertNotIn("App version (leave blank for latest):", script_text)
        self.assertIn("Pin a specific Splunkbase version (default: latest)", script_text)


    def test_cloud_batch_uninstall_returns_nonzero_when_failures_cannot_be_verified(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import sys

                args = sys.argv[1:]
                cmd = " ".join(args)

                if "apps uninstall bad-app" in cmd:
                    print("boom", file=sys.stderr)
                    raise SystemExit(2)
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                raise SystemExit(0)
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="cloud"
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    SPLUNK_SEARCH_API_URI="https://example-stack.splunkcloud.com:8089"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/shared/scripts/cloud_batch_uninstall.sh",
                "--no-restart",
                "bad-app",
                env=env,
            )

            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertIn("verification skipped", (result.stdout + result.stderr).lower())


    def test_cloud_batch_uninstall_resolves_search_uri_from_cloud_only_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            acs_log = tmp_path / "acs.log"
            curl_log = tmp_path / "curl.log"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                log_path = Path(os.environ["ACS_LOG"])
                cmd = " ".join(sys.argv[1:])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(cmd + "\\n")

                if cmd == "config current-stack":
                    print("Current Search Head: shc1")
                    raise SystemExit(0)

                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                log_path = Path(os.environ["CURL_LOG"])
                args = sys.argv[1:]
                url = ""
                output_target = None
                write_code = False

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if "%{http_code}" in arg:
                        write_code = True
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                if "/services/apps/local/" in path and output_target == "/dev/null" and write_code:
                    sys.stdout.write("404")
                    raise SystemExit(0)

                if write_code and output_target == "/dev/null":
                    sys.stdout.write("200")
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
                    SPLUNK_PLATFORM="cloud"
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    STACK_USERNAME="stack-user"
                    STACK_PASSWORD="stack-pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/shared/scripts/cloud_batch_uninstall.sh",
                "--no-restart",
                "example_app",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("example_app = removed", result.stdout)
            self.assertNotIn("verification skipped", (result.stdout + result.stderr).lower())

            curl_output = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://shc1.example-stack.stg.splunkcloud.com:8089/services/auth/login",
                curl_output,
            )


    def test_cloud_batch_uninstall_uses_cloud_search_verification_in_hybrid_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            acs_log = tmp_path / "acs.log"
            curl_log = tmp_path / "curl.log"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                log_path = Path(os.environ["ACS_LOG"])
                cmd = " ".join(sys.argv[1:])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(cmd + "\\n")

                if cmd == "config current-stack":
                    print("Current Search Head: shc1")
                    raise SystemExit(0)

                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                log_path = Path(os.environ["CURL_LOG"])
                args = sys.argv[1:]
                url = ""
                output_target = None
                write_code = False

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if "%{http_code}" in arg:
                        write_code = True
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                if "/services/apps/local/" in path and output_target == "/dev/null" and write_code:
                    sys.stdout.write("404")
                    raise SystemExit(0)

                if write_code and output_target == "/dev/null":
                    sys.stdout.write("200")
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
                    SPLUNK_PROFILE="cloud"
                    SPLUNK_SEARCH_PROFILE="hf"
                    PROFILE_cloud__SPLUNK_PLATFORM="cloud"
                    PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
                    PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"
                    PROFILE_cloud__STACK_TOKEN="token"
                    PROFILE_cloud__STACK_USERNAME="stack-user"
                    PROFILE_cloud__STACK_PASSWORD="stack-pass"
                    PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
                    PROFILE_hf__SPLUNK_PLATFORM="enterprise"
                    PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
                    PROFILE_hf__SPLUNK_USER="hf-user"
                    PROFILE_hf__SPLUNK_PASS="hf-pass"
                    PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
                    SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/shared/scripts/cloud_batch_uninstall.sh",
                "--no-restart",
                "example_app",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("example_app = removed", result.stdout)
            self.assertIn(
                "https://shc1.example-stack.stg.splunkcloud.com:8089/services/auth/login",
                curl_log.read_text(encoding="utf-8"),
            )


    def test_cloud_uninstall_resolves_search_uri_from_cloud_only_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            acs_log = tmp_path / "acs.log"
            curl_log = tmp_path / "curl.log"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                log_path = Path(os.environ["ACS_LOG"])
                cmd = " ".join(sys.argv[1:])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(cmd + "\\n")

                if cmd == "config current-stack":
                    print("Current Search Head: shc1")
                    raise SystemExit(0)

                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                log_path = Path(os.environ["CURL_LOG"])
                args = sys.argv[1:]
                url = ""
                output_target = None
                write_code = False

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if "%{http_code}" in arg:
                        write_code = True
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                if "/services/apps/local/example_app" in path and output_target == "/dev/null" and write_code:
                    sys.stdout.write("404")
                    raise SystemExit(0)

                if write_code and output_target == "/dev/null":
                    sys.stdout.write("404")
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
                    SPLUNK_PLATFORM="cloud"
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    STACK_USERNAME="stack-user"
                    STACK_PASSWORD="stack-pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-app-install/scripts/uninstall_app.sh",
                "--app-name",
                "example_app",
                "--no-restart",
                env=env,
                input_text="yes\n",
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("has been removed from Splunk Cloud", result.stdout)

            curl_output = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://shc1.example-stack.stg.splunkcloud.com:8089/services/auth/login",
                curl_output,
            )


    def test_cloud_uninstall_uses_cloud_search_verification_in_hybrid_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            acs_log = tmp_path / "acs.log"
            curl_log = tmp_path / "curl.log"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                log_path = Path(os.environ["ACS_LOG"])
                cmd = " ".join(sys.argv[1:])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(cmd + "\\n")

                if cmd == "config current-stack":
                    print("Current Search Head: shc1")
                    raise SystemExit(0)

                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                log_path = Path(os.environ["CURL_LOG"])
                args = sys.argv[1:]
                url = ""
                output_target = None
                write_code = False

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if "%{http_code}" in arg:
                        write_code = True
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                if "/services/apps/local/example_app" in path and output_target == "/dev/null" and write_code:
                    sys.stdout.write("404")
                    raise SystemExit(0)

                if write_code and output_target == "/dev/null":
                    sys.stdout.write("404")
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
                    SPLUNK_PROFILE="cloud"
                    SPLUNK_SEARCH_PROFILE="hf"
                    PROFILE_cloud__SPLUNK_PLATFORM="cloud"
                    PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
                    PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"
                    PROFILE_cloud__STACK_TOKEN="token"
                    PROFILE_cloud__STACK_USERNAME="stack-user"
                    PROFILE_cloud__STACK_PASSWORD="stack-pass"
                    PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
                    PROFILE_hf__SPLUNK_PLATFORM="enterprise"
                    PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
                    PROFILE_hf__SPLUNK_USER="hf-user"
                    PROFILE_hf__SPLUNK_PASS="hf-pass"
                    PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
                    SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-app-install/scripts/uninstall_app.sh",
                "--app-name",
                "example_app",
                "--no-restart",
                env=env,
                input_text="yes\n",
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("has been removed from Splunk Cloud", result.stdout)
            self.assertIn(
                "https://shc1.example-stack.stg.splunkcloud.com:8089/services/auth/login",
                curl_log.read_text(encoding="utf-8"),
            )


    def test_cloud_uninstall_falls_back_to_stack_search_uri_when_current_search_head_lookup_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            acs_log = tmp_path / "acs.log"
            curl_log = tmp_path / "curl.log"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                log_path = Path(os.environ["ACS_LOG"])
                cmd = " ".join(sys.argv[1:])
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(cmd + "\\n")

                if cmd == "config current-stack":
                    raise SystemExit(1)

                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                log_path = Path(os.environ["CURL_LOG"])
                args = sys.argv[1:]
                url = ""
                output_target = None
                write_code = False

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if "%{http_code}" in arg:
                        write_code = True
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                if "/services/apps/local/example_app" in path and output_target == "/dev/null" and write_code:
                    sys.stdout.write("404")
                    raise SystemExit(0)

                if write_code and output_target == "/dev/null":
                    sys.stdout.write("404")
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
                    SPLUNK_PROFILE="cloud"
                    SPLUNK_SEARCH_PROFILE="hf"
                    PROFILE_cloud__SPLUNK_PLATFORM="cloud"
                    PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
                    PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"
                    PROFILE_cloud__STACK_TOKEN="token"
                    PROFILE_cloud__STACK_USERNAME="stack-user"
                    PROFILE_cloud__STACK_PASSWORD="stack-pass"
                    PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
                    PROFILE_hf__SPLUNK_PLATFORM="enterprise"
                    PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
                    PROFILE_hf__SPLUNK_USER="hf-user"
                    PROFILE_hf__SPLUNK_PASS="hf-pass"
                    PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
                    SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["ACS_LOG"] = str(acs_log)
            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-app-install/scripts/uninstall_app.sh",
                "--app-name",
                "example_app",
                "--no-restart",
                env=env,
                input_text="yes\n",
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("has been removed from Splunk Cloud", result.stdout)
            self.assertNotIn(
                "search-tier verification is unavailable",
                (result.stdout + result.stderr).lower(),
            )
            self.assertIn(
                "https://example-stack.stg.splunkcloud.com:8089/services/auth/login",
                curl_log.read_text(encoding="utf-8"),
            )


    def test_uninstall_app_uses_deployer_bundle_for_search_head_cluster_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            splunk_home = tmp_path / "splunk"
            app_dir = splunk_home / "etc" / "shcluster" / "apps" / "TestApp"
            (splunk_home / "bin").mkdir(parents=True)
            (app_dir / "default").mkdir(parents=True)
            (app_dir / "default" / "app.conf").write_text("[ui]\nis_visible = false\n", encoding="utf-8")
            apply_log = tmp_path / "bundle-apply.log"

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import sys
                from urllib.parse import urlparse

                args = sys.argv[1:]
                url = ""
                output_target = None
                write_format = ""

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if arg == "-w" and i + 1 < len(args):
                        write_format = args[i + 1]
                        i += 2
                        continue
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)
                if "/services/apps/local/TestApp" in path and output_target == "/dev/null" and "%{http_code}" in write_format:
                    sys.stdout.write("200")
                    raise SystemExit(0)
                raise SystemExit(0)
                """,
            )
            write_executable(
                splunk_home / "bin" / "splunk",
                """\
                #!/usr/bin/env bash
                printf '%s\\n' "$*" >> "${BUNDLE_APPLY_LOG}"
                exit 0
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="enterprise"
                    SPLUNK_TARGET_ROLE="search-tier"
                    SPLUNK_SEARCH_API_URI="https://localhost:8089"
                    SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_DEPLOYER_PROFILE="deployer"
                    PROFILE_deployer__SPLUNK_PLATFORM="enterprise"
                    PROFILE_deployer__SPLUNK_SEARCH_API_URI="https://localhost:8089"
                    PROFILE_deployer__SPLUNK_URI="${PROFILE_deployer__SPLUNK_SEARCH_API_URI}"
                    PROFILE_deployer__SPLUNK_USER="user"
                    PROFILE_deployer__SPLUNK_PASS="pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["SPLUNK_HOME"] = str(splunk_home)
            env["SPLUNK_LOCAL_SUDO"] = "false"
            env["SPLUNK_BUNDLE_OS_USER"] = getpass.getuser()
            env["BUNDLE_APPLY_LOG"] = str(apply_log)

            result = self.run_script(
                "skills/splunk-app-install/scripts/uninstall_app.sh",
                "--app-name",
                "TestApp",
                "--no-restart",
                env=env,
                input_text="yes\n",
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("deployer bundle removal", output)
            self.assertFalse(app_dir.exists())
            self.assertTrue(list((splunk_home / "etc" / "shcluster" / "apps").glob("TestApp.removed.*")))
            self.assertIn("apply shcluster-bundle", apply_log.read_text(encoding="utf-8"))


    def test_enterprise_uninstall_treats_delete_timeout_after_removal_as_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            state_file = tmp_path / "deleted.flag"

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                state_file = Path(os.environ["DELETE_STATE_FILE"])
                args = sys.argv[1:]
                url = ""
                method = "GET"
                output_target = None
                write_format = ""

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-X" and i + 1 < len(args):
                        method = args[i + 1]
                        i += 2
                        continue
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if arg == "-w" and i + 1 < len(args):
                        write_format = args[i + 1]
                        i += 2
                        continue
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                if "/services/apps/local/example_app" in path and method == "DELETE":
                    state_file.write_text("deleted", encoding="utf-8")
                    raise SystemExit(28)

                if "/services/apps/local/example_app" in path and output_target == "/dev/null" and "%{http_code}" in write_format:
                    sys.stdout.write("404" if state_file.exists() else "200")
                    raise SystemExit(0)

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
                    SPLUNK_PLATFORM="enterprise"
                    SPLUNK_SEARCH_API_URI="https://example-enterprise:8089"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_VERIFY_SSL="false"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["DELETE_STATE_FILE"] = str(state_file)

            result = self.run_script(
                "skills/splunk-app-install/scripts/uninstall_app.sh",
                "--app-name",
                "example_app",
                "--no-restart",
                env=env,
                input_text="yes\n",
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("did not finish cleanly, but the app is no longer present", result.stdout)
            self.assertIn("SUCCESS: App 'example_app' has been removed", result.stdout)


    def test_cloud_uninstall_treats_fallback_delete_timeout_after_removal_as_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            state_file = tmp_path / "deleted.flag"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import sys

                cmd = " ".join(sys.argv[1:])
                if cmd == "config current-stack":
                    print("Current Search Head: shc1")
                    raise SystemExit(0)
                if cmd == "apps describe example_app":
                    raise SystemExit(0)
                if cmd == "apps uninstall example_app":
                    raise SystemExit(0)
                raise SystemExit(0)
                """,
            )
            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path
                from urllib.parse import urlparse

                state_file = Path(os.environ["DELETE_STATE_FILE"])
                args = sys.argv[1:]
                url = ""
                method = "GET"
                output_target = None
                write_format = ""

                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "-X" and i + 1 < len(args):
                        method = args[i + 1]
                        i += 2
                        continue
                    if arg == "-o" and i + 1 < len(args):
                        output_target = args[i + 1]
                        i += 2
                        continue
                    if arg == "-w" and i + 1 < len(args):
                        write_format = args[i + 1]
                        i += 2
                        continue
                    if arg.startswith("http://") or arg.startswith("https://"):
                        url = arg
                    i += 1

                path = urlparse(url).path
                if path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                if "/services/apps/local/example_app" in path and method == "DELETE":
                    state_file.write_text("deleted", encoding="utf-8")
                    raise SystemExit(28)

                if "/services/apps/local/example_app" in path and output_target == "/dev/null" and "%{http_code}" in write_format:
                    if state_file.exists():
                        sys.stdout.write("404")
                    else:
                        sys.stdout.write("200")
                    raise SystemExit(0)

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
                    SPLUNK_PLATFORM="cloud"
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    STACK_USERNAME="stack-user"
                    STACK_PASSWORD="stack-pass"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["DELETE_STATE_FILE"] = str(state_file)

            result = self.run_script(
                "skills/splunk-app-install/scripts/uninstall_app.sh",
                "--app-name",
                "example_app",
                "--no-restart",
                env=env,
                input_text="yes\n",
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Search-tier REST DELETE did not finish cleanly, but the app is no longer present", result.stdout)
            self.assertIn("has been removed from Splunk Cloud", result.stdout)


    def test_list_apps_defaults_to_all_apps_in_noninteractive_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import json
                import sys
                from urllib.parse import urlparse

                args = sys.argv[1:]
                url = next((arg for arg in args if arg.startswith("http://") or arg.startswith("https://")), "")
                path = urlparse(url).path

                if path.endswith("/services/auth/login"):
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                if path.endswith("/services/apps/local"):
                    sys.stdout.write(json.dumps({
                        "entry": [
                            {"name": "TA_one", "content": {"version": "1.0.0", "label": "App One", "disabled": False}},
                            {"name": "TA_two", "content": {"version": "2.0.0", "label": "App Two", "disabled": True}},
                        ]
                    }))
                    raise SystemExit(0)

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
            env["SPLUNK_PLATFORM"] = "enterprise"

            result = self.run_script(
                "skills/splunk-app-install/scripts/list_apps.sh",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("TA_one", result.stdout)
            self.assertIn("TA_two", result.stdout)

    def test_list_apps_cloud_reads_apps_beyond_first_acs_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import json
                import sys

                args = sys.argv[1:]
                if args[:2] == ["--format", "structured"]:
                    args = args[2:]
                if args[:2] == ["--server", "https://staging.admin.splunk.com"]:
                    args = args[2:]

                cmd = " ".join(args)
                if cmd == "apps list --count 100 --offset 0":
                    print(json.dumps({"apps": [{"name": f"app-{i}", "version": "1.0.0", "label": f"App {i}", "status": "installed"} for i in range(100)]}))
                    raise SystemExit(0)
                if cmd == "apps list --count 100 --offset 100":
                    print(json.dumps({"apps": [{"name": "late-app", "version": "9.9.9", "label": "Late App", "status": "installed"}]}))
                    raise SystemExit(0)
                raise SystemExit(0)
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="cloud"
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-app-install/scripts/list_apps.sh",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("late-app", result.stdout)
            self.assertIn("Total: 101 app(s)", result.stdout)

    def test_uninstall_app_cloud_interactive_list_reads_apps_beyond_first_acs_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
                import sys

                args = sys.argv[1:]
                if args[:2] == ["--format", "structured"]:
                    args = args[2:]
                if args[:2] == ["--server", "https://staging.admin.splunk.com"]:
                    args = args[2:]

                cmd = " ".join(args)
                if cmd == "apps list --count 100 --offset 0":
                    import json
                    print(json.dumps({"apps": [{"name": f"app-{i}"} for i in range(100)]}))
                    raise SystemExit(0)
                if cmd == "apps list --count 100 --offset 100":
                    print('{"apps": [{"name": "late-app"}]}')
                    raise SystemExit(0)
                if cmd == "apps describe late-app":
                    raise SystemExit(0)
                if cmd == "apps uninstall late-app":
                    raise SystemExit(0)
                raise SystemExit(0)
                """,
            )

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PLATFORM="cloud"
                    SPLUNK_CLOUD_STACK="example-stack"
                    ACS_SERVER="https://staging.admin.splunk.com"
                    STACK_TOKEN="token"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-app-install/scripts/uninstall_app.sh",
                "--no-restart",
                env=env,
                input_text="late-app\nyes\n",
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("late-app", output)
            self.assertIn("ACS uninstall accepted for 'late-app'.", output)
