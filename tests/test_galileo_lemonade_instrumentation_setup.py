#!/usr/bin/env python3
"""Regression tests for Lemonade/Splunk and Galileo instrumentation skills."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from tests.regression_helpers import REPO_ROOT


GALILEO_SKILL = REPO_ROOT / "skills/galileo-lemonade-instrumentation-setup"
LEMONADE_SKILL = REPO_ROOT / "skills/lemonade-splunk-otel"
RENDER = GALILEO_SKILL / "scripts/render_collector_config.py"
VALIDATE = GALILEO_SKILL / "scripts/validate_collector_config.py"


def base_config() -> dict[str, object]:
    return {
        "receivers": {
            "otlp": {
                "protocols": {
                    "http": {"endpoint": "127.0.0.1:4318"},
                    "grpc": {"endpoint": "127.0.0.1:4317"},
                }
            }
        },
        "processors": {
            "memory_limiter": {"limit_mib": 256},
            "resourcedetection": {"detectors": ["env", "system"]},
            "batch": {},
        },
        "exporters": {
            "otlphttp/splunk": {"endpoint": "https://example.invalid"},
            "signalfx": {},
        },
        "service": {
            "pipelines": {
                "traces": {
                    "receivers": ["otlp"],
                    "processors": [
                        "memory_limiter",
                        "resourcedetection",
                        "batch",
                    ],
                    "exporters": ["otlphttp/splunk"],
                },
                "metrics": {
                    "receivers": ["otlp"],
                    "processors": ["batch"],
                    "exporters": ["signalfx"],
                },
                "logs": {
                    "receivers": ["otlp"],
                    "processors": ["batch"],
                    "exporters": ["otlphttp/splunk"],
                },
            }
        },
        "extensions": {"health_check": {"endpoint": "127.0.0.1:13133"}},
    }


def write_base(path: Path) -> None:
    path.write_text(yaml.safe_dump(base_config(), sort_keys=False), encoding="utf-8")


def render(
    base: Path, output: Path, mode: str, *extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RENDER),
            "--base",
            str(base),
            "--output",
            str(output),
            "--mode",
            mode,
            *extra,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def load(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_server_fanout_is_exact_idempotent_and_preserves_unknown_config(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    write_base(base)
    result = render(base, first, "server-fanout", "--routing", "ids")
    assert result.returncode == 0, result.stderr
    document = load(first)
    exporter = document["exporters"]["otlp_http/galileo_lemonade"]
    assert exporter["traces_endpoint"] == "${env:GALILEO_OTLP_TRACES_ENDPOINT}"
    assert "endpoint" not in exporter
    assert exporter["headers"] == {
        "Galileo-API-Key": "${env:GALILEO_API_KEY}",
        "projectid": "${env:GALILEO_PROJECT_ID}",
        "logstreamid": "${env:GALILEO_LOG_STREAM_ID}",
    }
    assert document["service"]["pipelines"]["traces"]["exporters"] == [
        "otlphttp/splunk"
    ]
    server_pipe = document["service"]["pipelines"]["traces/lemonade_galileo_server"]
    assert server_pipe["exporters"] == ["otlp_http/galileo_lemonade"]
    assert "filter/lemonade_galileo_server" in server_pipe["processors"]
    assert document["processors"]["filter/lemonade_galileo_server"][
        "trace_conditions"
    ] == ['resource.attributes["service.name"] != "lemonade-server"']
    assert (
        document["processors"]["filter/lemonade_galileo_server"]["error_mode"]
        == "propagate"
    )
    assert document["extensions"]["health_check"] == {"endpoint": "127.0.0.1:13133"}
    assert (
        document["extensions"]["file_storage/galileo_lemonade"]["directory_permissions"]
        == "0700"
    )
    checked = subprocess.run(
        [
            sys.executable,
            str(VALIDATE),
            "--collector-config",
            str(first),
            "--mode",
            "server-fanout",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr

    again = render(first, second, "server-fanout", "--routing", "ids")
    assert again.returncode == 0, again.stderr
    assert load(first) == load(second)


def test_client_fanout_separates_native_and_client_galileo_routes(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    server = tmp_path / "server.yaml"
    client = tmp_path / "client.yaml"
    write_base(base)
    assert render(base, server, "server-fanout").returncode == 0
    result = render(server, client, "client-fanout")
    assert result.returncode == 0, result.stderr
    document = load(client)
    pipelines = document["service"]["pipelines"]
    assert pipelines["traces"]["exporters"] == ["otlphttp/splunk"]
    client_pipe = pipelines["traces/lemonade_galileo_client"]
    assert client_pipe["receivers"] == ["otlp/lemonade_galileo_client"]
    assert client_pipe["exporters"] == ["otlp_http/galileo_lemonade"]
    assert "resource/lemonade" not in client_pipe["processors"]
    assert "resource/lemonade_galileo_client" in client_pipe["processors"]
    assert "resourcedetection" in client_pipe["processors"]
    semantics = document["processors"]["transform/lemonade_client_semantics"]
    assert semantics["error_mode"] == "propagate"
    assert "gen_ai.provider.name" in str(semantics)
    privacy = document["processors"]["transform/lemonade_client_error_privacy"]
    assert privacy["error_mode"] == "propagate"
    assert "exception.stacktrace" in str(privacy)
    assert "delete_matching_keys" in str(privacy)
    assert "input[.]value" in str(privacy)
    endpoint = document["receivers"]["otlp/lemonade_galileo_client"]["protocols"][
        "http"
    ]["endpoint"]
    assert endpoint == "127.0.0.1:14318"

    checked = subprocess.run(
        [
            sys.executable,
            str(VALIDATE),
            "--collector-config",
            str(client),
            "--mode",
            "client-fanout",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr


def test_custom_client_processors_cannot_follow_terminal_privacy_guards(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    rendered = tmp_path / "client.yaml"
    unsafe = tmp_path / "unsafe.yaml"
    document = base_config()
    document["processors"]["transform/reviewed_custom"] = {  # type: ignore[index]
        "error_mode": "propagate",
        "trace_statements": [],
    }
    base.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    result = render(
        base,
        rendered,
        "client-fanout",
        "--client-processor",
        "memory_limiter",
        "--client-processor",
        "transform/reviewed_custom",
        "--client-processor",
        "batch",
    )
    assert result.returncode == 0, result.stderr
    processors = load(rendered)["service"]["pipelines"][  # type: ignore[index]
        "traces/lemonade_galileo_client"
    ]["processors"]
    assert processors[-3:] == [
        "transform/lemonade_client_error_privacy",
        "transform/lemonade_galileo_route_guard",
        "batch",
    ]
    assert processors.index("transform/reviewed_custom") < processors.index(
        "transform/lemonade_client_error_privacy"
    )

    tampered = load(rendered)
    values = tampered["service"]["pipelines"][  # type: ignore[index]
        "traces/lemonade_galileo_client"
    ]["processors"]
    values.remove("transform/reviewed_custom")
    values.insert(values.index("batch"), "transform/reviewed_custom")
    unsafe.write_text(yaml.safe_dump(tampered, sort_keys=False), encoding="utf-8")
    checked = subprocess.run(
        [
            sys.executable,
            str(VALIDATE),
            "--collector-config",
            str(unsafe),
            "--mode",
            "client-fanout",
            "--allow-custom-client-processors",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert checked.returncode != 0
    assert "must end its non-batch processors" in checked.stderr

    rejected = render(
        base,
        tmp_path / "rejected.yaml",
        "client-fanout",
        "--client-processor",
        "batch",
        "--client-processor",
        "transform/reviewed_custom",
    )
    assert rejected.returncode != 0
    assert (
        "must not contain a non-batch processor after its first batch"
        in rejected.stderr
    )


def test_console_navigation_url_is_not_used_as_a_galileo_selector(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    write_base(base)
    result = render(
        base,
        output,
        "client-fanout",
        "--galileo-console-url",
        "https://console.example.invalid/tenant-navigation",
    )
    assert result.returncode == 0, result.stderr
    assert "Galileo console origin: https://console.example.invalid/" in result.stdout
    assert "Galileo API base candidate: https://api.example.invalid" in result.stdout
    assert "/tenant-navigation (not a project or Log stream selector)" in result.stdout


def test_console_navigation_url_rejects_invalid_hostname(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    write_base(base)
    result = render(
        base,
        output,
        "client-fanout",
        "--galileo-console-url",
        "https://console.example.invalid /tenant-navigation",
    )
    assert result.returncode != 0
    assert "invalid hostname" in result.stderr
    assert not output.exists()


def test_splunk_only_removes_all_managed_galileo_components(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    client = tmp_path / "client.yaml"
    clean = tmp_path / "clean.yaml"
    write_base(base)
    assert render(base, client, "client-fanout").returncode == 0
    assert render(client, clean, "splunk-only").returncode == 0
    text = clean.read_text(encoding="utf-8")
    assert "galileo" not in text.lower()
    assert "transform/lemonade_error_privacy" not in text
    assert load(clean)["service"]["pipelines"]["traces"]["exporters"] == [
        "otlphttp/splunk"
    ]


def test_renderer_rejects_non_loopback_client_receiver(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    write_base(base)
    result = render(
        base,
        output,
        "client-fanout",
        "--client-receiver-endpoint",
        "0.0.0.0:14318",
    )
    assert result.returncode != 0
    assert "loopback" in result.stderr
    assert not output.exists()


def test_names_routing_uses_only_name_placeholders(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    write_base(base)
    assert render(base, output, "server-fanout", "--routing", "names").returncode == 0
    headers = load(output)["exporters"]["otlp_http/galileo_lemonade"]["headers"]
    assert headers["project"] == "${env:GALILEO_PROJECT}"
    assert headers["logstream"] == "${env:GALILEO_LOG_STREAM}"
    assert "projectid" not in headers
    assert "logstreamid" not in headers


def test_client_mirroring_requires_explicit_validation_acceptance(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    write_base(base)
    result = render(
        base, output, "client-fanout", "--mirror-client-to-native-exporters"
    )
    assert result.returncode == 0, result.stderr
    exporters = load(output)["service"]["pipelines"]["traces/lemonade_galileo_client"][
        "exporters"
    ]
    assert exporters == ["otlphttp/splunk", "otlp_http/galileo_lemonade"]
    rejected = subprocess.run(
        [
            sys.executable,
            str(VALIDATE),
            "--collector-config",
            str(output),
            "--mode",
            "client-fanout",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "--allow-client-mirror" in rejected.stderr
    accepted = subprocess.run(
        [
            sys.executable,
            str(VALIDATE),
            "--collector-config",
            str(output),
            "--mode",
            "client-fanout",
            "--allow-client-mirror",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stderr


@pytest.mark.parametrize(
    "tampered_exporters",
    [
        ["signalfx", "otlp_http/galileo_lemonade"],
        ["otlphttp/splunk", "otlp_http/galileo_lemonade"],
        ["signalfx", "otlphttp/splunk", "otlp_http/galileo_lemonade"],
    ],
    ids=("missing-first-native", "missing-second-native", "reordered-native"),
)
def test_client_mirror_requires_exact_native_then_galileo_exporters(
    tmp_path: Path, tampered_exporters: list[str]
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    document = base_config()
    document["service"]["pipelines"]["traces"]["exporters"] = [
        "otlphttp/splunk",
        "signalfx",
    ]
    base.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    result = render(
        base, output, "client-fanout", "--mirror-client-to-native-exporters"
    )
    assert result.returncode == 0, result.stderr
    document = load(output)
    document["service"]["pipelines"]["traces/lemonade_galileo_client"]["exporters"] = (
        tampered_exporters
    )
    output.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    rejected = subprocess.run(
        [
            sys.executable,
            str(VALIDATE),
            "--collector-config",
            str(output),
            "--mode",
            "client-fanout",
            "--allow-client-mirror",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "exact native exporter sequence" in rejected.stderr


class CaptureHandler(BaseHTTPRequestHandler):
    payload: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        type(self).payload = json.loads(self.rfile.read(length))
        body = b'{"partialSuccess":{"rejectedSpans":0}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_galileo_canary_is_redacted_and_has_agent_llm_hierarchy() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(GALILEO_SKILL / "scripts/send_galileo_canary.py"),
                "--endpoint",
                f"http://127.0.0.1:{server.server_port}/v1/traces",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert result.returncode == 0, result.stderr
    assert "TRACE_ID=" in result.stdout and "TRACE_NAME=" in result.stdout
    assert "CREATED_AFTER=" in result.stdout
    spans = CaptureHandler.payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 3
    assert spans[1]["parentSpanId"] == spans[0]["spanId"]
    assert spans[2]["parentSpanId"] == spans[0]["spanId"]
    for span in spans:
        attrs = {
            item["key"]: next(iter(item["value"].values()))
            for item in span["attributes"]
        }
        assert attrs["input.value"] == "[REDACTED]"
        assert attrs["output.value"] == "[REDACTED]"
        assert attrs["gen_ai.provider.name"] == "lemonade"
        assert attrs["galileo.logstream.name"] == "route-guard-canary"
        assert attrs["galileo.experiment.id"] == "route-guard-canary"
    resource_attrs = {
        item["key"]: next(iter(item["value"].values()))
        for item in CaptureHandler.payload["resourceSpans"][0]["resource"]["attributes"]
    }
    assert resource_attrs["galileo.project.name"] == "route-guard-canary"
    assert resource_attrs["galileo.dataset.input"] == "route-guard-canary"
    llm_attrs = {
        item["key"]: next(iter(item["value"].values()))
        for item in spans[1]["attributes"]
    }
    assert llm_attrs["llm.input_messages.0.message.content"] == "[REDACTED]"
    assert llm_attrs["llm.output_messages.0.message.content"] == "[REDACTED]"
    kinds = {
        next(
            next(iter(item["value"].values()))
            for item in span["attributes"]
            if item["key"] == "openinference.span.kind"
        )
        for span in spans
    }
    assert kinds == {"AGENT", "LLM", "TOOL"}


def test_renderer_rejects_unrelated_generic_galileo_pipeline(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    document = base_config()
    document["exporters"]["otlp_http/galileo"] = {
        "traces_endpoint": "https://example.invalid/otel/v1/traces"
    }
    document["service"]["pipelines"]["traces/unrelated"] = {
        "receivers": ["otlp"],
        "processors": ["batch"],
        "exporters": ["otlp_http/galileo"],
    }
    base.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    result = render(base, output, "client-fanout")
    assert result.returncode != 0
    assert "another Galileo-like exporter/route" in result.stderr
    assert not output.exists()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readback_secret_file_and_trace_matching_are_safe(tmp_path: Path) -> None:
    module = load_module(
        "galileo_readback_test", GALILEO_SKILL / "scripts/galileo_readback.py"
    )
    secret = tmp_path / "key"
    secret.write_text("test-only-value\n", encoding="utf-8")
    secret.chmod(0o600)
    assert module.read_secret(secret) == "test-only-value"
    secret.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        module.read_secret(secret)
    record = {
        "trace_id": "galileo-uuid",
        "external_id": "ab-cd",
        "name": "unique-canary",
    }
    assert module.match_record(record, "abcd", "") == ["trace_id"]
    assert module.match_record(record, "", "unique-canary") == ["name"]
    assert module.match_record(record, "abcd", "unique-canary") == ["trace_id", "name"]
    assert module.match_record(record, "abcd", "wrong") == []


def test_target_discovery_paginates_and_emits_only_routing_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(GALILEO_SKILL / "scripts"))
    module = load_module(
        "galileo_target_discovery_test",
        GALILEO_SKILL / "scripts/galileo_target_discovery.py",
    )
    responses = [
        {
            "projects": [
                {
                    "id": "project-b",
                    "name": "Project B",
                    "created_by_user": {"email": "must-not-appear@example.com"},
                    "log_streams": [{"id": "stream-b", "name": "Production"}],
                }
            ],
            "next_starting_token": 100,
        },
        {
            "projects": [
                {
                    "id": "project-a",
                    "name": "Project A",
                    "log_streams": [{"id": "stream-a", "name": "Development"}],
                }
            ],
            "next_starting_token": None,
        },
    ]

    def fake_request(*_args, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(module, "request_json", fake_request)
    args = type(
        "Args",
        (),
        {
            "api_base": "https://api.example.com",
            "api_key_header": "Galileo-API-Key",
            "request_timeout": 1.0,
            "project_id": "",
            "project_name": "",
            "limit": 100,
            "max_pages": 10,
        },
    )()
    result = module.discover(args, "not-printed")
    assert [item["project_id"] for item in result["projects"]] == [
        "project-a",
        "project-b",
    ]
    assert result["projects"][0]["log_streams"] == [
        {"log_stream_id": "stream-a", "log_stream_name": "Development"}
    ]
    assert "created_by_user" not in json.dumps(result)
    assert "not-printed" not in json.dumps(result)


def test_target_discovery_uses_paginated_log_stream_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(GALILEO_SKILL / "scripts"))
    module = load_module(
        "galileo_target_discovery_fallback_test",
        GALILEO_SKILL / "scripts/galileo_target_discovery.py",
    )
    responses = [
        {
            "log_streams": [{"id": "stream-z", "name": "Zeta"}],
            "next_starting_token": 100,
        },
        {
            "log_streams": [{"id": "stream-a", "name": "Alpha"}],
            "next_starting_token": None,
        },
    ]
    endpoints: list[str] = []

    def fake_request(_args, _key, _method, endpoint, _payload=None):
        endpoints.append(endpoint)
        return responses.pop(0)

    monkeypatch.setattr(module, "request_json", fake_request)
    args = type(
        "Args",
        (),
        {
            "api_base": "https://api.example.com",
            "api_key_header": "Splunk-AO-API-Key",
            "request_timeout": 1.0,
            "limit": 100,
            "max_pages": 10,
        },
    )()
    streams = module.list_project_log_streams(args, "not-printed", "project-id")
    assert streams == [
        {"log_stream_id": "stream-a", "log_stream_name": "Alpha"},
        {"log_stream_id": "stream-z", "log_stream_name": "Zeta"},
    ]
    assert all("/log_streams/paginated?" in endpoint for endpoint in endpoints)


def test_target_discovery_rejects_malformed_or_conflicting_routing_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(GALILEO_SKILL / "scripts"))
    module = load_module(
        "galileo_target_discovery_malformed_test",
        GALILEO_SKILL / "scripts/galileo_target_discovery.py",
    )
    with pytest.raises(RuntimeError, match="non-empty string"):
        module.sanitized_log_streams(
            [{"id": "stream-id", "name": {"email": "must-not-appear@example.com"}}]
        )
    with pytest.raises(RuntimeError, match="conflicting names"):
        module.sanitized_log_streams(
            [
                {"id": "stream-id", "name": "First"},
                {"id": "stream-id", "name": "Second"},
            ]
        )
    with pytest.raises(RuntimeError, match="projects array"):
        module.project_items({"data": []})


def test_target_discovery_does_not_reflect_transport_error_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(GALILEO_SKILL / "scripts"))
    module = load_module(
        "galileo_target_discovery_transport_test",
        GALILEO_SKILL / "scripts/galileo_target_discovery.py",
    )

    class FailingOpener:
        def open(self, *_args, **_kwargs):
            raise module.urllib.error.URLError("dummy-secret-must-not-appear")

    monkeypatch.setattr(
        module.urllib.request, "build_opener", lambda *_args: FailingOpener()
    )
    args = type(
        "Args",
        (),
        {
            "api_key_header": "Splunk-AO-API-Key",
            "request_timeout": 1.0,
        },
    )()
    with pytest.raises(RuntimeError) as error:
        module.request_json(
            args,
            "dummy-secret-must-not-appear",
            "GET",
            "https://api.example.com/v2/projects",
        )
    assert "dummy-secret-must-not-appear" not in str(error.value)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"projects": []}, "omitted its pagination token"),
        (
            {"projects": [], "next_starting_token": True},
            "invalid pagination token",
        ),
    ],
)
def test_target_discovery_rejects_ambiguous_pagination(
    monkeypatch: pytest.MonkeyPatch,
    document: dict[str, object],
    message: str,
) -> None:
    monkeypatch.syspath_prepend(str(GALILEO_SKILL / "scripts"))
    module = load_module(
        "galileo_target_discovery_pagination_test_" + message.split()[0],
        GALILEO_SKILL / "scripts/galileo_target_discovery.py",
    )
    monkeypatch.setattr(module, "request_json", lambda *_args, **_kwargs: document)
    args = type(
        "Args",
        (),
        {
            "api_base": "https://api.example.com",
            "api_key_header": "Splunk-AO-API-Key",
            "request_timeout": 1.0,
            "project_id": "",
            "project_name": "",
            "limit": 100,
            "max_pages": 10,
        },
    )()
    with pytest.raises(RuntimeError, match=message):
        module.discover(args, "not-printed")


def test_readback_accepts_safe_enterprise_api_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module(
        "galileo_readback_path_test", GALILEO_SKILL / "scripts/galileo_readback.py"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "galileo_readback.py",
            "--api-base",
            "https://galileo.example.com/platform/api",
            "--expected-origin",
            "https://galileo.example.com",
            "--api-key-file",
            "/not/read/during-parse",
            "--api-key-header",
            "Splunk-AO-API-Key",
            "--project-id",
            "project-id",
            "--log-stream-id",
            "stream-id",
            "--expected-name",
            "unique-canary",
            "--created-after",
            "2026-07-11T12:00:00Z",
        ],
    )
    args = module.parse_args()
    assert args.api_base == "https://galileo.example.com/platform/api"


def test_readback_rejects_invalid_api_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module(
        "galileo_readback_invalid_host_test",
        GALILEO_SKILL / "scripts/galileo_readback.py",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "galileo_readback.py",
            "--api-base",
            "https://api.example.com /platform/api",
            "--expected-origin",
            "https://api.example.com",
            "--api-key-file",
            "/not/read/during-parse",
            "--api-key-header",
            "Splunk-AO-API-Key",
            "--project-id",
            "project-id",
            "--log-stream-id",
            "stream-id",
            "--expected-name",
            "unique-canary",
            "--created-after",
            "2026-07-11T12:00:00Z",
        ],
    )
    with pytest.raises(SystemExit):
        module.parse_args()


def test_readback_sanitizes_hierarchy_and_enforces_privacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module(
        "galileo_readback_summary_test", GALILEO_SKILL / "scripts/galileo_readback.py"
    )
    detail = {
        "id": "galileo-id",
        "name": "unique-canary",
        "is_complete": True,
        "input": "[REDACTED]",
        "output": "[REDACTED]",
        "spans": [
            {
                "type": "agent",
                "input": "[REDACTED]",
                "output": "[REDACTED]",
                "spans": [
                    {"type": "llm", "input": "[REDACTED]", "output": "[REDACTED]"},
                    {"type": "tool", "input": "[REDACTED]", "output": "[REDACTED]"},
                ],
            }
        ],
    }
    monkeypatch.setattr(module, "request_json", lambda *args, **kwargs: detail)
    args = type(
        "Args",
        (),
        {
            "api_base": "https://api.example.com",
            "project_id": "project-id",
            "require_span_type": ["agent", "llm", "tool"],
            "require_redacted_content": True,
        },
    )()
    summary = module.get_trace_summary(args, "not-printed", {"id": "galileo-id"})
    assert summary["span_types"] == ["agent", "llm", "tool"]
    assert summary["span_count"] == 3
    assert "input" not in summary and "output" not in summary
    detail["spans"][0]["input"] = "sensitive-value"
    with pytest.raises(RuntimeError, match="non-redacted"):
        module.get_trace_summary(args, "not-printed", {"id": "galileo-id"})
    assert (
        module.content_state(
            {"messages": [{"content": "sensitive-value"}, {"content": "[REDACTED]"}]}
        )
        == "present"
    )


@pytest.mark.skipif(
    sys.platform.startswith("linux"),
    reason="positive integration requires an installed root-owned evidence fixture",
)
def test_collector_runtime_wrapper_uses_protected_key_file(tmp_path: Path) -> None:
    class TinyproxyProbeHandler(BaseHTTPRequestHandler):
        def do_CONNECT(self) -> None:  # noqa: N802
            self.send_response(200 if self.path == "api.example.com:443" else 403)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), TinyproxyProbeHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    secret = tmp_path / "galileo_api_key"
    secret.write_text("test-only-value\n", encoding="utf-8")
    secret.chmod(0o600)
    endpoint = "https://api.example.com/otel/v1/traces"
    origin = "https://api.example.com"
    canonical = json.dumps(
        {
            "endpoint": endpoint,
            "log_stream": "stream-id",
            "project": "project-id",
            "selector_kind": "ids",
            "version": 1,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    fingerprint = hashlib.sha256(canonical).hexdigest()
    queue = tmp_path / fingerprint
    queue.mkdir()
    queue.chmod(0o700)
    wrapper = GALILEO_SKILL / "scripts/collector_runtime_wrapper.py"
    wrapper_module = load_module("galileo_wrapper_fixture", wrapper)
    tinyproxy_binary = tmp_path / "tinyproxy"
    tinyproxy_binary.write_bytes(b"reviewed tinyproxy fixture")
    tinyproxy_binary.chmod(0o700)
    proxy_filter = tmp_path / "galileo.filter"
    proxy_filter.write_text(r"^api\.example\.com$" + "\n", encoding="ascii")
    proxy_filter.chmod(0o600)
    proxy_config = tmp_path / "galileo.conf"
    proxy_config.write_text(
        "User tinyproxy\n"
        "Group tinyproxy\n"
        "Listen 127.0.0.1\n"
        f"Port {proxy.server_port}\n"
        "Timeout 30\n"
        "MaxClients 32\n"
        'PidFile "/run/tinyproxy-galileo/tinyproxy.pid"\n'
        "Syslog On\n"
        "LogLevel Info\n"
        "Allow 127.0.0.1\n"
        "ConnectPort 443\n"
        f'Filter "{proxy_filter}"\n'
        "FilterType ere\n"
        "FilterURLs No\n"
        "FilterCaseSensitive Yes\n"
        "FilterDefaultDeny Yes\n"
        "DisableViaHeader Yes\n",
        encoding="utf-8",
    )
    proxy_config.chmod(0o600)
    descriptor, binary_provenance = wrapper_module.open_trusted_executable(
        tinyproxy_binary, None
    )
    os.close(descriptor)
    _, config_provenance = wrapper_module.read_trusted_proxy_asset(
        proxy_config, "config", None
    )
    _, filter_provenance = wrapper_module.read_trusted_proxy_asset(
        proxy_filter, "filter", None
    )
    evidence = tmp_path / "tinyproxy-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "control": "tinyproxy-exact-connect-allowlist",
                "proxy_url": f"http://127.0.0.1:{proxy.server_port}",
                "allowed_connect_host": "api.example.com",
                "allowed_connect_port": 443,
                "binary": binary_provenance,
                "config": config_provenance,
                "filter": filter_provenance,
            }
        ),
        encoding="utf-8",
    )
    evidence.chmod(0o400)
    environment = dict(os.environ)
    environment.update(
        {
            "GALILEO_API_KEY_FILE": str(secret),
            "GALILEO_OTLP_TRACES_ENDPOINT": endpoint,
            "GALILEO_EXPECTED_ORIGIN": origin,
            "GALILEO_PROJECT_ID": "project-id",
            "GALILEO_LOG_STREAM_ID": "stream-id",
            "GALILEO_PROXY_URL": f"http://127.0.0.1:{proxy.server_port}",
            "GALILEO_TINYPROXY_EVIDENCE_FILE": str(evidence),
            "GALILEO_DESTINATION_FINGERPRINT": fingerprint,
            "GALILEO_QUEUE_STORAGE_DIRECTORY": str(queue),
        }
    )
    environment.pop("GALILEO_API_KEY", None)
    try:
        checked = subprocess.run(
            [sys.executable, str(wrapper), "--check"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        assert checked.returncode == 0, checked.stderr
        assert "test-only-value" not in checked.stdout + checked.stderr
        executed = subprocess.run(
            [sys.executable, str(wrapper), "--", "/usr/bin/true"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        assert executed.returncode == 0, executed.stderr
        environment["GALILEO_OTLP_TRACES_ENDPOINT"] = (
            "http://api.example.com/otel/v1/traces"
        )
        rejected = subprocess.run(
            [sys.executable, str(wrapper), "--check"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        assert rejected.returncode != 0
        assert "HTTPS" in rejected.stderr
    finally:
        proxy.shutdown()
        proxy_thread.join(timeout=5)
        proxy.server_close()


def test_migrated_lemonade_skill_scopes_resource_and_error_changes(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    write_base(base)
    result = subprocess.run(
        [
            sys.executable,
            str(LEMONADE_SKILL / "scripts/render_collector_config.py"),
            "--base",
            str(base),
            "--output",
            str(output),
            "--deployment-environment",
            "ryzen-halo-dev",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    document = load(output)
    transform = document["processors"]["transform/lemonade_resource_privacy"]
    assert "ryzen-halo-dev" in str(transform)
    assert "status.message" in str(transform)
    assert "[REDACTED]" in str(transform)
    assert transform["error_mode"] == "propagate"
    assert (
        "transform/lemonade_resource_privacy"
        in document["service"]["pipelines"]["traces"]["processors"]
    )
    assert "send_otlp_histograms" not in document["exporters"]["signalfx"]
    assert document["processors"]["resourcedetection"]["detectors"] == ["env", "system"]


def test_lemonade_journald_uses_dedicated_pipeline(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    write_base(base)
    result = subprocess.run(
        [
            sys.executable,
            str(LEMONADE_SKILL / "scripts/render_collector_config.py"),
            "--base",
            str(base),
            "--output",
            str(output),
            "--deployment-environment",
            "ryzen-halo-dev",
            "--enable-journald",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    document = load(output)
    assert (
        "journald/lemonade" not in document["service"]["pipelines"]["logs"]["receivers"]
    )
    dedicated = document["service"]["pipelines"]["logs/lemonade"]
    assert dedicated["receivers"] == ["journald/lemonade"]
    assert "resource/lemonade_logs" in dedicated["processors"]


def test_lemonade_legacy_shared_relabel_requires_explicit_migration(
    tmp_path: Path,
) -> None:
    base = tmp_path / "legacy.yaml"
    output = tmp_path / "output.yaml"
    document = base_config()
    document["processors"]["resource/lemonade"] = {
        "attributes": [
            {"key": "service.name", "value": "lemonade-server", "action": "insert"},
            {
                "key": "deployment.environment.name",
                "value": "legacy-dev",
                "action": "insert",
            },
            {
                "key": "deployment.environment",
                "value": "legacy-dev",
                "action": "insert",
            },
        ]
    }
    document["processors"]["resource_detection"] = document["processors"].pop(
        "resourcedetection"
    )
    for pipeline in document["service"]["pipelines"].values():
        pipeline["processors"] = [
            "resource_detection" if item == "resourcedetection" else item
            for item in pipeline["processors"]
        ]
    document["service"]["pipelines"]["traces"]["processors"].append("resource/lemonade")
    document["service"]["pipelines"]["logs"]["processors"].append("resource/lemonade")
    base.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    common = [
        sys.executable,
        str(LEMONADE_SKILL / "scripts/render_collector_config.py"),
        "--base",
        str(base),
        "--output",
        str(output),
        "--deployment-environment",
        "ryzen-halo-dev",
    ]
    rejected = subprocess.run(common, text=True, capture_output=True, check=False)
    assert rejected.returncode != 0
    assert "--migrate-legacy-lemonade-renderer" in rejected.stderr
    accepted = subprocess.run(
        [*common, "--migrate-legacy-lemonade-renderer"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stderr
    migrated = load(output)
    assert "resource/lemonade" not in migrated["processors"]
    assert "resourcedetection" not in migrated["processors"]
    assert migrated["processors"]["resource_detection"]["detectors"] == [
        "env",
        "system",
    ]
    for pipeline in migrated["service"]["pipelines"].values():
        assert "resource/lemonade" not in (pipeline.get("processors") or [])


def test_client_fanout_preserves_splunk_resource_detection_id(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    document = base_config()
    document["processors"]["resource_detection"] = document["processors"].pop(
        "resourcedetection"
    )
    for pipeline in document["service"]["pipelines"].values():
        pipeline["processors"] = [
            "resource_detection" if item == "resourcedetection" else item
            for item in pipeline["processors"]
        ]
    base.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    result = render(base, output, "client-fanout")
    assert result.returncode == 0, result.stderr
    rendered = load(output)
    client_processors = rendered["service"]["pipelines"][
        "traces/lemonade_galileo_client"
    ]["processors"]
    assert "resource_detection" in client_processors
    assert "resourcedetection" not in client_processors


def test_lemonade_validation_resolves_receiver_bind_from_environment(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    write_base(base)
    rendered = subprocess.run(
        [
            sys.executable,
            str(LEMONADE_SKILL / "scripts/render_collector_config.py"),
            "--base",
            str(base),
            "--output",
            str(output),
            "--deployment-environment",
            "ryzen-halo-dev",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    document = load(output)
    document["receivers"]["otlp"]["protocols"]["http"]["endpoint"] = (
        "${SPLUNK_LISTEN_INTERFACE}:4318"
    )
    output.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    command = [
        "bash",
        str(LEMONADE_SKILL / "scripts/validate.sh"),
        "--collector-config",
        str(output),
    ]
    env = dict(os.environ)
    env["PATH"] = f"{Path(sys.executable).parent}:{env.get('PATH', '')}"
    env.pop("SPLUNK_LISTEN_INTERFACE", None)
    missing = subprocess.run(
        command, text=True, capture_output=True, check=False, env=env
    )
    assert missing.returncode != 0
    assert "set SPLUNK_LISTEN_INTERFACE" in missing.stderr
    env["SPLUNK_LISTEN_INTERFACE"] = "127.0.0.1"
    accepted = subprocess.run(
        command, text=True, capture_output=True, check=False, env=env
    )
    assert accepted.returncode == 0, accepted.stderr
    env["SPLUNK_LISTEN_INTERFACE"] = "0.0.0.0"
    exposed = subprocess.run(
        command, text=True, capture_output=True, check=False, env=env
    )
    assert exposed.returncode != 0
    assert "not loopback-bound" in exposed.stderr


def test_skill_assets_have_no_literal_credential_and_strict_client_privacy() -> None:
    env_template = (GALILEO_SKILL / "assets/galileo-collector.env.example").read_text(
        encoding="utf-8"
    )
    assert "GALILEO_API_KEY_FILE=" in env_template
    assert "GALILEO_API_KEY=\n" not in env_template
    for required in (
        "GALILEO_EXPECTED_ORIGIN=",
        "GALILEO_PROXY_URL=",
        "GALILEO_TINYPROXY_EVIDENCE_FILE=",
        "GALILEO_DESTINATION_FINGERPRINT=",
        "GALILEO_QUEUE_STORAGE_DIRECTORY=",
    ):
        assert required in env_template
    client = (GALILEO_SKILL / "assets/lemonade_openinference_client.py").read_text(
        encoding="utf-8"
    )
    for flag in (
        "hide_inputs=True",
        "hide_outputs=True",
        "hide_input_messages=True",
        "hide_output_messages=True",
        "hide_llm_invocation_parameters=True",
        "hide_llm_tools=True",
    ):
        assert flag in client
    assert 'lemonade.scheme == "http" and not lemonade_loopback' in client
    assert "LEMONADE_API_KEY_FILE" in client
    assert "except Exception" in client
    assert "inspect protected local logs" in client


def test_entrypoints_are_executable() -> None:
    for path in (
        GALILEO_SKILL / "scripts/setup.sh",
        GALILEO_SKILL / "scripts/validate.sh",
        GALILEO_SKILL / "scripts/render_collector_config.py",
        GALILEO_SKILL / "scripts/validate_collector_config.py",
        GALILEO_SKILL / "scripts/send_galileo_canary.py",
        GALILEO_SKILL / "scripts/galileo_readback.py",
        GALILEO_SKILL / "scripts/galileo_target_discovery.py",
        GALILEO_SKILL / "scripts/collector_runtime_wrapper.py",
        GALILEO_SKILL / "scripts/render_tinyproxy_filter.py",
        GALILEO_SKILL / "scripts/render_tinyproxy_evidence.py",
        LEMONADE_SKILL / "scripts/setup.sh",
        LEMONADE_SKILL / "scripts/validate.sh",
        LEMONADE_SKILL / "scripts/render_collector_config.py",
        LEMONADE_SKILL / "scripts/send_genai_canary.py",
        LEMONADE_SKILL / "scripts/splunk_trace_readback.py",
        LEMONADE_SKILL / "scripts/collector_evidence.py",
        LEMONADE_SKILL / "scripts/config_change_summary.py",
        LEMONADE_SKILL / "scripts/transactional_apply.py",
    ):
        assert path.stat().st_mode & stat.S_IXUSR, path


def test_collector_binary_validation_uses_validate_subcommand(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    clean = tmp_path / "clean.yaml"
    args_file = tmp_path / "args.txt"
    mock = tmp_path / "otelcol"
    write_base(base)
    assert render(base, clean, "splunk-only").returncode == 0
    mock.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$@" >"$ARGS_FILE"\n',
        encoding="utf-8",
    )
    mock.chmod(0o700)
    env = dict(os.environ)
    env["ARGS_FILE"] = str(args_file)
    env["PATH"] = f"{Path(sys.executable).parent}:{env.get('PATH', '')}"
    result = subprocess.run(
        [
            "bash",
            str(GALILEO_SKILL / "scripts/validate.sh"),
            "--collector-config",
            str(clean),
            "--mode",
            "splunk-only",
            "--collector-binary",
            str(mock),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "validate",
        f"--config={clean}",
    ]


def test_production_shell_requires_absolute_binary_and_clean_option_values(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    clean = tmp_path / "clean.yaml"
    mock = tmp_path / "otelcol"
    write_base(base)
    assert render(base, clean, "splunk-only").returncode == 0
    mock.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    mock.chmod(0o700)
    env = dict(os.environ)
    env["PATH"] = f"{Path(sys.executable).parent}:{env.get('PATH', '')}"

    relative = subprocess.run(
        [
            "bash",
            str(GALILEO_SKILL / "scripts/validate.sh"),
            "--collector-config",
            str(clean),
            "--mode",
            "splunk-only",
            "--collector-binary",
            "otelcol",
            "--production",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert relative.returncode != 0
    assert "absolute" in relative.stderr

    missing = subprocess.run(
        [
            "bash",
            str(GALILEO_SKILL / "scripts/validate.sh"),
            "--collector-config",
            str(clean),
            "--mode",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert missing.returncode == 2
    assert "requires a nonempty value" in missing.stderr
    assert "unbound variable" not in missing.stderr
