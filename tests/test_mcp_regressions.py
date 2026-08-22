#!/usr/bin/env python3
"""Regression tests for Splunk MCP Server setup shell scripts."""

import contextlib
import configparser
import hashlib
import importlib.util
import io
import json
import os
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from tests.regression_helpers import REPO_ROOT, ShellScriptRegressionBase, write_executable


def load_mcp_tools_loader_module():
    module_path = REPO_ROOT / "skills/shared/scripts/load_mcp_tools.py"
    spec = importlib.util.spec_from_file_location("load_mcp_tools_for_tests", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def minimal_mcp_tools_document() -> dict[str, object]:
    return {
        "name": "Demo MCP Tools",
        "description": "Demo",
        "version": "1.0.0",
        "author": "tests",
        "tools": [
            {
                "_key": "demo:demo_example",
                "name": "demo_example",
                "title": "Demo Example",
                "description": "Example",
                "category": "demo",
                "tags": ["demo"],
                "time_range": False,
                "row_limiter": True,
                "spl": "| rest /services/server/info | table serverName",
                "arguments": [],
                "examples": [],
            }
        ],
    }


def write_mcp_validation_curl(path: Path) -> None:
    """Write a deterministic curl double for the MCP completion validator."""
    write_executable(
        path,
        """\
        #!/usr/bin/env python3
        import json
        import os
        import sys
        from pathlib import Path

        args = sys.argv[1:]
        url = ""
        data = ""
        output_target = None
        write_format = ""
        headers = []
        curl_configs = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in {"-d", "--data", "--data-raw"} and i + 1 < len(args):
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
            if arg == "-H" and i + 1 < len(args):
                headers.append(args[i + 1])
                i += 2
                continue
            if arg == "-K" and i + 1 < len(args):
                try:
                    curl_configs.append(Path(args[i + 1]).read_text(encoding="utf-8"))
                except OSError:
                    pass
                i += 2
                continue
            if arg.startswith(("https://", "http://")):
                url = arg
            i += 1

        log_path = Path(os.environ["MCP_VALIDATION_CURL_LOG"])
        with log_path.open("a", encoding="utf-8") as handle:
            auth_scheme = "bearer" if any("Authorization: Bearer " in value for value in curl_configs) else "splunk"
            handle.write(json.dumps({
                "url": url,
                "data": data,
                "auth_scheme": auth_scheme,
                "headers": headers,
                "quiet_config": "-q" in args,
                "https_protocol_only": "=https" in args,
                "no_redirects": "--max-redirs" in args and args[args.index("--max-redirs") + 1] == "0",
                "globbing_disabled": "--globoff" in args,
            }) + "\\n")

        status = 200
        body = "{}"
        if url.endswith("/services/auth/login"):
            body = "<response><sessionKey>test-session-key</sessionKey></response>"
        elif "/services/apps/local/Splunk_MCP_Server?" in url:
            version = os.environ.get("MCP_VALIDATION_APP_VERSION", "1.3.1")
            body = json.dumps({
                "entry": [{"content": {"version": version, "visible": True}}]
            })
        elif "/configs/conf-mcp/" in url:
            body = json.dumps({
                "entry": [{"content": {
                    "base_url": "/services/mcp",
                    "timeout": "30",
                    "max_row_limit": "2000",
                    "default_row_limit": "100",
                    "ssl_verify": "true",
                    "require_encrypted_token": "true",
                    "legacy_token_grace_days": "0",
                    "mcp_token_default_lifetime_seconds": "3600",
                    "mcp_token_max_lifetime_seconds": "86400",
                    "token_key_reload_interval_seconds": "300",
                    "global": "120",
                    "admission_global": "30",
                    "tenant_authenticated": "60",
                    "tenant_unauthenticated": "10",
                    "circuit_breaker_failure_threshold": "5",
                    "circuit_breaker_cooldown_seconds": "60",
                }}]
            })
        elif url.endswith("/services/mcp"):
            request = json.loads(data)
            method = request.get("method")
            if any(value == "Origin: https://untrusted.invalid" for value in headers):
                status = 403
                body = json.dumps({"error": {"message": "untrusted origin"}})
            elif method == "ping":
                body = json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": {"message": "pong"}})
            elif method == "initialize":
                body = json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": {"protocolVersion": "2025-06-18"}})
            elif method == "notifications/initialized":
                status = 202
                body = ""
            elif method == "tools/list":
                tools = [] if os.environ.get("MCP_VALIDATION_HIDE_GET_INFO") == "1" else [{"name": "splunk_get_info"}]
                if os.environ.get("MCP_VALIDATION_EXTRA_TOOL"):
                    tools.append({"name": os.environ["MCP_VALIDATION_EXTRA_TOOL"]})
                body = json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": {"tools": tools}})
            elif method == "tools/call":
                body = json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": {"content": [{"type": "text", "text": "ok"}], "isError": False}})
            else:
                status = 400
                body = json.dumps({"error": {"message": "unexpected method"}})
        elif "/data/ui/views/" in url:
            missing_view = os.environ.get("MCP_VALIDATION_MISSING_VIEW", "")
            if missing_view and f"/data/ui/views/{missing_view}?" in url:
                status = 404

        if output_target and output_target != "/dev/null":
            Path(output_target).write_text(body, encoding="utf-8")
        elif not output_target:
            sys.stdout.write(body)
        if write_format:
            sys.stdout.write(write_format.replace("\\\\n", "\\n").replace("%{http_code}", str(status)))
        """,
    )


def mcp_validation_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_mcp_validation_curl(bin_dir / "curl")
    curl_log = tmp_path / "curl.jsonl"
    credentials_file = tmp_path / "credentials"
    credentials_file.write_text("", encoding="utf-8")
    mcp_token_file = tmp_path / "mcp.token"
    mcp_token_file.write_text("encrypted-mcp-token", encoding="utf-8")
    mcp_token_file.chmod(0o600)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "MCP_VALIDATION_CURL_LOG": str(curl_log),
            "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
            "SPLUNK_PLATFORM": "enterprise",
            "SPLUNK_TARGET_ROLE": "search-tier",
            "SPLUNK_URI": "https://splunk.example.invalid:8089",
            "SPLUNK_USER": "admin",
            "SPLUNK_PASS": "test-password",
            "SPLUNK_MCP_BEARER_TOKEN_FILE": str(mcp_token_file),
        }
    )
    return env, curl_log


