from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import parse


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTER = REPO_ROOT / "skills/splunk-appdynamics-controller-admin-setup/scripts/license_usage_report.sh"
REPORTER_PY = REPO_ROOT / "skills/splunk-appdynamics-controller-admin-setup/scripts/license_usage_report.py"


def load_reporter_module():
    spec = importlib.util.spec_from_file_location("appd_license_usage_report", REPORTER_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def unsigned_jwt(payload: dict[str, object]) -> str:
    def segment(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{segment({'alg': 'none', 'typ': 'JWT'})}.{segment(payload)}.signature"


class LicenseApiHandler(BaseHTTPRequestHandler):
    fail_license_rules = False
    access_token = "test-access-token"
    seen_accept_headers: list[str] = []

    def log_message(self, format: str, *args: object) -> None:
        return

    def _write_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/controller/api/oauth/access_token":
            self._write_json({"error": "not found"}, 404)
            return
        type(self).seen_accept_headers.append(self.headers.get("Accept", ""))
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        params = parse.parse_qs(body)
        if params.get("client_id") != ["automation-client@customer1"]:
            self._write_json({"error": "bad client"}, 401)
            return
        self._write_json({"access_token": type(self).access_token, "token_type": "bearer"})

    def do_GET(self) -> None:
        type(self).seen_accept_headers.append(self.headers.get("Accept", ""))
        if self.headers.get("Authorization") != f"Bearer {type(self).access_token}":
            self._write_json({"error": "unauthorized"}, 401)
            return
        parsed = parse.urlparse(self.path)
        path = parsed.path
        query = parse.parse_qs(parsed.query)
        if path == "/controller/licensing/v1/account/1965/info":
            self._write_json(
                {
                    "accountId": 1965,
                    "packages": [
                        {
                            "packageName": "ENTERPRISE",
                            "type": "PAID",
                            "kind": "INFRASTRUCTURE_BASED",
                            "family": "APM",
                            "licenseUnits": "100",
                            "startDate": "2026-01-01T00:00:00Z",
                            "expirationDate": "2027-01-01T00:00:00Z",
                        }
                    ],
                }
            )
        elif path == "/controller/licensing/v1/usage/account/1965":
            if query.get("includeEntityTypes") != ["true"] or query.get("includeConsumptionBased") != ["true"]:
                self._write_json({"error": "missing rich usage flags"}, 400)
                return
            self._write_json(usage_payload("account", "license-secret-key"))
        elif path == "/controller/rest/applications":
            self._write_json([{"id": 42, "name": "Checkout"}])
        elif path == "/controller/licensing/v1/account/1965/grouped-usage/application/by-id":
            if query.get("appId") != ["42"]:
                self._write_json({"error": "missing app id"}, 400)
                return
            self._write_json(
                {
                    "vCpuTotal": 4,
                    "items": {
                        "42": {
                            "appId": 42,
                            "appName": "Checkout",
                            "vCpu": 4,
                            "nodes": [{"nodeName": "checkout-node"}],
                            "containers": [],
                            "agents": [{"type": "APP_AGENT", "licenseKey": "license-secret-key"}],
                            "hosts": {"items": {"host-a": {"host": "host-a", "vCpu": 4}}},
                        }
                    },
                }
            )
        elif path == "/controller/licensing/v1/account/1965/grouped-usage/host":
            if query.get("hostId") != ["host-a"]:
                self._write_json({"error": "missing host id"}, 400)
                return
            self._write_json(
                {
                    "vCpuTotal": 4,
                    "hosts": {
                        "vCpuTotal": 4,
                        "items": {
                            "host-a": {
                                "host": "host-a",
                                "vCpu": 4,
                                "nodes": [{"nodeName": "checkout-node"}],
                                "containers": [],
                                "agents": [{"type": "APP_AGENT", "licenseKey": "license-secret-key"}],
                            }
                        }
                    },
                }
            )
        elif path == "/controller/licensing/v1/account/1965/allocation":
            self._write_json(
                [
                    {
                        "id": "alloc-1",
                        "name": "Production",
                        "licenseKey": "license-secret-key",
                        "filters": [{"type": "APPLICATION", "value": "42"}],
                        "limits": [{"package": "ENTERPRISE", "units": 50}],
                        "tags": ["prod"],
                    }
                ]
            )
        elif path == "/controller/licensing/v1/usage/account/1965/allocation/license-secret-key":
            self._write_json(usage_payload("allocation", "license-secret-key"))
        elif path == "/controller/mds/v1/license/rules":
            if self.fail_license_rules:
                self._write_json({"error": "forbidden", "access_key": "account-accesskey-123"}, 403)
                return
            self._write_json(
                [
                    {
                        "id": "rule-1",
                        "name": "Default",
                        "enabled": True,
                        "access_key": "account-accesskey-123",
                        "total_licenses": 100,
                        "peak_usage": 25,
                        "entitlements": [{"license_module_type": "JAVA", "number_of_licenses": 100}],
                        "constraints": [],
                    }
                ]
            )
        else:
            self._write_json({"error": f"not found: {path}"}, 404)


def usage_payload(rule_name: str, license_key: str) -> dict[str, object]:
    return {
        "accountId": 1965,
        "licenseRule": {"id": "rule-1", "name": rule_name, "licenseKey": license_key},
        "packages": [
            {
                "name": "ENTERPRISE",
                "unitUsages": [
                    {
                        "usageType": "APM",
                        "granularityInMinutes": 60,
                        "data": {
                            "timestamp": "2026-05-28T00:00:00Z",
                            "provisioned": {"max": 100},
                            "used": {"max": 25},
                            "registrations": [{"type": "APP_AGENT", "registered": {"max": 3}}],
                        },
                    }
                ],
            }
        ],
    }


def run_reporter(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(REPORTER), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def secret_file(tmp_path: Path, value: str = "client-secret") -> Path:
    path = tmp_path / "secret.txt"
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def start_server(handler: type[BaseHTTPRequestHandler] = LicenseApiHandler) -> tuple[HTTPServer, str]:
    handler.seen_accept_headers = []  # type: ignore[attr-defined]
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def test_license_usage_report_oauth_deep_outputs_and_redacts(tmp_path: Path) -> None:
    server, controller_url = start_server()
    output_dir = tmp_path / "report"
    try:
        result = run_reporter(
            "--controller-url",
            controller_url,
            "--account-name",
            "customer1",
            "--account-id",
            "1965",
            "--api-client-name",
            "automation-client",
            "--client-secret-file",
            str(secret_file(tmp_path)),
            "--from",
            "2026-05-27T00:00:00Z",
            "--to",
            "2026-05-28T00:00:00Z",
            "--granularity-minutes",
            "60",
            "--deep",
            "--include-raw",
            "--output-dir",
            str(output_dir),
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stderr + result.stdout
    assert any("application/vnd.appd.cntrl+json" in value for value in LicenseApiHandler.seen_accept_headers)
    markdown = (output_dir / "license-usage-report.md").read_text(encoding="utf-8")
    assert "# AppDynamics License Consumption Report" in markdown
    assert "## Executive Summary" in markdown
    assert "## Consumption Highlights" in markdown
    assert "| ENTERPRISE | APM | 25 | 25 | 100 | 25.0% |" in markdown
    assert "Permission Troubleshooting Context" not in markdown
    assert "Checkout" in markdown
    assert "Production" in markdown
    assert "2026-05-27T01:00:00Z" not in markdown
    assert "license-secret-key" not in markdown

    payload = json.loads((output_dir / "license-usage-report.json").read_text(encoding="utf-8"))
    assert payload["succeeded"] is True
    assert payload["auth_context"]["token_format"] == "opaque"
    assert any(endpoint["name"] == "account_usage" and endpoint["ok"] for endpoint in payload["endpoint_results"])
    assert "license-secret-key" not in json.dumps(payload)
    assert any(
        endpoint["name"] == "allocation_usage:Production"
        and endpoint["path"].endswith("/allocation/<redacted:license-key>?dateFrom=2026-05-27T00%3A00%3A00Z&dateTo=2026-05-28T00%3A00%3A00Z&granularityMinutes=60&includeEntityTypes=true")
        for endpoint in payload["endpoint_results"]
    )

    csv_text = (output_dir / "license-usage-report.csv").read_text(encoding="utf-8")
    assert "ENTERPRISE" in csv_text
    assert "license-secret-key" not in csv_text

    raw_text = "\n".join(path.read_text(encoding="utf-8") for path in (output_dir / "raw").glob("*.json"))
    assert "<redacted:license-key>" in raw_text
    assert "account-accesskey-123" not in raw_text


def test_license_usage_report_degrades_optional_license_rules(tmp_path: Path) -> None:
    class FailingRulesHandler(LicenseApiHandler):
        fail_license_rules = True

    server, controller_url = start_server(FailingRulesHandler)
    output_dir = tmp_path / "report"
    try:
        result = run_reporter(
            "--controller-url",
            controller_url,
            "--account-name",
            "customer1",
            "--account-id",
            "1965",
            "--api-client-name",
            "automation-client",
            "--client-secret-file",
            str(secret_file(tmp_path)),
            "--from",
            "2026-05-27T00:00:00Z",
            "--to",
            "2026-05-28T00:00:00Z",
            "--deep",
            "--output-dir",
            str(output_dir),
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads((output_dir / "license-usage-report.json").read_text(encoding="utf-8"))
    license_rules = [endpoint for endpoint in payload["endpoint_results"] if endpoint["name"] == "license_rules"]
    assert license_rules and license_rules[0]["ok"] is False
    assert license_rules[0]["status_code"] == 403
    assert any("LICENSE_RULE" in warning and "Administration > API Clients" in warning for warning in payload["warnings"])
    assert "account-accesskey-123" not in json.dumps(payload)


def test_license_usage_report_warns_on_api_client_token_without_roles_when_forbidden(tmp_path: Path) -> None:
    class NoRoleTokenHandler(LicenseApiHandler):
        fail_license_rules = True
        access_token = unsigned_jwt(
            {
                "idType": "API_CLIENT",
                "sub": "automation-client",
                "acctName": "customer1",
                "acctId": "11111111-2222-3333-4444-555555555555",
                "tntId": "66666666-7777-8888-9999-aaaaaaaaaaaa",
                "roleIds": [],
                "acctPerm": [],
            }
        )

    server, controller_url = start_server(NoRoleTokenHandler)
    output_dir = tmp_path / "report"
    try:
        result = run_reporter(
            "--controller-url",
            controller_url,
            "--account-name",
            "customer1",
            "--account-id",
            "1965",
            "--api-client-name",
            "automation-client",
            "--client-secret-file",
            str(secret_file(tmp_path)),
            "--from",
            "2026-05-27T00:00:00Z",
            "--to",
            "2026-05-28T00:00:00Z",
            "--deep",
            "--output-dir",
            str(output_dir),
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads((output_dir / "license-usage-report.json").read_text(encoding="utf-8"))
    assert payload["auth_context"]["id_type"] == "API_CLIENT"
    assert payload["auth_context"]["role_count"] == 0
    assert payload["auth_context"]["account_permission_count"] == 0
    assert any("Administration > API Clients" in warning for warning in payload["warnings"])
    report_text = (output_dir / "license-usage-report.md").read_text(encoding="utf-8")
    assert "Permission Troubleshooting Context" in report_text
    assert NoRoleTokenHandler.access_token not in json.dumps(payload)
    assert NoRoleTokenHandler.access_token not in report_text


def test_license_usage_report_uses_application_inventory_when_grouped_usage_empty(tmp_path: Path) -> None:
    class EmptyGroupedUsageHandler(LicenseApiHandler):
        def do_GET(self) -> None:
            parsed = parse.urlparse(self.path)
            if parsed.path == "/controller/licensing/v1/account/1965/grouped-usage/application/by-id":
                if self.headers.get("Authorization") != "Bearer test-access-token":
                    self._write_json({"error": "unauthorized"}, 401)
                    return
                self._write_json({"items": {}, "vCpuTotal": 0})
                return
            super().do_GET()

    server, controller_url = start_server(EmptyGroupedUsageHandler)
    output_dir = tmp_path / "report"
    try:
        result = run_reporter(
            "--controller-url",
            controller_url,
            "--account-name",
            "customer1",
            "--account-id",
            "1965",
            "--api-client-name",
            "automation-client",
            "--client-secret-file",
            str(secret_file(tmp_path)),
            "--from",
            "2026-05-27T00:00:00Z",
            "--to",
            "2026-05-28T00:00:00Z",
            "--deep",
            "--output-dir",
            str(output_dir),
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads((output_dir / "license-usage-report.json").read_text(encoding="utf-8"))
    assert payload["sections"]["applications"] == [
        {
            "agents": "",
            "containers": "",
            "id": 42,
            "name": "Checkout",
            "nodes": "",
            "source": "application_inventory",
            "v_cpu": "",
        }
    ]


def test_license_usage_report_rejects_bad_secret_file_permissions(tmp_path: Path) -> None:
    bad_secret = tmp_path / "secret.txt"
    bad_secret.write_text("client-secret", encoding="utf-8")
    bad_secret.chmod(0o644)

    result = run_reporter(
        "--controller-url",
        "http://127.0.0.1:1",
        "--account-name",
        "customer1",
        "--account-id",
        "1965",
        "--api-client-name",
        "automation-client",
        "--client-secret-file",
        str(bad_secret),
    )

    assert result.returncode == 2
    assert "must be chmod 600" in result.stderr


def test_license_usage_report_rejects_secret_value_as_file_path() -> None:
    result = run_reporter(
        "--controller-url",
        "http://127.0.0.1:1",
        "--account-name",
        "customer1",
        "--account-id",
        "1965",
        "--api-client-name",
        "automation-client",
        "--client-secret-file",
        "76fd4423-1111-2222-3333-444444444444",
    )

    assert result.returncode == 2
    assert "must point at a chmod-600 file" in result.stderr
    assert "inline secret" in result.stderr


def test_license_usage_report_normalizes_controller_url_and_explains_account_id(tmp_path: Path) -> None:
    reporter = load_reporter_module()
    args = reporter.parse_args(
        [
            "--controller-url",
            "customer.saas.appdynamics.com",
            "--account-name",
            "customer1",
            "--account-id",
            "1965",
            "--oauth-token-file",
            str(secret_file(tmp_path, "opaque-token")),
        ]
    )
    assert args.controller_url == "https://customer.saas.appdynamics.com"

    try:
        reporter.parse_args(
            [
                "--controller-url",
                "https://customer.saas.appdynamics.com",
                "--account-name",
                "customer1",
                "--account-id",
                "uylojnqg6e81",
                "--oauth-token-file",
                str(secret_file(tmp_path, "opaque-token")),
            ]
        )
    except reporter.ConfigError as exc:
        assert "numeric AppDynamics License API accountId" in str(exc)
        assert "OAuth acctId/tntId" in str(exc)
    else:
        raise AssertionError("expected ConfigError for non-numeric account id")
