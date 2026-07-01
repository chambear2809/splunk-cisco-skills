#!/usr/bin/env python3
"""Regression coverage for coding-agent and Codex O11y instrumentation skills."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

from tests.regression_helpers import REPO_ROOT

from skills.shared.coding_agent_o11y import codex as codex_o11y


PARENT = REPO_ROOT / "skills/splunk-observability-coding-agent-instrumentation-setup/scripts/setup.sh"
CODEX = REPO_ROOT / "skills/splunk-observability-codex-instrumentation-setup/scripts/setup.sh"
NOTIFY_SPAN = (
    REPO_ROOT
    / "skills/splunk-observability-codex-instrumentation-setup/runtime/codex-splunk-o11y-notify-span.py"
)


def load_notify_span_module():
    spec = importlib.util.spec_from_file_location("codex_notify_span_regression", NOTIFY_SPAN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def run_codex(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_cmd("bash", str(CODEX), *args, check=check)


def rendered_text(root: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(root.rglob("*")) if path.is_file())


def test_parent_execute_dry_run_json_returns_exact_child_command() -> None:
    result = run_cmd(
        "bash",
        str(PARENT),
        "--execute",
        "--dry-run",
        "--json",
        "--agent",
        "codex",
        "--destination",
        "direct",
    )
    payload = json.loads(result.stdout)
    assert payload["router_only"] is True
    assert payload["would_execute"] == [
        "bash",
        "skills/splunk-observability-codex-instrumentation-setup/scripts/setup.sh",
        "--render",
        "--destination",
        "direct",
    ]
    assert "direct Splunk ingest" in payload["warnings"][0]


def test_parent_execute_codex_splunk_direct_maps_to_direct() -> None:
    result = run_cmd(
        "bash",
        str(PARENT),
        "--execute",
        "--dry-run",
        "--json",
        "--agent",
        "codex",
        "--destination",
        "splunk-direct",
    )
    payload = json.loads(result.stdout)
    assert payload["destination"] == "splunk-direct"
    assert payload["would_execute"] == [
        "bash",
        "skills/splunk-observability-codex-instrumentation-setup/scripts/setup.sh",
        "--render",
        "--destination",
        "direct",
    ]


def test_codex_local_and_external_profiles_render_valid_toml(tmp_path: Path) -> None:
    local_out = tmp_path / "local"
    run_codex(
        "--render",
        "--destination",
        "local-collector",
        "--realm",
        "us1",
        "--output-dir",
        str(local_out),
    )
    external_out = tmp_path / "external"
    run_codex(
        "--render",
        "--destination",
        "external-collector",
        "--realm",
        "us1",
        "--external-trace-endpoint",
        "https://otel-gateway.example.com/v1/traces",
        "--external-metric-endpoint",
        "https://otel-gateway.example.com/v1/metrics",
        "--external-header",
        "x-otlp-routing=codex",
        "--output-dir",
        str(external_out),
    )

    local_profile = local_out / "profiles/codex-o11y-local.config.toml"
    external_profile = external_out / "profiles/codex-o11y-external.config.toml"
    for profile in (local_profile, external_profile):
        assert profile.is_file()
        with profile.open("rb") as handle:
            parsed = tomllib.load(handle)
        assert "otel" in parsed

    assert "http://127.0.0.1:14318" in local_profile.read_text(encoding="utf-8")
    assert "http://127.0.0.1:14318/v1/traces" in local_profile.read_text(encoding="utf-8")
    assert "http://127.0.0.1:14318/v1/metrics" in local_profile.read_text(encoding="utf-8")
    assert "https://otel-gateway.example.com/v1/traces" in external_profile.read_text(encoding="utf-8")
    assert "CODEX_PROFILE=codex-o11y-local" in (local_out / "bin/codex-o11y-exec").read_text(encoding="utf-8")
    assert "CODEX_PROFILE=codex-o11y-external" in (external_out / "bin/codex-o11y-exec").read_text(
        encoding="utf-8"
    )


def test_codex_local_collector_endpoint_is_configurable(tmp_path: Path) -> None:
    out = tmp_path / "custom-localhost"
    run_codex(
        "--render",
        "--destination",
        "local-collector",
        "--local-collector-endpoint",
        "http://localhost:24318",
        "--enable-native-logs",
        "--output-dir",
        str(out),
    )

    profile = (out / "profiles/codex-o11y-local.config.toml").read_text(encoding="utf-8")
    assert "http://localhost:24318/v1/traces" in profile
    assert "http://localhost:24318/v1/metrics" in profile
    assert "http://localhost:24318/v1/logs" in profile

    overlay = (out / "collector/codex-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert 'endpoint: "0.0.0.0:4318"' in overlay

    run_codex("--validate", "--output-dir", str(out))


def test_codex_local_collector_receiver_bind_is_independent_and_configurable(tmp_path: Path) -> None:
    out = tmp_path / "receiver-bind"
    run_codex(
        "--render",
        "--destination",
        "local-collector",
        "--local-collector-endpoint",
        "http://127.0.0.1:14318",
        "--local-collector-receiver-endpoint",
        "127.0.0.1:24318",
        "--output-dir",
        str(out),
    )

    profile = (out / "profiles/codex-o11y-local.config.toml").read_text(encoding="utf-8")
    overlay = (out / "collector/codex-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert "http://127.0.0.1:14318/v1/traces" in profile
    assert 'endpoint: "127.0.0.1:24318"' in overlay


def test_codex_local_collector_receiver_bind_rejects_url(tmp_path: Path) -> None:
    result = run_codex(
        "--render",
        "--local-collector-receiver-endpoint",
        "http://0.0.0.0:4318",
        "--output-dir",
        str(tmp_path / "bad-receiver-bind"),
        check=False,
    )
    assert result.returncode != 0
    assert "bind address" in result.stdout + result.stderr


def test_codex_local_collector_endpoint_rejects_full_signal_path(tmp_path: Path) -> None:
    result = run_codex(
        "--render",
        "--local-collector-endpoint",
        "http://localhost:14318/v1/traces",
        "--output-dir",
        str(tmp_path / "bad-local-endpoint"),
        check=False,
    )
    assert result.returncode != 0
    assert "base URL" in result.stdout + result.stderr


def test_codex_local_collector_endpoint_rejects_https_without_tls_receiver(tmp_path: Path) -> None:
    result = run_codex(
        "--render",
        "--local-collector-endpoint",
        "https://localhost:14318",
        "--output-dir",
        str(tmp_path / "bad-local-https-endpoint"),
        check=False,
    )
    assert result.returncode != 0
    assert "plain OTLP HTTP" in result.stdout + result.stderr


def test_codex_external_collector_http_and_grpc_profiles(tmp_path: Path) -> None:
    http_out = tmp_path / "http"
    run_codex(
        "--render",
        "--destination",
        "external-collector",
        "--external-collector-protocol",
        "otlp-http",
        "--external-trace-endpoint",
        "https://otel.example.com/v1/traces",
        "--external-metric-endpoint",
        "https://otel.example.com/v1/metrics",
        "--output-dir",
        str(http_out),
    )
    http_text = (http_out / "profiles/codex-o11y-external.config.toml").read_text(encoding="utf-8")
    assert '"otlp-http"' in http_text
    assert '"protocol" = "binary"' in http_text

    grpc_out = tmp_path / "grpc"
    run_codex(
        "--render",
        "--destination",
        "external-collector",
        "--external-collector-protocol",
        "otlp-grpc",
        "--external-trace-endpoint",
        "https://otel.example.com:4317",
        "--external-metric-endpoint",
        "https://otel.example.com:4317",
        "--enable-native-logs",
        "--external-log-endpoint",
        "https://otel.example.com:4317",
        "--output-dir",
        str(grpc_out),
    )
    grpc_text = (grpc_out / "profiles/codex-o11y-external.config.toml").read_text(encoding="utf-8")
    assert '"otlp-grpc"' in grpc_text
    assert 'exporter = { "otlp-grpc"' in grpc_text


def test_codex_runtime_env_and_collector_overlay_quote_values(tmp_path: Path) -> None:
    out = tmp_path / "rendered with spaces"
    service_name = "codex cli: prod #1"
    environment = "prod blue"
    run_codex(
        "--render",
        "--service-name",
        service_name,
        "--environment",
        environment,
        "--output-dir",
        str(out),
    )

    env_file = out / "runtime/codex-o11y.env"
    sourced = subprocess.run(
        [
            "bash",
            "-c",
            f"source {shlex.quote(str(env_file))}; "
            'printf "%s\\n%s\\n%s\\n" "$CODEX_O11Y_RENDERED_DIR" "$CODEX_O11Y_SERVICE_NAME" "$CODEX_O11Y_ENVIRONMENT"',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert sourced.returncode == 0, sourced.stdout + sourced.stderr
    rendered_dir, actual_service, actual_environment = sourced.stdout.splitlines()
    assert rendered_dir == str(out)
    assert actual_service == service_name
    assert actual_environment == environment

    overlay = (out / "collector/codex-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert 'value: "codex cli: prod #1"' in overlay
    assert 'value: "prod blue"' in overlay
    assert "key: sf_service" in overlay
    assert "key: sf_environment" in overlay
    assert overlay.count("action: upsert") == 4
    assert 'endpoint: "0.0.0.0:4318"' in overlay
    assert 'realm: "us0"' in overlay
    assert 'traces_endpoint: "https://ingest.us0.observability.splunkcloud.com/v2/trace/otlp"' in overlay
    assert 'access_token: "${env:SPLUNK_ACCESS_TOKEN}"' in overlay
    assert "logs/codex" not in overlay


def test_codex_local_native_logs_render_collector_logs_pipeline(tmp_path: Path) -> None:
    out = tmp_path / "local-logs"
    run_codex("--render", "--destination", "local-collector", "--enable-native-logs", "--output-dir", str(out))

    profile = (out / "profiles/codex-o11y-local.config.toml").read_text(encoding="utf-8")
    assert "http://127.0.0.1:14318/v1/logs" in profile
    overlay = (out / "collector/codex-o11y-local-collector.yaml").read_text(encoding="utf-8")
    assert "logs/codex:" in overlay
    assert "/v2/log/otlp" not in overlay
    assert 'logs_endpoint: "https://ingest.us0.observability.splunkcloud.com/v3/event"' in overlay
    assert "exporters: [otlphttp/codex_logs]" in overlay
    assert "exporters: [otlphttp/codex_traces, signalfx/codex]" not in overlay
    assert "exporters: [otlphttp/codex_traces]" in overlay


def test_codex_local_collector_pins_splunk_distribution_native_histograms(tmp_path: Path) -> None:
    out = tmp_path / "splunk-distribution"
    run_codex("--render", "--destination", "local-collector", "--output-dir", str(out))

    overlay = (out / "collector/codex-o11y-local-collector.yaml").read_text(encoding="utf-8")
    runner = (out / "collector/run-codex-o11y-local-collector.sh").read_text(encoding="utf-8")
    image = (
        "quay.io/signalfx/splunk-otel-collector"
        "@sha256:7ca38b306f8736673f24dda39a2c8040d33e575d22054a7f708b5829ea2a21f2"
    )

    assert image in overlay
    assert image in runner
    assert "otel/opentelemetry-collector-contrib" not in runner
    assert "signalfx/codex:" in overlay
    assert "exporters: [signalfx/codex]" in overlay
    assert "send_otlp_histograms: true" in overlay
    assert "splunk_otlp_histograms" not in overlay
    assert "--env SPLUNK_ACCESS_TOKEN" in runner
    assert "--config=/etc/otel/collector/codex-o11y.yaml" in runner


def test_codex_validate_rejects_upstream_collector_runner(tmp_path: Path) -> None:
    out = tmp_path / "wrong-distribution"
    run_codex("--render", "--destination", "local-collector", "--output-dir", str(out))
    runner = out / "collector/run-codex-o11y-local-collector.sh"
    runner.write_text(
        runner.read_text(encoding="utf-8").replace(
            "quay.io/signalfx/splunk-otel-collector"
            "@sha256:7ca38b306f8736673f24dda39a2c8040d33e575d22054a7f708b5829ea2a21f2",
            "otel/opentelemetry-collector-contrib:0.154.0",
        ),
        encoding="utf-8",
    )

    result = run_codex("--validate", "--output-dir", str(out), check=False)
    assert result.returncode != 0
    assert "must pin the supported Splunk Distribution image" in result.stdout + result.stderr
    assert "must not use the upstream contrib image" in result.stdout + result.stderr


def test_codex_notify_genai_metric_contract_and_delta_temporality() -> None:
    notify_span = load_notify_span_module()

    class RecordingInstrument:
        def __init__(self, name: str, unit: str | None, boundaries=()) -> None:
            self.name = name
            self.unit = unit
            self.boundaries = tuple(boundaries)
            self.points: list[tuple[float | int, dict[str, object]]] = []

        def record(self, value, attributes) -> None:
            self.points.append((value, dict(attributes)))

        def add(self, value, attributes) -> None:
            self.points.append((value, dict(attributes)))

    class RecordingMeter:
        def __init__(self) -> None:
            self.instruments: dict[str, RecordingInstrument] = {}

        def create_histogram(
            self,
            name: str,
            unit: str = "",
            explicit_bucket_boundaries_advisory=(),
        ) -> RecordingInstrument:
            instrument = RecordingInstrument(name, unit, explicit_bucket_boundaries_advisory)
            self.instruments[name] = instrument
            return instrument

        def create_counter(self, name: str, unit: str = "") -> RecordingInstrument:
            instrument = RecordingInstrument(name, unit)
            self.instruments[name] = instrument
            return instrument

    meter = RecordingMeter()
    provider = SimpleNamespace(get_meter=lambda *_args: meter)
    notify_span._record_metrics(provider, notify_span.synthetic_turn())

    assert {name: instrument.unit for name, instrument in meter.instruments.items()} == {
        "gen_ai.workflow.duration": "s",
        "gen_ai.agent.duration": "s",
        "gen_ai.client.operation.duration": "s",
        "gen_ai.client.token.usage": "{token}",
        "codex.turns": "",
    }
    duration_boundaries = (
        0.01,
        0.02,
        0.04,
        0.08,
        0.16,
        0.32,
        0.64,
        1.28,
        2.56,
        5.12,
        10.24,
        20.48,
        40.96,
        81.92,
    )
    token_boundaries = (
        1,
        4,
        16,
        64,
        256,
        1024,
        4096,
        16384,
        65536,
        262144,
        1048576,
        4194304,
        16777216,
        67108864,
    )
    for name in (
        "gen_ai.workflow.duration",
        "gen_ai.agent.duration",
        "gen_ai.client.operation.duration",
    ):
        assert meter.instruments[name].boundaries == duration_boundaries
    assert meter.instruments["gen_ai.client.token.usage"].boundaries == token_boundaries
    for instrument in meter.instruments.values():
        for _, attributes in instrument.points:
            assert attributes["gen_ai.agent.name"] == "codex"
            assert attributes["gen_ai.framework"] == "codex"
            assert attributes["gen_ai.provider.name"] == "openai"
            assert attributes["gen_ai.request.model"] == "codex-smoke-model"
            assert attributes["gen_ai.response.model"] == "codex-smoke-model"

    assert {
        attributes["gen_ai.token.type"]
        for _, attributes in meter.instruments["gen_ai.client.token.usage"].points
    } == {"input", "output"}
    assert meter.instruments["gen_ai.workflow.duration"].points[0][1]["gen_ai.operation.name"] == "invoke_workflow"
    assert meter.instruments["gen_ai.agent.duration"].points[0][1]["gen_ai.operation.name"] == "invoke_agent"
    assert meter.instruments["gen_ai.client.operation.duration"].points[0][1]["gen_ai.operation.name"] == "chat"

    delta = object()
    fake_metrics_sdk = SimpleNamespace(
        Histogram=type("Histogram", (), {}),
    )
    fake_metrics_export = SimpleNamespace(AggregationTemporality=SimpleNamespace(DELTA=delta))
    preferences = notify_span._delta_metric_temporality(fake_metrics_sdk, fake_metrics_export)
    assert set(preferences) == {fake_metrics_sdk.Histogram}
    assert all(value is delta for value in preferences.values())
    source = NOTIFY_SPAN.read_text(encoding="utf-8")
    assert "preferred_temporality=_delta_metric_temporality(metrics_sdk, metrics_export)" in source


def test_codex_direct_mode_fails_closed_for_credentials(tmp_path: Path) -> None:
    # Retain upstream coverage for native-log and gRPC direct requests while
    # asserting the stricter reviewed behavior: direct mode now fails before
    # rendering any credential-bearing profile, regardless of legacy options.
    cases = (
        ("default", ()),
        ("native-logs", ("--enable-native-logs",)),
        ("grpc", ("--external-collector-protocol", "otlp-grpc")),
    )
    for name, extra_args in cases:
        output_dir = tmp_path / name
        result = run_codex(
            "--render",
            "--destination",
            "direct",
            *extra_args,
            "--output-dir",
            str(output_dir),
            "--json",
            check=False,
        )
        assert result.returncode != 0
        output = result.stdout + result.stderr
        assert "header placeholders literally" in output
        assert "use local-collector" in output
        assert not (output_dir / "profiles/codex-o11y-direct.config.toml").exists()


def test_codex_reports_apply_plan_strict_config_hooks_and_histograms(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    run_codex("--render", "--destination", "local-collector", "--realm", "us0", "--output-dir", str(out))

    required = [
        "apply-plan.json",
        "coverage-report.json",
        "coverage-report.md",
        "doctor-report.md",
        "handoff.md",
        "collector/codex-o11y-local-collector.yaml",
        "bin/codex-o11y-exec",
        "bin/codex-o11y-jsonl-to-spans.py",
        "hooks/hooks.json",
        "hooks/codex-o11y-stop-hook.py",
        "runtime/codex-notify-galileo-handoff.md",
    ]
    for rel in required:
        assert (out / rel).is_file(), rel

    plan = json.loads((out / "apply-plan.json").read_text(encoding="utf-8"))
    assert ["codex", "--strict-config", "--profile", "codex-o11y-local"] in [
        profile["strict_config_command"] for profile in plan["profiles"]
    ]
    strict_commands = [" ".join(profile["strict_config_command"]) for profile in plan["profiles"]]
    assert "codex --strict-config --profile codex-o11y-local" in strict_commands
    runtime_commands = [
        command
        for step in plan["steps"]
        if step["section"] == "runtime"
        for command in step["commands"]
    ]
    assert any(command[-1].endswith("codex-o11y-exec") for command in runtime_commands)
    assert any(command[-1].endswith("codex-o11y-jsonl-to-spans.py") for command in runtime_commands)
    hook_commands = [
        command
        for step in plan["steps"]
        if step["section"] == "hooks"
        for command in step["commands"]
    ]
    assert any(command[0] == "merge-hooks" for command in hook_commands)

    hooks = json.loads((out / "hooks/hooks.json").read_text(encoding="utf-8"))
    assert "Stop" in hooks["hooks"]
    hook_text = (out / "hooks/codex-o11y-stop-hook.py").read_text(encoding="utf-8")
    assert "except Exception" in hook_text
    assert "sys.exit(main())" in hook_text
    assert "/hooks" in (out / "handoff.md").read_text(encoding="utf-8")
    assert "send_otlp_histograms: true" in (out / "collector/codex-o11y-local-collector.yaml").read_text(
        encoding="utf-8"
    )
    galileo_handoff = (out / "runtime/codex-notify-galileo-handoff.md").read_text(encoding="utf-8")
    assert "Galileo MCP server" in galileo_handoff
    assert "POST /v2/projects/{project_id}/traces" in galileo_handoff
    assert "user_metadata" in galileo_handoff
    assert "traces/count" in galileo_handoff


def test_codex_apply_uses_concrete_codex_home_installs_runtime_and_merges_hooks(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    existing_hooks = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup",
                    "hooks": [{"type": "command", "command": "python3 keep.py", "statusMessage": "Keep me"}],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 old-codex-o11y.py",
                            "statusMessage": "Capturing Codex O11y session metadata",
                        }
                    ]
                },
                {"hooks": [{"type": "command", "command": "python3 unrelated.py", "statusMessage": "Keep Stop"}]},
            ],
        }
    }
    codex_home.mkdir()
    (codex_home / "hooks.json").write_text(json.dumps(existing_hooks), encoding="utf-8")

    out = tmp_path / "rendered"
    result = run_codex(
        "--apply",
        "all",
        "--codex-home",
        str(codex_home),
        "--destination",
        "local-collector",
        "--realm",
        "us0",
        "--output-dir",
        str(out),
        "--json",
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True

    assert (codex_home / "codex-o11y-local.config.toml").is_file()
    assert (codex_home / "bin/codex-o11y-exec").is_file()
    assert (codex_home / "bin/codex-o11y-jsonl-to-spans.py").is_file()
    assert (codex_home / "hooks/codex-o11y-stop-hook.py").is_file()
    assert os.access(codex_home / "bin/codex-o11y-exec", os.X_OK)
    assert os.access(codex_home / "bin/codex-o11y-jsonl-to-spans.py", os.X_OK)

    merged = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
    assert "SessionStart" in merged["hooks"]
    stop_commands = [
        hook["command"]
        for group in merged["hooks"]["Stop"]
        for hook in group.get("hooks", [])
        if isinstance(hook, dict)
    ]
    assert "python3 unrelated.py" in stop_commands
    assert not any("old-codex-o11y.py" in command for command in stop_commands)
    assert any(str(codex_home / "hooks/codex-o11y-stop-hook.py") in command for command in stop_commands)

    operation_text = json.dumps(payload["operations"])
    assert "${CODEX_HOME" not in operation_text
    assert str(codex_home) in operation_text


def test_codex_apply_consumes_reviewed_artifacts_without_rerendering_defaults(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    out = tmp_path / "reviewed"
    run_codex(
        "--render",
        "--destination",
        "local-collector",
        "--realm",
        "us1",
        "--codex-home",
        str(codex_home),
        "--output-dir",
        str(out),
    )

    result = run_codex("--apply", "profiles", "--output-dir", str(out), "--json")
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["ok"] is True
    assert (codex_home / "codex-o11y-local.config.toml").is_file()
    assert not (codex_home / "codex-o11y-external.config.toml").exists()
    assert "http://127.0.0.1:14318/v1/traces" in (
        codex_home / "codex-o11y-local.config.toml"
    ).read_text(encoding="utf-8")


def test_codex_rejects_secret_flags_and_scans_rendered_token_leaks(tmp_path: Path) -> None:
    flag = run_codex(
        "--render",
        "--token=abc123",
        "--output-dir",
        str(tmp_path / "secret-flag"),
        check=False,
    )
    assert flag.returncode != 0
    assert "would expose a secret" in flag.stdout + flag.stderr

    header = run_codex(
        "--render",
        "--destination",
        "external-collector",
        "--external-trace-endpoint",
        "https://otel.example.com/v1/traces",
        "--external-metric-endpoint",
        "https://otel.example.com/v1/metrics",
        "--external-header",
        "x-api-key=SUPER_SECRET_TOKEN_SHOULD_NOT_RENDER",
        "--output-dir",
        str(tmp_path / "secret-header"),
        check=False,
    )
    assert header.returncode != 0
    assert "raw secret material" in header.stdout + header.stderr

    bearer = run_codex(
        "--render",
        "--destination",
        "external-collector",
        "--external-trace-endpoint",
        "https://otel.example.com/v1/traces",
        "--external-metric-endpoint",
        "https://otel.example.com/v1/metrics",
        "--external-header",
        "Authorization=Bearer abc123",
        "--output-dir",
        str(tmp_path / "bearer-header"),
        check=False,
    )
    assert bearer.returncode != 0
    assert "may carry credentials" in bearer.stdout + bearer.stderr

    placeholder = run_codex(
        "--render",
        "--destination",
        "external-collector",
        "--external-trace-endpoint",
        "https://otel.example.com/v1/traces",
        "--external-metric-endpoint",
        "https://otel.example.com/v1/metrics",
        "--external-header",
        "Authorization=${OTLP_TOKEN}",
        "--output-dir",
        str(tmp_path / "placeholder-header"),
        check=False,
    )
    assert placeholder.returncode != 0
    assert "sends OTLP header placeholders literally" in placeholder.stdout + placeholder.stderr
    assert not (tmp_path / "placeholder-header/profiles/codex-o11y-external.config.toml").exists()


def test_codex_exec_json_fixture_parses_dedupe_and_truncates_content() -> None:
    long_text = "x" * 400
    fixture = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            json.dumps({"type": "turn.started"}),
            json.dumps({"type": "item.completed", "item": {"id": "item-1", "type": "agent_message", "text": long_text}}),
            json.dumps({"type": "item.completed", "item": {"id": "item-1", "type": "agent_message", "text": long_text}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}}),
            "{bad json",
        ]
    )
    parsed = codex_o11y.parse_codex_jsonl(
        fixture,
        service_name="codex-test",
        environment="test",
        capture_content=True,
        max_text_length=64,
    )
    assert parsed["errors"]
    assert parsed["dedupe_count"] == 4
    assert any(metric["name"] == "codex.usage.input_tokens" for metric in parsed["metrics"])
    content_spans = [span for span in parsed["spans"] if "codex.content" in span["attributes"]]
    assert content_spans[0]["attributes"]["codex.content"] == "x" * 64
    assert content_spans[0]["attributes"]["codex.content_truncated"] is True


def test_generated_jsonl_parser_and_stop_hook_fail_soft(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    run_codex("--render", "--output-dir", str(out))
    fixture = tmp_path / "events.jsonl"
    fixture.write_text('{"type":"thread.started","thread_id":"t1"}\nnot-json\n', encoding="utf-8")
    spans = tmp_path / "spans.json"
    parser = out / "bin/codex-o11y-jsonl-to-spans.py"
    result = run_cmd(sys.executable, str(parser), "--input", str(fixture), "--output", str(spans))
    assert result.returncode == 0
    parsed = json.loads(spans.read_text(encoding="utf-8"))
    assert parsed["errors"]

    hook = out / "hooks/codex-o11y-stop-hook.py"
    result = subprocess.run(
        [sys.executable, str(hook)],
        env={"CODEX_O11Y_SESSION_JSONL": str(tmp_path / "missing.jsonl"), "CODEX_O11Y_HOOK_LOG_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert (tmp_path / "codex-o11y-stop-hook.log").is_file()

    interactive = tmp_path / "interactive.jsonl"
    interactive.write_text('{"type":"thread.started","thread_id":"t-stop"}\n', encoding="utf-8")
    interactive_spans = tmp_path / "interactive-spans.json"
    result = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"transcript_path": str(interactive)}),
        env={"CODEX_O11Y_INTERACTIVE_SPANS": str(interactive_spans), "CODEX_O11Y_HOOK_LOG_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    parsed = json.loads(interactive_spans.read_text(encoding="utf-8"))
    assert parsed["spans"][0]["attributes"]["codex.event_type"] == "thread.started"


def test_exec_wrapper_preserves_codex_failure_status_and_still_parses_jsonl(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    marker = tmp_path / "shell-injection-marker"
    run_codex(
        "--render",
        "--service-name",
        f"codex $(touch {marker})",
        "--environment",
        "prod `touch should-not-run`",
        "--output-dir",
        str(out),
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    codex.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"$CODEX_ARGS_OUT\"\n"
        "printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"t-fail\"}'\n"
        "exit 7\n",
        encoding="utf-8",
    )
    codex.chmod(codex.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CODEX_O11Y_JSONL"] = str(tmp_path / "events.jsonl")
    env["CODEX_O11Y_SPANS"] = str(tmp_path / "spans.json")
    env["CODEX_ARGS_OUT"] = str(tmp_path / "codex-args.txt")

    result = subprocess.run(
        [str(out / "bin/codex-o11y-exec"), "do work"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 7
    assert (tmp_path / "codex-args.txt").read_text(encoding="utf-8").splitlines() == [
        "exec",
        "--profile",
        "codex-o11y-local",
        "--json",
        "do work",
    ]
    assert not (tmp_path / "events.jsonl").exists()
    assert not marker.exists()
    spans = json.loads((tmp_path / "spans.json").read_text(encoding="utf-8"))
    assert spans["spans"][0]["attributes"]["codex.thread_id"] == "t-fail"
    assert spans["spans"][0]["attributes"]["service.name"] == f"codex $(touch {marker})"


def test_content_capture_and_ai_defense_gates(tmp_path: Path) -> None:
    spec = {
        "api_version": "splunk-observability-codex-instrumentation-setup/v1",
        "codex": {"content_capture": True},
    }
    spec_path = tmp_path / "content.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    blocked = run_codex("--render", "--spec", str(spec_path), "--output-dir", str(tmp_path / "blocked"), check=False)
    assert blocked.returncode != 0
    assert "--accept-content-capture" in blocked.stdout + blocked.stderr

    accepted = tmp_path / "accepted"
    run_codex(
        "--render",
        "--enable-advanced-genai-spans",
        "--accept-content-capture",
        "--enable-ai-defense",
        "--accept-ai-defense-content-inspection",
        "--output-dir",
        str(accepted),
    )
    env_text = (accepted / "runtime/codex-o11y.env").read_text(encoding="utf-8")
    assert "CODEX_O11Y_CAPTURE_CONTENT=true" in env_text
    coverage = json.loads((accepted / "coverage-report.json").read_text(encoding="utf-8"))["coverage"]
    assert any(entry["key"] == "ai_defense" and entry["status"] == "render" for entry in coverage)

    ai_blocked = run_codex(
        "--render",
        "--enable-ai-defense",
        "--output-dir",
        str(tmp_path / "ai-blocked"),
        check=False,
    )
    assert ai_blocked.returncode != 0
    assert "--accept-ai-defense-content-inspection" in ai_blocked.stdout + ai_blocked.stderr
