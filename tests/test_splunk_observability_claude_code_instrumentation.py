#!/usr/bin/env python3
"""Regression coverage for the Claude Code OTel instrumentation skill."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from tests.regression_helpers import REPO_ROOT
from skills.shared.coding_agent_o11y import claude_code as cc_o11y
from skills.shared.coding_agent_o11y.common import scan_rendered_for_secret_leaks

PARENT = REPO_ROOT / "skills/splunk-observability-coding-agent-instrumentation-setup/scripts/setup.sh"
CLAUDE = REPO_ROOT / "skills/splunk-observability-claude-code-instrumentation-setup/scripts/setup.sh"
CLAUDE_VALIDATE = REPO_ROOT / "skills/splunk-observability-claude-code-instrumentation-setup/scripts/validate.sh"
PUBLIC_GALILEO_CONSOLE = "https://app.galileo.ai/"


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


def run_claude(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    argv = list(args)
    destination = argv[argv.index("--destination") + 1] if "--destination" in argv else "local-collector"
    galileo_requested = "--galileo-project" in argv or "--galileo-enabled" in argv
    instance_supplied = (
        "--galileo-console-url" in argv or "--galileo-otel-endpoint" in argv
    )
    if (
        galileo_requested
        and "--disable-galileo" not in argv
        and destination != "splunk-direct"
        and not instance_supplied
    ):
        # Normal Galileo-enabled regression cases explicitly confirm the public
        # instance. Dedicated negative coverage below bypasses this helper.
        argv.extend(["--galileo-console-url", PUBLIC_GALILEO_CONSOLE])
    return run_cmd("bash", str(CLAUDE), *argv, check=check)


def rendered_text(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


# ---------------------------------------------------------------------------
# Parent router tests — claude-code agent
# ---------------------------------------------------------------------------


def test_parent_discover_includes_claude_code() -> None:
    result = run_cmd("bash", str(PARENT), "--discover", "--json")
    payload = json.loads(result.stdout)
    assert "claude-code" in payload["agents"]
    assert "claude-code" in payload["implemented_agents"]


def test_parent_execute_dry_run_json_returns_exact_child_command_claude_code() -> None:
    result = run_cmd(
        "bash",
        str(PARENT),
        "--execute",
        "--dry-run",
        "--json",
        "--agent",
        "claude-code",
        "--destination",
        "local-collector",
    )
    payload = json.loads(result.stdout)
    assert payload["router_only"] is True
    assert payload["would_execute"] == [
        "bash",
        "skills/splunk-observability-claude-code-instrumentation-setup/scripts/setup.sh",
        "--render",
        "--destination",
        "local-collector",
    ]


def test_parent_execute_dry_run_splunk_direct_warns_about_galileo() -> None:
    result = run_cmd(
        "bash",
        str(PARENT),
        "--execute",
        "--dry-run",
        "--json",
        "--agent",
        "claude-code",
        "--destination",
        "direct",
    )
    payload = json.loads(result.stdout)
    assert payload["would_execute"][0] == "bash"
    assert "claude-code-instrumentation-setup/scripts/setup.sh" in payload["would_execute"][1]
    assert payload["would_execute"][-1] == "splunk-direct"


# ---------------------------------------------------------------------------
# local-collector destination
# ---------------------------------------------------------------------------


def test_local_collector_renders_valid_settings_and_collector_overlay(tmp_path: Path) -> None:
    out = tmp_path / "local"
    result = run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--realm",
        "us1",
        "--galileo-project",
        "my-project",
        "--galileo-log-stream",
        "default",
        "--enable-traces-beta",
        "--json",
        "--output-dir",
        str(out),
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["errors"] == []

    # Settings file
    settings_files = list((out / "settings").glob("*.json"))
    assert settings_files, "Expected at least one settings JSON file"
    settings = json.loads(settings_files[0].read_text(encoding="utf-8"))
    env = settings["env"]
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert env["OTEL_METRICS_EXPORTER"] == "otlp"
    assert env["OTEL_LOGS_EXPORTER"] == "otlp"
    assert env["OTEL_TRACES_EXPORTER"] == "otlp"
    assert env["CLAUDE_CODE_ENHANCED_TELEMETRY_BETA"] == "1"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://127.0.0.1:14318"
    assert env["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/protobuf"
    assert "sf_environment=prod" in env["OTEL_RESOURCE_ATTRIBUTES"]
    assert "sf_service=claude-code" in env["OTEL_RESOURCE_ATTRIBUTES"]
    assert "deployment.environment.name=prod" in env["OTEL_RESOURCE_ATTRIBUTES"]
    # NO literal token anywhere
    assert "X-SF-TOKEN" not in json.dumps(settings)
    assert "OTEL_EXPORTER_OTLP_HEADERS" not in env

    # Collector overlay
    overlay_path = out / "collector" / "claude-code-o11y-local-collector.yaml"
    assert overlay_path.is_file()
    overlay = overlay_path.read_text(encoding="utf-8")
    assert "send_otlp_histograms: true" in overlay
    assert "otlp_http/galileo" in overlay
    assert "https://api.galileo.ai/otel/traces" in overlay
    assert '${env:GALILEO_API_KEY}' in overlay
    assert "project: " in overlay
    assert "logstream: " in overlay
    assert "otlp_http/claude_code_traces" in overlay
    assert "otlp_http/claude_code_metrics" in overlay
    assert "otlp_http/claude_code_logs" in overlay
    assert "https://ingest.us1.observability.splunkcloud.com/v2/datapoint/otlp" in overlay
    assert "https://ingest.us1.observability.splunkcloud.com/v2/log/otlp" in overlay
    assert "https://ingest.us1.observability.splunkcloud.com/v2/trace/otlp" in overlay
    assert '${env:SPLUNK_ACCESS_TOKEN}' in overlay
    assert "key: sf_environment" in overlay
    assert "key: sf_service" in overlay
    # Galileo trace pipeline fans out to Splunk and Galileo. Native cumulative
    # token metrics are converted to the histogram required by the AI overview.
    assert "otlp_http/claude_code_traces" in overlay
    assert "otlp_http/galileo" in overlay
    assert "sum/claude_code_input_tokens" not in overlay
    assert "sum/claude_code_output_tokens" not in overlay
    assert "gen_ai.client.token.usage" in overlay
    assert "transform/claude_code_token_metric_genai" in overlay
    assert "filter/claude_code_token_metrics" in overlay
    assert 'set(datapoint.attributes["gen_ai.response.model"], datapoint.attributes["gen_ai.request.model"])' in overlay
    assert "cumulativetodelta/claude_code_tokens" in overlay
    assert "signal_to_metrics/claude_code_token_histogram" in overlay
    assert 'unit: "{token}"' in overlay
    assert "Double(datapoint.value_int) + datapoint.value_double" in overlay
    assert "67108864" in overlay
    assert "metrics/claude_code_token_genai" in overlay
    assert "metrics/claude_code_token_histogram" in overlay
    assert "span_metrics/claude_code_genai" in overlay
    assert "namespace: gen_ai.client.operation" in overlay
    assert "unit: s" in overlay
    assert "metrics/claude_code_genai_duration" in overlay
    assert "traces/claude_code_galileo" in overlay
    assert "transform/claude_code_galileo" in overlay
    assert "filter/claude_code_galileo_genai" in overlay
    assert 'span.attributes["user_prompt"]' in overlay
    assert 'span.attributes["response.model_output"]' in overlay
    assert 'span.attributes["llm.input_messages.0.message.content"]' in overlay
    assert 'span.attributes["llm.output_messages.0.message.content"]' in overlay
    assert 'span.cache["claude_tools"]' in overlay
    assert 'flatten(span.cache["claude_tools"])' in overlay
    assert 'replace_all_patterns(span.cache["claude_tools"], "key"' in overlay
    assert 'replace_all_patterns(span.cache["claude_tools"], "value"' in overlay
    assert 'merge_maps(span.attributes, span.cache["claude_tools"], "upsert")' in overlay
    assert 'span.attributes["gen_ai.tool.definitions"]' in overlay
    assert 'span.attributes["claude_code.galileo.available_tools_count"]' in overlay
    assert 'set(span.attributes["llm.tools"], span.attributes["tools"])' not in overlay
    assert 'span.attributes["gen_ai.operation.name"], "execute_tool"' in overlay
    assert 'span.attributes["gen_ai.tool.name"]' in overlay
    assert 'span.attributes["gen_ai.tool.call.arguments"]' in overlay
    assert 'span.attributes["gen_ai.tool.call.result"]' in overlay
    assert 'spanevent.name == "tool.output"' in overlay
    assert 'span.attributes["span.type"] == "tool.execution"' in overlay
    assert 'delete_key(resource.attributes, "_claude_code.galileo.final_output")' in overlay
    # GenAI-convention transform bridges Claude Code spans to the AI overview.
    assert "transform/claude_code_genai" in overlay
    assert 'set(span.attributes["gen_ai.operation.name"], "chat")' in overlay
    assert 'set(span.attributes["gen_ai.agent.name"], "claude-code")' in overlay
    assert 'set(span.attributes["gen_ai.operation.name"], "invoke_workflow")' in overlay
    assert 'gen_ai.workflow.name' in overlay
    assert "SPAN_KIND_CLIENT" in overlay
    assert 'gen_ai.usage.input_tokens' in overlay
    assert 'gen_ai.response.model' in overlay
    assert 'gen_ai.provider.name' in overlay
    # Transform runs in the traces pipeline before batch.
    assert "resource/claude_code, transform/claude_code_genai, batch/claude_code" in overlay
    assert (
        "resource/claude_code, transform/claude_code_genai, "
        "transform/claude_code_galileo, filter/claude_code_galileo_genai, "
        "batch/claude_code"
    ) in overlay
    shared_routing = (out / "runtime" / "shared-collector-routing.md").read_text(encoding="utf-8")
    assert "context: span" in shared_routing
    assert "context: metric" in shared_routing
    assert "context: datapoint" in shared_routing
    assert "context: log" in shared_routing
    assert 'name == "claude_code.token.usage"' in shared_routing
    assert "metrics/claude_code_token_genai" in shared_routing
    assert "transform/claude_code_token_metric_genai" in shared_routing
    assert "cumulativetodelta/claude_code_tokens" in shared_routing
    assert "signal_to_metrics/claude_code_token_histogram" in shared_routing
    assert "metrics/claude_code_token_histogram" in shared_routing
    assert "span_metrics/claude_code_genai" in shared_routing
    assert "unit: s" in shared_routing
    assert "metrics/claude_code_genai_duration" in shared_routing
    assert "otlp_http/claude_code_metrics" in shared_routing
    assert "127.0.0.1:14318:4318" in shared_routing
    assert "0.0.0.0:4318" in shared_routing


def test_detailed_traces_opt_in_emits_beta_endpoint(tmp_path: Path) -> None:
    out = tmp_path / "detailed"
    run_claude(
        "--render", "--destination", "local-collector",
        "--realm", "us1", "--galileo-project", "coding-agents",
        "--enable-detailed-traces", "--accept-content-capture",
        "--output-dir", str(out),
    )
    env = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))["env"]
    assert env["ENABLE_BETA_TRACING_DETAILED"] == "1"
    # BETA_TRACING_ENDPOINT is a SEPARATE endpoint; for local-collector it must match
    # the OTLP endpoint so child spans reach the same collector.
    assert env["BETA_TRACING_ENDPOINT"] == env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://127.0.0.1:14318"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2.1.197 (Claude Code)", (2, 1, 197)),
        ("claude-code v2.1.193", (2, 1, 193)),
        ("not-a-version", None),
    ],
)
def test_parse_claude_code_version(
    raw: str, expected: tuple[int, int, int] | None
) -> None:
    assert cc_o11y.parse_claude_code_version(raw) == expected


def test_assistant_response_version_preflight_rejects_old_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cc_o11y.shutil, "which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        cc_o11y.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout="2.1.185 (Claude Code)\n", stderr=""
        ),
    )
    with pytest.raises(cc_o11y.UsageError, match="v2.1.193 or newer"):
        cc_o11y.require_assistant_response_capable_claude()


def test_assistant_response_version_preflight_accepts_supported_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cc_o11y.shutil, "which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        cc_o11y.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout="2.1.197 (Claude Code)\n", stderr=""
        ),
    )
    assert cc_o11y.require_assistant_response_capable_claude() == (2, 1, 197)


def test_detailed_traces_splunk_direct_points_beta_at_trace_endpoint(tmp_path: Path) -> None:
    out = tmp_path / "detailed-direct"
    run_claude(
        "--render", "--destination", "splunk-direct", "--realm", "us1",
        "--enable-detailed-traces", "--accept-content-capture",
        "--output-dir", str(out),
    )
    env = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))["env"]
    assert env["ENABLE_BETA_TRACING_DETAILED"] == "1"
    assert env["BETA_TRACING_ENDPOINT"] == env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"]
    assert env["BETA_TRACING_ENDPOINT"].endswith("/v2/trace/otlp")


def test_detailed_traces_require_content_capture_acceptance(tmp_path: Path) -> None:
    result = run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--enable-detailed-traces",
        "--disable-galileo",
        "--output-dir",
        str(tmp_path / "detailed-without-consent"),
        check=False,
    )
    assert result.returncode != 0
    assert "content-bearing span attributes" in result.stdout + result.stderr


def test_detailed_traces_default_off_omits_beta_vars(tmp_path: Path) -> None:
    out = tmp_path / "no-detailed"
    run_claude(
        "--render", "--destination", "local-collector",
        "--realm", "us1", "--galileo-project", "coding-agents",
        "--output-dir", str(out),
    )
    env = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))["env"]
    assert "ENABLE_BETA_TRACING_DETAILED" not in env
    assert "BETA_TRACING_ENDPOINT" not in env
    # Base traces beta remains on and emits current llm_request/tool spans.
    assert env["OTEL_TRACES_EXPORTER"] == "otlp"


def test_disable_traces_beta_also_disables_detailed(tmp_path: Path) -> None:
    out = tmp_path / "no-traces"
    run_claude(
        "--render", "--destination", "local-collector",
        "--realm", "us1", "--disable-galileo",
        "--disable-traces-beta",
        "--output-dir", str(out),
    )
    env = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))["env"]
    assert "OTEL_TRACES_EXPORTER" not in env
    assert "ENABLE_BETA_TRACING_DETAILED" not in env
    assert "BETA_TRACING_ENDPOINT" not in env


def test_merge_strips_stale_beta_tracing_endpoint(tmp_path: Path) -> None:
    """Switching destinations must not leave a stale BETA_TRACING_ENDPOINT behind."""
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({
        "env": {
            "ENABLE_BETA_TRACING_DETAILED": "1",
            "BETA_TRACING_ENDPOINT": "https://old-endpoint.example.com/v2/trace/otlp",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:99999",
            "MY_CUSTOM_KEY": "keep-me",
        },
        "model": "sonnet",
    }), encoding="utf-8")
    # Render a splunk-direct profile then merge it over the stale target.
    out = tmp_path / "render"
    run_claude("--render", "--destination", "splunk-direct", "--realm", "us1",
               "--output-dir", str(out))
    source = next((out / "settings").glob("*.json"))
    cc_o11y.merge_settings_file(source, target)
    merged = json.loads(target.read_text(encoding="utf-8"))["env"]
    # Detailed tracing defaults off, so stale managed values are removed.
    assert "ENABLE_BETA_TRACING_DETAILED" not in merged
    assert "BETA_TRACING_ENDPOINT" not in merged
    # Unmanaged key preserved.
    assert merged["MY_CUSTOM_KEY"] == "keep-me"


def test_disable_detailed_traces_omits_beta_vars(tmp_path: Path) -> None:
    out = tmp_path / "no-detailed"
    run_claude(
        "--render", "--destination", "local-collector",
        "--realm", "us1", "--galileo-project", "coding-agents",
        "--disable-detailed-traces",
        "--output-dir", str(out),
    )
    env = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))["env"]
    assert "ENABLE_BETA_TRACING_DETAILED" not in env
    assert "BETA_TRACING_ENDPOINT" not in env
    # Base traces beta remains on.
    assert env["OTEL_TRACES_EXPORTER"] == "otlp"


def test_local_collector_custom_endpoint(tmp_path: Path) -> None:
    out = tmp_path / "custom"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--local-collector-endpoint",
        "http://localhost:24318",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(out),
    )
    settings = json.loads(
        next((out / "settings").glob("*.json")).read_text(encoding="utf-8")
    )
    assert settings["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:24318"
    overlay = (out / "collector" / "claude-code-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert 'endpoint: "localhost:24318"' in overlay


def test_local_collector_without_galileo_omits_galileo_exporter(tmp_path: Path) -> None:
    out = tmp_path / "no-galileo"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    overlay = (out / "collector" / "claude-code-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert "otlp_http/galileo" not in overlay
    assert "GALILEO" not in overlay


def test_local_collector_galileo_project_required_when_galileo_enabled(tmp_path: Path) -> None:
    result = run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--galileo-enabled",
        "--output-dir",
        str(tmp_path / "bad"),
        check=False,
    )
    assert result.returncode != 0
    assert "galileo" in (result.stdout + result.stderr).lower()


def test_local_collector_rejects_http_local_endpoint_with_path(tmp_path: Path) -> None:
    result = run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--local-collector-endpoint",
        "http://localhost:14318/v1/traces",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(tmp_path / "bad"),
        check=False,
    )
    assert result.returncode != 0
    assert "base URL" in result.stdout + result.stderr


def test_local_collector_rejects_https_local_endpoint(tmp_path: Path) -> None:
    result = run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--local-collector-endpoint",
        "https://localhost:14318",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(tmp_path / "bad-https"),
        check=False,
    )
    assert result.returncode != 0
    assert "http://" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# splunk-direct destination
# ---------------------------------------------------------------------------


def test_splunk_direct_renders_per_signal_endpoints_and_headers_helper(tmp_path: Path) -> None:
    out = tmp_path / "direct"
    result = run_claude(
        "--render",
        "--destination",
        "splunk-direct",
        "--realm",
        "us1",
        "--galileo-enabled",
        "--enable-traces-beta",
        "--json",
        "--output-dir",
        str(out),
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    # Galileo warning expected (splunk-direct cannot fan out to Galileo)
    assert any("splunk-direct" in w or "Galileo" in w for w in payload["warnings"])

    settings_files = list((out / "settings").glob("*.json"))
    assert settings_files, "Expected at least one settings JSON file"
    settings = json.loads(settings_files[0].read_text(encoding="utf-8"))
    env = settings["env"]
    # Per-signal endpoints for direct mode
    assert "ingest.us1.observability.splunkcloud.com/v2/datapoint/otlp" in env["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"]
    assert "ingest.us1.observability.splunkcloud.com/v2/log/otlp" in env["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"]
    assert "ingest.us1.observability.splunkcloud.com/v2/trace/otlp" in env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"]
    # Token must NOT be in the settings file or env block
    assert "OTEL_EXPORTER_OTLP_HEADERS" not in env
    assert "X-SF-TOKEN" not in json.dumps(settings)
    # otelHeadersHelper key must point at the rendered helper
    assert "otelHeadersHelper" in settings
    assert str(Path.home() / ".claude" / "bin" / "claude-code-otel-headers.sh") == settings["otelHeadersHelper"]

    # Headers helper exists, is executable, and never contains a literal token
    helper = out / "bin" / "claude-code-otel-headers.sh"
    assert helper.is_file()
    assert helper.stat().st_mode & stat.S_IXUSR
    helper_text = helper.read_text(encoding="utf-8")
    assert "SPLUNK_O11Y_TOKEN_FILE" in helper_text
    assert "X-SF-TOKEN" in helper_text
    assert '"$token"' not in helper_text
    # The helper must not contain any hardcoded token value (high-entropy string)
    # but IS allowed to reference env var names and comments
    import re
    # Look for assignment of a non-placeholder secret-like value (28+ chars of base64/hex)
    secret_pattern = re.compile(r'X-SF-TOKEN["\s]*[=:]["\s]*(?!\$)[A-Za-z0-9+/=_-]{20,}')
    assert not secret_pattern.search(helper_text), "Found hardcoded token in headers helper"

    # No collector overlay for direct mode
    assert not (out / "collector").exists()


def test_splunk_direct_without_realm_uses_default_realm(tmp_path: Path) -> None:
    """splunk-direct uses the default realm (us0) when none is explicitly set."""
    out = tmp_path / "default-realm"
    result = run_claude(
        "--render",
        "--destination",
        "splunk-direct",
        "--disable-galileo",
        "--json",
        "--output-dir",
        str(out),
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    settings = json.loads(
        next((out / "settings").glob("*.json")).read_text(encoding="utf-8")
    )
    # Default realm is us0
    assert "ingest.us0.observability.splunkcloud.com" in settings["env"]["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"]


def test_splunk_direct_with_galileo_disabled_has_no_warning(tmp_path: Path) -> None:
    out = tmp_path / "direct-no-galileo"
    result = run_claude(
        "--render",
        "--destination",
        "splunk-direct",
        "--realm",
        "us0",
        "--disable-galileo",
        "--json",
        "--output-dir",
        str(out),
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    galileo_warnings = [w for w in payload.get("warnings", []) if "Galileo" in w or "galileo" in w]
    assert not galileo_warnings


# ---------------------------------------------------------------------------
# external-collector destination
# ---------------------------------------------------------------------------


def test_external_collector_uses_shared_endpoint_and_renders_no_overlay(tmp_path: Path) -> None:
    out = tmp_path / "external"
    result = run_claude(
        "--render",
        "--destination",
        "external-collector",
        "--external-collector-endpoint",
        "https://otel-gateway.example.com:4318",
        "--external-collector-protocol",
        "otlp-http",
        "--disable-galileo",
        "--json",
        "--output-dir",
        str(out),
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    settings = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))
    env = settings["env"]
    assert env["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/protobuf"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://otel-gateway.example.com:4318"
    assert not (out / "collector").exists()


# ---------------------------------------------------------------------------
# all destination
# ---------------------------------------------------------------------------


def test_all_destination_renders_both_local_and_direct_settings(tmp_path: Path) -> None:
    out = tmp_path / "all"
    result = run_claude(
        "--render",
        "--destination",
        "all",
        "--realm",
        "us1",
        "--galileo-project",
        "proj",
        "--json",
        "--output-dir",
        str(out),
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    settings_files = list((out / "settings").glob("*.json"))
    destinations_in_filenames = {f.name for f in settings_files}
    assert any("local" in n for n in destinations_in_filenames)
    assert any("direct" in n for n in destinations_in_filenames)
    # Collector overlay is rendered for 'all' (contains local-collector path)
    assert (out / "collector" / "claude-code-o11y-local-collector.yaml").is_file()
    # Headers helper is rendered for 'all' (contains splunk-direct path)
    assert (out / "bin" / "claude-code-otel-headers.sh").is_file()


# ---------------------------------------------------------------------------
# Secret safety
# ---------------------------------------------------------------------------


def test_no_secret_leaks_in_local_collector_render(tmp_path: Path) -> None:
    out = tmp_path / "scan"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--realm",
        "us1",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(out),
    )
    errors = scan_rendered_for_secret_leaks(out)
    assert errors == [], f"Secret leaks found: {errors}"


def test_no_secret_leaks_in_splunk_direct_render(tmp_path: Path) -> None:
    out = tmp_path / "scan-direct"
    run_claude(
        "--render",
        "--destination",
        "splunk-direct",
        "--realm",
        "us0",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    errors = scan_rendered_for_secret_leaks(out)
    assert errors == [], f"Secret leaks found: {errors}"


@pytest.mark.parametrize(
    "argv",
    [
        ["--render", "--token", "SUPER_SECRET"],
        ["--render", "--token=SUPER_SECRET"],
        ["--render", "--access-token", "X"],
        ["--render", "--access-token=X"],
        ["--render", "--sf-token", "X"],
        ["--render", "--sf-token=X"],
        ["--render", "--o11y-token", "X"],
        ["--render", "--o11y-token=X"],
        ["--render", "--api-key", "X"],
        ["--render", "--api-key=X"],
        ["--render", "--galileo-api-key", "X"],
        ["--render", "--galileo-api-key=X"],
        ["--render", "--password", "X"],
        ["--render", "--password=X"],
        ["--render", "--TOKEN=X"],       # locks re.IGNORECASE
        ["--render", "--API-KEY", "X"],  # uppercase, space form
    ],
)
def test_reject_secret_argv(argv) -> None:
    result = run_claude(*argv, check=False)
    assert result.returncode != 0
    assert "secret" in (result.stdout + result.stderr).lower()


# ---------------------------------------------------------------------------
# Content capture gating
# ---------------------------------------------------------------------------


def test_content_capture_requires_accept_flag(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps({
            "api_version": "splunk-observability-claude-code-instrumentation-setup/v1",
            "claude_code": {
                "log_user_prompts": True,
                "galileo_project": "proj",
            },
        }),
        encoding="utf-8",
    )
    result = run_claude(
        "--render",
        "--spec",
        str(spec),
        "--destination",
        "local-collector",
        "--output-dir",
        str(tmp_path / "out"),
        check=False,
    )
    assert result.returncode != 0
    assert "accept-content-capture" in result.stdout + result.stderr


def test_content_capture_with_accept_flag_renders_env_flags(tmp_path: Path) -> None:
    out = tmp_path / "content"
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps({
            "api_version": "splunk-observability-claude-code-instrumentation-setup/v1",
            "claude_code": {
                "log_user_prompts": True,
                "log_assistant_responses": True,
                "galileo_project": "proj",
            },
        }),
        encoding="utf-8",
    )
    run_claude(
        "--render",
        "--spec",
        str(spec),
        "--destination",
        "local-collector",
        "--accept-content-capture",
        "--output-dir",
        str(out),
    )
    settings = json.loads(
        next((out / "settings").glob("*.json")).read_text(encoding="utf-8")
    )
    env = settings["env"]
    assert env.get("OTEL_LOG_USER_PROMPTS") == "1"
    assert env.get("OTEL_LOG_ASSISTANT_RESPONSES") == "1"


# ---------------------------------------------------------------------------
# Traces beta gating
# ---------------------------------------------------------------------------


def test_traces_beta_off_by_default_does_not_render_trace_exporter(tmp_path: Path) -> None:
    out = tmp_path / "no-traces"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--disable-traces-beta",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    settings = json.loads(
        next((out / "settings").glob("*.json")).read_text(encoding="utf-8")
    )
    env = settings["env"]
    assert "OTEL_TRACES_EXPORTER" not in env
    assert "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA" not in env


def test_traces_beta_renders_when_enabled(tmp_path: Path) -> None:
    out = tmp_path / "traces"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--enable-traces-beta",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(out),
    )
    settings = json.loads(
        next((out / "settings").glob("*.json")).read_text(encoding="utf-8")
    )
    env = settings["env"]
    assert env.get("OTEL_TRACES_EXPORTER") == "otlp"
    assert env.get("CLAUDE_CODE_ENHANCED_TELEMETRY_BETA") == "1"


# ---------------------------------------------------------------------------
# Galileo console URL derivation
# ---------------------------------------------------------------------------


def test_galileo_console_url_derives_api_endpoint() -> None:
    # console.<tenant> -> api.<tenant>
    assert cc_o11y.galileo_endpoint_from_console("https://console.galileo.ai") == "https://api.galileo.ai/otel/traces"
    assert cc_o11y.galileo_endpoint_from_console("https://console.galileo.example.com") == "https://api.galileo.example.com/otel/traces"
    assert cc_o11y.galileo_endpoint_from_console("https://console.demo-v2.galileocloud.io/") == "https://api.demo-v2.galileocloud.io/otel/traces"
    assert cc_o11y.galileo_endpoint_from_console("https://app.galileo.ai/") == "https://api.galileo.ai/otel/traces"
    assert cc_o11y.galileo_endpoint_from_console("https://console-galileo.apps.mycompany.com") == "https://api-galileo.apps.mycompany.com/otel/traces"
    # an api.<tenant> host is already correct and passes through
    assert cc_o11y.galileo_endpoint_from_console("https://api.demo-v2.galileocloud.io") == "https://api.demo-v2.galileocloud.io/otel/traces"


def test_galileo_console_url_rejects_ambiguous_host() -> None:
    # Hosts that are neither console.* nor api.* cannot be derived deterministically
    # (CC-06: the old logic produced unreachable hosts like api.app.galileo.ai).
    import pytest

    for bad in (
        "https://galileo.mycompany.com/",
        "https://console.galileo.example.com/a/path",
        "https://console.galileo.example.com/?token=not-allowed",
    ):
        with pytest.raises(cc_o11y.UsageError):
            cc_o11y.galileo_endpoint_from_console(bad)


def test_galileo_enabled_requires_explicit_instance_url(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(CLAUDE),
        "--render",
        "--destination",
        "local-collector",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(tmp_path / "missing-instance"),
        check=False,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "user's instance URL" in combined
    assert "do not assume the public tenant" in combined


def test_galileo_console_url_cli_overrides_endpoint(tmp_path: Path) -> None:
    out = tmp_path / "console-url"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--galileo-project",
        "proj",
        "--galileo-console-url",
        "https://console.galileo.myco.com",
        "--output-dir",
        str(out),
    )
    overlay = (out / "collector" / "claude-code-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert "https://api.galileo.myco.com/otel/traces" in overlay


def test_galileo_console_url_from_spec_derives_endpoint(tmp_path: Path) -> None:
    out = tmp_path / "spec-console-url"
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "api_version": "splunk-observability-claude-code-instrumentation-setup/v1",
                "claude_code": {
                    "galileo_console_url": "https://console.demo-v2.galileocloud.io/",
                    "galileo_enabled": True,
                    "galileo_project": "proj",
                },
            }
        ),
        encoding="utf-8",
    )
    run_claude("--render", "--spec", str(spec), "--output-dir", str(out))
    overlay = (out / "collector" / "claude-code-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert "https://api.demo-v2.galileocloud.io/otel/traces" in overlay


def test_galileo_spec_endpoint_override_is_preserved(tmp_path: Path) -> None:
    out = tmp_path / "spec-endpoint-url"
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "api_version": "splunk-observability-claude-code-instrumentation-setup/v1",
                "claude_code": {
                    "galileo_console_url": "https://console.demo-v2.galileocloud.io/",
                    "galileo_enabled": True,
                    "galileo_otel_endpoint": "https://api.explicit.example.com/otel/traces",
                    "galileo_project": "proj",
                },
            }
        ),
        encoding="utf-8",
    )
    run_claude("--render", "--spec", str(spec), "--output-dir", str(out))
    overlay = (out / "collector" / "claude-code-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert "https://api.explicit.example.com/otel/traces" in overlay


def test_galileo_cli_endpoint_override_is_preserved(tmp_path: Path) -> None:
    out = tmp_path / "cli-endpoint-url"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--galileo-project",
        "proj",
        "--galileo-console-url",
        "https://console.demo-v2.galileocloud.io/",
        "--galileo-otel-endpoint",
        "https://api.explicit.example.com/otel/traces",
        "--output-dir",
        str(out),
    )
    overlay = (out / "collector" / "claude-code-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert "https://api.explicit.example.com/otel/traces" in overlay


def test_galileo_requires_traces_beta(tmp_path: Path) -> None:
    result = run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--disable-traces-beta",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(tmp_path / "bad-galileo-no-traces"),
        check=False,
    )
    assert result.returncode != 0
    assert "Galileo integration requires Claude Code traces beta" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Validate passes on freshly rendered output
# ---------------------------------------------------------------------------


def test_validate_passes_on_local_collector_render(tmp_path: Path) -> None:
    out = tmp_path / "validate-local"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--realm",
        "us0",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(out),
    )
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out))
    assert result.returncode == 0
    assert "validate: OK" in result.stdout


def test_validate_passes_on_splunk_direct_render(tmp_path: Path) -> None:
    out = tmp_path / "validate-direct"
    run_claude(
        "--render",
        "--destination",
        "splunk-direct",
        "--realm",
        "us0",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out))
    assert result.returncode == 0
    assert "validate: OK" in result.stdout


def test_template_example_renders_and_validates(tmp_path: Path) -> None:
    out = tmp_path / "template"
    run_claude(
        "--render",
        "--spec",
        "skills/splunk-observability-claude-code-instrumentation-setup/template.example",
        "--output-dir",
        str(out),
    )
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out))
    assert result.returncode == 0
    assert "validate: OK" in result.stdout


# ---------------------------------------------------------------------------
# Apply dry-run uses merge-settings, not overwrite
# ---------------------------------------------------------------------------


def test_apply_dry_run_shows_merge_settings_operation(tmp_path: Path) -> None:
    out = tmp_path / "apply-dry"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(out),
    )
    result = run_claude(
        "--apply",
        "settings",
        "--dry-run",
        "--json",
        "--output-dir",
        str(out),
    )
    stdout = result.stdout.strip()
    assert stdout.startswith("{")
    payload = json.loads(stdout)
    assert payload["dry_run"] is True
    operations = payload.get("operations", [])
    section_ops = [op for op in operations if op.get("section") == "settings"]
    assert section_ops, "Expected at least one settings operation"
    commands = [op["command"] for op in section_ops]
    assert any(cmd[0] == "merge-settings" for cmd in commands), (
        f"Expected merge-settings command, got: {commands}"
    )
    # Must never have overwrite/install as the settings command
    overwrite_cmds = [cmd for cmd in commands if cmd[0] == "overwrite"]
    assert not overwrite_cmds, "settings section must not overwrite the target file"


def test_apply_dry_run_preserves_existing_settings_keys(tmp_path: Path) -> None:
    """merge_settings_file must not clobber unrelated settings.json keys."""
    out = tmp_path / "merge-test"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(out),
    )
    # Write a fake existing settings.json with unrelated content
    fake_target = tmp_path / "fake-settings.json"
    fake_target.write_text(
        json.dumps({
            "permissions": {"allow": ["Bash(*)", "Edit(*)"]},
            "model": "claude-opus-4-8",
            "env": {"MY_CUSTOM_VAR": "preserved"},
        }),
        encoding="utf-8",
    )
    # Perform an actual merge using the module function
    rendered_settings_files = list((out / "settings").glob("*.json"))
    assert rendered_settings_files
    cc_o11y.merge_settings_file(rendered_settings_files[0], fake_target)
    merged = json.loads(fake_target.read_text(encoding="utf-8"))
    # Our keys are merged in
    assert merged["env"]["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    # Unrelated keys are preserved
    assert merged["permissions"] == {"allow": ["Bash(*)", "Edit(*)"]}
    assert merged["model"] == "claude-opus-4-8"
    assert merged["env"]["MY_CUSTOM_VAR"] == "preserved"
    assert merged["_managedBy"] == cc_o11y.MANAGED_SETTINGS_MARKER


def test_merge_local_settings_removes_previous_managed_headers_helper(tmp_path: Path) -> None:
    out = tmp_path / "merge-helper"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    fake_target = tmp_path / "fake-settings.json"
    fake_target.write_text(
        json.dumps({
            "_managedBy": cc_o11y.MANAGED_SETTINGS_MARKER,
            "otelHeadersHelper": str(Path.home() / ".claude" / "bin" / "claude-code-otel-headers.sh"),
            "env": {"MY_CUSTOM_VAR": "preserved"},
        }),
        encoding="utf-8",
    )
    rendered_settings_files = list((out / "settings").glob("*.json"))
    assert rendered_settings_files
    cc_o11y.merge_settings_file(rendered_settings_files[0], fake_target)
    merged = json.loads(fake_target.read_text(encoding="utf-8"))
    assert "otelHeadersHelper" not in merged
    assert merged["env"]["MY_CUSTOM_VAR"] == "preserved"


def test_apply_settings_refuses_all_destination(tmp_path: Path) -> None:
    out = tmp_path / "all-apply"
    run_claude(
        "--render",
        "--destination",
        "all",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    result = run_claude(
        "--apply",
        "settings",
        "--dry-run",
        "--json",
        "--output-dir",
        str(out),
        check=False,
    )
    assert result.returncode != 0
    assert "one concrete destination" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# doctor and discover
# ---------------------------------------------------------------------------


def test_doctor_renders_report(tmp_path: Path) -> None:
    out = tmp_path / "doctor"
    result = run_claude(
        "--doctor",
        "--destination",
        "local-collector",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(out),
    )
    assert result.returncode == 0
    report = (out / "doctor-report.md").read_text(encoding="utf-8")
    # Assert the doctor body content, not merely that the file exists (TC-07).
    assert "Selected destination: `local-collector`" in report
    assert "Galileo enabled: `true`" in report
    assert "OK: render contract is valid." in report


def test_discover_returns_valid_payload() -> None:
    result = run_claude("--discover", "--json")
    payload = json.loads(result.stdout)
    assert "destinations" in payload
    assert "local-collector" in payload["destinations"]
    assert "splunk-direct" in payload["destinations"]


# ---------------------------------------------------------------------------
# Negative validate coverage (TC-02): mutate one artifact, expect failure
# ---------------------------------------------------------------------------


def _render_direct(out: Path) -> None:
    run_claude("--render", "--destination", "splunk-direct", "--realm", "us1",
               "--disable-galileo", "--output-dir", str(out))


def test_validate_fails_when_headers_helper_removed(tmp_path: Path) -> None:
    out = tmp_path / "v"
    _render_direct(out)
    settings = next((out / "settings").glob("*.json"))
    doc = json.loads(settings.read_text(encoding="utf-8"))
    doc.pop("otelHeadersHelper")
    settings.write_text(json.dumps(doc), encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "otelHeadersHelper" in result.stderr


def test_validate_fails_when_rendered_headers_helper_removed(tmp_path: Path) -> None:
    out = tmp_path / "v"
    _render_direct(out)
    (out / "bin" / "claude-code-otel-headers.sh").unlink()
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "rendered headers helper" in result.stderr


def test_validate_fails_when_rendered_headers_helper_not_executable(tmp_path: Path) -> None:
    out = tmp_path / "v"
    _render_direct(out)
    helper = out / "bin" / "claude-code-otel-headers.sh"
    helper.chmod(0o644)
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "must be executable" in result.stderr


def test_validate_fails_when_direct_embeds_headers(tmp_path: Path) -> None:
    out = tmp_path / "v"
    _render_direct(out)
    settings = next((out / "settings").glob("*.json"))
    doc = json.loads(settings.read_text(encoding="utf-8"))
    doc["env"]["OTEL_EXPORTER_OTLP_HEADERS"] = "X-SF-TOKEN=leaked"
    settings.write_text(json.dumps(doc), encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "must not embed OTEL_EXPORTER_OTLP_HEADERS" in result.stderr


def test_validate_fails_when_telemetry_disabled(tmp_path: Path) -> None:
    out = tmp_path / "v"
    _render_direct(out)
    settings = next((out / "settings").glob("*.json"))
    doc = json.loads(settings.read_text(encoding="utf-8"))
    doc["env"]["CLAUDE_CODE_ENABLE_TELEMETRY"] = "0"
    settings.write_text(json.dumps(doc), encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "CLAUDE_CODE_ENABLE_TELEMETRY must be '1'" in result.stderr


def test_validate_fails_when_histograms_removed(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    overlay.write_text(overlay.read_text(encoding="utf-8").replace("send_otlp_histograms: true", "send_otlp_histograms: false"), encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "send_otlp_histograms: true" in result.stderr


def test_validate_fails_when_galileo_pipeline_dropped(tmp_path: Path) -> None:
    """CC-09 structural check: Galileo exporter defined but not wired into traces."""
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    # Remove galileo from the Galileo traces pipeline exporters list but leave it defined.
    text = text.replace("exporters: [otlp_http/galileo]", "exporters: []")
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "otlp_http/galileo" in result.stderr


def test_validate_fails_when_galileo_filter_removed(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = text.replace(
        "processors: [resource/claude_code, transform/claude_code_genai, transform/claude_code_galileo, filter/claude_code_galileo_genai, batch/claude_code]",
        "processors: [resource/claude_code, transform/claude_code_genai, transform/claude_code_galileo, batch/claude_code]",
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "filter/claude_code_galileo_genai" in result.stderr


def test_validate_fails_when_galileo_content_transform_removed(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = text.replace(
        "processors: [resource/claude_code, transform/claude_code_genai, transform/claude_code_galileo, filter/claude_code_galileo_genai, batch/claude_code]",
        "processors: [resource/claude_code, transform/claude_code_genai, filter/claude_code_galileo_genai, batch/claude_code]",
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "transform/claude_code_galileo" in result.stderr


def test_validate_fails_when_galileo_dynamic_tool_mapping_removed(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = "\n".join(
        line
        for line in text.splitlines()
        if 'merge_maps(span.attributes, span.cache["claude_tools"]' not in line
    ) + "\n"
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "merge_maps" in result.stderr


def test_validate_fails_on_resource_only_shared_trace_route(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = text.replace(
        "\nexporters:\n",
        """
