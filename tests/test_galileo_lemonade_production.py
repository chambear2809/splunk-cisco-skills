from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
import pytest

from tests.regression_helpers import REPO_ROOT


SKILL = REPO_ROOT / "skills/galileo-lemonade-instrumentation-setup"
RENDER = SKILL / "scripts/render_collector_config.py"
VALIDATE = SKILL / "scripts/validate_collector_config.py"


def base_document() -> dict:
    return {
        "receivers": {
            "otlp": {
                "protocols": {
                    "http": {"endpoint": "127.0.0.1:4318"},
                    "grpc": {"endpoint": "127.0.0.1:4317"},
                }
            }
        },
        "processors": {"memory_limiter": {}, "resourcedetection": {}, "batch": {}},
        "exporters": {"otlphttp/splunk": {"endpoint": "https://example.invalid"}},
        "extensions": {"health_check": {"endpoint": "127.0.0.1:13133"}},
        "service": {
            "extensions": ["health_check"],
            "pipelines": {
                "traces": {
                    "receivers": ["otlp"],
                    "processors": ["memory_limiter", "resourcedetection", "batch"],
                    "exporters": ["otlphttp/splunk"],
                }
            },
        },
    }


def write(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


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


def validate(path: Path, mode: str, *extra: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATE),
            "--collector-config",
            str(path),
            "--mode",
            mode,
            *extra,
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


@contextmanager
def production_target(tmp_path: Path):
    class ProbeProxy(BaseHTTPRequestHandler):
        def do_CONNECT(self) -> None:  # noqa: N802
            self.send_response(200 if self.path == "api.example.com:443" else 403)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), ProbeProxy)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    endpoint = "https://api.example.com/otel/traces"
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
    queue = tmp_path / "galileo-queue" / fingerprint
    queue.mkdir(parents=True)
    queue.chmod(0o700)
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

    def provenance(path: Path) -> dict[str, int | str]:
        info = path.stat()
        return {
            "path": str(path),
            "device": info.st_dev,
            "inode": info.st_ino,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "uid": info.st_uid,
            "mode": stat.S_IMODE(info.st_mode),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    proxy_url = f"http://127.0.0.1:{proxy.server_port}"
    evidence = {
        "schema_version": 1,
        "control": "tinyproxy-exact-connect-allowlist",
        "proxy_url": proxy_url,
        "allowed_connect_host": "api.example.com",
        "allowed_connect_port": 443,
        "binary": provenance(tinyproxy_binary),
        "config": provenance(proxy_config),
        "filter": provenance(proxy_filter),
    }
    environment = {
        **os.environ,
        "GALILEO_OTLP_TRACES_ENDPOINT": endpoint,
        "GALILEO_EXPECTED_ORIGIN": origin,
        "GALILEO_PROJECT_ID": "project-id",
        "GALILEO_LOG_STREAM_ID": "stream-id",
        "GALILEO_DESTINATION_FINGERPRINT": fingerprint,
        "GALILEO_QUEUE_STORAGE_DIRECTORY": str(queue),
        "GALILEO_PROXY_URL": proxy_url,
    }
    evidence_path = tmp_path / "tinyproxy-evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    evidence_path.chmod(0o400)
    environment["GALILEO_TINYPROXY_EVIDENCE_FILE"] = str(evidence_path)
    try:
        yield fingerprint, queue, environment, proxy_url
    finally:
        proxy.shutdown()
        thread.join(timeout=5)
        proxy.server_close()


def test_client_default_is_persistent_and_deletes_known_content(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "client.yaml"
    write(base, base_document())
    result = render(base, output, "client-fanout")
    assert result.returncode == 0, result.stderr
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    exporter = document["exporters"]["otlp_http/galileo_lemonade"]
    assert exporter["sending_queue"] == {
        "enabled": True,
        "num_consumers": 4,
        "queue_size": 268_435_456,
        "block_on_overflow": False,
        "sizer": "bytes",
        "storage": "file_storage/galileo_lemonade",
    }
    storage = document["extensions"]["file_storage/galileo_lemonade"]
    assert storage["compaction"]["directory"] == (
        "/var/lib/splunk-otel-collector/galileo-queue/compaction"
    )
    resource_actions = document["processors"]["resource/lemonade_galileo_client"][
        "attributes"
    ]
    assert resource_actions[0] == {
        "key": "service.name",
        "value": "lemonade-galileo-client",
        "action": "upsert",
    }
    privacy = str(document["processors"]["transform/lemonade_client_error_privacy"])
    for marker in (
        "delete_matching_keys",
        "input[.]value",
        "llm[.](input|output)_messages",
        "gen_ai[.]tool[.]call",
    ):
        assert marker in privacy
    assert validate(output, "client-fanout").returncode == 0


def test_client_privacy_covers_pinned_openinference_content_only(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "client.yaml"
    write(base, base_document())
    assert render(base, output, "client-fanout").returncode == 0
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    groups = document["processors"]["transform/lemonade_client_error_privacy"][
        "trace_statements"
    ]
    statements = next(item for item in groups if item["context"] == "span")[
        "statements"
    ]
    match = re.fullmatch(
        r'delete_matching_keys\(span[.]attributes, "(.*)"\)', statements[0]
    )
    assert match is not None
    pattern = re.compile(match.group(1))

    sensitive_keys = (
        "llm.input_messages.0.message.content",
        "llm.input_messages.0.message.contents.0.message_content.text",
        "llm.input_messages.0.message.contents.1.message_content.image",
        "llm.input_messages.0.message.contents.1.message_content.image.image.url",
        "llm.input_messages.0.message.contents.2.message_content.data",
        "llm.output_messages.1.message.contents.0.message_content.encrypted_content",
        "llm.output_messages.1.message.contents.0.message_content.signature",
        "llm.input_messages.0.message.function_call_arguments_json",
        "llm.output_messages.1.message.tool_calls.0.tool_call.function.arguments",
        "llm.output_messages.1.message.tool_calls.0.tool_call.reasoning_signature",
        "llm.prompts.0.prompt.text",
        "llm.choices.0.completion.text",
        "llm.prompt_template.template",
        "llm.prompt_template.variables.customer_name",
        "llm.function_call",
        "llm.invocation_parameters",
        "llm.tools.0.tool.json_schema",
        "embedding.invocation_parameters",
        "embedding.embeddings.0.embedding.text",
        "embedding.embeddings.0.embedding.vector",
        "input.value",
        "output.value",
        "tool.description",
        "tool.parameters",
        "tool.schema",
        "tool.output",
        "retrieval.documents.0.document.content",
        "retrieval.documents.0.document.metadata",
        "reranker.query",
        "reranker.input_documents.0.document.content",
        "reranker.output_documents.0.document.metadata",
        "metadata",
        "user.id",
        "tag.tags",
        "gen_ai.input.messages",
        "gen_ai.input.messages.0.content.text",
        "gen_ai.output.messages",
        "gen_ai.output.messages.0.parts.0.image.url",
        "gen_ai.system_instructions.0.content",
        "gen_ai.tool.definitions.0.description",
        "gen_ai.tool.description",
        "gen_ai.retrieval.documents.0.content",
        "gen_ai.retrieval.query.text",
        "audio.url",
        "audio.transcript",
        "image.url",
        "prompt.url",
        "llm.input_messages.0.message.contents.0.message_content.audio.url",
        "llm.output_messages.0.message.contents.0.message_content.audio.transcript",
    )
    for key in sensitive_keys:
        assert pattern.fullmatch(key), key

    retained_semantic_keys = (
        "llm.input_messages.0.message.role",
        "llm.input_messages.0.message.name",
        "llm.input_messages.0.message.contents.0.message_content.type",
        "llm.input_messages.0.message.contents.0.message_content.id",
        "llm.output_messages.1.message.tool_call_id",
        "llm.output_messages.1.message.tool_calls.0.tool_call.id",
        "llm.output_messages.1.message.tool_calls.0.tool_call.function.name",
        "llm.model_name",
        "llm.provider",
        "llm.prompt_template.version",
        "embedding.model_name",
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "gen_ai.usage.input_tokens",
        "retrieval.documents.0.document.id",
        "retrieval.documents.0.document.score",
        "reranker.model_name",
        "reranker.top_k",
        "session.id",
    )
    for key in retained_semantic_keys:
        assert pattern.fullmatch(key) is None, key

    event_statement = next(item for item in groups if item["context"] == "spanevent")[
        "statements"
    ][0]
    event_match = re.fullmatch(
        r'delete_matching_keys\(spanevent[.]attributes, "(.*)"\)',
        event_statement,
    )
    assert event_match is not None
    event_pattern = re.compile(event_match.group(1))
    for key in (
        "gen_ai.input.messages.0.content.text",
        "gen_ai.output.messages.0.content.image.url",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "llm.message.content.text",
        "tool.arguments.payload",
        "tool.result",
    ):
        assert event_pattern.fullmatch(key), key
    for key in (
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "gen_ai.input.messages.0.role",
        "gen_ai.usage.input_tokens",
        "llm.model_name",
        "tool.name",
    ):
        assert event_pattern.fullmatch(key) is None, key

    resource_statement = next(item for item in groups if item["context"] == "resource")[
        "statements"
    ][0]
    assert match.group(1) in resource_statement
    for required in (
        'set(span.attributes["input.value"], "[REDACTED]")',
        'set(span.attributes["output.value"], "[REDACTED]")',
        'set(span.attributes["gen_ai.tool.call.arguments"], "[REDACTED]")',
        'set(span.attributes["gen_ai.tool.call.result"], "[REDACTED]")',
    ):
        assert any(required in statement for statement in statements)


def test_both_galileo_pipelines_end_with_exact_route_guard(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    write(base, base_document())
    for mode, pipeline_name in (
        ("client-fanout", "traces/lemonade_galileo_client"),
        ("server-fanout", "traces/lemonade_galileo_server"),
    ):
        output = tmp_path / f"{mode}.yaml"
        assert render(base, output, mode).returncode == 0
        document = yaml.safe_load(output.read_text(encoding="utf-8"))
        processors = document["service"]["pipelines"][pipeline_name]["processors"]
        route_guard = "transform/lemonade_galileo_route_guard"
        assert route_guard in processors
        batch_indexes = [
            index
            for index, value in enumerate(processors)
            if value.split("/", 1)[0] == "batch"
        ]
        assert processors.index(route_guard) < min(batch_indexes)
        guard = document["processors"][route_guard]
        assert guard["error_mode"] == "propagate"
        assert [item["context"] for item in guard["trace_statements"]] == [
            "resource",
            "span",
            "spanevent",
        ]
        assert all(
            "(?i)^galileo[.]" in item["statements"][0]
            for item in guard["trace_statements"]
        )
        assert validate(output, mode).returncode == 0


def test_validator_rejects_privacy_policy_missing_one_pinned_content_key(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "client.yaml"
    write(base, base_document())
    assert render(base, output, "client-fanout").returncode == 0
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    statements = document["processors"]["transform/lemonade_client_error_privacy"][
        "trace_statements"
    ][0]["statements"]
    statements[0] = statements[0].replace(
        "text|data|encrypted_content|signature", "text|data|signature"
    )
    write(output, document)

    rejected = validate(output, "client-fanout")
    assert rejected.returncode != 0
    assert "exact policy" in rejected.stderr


def test_validator_rejects_default_or_tampered_compaction_directory(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "client.yaml"
    queue_directory = tmp_path / "private-queue"
    write(base, base_document())
    assert (
        render(
            base,
            output,
            "client-fanout",
            "--queue-storage-directory",
            str(queue_directory),
        ).returncode
        == 0
    )
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    storage = document["extensions"]["file_storage/galileo_lemonade"]
    assert storage["compaction"]["directory"] == str(queue_directory / "compaction")
    storage["compaction"]["directory"] = "/var/lib/otelcol"
    write(output, document)

    rejected = validate(
        output,
        "client-fanout",
        "--queue-storage-directory",
        str(queue_directory),
    )
    assert rejected.returncode != 0
    assert "file storage does not match policy" in rejected.stderr


def test_validator_rejects_client_service_name_insert_action(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "client.yaml"
    write(base, base_document())
    assert render(base, output, "client-fanout").returncode == 0
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    resource_actions = document["processors"]["resource/lemonade_galileo_client"][
        "attributes"
    ]
    resource_actions[0]["action"] = "insert"
    write(output, document)

    rejected = validate(output, "client-fanout")
    assert rejected.returncode != 0
    assert "client resource processor does not match exact policy" in rejected.stderr


def test_validator_rejects_inert_or_modified_managed_components(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "client.yaml"
    write(base, base_document())
    assert render(base, output, "client-fanout").returncode == 0
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    document["processors"]["transform/lemonade_client_error_privacy"] = {
        "note": "status.message exception.stacktrace delete_matching_keys"
    }
    write(output, document)
    rejected = validate(output, "client-fanout")
    assert rejected.returncode != 0
    assert "exact policy" in rejected.stderr


def test_duplicate_galileo_route_from_native_receiver_fails_closed(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "server.yaml"
    document = base_document()
    document["exporters"]["otlp_http/galileo_existing"] = {
        "traces_endpoint": "${env:GALILEO_OTLP_TRACES_ENDPOINT}",
        "headers": {
            "Galileo-API-Key": "${env:GALILEO_API_KEY}",
            "projectid": "${env:GALILEO_PROJECT_ID}",
            "logstreamid": "${env:GALILEO_LOG_STREAM_ID}",
        },
    }
    document["service"]["pipelines"]["traces/duplicate"] = {
        "receivers": ["otlp"],
        "processors": ["batch"],
        "exporters": ["otlp_http/galileo_existing"],
    }
    write(base, document)
    rejected = render(base, output, "server-fanout")
    assert rejected.returncode != 0
    assert "another Galileo-like exporter" in rejected.stderr
    assert not output.exists()


def test_opaque_galileo_named_exporter_fails_without_shape(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "output.yaml"
    document = base_document()
    document["exporters"]["otlp_http/GaLiLeO_shadow"] = {
        "endpoint": "https://opaque.example.invalid"
    }
    write(base, document)
    for mode in ("client-fanout", "server-fanout", "splunk-only"):
        rejected = render(base, output, mode)
        assert rejected.returncode != 0
        assert "Galileo-like" in rejected.stderr
        assert not output.exists()


def test_dedicated_client_receiver_cannot_feed_an_extra_pipeline(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    rendered = tmp_path / "client.yaml"
    output = tmp_path / "rerendered.yaml"
    write(base, base_document())
    assert render(base, rendered, "client-fanout").returncode == 0
    document = yaml.safe_load(rendered.read_text(encoding="utf-8"))
    document["service"]["pipelines"]["traces/shadow"] = {
        "receivers": ["otlp/lemonade_galileo_client"],
        "processors": ["batch"],
        "exporters": ["otlphttp/splunk"],
    }
    write(rendered, document)
    rejected_render = render(rendered, output, "client-fanout")
    assert rejected_render.returncode != 0
    rejected_validate = validate(rendered, "client-fanout")
    assert rejected_validate.returncode != 0
    assert "dedicated receiver" in rejected_validate.stderr


def test_splunk_only_rejects_custom_galileo_shaped_route(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "clean.yaml"
    document = base_document()
    document["exporters"]["otlp_http/opaque"] = {
        "endpoint": "https://opaque.invalid/otel/traces",
        "headers": {"Galileo-API-Key": "${env:OPAQUE_KEY}"},
    }
    document["service"]["pipelines"]["traces/custom"] = {
        "receivers": ["otlp"],
        "processors": ["batch"],
        "exporters": ["otlp_http/opaque"],
    }
    write(base, document)
    rejected = render(base, output, "splunk-only")
    assert rejected.returncode != 0
    rejected_validation = validate(base, "splunk-only")
    assert rejected_validation.returncode != 0
    assert "Galileo-like" in rejected_validation.stderr


def test_rerender_rejects_managed_pipeline_drift(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    rendered = tmp_path / "client.yaml"
    output = tmp_path / "output.yaml"
    write(base, base_document())
    assert render(base, rendered, "client-fanout").returncode == 0
    document = yaml.safe_load(rendered.read_text(encoding="utf-8"))
    document["processors"]["debug/owned-drift"] = {}
    document["service"]["pipelines"]["traces/lemonade_galileo_client"][
        "processors"
    ].insert(-1, "debug/owned-drift")
    write(rendered, document)
    rejected = render(rendered, output, "splunk-only")
    assert rejected.returncode != 0
    assert "unknown shape" in rejected.stderr
    assert not output.exists()


def test_managed_name_collision_without_managed_pipeline_fails_closed(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "clean.yaml"
    document = base_document()
    document["exporters"]["otlp_http/galileo_lemonade"] = {"endpoint": "https://other"}
    write(base, document)
    rejected = render(base, output, "splunk-only")
    assert rejected.returncode != 0
    assert "collision or partial prior render" in rejected.stderr


@pytest.mark.skipif(
    sys.platform.startswith("linux"),
    reason="positive integration requires an installed root-owned evidence fixture",
)
def test_production_gate_requires_tinyproxy_contract_and_persistent_queue(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "client.yaml"
    with production_target(tmp_path) as (
        fingerprint,
        queue,
        environment,
        proxy_url,
    ):
        write(base, base_document())
        assert (
            render(
                base,
                output,
                "client-fanout",
                "--galileo-proxy-url",
                proxy_url,
                "--production",
                "--destination-fingerprint",
                fingerprint,
                "--queue-storage-directory",
                str(queue),
            ).returncode
            == 0
        )
        missing = validate(
            output,
            "client-fanout",
            "--production",
            "--galileo-proxy-url",
            proxy_url,
            "--destination-fingerprint",
            fingerprint,
            "--queue-storage-directory",
            str(queue),
            env={
                key: value
                for key, value in environment.items()
                if key != "GALILEO_TINYPROXY_EVIDENCE_FILE"
            },
        )
        assert missing.returncode != 0
        assert "EVIDENCE_FILE" in missing.stderr
        accepted = validate(
            output,
            "client-fanout",
            "--production",
            "--galileo-proxy-url",
            proxy_url,
            "--destination-fingerprint",
            fingerprint,
            "--queue-storage-directory",
            str(queue),
            env=environment,
        )
        assert accepted.returncode == 0, accepted.stderr

    memory = tmp_path / "memory.yaml"
    assert (
        render(base, memory, "client-fanout", "--queue-policy", "memory").returncode
        == 0
    )
    rejected = validate(
        memory,
        "client-fanout",
        "--queue-policy",
        "memory",
        "--production",
    )
    assert rejected.returncode != 0
    assert "persistent" in rejected.stderr


def test_production_render_requires_fingerprinted_queue_namespace(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "client.yaml"
    with production_target(tmp_path) as (fingerprint, queue, _environment, proxy_url):
        write(base, base_document())
        missing = render(base, output, "client-fanout", "--production")
        assert missing.returncode != 0
        assert "destination-fingerprint" in missing.stderr
        reused = render(
            base,
            output,
            "client-fanout",
            "--galileo-proxy-url",
            proxy_url,
            "--production",
            "--destination-fingerprint",
            fingerprint,
            "--queue-storage-directory",
            str(queue.parent / "shared"),
        )
        assert reused.returncode != 0
        assert "must end with" in reused.stderr


@pytest.mark.skipif(
    sys.platform.startswith("linux"),
    reason="positive integration requires an installed root-owned evidence fixture",
)
def test_production_selector_kind_must_match_rendered_routing(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "client.yaml"
    with production_target(tmp_path) as (
        fingerprint,
        queue,
        environment,
        proxy_url,
    ):
        write(base, base_document())
        rendered = render(
            base,
            output,
            "client-fanout",
            "--routing",
            "names",
            "--galileo-proxy-url",
            proxy_url,
            "--production",
            "--destination-fingerprint",
            fingerprint,
            "--queue-storage-directory",
            str(queue),
        )
        assert rendered.returncode == 0, rendered.stderr

        rejected = validate(
            output,
            "client-fanout",
            "--production",
            "--galileo-proxy-url",
            proxy_url,
            "--destination-fingerprint",
            fingerprint,
            "--queue-storage-directory",
            str(queue),
            env=environment,
        )
        assert rejected.returncode != 0
        assert "selector kind" in rejected.stderr


@pytest.mark.skipif(
    sys.platform.startswith("linux"),
    reason="positive integration requires an installed root-owned evidence fixture",
)
def test_server_production_requires_risk_acceptance_and_loopback(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "server.yaml"
    with production_target(tmp_path) as (
        fingerprint,
        queue,
        environment,
        proxy_url,
    ):
        write(base, base_document())
        assert (
            render(
                base,
                output,
                "server-fanout",
                "--galileo-proxy-url",
                proxy_url,
                "--production",
                "--destination-fingerprint",
                fingerprint,
                "--queue-storage-directory",
                str(queue),
            ).returncode
            == 0
        )
        rejected = validate(
            output,
            "server-fanout",
            "--production",
            "--galileo-proxy-url",
            proxy_url,
            "--destination-fingerprint",
            fingerprint,
            "--queue-storage-directory",
            str(queue),
            env=environment,
        )
        assert rejected.returncode != 0
        assert "shared" in rejected.stderr
        accepted = validate(
            output,
            "server-fanout",
            "--production",
            "--galileo-proxy-url",
            proxy_url,
            "--allow-server-shared-receiver",
            "--destination-fingerprint",
            fingerprint,
            "--queue-storage-directory",
            str(queue),
            env=environment,
        )
        assert accepted.returncode == 0, accepted.stderr

        document = yaml.safe_load(output.read_text(encoding="utf-8"))
        document["receivers"]["otlp"]["protocols"]["http"]["endpoint"] = "0.0.0.0:4318"
        write(output, document)
        exposed = validate(
            output,
            "server-fanout",
            "--galileo-proxy-url",
            proxy_url,
            "--queue-storage-directory",
            str(queue),
            env=dict(os.environ),
        )
        assert exposed.returncode != 0
        assert "loopback" in exposed.stderr


def test_server_rejects_receiver_without_explicit_loopback_bind(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "server.yaml"
    document = base_document()
    document["receivers"]["kafka"] = {"brokers": ["remote.example:9092"]}
    document["service"]["pipelines"]["traces"]["receivers"] = ["kafka"]
    write(base, document)
    assert render(base, output, "server-fanout").returncode == 0
    rejected = validate(output, "server-fanout", "--allow-server-shared-receiver")
    assert rejected.returncode != 0
    assert "no explicit bind endpoint" in rejected.stderr
