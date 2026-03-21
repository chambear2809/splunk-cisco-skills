#!/usr/bin/env python3
"""Regression tests for first-party shell entrypoints."""

import json
import os
import re
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

    def build_mock_cisco_skill_env(self, tmp_path: Path) -> tuple[dict, Path, Path, Path, Path]:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        state_file = tmp_path / "state.json"
        install_log = tmp_path / "install.log"
        curl_log = tmp_path / "curl.log"
        credentials_file = tmp_path / "credentials"
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()

        state_file.write_text(
            json.dumps(
                {
                    "installed_apps": {},
                    "indexes": [],
                    "security_cloud_handlers": {},
                    "security_cloud_settings": {"loglevel": ""},
                    "secure_access": {
                        "org_accounts": {},
                        "collections": {
                            "cloudlock-v2-tos": [],
                            "global_org": [],
                            "dashboard_settings": [],
                            "refresh_rate": [],
                            "cloudlock_settings": [],
                            "selected_destination_lists": [],
                            "s3_indexes": [],
                        },
                        "roles_bootstrapped": False,
                    },
                }
            ),
            encoding="utf-8",
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

        secret_values = {
            "xdr_refresh_token": "xdr-refresh-token",
            "se_api_key": "secure-endpoint-api-key",
            "cii_client_secret": "cii-client-secret",
            "sa_api_key": "secure-access-api-key",
            "sa_api_secret": "secure-access-api-secret",
            "cloudlock_token": "cloudlock-token",
        }
        for name, value in secret_values.items():
            (secrets_dir / name).write_text(value, encoding="utf-8")

        write_executable(
            bin_dir / "nc",
            """\
            #!/usr/bin/env bash
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
            from urllib.parse import parse_qs, urlparse, unquote

            state_path = Path(os.environ["SMOKE_STATE"])
            log_path = Path(os.environ["CURL_LOG"])
            state = json.loads(state_path.read_text(encoding="utf-8"))

            args = sys.argv[1:]
            method = "GET"
            data = ""
            url = ""
            write_code = False
            output_target = None

            def log(msg: str) -> None:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(msg + "\\n")

            def save() -> None:
                state_path.write_text(json.dumps(state), encoding="utf-8")

            def out(body: str = "", code: int | None = None) -> None:
                if output_target == "/dev/null" and write_code and code is not None:
                    sys.stdout.write(str(code))
                    raise SystemExit(0)
                if body:
                    sys.stdout.write(body)
                if write_code and code is not None:
                    sys.stdout.write(f"\\n{code}")
                raise SystemExit(0)

            def decode_form(raw: str) -> dict[str, str]:
                parsed_body = parse_qs(raw, keep_blank_values=True)
                return {key: values[-1] for key, values in parsed_body.items()}

            log("ARGV=" + repr(args))

            i = 0
            while i < len(args):
                arg = args[i]
                if arg == "-X" and i + 1 < len(args):
                    method = args[i + 1]
                    i += 2
                    continue
                if arg == "-d" and i + 1 < len(args):
                    if args[i + 1] == "@-":
                        data = sys.stdin.read()
                    else:
                        data = args[i + 1]
                    if method == "GET":
                        method = "POST"
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

            parsed = urlparse(url)
            path = parsed.path
            query = parse_qs(parsed.query)
            log(f"URL={url} METHOD={method} DATA={data!r} WRITE={write_code} OUTPUT={output_target}")

            if "splunkbase.splunk.com/api/v1/app/7404/release/" in url:
                out('[{"name":"3.6.3"}]')
            if "splunkbase.splunk.com/api/v1/app/5558/release/" in url:
                out('[{"name":"1.0.53"}]')

            if "/services/auth/login" in path:
                out("<response><sessionKey>test-session</sessionKey></response>")

            if "/services/server/info" in path and write_code:
                out(code=200)

            if "/services/apps/local/" in path:
                app = unquote(path.split("/services/apps/local/", 1)[1]).split("/", 1)[0]
                installed = state["installed_apps"].get(app)
                if output_target == "/dev/null" and write_code:
                    out(code=200 if installed else 404)
                if installed:
                    out(json.dumps({"entry": [{"name": app, "content": {"version": installed["version"]}}]}))
                out(json.dumps({"entry": []}))

            if path.endswith("/services/data/indexes") and method == "POST":
                body = decode_form(data)
                idx = body.get("name", "")
                if idx and idx not in state["indexes"]:
                    state["indexes"].append(idx)
                    save()
                out("", 201)

            if "/services/data/indexes/" in path:
                idx = path.rsplit("/", 1)[-1]
                exists = idx in state["indexes"]
                if output_target == "/dev/null" and write_code:
                    out(code=200 if exists else 404)
                out(json.dumps({"entry": [{"name": idx}]} if exists else {"entry": []}))

            if "configs/conf-ciscosecuritycloud_settings/logging" in path:
                if method == "POST":
                    body = decode_form(data)
                    if "loglevel" in body:
                        state["security_cloud_settings"]["loglevel"] = body["loglevel"]
                        save()
                    out("", 200)
                out(json.dumps({"entry": [{"content": {"loglevel": state["security_cloud_settings"].get("loglevel", "")}}]}))

            if "/servicesNS/nobody/CiscoSecurityCloud/CiscoSecurityCloud_" in path:
                handler = path.split("/servicesNS/nobody/CiscoSecurityCloud/", 1)[1].split("?", 1)[0]
                handlers = state["security_cloud_handlers"].setdefault(handler, {})
                if method == "GET":
                    entries = [{"name": name, "content": content} for name, content in handlers.items()]
                    out(json.dumps({"entry": entries}))
                body = decode_form(data)
                if "name" in body:
                    name = body.pop("name")
                else:
                    name = unquote(path.rsplit("/", 1)[-1].split("?", 1)[0])
                handlers[name] = body
                save()
                out("", 201)

            if "/servicesNS/nobody/cisco-cloud-security/org_accounts" in path:
                orgs = state["secure_access"]["org_accounts"]
                if query.get("action") == ["get_orgId"] and method == "POST":
                    out(json.dumps({"payload": {"orgId": "org-123"}, "status": 200}), 200)
                if method == "GET":
                    org_id = query.get("orgId", [""])[0]
                    if org_id:
                        if org_id in orgs:
                            out(json.dumps({"payload": {"data": [orgs[org_id]], "recordsTotal": 1}, "status": 200}), 200)
                        out(json.dumps({"payload": {"message": f"Account not found for orgId: {org_id}"}, "status": 404}), 404)
                    rows = list(orgs.values())
                    out(json.dumps({"payload": {"data": rows, "recordsTotal": len(rows)}, "status": 200}), 200)
                payload = json.loads(data or "{}")
                if "data" in payload:
                    payload = payload["data"]
                org_id = payload.get("orgId", "org-123")
                record = orgs.get(org_id, {"orgId": org_id})
                record.update({key: value for key, value in payload.items() if key not in ("apiKey", "apiSecret")})
                orgs[org_id] = record
                if not state["secure_access"]["collections"]["global_org"]:
                    state["secure_access"]["collections"]["global_org"] = [{"orgId": org_id}]
                save()
                if method == "POST":
                    out(json.dumps({"payload": {"message": "Account created successfully", "orgId": org_id}, "status": 201}), 201)
                if method == "PUT":
                    out(json.dumps({"payload": {"message": "Account updated successfully", "orgId": org_id}, "status": 200}), 200)

            if "/servicesNS/nobody/cisco-cloud-security/role_manager" in path:
                state["secure_access"]["roles_bootstrapped"] = True
                save()
                out(json.dumps({"payload": {"message": "Role creation completed"}, "status": 200}), 200)

            if "/servicesNS/nobody/cisco-cloud-security/toc_functionality" in path:
                payload = json.loads(data or "{}").get("data", {})
                coll = state["secure_access"]["collections"]["cloudlock-v2-tos"]
                coll.append(
                    {
                        "CustName": payload.get("CustName", ""),
                        "CustVersion": payload.get("CustVersion", ""),
                        "CustDate": "2026-03-20 00:00:00",
                    }
                )
                save()
                out(json.dumps({"payload": "successfully inserted into TOC kvstore", "status": 200}), 200)

            if "/servicesNS/nobody/cisco-cloud-security/update_settings" in path:
                payload = json.loads(data or "{}").get("data", {})
                coll = state["secure_access"]["collections"]
                org_id = payload.get("orgId", "")
                if "Dashboard" in payload:
                    coll["dashboard_settings"] = [{"search_interval": payload["Dashboard"].get("search_interval", "")}]
                if "refresh_rate" in payload:
                    coll["refresh_rate"] = [{"refresh_rate": payload["refresh_rate"]}]
                if "cloudlock" in payload:
                    cloudlock = dict(payload["cloudlock"])
                    cloudlock["status"] = "active"
                    coll["cloudlock_settings"] = [cloudlock]
                if "selected_destination_lists" in payload:
                    rows = []
                    for row in payload["selected_destination_lists"]:
                        new_row = dict(row)
                        new_row["orgId"] = org_id
                        rows.append(new_row)
                    coll["selected_destination_lists"] = rows
                if "s3_indexes" in payload:
                    s3 = payload["s3_indexes"]
                    coll["s3_indexes"] = [
                        {
                            "orgId": org_id,
                            "dns_index": s3.get("dns", ""),
                            "proxy_index": s3.get("proxy", ""),
                            "firewall_index": s3.get("firewall", ""),
                            "dlp_index": s3.get("dlp", ""),
                            "ravpn_index": s3.get("ravpn", ""),
                            "createdDate": s3.get("createdDate", ""),
                        }
                    ]
                save()
                out(json.dumps({"payload": "Application settings saved successfully", "status": 200}), 200)

            if "/storage/collections/data/" in path:
                collection = unquote(path.split("/storage/collections/data/", 1)[1])
                out(json.dumps(state["secure_access"]["collections"].get(collection, [])))

            out("", 200)
            """,
        )
        write_executable(
            tmp_path / "fake_install_app.sh",
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            python3 - "$@" <<'PY'
            import json
            import os
            import sys
            from pathlib import Path

            state_path = Path(os.environ["SMOKE_STATE"])
            log_path = Path(os.environ["INSTALL_LOG"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            args = sys.argv[1:]
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(" ".join(args) + "\\n")

            mapping = {
                "7404": ("CiscoSecurityCloud", "3.6.3"),
                "5558": ("cisco-cloud-security", "1.0.53"),
            }
            app_id = ""
            version = ""
            file_path = ""
            for i, arg in enumerate(args):
                if arg == "--app-id" and i + 1 < len(args):
                    app_id = args[i + 1]
                elif arg == "--app-version" and i + 1 < len(args):
                    version = args[i + 1]
                elif arg == "--file" and i + 1 < len(args):
                    file_path = args[i + 1]

            if app_id in mapping:
                app_name, default_version = mapping[app_id]
            elif "cisco-security-cloud" in file_path:
                app_name, default_version = ("CiscoSecurityCloud", "3.6.3")
            elif "cisco-secure-access-app-for-splunk" in file_path:
                app_name, default_version = ("cisco-cloud-security", "1.0.53")
            else:
                raise SystemExit(1)

            state["installed_apps"][app_name] = {"version": version or default_version}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            PY
            """,
        )

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["SMOKE_STATE"] = str(state_file)
        env["CURL_LOG"] = str(curl_log)
        env["INSTALL_LOG"] = str(install_log)
        env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
        env["APP_INSTALL_SCRIPT"] = str(tmp_path / "fake_install_app.sh")
        env["SPLUNK_PLATFORM"] = "enterprise"

        return env, secrets_dir, state_file, install_log, curl_log

    def build_mock_sc4s_env(self, tmp_path: Path) -> tuple[dict, Path]:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        state_file = tmp_path / "sc4s_state.json"
        credentials_file = tmp_path / "credentials"

        state_file.write_text(
            json.dumps(
                {
                    "indexes": {},
                    "hec_tokens": {},
                    "startup_count": 2,
                }
            ),
            encoding="utf-8",
        )

        credentials_file.write_text(
            textwrap.dedent(
                """\
                SPLUNK_PLATFORM="enterprise"
                SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
                SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
                SPLUNK_USER="user"
                SPLUNK_PASS="pass"
                """
            ),
            encoding="utf-8",
        )

        write_executable(
            bin_dir / "curl",
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path
            from urllib.parse import parse_qs, urlparse

            state_path = Path(os.environ["SC4S_STATE"])
            state = json.loads(state_path.read_text(encoding="utf-8"))

            args = sys.argv[1:]
            method = "GET"
            data = ""
            url = ""
            write_code = False
            output_target = None

            def save() -> None:
                state_path.write_text(json.dumps(state), encoding="utf-8")

            def out(body: str = "", code: int | None = None) -> None:
                if output_target == "/dev/null" and write_code and code is not None:
                    sys.stdout.write(str(code))
                    raise SystemExit(0)
                if body:
                    sys.stdout.write(body)
                if write_code and code is not None:
                    sys.stdout.write(f"\\n{code}")
                raise SystemExit(0)

            def decode_form(raw: str) -> dict[str, str]:
                parsed_body = parse_qs(raw, keep_blank_values=True)
                return {key: values[-1] for key, values in parsed_body.items()}

            i = 0
            while i < len(args):
                arg = args[i]
                if arg == "-X" and i + 1 < len(args):
                    method = args[i + 1]
                    i += 2
                    continue
                if arg == "-d" and i + 1 < len(args):
                    if args[i + 1] == "@-":
                        data = sys.stdin.read()
                    else:
                        data = args[i + 1]
                    if method == "GET":
                        method = "POST"
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

            parsed = urlparse(url)
            path = parsed.path

            if "/services/auth/login" in path:
                out("<response><sessionKey>test-session</sessionKey></response>")

            if path.endswith("/services/data/indexes") and method == "POST":
                body = decode_form(data)
                idx = body.get("name", "")
                datatype = body.get("datatype", "event")
                if idx:
                    state["indexes"][idx] = {"datatype": datatype}
                    save()
                out("", 201)

            if "/services/data/indexes/" in path:
                idx = path.rsplit("/", 1)[-1]
                exists = idx in state["indexes"]
                if output_target == "/dev/null" and write_code:
                    out(code=200 if exists else 404)
                if exists:
                    out(
                        json.dumps(
                            {
                                "entry": [
                                    {
                                        "name": idx,
                                        "content": {
                                            "datatype": state["indexes"][idx].get("datatype", "event")
                                        },
                                    }
                                ]
                            }
                        )
                    )
                out(json.dumps({"entry": []}))

            if path.endswith("/services/data/inputs/http") and method == "POST":
                body = decode_form(data)
                name = body.get("name", "sc4s")
                state["hec_tokens"][name] = {
                    "disabled": body.get("disabled", "false"),
                    "useACK": body.get("useACK", "0"),
                    "indexes": body.get("indexes", ""),
                    "index": body.get("index", "main"),
                    "token": f"generated-{name}-token",
                }
                save()
                out("", 201)

            if "/services/data/inputs/http/" in path and path.endswith("/enable") and method == "POST":
                encoded_name = path.rsplit("/", 2)[-2]
                name = encoded_name.replace("%3A", ":").replace("%2F", "/")
                if name.startswith("http://"):
                    name = name[len("http://") :]
                token = state["hec_tokens"].setdefault(name, {"index": "main", "token": f"generated-{name}-token"})
                token["disabled"] = "false"
                save()
                out("", 200)

            if path.endswith("/services/data/inputs/http"):
                entries = []
                for name, token in sorted(state["hec_tokens"].items()):
                    entries.append(
                        {
                            "name": f"http://{name}",
                            "content": {
                                "disabled": token.get("disabled", "false"),
                                "useACK": token.get("useACK", "0"),
                                "indexes": token.get("indexes", ""),
                                "index": token.get("index", "main"),
                                "token": token.get("token", ""),
                            },
                        }
                    )
                out(json.dumps({"entry": entries}))

            if path.endswith("/services/search/jobs") and method == "POST":
                out(json.dumps({"results": [{"count": str(state.get("startup_count", 0))}]}))

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

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["SC4S_STATE"] = str(state_file)
        env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
        env["SPLUNK_PLATFORM"] = "enterprise"

        return env, state_file

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
            "skills/cisco-catalyst-enhanced-netflow-setup/scripts/validate.sh",
            "skills/cisco-security-cloud-setup/scripts/validate.sh",
            "skills/cisco-secure-access-setup/scripts/validate.sh",
            "skills/cisco-dc-networking-setup/scripts/validate.sh",
            "skills/cisco-catalyst-ta-setup/scripts/validate.sh",
            "skills/cisco-intersight-setup/scripts/validate.sh",
            "skills/cisco-meraki-ta-setup/scripts/validate.sh",
            "skills/cisco-thousandeyes-setup/scripts/validate.sh",
            "skills/splunk-itsi-setup/scripts/validate.sh",
            "skills/splunk-connect-for-syslog-setup/scripts/validate.sh",
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

    def test_enterprise_networking_registry_declares_companion_ta_dependency(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        enterprise_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "7539"
        )
        enhanced_netflow_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "6872"
        )

        self.assertEqual(enterprise_entry["app_name"], "cisco-catalyst-app")
        self.assertEqual(enterprise_entry.get("install_requires"), ["7538"])
        self.assertEqual(enhanced_netflow_entry["skill"], "cisco-catalyst-enhanced-netflow-setup")
        self.assertEqual(enhanced_netflow_entry["app_name"], "splunk_app_stream_ipfix_cisco_hsl")
        self.assertIn(
            "cisco-catalyst-enhanced-netflow-add-on-for-splunk_*",
            enhanced_netflow_entry.get("package_patterns", []),
        )

    def test_cisco_security_registry_entries_are_present(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        security_cloud_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "7404"
        )
        secure_access_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "5558"
        )

        self.assertEqual(security_cloud_entry["skill"], "cisco-security-cloud-setup")
        self.assertEqual(security_cloud_entry["app_name"], "CiscoSecurityCloud")
        self.assertIn("cisco-security-cloud_*", security_cloud_entry.get("package_patterns", []))

        self.assertEqual(secure_access_entry["skill"], "cisco-secure-access-setup")
        self.assertEqual(secure_access_entry["app_name"], "cisco-cloud-security")
        self.assertIn(
            "cisco-secure-access-app-for-splunk_*",
            secure_access_entry.get("package_patterns", []),
        )

    def test_security_cloud_smoke_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, secrets_dir, state_file, install_log, curl_log = self.build_mock_cisco_skill_env(tmp_path)

            setup_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/setup.sh",
                "--install",
                "--set-log-level",
                "DEBUG",
                "--no-restart",
                env=env,
            )
            self.assertEqual(setup_result.returncode, 0, msg=setup_result.stdout + setup_result.stderr)
            self.assertIn("Set CiscoSecurityCloud log level to DEBUG.", setup_result.stdout)
            self.assertIn("Installed app: CiscoSecurityCloud", setup_result.stdout)

            xdr_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/configure_product.sh",
                "--product",
                "xdr",
                "--set",
                "region",
                "us",
                "--set",
                "auth_method",
                "client_id",
                "--set",
                "client_id",
                "example-client-id",
                "--set",
                "xdr_import_time_range",
                "7 days ago",
                "--secret-file",
                "refresh_token",
                str(secrets_dir / "xdr_refresh_token"),
                env=env,
            )
            self.assertEqual(xdr_result.returncode, 0, msg=xdr_result.stdout + xdr_result.stderr)
            self.assertIn("Configuring Cisco XDR via xdr", xdr_result.stdout)

            syslog_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/configure_product.sh",
                "--product",
                "secure_firewall_syslog",
                "--set",
                "type",
                "udp",
                "--set",
                "port",
                "514",
                "--set",
                "sourcetype",
                "cisco:sfw:syslog",
                "--set",
                "event_types",
                "connection,security",
                env=env,
            )
            self.assertEqual(syslog_result.returncode, 0, msg=syslog_result.stdout + syslog_result.stderr)
            self.assertIn("Configuring Cisco Secure Firewall Syslog via secure_firewall_syslog", syslog_result.stdout)

            cii_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/configure_product.sh",
                "--product",
                "cii_webhook",
                "--set",
                "cii_client_id",
                "cii-client-id",
                "--set",
                "cii_api_url",
                "https://cii.example/api",
                "--set",
                "cii_token_url",
                "https://cii.example/token",
                "--set",
                "cii_audience",
                "api://cii",
                "--set",
                "integration_method",
                "webhook",
                "--set",
                "hec_url",
                "https://splunk.example:8088",
                "--secret-file",
                "cii_client_secret",
                str(secrets_dir / "cii_client_secret"),
                env=env,
            )
            self.assertEqual(cii_result.returncode, 0, msg=cii_result.stdout + cii_result.stderr)
            self.assertIn("Configuring Cisco Identity Intelligence Webhook via cii_webhook", cii_result.stdout)

            validate_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/validate.sh",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 0, msg=validate_result.stdout + validate_result.stderr)
            self.assertIn("At least one Cisco Security Cloud input is configured", validate_result.stdout)

            validate_xdr_result = self.run_script(
                "skills/cisco-security-cloud-setup/scripts/validate.sh",
                "--product",
                "xdr",
                "--name",
                "XDR_Default",
                env=env,
            )
            self.assertEqual(validate_xdr_result.returncode, 0, msg=validate_xdr_result.stdout + validate_xdr_result.stderr)
            self.assertIn("sbg_xdr_input 'XDR_Default' is configured", validate_xdr_result.stdout)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["security_cloud_settings"]["loglevel"], "DEBUG")
            self.assertIn("cisco_xdr", state["indexes"])
            self.assertIn("cisco_sfw_ftd_syslog", state["indexes"])
            self.assertIn("cisco_cii", state["indexes"])
            self.assertIn("XDR_Default", state["security_cloud_handlers"]["CiscoSecurityCloud_sbg_xdr_input"])
            self.assertIn(
                "SecureFirewall_Syslog_Default",
                state["security_cloud_handlers"]["CiscoSecurityCloud_sbg_sfw_syslog_input"],
            )
            self.assertIn(
                "CII_Webhook_Default",
                state["security_cloud_handlers"]["CiscoSecurityCloud_sbg_cii_input"],
            )

            install_lines = install_log.read_text(encoding="utf-8").splitlines()
            self.assertTrue(
                any("--app-id 7404" in line for line in install_lines),
                msg="Cisco Security Cloud install was not invoked through the shared installer",
            )
            self.assertTrue(curl_log.exists(), msg="Expected mock curl log to be written")

    def test_sc4s_setup_smoke_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4s_env(tmp_path)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "sc4s.token"
            context_file = tmp_path / "splunk_metadata.csv"
            config_file = tmp_path / "app-workaround.conf"

            context_file.write_text("cisco_asa,index,netfw\n", encoding="utf-8")
            config_file.write_text(
                textwrap.dedent(
                    """\
                    application app-postfilter-cisco_asa_metadata[sc4s-postfilter] {
                      parser { app-postfilter-cisco_asa_metadata(); };
                    };
                    """
                ),
                encoding="utf-8",
            )

            setup_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--splunk-prep",
                "--include-metrics-index",
                "--write-hec-token-file",
                str(token_file),
                "--render-host",
                "--render-k8s",
                "--output-dir",
                str(output_dir),
                "--vendor-port",
                "checkpoint:tcp:9000",
                "--context-file",
                f"splunk_metadata.csv={context_file}",
                "--config-file",
                f"app-workaround.conf={config_file}",
                env=env,
            )
            self.assertEqual(setup_result.returncode, 0, msg=setup_result.stdout + setup_result.stderr)
            self.assertTrue(token_file.exists(), msg="Expected the SC4S token file to be written")
            self.assertEqual(token_file.read_text(encoding="utf-8"), "generated-sc4s-token\n")

            host_env = (output_dir / "host" / "env_file").read_text(encoding="utf-8")
            host_compose = (output_dir / "host" / "docker-compose.yml").read_text(encoding="utf-8")
            k8s_values = (output_dir / "k8s" / "values.yaml").read_text(encoding="utf-8")
            k8s_secret = (output_dir / "k8s" / "values.secret.yaml").read_text(encoding="utf-8")

            self.assertIn("SC4S_DEST_SPLUNK_HEC_DEFAULT_URL=https://example.invalid:8088", host_env)
            self.assertIn("SC4S_DEST_SPLUNK_HEC_DEFAULT_TOKEN=generated-sc4s-token", host_env)
            self.assertIn("SC4S_LISTEN_CHECKPOINT_TCP_PORT=9000", host_env)
            self.assertIn("- ./env_file", host_compose)
            self.assertIn("- ./local:/etc/syslog-ng/conf.d/local:z", host_compose)

            self.assertIn('hec_url: "https://example.invalid:8088/services/collector/event"', k8s_values)
            self.assertIn("vendor_product:", k8s_values)
            self.assertIn("name: checkpoint", k8s_values)
            self.assertIn("tcp: [9000]", k8s_values)
            self.assertIn("context_files:", k8s_values)
            self.assertIn("splunk_metadata.csv: |-", k8s_values)
            self.assertIn("cisco_asa,index,netfw", k8s_values)
            self.assertIn("config_files:", k8s_values)
            self.assertIn("app-workaround.conf: |-", k8s_values)
            self.assertIn('hec_token: "generated-sc4s-token"', k8s_secret)

            self.assertTrue((output_dir / "host" / "docker-compose.yml").exists())
            self.assertTrue((output_dir / "host" / "compose-up.sh").exists())
            self.assertTrue((output_dir / "k8s" / "helm-install.sh").exists())

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertIn("netfw", state["indexes"])
            self.assertIn("_metrics", state["indexes"])
            self.assertEqual(state["indexes"]["_metrics"]["datatype"], "metric")
            self.assertIn("sc4s", state["hec_tokens"])

            validate_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4s",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 0, msg=validate_result.stdout + validate_result.stderr)
            self.assertIn("HEC token 'sc4s' exists", validate_result.stdout)
            self.assertIn("SC4S startup event", validate_result.stdout)

    def test_sc4s_validate_reports_wrong_metrics_index_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4s_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["indexes"]["_metrics"] = {"datatype": "event"}
            state["hec_tokens"]["sc4s"] = {
                "disabled": "false",
                "useACK": "0",
                "indexes": "",
                "index": "main",
                "token": "generated-sc4s-token",
            }
            state_file.write_text(json.dumps(state), encoding="utf-8")

            validate_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/validate.sh",
                "--hec-token-name",
                "sc4s",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 1, msg=validate_result.stdout + validate_result.stderr)
            self.assertIn("exists but is an event index", validate_result.stdout)

    def test_sc4s_setup_enables_existing_disabled_hec_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, state_file = self.build_mock_sc4s_env(tmp_path)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["hec_tokens"]["sc4s"] = {
                "disabled": "true",
                "useACK": "0",
                "indexes": "",
                "index": "main",
                "token": "generated-sc4s-token",
            }
            state_file.write_text(json.dumps(state), encoding="utf-8")

            setup_result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--splunk-prep",
                "--hec-only",
                env=env,
            )
            self.assertEqual(setup_result.returncode, 0, msg=setup_result.stdout + setup_result.stderr)
            self.assertIn("exists but is disabled. Enabling it via Splunk REST", setup_result.stdout)
            self.assertIn("Enabled HEC token 'sc4s'.", setup_result.stdout)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["hec_tokens"]["sc4s"]["disabled"], "false")

    def test_sc4s_setup_blocks_custom_in_repo_secret_output_dir(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmpdir:
            tmp_path = Path(tmpdir)
            harness_path = tmp_path / "harness"
            harness_path.mkdir()
            env, state_file = self.build_mock_sc4s_env(harness_path)
            token_file = tmp_path / "sc4s.token"
            token_file.write_text("existing-token\n", encoding="utf-8")

            output_dir = tmp_path / "dangerous-render"
            result = self.run_script(
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                "--render-host",
                "--output-dir",
                str(output_dir),
                "--hec-token-file",
                str(token_file),
                env=env,
            )
            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertIn("Refusing to render secret-bearing SC4S outputs inside the repo", result.stdout + result.stderr)

    def test_gitignore_excludes_default_sc4s_render_output(self):
        gitignore_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/sc4s-rendered/", gitignore_text)

    def test_secure_access_smoke_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, secrets_dir, state_file, install_log, curl_log = self.build_mock_cisco_skill_env(tmp_path)

            setup_result = self.run_script(
                "skills/cisco-secure-access-setup/scripts/setup.sh",
                "--install",
                "--no-restart",
                env=env,
            )
            self.assertEqual(setup_result.returncode, 0, msg=setup_result.stdout + setup_result.stderr)
            self.assertIn("Installed app: cisco-cloud-security", setup_result.stdout)

            account_result = self.run_script(
                "skills/cisco-secure-access-setup/scripts/configure_account.sh",
                "--discover-org-id",
                "--base-url",
                "https://api.us.security.cisco.com",
                "--timezone",
                "UTC",
                "--storage-region",
                "us",
                "--api-key-file",
                str(secrets_dir / "sa_api_key"),
                "--api-secret-file",
                str(secrets_dir / "sa_api_secret"),
                "--investigate-index",
                "cisco_secure_access_investigate",
                "--privateapp-index",
                "cisco_secure_access_private_apps",
                "--appdiscovery-index",
                "cisco_secure_access_app_discovery",
                env=env,
            )
            self.assertEqual(account_result.returncode, 0, msg=account_result.stdout + account_result.stderr)
            self.assertIn("Discovered org ID: org-123", account_result.stdout)
            self.assertIn("Created Cisco Secure Access org account 'org-123'.", account_result.stdout)

            settings_result = self.run_script(
                "skills/cisco-secure-access-setup/scripts/configure_settings.sh",
                "--org-id",
                "org-123",
                "--bootstrap-roles",
                "--accept-terms",
                "--apply-dashboard-defaults",
                "--cloudlock-name",
                "Cloudlock_Default",
                "--cloudlock-url",
                "https://cloudlock.example",
                "--cloudlock-token-file",
                str(secrets_dir / "cloudlock_token"),
                "--cloudlock-start-date",
                "20/03/2026",
                "--cloudlock-incident-details",
                "true",
                "--cloudlock-ueba",
                "false",
                "--destination-list",
                "123",
                "Important list",
                "cs_admin",
                "--dns-index",
                "cisco_secure_access_dns",
                "--proxy-index",
                "cisco_secure_access_proxy",
                "--firewall-index",
                "cisco_secure_access_firewall",
                env=env,
            )
            self.assertEqual(settings_result.returncode, 0, msg=settings_result.stdout + settings_result.stderr)
            self.assertIn("Bootstrapped Cisco Secure Access roles.", settings_result.stdout)
            self.assertIn("Recorded Secure Access terms acceptance", settings_result.stdout)
            self.assertIn("Updated Cisco Secure Access app settings for org 'org-123'.", settings_result.stdout)

            validate_result = self.run_script(
                "skills/cisco-secure-access-setup/scripts/validate.sh",
                "--org-id",
                "org-123",
                env=env,
            )
            self.assertEqual(validate_result.returncode, 0, msg=validate_result.stdout + validate_result.stderr)
            for expected in (
                "Org account 'org-123' exists",
                "Terms acceptance record present",
                "Dashboard search interval configured: 12",
                "Refresh rate configured: 0",
                "Cloudlock settings present: Cloudlock_Default (active)",
                "Selected destination lists configured: 1",
                "S3-backed indexes configured",
            ):
                self.assertIn(expected, validate_result.stdout)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertTrue(state["secure_access"]["roles_bootstrapped"])
            self.assertEqual(
                state["secure_access"]["collections"]["global_org"][0]["orgId"],
                "org-123",
            )
            self.assertEqual(
                state["secure_access"]["collections"]["dashboard_settings"][0]["search_interval"],
                "12",
            )
            self.assertEqual(
                state["secure_access"]["collections"]["refresh_rate"][0]["refresh_rate"],
                "0",
            )
            self.assertEqual(
                state["secure_access"]["collections"]["cloudlock_settings"][0]["configName"],
                "Cloudlock_Default",
            )
            self.assertEqual(
                state["secure_access"]["collections"]["selected_destination_lists"][0]["orgId"],
                "org-123",
            )
            self.assertEqual(
                state["secure_access"]["collections"]["s3_indexes"][0]["dns_index"],
                "cisco_secure_access_dns",
            )

            install_lines = install_log.read_text(encoding="utf-8").splitlines()
            self.assertTrue(
                any("--app-id 5558" in line for line in install_lines),
                msg="Cisco Secure Access install was not invoked through the shared installer",
            )
            self.assertTrue(curl_log.exists(), msg="Expected mock curl log to be written")

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

    def test_stream_app_registry_uses_current_splunkbase_ids(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )
        stream_entries = {
            app["app_name"]: app["splunkbase_id"]
            for app in registry.get("apps", [])
            if app.get("skill") == "splunk-stream-setup"
        }

        self.assertEqual(stream_entries["splunk_app_stream"], "1809")
        self.assertEqual(stream_entries["Splunk_TA_stream"], "5238")
        self.assertEqual(stream_entries["Splunk_TA_stream_wire_data"], "5234")

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

    def test_stream_setup_install_prefers_splunkbase_before_local_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            ta_cache = tmp_path / "splunk-ta"
            ta_cache.mkdir()
            install_log = tmp_path / "install.log"
            credentials_file = tmp_path / "credentials"
            registry_file = tmp_path / "app_registry.json"
            app_install_script = tmp_path / "fake_install_app.sh"

            for filename in (
                "splunk-app-for-stream_816.tgz",
                "splunk-add-on-for-stream-forwarders_816.tgz",
                "splunk-add-on-for-stream-wire-data_816.tgz",
            ):
                (ta_cache / filename).write_text("placeholder", encoding="utf-8")

            registry_file.write_text(
                textwrap.dedent(
                    """\
                    {
                      "apps": [
                        {
                          "skill": "splunk-stream-setup",
                          "app_name": "splunk_app_stream",
                          "splunkbase_id": "1809"
                        },
                        {
                          "skill": "splunk-stream-setup",
                          "app_name": "Splunk_TA_stream",
                          "splunkbase_id": "5238"
                        },
                        {
                          "skill": "splunk-stream-setup",
                          "app_name": "Splunk_TA_stream_wire_data",
                          "splunkbase_id": "5234"
                        }
                      ]
                    }
                    """
                ),
                encoding="utf-8",
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

            write_executable(
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import sys

                args = " ".join(sys.argv[1:])
                if "/services/auth/login" in args and "-d @-" in args:
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                elif "/services/server/info" in args and "%{http_code}" in args:
                    sys.stdout.write("200")
                elif "/services/apps/local/" in args and "%{http_code}" in args:
                    sys.stdout.write("404")
                elif "/services/auth/login" in args and "%{http_code}" in args:
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
            write_executable(
                app_install_script,
                """\
                #!/usr/bin/env bash
                set -euo pipefail
                printf '%s\\n' "$*" >> "${INSTALL_LOG}"
                if [[ "$*" == *"--source splunkbase --app-id 5238"* ]]; then
                    exit 1
                fi
                exit 0
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["TA_CACHE"] = str(ta_cache)
            env["REGISTRY_FILE"] = str(registry_file)
            env["APP_INSTALL_SCRIPT"] = str(app_install_script)
            env["INSTALL_LOG"] = str(install_log)

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/setup.sh",
                "--install",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            install_lines = install_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                install_lines,
                [
                    "--source splunkbase --app-id 1809 --no-update --no-restart",
                    "--source splunkbase --app-id 5238 --no-update --no-restart",
                    f"--source local --file {ta_cache / 'splunk-add-on-for-stream-forwarders_816.tgz'} --no-update --no-restart",
                    "--source splunkbase --app-id 5234 --no-update --no-restart",
                ],
            )

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

    def _build_configure_account_env(self, tmp_path: Path) -> tuple[dict, Path]:
        """Build a mock environment for configure_account.sh integration tests."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        curl_log = tmp_path / "curl.log"
        credentials_file = tmp_path / "credentials"
        password_file = tmp_path / "device_password"

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
        password_file.write_text("device-secret", encoding="utf-8")

        write_executable(
            bin_dir / "nc",
            """\
            #!/usr/bin/env bash
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
            from urllib.parse import parse_qs, urlparse, unquote

            log_path = Path(os.environ["CURL_LOG"])
            args = sys.argv[1:]
            method = "GET"
            data = ""
            url = ""
            write_code = False
            output_target = None

            def log(msg: str) -> None:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(msg + "\\n")

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
                if arg == "-d" and i + 1 < len(args):
                    if args[i + 1] == "@-":
                        data = sys.stdin.read()
                    else:
                        data = args[i + 1]
                    if method == "GET":
                        method = "POST"
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

            parsed = urlparse(url)
            path = parsed.path
            log(f"URL={url} METHOD={method} DATA={data!r}")

            if "/services/auth/login" in path:
                out("<response><sessionKey>test-session</sessionKey></response>")

            # Account creation handlers — accept any POST
            if ("_account" in path or "_settings" in path) and method == "POST":
                log(f"CONF_POST path={path} data={data!r}")
                out("", 200)

            out("", 200)
            """,
        )

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["CURL_LOG"] = str(curl_log)
        env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
        env["SPLUNK_PLATFORM"] = "enterprise"

        return env, curl_log

    def test_catalyst_configure_account_no_verify_ssl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, curl_log = self._build_configure_account_env(tmp_path)
            password_file = tmp_path / "device_password"

            result = self.run_script(
                "skills/cisco-catalyst-ta-setup/scripts/configure_account.sh",
                "--type", "catalyst_center",
                "--name", "TestDNAC",
                "--host", "https://10.100.0.60",
                "--username", "admin",
                "--password-file", str(password_file),
                "--no-verify-ssl",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("verify_ssl=False", result.stdout)
            self.assertIn("ta_cisco_catalyst_settings", result.stdout)

            log_text = curl_log.read_text(encoding="utf-8")
            settings_posts = [
                line for line in log_text.splitlines()
                if "CONF_POST" in line and "ta_cisco_catalyst_settings" in line
            ]
            self.assertTrue(
                len(settings_posts) > 0,
                msg="Expected a POST to ta_cisco_catalyst_settings conf",
            )
            self.assertTrue(
                any("verify_ssl" in line and "False" in line for line in settings_posts),
                msg=f"Expected verify_ssl=False in settings POST, got: {settings_posts}",
            )

    def test_dc_networking_configure_account_no_verify_ssl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, curl_log = self._build_configure_account_env(tmp_path)
            password_file = tmp_path / "device_password"

            result = self.run_script(
                "skills/cisco-dc-networking-setup/scripts/configure_account.sh",
                "--type", "aci",
                "--name", "TestACI",
                "--hostname", "10.0.0.1",
                "--username", "admin",
                "--password-file", str(password_file),
                "--no-verify-ssl",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("verify_ssl=False", result.stdout)
            self.assertIn("cisco_dc_networking_app_for_splunk_settings", result.stdout)

            log_text = curl_log.read_text(encoding="utf-8")
            settings_posts = [
                line for line in log_text.splitlines()
                if "CONF_POST" in line and "cisco_dc_networking_app_for_splunk_settings" in line
            ]
            self.assertTrue(
                len(settings_posts) > 0,
                msg="Expected a POST to cisco_dc_networking_app_for_splunk_settings conf",
            )
            self.assertTrue(
                any("verify_ssl" in line and "False" in line for line in settings_posts),
                msg=f"Expected verify_ssl=False in settings POST, got: {settings_posts}",
            )

    def test_catalyst_configure_account_without_ssl_flag_skips_setting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, curl_log = self._build_configure_account_env(tmp_path)
            password_file = tmp_path / "device_password"

            result = self.run_script(
                "skills/cisco-catalyst-ta-setup/scripts/configure_account.sh",
                "--type", "catalyst_center",
                "--name", "TestDNAC",
                "--host", "https://10.100.0.60",
                "--username", "admin",
                "--password-file", str(password_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertNotIn("verify_ssl", result.stdout)

            log_text = curl_log.read_text(encoding="utf-8")
            settings_posts = [
                line for line in log_text.splitlines()
                if "CONF_POST" in line and "ta_cisco_catalyst_settings" in line
            ]
            self.assertEqual(
                len(settings_posts), 0,
                msg="Should not POST to settings conf when --no-verify-ssl is not passed",
            )


if __name__ == "__main__":
    unittest.main()
