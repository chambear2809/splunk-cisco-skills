#!/usr/bin/env python3
"""Focused regression coverage for the Splunk AI Assistant setup skill."""

import base64
import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT, ShellScriptRegressionBase, write_executable


class SplunkAIAssistantRegressionTests(ShellScriptRegressionBase):
    def test_activation_code_is_not_passed_to_python_argv(self) -> None:
        script_text = (REPO_ROOT / "skills/splunk-ai-assistant-setup/scripts/setup.sh").read_text(encoding="utf-8")

        self.assertNotIn('python3 - "${activation_code}"', script_text)
        self.assertIn('python3 - 3<<<"${activation_code}"', script_text)

    def test_proxy_password_is_not_passed_to_python_argv(self) -> None:
        script_text = (REPO_ROOT / "skills/splunk-ai-assistant-setup/scripts/setup.sh").read_text(encoding="utf-8")

        self.assertNotIn('python3 - "${PROXY_URL}" "${PROXY_USERNAME}" "${proxy_password}"', script_text)
        self.assertIn('python3 - "${PROXY_URL}" "${PROXY_USERNAME}" 3<<<"${proxy_password}"', script_text)
        self.assertIn("os.fdopen(3", script_text)

    def test_cloud_install_uses_acs_without_preinstall_rest_auth(self) -> None:
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
                with Path(os.environ["ACS_LOG"]).open("a", encoding="utf-8") as handle:
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

                with Path(os.environ["CURL_LOG"]).open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

                if url.endswith("/services/auth/login"):
                    raise SystemExit(99)
                if url in ("https://checkip.amazonaws.com", "https://api.ipify.org"):
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
            self.assertIn("apps install splunkbase --splunkbase-id 7245", acs_log.read_text(encoding="utf-8"))
            curl_output = curl_log.read_text(encoding="utf-8") if curl_log.exists() else ""
            self.assertNotIn("/services/auth/login", curl_output)

    def test_submit_onboarding_normalizes_region_and_auto_validates(self) -> None:
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
                    handle.write(json.dumps({{"url": url, "headers": headers, "data": data, "method": method}}) + "\\n")

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
                if path.endswith("/servicesNS/nobody/Splunk_AI_Assistant_Cloud/submitonboardingform"):
                    emit(json.dumps({{"value": "encoded-onboarding-data"}}), 200)
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

    def test_complete_onboarding_reads_activation_code_and_auto_validates(self) -> None:
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
                                        "scs_region": "usa",
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
            self.assertEqual(json.loads(activation_request["data"]), {"activation_code": "encoded-activation-code"})
            self.assertIn("Completed cloud-connected activation for example-prod", result.stdout)
            self.assertIn("configured state matches expected state (true)", result.stdout)
            self.assertIn("onboarded state matches expected state (true)", result.stdout)

    def test_validate_reports_pending_onboarding_state_and_expectations(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