connectors:
  routing:
    default_pipelines: [traces/default]
    error_mode: ignore
    table:
      - context: resource
        condition: 'attributes["data.source"] == "claude-code"'
        pipelines: [traces/claude_code]

exporters:
""",
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "context: span route" in result.stderr


def test_validate_fails_on_resource_only_shared_metric_route(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = text.replace(
        "\nexporters:\n",
        """
connectors:
  routing/metrics:
    default_pipelines: [metrics/default]
    error_mode: ignore
    table:
      - context: resource
        condition: 'attributes["service.name"] == "claude-code"'
        pipelines: [metrics/claude_code]

exporters:
""",
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "context: metric or context: datapoint" in result.stderr


def test_validate_fails_when_genai_transform_removed_from_trace_pipeline(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = text.replace(
        "processors: [resource/claude_code, transform/claude_code_genai, batch/claude_code]",
        "processors: [resource/claude_code, batch/claude_code]",
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "must run transform/claude_code_genai" in result.stderr


def test_validate_fails_when_native_token_genai_metric_pipeline_dropped(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = text.replace(
        """    metrics/claude_code_token_genai:
      receivers: [otlp/claude_code]
      processors: [resource/claude_code, filter/claude_code_token_metrics, transform/claude_code_token_metric_genai, cumulativetodelta/claude_code_tokens, batch/claude_code]
      exporters: [signal_to_metrics/claude_code_token_histogram]
