"""Regression coverage for galileo-platform-setup."""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import importlib.util
import urllib.error
from argparse import Namespace
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/galileo-platform-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
VALIDATE = SKILL_DIR / "scripts/validate.sh"
RENDER = SKILL_DIR / "scripts/render_assets.py"
BRIDGE = SKILL_DIR / "scripts/galileo_to_splunk_hec.py"
LIFECYCLE = SKILL_DIR / "scripts/galileo_object_lifecycle.py"
LUNA = SKILL_DIR / "scripts/galileo_luna_scorers.py"
ALERT_RELAY = SKILL_DIR / "scripts/galileo_alert_webhook_relay.py"
GALILEO_CONSOLE_ARGS = ("--galileo-console-url", "https://console.demo-v2.galileocloud.io/")


def run_cmd(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def rendered_text(root: Path) -> str:
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def load_bridge() -> ModuleType:
    spec = importlib.util.spec_from_file_location("galileo_to_splunk_hec", BRIDGE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_script(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _query_args() -> Namespace:
    return Namespace(
        galileo_api_base="https://api.example.invalid",
        project_id="project-id",
        export_format="jsonl",
        max_records=None,
    )


def test_query_galileo_accepts_ndjson_content_type(monkeypatch) -> None:
    bridge = load_bridge()
    monkeypatch.setattr(bridge, "galileo_headers", lambda _args: {})
    monkeypatch.setattr(bridge, "build_export_records_request", lambda _args, _since: {})
    monkeypatch.setattr(
        bridge,
        "request_bytes",
        lambda *_args, **_kwargs: (b'{"id":"one"}\n{"id":"two"}\n', "application/x-ndjson"),
    )
    assert [item["id"] for item in bridge.query_galileo(_query_args(), None)] == ["one", "two"]


def test_query_galileo_falls_back_to_jsonl_for_generic_json(monkeypatch) -> None:
    bridge = load_bridge()
    monkeypatch.setattr(bridge, "galileo_headers", lambda _args: {})
    monkeypatch.setattr(bridge, "build_export_records_request", lambda _args, _since: {})
    monkeypatch.setattr(
        bridge,
        "request_bytes",
        lambda *_args, **_kwargs: (b'{"id":"one"}\n{"id":"two"}\n', "application/json"),
    )
    assert [item["id"] for item in bridge.query_galileo(_query_args(), None)] == ["one", "two"]


def test_query_galileo_parses_csv_exports(monkeypatch) -> None:
    bridge = load_bridge()
    args = _query_args()
    args.export_format = "csv"
    monkeypatch.setattr(bridge, "galileo_headers", lambda _args: {})
    monkeypatch.setattr(bridge, "build_export_records_request", lambda _args, _since: {})
    monkeypatch.setattr(
        bridge,
        "request_bytes",
        lambda *_args, **_kwargs: (
            b"id,type,updated_at\none,trace,2026-07-07T00:00:00Z\n",
            "text/csv",
        ),
    )

    assert bridge.query_galileo(args, None) == [
        {"id": "one", "type": "trace", "updated_at": "2026-07-07T00:00:00Z"}
    ]
    assert bridge.parse_csv_records('id,summary\none,"line one\nline two"\n') == [
        {"id": "one", "summary": "line one\nline two"}
    ]
    large_value = "x" * 150_000
    assert bridge.parse_csv_records(f"id,summary\none,{large_value}\n")[0]["summary"] == large_value


def test_query_galileo_parses_downloaded_csv(monkeypatch) -> None:
    bridge = load_bridge()
    args = _query_args()
    args.export_format = "csv"
    responses = iter(
        [
            (b'{"file_url":"https://download.example/export.csv"}', "application/json"),
            (b"id,type\none,trace\n", "application/octet-stream"),
        ]
    )
    monkeypatch.setattr(bridge, "galileo_headers", lambda _args: {})
    monkeypatch.setattr(bridge, "build_export_records_request", lambda _args, _since: {})
    requests: list[tuple[object, ...]] = []

    def request_bytes(*request_args, **_kwargs):
        requests.append(request_args)
        return next(responses)

    monkeypatch.setattr(bridge, "request_bytes", request_bytes)

    assert bridge.query_galileo(args, None) == [{"id": "one", "type": "trace"}]
    assert requests[1][1] == "https://download.example/export.csv"
    assert requests[1][2] == {}


@pytest.mark.parametrize(
    "api_base",
    [
        "http://api.example.com",
        "https://user:secret@api.example.com",
        "https://api.example.com/v2",
        "https://api.example.com?token=secret",
    ],
)
def test_export_bridge_rejects_unsafe_galileo_api_origins(api_base: str) -> None:
    bridge = load_bridge()

    with pytest.raises(SystemExit, match="Galileo API base"):
        bridge.parse_args(
            [
                "--project-id",
                "00000000-0000-4000-8000-000000000001",
                "--galileo-api-base",
                api_base,
            ]
        )


def test_export_bridge_supports_current_export_request_options() -> None:
    bridge = load_bridge()
    args = bridge.parse_args(
        [
            "--project-id",
            "00000000-0000-4000-8000-000000000001",
            "--export-format",
            "csv",
            "--export-computed-metrics-only",
            "--include-code-metric-metadata",
            "--limit",
            "25",
        ]
    )

    body = bridge.build_export_records_request(args)

    assert args.galileo_api_base == "https://api.galileo.ai"
    assert args.max_records == 25
    assert body["export_computed_metrics_only"] is True
    assert body["include_code_metric_metadata"] is True

    with pytest.raises(SystemExit, match="not supported with jsonl_flat"):
        bridge.parse_args(
            [
                "--project-id",
                "00000000-0000-4000-8000-000000000001",
                "--export-format",
                "jsonl_flat",
                "--export-computed-metrics-only",
            ]
        )


@pytest.mark.parametrize(("flag", "value"), [("--batch-size", "0"), ("--max-records", "-1")])
def test_export_bridge_rejects_nonpositive_limits(flag: str, value: str) -> None:
    bridge = load_bridge()

    with pytest.raises(SystemExit, match="positive integer"):
        bridge.parse_args(
            [
                "--project-id",
                "00000000-0000-4000-8000-000000000001",
                flag,
                value,
            ]
        )


def test_export_download_rejects_cross_origin_plain_http() -> None:
    bridge = load_bridge()

    with pytest.raises(RuntimeError, match="must use HTTPS"):
        bridge.safe_download_headers(
            "http://download.example/export.jsonl",
            "https://api.galileo.ai",
            {"Galileo-API-Key": "must-not-leak"},
        )
    assert (
        bridge.safe_download_headers(
            "https://api.galileo.ai/v2/exports/file",
            "https://api.galileo.ai",
            {"Galileo-API-Key": "must-not-leak"},
        )
        == {}
    )


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError(
            "https://download.example/export.jsonl",
            403,
            "forbidden",
            {},
            None,
        ),
        urllib.error.HTTPError(
            "https://download.example/export.jsonl",
            307,
            "redirect",
            {},
            None,
        ),
        urllib.error.URLError("X-Amz-Signature=must-not-leak"),
    ],
)
def test_export_download_errors_redact_presigned_query_and_remote_detail(
    monkeypatch, error: Exception
) -> None:
    bridge = load_bridge()
    sentinel = "X-Amz-Signature=must-not-leak"
    url = f"https://download.example/export.jsonl?{sentinel}"

    def fail_open(*_args, **_kwargs):
        if isinstance(error, urllib.error.HTTPError):
            error.fp = io.BytesIO(sentinel.encode())
        raise error

    monkeypatch.setattr(bridge, "open_without_redirect", fail_open)

    with pytest.raises(RuntimeError) as exc_info:
        bridge.request_bytes("GET", url, {})

    message = str(exc_info.value)
    assert message.startswith("GET https://download.example/export.jsonl")
    assert sentinel not in message


def test_setup_help_lists_apply_sections() -> None:
    result = run_cmd("bash", str(SETUP), "--help")
    combined = result.stdout + result.stderr

    assert "--o11y-only" in combined
    assert "--luna-list-only" in combined
    for section in [
        "readiness",
        "object-lifecycle",
        "luna-scorers",
        "observe-export",
        "observe-runtime",
        "protect-runtime",
        "evaluate-assets",
        "multimodal-assets",
        "splunk-hec",
        "splunk-otlp",
        "otel-collector",
        "dashboards",
        "detectors",
    ]:
        assert section in combined


def test_default_render_emits_plan_coverage_and_handoff_scripts(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        *GALILEO_CONSOLE_ARGS,
        "--json",
    )
    payload = json.loads(result.stdout)

    assert payload["output_dir"] == str(output_dir.resolve())
    assert (output_dir / "apply-plan.json").is_file()
    assert (output_dir / "coverage-report.json").is_file()
    assert (output_dir / "handoff.md").is_file()
    assert (output_dir / "readiness/readiness-report.json").is_file()
    assert (output_dir / "readiness/galileo-2026-07-07-readiness.json").is_file()
    assert (output_dir / "lifecycle/object-lifecycle-manifest.example.json").is_file()
    assert (output_dir / "lifecycle/luna-scorer-map.example.json").is_file()
    assert (output_dir / "lifecycle/product-coverage-matrix.json").is_file()
    assert (output_dir / "lifecycle/product-coverage-matrix.md").is_file()
    assert (output_dir / "runtime/python-opentelemetry-env.sh").is_file()
    assert (output_dir / "runtime/codex-notify-galileo-handoff.md").is_file()
    assert (output_dir / "runtime/python-galileo-protect.py").is_file()
    assert (output_dir / "evaluate/evaluate-assets.yaml").is_file()
    assert (output_dir / "evaluate/ai-assistant-handoff.md").is_file()
    assert (output_dir / "evaluate/experiment-groups-and-scaling-handoff.md").is_file()
    assert (output_dir / "evaluate/multimodal-metrics-handoff.yaml").is_file()
    assert (output_dir / "alerts/generic-webhook-handoff.md").is_file()
    assert (output_dir / "alerts/galileo-alert-webhook-payload.example.json").is_file()
    assert (output_dir / "multimodal/multimodal-observability.md").is_file()
    assert (output_dir / "multimodal/multimodal-intake.example.json").is_file()
    assert (output_dir / "splunk-platform/hec-event-sample.json").is_file()
    assert (output_dir / "splunk-platform/export-records-request.json").is_file()
    assert (output_dir / "splunk-platform/galileo-alert-hec-event.example.json").is_file()
    assert (output_dir / "splunk-platform/galileo-alert-webhook-search-examples.spl").is_file()
    assert (output_dir / "splunk-platform/multimodal-search-examples.spl").is_file()
    assert (output_dir / "otel/collector-galileo-fanout.yaml").is_file()
    assert (output_dir / "dashboards/galileo-global-dashboard-handoff.md").is_file()
    assert (output_dir / "scripts/galileo_alert_webhook_relay.py").is_file()
    matrix = json.loads((output_dir / "lifecycle/product-coverage-matrix.json").read_text(encoding="utf-8"))
    surfaces = {item["surface"] for item in matrix}
    for surface in [
        "API keys, auth, users, groups, and RBAC",
        "REST API base URL, custom deployments, and healthcheck",
        "SSO, OIDC, SAML, and enterprise identity",
        "Dataset query, preview, content mutation, and bulk maintenance",
        "Prompt templates, rendering, and version utilities",
        "Evaluate workflow runs",
        "Python and TypeScript SDK parity",
        "Experiment columns, metrics APIs, and paginated search",
        "Large-dataset Playground and experiment batched processing",
        "Metric taxonomy, autotune, and use-case categories",
        "Custom scorers and scorer validation",
        "Scorer governance, health scores, and restore flows",
        "Luna and model/provider integrations",
        "Luna-2 fine-tuning and metric evaluation workflows",
        "Luna Studio UI and SDK training lifecycle",
        "Provider integrations, model aliases, costs, and pricing",
        "Provider integration selection, status, and Databricks helpers",
        "Codex notify turn logging",
        "Tags, metadata, run labels, and filter hygiene",
        "Enterprise data retention, TTL, redaction, and privacy controls",
        "Trace query, columns, recompute, update, and delete maintenance",
        "Trace metrics, counts, partial queries, and live logging APIs",
        "Agent Graph, Logs UI, Messages UI, and console debugging views",
        "Distributed tracing and multi-service propagation",
        "Multimodal observability",
        "OpenTelemetry and OpenInference",
        "Third-party framework integrations and wrappers",
        "MCP tool-call logging and tool spans",
        "Galileo alerts and notifications",
        "Annotation templates, ratings, and queues",
        "Feedback templates and ratings",
        "Trends dashboards, widgets, sections, Signals, and insights",
        "Global dashboards across projects and Log streams",
        "AI Assistant (beta) investigations",
        "Run insights, health scores, and token usage",
        "Jobs, async tasks, validation status, and progress polling",
        "Enterprise deployment, system users, and organization jobs",
        "Galileo MCP Server and IDE developer tooling",
        "Playgrounds, sample projects, unit tests, and CI experiments",
        "Cookbooks, use-case guides, and starter examples",
        "Error catalog, troubleshooting, and support diagnostics",
        "Release notes and version compatibility",
        "Splunk destinations",
    ]:
        assert surface in surfaces
    release = json.loads(
        (output_dir / "readiness/galileo-2026-07-07-readiness.json").read_text(
            encoding="utf-8"
        )
    )
    assert release["release_date"] == "2026-07-07"
    assert set(release["features"]) == {
        "ai_assistant_beta",
        "global_dashboards",
        "generic_alert_webhooks",
        "experiment_groups",
        "large_dataset_batched_processing",
    }
    assistant = release["features"]["ai_assistant_beta"]
    assert assistant["requires"] == [
        "enterprise_enablement_by_galileo_support",
        "configured_llm_integration",
    ]
    assert assistant["grounding_inputs"]
    webhook_readiness = release["features"]["generic_alert_webhooks"]
    assert webhook_readiness["relay_delivery"] == "at_least_once_downstream_search_dedup"
    manifest = json.loads(
        (output_dir / "lifecycle/object-lifecycle-manifest.example.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["experiments"][0]["experiment_group"]
    assert manifest["experiment_processing"]["minimum_group_sdk"] == "galileo>=2.2.0"
    assert manifest["experiment_processing"]["documented_scale"] == "thousands_of_rows"
    assert manifest["ownership_cleanup"]["exact_id_only"] is True
    assert manifest["ownership_cleanup"]["dataset_delete_requires_project_association"] is True
    assert (
        manifest["ownership_cleanup"]["metric_enablement"]
        == "newly_created_owned_log_stream_only"
    )
    assert manifest["ownership_cleanup"]["update_existing_dataset_rows"].endswith(
        "no_automatic_rollback"
    )
    webhook = json.loads(
        (output_dir / "alerts/galileo-alert-webhook-payload.example.json").read_text(
            encoding="utf-8"
        )
    )
    assert webhook["version"] == "1.0"
    assert webhook["event"] == "alert.triggered"
    assert webhook["event_id"]
    assert webhook["dedup_key"]
    readiness = json.loads(
        (output_dir / "readiness/readiness-report.json").read_text(encoding="utf-8")
    )
    assert readiness["galileo"]["api_base"] == "https://api.demo-v2.galileocloud.io"
    assert readiness["latest_release"]["target"] == "2026-07-07"
    otel = (output_dir / "otel/collector-galileo-fanout.yaml").read_text(encoding="utf-8")
    assert (
        "traces_endpoint: https://api.demo-v2.galileocloud.io/otel/traces" in otel
    )
    assert "\n    endpoint: https://api.demo-v2.galileocloud.io/otel/traces" not in otel
    assert "/otel/v1/traces" not in otel
    codex_notify = (output_dir / "runtime/codex-notify-galileo-handoff.md").read_text(encoding="utf-8")
    assert "Galileo MCP server" in codex_notify
    assert "POST /v2/projects/{project_id}/traces" in codex_notify
    assert "traces/count" in codex_notify
    for script in [
        "apply-readiness.sh",
        "apply-object-lifecycle.sh",
        "cleanup-object-lifecycle.sh",
        "apply-luna-scorers.sh",
        "apply-observe-export.sh",
        "apply-observe-runtime.sh",
        "apply-protect-runtime.sh",
        "apply-evaluate-assets.sh",
        "apply-multimodal-assets.sh",
        "apply-splunk-hec.sh",
        "apply-splunk-otlp.sh",
        "apply-otel-collector.sh",
        "apply-dashboards.sh",
        "apply-detectors.sh",
        "apply-selected.sh",
    ]:
        assert (output_dir / "scripts" / script).is_file()
        assert (output_dir / "scripts" / script).stat().st_mode & 0o111

    lifecycle_apply = (output_dir / "scripts/apply-object-lifecycle.sh").read_text(
        encoding="utf-8"
    )
    lifecycle_cleanup = (output_dir / "scripts/cleanup-object-lifecycle.sh").read_text(
        encoding="utf-8"
    )
    assert "--ownership-ledger" in lifecycle_apply
    assert "--cleanup-created" in lifecycle_cleanup
    assert "object-lifecycle-ownership.json" in lifecycle_cleanup
    alert_searches = (
        output_dir / "splunk-platform/galileo-alert-webhook-search-examples.spl"
    ).read_text(encoding="utf-8")
    assert "| dedup galileo_alert_event_id" in alert_searches
    assert "| spath path=alert.name" in alert_searches
    assert "| dedup event_id" not in alert_searches

    run_cmd("bash", str(VALIDATE), "--output-dir", str(output_dir))


def test_render_forwards_current_export_records_options(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        *GALILEO_CONSOLE_ARGS,
        "--export-format",
        "csv",
        "--export-computed-metrics-only",
        "true",
        "--include-code-metric-metadata",
        "true",
    )

    request = json.loads(
        (output_dir / "splunk-platform/export-records-request.json").read_text(
            encoding="utf-8"
        )
    )
    wrapper = (output_dir / "scripts/apply-observe-export.sh").read_text(
        encoding="utf-8"
    )

    assert request["export_format"] == "csv"
    assert request["export_computed_metrics_only"] is True
    assert request["include_code_metric_metadata"] is True
    assert "--export-computed-metrics-only" in wrapper
    assert "--include-code-metric-metadata" in wrapper
    run_cmd("bash", str(VALIDATE), "--output-dir", str(output_dir))


def test_render_rejects_computed_metrics_only_with_jsonl_flat(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(tmp_path / "rendered"),
        *GALILEO_CONSOLE_ARGS,
        "--export-format",
        "jsonl_flat",
        "--export-computed-metrics-only",
        "true",
        check=False,
    )

    assert result.returncode != 0
    assert "not supported with jsonl_flat" in result.stdout + result.stderr


def test_hec_handoff_delegates_to_hec_service_with_token_file_only(tmp_path: Path) -> None:
    secret = "SPLUNK_HEC_SECRET_SHOULD_NOT_RENDER"
    token_file = tmp_path / "hec.token"
    token_file.write_text(secret, encoding="utf-8")
    output_dir = tmp_path / "rendered"

    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        *GALILEO_CONSOLE_ARGS,
        "--splunk-hec-token-file",
        str(token_file),
        "--splunk-index",
        "galileo_prod",
    )

    script = (output_dir / "scripts/apply-splunk-hec.sh").read_text(encoding="utf-8")
    assert "splunk-hec-service-setup/scripts/setup.sh" in script
    assert "--token-file" in script
    assert not re.search(r"--splunk-hec-token(?:=|\s)", script)
    assert secret not in rendered_text(output_dir)
    assert str(token_file) in script


def test_otlp_handoff_delegates_to_splunk_connect_for_otlp(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd("bash", str(SETUP), "--render", "--output-dir", str(output_dir), *GALILEO_CONSOLE_ARGS)

    script = (output_dir / "scripts/apply-splunk-otlp.sh").read_text(encoding="utf-8")
    assert "splunk-connect-for-otlp-setup/scripts/setup.sh" in script
    assert "--hec-token-file" in script
    assert "--configure-input" in script


def test_otel_collector_handoff_delegates_to_splunk_otel_collector(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        *GALILEO_CONSOLE_ARGS,
        "--realm",
        "us0",
    )

    script = (output_dir / "scripts/apply-otel-collector.sh").read_text(encoding="utf-8")
    assert "splunk-observability-otel-collector-setup/scripts/setup.sh" in script
    assert "--o11y-token-file" in script
    assert "--platform-hec-token-file" in script
    assert "--render-platform-hec-helper" in script


def test_o11y_only_otel_collector_handoff_omits_platform_hec(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        *GALILEO_CONSOLE_ARGS,
        "--o11y-only",
        "--realm",
        "us0",
    )

    script = (output_dir / "scripts/apply-otel-collector.sh").read_text(encoding="utf-8")
    assert "splunk-observability-otel-collector-setup/scripts/setup.sh" in script
    assert "--o11y-token-file" in script
    assert "SPLUNK_HEC_TOKEN_FILE" not in script
    assert "--render-platform-hec-helper" not in script
    assert "--platform-hec-token-file" not in script
    assert "--platform-hec-url" not in script
    assert "--platform-hec-index" not in script

    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    assert plan["modes"] == {
        "o11y_only": True,
        "splunk_platform_hec_enabled": False,
    }
    assert plan["selected_sections"] == [
        "readiness",
        "object-lifecycle",
        "luna-scorers",
        "observe-runtime",
        "protect-runtime",
        "evaluate-assets",
        "multimodal-assets",
        "observability-controls",
        "otel-collector",
        "dashboards",
        "detectors",
    ]


def test_o11y_only_default_apply_dry_run_selects_cloud_sections(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--apply",
        "--o11y-only",
        "--dry-run",
        "--json",
        *GALILEO_CONSOLE_ARGS,
        "--output-dir",
        str(tmp_path / "rendered"),
    )
    payload = json.loads(result.stdout)

    assert payload["modes"]["o11y_only"] is True
    assert payload["modes"]["splunk_platform_hec_enabled"] is False
    assert payload["selected_sections"] == [
        "readiness",
        "object-lifecycle",
        "luna-scorers",
        "otel-collector",
        "dashboards",
        "detectors",
    ]
    for platform_section in ["splunk-hec", "observe-export", "splunk-otlp"]:
        assert platform_section not in payload["selected_sections"]


def test_o11y_only_apply_all_uses_cloud_sections_before_apply(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--apply",
        "all",
        "--o11y-only",
        "--realm",
        "us0",
        *GALILEO_CONSOLE_ARGS,
        "--output-dir",
        str(tmp_path / "rendered"),
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode != 0
    assert "Unknown apply section: all" not in combined
    assert "--galileo-api-key-file is required" in combined


def test_o11y_only_rejects_explicit_platform_sections(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--apply",
        "observe-export",
        "--o11y-only",
        "--dry-run",
        *GALILEO_CONSOLE_ARGS,
        "--output-dir",
        str(tmp_path / "rendered"),
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode != 0
    assert "--o11y-only" in combined
    assert "Splunk Platform" in combined
    assert "observe-export" in combined


def test_direct_secret_flags_are_rejected_without_echoing_values(tmp_path: Path) -> None:
    secret = "DIRECT_GALILEO_SECRET_SHOULD_NOT_ECHO"
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(tmp_path / "rendered"),
        "--galileo-api-key",
        secret,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert secret not in combined
    assert "--galileo-api-key-file" in combined


def test_rendered_files_do_not_contain_token_values_or_direct_authorization(tmp_path: Path) -> None:
    galileo_secret = "GALILEO_SECRET_SHOULD_NOT_RENDER"
    hec_secret = "HEC_SECRET_SHOULD_NOT_RENDER"
    o11y_secret = "O11Y_SECRET_SHOULD_NOT_RENDER"
    galileo_file = tmp_path / "galileo.token"
    hec_file = tmp_path / "hec.token"
    o11y_file = tmp_path / "o11y.token"
    galileo_file.write_text(galileo_secret, encoding="utf-8")
    hec_file.write_text(hec_secret, encoding="utf-8")
    o11y_file.write_text(o11y_secret, encoding="utf-8")
    output_dir = tmp_path / "rendered"

    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        "--galileo-api-key-file",
        str(galileo_file),
        *GALILEO_CONSOLE_ARGS,
        "--splunk-hec-token-file",
        str(hec_file),
        "--o11y-token-file",
        str(o11y_file),
        "--splunk-hec-url",
        "https://splunk.example.com:8088/services/collector/event",
        "--realm",
        "us0",
    )
    text = rendered_text(output_dir)

    assert galileo_secret not in text
    assert hec_secret not in text
    assert o11y_secret not in text
    assert "Authorization: Splunk" not in text
    assert "Authorization: Bearer" not in text
    assert str(galileo_file) in text
    assert str(hec_file) in text
    assert str(o11y_file) in text


def test_export_records_request_shape_defaults_to_jsonl_and_redaction() -> None:
    bridge = load_bridge()
    args = bridge.parse_args(
        [
            "--project-id",
            "00000000-0000-4000-8000-000000000001",
            "--log-stream-id",
            "00000000-0000-4000-8000-000000000002",
            "--experiment-id",
            "00000000-0000-4000-8000-000000000003",
            "--metrics-testing-id",
            "00000000-0000-4000-8000-000000000004",
            "--galileo-api-key-file",
            "/tmp/galileo",
            "--splunk-hec-token-file",
            "/tmp/hec",
            "--splunk-hec-url",
            "https://splunk.example.com:8088",
            "--since",
            "2026-05-01T00:00:00Z",
        ]
    )
    body = bridge.build_export_records_request(args, args.since)

    assert body["root_type"] == "trace"
    assert body["export_format"] == "jsonl"
    assert body["redact"] is True
    assert body["log_stream_id"].endswith("0002")
    assert body["experiment_id"].endswith("0003")
    assert body["metrics_testing_id"].endswith("0004")
    assert body["filters"][0] == {
        "column_id": "updated_at",
        "operator": "gte",
        "type": "date",
        "value": "2026-05-01T00:00:00Z",
    }


def test_hec_envelope_extracts_flat_dotted_control_attributes() -> None:
    bridge = load_bridge()
    args = Namespace(
        include_raw=False,
        indexed_fields=True,
        log_stream_id="log-stream-1",
        project_id="project-1",
        root_type="span",
        splunk_host=None,
        splunk_index="galileo",
        splunk_source="galileo",
        splunk_sourcetype="galileo:observe:json",
        time_field="updated_at",
    )
    record = {
        "id": "span-1",
        "type": "span",
        "project_id": "project-1",
        "run_id": "log-stream-1",
        "trace_id": "trace-1",
        "updated_at": "2026-06-18T00:00:00Z",
        "attributes": {
            "control.id": "control-1",
            "control.name": "block-output-pii",
            "control.step": "LLM",
            "control.stage": "Post",
            "control.action.decision": "deny",
            "control.matched": True,
            "control.source": "custom",
            "control.evaluator.name": "pii-detector",
            "control.selector.path": "output",
        },
    }

    envelope = bridge.hec_envelope(record, args)
    event = envelope["event"]

    assert event["control_info"] == {
        "control_id": "control-1",
        "stage": "Post",
        "step_type": "LLM",
        "action": "deny",
        "matched": True,
        "evaluator_name": "pii-detector",
        "selector_path": "output",
        "source": "custom",
        "control_name": "block-output-pii",
    }
    assert event["galileo_control_id"] == "control-1"
    assert event["galileo_control_name"] == "block-output-pii"
    assert event["galileo_control_step_type"] == "LLM"
    assert event["galileo_control_source"] == "custom"
    assert envelope["fields"]["galileo_control_matched"] == "true"


def test_csv_hec_envelope_preserves_selected_columns_without_raw_content() -> None:
    bridge = load_bridge()
    args = Namespace(
        export_format="csv",
        include_raw=False,
        indexed_fields=False,
        log_stream_id="log-stream-1",
        project_id="project-1",
        root_type="trace",
        splunk_host=None,
        splunk_index="galileo",
        splunk_source="galileo",
        splunk_sourcetype="galileo:observe:json",
        time_field="updated_at",
    )
    record = {
        "id": "trace-1",
        "type": "trace",
        "updated_at": "2026-07-07T00:00:00Z",
        "metrics/custom_score": "0.91",
        "business_unit": "payments",
        "input": "raw prompt must remain excluded",
        "transcript": "raw transcript must remain excluded",
    }

    event = bridge.hec_envelope(record, args)["event"]

    assert event["exported_columns"] == {"metrics/custom_score": "0.91"}
    assert "input" not in event
    assert "business_unit" not in json.dumps(event)
    assert "raw prompt must remain excluded" not in json.dumps(event)
    assert "raw transcript must remain excluded" not in json.dumps(event)


def test_csv_unknown_columns_require_explicit_raw_approval() -> None:
    bridge = load_bridge()
    args = Namespace(
        export_format="csv",
        include_raw=False,
        indexed_fields=False,
        log_stream_id="log-stream-1",
        project_id="project-1",
        root_type="trace",
        splunk_host=None,
        splunk_index="galileo",
        splunk_source="galileo",
        splunk_sourcetype="galileo:observe:json",
        time_field="updated_at",
    )
    record = {
        "id": "trace-1",
        "type": "trace",
        "request_payload": "RAW_REQUEST_SENTINEL",
        "llm_input.value": "RAW_INPUT_SENTINEL",
        "response_text": "RAW_RESPONSE_SENTINEL",
    }

    safe_event = bridge.hec_envelope(record, args)["event"]
    assert "RAW_" not in json.dumps(safe_event)

    args.include_raw = True
    raw_event = bridge.hec_envelope(record, args)["event"]
    assert raw_event["exported_columns"]["request_payload"] == "RAW_REQUEST_SENTINEL"


def test_jsonl_flat_preserves_safe_metric_columns_only() -> None:
    bridge = load_bridge()
    args = Namespace(
        export_format="jsonl_flat",
        include_raw=False,
        indexed_fields=False,
        log_stream_id="log-stream-1",
        project_id="project-1",
        root_type="trace",
        splunk_host=None,
        splunk_index="galileo",
        splunk_source="galileo",
        splunk_sourcetype="galileo:observe:json",
        time_field="updated_at",
    )
    record = {
        "id": "trace-1",
        "type": "trace",
        "metrics/correctness": 0.95,
        "response_text": "RAW_RESPONSE_SENTINEL",
    }

    event = bridge.hec_envelope(record, args)["event"]

    assert event["exported_columns"] == {"metrics/correctness": 0.95}
    assert "RAW_RESPONSE_SENTINEL" not in json.dumps(event)


def test_envelope_terminal_sample_is_metadata_only() -> None:
    bridge = load_bridge()
    envelope = {
        "time": 1.0,
        "source": "galileo",
        "sourcetype": "galileo:observe:json",
        "event": {
            "galileo_record_id": "trace-1",
            "galileo_record_type": "trace",
            "input": "RAW_PROMPT_SENTINEL",
            "output": "RAW_OUTPUT_SENTINEL",
            "exported_columns": {"response_text": "RAW_RESPONSE_SENTINEL"},
        },
    }

    sample = bridge.envelope_log_summary(envelope)

    assert sample["event"] == {
        "galileo_record_id": "trace-1",
        "galileo_record_type": "trace",
    }
    assert "RAW_" not in json.dumps(sample)


def test_hec_envelope_extracts_multimodal_metadata_without_raw_payloads() -> None:
    bridge = load_bridge()
    args = Namespace(
        include_raw=False,
        indexed_fields=True,
        log_stream_id="log-stream-1",
        project_id="project-1",
        root_type="trace",
        splunk_host=None,
        splunk_index="galileo",
        splunk_source="galileo",
        splunk_sourcetype="galileo:observe:json",
        time_field="updated_at",
    )
    record = {
        "id": "trace-1",
        "type": "trace",
        "project_id": "project-1",
        "run_id": "log-stream-1",
        "trace_id": "trace-1",
        "updated_at": "2026-06-18T00:00:00Z",
        "input": [
            {"type": "text", "text": "Analyze these files"},
            {
                "modality": "image",
                "mime_type": "image/png",
                "url": "https://example.com/customer-photo.png",
                "source": "/private/customer-photo.png",
                "width": 640,
                "height": 480,
            },
            {
                "modality": "audio",
                "mime_type": "audio/wav",
                "base64": "RAW_AUDIO_BASE64_SHOULD_NOT_RENDER",
                "duration_ms": 1200,
            },
            {
                "modality": "document",
                "mime_type": "application/pdf",
                "file_name": "case-file.pdf",
                "page_count": 3,
                "data": "RAW_PDF_BYTES_SHOULD_NOT_RENDER",
            },
        ],
        "output": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "The image is readable and the audio is clear."},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "https://example.com/generated-image.png",
                        "mime_type": "image/png",
                    },
                },
            ],
        },
        "metrics": {
            "visual_quality": True,
            "interruption_detection": False,
        },
    }

    envelope = bridge.hec_envelope(record, args)
    event = envelope["event"]
    serialized = json.dumps(envelope)

    assert event["galileo_has_multimodal"] is True
    assert event["galileo_modalities"] == ["audio", "document", "image"]
    assert event["galileo_input_modalities"] == ["audio", "document", "image"]
    assert event["galileo_output_modalities"] == ["image"]
    assert event["galileo_multimodal_asset_count"] == 4
    assert event["galileo_multimodal_metrics"] == ["interruption_detection", "visual_quality"]
    assert event["multimodal_info"]["asset_counts"] == {
        "audio": 1,
        "document": 1,
        "image": 2,
    }
    assert "RAW_AUDIO_BASE64_SHOULD_NOT_RENDER" not in serialized
    assert "RAW_PDF_BYTES_SHOULD_NOT_RENDER" not in serialized
    assert "https://example.com/customer-photo.png" not in serialized
    assert "https://example.com/generated-image.png" not in serialized
    assert "/private/customer-photo.png" not in serialized
    assert event["multimodal_info"]["assets"][0]["has_source"] is True
    assert envelope["fields"]["galileo_has_multimodal"] == "true"
    assert envelope["fields"]["galileo_modalities"] == "audio,document,image"


