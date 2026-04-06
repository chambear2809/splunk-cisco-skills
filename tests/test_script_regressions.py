#!/usr/bin/env python3
"""Regression tests for first-party shell entrypoints."""

import json
import hashlib
import os
import re
import stat
import subprocess
import tarfile
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def sha512_hex(text: str) -> str:
    return hashlib.sha512(text.encode("utf-8")).hexdigest()


def write_mock_curl(path: Path) -> None:
    write_executable(
        path,
        """\
        #!/usr/bin/env python3
        import json
        import os
        import sys
        from pathlib import Path

        state = json.loads(Path(os.environ["MOCK_CURL_STATE"]).read_text(encoding="utf-8"))
        args = sys.argv[1:]
        output_target = None
        url = ""
        i = 0
        while i < len(args):
            if args[i] == "-o" and i + 1 < len(args):
                output_target = args[i + 1]
                i += 2
                continue
            if args[i].startswith("http://") or args[i].startswith("https://"):
                url = args[i]
            i += 1

        log_path = os.environ.get("CURL_LOG")
        if log_path:
            with Path(log_path).open("a", encoding="utf-8") as handle:
                handle.write(url + "\\n")

        if url in state.get("fail", []):
            raise SystemExit(1)

        if output_target is not None and url in state.get("files", {}):
            Path(output_target).write_text(state["files"][url], encoding="utf-8")
            raise SystemExit(0)

        if url in state.get("text", {}):
            sys.stdout.write(state["text"][url])
            raise SystemExit(0)

        raise SystemExit(1)
        """,
    )


