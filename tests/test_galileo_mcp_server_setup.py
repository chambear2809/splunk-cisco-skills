"""Regression coverage for the Galileo MCP catalog and product boundaries."""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/galileo-mcp-server-setup"
RENDER = SKILL_DIR / "scripts/render_assets.py"
PROBE = SKILL_DIR / "scripts/probe_mcp.py"
AUDIT = SKILL_DIR / "scripts/audit_product_coverage.py"
DEEP_AUDIT = SKILL_DIR / "scripts/deep_audit.sh"


def load_script(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mcp_snapshot_matches_renderer_and_live_review_metadata() -> None:
    render = load_script(RENDER, "galileo_mcp_render_catalog")
    probe = load_script(PROBE, "galileo_mcp_probe_catalog")

    assert render.EXPECTED_SERVER_NAME == probe.EXPECTED_SERVER_NAME == "EvalsInIDEServer"
    assert render.EXPECTED_SERVER_VERSION == probe.EXPECTED_SERVER_VERSION == "1.28.1"
    assert render.CATALOG_REVIEW_DATE == "2026-07-08"
    assert {item["name"] for item in render.TOOL_CATALOG} == set(probe.EXPECTED_TOOLS)
    assert {
        item["name"]: item["schema_sha256"] for item in render.TOOL_CATALOG
    } == {
        name: item["schema_sha256"] for name, item in probe.EXPECTED_TOOLS.items()
    }


def test_server_identity_is_part_of_fail_on_drift_classification() -> None:
    probe = load_script(PROBE, "galileo_mcp_probe_drift")
    clean = {
        "server_drift": [],
        "unknown_tools": [],
        "missing_tools": [],
        "schema_drift": [],
        "prompts_count": 0,
        "resources_count": 0,
    }

    assert probe.report_has_drift(clean) is False
    assert probe.report_has_drift(
        {**clean, "server_drift": [{"field": "version", "live": "future"}]}
    ) is True


@pytest.mark.parametrize(
    ("mcp_url", "console_url"),
    [
        ("ftp://api.galileo.ai/mcp/http/mcp", ""),
        ("http://api.galileo.ai/mcp/http/mcp", ""),
        ("https://user:secret@api.galileo.ai/mcp/http/mcp", ""),
        ("https://api.galileo.ai/mcp/http/mcp?token=secret", ""),
        ("https://api.galileo.ai:bad/mcp/http/mcp", ""),
        ("", "https://console.galileo.ai/path"),
        ("", "http://console.galileo.ai"),
        (
            "https://api.galileo.ai/mcp/http/mcp",
            "https://user:secret@console.galileo.ai/",
        ),
    ],
)
def test_mcp_url_derivation_rejects_unsafe_urls(mcp_url: str, console_url: str) -> None:
    render = load_script(RENDER, "galileo_mcp_render_unsafe_url")
    probe = load_script(PROBE, "galileo_mcp_probe_unsafe_url")

    for module in (render, probe):
        with pytest.raises(ValueError):
            module.derive_mcp_url(mcp_url, console_url)


def test_mcp_url_derivation_allows_loopback_http_for_local_validation() -> None:
    render = load_script(RENDER, "galileo_mcp_render_loopback_url")
    probe = load_script(PROBE, "galileo_mcp_probe_loopback_url")
    endpoint = "http://127.0.0.1:43199/mcp/http/mcp"

    for module in (render, probe):
        assert module.derive_mcp_url(endpoint, "") == endpoint


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_stdio_bridge_accepts_bracketed_ipv6_loopback_http() -> None:
    bridge = SKILL_DIR / "assets/stdio_streamable_http_bridge.js"
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "GALILEO_API_KEY",
            "GALILEO_API_KEY_FILE",
            "GALILEO_MCP_ALLOW_HTTP",
            "GALILEO_MCP_URL",
        }
    }
    env.update(
        GALILEO_API_KEY="test-only-key",
        GALILEO_MCP_URL="http://[::1]:43199/mcp/http/mcp",
    )

    result = subprocess.run(
        ["node", str(bridge)],
        input="",
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "must use HTTPS outside loopback testing" not in result.stderr

    env["GALILEO_MCP_URL"] = "http://api.galileo.ai/mcp/http/mcp"
    remote_result = subprocess.run(
        ["node", str(bridge)],
        input="",
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        env=env,
    )

    assert remote_result.returncode != 0
    assert "must use HTTPS outside loopback testing" in remote_result.stderr


def test_authenticated_probe_rejects_redirect_without_forwarding_key(tmp_path: Path) -> None:
    probe = load_script(PROBE, "galileo_mcp_probe_redirect")
    secret = "redirect-sentinel-galileo-key"
    state = {"initial_key": None, "redirect_hit": False, "redirect_key": None}

    class RedirectHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            if self.path == "/v2/current_user":
                state["initial_key"] = self.headers.get("Galileo-API-Key")
                self.send_response(302)
                self.send_header("Location", "/redirect-sentinel")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            state["redirect_hit"] = True
            state["redirect_key"] = self.headers.get("Galileo-API-Key")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    key_file = tmp_path / "galileo.key"
    key_file.write_text(secret, encoding="utf-8")
    key_file.chmod(0o600)
    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        mcp_url = f"http://127.0.0.1:{server.server_port}/mcp/http/mcp"
        result = probe.auth_check(mcp_url, str(key_file), 5.0, False)

        assert result == {"ok": False, "status": 302, "error": "HTTP request rejected"}
        assert state["initial_key"] == secret
        assert state["redirect_hit"] is False
        assert state["redirect_key"] is None
        assert secret not in json.dumps(result)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


def test_authenticated_probe_rejects_non_loopback_cleartext_before_reading_key(
    tmp_path: Path,
) -> None:
    probe = load_script(PROBE, "galileo_mcp_probe_cleartext_auth")
    missing_key = tmp_path / "must-not-be-read.key"

    with pytest.raises(ValueError, match="must use HTTPS outside loopback"):
        probe.auth_check(
            "http://api.galileo.ai/mcp/http/mcp",
            str(missing_key),
            5.0,
            False,
        )


def test_july_release_has_explicit_mcp_product_boundary_rules() -> None:
    audit = load_script(AUDIT, "galileo_mcp_product_audit")
    ids = {rule["id"] for rule in audit.PRODUCT_RULES}
    assert {
        "ai_assistant_beta",
        "global_dashboards",
        "generic_alert_webhooks",
        "experiment_groups_playgrounds_ci",
        "large_dataset_batched_experiments",
    } <= ids

    matrix = (SKILL_DIR / "references/product-gap-matrix.md").read_text(encoding="utf-8")
    for marker in (
        "AI Assistant beta",
        "Global dashboards across projects and log streams",
        "Generic alert webhooks, payload v1.0",
        "Python SDK >=2.2.0",
        "Large-dataset batched Playground",
    ):
        assert marker in matrix


def test_product_audit_fails_on_a_newer_unreviewed_release() -> None:
    audit = load_script(AUDIT, "galileo_mcp_product_audit_future_release")
    matrix = (SKILL_DIR / "references/product-gap-matrix.md").read_text(encoding="utf-8")
    docs = f'{audit.FALLBACK_DOCS_INDEX}\n<Update label="2026-07-08">'

    failures = audit.missing_coverage(docs, matrix)

    assert {
        "id": "unreviewed_release",
        "reason": "newer_release_note_detected",
        "latest_documented_release": "2026-07-08",
        "latest_reviewed_release": "2026-07-07",
    } in failures


def test_product_audit_fails_when_release_date_markup_disappears() -> None:
    audit = load_script(AUDIT, "galileo_mcp_product_audit_missing_release_label")
    matrix = (SKILL_DIR / "references/product-gap-matrix.md").read_text(encoding="utf-8")
    docs = audit.RELEASE_LABEL_RE.sub("", audit.FALLBACK_DOCS_INDEX)

    failures = audit.missing_coverage(docs, matrix)

    assert {
        "id": "release_label_not_found",
        "reason": "release_note_date_markup_not_found",
        "latest_reviewed_release": "2026-07-07",
    } in failures


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_generated_stdio_bridge_supports_streamable_http_end_to_end(tmp_path: Path) -> None:
    secret = "test-only-galileo-key-never-log"
    cancellation_seen = threading.Event()
    state: dict[str, object] = {
        "requests": [],
        "delete_seen": False,
        "redirect_target_seen": False,
        "get_count": 0,
    }

    class FakeMcpHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def record(self, method: str, message: object = None) -> None:
            requests = state["requests"]
            assert isinstance(requests, list)
            requests.append(
                {
                    "method": method,
                    "message": message,
                    "api_key": self.headers.get("Galileo-API-Key"),
                    "accept": self.headers.get("Accept"),
                    "session": self.headers.get("Mcp-Session-Id"),
                    "protocol": self.headers.get("MCP-Protocol-Version"),
                }
            )

        def send_json(self, payload: object, *, session: bool = False) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if session:
                self.send_header("Mcp-Session-Id", "session-test")
            self.end_headers()
            self.wfile.write(body)

        def send_sse(self, payload: object) -> None:
            self.send_sse_events([payload])

        def send_sse_events(self, payloads: list[object]) -> None:
            body = "".join(
                f"event: message\ndata: {json.dumps(payload)}\n\n" for payload in payloads
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            length = int(self.headers.get("Content-Length", "0"))
            message = json.loads(self.rfile.read(length))
            self.record("POST", message)
            method = message.get("method")
            request_id = message.get("id")

            if self.path == "/redirect-target":
                state["redirect_target_seen"] = True
                self.send_response(204)
                self.end_headers()
            elif method == "initialize":
                self.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {
                                "tools": {},
                                "prompts": {},
                                "resources": {},
                            },
                            "serverInfo": {"name": "fake-galileo", "version": "1.0"},
                        },
                    },
                    session=True,
                )
            elif method == "notifications/initialized":
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif method == "notifications/cancelled":
                cancellation_seen.set()
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif method == "tools/list":
                self.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"tools": [{"name": "search_docs"}]},
                    }
                )
            elif method == "tools/call":
                cancellation_seen.wait(timeout=5)
                self.send_sse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "cancelled" if cancellation_seen.is_set() else "timeout",
                                }
                            ]
                        },
                    }
                )
            elif method == "prompts/list":
                self.send_json(
                    {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}
                )
            elif method == "resources/list":
                self.send_sse(
                    {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
                )
            elif method == "resources/templates/list":
                self.send_response(307)
                self.send_header("Location", "/redirect-target")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.send_response(400)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            self.record("GET")
            state["get_count"] = int(state["get_count"]) + 1
            get_count = int(state["get_count"])
            if get_count == 1:
                self.send_sse_events(
                    [
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/message",
                            "params": {"level": "info", "sequence": sequence},
                        }
                        for sequence in range(20)
                    ]
                )
            elif get_count == 2:
                self.send_sse(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/message",
                        "params": {"level": "info", "data": "reconnected"},
                    }
                )
            else:
                self.send_response(405)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            self.record("DELETE")
            state["delete_seen"] = True
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeMcpHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        output_dir = tmp_path / "rendered"
        endpoint = f"http://127.0.0.1:{server.server_port}/mcp/http/mcp"
        render_result = subprocess.run(
            [
                "python3",
                str(RENDER),
                "--output-dir",
                str(output_dir),
                "--client",
                "codex",
                "--mcp-url",
                endpoint,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert render_result.returncode == 0, render_result.stdout + render_result.stderr

        env_file = output_dir / "mcp/.env.galileo-mcp"
        env_file.write_text(
            f"GALILEO_MCP_URL={endpoint}\nGALILEO_API_KEY='{secret}'\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            env_file.chmod(0o644)
            permission_result = subprocess.run(
                ["node", str(output_dir / "mcp/run-galileo-mcp.js")],
                input="",
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
                env={
                    key: value
                    for key, value in os.environ.items()
                    if key
                    not in {"GALILEO_API_KEY", "GALILEO_API_KEY_FILE", "GALILEO_MCP_URL"}
                },
            )
            assert permission_result.returncode != 0
            assert "refusing non-owner-only .env.galileo-mcp" in permission_result.stderr
            assert secret not in permission_result.stderr
        env_file.chmod(0o600)

        process_env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"GALILEO_API_KEY", "GALILEO_API_KEY_FILE", "GALILEO_MCP_URL"}
        }
        process_env.update(
            GALILEO_MCP_MAX_BODY_BYTES="1024",
            GALILEO_MCP_SSE_RECONNECT_BASE_MS="10",
            GALILEO_MCP_SSE_RECONNECT_MAX_MS="50",
            GALILEO_MCP_SSE_STABLE_MS="1000",
        )
        process = subprocess.Popen(
            ["node", str(output_dir / "mcp/run-galileo-mcp.js")],
            cwd=REPO_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=process_env,
        )
        assert process.stdin and process.stdout and process.stderr

        output_queue: queue.Queue[str] = queue.Queue()

        def read_output() -> None:
            assert process.stdout
            for line in process.stdout:
                output_queue.put(line)

        output_thread = threading.Thread(target=read_output, daemon=True)
        output_thread.start()
        observed: list[dict[str, object]] = []
        received_by_id: dict[int, dict[str, object]] = {}

        def send(message: dict[str, object]) -> None:
            assert process.stdin
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def receive_id(request_id: int) -> dict[str, object]:
            if request_id in received_by_id:
                return received_by_id[request_id]
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    message = json.loads(output_queue.get(timeout=0.2))
                except queue.Empty:
                    continue
                observed.append(message)
                message_id = message.get("id")
                if isinstance(message_id, int):
                    received_by_id[message_id] = message
                if request_id in received_by_id:
                    return received_by_id[request_id]
            pytest.fail(f"timed out waiting for MCP response id {request_id}: {observed}")

        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1"},
                },
            }
        )
        assert receive_id(1)["result"]["protocolVersion"] == "2025-03-26"
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        cases = [(2, "tools/list", {})]
        responses = {}
        for request_id, method, params in cases:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            responses[request_id] = receive_id(request_id)

        # A slow tool call must not block either another normal request or the
        # cancellation notification that releases it.
        send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "slow_tool", "arguments": {}},
            }
        )
        send({"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}})
        send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 3, "reason": "test cancellation"},
            }
        )
        responses[7] = receive_id(7)
        responses[3] = receive_id(3)

        for request_id, method, params in [
            (4, "prompts/list", {}),
            (5, "resources/list", {}),
            (6, "resources/templates/list", {}),
        ]:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            responses[request_id] = receive_id(request_id)

        assert responses[2]["result"]["tools"][0]["name"] == "search_docs"
        assert responses[7]["result"]["tools"][0]["name"] == "search_docs"
        assert responses[3]["result"]["content"][0]["text"] == "cancelled"
        assert cancellation_seen.is_set()
        assert responses[4]["result"] == {"prompts": []}
        assert responses[5]["result"] == {"resources": []}
        assert responses[6]["error"]["data"] == {"http_status": 307}

        event_deadline = time.monotonic() + 5
        while time.monotonic() < event_deadline:
            has_last_large_stream_event = any(
                item.get("params", {}).get("sequence") == 19 for item in observed
            )
            has_reconnected_event = any(
                item.get("params", {}).get("data") == "reconnected" for item in observed
            )
            if int(state["get_count"]) >= 3 and has_last_large_stream_event and has_reconnected_event:
                break
            try:
                observed.append(json.loads(output_queue.get(timeout=0.1)))
            except queue.Empty:
                continue

        process.stdin.close()
        assert process.wait(timeout=10) == 0
        stderr = process.stderr.read()
        output_thread.join(timeout=2)

        while not output_queue.empty():
            observed.append(json.loads(output_queue.get_nowait()))
        assert int(state["get_count"]) >= 3
        assert any(item.get("params", {}).get("sequence") == 19 for item in observed)
        assert any(item.get("params", {}).get("data") == "reconnected" for item in observed)
        assert state["delete_seen"] is True
        assert state["redirect_target_seen"] is False
        assert secret not in stderr
        assert all(secret not in json.dumps(item) for item in observed)

        requests = state["requests"]
        assert isinstance(requests, list)
        assert requests
        assert all(item["api_key"] == secret for item in requests)
        assert all(
            item["accept"] == "application/json, text/event-stream" for item in requests
        )
        initialize = next(
            item
            for item in requests
            if isinstance(item["message"], dict)
            and item["message"].get("method") == "initialize"
        )
        assert initialize["session"] is None
        subsequent = [item for item in requests if item is not initialize]
        assert all(item["session"] == "session-test" for item in subsequent)
        assert all(item["protocol"] == "2025-03-26" for item in subsequent)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


def test_offline_deep_audit_gate_passes() -> None:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        ["bash", str(DEEP_AUDIT), "--skip-live"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Galileo MCP Server skill passed" in result.stdout + result.stderr
