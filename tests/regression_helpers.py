#!/usr/bin/env python3
"""Regression tests for first-party shell entrypoints."""

import json
import hashlib
import os
import stat
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_logged_command(path: Path, log_env_var: str) -> None:
    write_executable(
        path,
        f"""\
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        log_path = os.environ.get("{log_env_var}", "")
        if log_path:
            with Path(log_path).open("a", encoding="utf-8") as handle:
                handle.write("{path.name} " + " ".join(sys.argv[1:]) + "\\n")
        """,
    )


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


def write_remote_shell_mocks(bin_dir: Path) -> None:
    write_executable(
        bin_dir / "sshpass",
        """\
        #!/usr/bin/env bash
        shift 2
        exec "$@"
        """,
    )
    write_executable(
        bin_dir / "sudo",
        """\
        #!/usr/bin/env bash
        if [[ "${REMOTE_SUDO_MODE:-}" == "require_stdin" ]]; then
            use_stdin=false
            args=()
            for arg in "$@"; do
                if [[ "${arg}" == "-S" ]]; then
                    use_stdin=true
                    continue
                fi
                args+=("${arg}")
            done
            if [[ "${use_stdin}" != "true" ]]; then
                echo "sudo: a terminal is required to read the password; either use the -S option to read from standard input or configure an askpass helper" >&2
                echo "sudo: a password is required" >&2
                exit 1
            fi
            cat >/dev/null
            exec "${args[@]}"
        fi
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
        bin_dir / "scp",
        """\
        #!/usr/bin/env bash
        local_path="${@: -2:1}"
        remote_spec="${@: -1}"
        remote_path="${remote_spec#*:}"
        destination="${REMOTE_ROOT}${remote_path}"
        mkdir -p "$(dirname "${destination}")"
        cp "${local_path}" "${destination}"
        """,
    )
    write_executable(
        bin_dir / "ssh",
        """\
        #!/usr/bin/env python3
        import os
        import re
        import shlex
        import subprocess
        import sys
        from pathlib import Path

        remote_root = os.environ["REMOTE_ROOT"]
        remote_cmd = sys.argv[-1]
        parts = shlex.split(remote_cmd)
        if len(parts) >= 3 and parts[0] == "bash" and parts[1] == "-lc":
            raw_cmd = parts[2]
        else:
            raw_cmd = remote_cmd

        def remap_paths(text, source_path, target_path):
            pattern = re.compile(
                rf"(?P<prefix>(^|[\\s\\\"'=(:])){re.escape(source_path)}(?P<suffix>(?=$|[/\\s\\\"')]))"
            )
            return pattern.sub(lambda match: match.group("prefix") + target_path, text)

        raw_cmd = remap_paths(raw_cmd, "/opt/splunk", f"{remote_root}/opt/splunk")
        raw_cmd = remap_paths(raw_cmd, "/var/tmp", f"{remote_root}/var/tmp")
        raw_cmd = raw_cmd.replace(remote_root, "\\x00RR\\x00")
        raw_cmd = remap_paths(raw_cmd, "/tmp", f"{remote_root}/tmp")
        raw_cmd = raw_cmd.replace("\\x00RR\\x00", remote_root)

        env = os.environ.copy()
        env["PATH"] = f"{Path(sys.argv[0]).resolve().parent}:{env.get('PATH', '')}"
        result = subprocess.run(["bash", "-c", raw_cmd], env=env, check=False)
        raise SystemExit(result.returncode)
        """,
    )



class ShellScriptRegressionBase(unittest.TestCase):
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
            timeout=120,
        )

    def run_script_no_env(
        self,
        script_rel_path: str,
        *args: str,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(REPO_ROOT / script_rel_path), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
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
            if "splunkbase.splunk.com/api/v1/app/7569/release/" in url:
                out('[{"name":"1.0.50"}]')

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
                "7569": ("TA-cisco-cloud-security-addon", "1.0.50"),
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
            elif "cisco-secure-access-add-on-for-splunk" in file_path:
                app_name, default_version = ("TA-cisco-cloud-security-addon", "1.0.50")
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
        command_log = tmp_path / "sc4s_commands.log"

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

            log_path = os.environ.get("CURL_LOG", "")
            if log_path and url:
                with Path(log_path).open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

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
                    "index": body.get("index", "sc4s"),
                    "default_index": body.get("index", "sc4s"),
                    "token": f"generated-{name}-token",
                }
                save()
                out("", 201)

            if "/services/data/inputs/http/" in path and method == "POST" and not path.endswith("/enable"):
                encoded_name = path.rsplit("/", 1)[-1]
                encoded_name = encoded_name.split("?", 1)[0]
                name = encoded_name.replace("%3A", ":").replace("%2F", "/")
                if name.startswith("http://"):
                    name = name[len("http://") :]
                body = decode_form(data)
                token = state["hec_tokens"].setdefault(
                    name,
                    {"index": "sc4s", "default_index": "sc4s", "token": f"generated-{name}-token"},
                )
                if "index" in body:
                    token["index"] = body["index"]
                    token["default_index"] = body["index"]
                save()
                out("", 200)

            if "/services/data/inputs/http/" in path and path.endswith("/enable") and method == "POST":
                encoded_name = path.rsplit("/", 2)[-2]
                name = encoded_name.replace("%3A", ":").replace("%2F", "/")
                if name.startswith("http://"):
                    name = name[len("http://") :]
                token = state["hec_tokens"].setdefault(
                    name,
                    {"index": "sc4s", "default_index": "sc4s", "token": f"generated-{name}-token"},
                )
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
                                "index": token.get("index", "sc4s"),
                                "default_index": token.get("default_index", token.get("index", "sc4s")),
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
        write_logged_command(bin_dir / "docker", "SC4S_COMMAND_LOG")
        write_logged_command(bin_dir / "podman", "SC4S_COMMAND_LOG")
        write_logged_command(bin_dir / "podman-compose", "SC4S_COMMAND_LOG")
        write_logged_command(bin_dir / "helm", "SC4S_COMMAND_LOG")
        write_logged_command(bin_dir / "systemctl", "SC4S_COMMAND_LOG")

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["SC4S_STATE"] = str(state_file)
        env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
        env["SPLUNK_PLATFORM"] = "enterprise"
        env["SC4S_COMMAND_LOG"] = str(command_log)
        env["SC4S_SYSTEMD_UNIT_DIR"] = str(tmp_path / "systemd-units")
        env["SC4S_SYSTEMD_USE_SUDO"] = "never"

        return env, state_file

    def build_mock_sc4snmp_env(self, tmp_path: Path) -> tuple[dict, Path]:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        state_file = tmp_path / "sc4snmp_state.json"
        credentials_file = tmp_path / "credentials"
        command_log = tmp_path / "sc4snmp_commands.log"

        state_file.write_text(
            json.dumps(
                {
                    "indexes": {},
                    "hec_tokens": {},
                    "data_count": 4,
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

            state_path = Path(os.environ["SC4SNMP_STATE"])
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

            log_path = os.environ.get("CURL_LOG", "")
            if log_path and url:
                with Path(log_path).open("a", encoding="utf-8") as handle:
                    handle.write(url + "\\n")

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
                name = body.get("name", "sc4snmp")
                state["hec_tokens"][name] = {
                    "disabled": body.get("disabled", "false"),
                    "useACK": body.get("useACK", "0"),
                    "indexes": body.get("indexes", ""),
                    "index": body.get("index", "netops"),
                    "default_index": body.get("index", "netops"),
                    "token": f"generated-{name}-token",
                }
                save()
                out("", 201)

            if "/services/data/inputs/http/" in path and method == "POST" and not path.endswith("/enable"):
                encoded_name = path.rsplit("/", 1)[-1]
                encoded_name = encoded_name.split("?", 1)[0]
                name = encoded_name.replace("%3A", ":").replace("%2F", "/")
                if name.startswith("http://"):
                    name = name[len("http://") :]
                body = decode_form(data)
                token = state["hec_tokens"].setdefault(
                    name,
                    {"index": "netops", "default_index": "netops", "token": f"generated-{name}-token"},
                )
                if "index" in body:
                    token["index"] = body["index"]
                    token["default_index"] = body["index"]
                save()
                out("", 200)

            if "/services/data/inputs/http/" in path and path.endswith("/enable") and method == "POST":
                encoded_name = path.rsplit("/", 2)[-2]
                name = encoded_name.replace("%3A", ":").replace("%2F", "/")
                if name.startswith("http://"):
                    name = name[len("http://") :]
                token = state["hec_tokens"].setdefault(
                    name,
                    {"index": "netops", "default_index": "netops", "token": f"generated-{name}-token"},
                )
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
                                "index": token.get("index", "netops"),
                                "default_index": token.get("default_index", token.get("index", "netops")),
                                "token": token.get("token", ""),
                            },
                        }
                    )
                out(json.dumps({"entry": entries}))

            if path.endswith("/services/search/jobs") and method == "POST":
                out(json.dumps({"results": [{"count": str(state.get("data_count", 0))}]}))

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
        write_logged_command(bin_dir / "docker", "SC4SNMP_COMMAND_LOG")
        write_logged_command(bin_dir / "podman", "SC4SNMP_COMMAND_LOG")
        write_logged_command(bin_dir / "podman-compose", "SC4SNMP_COMMAND_LOG")
        write_logged_command(bin_dir / "helm", "SC4SNMP_COMMAND_LOG")

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["SC4SNMP_STATE"] = str(state_file)
        env["SPLUNK_CREDENTIALS_FILE"] = str(credentials_file)
        env["SPLUNK_PLATFORM"] = "enterprise"
        env["SC4SNMP_COMMAND_LOG"] = str(command_log)

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