class ShellScriptRegressionTests(unittest.TestCase):
    def run_script(
        self,
        script_rel_path: str,
        *args: str,
        env: dict,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(REPO_ROOT / script_rel_path), *args],
            cwd=REPO_ROOT,
            env=env,
            input=input_text,
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

    def _build_mock_install_env(
        self,
        tmp_path: Path,
        *,
        app_name: str,
        app_version: str,
        target_role: str,
    ) -> dict:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        credentials_file = tmp_path / "credentials"

        credentials_file.write_text(
            textwrap.dedent(
                f"""\
                SPLUNK_PLATFORM="enterprise"
                SPLUNK_TARGET_ROLE="{target_role}"
                SPLUNK_SEARCH_API_URI="https://localhost:8089"
                SPLUNK_URI="${{SPLUNK_SEARCH_API_URI}}"
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
            from urllib.parse import urlparse

            app_name = os.environ["MOCK_INSTALL_APP_NAME"]
            app_version = os.environ["MOCK_INSTALL_APP_VERSION"]
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
                out(json.dumps({"entry": [{"name": app_name}]}), 201)

            if f"/services/apps/local/{app_name}" in path:
                if output_target == "/dev/null" and write_code:
                    out(code=200)
                out(json.dumps({"entry": [{"name": app_name, "content": {"version": app_version}}]}))

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
        env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
        env["MOCK_INSTALL_APP_NAME"] = app_name
        env["MOCK_INSTALL_APP_VERSION"] = app_version
        return env

    def _build_mock_stream_validate_env(
        self,
        tmp_path: Path,
        *,
        target_role: str | None = None,
        state: dict,
        credentials_text: str | None = None,
        acs_search_head: str | None = None,
    ) -> dict:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        state_file = tmp_path / "stream_state.json"
        credentials_file = tmp_path / "credentials"

        state_file.write_text(json.dumps(state), encoding="utf-8")
        if credentials_text is None:
            credentials_text = textwrap.dedent(
                f"""\
                SPLUNK_PLATFORM="enterprise"
                SPLUNK_TARGET_ROLE="{target_role}"
                SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
                SPLUNK_URI="${{SPLUNK_SEARCH_API_URI}}"
                SPLUNK_USER="user"
                SPLUNK_PASS="pass"
                """
            )
        credentials_file.write_text(credentials_text, encoding="utf-8")

        write_executable(
            bin_dir / "curl",
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path
            from urllib.parse import parse_qs, unquote, urlparse

            state_path = Path(os.environ["STREAM_STATE"])
            state = json.loads(state_path.read_text(encoding="utf-8"))

            args = sys.argv[1:]
            method = "GET"
            data = ""
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

            if "/services/apps/local/" in path:
                app = unquote(path.split("/services/apps/local/", 1)[1]).split("/", 1)[0]
                installed = state.get("apps", {}).get(app)
                if output_target == "/dev/null" and write_code:
                    out(code=200 if installed else 404)
                if installed:
                    out(json.dumps({"entry": [{"name": app, "content": {"version": installed.get("version", "unknown")}}]}))
                out(json.dumps({"entry": []}))

            if "/services/data/indexes/" in path:
                idx = path.rsplit("/", 1)[-1]
                exists = idx in state.get("indexes", [])
                if output_target == "/dev/null" and write_code:
                    out(code=200 if exists else 404)
                if exists:
                    out(json.dumps({"entry": [{"name": idx}]}))
                out(json.dumps({"entry": []}))

            if "/servicesNS/nobody/Splunk_TA_stream/configs/conf-" in path:
                conf = path.split("/configs/conf-", 1)[1].split("/", 1)[0]
                stanza = unquote(path.rsplit("/", 1)[-1].split("?", 1)[0])
                content = state.get("configs", {}).get(f"{conf}:{stanza}")
                if output_target == "/dev/null" and write_code:
                    out(code=200 if content else 404)
                if content:
                    out(json.dumps({"entry": [{"content": content}]}))
                out(json.dumps({"entry": []}))

            if path.endswith("/services/search/jobs") and method == "POST":
                body = decode_form(data)
                search = body.get("search", "")
                counts = state.get("counts", {})
                if "source=stream" in search:
                    count = counts.get("source=stream", 0)
                elif "index=netflow" in search:
                    count = counts.get("index=netflow", 0)
                else:
                    count = 0
                out(json.dumps({"results": [{"count": str(count)}]}))

            if path.endswith("/services/kvstore/status"):
                out(
                    json.dumps(
                        {
                            "entry": [
                                {
                                    "content": {
                                        "current": {
                                            "status": state.get("kvstore_status", "ready")
                                        }
                                    }
                                }
                            ]
                        }
                    )
                )

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
        if acs_search_head is not None:
            write_executable(
                bin_dir / "acs",
                f"""\
                #!/usr/bin/env python3
                import sys

                if " ".join(sys.argv[1:]) == "config current-stack":
                    print("Current Search Head: {acs_search_head}")
                    raise SystemExit(0)

                raise SystemExit(0)
                """,
            )

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
        env["STREAM_STATE"] = str(state_file)
        return env

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

    def test_app_registry_declares_deployment_roles_and_complete_role_support(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        expected_roles = [
            "search-tier",
            "indexer",
            "heavy-forwarder",
            "universal-forwarder",
            "external-collector",
        ]
        allowed_values = {"required", "supported", "none"}

        self.assertEqual(registry.get("deployment_roles"), expected_roles)

        for app in registry.get("apps", []):
            with self.subTest(app=app.get("app_name")):
                role_support = app.get("role_support")
                self.assertIsInstance(role_support, dict)
                self.assertEqual(sorted(role_support.keys()), sorted(expected_roles))
                self.assertTrue(set(role_support.values()).issubset(allowed_values))

    def test_app_registry_declares_capabilities_for_every_app(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        expected_capabilities = {
            "needs_custom_rest",
            "needs_search_time_objects",
            "needs_kvstore",
            "needs_python_runtime",
            "needs_packet_capture",
            "uf_safe",
        }

        apps_by_id = {
            app["splunkbase_id"]: app
            for app in registry.get("apps", [])
        }

        for app in registry.get("apps", []):
            with self.subTest(app=app.get("app_name")):
                capabilities = app.get("capabilities")
                self.assertIsInstance(capabilities, dict)
                self.assertEqual(set(capabilities.keys()), expected_capabilities)
                self.assertTrue(all(isinstance(value, bool) for value in capabilities.values()))

        self.assertEqual(
            apps_by_id["7538"]["capabilities"],
            {
                "needs_custom_rest": True,
                "needs_search_time_objects": False,
                "needs_kvstore": False,
                "needs_python_runtime": True,
                "needs_packet_capture": False,
                "uf_safe": False,
            },
        )
        self.assertEqual(
            apps_by_id["5238"]["capabilities"],
            {
                "needs_custom_rest": False,
                "needs_search_time_objects": False,
                "needs_kvstore": False,
                "needs_python_runtime": False,
                "needs_packet_capture": True,
                "uf_safe": True,
            },
        )
        self.assertEqual(
            apps_by_id["5234"]["capabilities"],
            {
                "needs_custom_rest": False,
                "needs_search_time_objects": True,
                "needs_kvstore": False,
                "needs_python_runtime": False,
                "needs_packet_capture": False,
                "uf_safe": False,
            },
        )

    def test_skill_topologies_cover_registry_skills_and_special_cases(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        expected_roles = set(registry["deployment_roles"])
        allowed_values = {"required", "supported", "none"}
        skill_topologies = {
            entry["skill"]: entry
            for entry in registry.get("skill_topologies", [])
        }

        for app_skill in {app["skill"] for app in registry.get("apps", [])}:
            self.assertIn(app_skill, skill_topologies)

        self.assertIn("cisco-product-setup", skill_topologies)
        self.assertIn("splunk-connect-for-syslog-setup", skill_topologies)
        self.assertIn("splunk-app-install", skill_topologies)

        for skill, topology in skill_topologies.items():
            with self.subTest(skill=skill):
                role_support = topology.get("role_support")
                self.assertIsInstance(role_support, dict)
                self.assertEqual(set(role_support.keys()), expected_roles)
                self.assertTrue(set(role_support.values()).issubset(allowed_values))
                self.assertTrue(set(topology.get("cloud_pairing", [])).issubset(expected_roles))

        sc4s = skill_topologies["splunk-connect-for-syslog-setup"]
        self.assertEqual(sc4s["role_support"]["external-collector"], "required")

    def test_stream_role_topology_matches_split_package_model(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        stream_topology = next(
            entry
            for entry in registry.get("skill_topologies", [])
            if entry.get("skill") == "splunk-stream-setup"
        )
        self.assertEqual(
            stream_topology["role_support"],
            {
                "search-tier": "required",
                "indexer": "supported",
                "heavy-forwarder": "required",
                "universal-forwarder": "supported",
                "external-collector": "none",
            },
        )
        self.assertEqual(
            stream_topology["cloud_pairing"],
            ["heavy-forwarder", "universal-forwarder"],
        )

        stream_apps = {
            app["app_name"]: app["role_support"]
            for app in registry.get("apps", [])
            if app.get("skill") == "splunk-stream-setup"
        }
        self.assertEqual(
            stream_apps["splunk_app_stream"],
            {
                "search-tier": "required",
                "indexer": "none",
                "heavy-forwarder": "none",
                "universal-forwarder": "none",
                "external-collector": "none",
            },
        )
        self.assertEqual(
            stream_apps["Splunk_TA_stream"],
            {
                "search-tier": "none",
                "indexer": "none",
                "heavy-forwarder": "required",
                "universal-forwarder": "supported",
                "external-collector": "none",
            },
        )
        self.assertEqual(
            stream_apps["Splunk_TA_stream_wire_data"],
            {
                "search-tier": "supported",
                "indexer": "required",
                "heavy-forwarder": "supported",
                "universal-forwarder": "none",
                "external-collector": "none",
            },
        )

    def test_role_matrix_keeps_search_tier_only_and_collector_defaults_explicit(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        entries_by_id = {
            app["splunkbase_id"]: app
            for app in registry.get("apps", [])
        }
        self.assertEqual(
            entries_by_id["7539"]["role_support"],
            {
                "search-tier": "required",
                "indexer": "none",
                "heavy-forwarder": "none",
                "universal-forwarder": "none",
                "external-collector": "none",
            },
        )

        collector_ids = ["7538", "7777", "7404", "5558", "7828", "3471", "5580", "7719"]
        for app_id in collector_ids:
            with self.subTest(app_id=app_id):
                role_support = entries_by_id[app_id]["role_support"]
                self.assertEqual(role_support["search-tier"], "supported")
                self.assertEqual(role_support["heavy-forwarder"], "supported")
                self.assertEqual(role_support["indexer"], "none")
                self.assertEqual(role_support["universal-forwarder"], "none")

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

    def test_stream_validate_search_tier_downgrades_forwarder_checks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = self._build_mock_stream_validate_env(
                tmp_path,
                target_role="search-tier",
                state={
                    "apps": {
                        "splunk_app_stream": {"version": "8.1.6"},
                    },
                    "indexes": [],
                    "configs": {},
                    "counts": {"source=stream": 0, "index=netflow": 0},
                    "kvstore_status": "ready",
                },
            )

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/validate.sh",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Splunk TA Stream (Forwarder) is not installed on this search-tier target", result.stdout)
            self.assertIn("Forwarder-side streamfwd validation is skipped on the search tier", result.stdout)
            self.assertNotIn("FAIL: Splunk TA Stream (Forwarder) not installed", result.stdout)
            self.assertNotIn("FAIL: streamfwd.conf stanza not found", result.stdout)

    def test_stream_validate_heavy_forwarder_downgrades_search_tier_app_requirement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = self._build_mock_stream_validate_env(
                tmp_path,
                target_role="heavy-forwarder",
                state={
                    "apps": {
                        "Splunk_TA_stream": {"version": "8.1.6"},
                    },
                    "indexes": [],
                    "configs": {
                        "streamfwd:streamfwd": {
                            "ipAddr": "10.1.1.10",
                            "port": "8889",
                            "netflowReceiver.0.port": "9995",
                        },
                        "inputs:streamfwd://streamfwd": {
                            "splunk_stream_app_location": "https://stream.example/en-us/custom/splunk_app_stream/",
                            "sslVerifyServerCert": "false",
                            "disabled": "0",
                        },
                    },
                    "counts": {"source=stream": 0, "index=netflow": 0},
                    "kvstore_status": "ready",
                },
            )

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/validate.sh",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Splunk Stream search-tier app is not installed on this forwarder target", result.stdout)
            self.assertIn("streamfwd.conf stanza exists", result.stdout)
            self.assertIn("KV Store check skipped on heavy-forwarder", result.stdout)
            self.assertNotIn("FAIL: Splunk Stream not installed", result.stdout)

    def test_stream_validate_indexer_focuses_on_wire_data_requirements(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = self._build_mock_stream_validate_env(
                tmp_path,
                target_role="indexer",
                state={
                    "apps": {
                        "Splunk_TA_stream_wire_data": {"version": "8.1.6"},
                    },
                    "indexes": [],
                    "configs": {},
                    "counts": {"source=stream": 0, "index=netflow": 0},
                    "kvstore_status": "ready",
                },
            )

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/validate.sh",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Splunk TA Stream Wire Data installed", result.stdout)
            self.assertIn("Splunk TA Stream (Forwarder) is not installed on this indexer target", result.stdout)
            self.assertIn("Forwarder-side streamfwd validation is skipped on the indexer tier", result.stdout)
            self.assertIn("KV Store check skipped on indexer", result.stdout)
            self.assertNotIn("FAIL: Splunk TA Stream (Forwarder) not installed", result.stdout)

    def test_stream_validate_hybrid_cloud_profile_stays_search_tier_focused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = self._build_mock_stream_validate_env(
                tmp_path,
                state={
                    "apps": {
                        "splunk_app_stream": {"version": "8.1.6"},
                    },
                    "indexes": [],
                    "configs": {},
                    "counts": {"source=stream": 0, "index=netflow": 0},
                    "kvstore_status": "ready",
                },
                credentials_text=textwrap.dedent(
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
                acs_search_head="shc1",
            )

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/validate.sh",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Splunk TA Stream (Forwarder) is not installed on this search-tier target", result.stdout)
            self.assertIn("Forwarder-side streamfwd validation is skipped on the search tier", result.stdout)
            self.assertNotIn("search-tier app is not installed on this forwarder target", result.stdout)
            self.assertNotIn("KV Store check skipped on heavy-forwarder", result.stdout)

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

    def test_configure_streams_help_does_not_require_profile_selection(self):
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
                "skills/splunk-stream-setup/scripts/configure_streams.sh",
                "--help",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("Usage:", result.stdout)
            self.assertNotIn("Multiple credential profiles are defined", output)

    def test_configure_streams_rejects_forwarder_roles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
                    SPLUNK_USER="user"
                    SPLUNK_PASS="pass"
                    SPLUNK_TARGET_ROLE="heavy-forwarder"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/configure_streams.sh",
                "--list",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, msg=output)
            self.assertIn("search-tier only", output)
            self.assertIn("heavy-forwarder", output)
            self.assertNotIn("Could not authenticate", output)

    def test_configure_streams_uses_refreshed_cloud_stream_web_uri(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_PROFILE="cloud"
                    SPLUNK_SEARCH_PROFILE="hf"
                    PROFILE_cloud__SPLUNK_PLATFORM="cloud"
                    PROFILE_cloud__SPLUNK_CLOUD_STACK="stack"
                    PROFILE_cloud__SPLUNK_CLOUD_SEARCH_HEAD="shc1"
                    PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"
                    PROFILE_cloud__STACK_TOKEN="token"
                    PROFILE_cloud__SPLUNK_USER="cloud-user"
                    PROFILE_cloud__SPLUNK_PASS="cloud-pass"
                    PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
                    PROFILE_hf__SPLUNK_PLATFORM="enterprise"
                    PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
                    PROFILE_hf__SPLUNK_USER="hf-user"
                    PROFILE_hf__SPLUNK_PASS="hf-pass"
                    PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
                    """
                ),
                encoding="utf-8",
            )

            write_executable(
                bin_dir / "acs",
                """\
                #!/usr/bin/env python3
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
                bin_dir / "curl",
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                log_path = Path(os.environ["CURL_LOG"])
                args = sys.argv[1:]
                url = next((arg for arg in args if arg.startswith("http://") or arg.startswith("https://")), "")
                joined = " ".join(args)

                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

                if "/services/auth/login" in url and "-d" in args:
                    sys.stdout.write("<response><sessionKey>test-session</sessionKey></response>")
                    raise SystemExit(0)

                if "/servicesNS/nobody/splunk_app_stream/storage/collections/data/streams" in url and "%{http_code}" in joined:
                    sys.stdout.write("\\n404")
                    raise SystemExit(0)

                if "/en-US/custom/splunk_app_stream/streams" in url and "%{http_code}" in joined:
                    sys.stdout.write('{"streams":[{"id":"dns","enabled":true,"index":"stream"}]}\\n200')
                    raise SystemExit(0)

                if "/services/auth/login" in url and "%{http_code}" in joined:
                    sys.stdout.write("200")
                    raise SystemExit(0)

                if "/services/server/info" in url and "%{http_code}" in joined:
                    sys.stdout.write("200")
                    raise SystemExit(0)

                raise SystemExit(0)
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            env["CURL_LOG"] = str(curl_log)
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
            env["SPLUNK_SKIP_ALLOWLIST"] = "true"

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/configure_streams.sh",
                "--list",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)
            self.assertIn("dns", output)

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn(
                "https://shc1.stack.stg.splunkcloud.com:443/en-US/custom/splunk_app_stream/streams?output_mode=json",
                curl_requests,
            )
            self.assertNotIn(
                "https://hf.example.com:443/en-US/custom/splunk_app_stream/streams?output_mode=json",
                curl_requests,
            )

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

    def test_stream_setup_install_scopes_packages_to_declared_search_tier_role(self):
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
                          "splunkbase_id": "1809",
                          "role_support": {
                            "search-tier": "required",
                            "indexer": "none",
                            "heavy-forwarder": "none",
                            "universal-forwarder": "none",
                            "external-collector": "none"
                          }
                        },
                        {
                          "skill": "splunk-stream-setup",
                          "app_name": "Splunk_TA_stream",
                          "splunkbase_id": "5238",
                          "role_support": {
                            "search-tier": "none",
                            "indexer": "none",
                            "heavy-forwarder": "required",
                            "universal-forwarder": "supported",
                            "external-collector": "none"
                          }
                        },
                        {
                          "skill": "splunk-stream-setup",
                          "app_name": "Splunk_TA_stream_wire_data",
                          "splunkbase_id": "5234",
                          "role_support": {
                            "search-tier": "supported",
                            "indexer": "required",
                            "heavy-forwarder": "supported",
                            "universal-forwarder": "none",
                            "external-collector": "none"
                          }
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
                    SPLUNK_TARGET_ROLE="search-tier"
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
            self.assertIn("Active deployment role: search-tier", result.stdout)

            install_lines = install_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                install_lines,
                [
                    "--source splunkbase --app-id 1809 --no-update --no-restart",
                    "--source splunkbase --app-id 5234 --no-update --no-restart",
                ],
            )

    def test_stream_setup_full_setup_requires_split_phases_on_role_scoped_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"

            credentials_file.write_text(
                textwrap.dedent(
                    """\
                    SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
                    SPLUNK_TARGET_ROLE="search-tier"
                    """
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-stream-setup/scripts/setup.sh",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, msg=output)
            self.assertIn("Full Stream setup spans multiple runtime roles", output)

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

    def test_sanitize_response_reads_bodies_from_stdin_instead_of_process_args(self):
        script_text = (REPO_ROOT / "skills/shared/lib/rest_helpers.sh").read_text(encoding="utf-8")

        self.assertIn('3<<<"${resp}"', script_text)
        self.assertIn("os.fdopen(3", script_text)
        self.assertNotIn('python3 - "${max_lines}" "${resp}"', script_text)
        self.assertNotIn("text = sys.argv[2]", script_text)

    def test_splunk_mcp_setup_passes_response_body_directly_to_sanitize_response(self):
        script_text = (
            REPO_ROOT / "skills/splunk-mcp-server-setup/scripts/setup.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('sanitize_response "${body}" 10 >&2', script_text)
        self.assertNotIn('printf \'%s\\n\' "${body}" | sanitize_response 10 >&2', script_text)

    def test_splunk_mcp_validate_normalizes_boolean_expectations(self):
        script_text = (
            REPO_ROOT / "skills/splunk-mcp-server-setup/scripts/validate.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("normalize_boolean_if_possible()", script_text)
        self.assertIn(
            'SERVER_REQUIRE_ENCRYPTED_TOKEN_NORMALIZED="$(normalize_boolean_if_possible "${SERVER_REQUIRE_ENCRYPTED_TOKEN}")"',
            script_text,
        )
        self.assertIn(
            'assert_equal "require_encrypted_token" "${EXPECT_REQUIRE_ENCRYPTED_TOKEN}" "${SERVER_REQUIRE_ENCRYPTED_TOKEN_NORMALIZED}"',
            script_text,
        )

    def test_splunk_mcp_rendered_client_name_is_json_and_shell_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            output_dir = tmp_path / "rendered"
            codex_log = tmp_path / "codex-log.json"
            marker_path = tmp_path / "client-name-marker"
            client_name = f'bad"name$(touch {marker_path})'

            write_executable(
                bin_dir / "codex",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                Path(os.environ["CODEX_LOG"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["CODEX_LOG"] = str(codex_log)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example:8089/services/mcp",
                "--output-dir",
                str(output_dir),
                "--client-name",
                client_name,
                "--no-register-codex",
                "--no-configure-cursor",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)

            rendered_config = json.loads((output_dir / ".cursor/mcp.json").read_text(encoding="utf-8"))
            self.assertIn(client_name, rendered_config["mcpServers"])
            self.assertEqual(
                rendered_config["mcpServers"][client_name]["command"],
                "${workspaceFolder}/run-splunk-mcp.sh",
            )

            register_result = subprocess.run(
                ["bash", str(output_dir / "register-codex-mcp.sh")],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                register_result.returncode,
                0,
                msg=register_result.stdout + register_result.stderr,
            )
            self.assertFalse(marker_path.exists(), "client-name command substitution should not execute")

            codex_args = json.loads(codex_log.read_text(encoding="utf-8"))
            self.assertEqual(codex_args[:3], ["mcp", "add", client_name])
            self.assertEqual(codex_args[3], "--")
            self.assertEqual(codex_args[4], str(output_dir / "run-splunk-mcp.sh"))

    def test_splunk_mcp_rendered_env_file_is_shell_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "splunk.token"
            mcp_remote_log = tmp_path / "mcp-remote-log.json"
            url_marker = tmp_path / "url-marker"
            token_marker = tmp_path / "token-marker"
            mcp_url = f"https://splunk.example:8089/services/mcp?target=$(touch {url_marker})"
            token_value = f"token$(touch {token_marker})"

            token_file.write_text(token_value, encoding="utf-8")
            token_file.chmod(0o600)

            write_executable(
                bin_dir / "mcp-remote",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                Path(os.environ["MCP_REMOTE_LOG"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["MCP_REMOTE_LOG"] = str(mcp_remote_log)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                mcp_url,
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--no-register-codex",
                "--no-configure-cursor",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)

            wrapper_result = subprocess.run(
                ["bash", str(output_dir / "run-splunk-mcp.sh")],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                wrapper_result.returncode,
                0,
                msg=wrapper_result.stdout + wrapper_result.stderr,
            )
            self.assertFalse(url_marker.exists(), "MCP URL command substitution should not execute")
            self.assertFalse(token_marker.exists(), "token command substitution should not execute")

            mcp_remote_args = json.loads(mcp_remote_log.read_text(encoding="utf-8"))
            self.assertEqual(mcp_remote_args[0], mcp_url)
            self.assertEqual(
                mcp_remote_args[1:3],
                ["--header", f"Authorization: Bearer {token_value}"],
            )

    def test_splunk_mcp_validate_uses_root_protected_resource_endpoint(self):
        script_text = (
            REPO_ROOT / "skills/splunk-mcp-server-setup/scripts/validate.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('/.well-known/oauth-protected-resource', script_text)
        self.assertNotIn('/services/.well-known/oauth-protected-resource', script_text)

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

    def test_mcp_setup_merges_existing_cursor_workspace_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home_dir = tmp_path / "home"
            workspace_dir = tmp_path / "cursor-workspace"
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "splunk.token"
            cursor_dir = workspace_dir / ".cursor"
            cursor_dir.mkdir(parents=True)
            home_dir.mkdir()

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)
            (cursor_dir / "mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "existing": {
                                "type": "stdio",
                                "command": "/bin/echo",
                                "args": ["hello"],
                            }
                        },
                        "notes": {"keep": True},
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["HOME"] = str(home_dir)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--cursor-workspace",
                str(workspace_dir),
                "--client-name",
                "splunk-merge",
                "--no-register-codex",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            workspace_json = json.loads((cursor_dir / "mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(workspace_json["notes"], {"keep": True})
            self.assertEqual(workspace_json["mcpServers"]["existing"]["command"], "/bin/echo")
            self.assertEqual(
                Path(workspace_json["mcpServers"]["splunk-merge"]["command"]).resolve(),
                (output_dir / "run-splunk-mcp.sh").resolve(),
            )
            self.assertEqual(workspace_json["mcpServers"]["splunk-merge"]["args"], [])
            self.assertEqual(workspace_json["mcpServers"]["splunk-merge"]["type"], "stdio")

    def test_mcp_setup_uses_workspace_relative_cursor_command_when_bundle_is_inside_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home_dir = tmp_path / "home"
            workspace_dir = tmp_path / "cursor-workspace"
            output_dir = workspace_dir / "rendered"
            token_file = tmp_path / "splunk.token"
            home_dir.mkdir()
            workspace_dir.mkdir()

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)

            env = os.environ.copy()
            env["HOME"] = str(home_dir)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--cursor-workspace",
                str(workspace_dir),
                "--client-name",
                "splunk-relative",
                "--no-register-codex",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            workspace_json = json.loads((workspace_dir / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(
                workspace_json["mcpServers"]["splunk-relative"]["command"],
                "${workspaceFolder}/rendered/run-splunk-mcp.sh",
            )
            self.assertEqual(workspace_json["mcpServers"]["splunk-relative"]["args"], [])
            self.assertEqual(workspace_json["mcpServers"]["splunk-relative"]["type"], "stdio")

    def test_mcp_setup_rejects_invalid_cursor_workspace_config_after_render(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home_dir = tmp_path / "home"
            workspace_dir = tmp_path / "cursor-workspace"
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "splunk.token"
            cursor_dir = workspace_dir / ".cursor"
            cursor_dir.mkdir(parents=True)
            home_dir.mkdir()

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)
            (cursor_dir / "mcp.json").write_text("{invalid json\n", encoding="utf-8")

            env = os.environ.copy()
            env["HOME"] = str(home_dir)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--cursor-workspace",
                str(workspace_dir),
                "--client-name",
                "splunk-invalid-cursor",
                "--no-register-codex",
                env=env,
            )

            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertIn("not valid JSON", result.stdout + result.stderr)
            self.assertTrue((output_dir / "run-splunk-mcp.sh").exists())
            self.assertTrue((output_dir / ".cursor" / "mcp.json").exists())

    def test_mcp_setup_defaults_cursor_workspace_to_current_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home_dir = tmp_path / "home"
            workspace_dir = tmp_path / "cursor-workspace"
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "splunk.token"
            home_dir.mkdir()
            workspace_dir.mkdir()

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)

            env = os.environ.copy()
            env["HOME"] = str(home_dir)

            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "skills/splunk-mcp-server-setup/scripts/setup.sh"),
                    "--render-clients",
                    "--mcp-url",
                    "https://splunk.example.invalid:8089/services/mcp",
                    "--bearer-token-file",
                    str(token_file),
                    "--output-dir",
                    str(output_dir),
                    "--client-name",
                    "splunk-default-workspace",
                    "--no-register-codex",
                ],
                cwd=workspace_dir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            workspace_json = json.loads((workspace_dir / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(
                Path(workspace_json["mcpServers"]["splunk-default-workspace"]["command"]).resolve(),
                (output_dir / "run-splunk-mcp.sh").resolve(),
            )

    def test_mcp_setup_repeated_runs_update_codex_registration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home_dir = tmp_path / "home"
            output_dir_one = tmp_path / "rendered-one"
            output_dir_two = tmp_path / "rendered-two"
            token_file = tmp_path / "splunk.token"
            home_dir.mkdir()

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)

            env = os.environ.copy()
            env["HOME"] = str(home_dir)

            first = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir_one),
                "--client-name",
                "splunk-repeat",
                "--no-configure-cursor",
                env=env,
            )
            self.assertEqual(first.returncode, 0, msg=first.stdout + first.stderr)

            second = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir_two),
                "--client-name",
                "splunk-repeat",
                "--no-configure-cursor",
                env=env,
            )
            self.assertEqual(second.returncode, 0, msg=second.stdout + second.stderr)

            registered = subprocess.run(
                ["codex", "mcp", "get", "splunk-repeat", "--json"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(registered.returncode, 0, msg=registered.stdout + registered.stderr)

            data = json.loads(registered.stdout)
            self.assertEqual(data["transport"]["type"], "stdio")
            self.assertEqual(
                Path(data["transport"]["command"]).resolve(),
                (output_dir_two / "run-splunk-mcp.sh").resolve(),
            )
            self.assertEqual(data["transport"]["args"], [])

    def test_repo_cursor_config_tracks_workspace_relative_rendered_bundle(self):
        config = json.loads((REPO_ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))

        self.assertEqual(
            config,
            {
                "mcpServers": {
                    "splunk-mcp": {
                        "type": "stdio",
                        "command": "${workspaceFolder}/splunk-mcp-rendered/run-splunk-mcp.sh",
                        "args": [],
                    }
                }
            },
        )

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
                "--execution", "local",
                "--host-bootstrap-role", "standalone-search-tier",
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--admin-password-file", str(password_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://localhost:8089/services/auth/login", curl_requests)
            self.assertIn("https://localhost:8089/services/server/info?output_mode=json", curl_requests)
            self.assertNotIn("wrong.example.com", curl_requests)

    def test_host_bootstrap_validate_heavy_forwarder_accepts_server_list_without_mode_flag(self):
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
                "--execution", "local",
                "--host-bootstrap-role", "heavy-forwarder",
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--admin-password-file", str(password_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("outputs.conf uses a static server list", result.stdout)

    def test_host_bootstrap_setup_requires_current_shc_member_for_existing_cluster(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            credentials_file = tmp_path / "credentials"
            credentials_file.write_text("", encoding="utf-8")
            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)

            result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                "--phase", "cluster",
                "--execution", "local",
                "--deployment-mode", "clustered",
                "--host-bootstrap-role", "shc-member",
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
                "--phase", "cluster",
                "--execution", "local",
                "--deployment-mode", "clustered",
                "--host-bootstrap-role", "shc-member",
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--admin-password-file", str(password_file),
                "--shc-secret-file", str(shc_secret_file),
                "--deployer-uri", "https://deployer.example.com:8089",
                "--current-shc-member-uri", "https://sh1.example.com:8089",
                "--advertise-host", "sh2.example.com",
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
                "--phase", "install",
                "--execution", "local",
                "--host-bootstrap-role", "standalone-search-tier",
                "--source", "local",
                "--file", str(package_file),
                "--package-type", "auto",
                "--splunk-home", str(tmp_path / "custom-splunk"),
                "--admin-password-file", str(password_file),
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
                "--phase", "install",
                "--execution", "local",
                "--host-bootstrap-role", "standalone-search-tier",
                "--source", "local",
                "--file", str(package_file),
                "--package-type", "auto",
                "--splunk-home", str(target_home),
                "--admin-password-file", str(password_file),
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists but is not a Splunk install", result.stdout + result.stderr)

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
                source "{REPO_ROOT / 'skills/shared/lib/host_bootstrap_helpers.sh'}"
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
                ["bash", "-lc", helper_script],
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

    def test_host_bootstrap_install_preserves_local_package_and_cleans_user_seed_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            current_user = subprocess.check_output(["id", "-un"], text=True).strip()
            credentials_file = tmp_path / "credentials"
            password_file = tmp_path / "admin_password"
            package_file = tmp_path / "splunk-package.tgz"
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
                "--phase", "install",
                "--execution", "local",
                "--host-bootstrap-role", "standalone-search-tier",
                "--source", "local",
                "--file", str(package_file),
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--admin-password-file", str(password_file),
                "--no-boot-start",
            )

            first_result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                *install_args,
                env=env,
            )
            self.assertEqual(first_result.returncode, 0, msg=first_result.stdout + first_result.stderr)
            self.assertTrue(package_file.exists(), msg="Local package should not be deleted after install")
            self.assertFalse((splunk_home / "etc/system/local/user-seed.conf").exists())
            self.assertEqual(list((splunk_home / "etc/system/local").glob("user-seed.conf.bak.*")), [])

            stale_backup = splunk_home / "etc/system/local/user-seed.conf.bak.stale"
            stale_backup.parent.mkdir(parents=True, exist_ok=True)
            stale_backup.write_text("stale", encoding="utf-8")

            second_result = self.run_script(
                "skills/splunk-enterprise-host-setup/scripts/setup.sh",
                *install_args,
                env=env,
            )
            self.assertEqual(second_result.returncode, 0, msg=second_result.stdout + second_result.stderr)
            self.assertTrue(package_file.exists(), msg="Local package should remain after repeated install runs")
            self.assertFalse((splunk_home / "etc/system/local/user-seed.conf").exists())
            self.assertEqual(list((splunk_home / "etc/system/local").glob("user-seed.conf.bak.*")), [])

    def test_host_bootstrap_configure_heavy_forwarder_does_not_require_admin_password(self):
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
                "--phase", "configure",
                "--execution", "local",
                "--host-bootstrap-role", "heavy-forwarder",
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--server-list", "idx01.example.com:9997",
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
                "--phase", "cluster",
                "--execution", "local",
                "--deployment-mode", "clustered",
                "--host-bootstrap-role", "cluster-manager",
                "--splunk-home", str(splunk_home),
                "--service-user", current_user,
                "--idxc-secret-file", str(idxc_secret_file),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            server_conf = (splunk_home / "etc/system/local/server.conf").read_text(encoding="utf-8")
            self.assertIn("mode = manager", server_conf)

    def test_host_bootstrap_download_without_url_resolves_latest_official_tgz_and_verifies_sha512(self):
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
                "--phase", "download",
                "--execution", "local",
                "--source", "auto",
                "--package-type", "tgz",
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
            self.assertIn("https://www.splunk.com/en_us/download/splunk-enterprise.html", curl_requests)
            self.assertIn(package_url, curl_requests)
            self.assertIn(sha_url, curl_requests)
            self.assertNotIn(old_package_url, curl_requests)

    def test_host_bootstrap_download_without_url_resolves_latest_official_deb_when_requested(self):
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
                "--phase", "download",
                "--execution", "local",
                "--source", "remote",
                "--package-type", "deb",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Resolved latest Splunk Enterprise 10.2.1 package", result.stdout)
            self.assertTrue(package_path.exists())
            self.assertTrue(metadata_path.exists())

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://www.splunk.com/en_us/download/splunk-enterprise.html", curl_requests)
            self.assertIn(package_url, curl_requests)
            self.assertIn(sha_url, curl_requests)

    def test_host_bootstrap_download_without_url_auto_selects_deb_from_remote_target_os(self):
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
                "--phase", "download",
                "--execution", "ssh",
                "--source", "remote",
                "--package-type", "auto",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Auto-selected deb", result.stdout)
            self.assertIn("Resolved latest Splunk Enterprise 10.2.1 package", result.stdout)
            self.assertTrue(package_path.exists())

    def test_host_bootstrap_download_without_url_fails_when_page_version_disagrees_with_package_version(self):
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
                "--phase", "download",
                "--execution", "local",
                "--source", "remote",
                "--package-type", "tgz",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Failed to resolve the latest official Splunk Enterprise tgz package", result.stdout + result.stderr)

    def test_host_bootstrap_download_without_url_can_use_stale_latest_metadata_when_allowed(self):
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
                "--phase", "download",
                "--execution", "local",
                "--source", "remote",
                "--package-type", "tgz",
                "--allow-stale-latest",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("attempting stale metadata fallback", result.stdout)
            self.assertTrue(package_path.exists())
            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://www.splunk.com/en_us/download/splunk-enterprise.html", curl_requests)
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
                "--phase", "download",
                "--execution", "local",
                "--source", "remote",
                "--package-type", "tgz",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--allow-stale-latest", result.stdout + result.stderr)

    def test_host_bootstrap_download_without_url_rejects_stale_metadata_older_than_30_days(self):
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
                "--phase", "download",
                "--execution", "local",
                "--source", "remote",
                "--package-type", "tgz",
                "--allow-stale-latest",
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("older than 30 days", result.stdout + result.stderr)

    def test_host_bootstrap_smoke_latest_resolution_checks_live_metadata_without_downloading_package(self):
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
                "--package-type", "tgz",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("Smoke check passed for tgz (live)", result.stdout)
            self.assertIn(package_url, result.stdout)
            self.assertIn(sha_url, result.stdout)
            self.assertFalse(package_path.exists())
            self.assertFalse(metadata_path.exists())

            curl_requests = curl_log.read_text(encoding="utf-8")
            self.assertIn("https://www.splunk.com/en_us/download/splunk-enterprise.html", curl_requests)
            self.assertIn(sha_url, curl_requests)
            self.assertNotIn(package_url + "\n", curl_requests)


if __name__ == "__main__":
    unittest.main()