@pytest.mark.parametrize("response", [{}, [], {"text": "Success"}, {"code": 1}])
def test_export_bridge_requires_explicit_hec_code_zero(monkeypatch, response) -> None:
    bridge = load_bridge()
    args = Namespace(
        splunk_hec_url="https://splunk.example.com:8088/services/collector/event",
        splunk_hec_token_file="unused-test-token-file",
        insecure=False,
    )
    monkeypatch.setattr(bridge, "splunk_headers", lambda _args: {})
    monkeypatch.setattr(
        bridge,
        "request_json",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(RuntimeError, match="rejected batch"):
        bridge.send_to_splunk(args, [{"event": {"id": "record-1"}}])


def test_export_bridge_accepts_hec_code_zero(monkeypatch) -> None:
    bridge = load_bridge()
    args = Namespace(
        splunk_hec_url="https://splunk.example.com:8088/services/collector/event",
        splunk_hec_token_file="unused-test-token-file",
        insecure=False,
    )
    monkeypatch.setattr(bridge, "splunk_headers", lambda _args: {})
    monkeypatch.setattr(
        bridge,
        "request_json",
        lambda *_args, **_kwargs: {"code": 0, "text": "Success"},
    )

    bridge.send_to_splunk(args, [{"event": {"id": "record-1"}}])


def test_object_lifecycle_dry_run_covers_core_galileo_objects(tmp_path: Path) -> None:
    manifest = tmp_path / "lifecycle.json"
    output = tmp_path / "result.json"
    manifest.write_text(
        json.dumps(
            {
                "project": {"name": "enterprise-ops"},
                "log_stream": {"name": "production", "metrics": ["correctness"]},
                "datasets": [{"name": "eval-cases", "content": [{"input": "hi"}]}],
                "prompts": [{"name": "triage", "template": [{"role": "user", "content": "{{input}}"}]}],
                "experiments": [
                    {"name": "baseline", "experiment_group": "RAG Benchmark"}
                ],
                "protect_stages": [{"name": "production", "create": True}],
                "agent_control_targets": [{"target_type": "log_stream"}],
            }
        ),
        encoding="utf-8",
    )

    result = run_cmd(
        sys.executable,
        str(LIFECYCLE),
        "--dry-run",
        "--galileo-api-key-file",
        str(tmp_path / "galileo.token"),
        "--manifest",
        str(manifest),
        "--output",
        str(output),
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "ok"
    assert payload["project"]["status"] == "planned"
    assert payload["log_stream"]["status"] == "planned"
    assert payload["metrics"]["status"] == "planned"
    assert payload["datasets"][0]["status"] == "planned"
    assert payload["prompts"][0]["status"] == "planned"
    assert payload["experiments"][0]["status"] == "planned"
    assert payload["experiments"][0]["experiment_group"] == "RAG Benchmark"
    assert payload["protect_stages"][0]["status"] == "planned"
    assert payload["agent_control_targets"][0]["status"] == "planned"
    assert output.is_file()


def test_dataset_lifecycle_is_project_scoped_and_append_has_no_rollback_claim(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_dataset_scope")
    galileo = ModuleType("galileo")
    datasets = ModuleType("galileo.datasets")
    calls: list[tuple[str, dict[str, object]]] = []

    def get_dataset(**kwargs):
        calls.append(("get", kwargs))
        return None

    def create_dataset(**kwargs):
        calls.append(("create", kwargs))
        return {"id": "dataset-id", "name": kwargs["name"]}

    datasets.get_dataset = get_dataset
    datasets.create_dataset = create_dataset
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.datasets", datasets)

    created = lifecycle.ensure_dataset(
        {"name": "eval-cases", "content": [{"input": "hello"}]},
        {"id": "project-id", "name": "project"},
        False,
    )

    assert created["status"] == "created"
    assert created["project_scope_validated"] is True
    assert calls == [
        ("get", {"name": "eval-cases", "project_id": "project-id"}),
        (
            "create",
            {
                "name": "eval-cases",
                "content": [{"input": "hello"}],
                "project_id": "project-id",
            },
        ),
    ]

    class ExistingDataset:
        id = "dataset-id"
        name = "eval-cases"

        def add_rows(self, rows):
            calls.append(("add_rows", {"rows": rows}))

    datasets.get_dataset = lambda **_kwargs: ExistingDataset()
    updated = lifecycle.ensure_dataset(
        {
            "name": "eval-cases",
            "content": [{"input": "second"}],
            "update_existing": True,
        },
        {"id": "project-id", "name": "project"},
        False,
    )

    assert updated["status"] == "rows_appended_new_version"
    assert updated["reversible"] is False
    assert updated["rollback"].startswith("not_supported")


def test_dataset_scope_uses_narrow_rest_validation_for_sdk_permission_enum_bug(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_dataset_compat")
    project_id = "11111111-1111-4111-8111-111111111111"
    galileo = ModuleType("galileo")
    datasets = ModuleType("galileo.datasets")
    resolver_calls: list[tuple[object, object]] = []

    def broken_resolver(project_id=None, project_name=None, **_kwargs):
        resolver_calls.append((project_id, project_name))
        raise ValueError("'update_control_bindings' is not a valid AnnotationQueueAction")

    def get_dataset(**kwargs):
        datasets.resolve_project_id(kwargs.get("project_id"), kwargs.get("project_name"))
        return {"id": "dataset-id", "name": kwargs["name"]}

    datasets.resolve_project_id = broken_resolver
    datasets.get_dataset = get_dataset
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.datasets", datasets)
    monkeypatch.setattr(
        lifecycle,
        "_get_project_rest",
        lambda **kwargs: {"id": kwargs["project_id"], "name": "project"},
    )

    dataset, source = lifecycle.call_dataset_project_scoped(
        get_dataset,
        project_id=project_id,
        project_name="project",
        kwargs={"name": "eval-cases"},
    )
    assert dataset == {"id": "dataset-id", "name": "eval-cases"}
    assert source == "documented_rest_project_validation_sdk_workaround"
    assert resolver_calls == [(project_id, None)]
    assert datasets.resolve_project_id is broken_resolver

    delete_calls: list[dict[str, object]] = []

    def delete_dataset(**kwargs):
        datasets.resolve_project_id(kwargs.get("project_id"), kwargs.get("project_name"))
        delete_calls.append(kwargs)

    deleted, delete_source = lifecycle.call_dataset_project_scoped(
        delete_dataset,
        project_id=project_id,
        project_name="",
        kwargs={"id": "dataset-id"},
    )
    assert deleted is None
    assert delete_source == "documented_rest_project_validation_sdk_workaround"
    assert delete_calls == [{"id": "dataset-id", "project_id": project_id}]
    assert datasets.resolve_project_id is broken_resolver


def test_log_stream_id_is_looked_up_and_validated_exactly(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_log_stream_id")
    galileo = ModuleType("galileo")
    log_streams = ModuleType("galileo.log_streams")
    calls: list[dict[str, object]] = []

    def get_log_stream(**kwargs):
        calls.append(kwargs)
        return {
            "id": "requested-stream-id",
            "name": "production",
            "project_id": "project-id",
        }

    log_streams.get_log_stream = get_log_stream
    log_streams.create_log_stream = lambda **_kwargs: pytest.fail("must not create")
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.log_streams", log_streams)
    config = {
        "project": {"id": "project-id", "name": "project"},
        "log_stream": {
            "id": "requested-stream-id",
            "name": "production",
            "create": True,
        },
    }

    result, _obj = lifecycle.ensure_log_stream(
        config,
        {"id": "project-id", "name": "project"},
        False,
    )
    assert result["status"] == "exists"
    assert calls == [{"name": "production", "project_id": "project-id"}]

    log_streams.get_log_stream = lambda **_kwargs: {
        "id": "different-stream-id",
        "name": "production",
        "project_id": "project-id",
    }
    with pytest.raises(RuntimeError, match="resolved to a different ID"):
        lifecycle.ensure_log_stream(
            config,
            {"id": "project-id", "name": "project"},
            False,
        )

    config["log_stream"]["name"] = ""
    with pytest.raises(RuntimeError, match="name is required with --log-stream-id"):
        lifecycle.ensure_log_stream(
            config,
            {"id": "project-id", "name": "project"},
            False,
        )


def test_child_creation_in_preexisting_project_fails_before_mutation(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_existing_project")
    galileo = ModuleType("galileo")
    log_streams = ModuleType("galileo.log_streams")
    log_streams.get_log_stream = lambda **_kwargs: None
    log_streams.create_log_stream = lambda **_kwargs: pytest.fail("must fail before create")
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.log_streams", log_streams)
    config = {
        "project": {
            "id": "project-id",
            "name": "existing-project",
            "_created_by_operation": False,
        },
        "log_stream": {"name": "validation", "id": "", "create": True},
    }

    with pytest.raises(RuntimeError, match="pre-existing project"):
        lifecycle.ensure_log_stream(
            config,
            {"id": "project-id", "name": "existing-project"},
            False,
        )


def test_metric_enablement_does_not_mutate_a_preexisting_log_stream() -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_existing_metrics")
    calls: list[list[str]] = []

    class ExistingLogStream:
        def enable_metrics(self, metrics):
            calls.append(metrics)
            return []

    config = {
        "project": {"id": "project-id", "name": "project"},
        "log_stream": {
            "id": "stream-id",
            "name": "production",
            "metrics": ["correctness"],
            "_created_by_operation": False,
        },
    }

    with pytest.raises(RuntimeError, match="pre-existing log stream"):
        lifecycle.enable_log_stream_metrics(config, ExistingLogStream(), False)
    assert calls == []

    assert lifecycle.enable_log_stream_metrics(config, ExistingLogStream(), True) == {
        "status": "planned",
        "metrics": ["correctness"],
    }
    assert calls == []

    config["log_stream"]["_created_by_operation"] = True
    assert lifecycle.enable_log_stream_metrics(config, ExistingLogStream(), False) == {
        "status": "enabled",
        "metrics": ["correctness"],
        "local_metrics": 0,
    }
    assert calls == [["correctness"]]


def test_project_compat_fallback_is_limited_to_known_permission_enum_errors(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_project_compat")
    fallback_calls: list[dict[str, object]] = []

    def rest_fallback(**kwargs):
        fallback_calls.append(kwargs)
        return {"id": "project-id", "name": "project"}

    monkeypatch.setattr(lifecycle, "_get_project_rest", rest_fallback)

    def schema_failure(**_kwargs):
        raise ValueError("'update_control_bindings' is not a valid PermissionAction")

    project, source = lifecycle.get_project_compat(schema_failure, project_id="project-id")
    assert project["id"] == "project-id"
    assert source == "documented_rest_fallback"
    assert fallback_calls == [{"project_id": "project-id", "name": ""}]

    def auth_failure(**_kwargs):
        raise RuntimeError("HTTP 401 unauthorized")

    with pytest.raises(RuntimeError, match="401"):
        lifecycle.get_project_compat(auth_failure, project_id="project-id")
    assert len(fallback_calls) == 1

    def unrelated_enum_failure(**_kwargs):
        raise ValueError("'delete' is not a valid PermissionAction")

    with pytest.raises(ValueError, match="not a valid PermissionAction"):
        lifecycle.get_project_compat(unrelated_enum_failure, project_id="project-id")
    assert len(fallback_calls) == 1


def test_experiment_project_compat_bypasses_only_verified_sdk_project_read(
    monkeypatch,
) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_experiment_compat")
    galileo = ModuleType("galileo")
    experiments = ModuleType("galileo.experiments")

    class Projects:
        def get_with_env_fallbacks(self, *, id=None, name=None):
            del id, name
            raise ValueError("'use_control_runtime' is not a valid AnnotationQueueAction")

    experiments.Projects = Projects
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.experiments", experiments)
    monkeypatch.setattr(
        lifecycle,
        "_get_project_rest",
        lambda **_kwargs: {"id": "project-id", "name": "project"},
    )

    def sdk_helper(*, project_id, experiment_name):
        project = experiments.Projects().get_with_env_fallbacks(
            id=project_id,
            name=None,
        )
        return {"id": "experiment-id", "name": experiment_name, "project": project.id}

    result, resolution = lifecycle.call_experiment_project_scoped(
        sdk_helper,
        project_id="project-id",
        project_name="project",
        variants=[{"project_id": "project-id", "experiment_name": "baseline"}],
    )

    assert result["project"] == "project-id"
    assert resolution == "documented_rest_project_validation_sdk_workaround"
    with pytest.raises(ValueError, match="use_control_runtime"):
        experiments.Projects().get_with_env_fallbacks(id="project-id", name=None)


def test_project_rest_fallback_uses_configured_api_key_without_redirects(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_project_rest")
    project_id = "11111111-1111-4111-8111-111111111111"
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"id": project_id, "name": "project"}).encode()

    class Opener:
        def open(self, request, timeout):
            captured["url"] = request.full_url
            captured["api_key"] = request.get_header("Galileo-api-key")
            captured["timeout"] = timeout
            return Response()

    def build_opener(*handlers):
        captured["no_redirect"] = any(
            isinstance(handler, lifecycle.NoRedirectHandler) for handler in handlers
        )
        return Opener()

    monkeypatch.setenv("GALILEO_API_BASE", "https://api.example.invalid")
    monkeypatch.setenv("GALILEO_API_KEY", "test-secret-must-not-be-logged")
    monkeypatch.setattr(lifecycle.urllib.request, "build_opener", build_opener)

    project = lifecycle._get_project_rest(project_id=project_id)
    assert project == {"id": project_id, "name": "project"}
    assert captured == {
        "url": f"https://api.example.invalid/v2/projects/{project_id}",
        "api_key": "test-secret-must-not-be-logged",
        "timeout": 60,
        "no_redirect": True,
    }


def test_project_rest_fallback_rejects_cleartext_non_loopback_api_key_transport(
    monkeypatch,
) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_project_http")
    monkeypatch.setenv("GALILEO_API_BASE", "http://api.example.invalid")
    monkeypatch.setenv("GALILEO_API_KEY", "test-secret-must-not-be-logged")

    with pytest.raises(RuntimeError, match="must use HTTPS unless the host is loopback"):
        lifecycle._project_rest_request("GET", "/v2/projects/project-id")

    monkeypatch.setenv("GALILEO_API_BASE", "http://127.0.0.1:8080")
    assert lifecycle._validated_api_base() == "http://127.0.0.1:8080"


def test_project_delete_fallback_is_exact_and_limited_to_known_schema_error(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_project_delete")
    project_id = "11111111-1111-4111-8111-111111111111"
    rest_calls: list[tuple[str, str, bool]] = []

    def sdk_schema_failure(**_kwargs):
        raise ValueError("'use_control_runtime' is not a valid PermissionAction")

    def rest_request(method, path, *, body=None, not_found_is_none=False):
        assert body is None
        rest_calls.append((method, path, not_found_is_none))
        return {"message": "deleted"}

    monkeypatch.setattr(lifecycle, "_project_rest_request", rest_request)
    project_reads = iter([{"id": project_id, "name": "project"}, None])
    monkeypatch.setattr(lifecycle, "_get_project_rest", lambda **_kwargs: next(project_reads))

    source = lifecycle.delete_project_compat(sdk_schema_failure, project_id=project_id)
    assert source == "documented_rest_fallback"
    assert rest_calls == [("DELETE", f"/v2/projects/{project_id}", True)]

    def sdk_auth_failure(**_kwargs):
        raise RuntimeError("HTTP 403 forbidden")

    monkeypatch.setattr(
        lifecycle,
        "_get_project_rest",
        lambda **_kwargs: {"id": project_id, "name": "project"},
    )
    with pytest.raises(RuntimeError, match="403"):
        lifecycle.delete_project_compat(sdk_auth_failure, project_id=project_id)
    assert len(rest_calls) == 1

    sdk_calls: list[dict[str, object]] = []

    def must_not_delete(**kwargs):
        sdk_calls.append(kwargs)
        pytest.fail("an already-absent exact project must not call SDK delete")

    monkeypatch.setattr(lifecycle, "_get_project_rest", lambda **_kwargs: None)
    assert (
        lifecycle.delete_project_compat(must_not_delete, project_id=project_id)
        == "already_absent_verified"
    )
    assert sdk_calls == []


def test_project_failure_stops_log_stream_and_all_child_processing(monkeypatch, tmp_path: Path) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_child_gate")
    output = tmp_path / "result.json"
    args = Namespace(
        galileo_api_key_file=str(tmp_path / "unused"),
        project_name="project",
        project_id="",
        log_stream_name="production",
        log_stream_id="",
        console_url="",
        api_base="",
        manifest="",
        dataset_dir="",
        prompt_manifest="",
        experiment_manifest="",
        protect_stage_manifest="",
        metrics="",
        output=str(output),
        ownership_ledger="",
        cleanup_created=False,
        dry_run=True,
    )
    config = {
        "project": {"name": "project", "id": "", "create": True},
        "log_stream": {"name": "production", "id": "", "create": True},
        "datasets": [{"name": "dataset"}],
        "prompts": [{"name": "prompt"}],
        "experiments": [{"name": "experiment"}],
        "protect_stages": [{"name": "stage"}],
        "agent_control_targets": [{"name": "target"}],
    }
    monkeypatch.setattr(lifecycle, "parse_args", lambda _argv=None: args)
    monkeypatch.setattr(lifecycle, "merge_inputs", lambda _args: config)
    monkeypatch.setattr(
        lifecycle,
        "ensure_project",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("project readback failed")),
    )
    monkeypatch.setattr(
        lifecycle,
        "ensure_log_stream",
        lambda *_args: pytest.fail("log stream must not be processed"),
    )
    monkeypatch.setattr(
        lifecycle,
        "ensure_dataset",
        lambda *_args: pytest.fail("child objects must not be processed"),
    )

    assert lifecycle.main([]) == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["project"] == {}
    assert payload["log_stream"]["status"] == "skipped"
    assert payload["datasets"][0]["status"] == "skipped"
    assert payload["prompts"][0]["status"] == "skipped"
    assert payload["experiments"][0]["status"] == "skipped"
    assert payload["protect_stages"][0]["status"] == "skipped"
    assert payload["agent_control_targets"][0]["status"] == "skipped"


def test_cleanup_ledger_deletes_datasets_before_exact_project_and_marks_children(
    monkeypatch, tmp_path: Path
) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_cleanup")
    project_id = "11111111-1111-4111-8111-111111111111"
    stream_id = "22222222-2222-4222-8222-222222222222"
    dataset_id = "33333333-3333-4333-8333-333333333333"
    prompt_id = "55555555-5555-4555-8555-555555555555"
    ledger_path = tmp_path / "ownership.json"
    ledger_path.write_text(
        json.dumps(
            {
                "api_version": "galileo-platform-setup/object-lifecycle-ownership/v1",
                "created_by": "galileo_object_lifecycle.py",
                "operation_id": "44444444-4444-4444-8444-444444444444",
                "secret_values_rendered": False,
                "status": "complete",
                "created_objects": [
                    {
                        "kind": "project",
                        "id": project_id,
                        "project_id": project_id,
                        "cleanup_status": "pending",
                    },
                    {
                        "kind": "log_stream",
                        "id": stream_id,
                        "project_id": project_id,
                        "cleanup_status": "pending",
                    },
                    {
                        "kind": "dataset",
                        "id": dataset_id,
                        "project_id": project_id,
                        "cleanup_status": "pending",
                    },
                    {
                        "kind": "prompt",
                        "id": prompt_id,
                        "project_id": project_id,
                        "cleanup_status": "pending",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    galileo = ModuleType("galileo")
    datasets = ModuleType("galileo.datasets")
    projects = ModuleType("galileo.projects")
    prompts = ModuleType("galileo.prompts")
    calls: list[tuple[str, dict[str, object]]] = []
    dataset_reads = iter([{"id": dataset_id, "name": "dataset"}, "deleted"])

    def get_dataset(**_kwargs):
        value = next(dataset_reads)
        if value == "deleted":
            raise RuntimeError("Resource not found for exact dataset ID (HTTP 404)")
        return value

    datasets.get_dataset = get_dataset
    datasets.delete_dataset = lambda **kwargs: calls.append(("dataset", kwargs))

    def delete_project(**kwargs):
        calls.append(("project", kwargs))
        return True

    projects.delete_project = delete_project
    prompt_reads = iter([{"id": prompt_id, "name": "prompt"}, "deleted"])

    def get_prompt(**_kwargs):
        value = next(prompt_reads)
        if value == "deleted":
            raise RuntimeError("Resource not found for exact prompt ID (HTTP 404)")
        return value

    prompts.get_prompt = get_prompt
    prompts.delete_prompt = lambda **kwargs: calls.append(("prompt", kwargs))
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.datasets", datasets)
    monkeypatch.setitem(sys.modules, "galileo.projects", projects)
    monkeypatch.setitem(sys.modules, "galileo.prompts", prompts)
    project_reads = iter([{"id": project_id, "name": "project"}, None])
    monkeypatch.setattr(lifecycle, "_get_project_rest", lambda **_kwargs: next(project_reads))

    result = lifecycle.cleanup_created_objects(ledger_path, dry_run=False)
    assert result["status"] == "cleaned"
    assert result["exact_id_only"] is True
    assert calls == [
        ("dataset", {"id": dataset_id, "project_id": project_id}),
        ("prompt", {"id": prompt_id}),
        ("project", {"id": project_id}),
    ]
    cleaned = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert cleaned["status"] == "cleaned"
    assert cleaned["created_objects"][0]["cleanup_status"] == "deleted_by_exact_id"
    assert cleaned["created_objects"][1]["cleanup_status"] == "covered_by_exact_project_delete"
    assert cleaned["created_objects"][2]["cleanup_status"] == "deleted_by_exact_id"
    assert cleaned["created_objects"][3]["cleanup_status"] == "deleted_by_exact_id"


def test_cleanup_ledger_recovers_when_dataset_and_prompt_are_already_absent(
    monkeypatch, tmp_path: Path
) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_cleanup_absent_children")
    project_id = "11111111-1111-4111-8111-111111111111"
    dataset_id = "33333333-3333-4333-8333-333333333333"
    prompt_id = "55555555-5555-4555-8555-555555555555"
    ledger_path = tmp_path / "ownership.json"
    ledger_path.write_text(
        json.dumps(
            {
                "api_version": "galileo-platform-setup/object-lifecycle-ownership/v1",
                "created_by": "galileo_object_lifecycle.py",
                "operation_id": "44444444-4444-4444-8444-444444444444",
                "created_objects": [
                    {
                        "kind": "dataset",
                        "id": dataset_id,
                        "project_id": project_id,
                        "cleanup_status": "pending",
                    },
                    {
                        "kind": "prompt",
                        "id": prompt_id,
                        "project_id": project_id,
                        "cleanup_status": "pending",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    galileo = ModuleType("galileo")
    datasets = ModuleType("galileo.datasets")
    projects = ModuleType("galileo.projects")
    prompts = ModuleType("galileo.prompts")
    datasets.get_dataset = lambda **_kwargs: None
    datasets.delete_dataset = lambda **_kwargs: pytest.fail("already absent")
    projects.delete_project = lambda **_kwargs: pytest.fail("no project entry")
    prompts.get_prompt = lambda **_kwargs: None
    prompts.delete_prompt = lambda **_kwargs: pytest.fail("already absent")
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.datasets", datasets)
    monkeypatch.setitem(sys.modules, "galileo.projects", projects)
    monkeypatch.setitem(sys.modules, "galileo.prompts", prompts)

    result = lifecycle.cleanup_created_objects(ledger_path, dry_run=False)

    assert result["status"] == "cleaned"
    assert {item["status"] for item in result["objects"]} == {
        "already_absent_verified"
    }


def test_cleanup_ledger_keeps_dataset_pending_when_delete_is_not_observed(
    monkeypatch, tmp_path: Path
) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_cleanup_dataset_noop")
    project_id = "11111111-1111-4111-8111-111111111111"
    dataset_id = "33333333-3333-4333-8333-333333333333"
    ledger_path = tmp_path / "ownership.json"
    ledger_path.write_text(
        json.dumps(
            {
                "api_version": "galileo-platform-setup/object-lifecycle-ownership/v1",
                "created_by": "galileo_object_lifecycle.py",
                "operation_id": "44444444-4444-4444-8444-444444444444",
                "created_objects": [
                    {
                        "kind": "project",
                        "id": project_id,
                        "project_id": project_id,
                        "cleanup_status": "pending",
                    },
                    {
                        "kind": "dataset",
                        "id": dataset_id,
                        "project_id": project_id,
                        "cleanup_status": "pending",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    galileo = ModuleType("galileo")
    datasets = ModuleType("galileo.datasets")
    projects = ModuleType("galileo.projects")
    prompts = ModuleType("galileo.prompts")
    datasets.get_dataset = lambda **_kwargs: {"id": dataset_id, "name": "dataset"}
    datasets.delete_dataset = lambda **_kwargs: None
    projects.delete_project = lambda **_kwargs: pytest.fail("project cleanup must not run")
    prompts.get_prompt = lambda **_kwargs: None
    prompts.delete_prompt = lambda **_kwargs: None
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.datasets", datasets)
    monkeypatch.setitem(sys.modules, "galileo.projects", projects)
    monkeypatch.setitem(sys.modules, "galileo.prompts", prompts)

    with pytest.raises(RuntimeError, match="still exists after deletion"):
        lifecycle.cleanup_created_objects(ledger_path, dry_run=False)

    retained = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert {item["cleanup_status"] for item in retained["created_objects"]} == {
        "pending"
    }


def test_cleanup_ledger_keeps_prompt_pending_when_delete_is_not_observed(
    monkeypatch, tmp_path: Path
) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_cleanup_prompt_noop")
    project_id = "11111111-1111-4111-8111-111111111111"
    prompt_id = "55555555-5555-4555-8555-555555555555"
    ledger_path = tmp_path / "ownership.json"
    ledger_path.write_text(
        json.dumps(
            {
                "api_version": "galileo-platform-setup/object-lifecycle-ownership/v1",
                "created_by": "galileo_object_lifecycle.py",
                "operation_id": "44444444-4444-4444-8444-444444444444",
                "created_objects": [
                    {
                        "kind": "project",
                        "id": project_id,
                        "project_id": project_id,
                        "cleanup_status": "pending",
                    },
                    {
                        "kind": "prompt",
                        "id": prompt_id,
                        "project_id": project_id,
                        "cleanup_status": "pending",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    galileo = ModuleType("galileo")
    datasets = ModuleType("galileo.datasets")
    projects = ModuleType("galileo.projects")
    prompts = ModuleType("galileo.prompts")
    datasets.get_dataset = lambda **_kwargs: None
    datasets.delete_dataset = lambda **_kwargs: None
    projects.delete_project = lambda **_kwargs: pytest.fail("project cleanup must not run")
    prompts.get_prompt = lambda **_kwargs: {"id": prompt_id, "name": "prompt"}
    prompts.delete_prompt = lambda **_kwargs: None
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.datasets", datasets)
    monkeypatch.setitem(sys.modules, "galileo.projects", projects)
    monkeypatch.setitem(sys.modules, "galileo.prompts", prompts)

    with pytest.raises(RuntimeError, match="still exists after deletion"):
        lifecycle.cleanup_created_objects(ledger_path, dry_run=False)

    retained = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert {item["cleanup_status"] for item in retained["created_objects"]} == {
        "pending"
    }


def test_cleanup_ledger_fails_closed_before_mutation_for_unowned_child_project(tmp_path: Path) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_cleanup_fail_closed")
    ledger_path = tmp_path / "ownership.json"
    ledger_path.write_text(
        json.dumps(
            {
                "api_version": "galileo-platform-setup/object-lifecycle-ownership/v1",
                "created_by": "galileo_object_lifecycle.py",
                "operation_id": "44444444-4444-4444-8444-444444444444",
                "created_objects": [
                    {
                        "kind": "log_stream",
                        "id": "22222222-2222-4222-8222-222222222222",
                        "project_id": "11111111-1111-4111-8111-111111111111",
                        "cleanup_status": "pending",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="project was not created by this ledger"):
        lifecycle.cleanup_created_objects(ledger_path, dry_run=False)


def test_experiment_group_is_forwarded_only_when_configured(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_groups")
    calls: list[dict[str, object]] = []
    group_queries: list[dict[str, object]] = []
    galileo = ModuleType("galileo")
    experiments = ModuleType("galileo.experiments")

    def get_experiment(**_kwargs):
        return None

    def create_experiment(**kwargs):
        calls.append(kwargs)
        return {"id": f"experiment-{len(calls)}", "name": kwargs["experiment_name"]}

    def get_experiments(**kwargs):
        group_queries.append(kwargs)
        return [{"id": "experiment-2", "name": "grouped"}]

    experiments.get_experiment = get_experiment
    experiments.get_experiments = get_experiments
    experiments.create_experiment = create_experiment
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.experiments", experiments)
    monkeypatch.setattr(lifecycle, "require_experiment_group_sdk", lambda: None)

    lifecycle.ensure_experiment(
        {"name": "ungrouped"},
        {"id": "project-id", "name": "project", "_created_by_operation": True},
        False,
    )
    grouped = lifecycle.ensure_experiment(
        {"name": "grouped", "experiment_group": "RAG Benchmark"},
        {"id": "project-id", "name": "project", "_created_by_operation": True},
        False,
    )

    assert "experiment_group" not in calls[0]
    assert "experiment_group_id" not in calls[0]
    assert calls[1]["experiment_group"] == "RAG Benchmark"
    assert "experiment_group_id" not in calls[1]
    assert grouped["experiment_group_verified"] is True
    assert group_queries == [
        {"project_id": "project-id", "experiment_group": "RAG Benchmark"}
    ]


def test_created_experiment_group_mismatch_is_not_reported_as_success(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_created_group_mismatch")
    galileo = ModuleType("galileo")
    experiments = ModuleType("galileo.experiments")
    experiments.get_experiment = lambda **_kwargs: None
    experiments.get_experiments = lambda **_kwargs: [
        {"id": "different-experiment-id", "name": "baseline"}
    ]
    experiments.create_experiment = lambda **kwargs: {
        "id": "experiment-id",
        "name": kwargs["experiment_name"],
    }
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.experiments", experiments)
    monkeypatch.setattr(lifecycle, "require_experiment_group_sdk", lambda: None)

    with pytest.raises(RuntimeError, match="was not found in requested group"):
        lifecycle.ensure_experiment(
            {"name": "baseline", "experiment_group": "RAG Benchmark"},
            {"id": "project-id", "name": "project", "_created_by_operation": True},
            False,
        )


def test_experiment_group_and_tags_are_forwarded_to_run(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_group_run")
    calls: list[dict[str, object]] = []
    galileo = ModuleType("galileo")
    datasets = ModuleType("galileo.datasets")
    prompts = ModuleType("galileo.prompts")
    experiments = ModuleType("galileo.experiments")
    datasets.get_dataset = lambda **_kwargs: None
    prompts.get_prompt = lambda **_kwargs: None

    def run_experiment(**kwargs):
        calls.append(kwargs)
        return {"id": "experiment-id", "name": kwargs["experiment_name"]}

    experiments.run_experiment = run_experiment
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.datasets", datasets)
    monkeypatch.setitem(sys.modules, "galileo.prompts", prompts)
    monkeypatch.setitem(sys.modules, "galileo.experiments", experiments)
    monkeypatch.setattr(lifecycle, "require_experiment_group_sdk", lambda: None)

    result = lifecycle.ensure_experiment(
        {
            "name": "large-rag-run",
            "mode": "run",
            "dataset": [{"input": "hello"}],
            "metrics": ["correctness"],
            "tags": {"scale": "large"},
            "experiment_group_id": "group-id",
        },
        {"id": "project-id", "name": "project", "_created_by_operation": True},
        False,
    )

    assert result["status"] == "ran"
    assert result["experiment_group_id"] == "group-id"
    assert calls[0]["experiment_group_id"] == "group-id"
    assert "experiment_group" not in calls[0]
    assert calls[0]["experiment_tags"] == {"scale": "large"}


def test_existing_experiment_group_mismatch_is_not_reported_as_success(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_group_mismatch")
    galileo = ModuleType("galileo")
    experiments = ModuleType("galileo.experiments")
    existing = {
        "id": "experiment-id",
        "name": "baseline",
        "experiment_group_name": "Other Group",
    }
    experiments.get_experiment = lambda **_kwargs: existing
    experiments.get_experiments = lambda **_kwargs: [
        {"id": "different-experiment-id", "name": "baseline"}
    ]
    experiments.create_experiment = lambda **_kwargs: pytest.fail(
        "existing experiment must not be recreated"
    )
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.experiments", experiments)
    monkeypatch.setattr(lifecycle, "require_experiment_group_sdk", lambda: None)

    with pytest.raises(RuntimeError, match="not in requested group"):
        lifecycle.ensure_experiment(
            {"name": "baseline", "experiment_group": "RAG Benchmark"},
            {"id": "project-id", "name": "project"},
            False,
        )


def test_existing_experiment_group_is_verified_with_group_filtered_list(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_group_verified")
    galileo = ModuleType("galileo")
    experiments = ModuleType("galileo.experiments")
    existing = {"id": "experiment-id", "name": "baseline"}
    group_queries: list[dict[str, object]] = []
    experiments.get_experiment = lambda **_kwargs: existing

    def get_experiments(**kwargs):
        group_queries.append(kwargs)
        return [existing]

    experiments.get_experiments = get_experiments
    experiments.create_experiment = lambda **_kwargs: pytest.fail(
        "existing experiment must not be recreated"
    )
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.experiments", experiments)
    monkeypatch.setattr(lifecycle, "require_experiment_group_sdk", lambda: None)

    result = lifecycle.ensure_experiment(
        {"name": "baseline", "experiment_group": "RAG Benchmark"},
        {"id": "project-id", "name": "project"},
        False,
    )

    assert result["status"] == "exists"
    assert result["experiment_group_verified"] is True
    assert group_queries == [
        {"project_id": "project-id", "experiment_group": "RAG Benchmark"}
    ]


def test_experiment_group_requires_galileo_sdk_2_2(monkeypatch) -> None:
    lifecycle = load_script(LIFECYCLE, "galileo_object_lifecycle_group_version")
    monkeypatch.setattr(lifecycle, "version", lambda _name: "2.1.9")

    with pytest.raises(RuntimeError, match=r">= 2\.2\.0; found 2\.1\.9"):
        lifecycle.require_experiment_group_sdk()

    monkeypatch.setattr(lifecycle, "version", lambda _name: "2.2.0rc1")
    with pytest.raises(RuntimeError, match=r">= 2\.2\.0; found 2\.2\.0rc1"):
        lifecycle.require_experiment_group_sdk()


def test_luna_scorer_script_dry_run_builds_partial_replacement_plan(tmp_path: Path) -> None:
    token_file = tmp_path / "galileo.token"
    token_file.write_text("unused", encoding="utf-8")
    output = tmp_path / "luna-result.json"
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_file_location("galileo_luna_scorers", LUNA)
    )
    assert module.__spec__ and module.__spec__.loader
    module.__spec__.loader.exec_module(module)

    settings = {
        "scorers": [
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "name": "completeness",
                "scorer_type": "preset",
                "model_type": "llm",
                "input_type": "llm_spans",
                "output_type": "percentage",
                "filters": [{"name": "old_filter"}],
                "num_judges": 3,
                "scoreable_node_types": ["llm", "chat"],
            },
            {
                "id": "00000000-0000-4000-8000-000000000002",
                "name": "correctness",
                "scorer_type": "preset",
                "model_type": "llm",
                "input_type": "llm_spans",
                "output_type": "boolean_multilabel",
                "scoreable_node_types": ["llm", "chat"],
            },
            {
                "id": "00000000-0000-4000-8000-000000000005",
                "name": "agent_efficiency",
                "scorer_type": "preset",
                "model_type": "llm",
                "input_type": "sessions_normalized",
                "output_type": "boolean_multilabel",
                "scoreable_node_types": ["session"],
            },
        ],
        "segment_filters": None,
    }
    targets = {
        "completeness_luna": {
                "id": "00000000-0000-4000-8000-000000000003",
                "name": "completeness_luna",
                "scorer_type": "preset",
                "model_type": "slm",
                "output_type": "percentage",
                "defaults": {
                    "filters": [{"name": "luna_filter"}],
                    "num_judges": 1,
                    "scoreable_node_types": ["session"],
                },
            }
        }

    plan = module.build_metric_settings_plan(
        settings,
        module.normalize_replacements(
            {
                "strict": "false",
                "replacements": module.DEFAULT_REPLACEMENTS
                + [{"from": "agent_efficiency", "remove": True}],
                "custom_luna_scorer_ids": [
                    {
                        "from": "correctness",
                        "to_id": "00000000-0000-4000-8000-000000000004",
                        "scorer_type": "luna",
                        "model_type": "slm",
                    },
                    {"from": "agent_efficiency", "to_id": ""},
                ],
            }
        ),
        targets,
        strict=False,
    )

    assert plan["errors"] == []
    assert plan["applied"][0]["from"]["name"] == "completeness"
    assert plan["applied"][0]["to"]["name"] == "completeness_luna"
    assert plan["applied"][1]["from"]["name"] == "correctness"
    assert plan["applied"][1]["to"]["id"].endswith("0004")
    assert plan["unavailable"] == []
    assert plan["patch_body"]["scorers"][0]["id"].endswith("0003")
    assert plan["patch_body"]["scorers"][0]["model_type"] == "slm"
    assert plan["patch_body"]["scorers"][0]["input_type"] == "llm_spans"
    assert plan["patch_body"]["scorers"][0]["filters"] == [{"name": "luna_filter"}]
    assert plan["patch_body"]["scorers"][0]["num_judges"] == 1
    assert plan["patch_body"]["scorers"][0]["scoreable_node_types"] == ["session"]
    assert plan["patch_body"]["scorers"][1]["id"].endswith("0004")
    assert plan["patch_body"]["scorers"][1]["scorer_type"] == "luna"
    assert "scoreable_node_types" not in plan["patch_body"]["scorers"][1]
    assert [item["status"] for item in plan["applied"]] == ["planned", "planned", "removed"]
    assert all(not item["id"].endswith("0005") for item in plan["patch_body"]["scorers"])
    module.write_result(str(output), {"status": "planned"})
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "planned"


def test_repo_has_no_legacy_galileo_skill_references() -> None:
    legacy = "splunk-" + "galileo-integration"
    result = run_cmd("git", "grep", "-n", legacy, "--", ".", check=False)
    assert result.returncode == 1, result.stdout + result.stderr


def _alert_payload() -> dict[str, object]:
    return {
        "version": "1.0",
        "event": "alert.triggered",
        "event_id": "event-id",
        "timestamp": "2026-07-07T10:30:00Z",
        "alert": {
            "id": "alert-id",
            "name": "High hallucination rate",
            "status": "triggered",
            "previous_status": "healthy",
        },
        "scope": {
            "org_id": "org-id",
            "project_id": "project-id",
            "project_name": "project",
            "log_stream_id": "log-stream-id",
            "log_stream_name": "production",
        },
        "conditions": [
            {
                "metric": "metrics/context_adherence",
                "aggregation": "Average",
                "operator": "less than",
                "threshold": 0.5,
                "observed_value": 0.34,
            }
        ],
        "dedup_key": "alert-id:project-id:log-stream-id",
        "deep_link": "https://console.galileo.ai/example",
        "metadata": {"team": "platform", "env": "production"},
    }


@pytest.mark.parametrize("flag", ["--token", "--api-key", "--splunk-hec-token"])
def test_alert_relay_rejects_direct_secrets_without_echoing_values(flag: str) -> None:
    relay = load_script(ALERT_RELAY, "galileo_alert_webhook_relay_secret_flags")
    secret = "WEBHOOK_SECRET_SHOULD_NOT_ECHO"

    with pytest.raises(SystemExit) as exc:
        relay.parse_args([f"{flag}={secret}"])

    assert secret not in str(exc.value)
    assert "--galileo-webhook-token-file" in str(exc.value)


def test_alert_relay_requires_private_secret_file_permissions(tmp_path: Path) -> None:
    relay = load_script(ALERT_RELAY, "galileo_alert_webhook_relay_permissions")
    secret_file = tmp_path / "webhook.token"
    secret_file.write_text("shared-secret", encoding="utf-8")
    secret_file.chmod(0o644)

    with pytest.raises(RuntimeError, match="0600"):
        relay.read_secret_file(str(secret_file), "Webhook token file")

    secret_file.chmod(0o600)
    assert relay.read_secret_file(str(secret_file), "Webhook token file") == "shared-secret"


def test_alert_relay_validates_v1_payload_and_builds_searchable_hec_envelope() -> None:
    relay = load_script(ALERT_RELAY, "galileo_alert_webhook_relay_envelope")
    payload = relay.validate_payload(_alert_payload())
    args = Namespace(
        splunk_source="galileo-alert-webhook",
        splunk_sourcetype="galileo:alert:webhook:json",
        splunk_index="galileo",
        splunk_host="relay-1",
    )

    envelope = relay.build_hec_envelope(payload, args)

    assert envelope["event"] == payload
    assert envelope["time"] == 1783420200.0
    assert envelope["host"] == "relay-1"
    assert envelope["fields"] == {
        "galileo_alert_event_id": "event-id",
        "galileo_alert_event_type": "alert.triggered",
        "galileo_alert_dedup_key": "alert-id:project-id:log-stream-id",
        "galileo_alert_id": "alert-id",
        "galileo_alert_status": "triggered",
        "galileo_project_id": "project-id",
        "galileo_log_stream_id": "log-stream-id",
    }

    invalid = _alert_payload()
    invalid["version"] = "2.0"
    with pytest.raises(ValueError, match="version"):
        relay.validate_payload(invalid)

    for section in ("alert", "scope"):
        invalid = _alert_payload()
        invalid[section] = {}
        with pytest.raises(ValueError, match=f"{section} field"):
            relay.validate_payload(invalid)

    invalid = _alert_payload()
    invalid["conditions"] = []
    with pytest.raises(ValueError, match="conditions array"):
        relay.validate_payload(invalid)


def test_alert_relay_requires_explicit_public_listener_review() -> None:
    relay = load_script(ALERT_RELAY, "galileo_alert_webhook_relay_listener")

    relay.validate_listener("127.0.0.1", allow_public=False)
    relay.validate_listener("relay.localhost", allow_public=False)
    with pytest.raises(RuntimeError, match="allow-public-http-listener"):
        relay.validate_listener("0.0.0.0", allow_public=False)
    relay.validate_listener("0.0.0.0", allow_public=True)


def test_alert_relay_rejects_external_plain_http_hec() -> None:
    bridge = load_bridge()
    relay = load_script(ALERT_RELAY, "galileo_alert_webhook_relay_hec_url")

    with pytest.raises(RuntimeError, match="HTTPS"):
        relay.normalize_hec_url("http://splunk.example.com:8088")
    with pytest.raises(SystemExit, match="HTTPS"):
        bridge.normalize_hec_url("http://splunk.example.com:8088")

    assert (
        relay.normalize_hec_url("http://127.0.0.1:8088")
        == "http://127.0.0.1:8088/services/collector/event"
    )
    assert (
        bridge.normalize_hec_url("http://127.0.0.1:8088")
        == "http://127.0.0.1:8088/services/collector/event"
    )
    assert (
        relay.normalize_hec_url(
            "http://splunk.example.com:8088", allow_insecure_http=True
        )
        == "http://splunk.example.com:8088/services/collector/event"
    )
    assert (
        relay.normalize_hec_url("https://splunk.example.com:8088/services/collector")
        == "https://splunk.example.com:8088/services/collector/event"
    )
    for unsafe_url in (
        "https://user:secret@splunk.example.com:8088/services/collector/event",
        "https://splunk.example.com:8088/services/collector/event?token=secret",
        "https://splunk.example.com:bad/services/collector/event",
    ):
        with pytest.raises(RuntimeError):
            relay.normalize_hec_url(unsafe_url)
        with pytest.raises(SystemExit):
            bridge.normalize_hec_url(unsafe_url)


def test_alert_relay_treats_non_json_hec_success_as_upstream_failure(monkeypatch) -> None:
    relay = load_script(ALERT_RELAY, "galileo_alert_webhook_relay_hec_response")

    class Response:
        status = 200

        def read(self, _limit):
            return b"not-json"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(relay, "open_without_redirect", lambda *_args, **_kwargs: Response())

    with pytest.raises(RuntimeError, match="non-JSON"):
        relay.send_to_hec(
            {"event": _alert_payload()},
            hec_url="https://splunk.example.com:8088/services/collector/event",
            hec_token="unused-test-token",
            ca_file="",
        )


@pytest.mark.parametrize("body", [b"", b"[]", b'{"text":"Success"}'])
def test_alert_relay_requires_explicit_hec_code_zero(monkeypatch, body: bytes) -> None:
    relay = load_script(ALERT_RELAY, "galileo_alert_webhook_relay_hec_code")

    class Response:
        status = 200

        def read(self, _limit):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(relay, "open_without_redirect", lambda *_args, **_kwargs: Response())

    with pytest.raises(RuntimeError, match="empty response|rejected event"):
        relay.send_to_hec(
            {"event": _alert_payload()},
            hec_url="https://splunk.example.com:8088/services/collector/event",
            hec_token="unused-test-token",
            ca_file="",
        )


def test_galileo_and_hec_clients_disable_http_redirects() -> None:
    bridge = load_script(BRIDGE, "galileo_to_splunk_hec_no_redirect")
    relay = load_script(ALERT_RELAY, "galileo_alert_webhook_relay_no_redirect")

    for handler in (bridge.NoRedirectHandler(), relay.NoRedirectHandler()):
        assert handler.redirect_request(None, None, 302, "Found", {}, "https://other") is None


def test_python_scripts_compile() -> None:
    run_cmd(
        sys.executable,
        "-m",
        "py_compile",
        str(RENDER),
        str(BRIDGE),
        str(LIFECYCLE),
        str(LUNA),
        str(ALERT_RELAY),
    )