class MCPRegressionTests(ShellScriptRegressionBase):
    def test_splunk_mcp_131_package_manifest_and_archive_contract(self):
        expected_filename = "splunk-mcp-server_131.tgz"
        expected_version = "1.3.1"
        expected_sha256 = "fa380909ba24dcea155d59f9dccc67fd83d99b1d9595681183c6467bacdf70d3"
        manifest_path = REPO_ROOT / "skills/splunk-mcp-server-setup/package-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["app_id"], 7931)
        self.assertEqual(manifest["app_name"], "Splunk_MCP_Server")
        self.assertEqual(manifest["filename"], expected_filename)
        self.assertEqual(manifest["version"], expected_version)
        self.assertEqual(manifest["sha256"], expected_sha256)
        self.assertIs(manifest["production_approved"], False)
        self.assertEqual(
            manifest["review_status"],
            "blocked_pending_vendor_security_fixes",
        )

        setup_text = (
            REPO_ROOT / "skills/splunk-mcp-server-setup/scripts/setup.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('PACKAGE_MANIFEST="${SCRIPT_DIR}/../package-manifest.json"', setup_text)
        self.assertIn('DEFAULT_PACKAGE_FILE="${PROJECT_ROOT}/splunk-ta/${DEFAULT_PACKAGE_NAME}"', setup_text)
        self.assertIn('if [[ "${actual_sha}" != "${DEFAULT_PACKAGE_SHA256}" ]]', setup_text)
        self.assertNotIn("splunk-mcp-server_110.tgz", setup_text)

        skill_text = (REPO_ROOT / "skills/splunk-mcp-server-setup/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"splunk-ta/{expected_filename}", skill_text)
        self.assertIn(f"version {expected_version}", skill_text)

        archive_path = REPO_ROOT / "splunk-ta" / expected_filename
        if not archive_path.exists():
            return

        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        self.assertEqual(digest, expected_sha256)
        with tarfile.open(archive_path, mode="r:gz") as archive:
            names = set(archive.getnames())
            app_conf_member = archive.extractfile("Splunk_MCP_Server/default/app.conf")
            self.assertIsNotNone(app_conf_member)
            app_conf = configparser.ConfigParser()
            app_conf.read_string(app_conf_member.read().decode("utf-8"))
            self.assertEqual(app_conf["id"]["version"], expected_version)
            self.assertEqual(app_conf["launcher"]["version"], expected_version)
            for view_name in ("dashboard", "monitoring", "tools", "tool_settings"):
                self.assertIn(
                    f"Splunk_MCP_Server/default/data/ui/views/{view_name}.xml",
                    names,
                )

    def test_splunk_mcp_131_token_mint_uses_vendor_get_contract(self):
        archive_path = REPO_ROOT / "splunk-ta/splunk-mcp-server_131.tgz"
        if not archive_path.exists():
            self.skipTest("Splunk MCP Server 1.3.1 archive is not present in this checkout")

        with tarfile.open(archive_path, mode="r:gz") as archive:
            handler_member = archive.extractfile(
                "Splunk_MCP_Server/bin/mcp_token_handler.py"
            )
            self.assertIsNotNone(handler_member)
            handler_text = handler_member.read().decode("utf-8")

        self.assertIn('if method == "POST":', handler_text)
        self.assertIn('if action != "rotate":', handler_text)
        self.assertIn('username = query_params.get(USERNAME, "").strip()', handler_text)

        setup_text = (
            REPO_ROOT / "skills/splunk-mcp-server-setup/scripts/setup.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'query="$(form_urlencode_pairs username "${TOKEN_USER}" expires_on "${TOKEN_EXPIRES_ON}"',
            setup_text,
        )
        self.assertIn(
            'not_before "${TOKEN_NOT_BEFORE}" output_mode json)',
            setup_text,
        )
        self.assertIn(
            'url="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_token?${query}"',
            setup_text,
        )
        self.assertIn('splunk_curl "${SK}" "${url}"', setup_text)
        self.assertNotIn(
            'splunk_curl_post "${SK}" "${body_form}" "${url}" -X POST',
            setup_text,
        )

    def test_splunk_mcp_install_blocks_nonproduction_package_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            package_file = Path(tmpdir) / "splunk-mcp-server_131.tgz"
            package_file.write_bytes(b"evaluation fixture")
            env = os.environ.copy()
            env.update(
                {
                    "SPLUNK_PLATFORM": "enterprise",
                    "SPLUNK_TARGET_ROLE": "search-tier",
                }
            )

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--install",
                "--package-file",
                str(package_file),
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, msg=output)
            self.assertIn("workflows are blocked", output)
            self.assertNotIn("Package checksum mismatch", output)

    def test_mcp_loaders_follow_shared_tls_policy(self):
        loader_paths = sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for path in REPO_ROOT.glob("skills/*/scripts/load_mcp_tools.sh")
            if (path.parents[1] / "mcp_tools.json").exists()
        )

        self.assertIn("skills/cisco-appdynamics-setup/scripts/load_mcp_tools.sh", loader_paths)
        self.assertIn("skills/splunk-enterprise-security-config/scripts/load_mcp_tools.sh", loader_paths)
        shared_loader = (REPO_ROOT / "skills/shared/scripts/load_mcp_tools.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("splunk_export_python_tls_env", shared_loader)
        self.assertNotIn("ssl.CERT_NONE", shared_loader)
        self.assertNotIn("check_hostname = False", shared_loader)
        for rel_path in loader_paths:
            with self.subTest(script=rel_path):
                script_text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
                self.assertIn("../../shared/scripts/load_mcp_tools.sh", script_text)
                self.assertNotIn("ssl.CERT_NONE", script_text)
                self.assertNotIn("check_hostname = False", script_text)

    def test_mcp_shared_loader_uses_rest_batch_before_legacy_kv(self):
        loader_text = (REPO_ROOT / "skills/shared/scripts/load_mcp_tools.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("mcp_tools/collisions", loader_text)
        self.assertIn("rest_batch_payload", loader_text)
        self.assertIn("cleanup_stale_legacy_keys", loader_text)
        self.assertIn('method="DELETE"', loader_text)
        self.assertIn("LEGACY_FALLBACK_STATUSES = {404, 405, 501}", loader_text)
        self.assertIn("exc.status not in LEGACY_FALLBACK_STATUSES", loader_text)
        self.assertIn("--allow-legacy-kv", loader_text)
        self.assertIn("Use --allow-legacy-kv only when an older Splunk MCP Server app lacks the REST batch endpoint.", loader_text)

    def test_mcp_python_loader_defaults_to_verified_tls(self):
        loader = load_mcp_tools_loader_module()
        saved = {
            "__SPLUNK_TLS_MODE": os.environ.pop("__SPLUNK_TLS_MODE", None),
            "__SPLUNK_TLS_CA_CERT": os.environ.pop("__SPLUNK_TLS_CA_CERT", None),
        }
        try:
            ctx = loader.ssl_context_from_env()
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value

        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_mcp_python_loader_rejects_plaintext_http_before_rest_calls(self):
        loader = load_mcp_tools_loader_module()
        calls = []
        with tempfile.TemporaryDirectory() as tmpdir:
            tools_path = Path(tmpdir) / "mcp_tools.json"
            tools_path.write_text(
                json.dumps(minimal_mcp_tools_document()),
                encoding="utf-8",
            )
            original_rest = loader.load_via_rest_batch
            saved = {
                key: os.environ.pop(key, None)
                for key in (
                    "__SPLUNK_ALLOW_INSECURE_HTTP",
                    "SPLUNK_ALLOW_INSECURE_HTTP",
                    "__SPLUNK_SK",
                )
            }
            loader.load_via_rest_batch = lambda **kwargs: calls.append(kwargs)
            try:
                os.environ["__SPLUNK_SK"] = "session"
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    result = loader.main(
                        [
                            "--tools-json",
                            str(tools_path),
                            "--splunk-uri",
                            "http://splunk.example:8089",
                        ]
                    )
            finally:
                loader.load_via_rest_batch = original_rest
                for key in saved:
                    os.environ.pop(key, None)
                for key, value in saved.items():
                    if value is not None:
                        os.environ[key] = value

        self.assertEqual(result, 1)
        self.assertEqual(calls, [])
        self.assertIn("plaintext HTTP is refused", stderr.getvalue())
        self.assertIn("SPLUNK_ALLOW_INSECURE_HTTP=true", stderr.getvalue())

    def test_mcp_python_loader_allows_explicit_lab_http_with_warning(self):
        loader = load_mcp_tools_loader_module()
        calls = []
        with tempfile.TemporaryDirectory() as tmpdir:
            tools_path = Path(tmpdir) / "mcp_tools.json"
            tools_path.write_text(
                json.dumps(minimal_mcp_tools_document()),
                encoding="utf-8",
            )
            original_rest = loader.load_via_rest_batch
            saved = {
                key: os.environ.pop(key, None)
                for key in (
                    "__SPLUNK_ALLOW_INSECURE_HTTP",
                    "SPLUNK_ALLOW_INSECURE_HTTP",
                    "__SPLUNK_SK",
                    "__SPLUNK_TLS_MODE",
                )
            }
            loader.load_via_rest_batch = lambda **kwargs: calls.append(kwargs)
            loader._WARNED_INSECURE_HTTP = False
            try:
                os.environ["__SPLUNK_ALLOW_INSECURE_HTTP"] = "true"
                os.environ["__SPLUNK_SK"] = "session"
                os.environ["__SPLUNK_TLS_MODE"] = "verify"
                stderr = io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                    result = loader.main(
                        [
                            "--tools-json",
                            str(tools_path),
                            "--splunk-uri",
                            "http://splunk.example:8089",
                        ]
                    )
            finally:
                loader.load_via_rest_batch = original_rest
                for key in saved:
                    os.environ.pop(key, None)
                for key, value in saved.items():
                    if value is not None:
                        os.environ[key] = value

        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["splunk_uri"], "http://splunk.example:8089")
        self.assertIn("WARNING: LAB ONLY", stderr.getvalue())

    def test_mcp_python_loader_follows_same_origin_but_rejects_cross_origin_redirects(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        loader = load_mcp_tools_loader_module()
        same_origin_auth = []
        cross_origin_called = threading.Event()

        class SameOriginHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                same_origin_auth.append(self.headers.get("Authorization", ""))
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/final")
                    self.end_headers()
                    return
                payload = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                return

        class TargetHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                cross_origin_called.set()
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_args):
                return

        target = HTTPServer(("127.0.0.1", 0), TargetHandler)

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{target.server_port}/credential-capture",
                )
                self.end_headers()

            def log_message(self, *_args):
                return

        same_origin = HTTPServer(("127.0.0.1", 0), SameOriginHandler)
        redirect = HTTPServer(("127.0.0.1", 0), RedirectHandler)
        servers = (same_origin, redirect, target)
        threads = [
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in servers
        ]
        saved = {
            key: os.environ.pop(key, None)
            for key in ("__SPLUNK_ALLOW_INSECURE_HTTP", "SPLUNK_ALLOW_INSECURE_HTTP")
        }
        for thread in threads:
            thread.start()
        try:
            os.environ["__SPLUNK_ALLOW_INSECURE_HTTP"] = "true"
            loader._WARNED_INSECURE_HTTP = False
            with contextlib.redirect_stderr(io.StringIO()):
                status, body, _ = loader.request_json(
                    f"http://127.0.0.1:{same_origin.server_port}/redirect",
                    method="GET",
                    session_key="session",
                    ctx=ssl.create_default_context(),
                )
                with self.assertRaises(loader.urllib.error.URLError) as raised:
                    loader.request_json(
                        f"http://127.0.0.1:{redirect.server_port}/redirect",
                        method="GET",
                        session_key="session",
                        ctx=ssl.create_default_context(),
                    )
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)
            for key in saved:
                os.environ.pop(key, None)
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value

        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True})
        self.assertEqual(same_origin_auth, ["Splunk session", "Splunk session"])
        self.assertIn("cross-origin redirect refused", str(raised.exception))
        self.assertFalse(cross_origin_called.is_set())

    def test_mcp_shared_loader_rest_batch_sequence_is_behavioral(self):
        loader = load_mcp_tools_loader_module()
        calls = []
        legacy_doc = {
            "name": "Demo MCP Tools",
            "description": "Demo",
            "version": "1.0.0",
            "author": "tests",
            "tools": [
                {
                    "_key": "demo:old_example",
                    "name": "demo_example",
                    "title": "Demo Example",
                    "description": "Example",
                    "category": "demo",
                    "tags": ["demo"],
                    "time_range": False,
                    "row_limiter": True,
                    "spl": "| rest /services/server/info | table serverName",
                    "arguments": [],
                    "examples": [],
                }
            ],
        }

        def fake_request_json(url, *, method, session_key, ctx, payload=None):
            calls.append(
                {
                    "url": url,
                    "method": method,
                    "session_key": session_key,
                    "payload": payload,
                }
            )
            self.assertEqual(session_key, "session")
            if url.endswith("/mcp_tools/collisions"):
                return 200, {"collisions": {}}, "{}"
            if method == "POST" and url.endswith("/mcp_tools") and "external_app_id" in payload:
                return 200, {"registered_count": len(payload["tools"]), "deleted_count": 0}, "{}"
            if method == "DELETE" and url.endswith("/mcp_tools"):
                return 200, {}, "{}"
            if method == "POST" and url.endswith("/mcp_tools") and payload.get("enabled") is True:
                return 200, {"enabled": True}, "{}"
            self.fail(f"Unexpected request: {method} {url} {payload}")

        original_request_json = loader.request_json
        loader.request_json = fake_request_json
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                loader.load_via_rest_batch(
                    legacy_doc=legacy_doc,
                    splunk_uri="https://splunk.example:8089",
                    app_context="Splunk_MCP_Server",
                    session_key="session",
                    ctx=None,
                    override_collisions=True,
                )
        finally:
            loader.request_json = original_request_json

        self.assertEqual([call["method"] for call in calls], ["POST", "POST", "DELETE", "POST"])
        self.assertTrue(calls[0]["url"].endswith("/mcp_tools/collisions"))
        self.assertEqual(calls[0]["payload"], {"tool_ids": ["demo:demo_example"]})
        self.assertEqual(calls[1]["payload"]["external_app_id"], "demo")
        self.assertEqual(calls[1]["payload"]["tools"][0]["name"], "demo_example")
        self.assertEqual(calls[2]["payload"], {"tool_id": "demo:old_example"})
        self.assertEqual(
            calls[3]["payload"],
            {
                "tool_id": "demo:demo_example",
                "tool_name": "demo_example",
                "enabled": True,
                "override": True,
            },
        )

    def test_mcp_shared_loader_aborts_on_collision_without_override(self):
        loader = load_mcp_tools_loader_module()
        calls = []
        legacy_doc = {
            "name": "Demo MCP Tools",
            "description": "Demo",
            "version": "1.0.0",
            "author": "tests",
            "tools": [
                {
                    "_key": "demo:demo_example",
                    "name": "demo_example",
                    "title": "Demo Example",
                    "description": "Example",
                    "category": "demo",
                    "tags": ["demo"],
                    "time_range": False,
                    "row_limiter": True,
                    "spl": "| rest /services/server/info | table serverName",
                    "arguments": [],
                    "examples": [],
                }
            ],
        }

        def fake_request_json(url, *, method, session_key, ctx, payload=None):
            calls.append({"url": url, "method": method, "payload": payload})
            return 200, {"collisions": {"demo:demo_example": ["builtin:get_server_info"]}}, "{}"

        original_request_json = loader.request_json
        loader.request_json = fake_request_json
        try:
            with self.assertRaises(loader.ManifestError):
                loader.load_via_rest_batch(
                    legacy_doc=legacy_doc,
                    splunk_uri="https://splunk.example:8089",
                    app_context="Splunk_MCP_Server",
                    session_key="session",
                    ctx=None,
                    override_collisions=False,
                )
        finally:
            loader.request_json = original_request_json

        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["url"].endswith("/mcp_tools/collisions"))

    def test_mcp_shared_loader_legacy_kv_fallback_is_explicit_and_status_gated(self):
        loader = load_mcp_tools_loader_module()
        legacy_calls = []
        legacy_doc = {
            "name": "Demo MCP Tools",
            "description": "Demo",
            "version": "1.0.0",
            "author": "tests",
            "tools": [
                {
                    "_key": "demo:demo_example",
                    "name": "demo_example",
                    "title": "Demo Example",
                    "description": "Example",
                    "category": "demo",
                    "tags": ["demo"],
                    "time_range": False,
                    "row_limiter": True,
                    "spl": "| rest /services/server/info | table serverName",
                    "arguments": [],
                    "examples": [],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tools_path = Path(tmpdir) / "mcp_tools.json"
            tools_path.write_text(json.dumps(legacy_doc), encoding="utf-8")

            original_rest = loader.load_via_rest_batch
            original_legacy = loader.load_via_legacy_kv

            def fake_legacy(**kwargs):
                legacy_calls.append(kwargs)

            loader.load_via_legacy_kv = fake_legacy
            try:
                def run(status, allow_legacy):
                    def fake_rest(**kwargs):
                        raise loader.HTTPFailure(status, {}, f"HTTP {status}")

                    loader.load_via_rest_batch = fake_rest
                    os.environ["__SPLUNK_SK"] = "session"
                    os.environ["__SPLUNK_TLS_MODE"] = "verify"
                    argv = [
                        "--tools-json",
                        str(tools_path),
                        "--splunk-uri",
                        "https://splunk.example:8089",
                    ]
                    if allow_legacy:
                        argv.append("--allow-legacy-kv")
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        return loader.main(argv)

                self.assertEqual(run(404, allow_legacy=False), 1)
                self.assertEqual(legacy_calls, [])

                self.assertEqual(run(500, allow_legacy=True), 1)
                self.assertEqual(legacy_calls, [])

                self.assertEqual(run(404, allow_legacy=True), 0)
                self.assertEqual(len(legacy_calls), 1)
            finally:
                loader.load_via_rest_batch = original_rest
                loader.load_via_legacy_kv = original_legacy
                os.environ.pop("__SPLUNK_SK", None)
                os.environ.pop("__SPLUNK_TLS_MODE", None)


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
            home_dir = tmp_path / "home"
            home_dir.mkdir()
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
            env["HOME"] = str(home_dir)

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
                "--no-configure-claude",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)

            rendered_config = json.loads((output_dir / ".cursor/mcp.json").read_text(encoding="utf-8"))
            self.assertIn(client_name, rendered_config["mcpServers"])
            self.assertEqual(
                rendered_config["mcpServers"][client_name]["command"],
                "node",
            )
            self.assertEqual(len(rendered_config["mcpServers"][client_name]["args"]), 1)
            self.assertIn("run-splunk-mcp.js", rendered_config["mcpServers"][client_name]["args"][0])

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
            self.assertEqual(codex_args[4], "node")
            self.assertTrue(codex_args[5].startswith(str(home_dir / ".codex" / "mcp-bridges")))
            self.assertTrue(codex_args[5].endswith("/run-splunk-mcp.js"))


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
            token_value = f"tok en'\"$(touch {token_marker})\\tail"

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

                payload = {
                    "args": sys.argv[1:],
                    "token": os.environ.get("SPLUNK_MCP_TOKEN"),
                    "url": os.environ.get("SPLUNK_MCP_URL"),
                }
                Path(os.environ["MCP_REMOTE_LOG"]).write_text(json.dumps(payload), encoding="utf-8")
                """,
            )
            (bin_dir / "package.json").write_text(
                json.dumps({"name": "mcp-remote", "version": "0.1.38"}),
                encoding="utf-8",
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
                "--no-configure-claude",
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

            mcp_remote_payload = json.loads(mcp_remote_log.read_text(encoding="utf-8"))
            mcp_remote_args = mcp_remote_payload["args"]
            self.assertEqual(mcp_remote_args[0], mcp_url)
            self.assertEqual(mcp_remote_payload["token"], token_value)
            self.assertEqual(mcp_remote_payload["url"], mcp_url)
            self.assertEqual(
                mcp_remote_args[1:3],
                ["--header", "Authorization: Bearer ${SPLUNK_MCP_TOKEN}"],
            )
            self.assertNotIn(token_value, json.dumps(mcp_remote_args))

            node_path = shutil.which("node")
            if not node_path:
                self.skipTest("node is required to exercise the rendered JS wrapper")
            mcp_remote_log.unlink()
            js_wrapper_result = subprocess.run(
                [node_path, str(output_dir / "run-splunk-mcp.js")],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                js_wrapper_result.returncode,
                0,
                msg=js_wrapper_result.stdout + js_wrapper_result.stderr,
            )
            mcp_remote_payload = json.loads(mcp_remote_log.read_text(encoding="utf-8"))
            mcp_remote_args = mcp_remote_payload["args"]
            self.assertEqual(mcp_remote_args[0], mcp_url)
            self.assertEqual(mcp_remote_payload["token"], token_value)
            self.assertEqual(mcp_remote_payload["url"], mcp_url)
            self.assertEqual(
                mcp_remote_args[1:3],
                ["--header", "Authorization: Bearer ${SPLUNK_MCP_TOKEN}"],
            )
            self.assertNotIn(token_value, json.dumps(mcp_remote_args))


    def test_splunk_mcp_js_wrapper_requires_pinned_remote_and_never_invokes_npx(self):
        node_path = shutil.which("node")
        if not node_path:
            self.skipTest("node is required to exercise the rendered JS wrapper")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "splunk.token"
            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)

            render_result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--no-register-codex",
                "--no-configure-cursor",
                "--no-configure-claude",
                env=os.environ.copy(),
            )
            self.assertEqual(
                render_result.returncode,
                0,
                msg=render_result.stdout + render_result.stderr,
            )

            wrong_bin = tmp_path / "wrong-bin"
            wrong_bin.mkdir()
            remote_marker = tmp_path / "wrong-remote-ran"
            write_executable(
                wrong_bin / "mcp-remote",
                f"""\
                #!/bin/sh
                /usr/bin/touch {remote_marker}
                """,
            )
            (wrong_bin / "package.json").write_text(
                json.dumps({"name": "mcp-remote", "version": "0.1.39"}),
                encoding="utf-8",
            )
            wrong_env = os.environ.copy()
            wrong_env["PATH"] = f"{wrong_bin}:{wrong_env['PATH']}"
            wrong_result = subprocess.run(
                [node_path, str(output_dir / "run-splunk-mcp.js")],
                cwd=REPO_ROOT,
                env=wrong_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(wrong_result.returncode, 1)
            self.assertIn("mcp-remote 0.1.38 is required", wrong_result.stderr)
            self.assertFalse(remote_marker.exists())

            npx_only_bin = tmp_path / "npx-only-bin"
            npx_only_bin.mkdir()
            npx_marker = tmp_path / "npx-ran"
            write_executable(
                npx_only_bin / "npx",
                f"""\
                #!/bin/sh
                /usr/bin/touch {npx_marker}
                """,
            )
            no_remote_env = os.environ.copy()
            no_remote_env["PATH"] = str(npx_only_bin)
            no_remote_result = subprocess.run(
                [node_path, str(output_dir / "run-splunk-mcp.js")],
                cwd=REPO_ROOT,
                env=no_remote_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(no_remote_result.returncode, 1)
            self.assertIn("mcp-remote not found on PATH", no_remote_result.stderr)
            self.assertFalse(npx_marker.exists(), "the JS bridge must never fall back to npx")


    def test_splunk_mcp_render_rejects_symlinked_secret_destination(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "rendered"
            output_dir.mkdir()
            token_file = tmp_path / "splunk.token"
            victim = tmp_path / "victim"
            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)
            victim.write_text("do-not-overwrite", encoding="utf-8")
            (output_dir / ".env.splunk-mcp").symlink_to(victim)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--no-register-codex",
                "--no-configure-cursor",
                "--no-configure-claude",
                env=os.environ.copy(),
            )

            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertIn("refusing to replace non-regular or symlink target", result.stdout + result.stderr)
            self.assertEqual(victim.read_text(encoding="utf-8"), "do-not-overwrite")


    def test_splunk_mcp_gateway_headers_are_shell_safe_and_not_in_argv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            output_dir = tmp_path / "rendered"
            o11y_token_file = tmp_path / "o11y.token"
            splunk_jwt_file = tmp_path / "splunk.jwt"
            mcp_remote_log = tmp_path / "mcp-remote-log.json"
            url_marker = tmp_path / "url-marker"
            o11y_marker = tmp_path / "o11y-marker"
            splunk_marker = tmp_path / "splunk-marker"
            tenant_marker = tmp_path / "tenant-marker"
            gateway_url = f"https://region-pdx10.api.scs.splunk.com/system/mcp-gateway/v1/?target=$(touch {url_marker})"
            o11y_token = f"sf tok'\"$(touch {o11y_marker})\\tail"
            splunk_jwt = f"spl unk'\"$(touch {splunk_marker})\\tail"
            tenant = f"tenant$(touch {tenant_marker})"

            o11y_token_file.write_text(o11y_token, encoding="utf-8")
            splunk_jwt_file.write_text(splunk_jwt, encoding="utf-8")
            o11y_token_file.chmod(0o600)
            splunk_jwt_file.chmod(0o600)

            write_executable(
                bin_dir / "mcp-remote",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                payload = {
                    "args": sys.argv[1:],
                    "url": os.environ.get("SPLUNK_MCP_URL"),
                    "authorization": os.environ.get("SPLUNK_MCP_HEADER_AUTHORIZATION"),
                    "tenant": os.environ.get("SPLUNK_MCP_HEADER_SPLUNK_TENANT"),
                    "sf_token": os.environ.get("SPLUNK_MCP_HEADER_X_SF_TOKEN"),
                    "sf_realm": os.environ.get("SPLUNK_MCP_HEADER_X_SF_REALM"),
                }
                Path(os.environ["MCP_REMOTE_LOG"]).write_text(json.dumps(payload), encoding="utf-8")
                """,
            )
            (bin_dir / "package.json").write_text(
                json.dumps({"name": "mcp-remote", "version": "0.1.38"}),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["MCP_REMOTE_LOG"] = str(mcp_remote_log)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--gateway-mode",
                "combined",
                "--gateway-url",
                gateway_url,
                "--o11y-realm",
                "us1",
                "--o11y-token-file",
                str(o11y_token_file),
                "--splunk-tenant",
                tenant,
                "--splunk-jwt-file",
                str(splunk_jwt_file),
                "--output-dir",
                str(output_dir),
                "--no-register-codex",
                "--no-configure-cursor",
                "--no-configure-claude",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)

            expected_args = [
                gateway_url,
                "--transport",
                "http-only",
                "--allow-http",
                "--header",
                "Authorization: ${SPLUNK_MCP_HEADER_AUTHORIZATION}",
                "--header",
                "splunk_tenant: ${SPLUNK_MCP_HEADER_SPLUNK_TENANT}",
                "--header",
                "X-SF-TOKEN: ${SPLUNK_MCP_HEADER_X_SF_TOKEN}",
                "--header",
                "X-SF-REALM: ${SPLUNK_MCP_HEADER_X_SF_REALM}",
            ]

            for command in (["bash", str(output_dir / "run-splunk-mcp.sh")],):
                wrapper_result = subprocess.run(
                    command,
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
                payload = json.loads(mcp_remote_log.read_text(encoding="utf-8"))
                self.assertEqual(payload["args"], expected_args)
                self.assertEqual(payload["url"], gateway_url)
                self.assertEqual(payload["authorization"], f"Bearer {splunk_jwt}")
                self.assertEqual(payload["tenant"], tenant)
                self.assertEqual(payload["sf_token"], o11y_token)
                self.assertEqual(payload["sf_realm"], "us1")
                argv_json = json.dumps(payload["args"])
                self.assertNotIn(o11y_token, argv_json)
                self.assertNotIn(splunk_jwt, argv_json)
                self.assertNotIn(tenant, argv_json)
                self.assertFalse(url_marker.exists(), "gateway URL command substitution should not execute")
                self.assertFalse(o11y_marker.exists(), "O11y token command substitution should not execute")
                self.assertFalse(splunk_marker.exists(), "Splunk token command substitution should not execute")
                self.assertFalse(tenant_marker.exists(), "tenant command substitution should not execute")

            node_path = shutil.which("node")
            if not node_path:
                self.skipTest("node is required to exercise the rendered JS wrapper")

            mcp_remote_log.unlink()
            js_wrapper_result = subprocess.run(
                [node_path, str(output_dir / "run-splunk-mcp.js")],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                js_wrapper_result.returncode,
                0,
                msg=js_wrapper_result.stdout + js_wrapper_result.stderr,
            )
            payload = json.loads(mcp_remote_log.read_text(encoding="utf-8"))
            self.assertEqual(payload["args"], expected_args)
            self.assertEqual(payload["authorization"], f"Bearer {splunk_jwt}")
            self.assertEqual(payload["tenant"], tenant)
            self.assertEqual(payload["sf_token"], o11y_token)
            self.assertEqual(payload["sf_realm"], "us1")
            argv_json = json.dumps(payload["args"])
            self.assertNotIn(o11y_token, argv_json)
            self.assertNotIn(splunk_jwt, argv_json)
            self.assertNotIn(tenant, argv_json)


    def test_splunk_mcp_gateway_rejects_unsupported_o11y_realms(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "rendered"
            o11y_token_file = tmp_path / "o11y.token"
            o11y_token_file.write_text("o11y-token-value", encoding="utf-8")
            o11y_token_file.chmod(0o600)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--gateway-mode",
                "o11y",
                "--gateway-url",
                "https://region-pdx10.api.scs.splunk.com/system/mcp-gateway/v1/",
                "--o11y-realm",
                "us2",
                "--o11y-token-file",
                str(o11y_token_file),
                "--output-dir",
                str(output_dir),
                "--no-register-codex",
                "--no-configure-cursor",
                "--no-configure-claude",
                env=os.environ.copy(),
            )

            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertIn("Google Cloud Platform realms or GovCloud realms", result.stdout + result.stderr)

            reference = (
                REPO_ROOT / "skills/splunk-mcp-server-setup/reference.md"
            ).read_text(encoding="utf-8")
            self.assertIn("Google Cloud Platform realms and GovCloud realms", reference)
            self.assertIn("us2", reference)


    def test_splunk_mcp_explicit_gateway_url_overrides_scs_region_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "rendered"
            o11y_token_file = tmp_path / "o11y.token"
            o11y_token_file.write_text("o11y-token-value", encoding="utf-8")
            o11y_token_file.chmod(0o600)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--gateway-mode",
                "o11y",
                "--gateway-url",
                "https://region-fra10.api.scs.splunk.com/system/mcp-gateway/v1/",
                "--scs-region",
                "pdx10",
                "--o11y-realm",
                "eu1",
                "--o11y-token-file",
                str(o11y_token_file),
                "--output-dir",
                str(output_dir),
                "--no-register-codex",
                "--no-configure-cursor",
                "--no-configure-claude",
                env=os.environ.copy(),
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            env_text = (output_dir / ".env.splunk-mcp").read_text(encoding="utf-8")
            self.assertIn(
                "SPLUNK_MCP_URL=https://region-fra10.api.scs.splunk.com/system/mcp-gateway/v1/",
                env_text,
            )


    def test_splunk_mcp_validate_uses_root_protected_resource_endpoint(self):
        script_text = (
            REPO_ROOT / "skills/splunk-mcp-server-setup/scripts/validate.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('/.well-known/oauth-protected-resource', script_text)
        self.assertNotIn('/services/.well-known/oauth-protected-resource', script_text)


    def test_splunk_mcp_validate_completion_probes_protocol_and_all_shipped_views(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, curl_log = mcp_validation_env(tmp_path)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/validate.sh",
                "--completion",
                "--accept-nonproduction-package",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, msg=output)
            self.assertIn("endpoint_services_mcp_initialize_http=200", output)
            self.assertIn("endpoint_services_mcp_initialized_notification_http=202", output)
            self.assertIn("endpoint_services_mcp_tools_list_has_get_info=true", output)
            self.assertIn("endpoint_services_mcp_tools_policy_ok=true", output)
            self.assertIn("endpoint_services_mcp_get_info_ok=true", output)
            self.assertIn("endpoint_mcp_tool_roles_http=200", output)
            self.assertIn("endpoint_mcp_guardrails_http=200", output)
            self.assertIn("endpoint_allowed_spl_cmds_http=200", output)
            self.assertIn("kv_mcp_tool_roles_http=200", output)
            self.assertIn("does not enforce it for internal HTTP calls", output)

            records = [
                json.loads(line)
                for line in curl_log.read_text(encoding="utf-8").splitlines()
            ]
            methods = []
            for record in records:
                if record["url"].endswith("/services/mcp") and record["data"].startswith("{"):
                    methods.append(json.loads(record["data"])["method"])
            self.assertEqual(
                methods,
                [
                    "ping",
                    "initialize",
                    "notifications/initialized",
                    "tools/list",
                    "tools/call",
                    "initialize",
                ],
            )
            mcp_records = [
                record for record in records if record["url"].endswith("/services/mcp")
            ]
            self.assertTrue(mcp_records)
            self.assertTrue(all(record["auth_scheme"] == "bearer" for record in mcp_records))
            self.assertTrue(all(record["quiet_config"] for record in mcp_records))
            self.assertTrue(all(record["https_protocol_only"] for record in mcp_records))
            self.assertTrue(all(record["no_redirects"] for record in mcp_records))
            self.assertTrue(all(record["globbing_disabled"] for record in mcp_records))
            self.assertTrue(
                all(
                    "MCP-Protocol-Version: 2025-06-18" in record["headers"]
                    for record in mcp_records
                )
            )

            urls = {record["url"] for record in records}
            for endpoint in ("mcp_tool_roles", "mcp_guardrails", "allowed_spl_cmds"):
                self.assertIn(
                    "https://splunk.example.invalid:8089/servicesNS/nobody/"
                    f"Splunk_MCP_Server/{endpoint}?output_mode=json",
                    urls,
                )
            self.assertIn(
                "https://splunk.example.invalid:8089/servicesNS/nobody/"
                "Splunk_MCP_Server/storage/collections/config/mcp_tool_roles?output_mode=json",
                urls,
            )
            for view_name in ("dashboard", "monitoring", "tools", "tool_settings"):
                self.assertIn(
                    "https://splunk.example.invalid:8089/servicesNS/nobody/"
                    f"Splunk_MCP_Server/data/ui/views/{view_name}?output_mode=json",
                    urls,
                )


    def test_splunk_mcp_validate_rejects_pre_131_app_and_missing_view(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _ = mcp_validation_env(tmp_path)
            env["MCP_VALIDATION_APP_VERSION"] = "1.3.0"
            env["MCP_VALIDATION_MISSING_VIEW"] = "monitoring"

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/validate.sh",
                "--completion",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, msg=output)
            self.assertIn("Splunk MCP Server 1.3.1 or newer is required; found 1.3.0", output)
            self.assertIn("Shipped view monitoring is not visible (HTTP 404)", output)

    def test_splunk_mcp_completion_blocks_unapproved_vendor_release(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env, _ = mcp_validation_env(Path(tmpdir))

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/validate.sh",
                "--completion",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, msg=output)
            self.assertIn("is not production-approved", output)
            self.assertIn("blocked_pending_vendor_security_fixes", output)

    def test_splunk_mcp_completion_requires_encrypted_bearer_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env, _ = mcp_validation_env(Path(tmpdir))
            env.pop("SPLUNK_MCP_BEARER_TOKEN_FILE")

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/validate.sh",
                "--completion",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, msg=output)
            self.assertIn("requires --mcp-bearer-token-file", output)

    def test_splunk_mcp_completion_rejects_unreviewed_enabled_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env, _ = mcp_validation_env(Path(tmpdir))
            env["MCP_VALIDATION_EXTRA_TOOL"] = "splunk_run_query"

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/validate.sh",
                "--completion",
                "--accept-nonproduction-package",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, msg=output)
            self.assertIn("endpoint_services_mcp_tools_policy_ok=false", output)
            self.assertIn("do not exactly match the reviewed allowlist", output)

    def test_splunk_mcp_existing_platform_workflow_requires_review_acknowledgement(self):
        env = os.environ.copy()
        env.update(
            {
                "SPLUNK_PLATFORM": "enterprise",
                "SPLUNK_TARGET_ROLE": "search-tier",
            }
        )

        result = self.run_script(
            "skills/splunk-mcp-server-setup/scripts/setup.sh",
            "--timeout",
            "90",
            env=env,
        )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, msg=output)
        self.assertIn("workflows are blocked", output)

    def test_splunk_mcp_approved_workflow_rejects_stale_installed_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env, _ = mcp_validation_env(tmp_path)
            fake_python = Path(env["PATH"].split(os.pathsep, 1)[0]) / "python3"
            real_python = sys.executable
            write_executable(
                fake_python,
                f"""\
                #!{real_python}
                import os
                import sys

                if any(arg.endswith("package-manifest.json") for arg in sys.argv[1:]):
                    sys.stdin.read()
                    print(
                        "1.3.2\\tsplunk-mcp-server_132.tgz\\t"
                        + "0" * 64
                        + "\\ttrue\\tapproved"
                    )
                    raise SystemExit(0)
                os.execv({real_python!r}, [{real_python!r}, *sys.argv[1:]])
                """,
            )

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--timeout",
                "90",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, msg=output)
            self.assertIn("Installed Splunk_MCP_Server version 1.3.1", output)
            self.assertIn("reviewed version 1.3.2", output)

    def test_splunk_mcp_approved_install_binds_platform_client_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            archive_path = REPO_ROOT / "splunk-ta/splunk-mcp-server_131.tgz"
            if not archive_path.is_file():
                self.skipTest("Splunk MCP Server 1.3.1 archive is not present in this checkout")
            env, _ = mcp_validation_env(tmp_path)
            env["SPLUNK_URI"] = "https://127.0.0.1:8089"
            fake_python = Path(env["PATH"].split(os.pathsep, 1)[0]) / "python3"
            real_python = sys.executable
            write_executable(
                fake_python,
                f"""\
                #!{real_python}
                import os
                import sys

                if any(arg.endswith("package-manifest.json") for arg in sys.argv[1:]):
                    sys.stdin.read()
                    print(
                        "1.3.1\\tsplunk-mcp-server_131.tgz\\t"
                        "fa380909ba24dcea155d59f9dccc67fd83d99b1d9595681183c6467bacdf70d3"
                        "\\ttrue\\tapproved"
                    )
                    raise SystemExit(0)
                os.execv({real_python!r}, [{real_python!r}, *sys.argv[1:]])
                """,
            )

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--install",
                "--render-clients",
                "--mcp-url",
                "https://different.example.invalid:8089/services/mcp",
                "--output-dir",
                str(tmp_path / "rendered"),
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, msg=output)
            self.assertIn("does not identify the same reviewed Splunk endpoint", output)


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
                "--accept-nonproduction-package",
                "--no-register-codex",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            workspace_json = json.loads((cursor_dir / "mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(workspace_json["notes"], {"keep": True})
            self.assertEqual(workspace_json["mcpServers"]["existing"]["command"], "/bin/echo")
            self.assertEqual(workspace_json["mcpServers"]["splunk-merge"]["command"], "node")
            self.assertEqual(len(workspace_json["mcpServers"]["splunk-merge"]["args"]), 1)
            self.assertEqual(
                Path(workspace_json["mcpServers"]["splunk-merge"]["args"][0]).resolve(),
                (output_dir / "run-splunk-mcp.js").resolve(),
            )
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
                "--accept-nonproduction-package",
                "--no-register-codex",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            workspace_json = json.loads((workspace_dir / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(workspace_json["mcpServers"]["splunk-relative"]["command"], "node")
            self.assertEqual(
                workspace_json["mcpServers"]["splunk-relative"]["args"],
                ["${workspaceFolder}/rendered/run-splunk-mcp.js"],
            )
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
                "--accept-nonproduction-package",
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
                    "--accept-nonproduction-package",
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
            self.assertEqual(workspace_json["mcpServers"]["splunk-default-workspace"]["command"], "node")
            self.assertEqual(len(workspace_json["mcpServers"]["splunk-default-workspace"]["args"]), 1)
            self.assertEqual(
                Path(workspace_json["mcpServers"]["splunk-default-workspace"]["args"][0]).resolve(),
                (output_dir / "run-splunk-mcp.js").resolve(),
            )


    def test_mcp_setup_repeated_runs_update_codex_registration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            home_dir = tmp_path / "home"
            output_dir_one = tmp_path / "rendered-one"
            output_dir_two = tmp_path / "rendered-two"
            token_file = tmp_path / "splunk.token"
            home_dir.mkdir()

            write_executable(
                bin_dir / "codex",
                """\
                #!/usr/bin/env python3
                import json, os, sys
                store = os.path.join(os.environ.get("HOME", "/tmp"), ".codex-mock-store")
                os.makedirs(store, exist_ok=True)
                args = sys.argv[1:]
                if len(args) >= 4 and args[0] == "mcp" and args[1] == "add":
                    name = args[2]
                    cmd = args[4] if len(args) > 4 else ""
                    cmd_args = args[5:] if len(args) > 5 else []
                    data = {"name": name, "transport": {"type": "stdio", "command": cmd, "args": cmd_args}}
                    with open(os.path.join(store, name + ".json"), "w") as f:
                        json.dump(data, f)
                elif len(args) >= 3 and args[0] == "mcp" and args[1] == "get":
                    name = args[2]
                    path = os.path.join(store, name + ".json")
                    if not os.path.exists(path):
                        print(f"Error: server '{name}' not found", file=sys.stderr)
                        sys.exit(1)
                    with open(path) as f:
                        data = json.load(f)
                    print(json.dumps(data))
                else:
                    print(f"mock codex: unsupported args: {args}", file=sys.stderr)
                    sys.exit(1)
                """,
            )

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["HOME"] = str(home_dir)

            first = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--accept-nonproduction-package",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir_one),
                "--client-name",
                "splunk-repeat",
                "--no-configure-cursor",
                "--no-configure-claude",
                env=env,
            )
            self.assertEqual(first.returncode, 0, msg=first.stdout + first.stderr)

            second = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--accept-nonproduction-package",
                "--mcp-url",
                "https://splunk-two.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir_two),
                "--client-name",
                "splunk-repeat",
                "--no-configure-cursor",
                "--no-configure-claude",
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
            self.assertEqual(data["transport"]["command"], "node")
            self.assertEqual(len(data["transport"]["args"]), 1)
            self.assertEqual(
                Path(data["transport"]["args"][0]).resolve(),
                (home_dir / ".codex" / "mcp-bridges" / "splunk-repeat" / "run-splunk-mcp.js").resolve(),
            )
            stable_env = (home_dir / ".codex" / "mcp-bridges" / "splunk-repeat" / ".env.splunk-mcp").read_text(
                encoding="utf-8"
            )
            self.assertIn("https://splunk-two.example.invalid:8089/services/mcp", stable_env)


    def test_repo_cursor_config_tracks_workspace_relative_rendered_bundle(self):
        config = json.loads((REPO_ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))

        self.assertEqual(
            config,
            {
                "mcpServers": {
                    "splunk-mcp": {
                        "type": "stdio",
                        "command": "node",
                        "args": ["${workspaceFolder}/splunk-mcp-rendered/run-splunk-mcp.js"],
                    },
                    "splunk-cisco-skills": {
                        "type": "stdio",
                        "command": "python3",
                        "args": ["-I", "${workspaceFolder}/agent/run-splunk-cisco-skills-mcp.py"],
                        "env": {
                            "SPLUNK_SKILLS_MCP_ENABLE_EXECUTION": "1",
                            "SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION": "0",
                            "SPLUNK_SKILLS_MCP_ALLOW_MUTATION": "0",
                        },
                    }
                }
            },
        )

    def test_repo_mcp_bridge_wrapper_exists_and_is_not_ignored(self):
        bridge = REPO_ROOT / "splunk-mcp-rendered" / "run-splunk-mcp.js"
        self.assertTrue(bridge.is_file(), "repo MCP configs must point at an available JS bridge")

        result = subprocess.run(
            ["git", "check-ignore", "--quiet", str(bridge.relative_to(REPO_ROOT))],
            cwd=REPO_ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 1, "the root MCP bridge must be tracked, not gitignored")

    def test_repo_mcp_bridge_wrapper_matches_setup_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "rendered"
            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--output-dir",
                str(output_dir),
                "--no-register-codex",
                "--no-configure-cursor",
                "--no-configure-claude",
                env=os.environ.copy(),
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertEqual(
                (REPO_ROOT / "splunk-mcp-rendered" / "run-splunk-mcp.js").read_bytes(),
                (output_dir / "run-splunk-mcp.js").read_bytes(),
            )

    def test_mcp_setup_writes_claude_mcp_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            workspace_dir = tmp_path / "workspace"
            workspace_dir.mkdir()
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "splunk.token"

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)

            env = os.environ.copy()
            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--accept-nonproduction-package",
                "--mcp-url",
                "https://splunk.example:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--client-name",
                "splunk-claude-test",
                "--no-register-codex",
                "--no-configure-cursor",
                "--cursor-workspace",
                str(workspace_dir),
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)

            claude_config_path = workspace_dir / ".mcp.json"
            self.assertTrue(claude_config_path.exists(), ".mcp.json should be written to workspace")

            config = json.loads(claude_config_path.read_text(encoding="utf-8"))
            self.assertIn("splunk-claude-test", config["mcpServers"])
            self.assertEqual(config["mcpServers"]["splunk-claude-test"]["type"], "stdio")

    def test_mcp_setup_merges_existing_claude_mcp_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            workspace_dir = tmp_path / "workspace"
            workspace_dir.mkdir()
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "splunk.token"

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)

            existing_config = {
                "mcpServers": {
                    "other-server": {
                        "type": "stdio",
                        "command": "/usr/local/bin/other-mcp",
                        "args": [],
                    }
                }
            }
            (workspace_dir / ".mcp.json").write_text(
                json.dumps(existing_config, indent=2), encoding="utf-8"
            )

            env = os.environ.copy()
            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--accept-nonproduction-package",
                "--mcp-url",
                "https://splunk.example:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--client-name",
                "splunk-merged",
                "--no-register-codex",
                "--no-configure-cursor",
                "--cursor-workspace",
                str(workspace_dir),
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)

            config = json.loads((workspace_dir / ".mcp.json").read_text(encoding="utf-8"))
            self.assertIn("other-server", config["mcpServers"], "existing entry should be preserved")
            self.assertIn("splunk-merged", config["mcpServers"], "new entry should be added")

    def test_repo_claude_mcp_config_tracks_rendered_bundle(self):
        config = json.loads((REPO_ROOT / ".mcp.json").read_text(encoding="utf-8"))

        self.assertEqual(
            config,
            {
                "mcpServers": {
                    "splunk-mcp": {
                        "type": "stdio",
                        "command": "node",
                        "args": ["./splunk-mcp-rendered/run-splunk-mcp.js"],
                    },
                    "splunk-cisco-skills": {
                        "type": "stdio",
                        "command": "python3",
                        "args": ["-I", "./agent/run-splunk-cisco-skills-mcp.py"],
                        "env": {
                            "SPLUNK_SKILLS_MCP_ENABLE_EXECUTION": "1",
                            "SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION": "0",
                            "SPLUNK_SKILLS_MCP_ALLOW_MUTATION": "0",
                        },
                    }
                }
            },
        )