""",
        "",
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "metrics/claude_code_token_genai" in result.stderr


def test_validate_fails_when_native_token_histogram_connector_is_unreachable(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = text.replace(
        """    metrics/claude_code_token_genai:
      receivers: [otlp/claude_code]
      processors: [resource/claude_code, filter/claude_code_token_metrics, transform/claude_code_token_metric_genai, cumulativetodelta/claude_code_tokens, batch/claude_code]
      exporters: [signal_to_metrics/claude_code_token_histogram]
""",
        """    metrics/claude_code_token_genai:
      receivers: [otlp/claude_code]
      processors: [resource/claude_code, filter/claude_code_token_metrics, transform/claude_code_token_metric_genai, cumulativetodelta/claude_code_tokens, batch/claude_code]
      exporters: [signalfx/claude_code]
""",
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "metrics/claude_code_token_genai pipeline must export to signal_to_metrics/claude_code_token_histogram" in result.stderr


def test_validate_fails_when_token_histogram_output_pipeline_dropped(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = text.replace(
        """    metrics/claude_code_token_histogram:
      receivers: [signal_to_metrics/claude_code_token_histogram]
      processors: [batch/claude_code]
      exporters: [otlp_http/claude_code_metrics]
""",
        "",
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "no metrics/claude_code_token_histogram pipeline" in result.stderr


def test_validate_fails_when_token_delta_processor_is_not_reachable(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8").replace(
        "transform/claude_code_token_metric_genai, cumulativetodelta/claude_code_tokens, batch/claude_code",
        "transform/claude_code_token_metric_genai, batch/claude_code",
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "must run cumulativetodelta/claude_code_tokens" in result.stderr


def test_validate_fails_when_token_counter_is_exported_directly(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8").replace(
        "exporters: [signal_to_metrics/claude_code_token_histogram]",
        "exporters: [signal_to_metrics/claude_code_token_histogram, otlp_http/claude_code_metrics]",
        1,
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "must not export the counter directly" in result.stderr


def test_validate_fails_when_token_histogram_shape_is_wrong(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = text.replace('        unit: "{token}"\n', '        unit: "1"\n', 1)
    text = text.replace(
        ", 4194304, 16777216, 67108864]",
        "]",
        1,
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "token histogram" in result.stderr or "unit {token}" in result.stderr


def test_validate_rejects_sum_connector_for_genai_token_usage(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8").replace(
        "connectors:\n",
        """connectors:
  sum/claude_code_input_tokens:
    spans:
      gen_ai.client.token.usage:
        source_attribute: gen_ai.usage.input_tokens
""",
        1,
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "must not be exported by a sum connector" in result.stderr


def test_validate_fails_when_genai_duration_histogram_pipeline_dropped(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = text.replace(
        """    metrics/claude_code_genai_duration:
      receivers: [span_metrics/claude_code_genai]
      processors: [batch/claude_code]
      exporters: [otlp_http/claude_code_metrics]
""",
        "",
    )
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "metrics/claude_code_genai_duration" in result.stderr


def test_validate_fails_when_genai_duration_histogram_uses_milliseconds(tmp_path: Path) -> None:
    out = tmp_path / "v"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    text = overlay.read_text(encoding="utf-8")
    text = text.replace("      unit: s\n", "      unit: ms\n", 1)
    overlay.write_text(text, encoding="utf-8")
    result = run_cmd("bash", str(CLAUDE_VALIDATE), "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "histogram must use unit s" in result.stderr


# ---------------------------------------------------------------------------
# Realm and endpoint negative coverage (TC-05)
# ---------------------------------------------------------------------------


def test_invalid_realm_rejected(tmp_path: Path) -> None:
    result = run_claude("--render", "--destination", "splunk-direct",
                        "--realm", "us0/../evil", "--json",
                        "--output-dir", str(tmp_path / "o"), check=False)
    assert result.returncode != 0
    assert "realm must be lowercase alphanumeric" in result.stdout + result.stderr


def test_long_galileo_identifiers_allowed_but_credentials_rejected(tmp_path: Path) -> None:
    out = tmp_path / "long-id"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--realm",
        "us1",
        "--galileo-project",
        "01234567-89ab-cdef-0123-456789abcdef",
        "--galileo-log-stream",
        "project-0123456789abcdefghijklmnop",
        "--output-dir",
        str(out),
    )
    assert json.loads((out / "metadata.json").read_text(encoding="utf-8"))["ok"] is True

    result = run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--realm",
        "us1",
        "--galileo-project",
        "sk-test-0123456789abcdef",
        "--output-dir",
        str(tmp_path / "secret-like"),
        check=False,
    )
    assert result.returncode != 0
    assert "galileo_project looks like credential material" in result.stdout + result.stderr


@pytest.mark.parametrize(
    "endpoint,needle",
    [
        ("http://api.galileo.ai/otel/traces", "must use https://"),
        ("https://api.galileo.ai/wrong/path", "must end with /otel/traces"),
        ("https://user:pass@api.galileo.ai/otel/traces", "must not include credentials"),
        ("https://api.galileo.ai/otel/traces?api_key=secret", "must not include a query string"),
    ],
)
def test_malformed_galileo_endpoint_rejected(tmp_path: Path, endpoint, needle) -> None:
    result = run_claude("--render", "--destination", "local-collector", "--realm", "us1",
                        "--galileo-project", "proj", "--galileo-otel-endpoint", endpoint,
                        "--json", "--output-dir", str(tmp_path / "o"), check=False)
    assert result.returncode != 0
    assert needle in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Atomic render (TC-04): a failed re-render must not wipe prior good output
# ---------------------------------------------------------------------------


def test_failed_rerender_preserves_prior_output(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run_claude("--render", "--destination", "local-collector", "--realm", "us1",
               "--galileo-project", "proj", "--output-dir", str(out))
    settings = out / "settings" / "claude-settings.user.local-collector.json"
    overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    assert settings.is_file() and overlay.is_file()
    # Re-render into the SAME dir with an invalid config (bad realm) — a deterministic
    # validation error that occurs after mkdir but must not wipe prior good output.
    result = run_claude("--render", "--destination", "splunk-direct", "--realm", "BAD/REALM",
                        "--output-dir", str(out), check=False)
    assert result.returncode != 0
    # Prior good artifacts survive the failed re-render.
    assert settings.is_file(), "prior settings were wiped by a failed re-render"
    assert overlay.is_file(), "prior overlay was wiped by a failed re-render"


# ---------------------------------------------------------------------------
# External-collector coverage (TC-01)
# ---------------------------------------------------------------------------


def test_external_collector_per_signal_endpoints(tmp_path: Path) -> None:
    out = tmp_path / "ext"
    run_claude("--render", "--destination", "external-collector",
               "--external-trace-endpoint", "https://gw.example.com:4318/v1/traces",
               "--external-metric-endpoint", "https://gw.example.com:4318/v1/metrics",
               "--external-log-endpoint", "https://gw.example.com:4318/v1/logs",
               "--external-collector-protocol", "http/json",
               "--disable-galileo", "--output-dir", str(out))
    env = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))["env"]
    assert env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] == "https://gw.example.com:4318/v1/traces"
    assert env["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"] == "https://gw.example.com:4318/v1/metrics"
    assert env["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/json"
    assert not (out / "collector").exists()


def test_external_collector_header_emission(tmp_path: Path) -> None:
    out = tmp_path / "ext-hdr"
    run_claude("--render", "--destination", "external-collector",
               "--external-collector-endpoint", "https://gw.example.com:4318",
               "--external-header", "X-Scope-OrgID=tenant-a",
               "--disable-galileo", "--output-dir", str(out))
    env = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))["env"]
    assert env["OTEL_EXPORTER_OTLP_HEADERS"] == "X-Scope-OrgID=tenant-a"


def test_external_collector_tls_env_emission(tmp_path: Path) -> None:
    out = tmp_path / "ext-tls"
    run_claude(
        "--render",
        "--destination",
        "external-collector",
        "--external-collector-endpoint",
        "https://gw.example.com:4318",
        "--external-ca-certificate",
        "/etc/otel/ca.pem",
        "--external-client-certificate",
        "/etc/otel/client.pem",
        "--external-client-private-key",
        "/etc/otel/client.key",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    env = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))["env"]
    assert env["NODE_EXTRA_CA_CERTS"] == "/etc/otel/ca.pem"
    assert env["CLAUDE_CODE_CLIENT_CERT"] == "/etc/otel/client.pem"
    assert env["CLAUDE_CODE_CLIENT_KEY"] == "/etc/otel/client.key"
    assert "OTEL_EXPORTER_OTLP_CERTIFICATE" not in env


def test_external_collector_grpc_uses_standard_otel_tls_env(tmp_path: Path) -> None:
    out = tmp_path / "ext-grpc-tls"
    run_claude(
        "--render",
        "--destination",
        "external-collector",
        "--external-collector-endpoint",
        "https://gw.example.com:4317",
        "--external-collector-protocol",
        "grpc",
        "--external-ca-certificate",
        "/etc/otel/ca.pem",
        "--external-client-certificate",
        "/etc/otel/client.pem",
        "--external-client-private-key",
        "/etc/otel/client.key",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    env = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))["env"]
    assert env["OTEL_EXPORTER_OTLP_CERTIFICATE"] == "/etc/otel/ca.pem"
    assert env["OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE"] == "/etc/otel/client.pem"
    assert env["OTEL_EXPORTER_OTLP_CLIENT_KEY"] == "/etc/otel/client.key"


def test_external_collector_galileo_coverage_is_operator_owned(tmp_path: Path) -> None:
    out = tmp_path / "ext-galileo"
    run_claude(
        "--render",
        "--destination",
        "external-collector",
        "--external-collector-endpoint",
        "https://gw.example.com:4318",
        "--galileo-project",
        "proj",
        "--output-dir",
        str(out),
    )
    coverage = json.loads((out / "coverage-report.json").read_text(encoding="utf-8"))["coverage"]
    statuses = {item["key"]: item["status"] for item in coverage}
    assert statuses["galileo.traces"] == "operator_owned"
    assert statuses["galileo.genai_attributes"] == "operator_owned"
    assert statuses["galileo.non_public_tenant"] == "operator_owned"


def test_external_collector_missing_endpoints_rejected(tmp_path: Path) -> None:
    result = run_claude("--render", "--destination", "external-collector",
                        "--disable-galileo", "--json",
                        "--output-dir", str(tmp_path / "o"), check=False)
    assert result.returncode != 0
    assert "external collector mode requires" in result.stdout + result.stderr


def test_external_collector_rejects_secret_header(tmp_path: Path) -> None:
    result = run_claude("--render", "--destination", "external-collector",
                        "--external-collector-endpoint", "https://gw.example.com:4318",
                        "--external-header", "Authorization=Bearer sk-abcdefghijklmnopqrstuvwxyz0123456789",
                        "--disable-galileo", "--json",
                        "--output-dir", str(tmp_path / "o"), check=False)
    assert result.returncode != 0
    assert "credentials" in (result.stdout + result.stderr).lower() or "secret" in (result.stdout + result.stderr).lower()


# ---------------------------------------------------------------------------
# Content-capture tool flags (TC-08)
# ---------------------------------------------------------------------------


def _spec(tmp_path: Path, **cc) -> Path:
    base = {
        "api_version": "splunk-observability-claude-code-instrumentation-setup/v1",
        "claude_code": {"realm": "us1", "destination": "local-collector",
                        "galileo_project": "proj",
                        "galileo_console_url": PUBLIC_GALILEO_CONSOLE,
                        **cc},
    }
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    return p


def test_tool_content_requires_accept_flag(tmp_path: Path) -> None:
    spec = _spec(tmp_path, log_tool_content=True)
    result = run_claude("--render", "--spec", str(spec), "--json",
                        "--output-dir", str(tmp_path / "o"), check=False)
    assert result.returncode != 0
    assert "accept-content-capture" in (result.stdout + result.stderr)


def test_tool_flags_render_with_accept(tmp_path: Path) -> None:
    spec = _spec(tmp_path, log_tool_details=True, log_tool_content=True, enable_traces_beta=True)
    run_claude("--render", "--spec", str(spec), "--accept-content-capture",
               "--output-dir", str(tmp_path / "o"))
    env = json.loads(next((tmp_path / "o" / "settings").glob("*.json")).read_text(encoding="utf-8"))["env"]
    assert env["OTEL_LOG_TOOL_DETAILS"] == "1"
    assert env["OTEL_LOG_TOOL_CONTENT"] == "1"


def test_tool_content_without_traces_warns(tmp_path: Path) -> None:
    spec = _spec(tmp_path, log_tool_content=True, enable_traces_beta=False)
    run_claude("--render", "--spec", str(spec), "--accept-content-capture",
               "--output-dir", str(tmp_path / "o"))
    meta = json.loads((tmp_path / "o" / "metadata.json").read_text(encoding="utf-8"))
    assert any("tool content is only attached to spans" in w for w in meta.get("warnings", []))


def test_prompt_only_capture_explicitly_keeps_assistant_responses_redacted(tmp_path: Path) -> None:
    spec = _spec(tmp_path, log_user_prompts=True, log_assistant_responses=False)
    out = tmp_path / "prompt-only"
    run_claude(
        "--render",
        "--spec",
        str(spec),
        "--accept-content-capture",
        "--output-dir",
        str(out),
    )
    env = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))["env"]
    assert env["OTEL_LOG_USER_PROMPTS"] == "1"
    assert env["OTEL_LOG_ASSISTANT_RESPONSES"] == "0"


# ---------------------------------------------------------------------------
# Apply output-dir isolation (TC-11): real merge runs against a scoped target
# ---------------------------------------------------------------------------


def test_apply_settings_managed_scope_merges_into_output_dir(tmp_path: Path) -> None:
    out = tmp_path / "out"
    # Render first so apply-plan.json exists (apply then skips the implicit re-render
    # that would otherwise clear the settings/ dir).
    run_claude("--render", "--destination", "local-collector", "--settings-scope", "managed",
               "--realm", "us1", "--galileo-project", "proj", "--output-dir", str(out))
    # Seed the managed target (inside the render tree) with unmanaged keys.
    managed = out / "settings" / "managed-settings.json"
    managed.write_text(json.dumps({"model": "sonnet", "env": {"MY_CUSTOM_VAR": "preserved"}}), encoding="utf-8")
    result = run_claude("--apply", "settings", "--settings-scope", "managed",
                        "--destination", "local-collector", "--realm", "us1",
                        "--galileo-project", "proj", "--json", "--output-dir", str(out))
    payload = json.loads(result.stdout[result.stdout.find("{"):])
    assert payload["dry_run"] is False
    merged = json.loads(managed.read_text(encoding="utf-8"))
    # Managed key merged in AND unmanaged keys preserved.
    assert merged["env"]["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert merged["env"]["MY_CUSTOM_VAR"] == "preserved"
    assert merged["model"] == "sonnet"
    # The merge target stayed under the temp output dir (never touched real ~/.claude).
    assert str(managed).startswith(str(tmp_path))


def test_apply_env_helper_managed_splunk_direct_skips_same_file_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    out = tmp_path / "out"
    run_claude(
        "--render",
        "--destination",
        "splunk-direct",
        "--settings-scope",
        "managed",
        "--realm",
        "us1",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    result = run_claude(
        "--apply",
        "env-helper",
        "--settings-scope",
        "managed",
        "--destination",
        "splunk-direct",
        "--realm",
        "us1",
        "--disable-galileo",
        "--json",
        "--output-dir",
        str(out),
    )
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is False
    helper = out / "bin" / "claude-code-otel-headers.sh"
    assert helper.is_file()
    assert helper.stat().st_mode & stat.S_IXUSR


# ---------------------------------------------------------------------------
# Deep-review regressions: portability, auth, and live shared collectors
# ---------------------------------------------------------------------------


def test_docker_receiver_bind_is_independent_from_claude_client_endpoint(tmp_path: Path) -> None:
    out = tmp_path / "docker-bind"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--local-collector-endpoint",
        "http://127.0.0.1:14318",
        "--collector-receiver-endpoint",
        "0.0.0.0:4318",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    settings = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))
    assert settings["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://127.0.0.1:14318"
    overlay = (out / "collector" / "claude-code-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert 'endpoint: "0.0.0.0:4318"' in overlay


def test_model_aliases_are_explicit_and_apply_to_spans_and_metrics(tmp_path: Path) -> None:
    out = tmp_path / "model-alias"
    source = "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/profile-123"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--model-alias",
        f"{source}=claude-sonnet-4-6",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    overlay = (out / "collector" / "claude-code-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert overlay.count(source) == 2
    assert overlay.count('set(span.attributes["gen_ai.request.model"], "claude-sonnet-4-6")') == 1
    assert overlay.count('set(datapoint.attributes["gen_ai.request.model"], "claude-sonnet-4-6")') == 1


def test_external_http_secret_header_uses_dynamic_helper(tmp_path: Path) -> None:
    out = tmp_path / "external-helper"
    run_claude(
        "--render",
        "--destination",
        "external-collector",
        "--external-collector-endpoint",
        "https://gw.example.com:4318",
        "--external-header",
        "Authorization=${GATEWAY_AUTH}",
        "--external-header",
        "X-Scope-OrgID=tenant-a",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    settings = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))
    assert "otelHeadersHelper" in settings
    assert "OTEL_EXPORTER_OTLP_HEADERS" not in settings["env"]
    helper = out / "bin" / "claude-code-otel-headers.sh"
    helper_text = helper.read_text(encoding="utf-8")
    assert "GATEWAY_AUTH" in helper_text
    assert "runtime-secret-value" not in helper_text
    env = dict(os.environ)
    env["GATEWAY_AUTH"] = "runtime-secret-value"
    result = subprocess.run(
        [str(helper)], capture_output=True, text=True, check=True, env=env
    )
    assert json.loads(result.stdout) == {
        "Authorization": "runtime-secret-value",
        "X-Scope-OrgID": "tenant-a",
    }


def test_external_grpc_rejects_unexpanded_secret_header_placeholder(tmp_path: Path) -> None:
    result = run_claude(
        "--render",
        "--destination",
        "external-collector",
        "--external-collector-endpoint",
        "https://gw.example.com:4317",
        "--external-collector-protocol",
        "grpc",
        "--external-header",
        "Authorization=${GATEWAY_AUTH}",
        "--disable-galileo",
        "--output-dir",
        str(tmp_path / "grpc-header"),
        check=False,
    )
    assert result.returncode != 0
    assert "otelHeadersHelper does not apply to gRPC" in result.stdout + result.stderr


def test_resource_attributes_are_encoded_and_keys_are_validated(tmp_path: Path) -> None:
    out = tmp_path / "resource-attrs"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--resource-attribute",
        "org.name=My Company",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    settings = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))
    assert "org.name=My%20Company" in settings["env"]["OTEL_RESOURCE_ATTRIBUTES"]

    bad = run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--resource-attribute",
        "bad,key=value",
        "--disable-galileo",
        "--output-dir",
        str(tmp_path / "bad-resource-key"),
        check=False,
    )
    assert bad.returncode != 0
    assert "resource attribute key" in bad.stdout + bad.stderr


def test_raw_api_body_capture_is_gated_and_rendered(tmp_path: Path) -> None:
    rejected = run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--log-raw-api-bodies",
        "--disable-galileo",
        "--output-dir",
        str(tmp_path / "raw-rejected"),
        check=False,
    )
    assert rejected.returncode != 0
    assert "accept-content-capture" in rejected.stdout + rejected.stderr

    out = tmp_path / "raw-accepted"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--log-raw-api-bodies",
        "file:/tmp/claude-raw-api-bodies",
        "--accept-content-capture",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    settings = json.loads(next((out / "settings").glob("*.json")).read_text(encoding="utf-8"))
    assert settings["env"]["OTEL_LOG_RAW_API_BODIES"] == "file:/tmp/claude-raw-api-bodies"


def test_settings_merge_creates_backup_and_preserves_operator_helper(tmp_path: Path) -> None:
    out = tmp_path / "merge-review"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps(
            {
                "_managedBy": cc_o11y.MANAGED_SETTINGS_MARKER,
                "otelHeadersHelper": "/opt/company/custom-otel-headers",
                "env": {"KEEP": "yes"},
            }
        ),
        encoding="utf-8",
    )
    source = next((out / "settings").glob("*.json"))
    cc_o11y.merge_settings_file(source, target)
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert merged["otelHeadersHelper"] == "/opt/company/custom-otel-headers"
    backups = list(tmp_path.glob("settings.json.bak.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["env"]["KEEP"] == "yes"


def test_validate_checks_shared_routing_reference_reachability(tmp_path: Path) -> None:
    out = tmp_path / "shared-reference"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    routing = out / "runtime" / "shared-collector-routing.md"
    routing.write_text(
        routing.read_text(encoding="utf-8").replace(
            "processors: [resource/claude_code, transform/claude_code_genai, batch]",
            "processors: [resource/claude_code, batch]",
        ),
        encoding="utf-8",
    )
    result = run_cmd(
        "bash",
        str(CLAUDE_VALIDATE),
        "--output-dir",
        str(out),
        check=False,
    )
    assert result.returncode != 0
    assert "make transform/claude_code_genai reachable" in result.stderr


def test_validate_accepts_and_checks_deployed_collector_config(tmp_path: Path) -> None:
    out = tmp_path / "deployed-config"
    run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--disable-galileo",
        "--output-dir",
        str(out),
    )
    rendered_overlay = out / "collector" / "claude-code-o11y-local-collector.yaml"
    result = run_cmd(
        "bash",
        str(CLAUDE_VALIDATE),
        "--output-dir",
        str(out),
        "--collector-config",
        str(rendered_overlay),
    )
    assert result.returncode == 0

    broken = tmp_path / "broken-collector.yaml"
    broken.write_text(
        rendered_overlay.read_text(encoding="utf-8").replace(
            "resource/claude_code, transform/claude_code_genai, batch/claude_code",
            "resource/claude_code, batch/claude_code",
            1,
        ),
        encoding="utf-8",
    )
    failed = run_cmd(
        "bash",
        str(CLAUDE_VALIDATE),
        "--output-dir",
        str(out),
        "--collector-config",
        str(broken),
        check=False,
    )
    assert failed.returncode != 0
    assert "collector config" in failed.stderr
    assert "must run transform/claude_code_genai" in failed.stderr


def test_unknown_spec_field_and_invalid_intervals_fail_closed(tmp_path: Path) -> None:
    spec = tmp_path / "bad-spec.json"
    spec.write_text(
        json.dumps(
            {
                "api_version": cc_o11y.API_VERSION,
                "claude_code": {"metric_export_interval_milliseconds": 1000},
            }
        ),
        encoding="utf-8",
    )
    unknown = run_claude(
        "--render", "--spec", str(spec), "--output-dir", str(tmp_path / "unknown"), check=False
    )
    assert unknown.returncode != 0
    assert "unknown claude_code spec field" in unknown.stdout + unknown.stderr

    invalid = run_claude(
        "--render",
        "--destination",
        "local-collector",
        "--metric-export-interval-ms",
        "0",
        "--disable-galileo",
        "--output-dir",
        str(tmp_path / "interval"),
        check=False,
    )
    assert invalid.returncode != 0
    assert "metric_export_interval_ms must be a positive integer" in invalid.stdout + invalid.stderr
