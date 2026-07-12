from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/galileo-lemonade-instrumentation-setup"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://127.0.0.1:4318/v1/traces",
        "http://127.0.0.1/v1/traces",
        "http://127.0.0.1:4318/other/v1/traces",
        "http://127.0.0.1:4318/v1/traces?next=https://example.com",
        "http://user:pass@127.0.0.1:4318/v1/traces",
        "http://@127.0.0.1:4318/v1/traces",
        "http://127.0.0.1:/v1/traces",
        "http://127.0.0.1:4318/%76%31/traces",
        "http://127.0.0.1:4318/v1/traces\\ignored",
        "http://127.0.0.1:4318/v1/traces\nignored",
    ),
)
def test_canary_rejects_noncanonical_receiver_urls(endpoint: str) -> None:
    module = load_module(
        "galileo_canary_url_test_" + hashlib.sha256(endpoint.encode()).hexdigest()[:8],
        SKILL / "scripts/send_galileo_canary.py",
    )
    assert not module.loopback_http(endpoint)
    assert module.loopback_http("http://127.0.0.1:4318/v1/traces")


class RedirectHandler(BaseHTTPRequestHandler):
    target: str = ""

    def do_POST(self) -> None:  # noqa: N802
        self.send_response(307)
        self.send_header("Location", type(self).target)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class RedirectTargetHandler(BaseHTTPRequestHandler):
    requests = 0

    def do_POST(self) -> None:  # noqa: N802
        type(self).requests += 1
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_canary_rejects_redirect_without_reflecting_location() -> None:
    target = ThreadingHTTPServer(("127.0.0.1", 0), RedirectTargetHandler)
    redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    secret_marker = "must-not-appear-in-error"
    RedirectTargetHandler.requests = 0
    RedirectHandler.target = (
        f"http://127.0.0.1:{target.server_port}/v1/traces?marker={secret_marker}"
    )
    threads = [
        threading.Thread(target=target.serve_forever, daemon=True),
        threading.Thread(target=redirect.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(SKILL / "scripts/send_galileo_canary.py"),
                "--endpoint",
                f"http://127.0.0.1:{redirect.server_port}/v1/traces",
            ],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "HTTP_PROXY": "http://127.0.0.1:1"},
        )
    finally:
        redirect.shutdown()
        target.shutdown()
        for thread in threads:
            thread.join(timeout=5)
        redirect.server_close()
        target.server_close()
    assert result.returncode != 0
    assert RedirectTargetHandler.requests == 0
    assert secret_marker not in result.stdout + result.stderr


def protected_secret(tmp_path: Path) -> Path:
    secret = tmp_path / "galileo-key"
    secret.write_text("test-only-value\n", encoding="utf-8")
    secret.chmod(0o600)
    return secret


def wrapper_environment(tmp_path: Path) -> dict[str, str]:
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
    queue = tmp_path / fingerprint
    queue.mkdir(exist_ok=True)
    queue.chmod(0o700)
    environment = dict(os.environ)
    environment.update(
        {
            "GALILEO_API_KEY_FILE": str(protected_secret(tmp_path)),
            "GALILEO_OTLP_TRACES_ENDPOINT": endpoint,
            "GALILEO_EXPECTED_ORIGIN": origin,
            "GALILEO_PROJECT_ID": "project-id",
            "GALILEO_LOG_STREAM_ID": "stream-id",
            "GALILEO_DESTINATION_FINGERPRINT": fingerprint,
            "GALILEO_QUEUE_STORAGE_DIRECTORY": str(queue),
        }
    )
    environment.pop("GALILEO_API_KEY", None)
    return configure_control_evidence(tmp_path, environment, "egress-allowlist")


def configure_control_evidence(
    tmp_path: Path, environment: dict[str, str], control: str
) -> dict[str, str]:
    environment["GALILEO_REDIRECT_CONTROL"] = control
    origin = environment["GALILEO_EXPECTED_ORIGIN"]
    evidence: dict[str, object] = {
        "schema_version": 1,
        "control": control,
        "destination_fingerprint": environment["GALILEO_DESTINATION_FINGERPRINT"],
        "expected_origin_sha256": hashlib.sha256(origin.encode()).hexdigest(),
    }
    if control == "egress-allowlist":
        evidence["control_contract"] = "origin-only-egress"
    elif control == "no-redirect-proxy":
        proxy = "http://127.0.0.1:18080"
        environment["HTTPS_PROXY"] = proxy
        evidence.update(
            {
                "control_contract": "reject-redirects",
                "https_proxy_sha256": hashlib.sha256(proxy.encode()).hexdigest(),
            }
        )
    else:
        binary = Path(sys.executable).resolve()
        evidence.update(
            {
                "control_contract": "redirects-disabled",
                "redirect_capability_test": "passed",
                "collector_binary": str(binary),
                "collector_binary_sha256": hashlib.sha256(
                    binary.read_bytes()
                ).hexdigest(),
            }
        )
    path = tmp_path / f"{control}-evidence.json"
    if path.exists():
        path.unlink()
    path.write_text(json.dumps(evidence), encoding="utf-8")
    path.chmod(0o400)
    environment["GALILEO_REDIRECT_CONTROL_EVIDENCE_FILE"] = str(path)
    return environment


def run_wrapper(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts/collector_runtime_wrapper.py"),
            "--check",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


def test_wrapper_prints_only_nonsecret_destination_fingerprint(tmp_path: Path) -> None:
    environment = wrapper_environment(tmp_path)
    expected = environment["GALILEO_DESTINATION_FINGERPRINT"]
    for name in (
        "GALILEO_API_KEY_FILE",
        "GALILEO_REDIRECT_CONTROL",
        "GALILEO_REDIRECT_CONTROL_EVIDENCE_FILE",
        "GALILEO_QUEUE_STORAGE_DIRECTORY",
    ):
        environment.pop(name, None)
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts/collector_runtime_wrapper.py"),
            "--print-destination-fingerprint",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
    assert environment["GALILEO_OTLP_TRACES_ENDPOINT"] not in result.stdout
    assert environment["GALILEO_PROJECT_ID"] not in result.stdout
    assert environment["GALILEO_LOG_STREAM_ID"] not in result.stdout


def test_wrapper_rejects_target_change_with_old_fingerprint(tmp_path: Path) -> None:
    environment = wrapper_environment(tmp_path)
    environment["GALILEO_LOG_STREAM_ID"] = "different-stream"
    rejected = run_wrapper(environment)
    assert rejected.returncode != 0
    assert "DESTINATION_FINGERPRINT does not match" in rejected.stderr
    assert "different-stream" not in rejected.stderr


def test_wrapper_requires_origin_pin_and_control_evidence(tmp_path: Path) -> None:
    environment = wrapper_environment(tmp_path)
    environment["GALILEO_EXPECTED_ORIGIN"] = "https://other.example.com"
    wrong_origin = run_wrapper(environment)
    assert wrong_origin.returncode != 0
    assert "does not match" in wrong_origin.stderr

    environment = wrapper_environment(tmp_path)
    environment["GALILEO_PROXY_URL"] = "http://127.0.0.1:18888"
    environment.pop("GALILEO_TINYPROXY_EVIDENCE_FILE", None)
    no_evidence = run_wrapper(environment)
    assert no_evidence.returncode != 0
    assert "EVIDENCE_FILE" in no_evidence.stderr


def test_wrapper_strips_ambient_proxy_and_bypass_environment() -> None:
    module = load_module(
        "galileo_wrapper_proxy_environment_test",
        SKILL / "scripts/collector_runtime_wrapper.py",
    )
    source = {
        "HTTPS_PROXY": "http://reviewed.proxy:8080",
        "https_proxy": "http://unreviewed.proxy:8080",
        "HTTP_PROXY": "http://unreviewed.proxy:8080",
        "ALL_PROXY": "socks5://unreviewed.proxy:1080",
        "NO_PROXY": "api.example.com",
        "KEEP": "value",
    }
    direct = module.restricted_transport_environment(source, "egress-allowlist")
    assert direct == {"KEEP": "value"}
    proxied = module.restricted_transport_environment(source, "no-redirect-proxy")
    assert proxied == {"KEEP": "value"}


def test_linux_redirect_evidence_rejects_user_owned_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module(
        "galileo_wrapper_linux_evidence_test",
        SKILL / "scripts/collector_runtime_wrapper.py",
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    evidence.chmod(0o400)
    monkeypatch.setattr(module.sys, "platform", "linux")
    with pytest.raises(ValueError, match="untrusted ancestor|protected"):
        module.read_protected_json(evidence)


@pytest.mark.skipif(
    sys.platform.startswith("linux"),
    reason="queue integration requires an installed root-owned evidence fixture",
)
def test_wrapper_queue_preflight_rejects_permissions_and_database_links(
    tmp_path: Path,
) -> None:
    module = load_module(
        "galileo_wrapper_queue_validation_test",
        SKILL / "scripts/collector_runtime_wrapper.py",
    )
    environment = wrapper_environment(tmp_path)
    queue = Path(environment["GALILEO_QUEUE_STORAGE_DIRECTORY"])
    fingerprint = environment["GALILEO_DESTINATION_FINGERPRINT"]
    queue.chmod(0o755)
    with pytest.raises(ValueError, match="mode 0700"):
        module.validate_queue_directory(str(queue), fingerprint)

    queue.chmod(0o700)
    database = queue / "queue.db"
    database.write_text("test", encoding="utf-8")
    database.chmod(0o644)
    with pytest.raises(ValueError, match="mode 0600"):
        module.validate_queue_directory(str(queue), fingerprint)


@pytest.mark.skipif(
    sys.platform.startswith("linux"),
    reason="positive integration requires an installed root-owned evidence fixture",
)
def test_wrapper_requires_explicit_loopback_proxy_contract(tmp_path: Path) -> None:
    del tmp_path
    module = load_module(
        "galileo_wrapper_explicit_proxy_test",
        SKILL / "scripts/collector_runtime_wrapper.py",
    )
    assert module.validate_galileo_proxy_url("http://127.0.0.1:18888") == (
        "http://127.0.0.1:18888",
        "127.0.0.1",
        18888,
    )
    for invalid in ("", "http://localhost:18888", "https://127.0.0.1:18888"):
        with pytest.raises(ValueError, match="GALILEO_PROXY_URL"):
            module.validate_galileo_proxy_url(invalid)


def test_custom_collector_provenance_rejects_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module(
        "galileo_wrapper_provenance_test",
        SKILL / "scripts/collector_runtime_wrapper.py",
    )
    monkeypatch.setattr(module.sys, "platform", "darwin")
    binary = tmp_path / "collector"
    binary.write_bytes(b"first reviewed collector")
    binary.chmod(0o700)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    descriptor, provenance = module.open_trusted_executable(binary, digest)
    os.close(descriptor)

    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"second collector payload")
    replacement.chmod(0o700)
    os.replace(replacement, binary)
    with pytest.raises(ValueError, match="evidence does not match|changed before"):
        module.open_trusted_executable(
            binary,
            digest,
            expected_provenance=provenance,
        )


def test_pinned_collector_command_opens_only_the_reviewed_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module(
        "galileo_wrapper_pinned_command_test",
        SKILL / "scripts/collector_runtime_wrapper.py",
    )
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module, "descriptor_exec_supported", lambda: True)
    binary = tmp_path / "collector"
    binary.write_bytes(b"reviewed collector")
    binary.chmod(0o700)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    environment = {
        "GALILEO_COLLECTOR_BINARY": str(binary),
        "GALILEO_COLLECTOR_BINARY_SHA256": digest,
    }
    descriptor = module.open_pinned_collector_command([str(binary)], environment)
    os.close(descriptor)
    with pytest.raises(ValueError, match="does not match"):
        module.open_pinned_collector_command(["/usr/bin/other"], environment)


def test_linux_custom_collector_requires_trusted_path_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module(
        "galileo_wrapper_trusted_path_test",
        SKILL / "scripts/collector_runtime_wrapper.py",
    )
    binary = tmp_path / "collector"
    binary.write_bytes(b"reviewed collector")
    binary.chmod(0o700)
    monkeypatch.setattr(module.sys, "platform", "linux")
    with pytest.raises(ValueError, match="root-owned|group/other-writable"):
        module.trusted_executable_path(binary)


def test_descriptor_exec_preserves_collector_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module(
        "galileo_wrapper_descriptor_exec_test",
        SKILL / "scripts/collector_runtime_wrapper.py",
    )
    observed: dict[str, object] = {}

    def fake_execve(
        descriptor: int, arguments: list[str], environment: dict[str, str]
    ) -> None:
        observed.update(
            descriptor=descriptor,
            arguments=list(arguments),
            environment=dict(environment),
        )

    monkeypatch.setattr(module.os, "execve", fake_execve)
    monkeypatch.setattr(module.os, "supports_fd", {fake_execve})
    arguments = [
        "/usr/bin/otelcol",
        "--config=/etc/otel/config.yaml",
        "--feature-gates=x",
    ]
    environment = {"GALILEO_API_KEY": "not-emitted", "KEEP": "value"}
    module.descriptor_exec(41, arguments, environment)
    assert observed == {
        "descriptor": 41,
        "arguments": arguments,
        "environment": environment,
    }


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("GALILEO_PROJECT_ID", " project-id"),
        ("GALILEO_PROJECT_ID", "project\\id"),
        ("GALILEO_PROJECT_ID", "project\nid"),
        ("GALILEO_LOG_STREAM_ID", "x" * 1025),
    ),
)
def test_wrapper_rejects_unsafe_selectors(
    tmp_path: Path, name: str, value: str
) -> None:
    environment = wrapper_environment(tmp_path)
    environment[name] = value
    rejected = run_wrapper(environment)
    assert rejected.returncode != 0
    assert value not in rejected.stderr


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://api.example.com:0/otel/traces",
        "https://api.example.com:99999/otel/traces",
        "https://@api.example.com/otel/traces",
        "https://api.example.com:/otel/traces",
        "https://bad_host.example/otel/traces",
        "https://api.example.com/otel/%74races",
        "https://api.example.com/otel/traces\\ignored",
        "https://api.example.com/otel/traces?redirect=x",
    ),
)
def test_wrapper_rejects_unsafe_exporter_endpoints(
    tmp_path: Path, endpoint: str
) -> None:
    environment = wrapper_environment(tmp_path)
    environment["GALILEO_OTLP_TRACES_ENDPOINT"] = endpoint
    assert run_wrapper(environment).returncode != 0


def test_readback_recursively_scans_content_and_hashes_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module(
        "galileo_recursive_privacy_test",
        SKILL / "scripts/galileo_readback.py",
    )
    raw_name = "trace-name-that-must-not-be-emitted"
    detail = {
        "id": "galileo-id",
        "name": raw_name,
        "is_complete": True,
        "input": "[REDACTED]",
        "output": "[REDACTED]",
        "metadata": {
            "request": {"messages": [{"role": "user", "content": "[REDACTED]"}]}
        },
        "protect_status": {"error_message": "platform-protection-diagnostic"},
        "protect_status_error_message": "platform-protection-diagnostic",
        "spans": [{"type": "agent", "attributes": {"input.value": "[REDACTED]"}}],
    }
    monkeypatch.setattr(module, "request_json", lambda *_args, **_kwargs: detail)
    args = type(
        "Args",
        (),
        {
            "api_base": "https://api.example.com",
            "project_id": "project-id",
            "require_span_type": ["agent"],
            "require_redacted_content": True,
        },
    )()
    summary = module.get_trace_summary(args, "not-printed", {"id": "galileo-id"})
    serialized = json.dumps(summary, sort_keys=True)
    assert raw_name not in serialized
    assert summary["name_sha256"] == hashlib.sha256(raw_name.encode()).hexdigest()
    assert summary["recursive_content_states"]["present"] == 0

    detail["metadata"]["request"]["messages"][0]["content"] = "sensitive-value"
    with pytest.raises(RuntimeError, match="non-redacted content"):
        module.get_trace_summary(args, "not-printed", {"id": "galileo-id"})
    detail["metadata"]["request"]["messages"][0]["content"] = "[REDACTED]"
    detail["spans"][0]["events"] = [
        {"attributes": {"exception.message": "sensitive-exception"}}
    ]
    with pytest.raises(RuntimeError, match="non-redacted content"):
        module.get_trace_summary(args, "not-printed", {"id": "galileo-id"})


@pytest.mark.parametrize(
    "value, expected",
    [
        ([{"role": "user", "content": ""}], "absent"),
        ({"role": "assistant", "content": ""}, "absent"),
        ([{"role": "user", "content": "[REDACTED]"}], "redacted"),
        (
            json.dumps(
                [
                    {
                        "role": "user",
                        "content": "[REDACTED]",
                        "tool_call_id": None,
                        "tool_calls": None,
                    }
                ]
            ),
            "redacted",
        ),
        ([{"role": "user", "content": "sensitive-value"}], "present"),
        (
            [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "arguments": "sensitive-value",
                            },
                        }
                    ],
                }
            ],
            "present",
        ),
    ],
)
def test_readback_classifies_message_structure_without_treating_roles_as_content(
    value: object, expected: str
) -> None:
    module = load_module(
        "galileo_structured_privacy_"
        + hashlib.sha256(repr(value).encode()).hexdigest()[:8],
        SKILL / "scripts/galileo_readback.py",
    )
    assert module.structured_content_state(value) == expected


def test_readback_search_follows_all_pages() -> None:
    module = load_module(
        "galileo_paginated_trace_search_test",
        SKILL / "scripts/galileo_readback.py",
    )
    documents = iter(
        [
            {"records": [], "next_starting_token": 100},
            {
                "records": [
                    {
                        "id": "galileo-id",
                        "external_id": "0123456789abcdef0123456789abcdef",
                        "name": "agent-canary",
                        "created_at": "2026-07-11T12:00:01Z",
                        "is_complete": True,
                    }
                ],
                "next_starting_token": None,
            },
        ]
    )
    starting_tokens: list[int] = []

    def request_json(args, key, method, endpoint, payload):  # noqa: ANN001
        del args, key, method, endpoint
        starting_tokens.append(payload["starting_token"])
        return next(documents)

    module.request_json = request_json
    args = type(
        "Args",
        (),
        {
            "api_base": "https://api.example.com",
            "project_id": "project-id",
            "log_stream_id": "stream-id",
            "limit": 100,
            "expected_trace_id": "0123456789abcdef0123456789abcdef",
            "expected_name": "agent-canary",
            "created_after_value": module.parse_timestamp("2026-07-11T12:00:00Z"),
        },
    )()
    record = module.search(args, "not-printed")
    assert record is not None
    assert record["id"] == "galileo-id"
    assert starting_tokens == [0, 100]


def test_readback_rejects_forbidden_canary_content_without_echoing_it() -> None:
    module = load_module(
        "galileo_forbidden_canary_test",
        SKILL / "scripts/galileo_readback.py",
    )
    marker = "synthetic-private-canary-content"
    with pytest.raises(RuntimeError, match="forbidden canary content") as exc_info:
        module.reject_forbidden_content({"nested": [{"content": marker}]}, (marker,))
    assert marker not in str(exc_info.value)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("user_metadata", {"customer": "sensitive-value"}),
        ("dataset_metadata", {"source": "sensitive-value"}),
        ("tags", ["sensitive-value"]),
        ("progress_message", "sensitive-value"),
        ("error_message", "sensitive-value"),
        ("files", [{"name": "sensitive-value.txt"}]),
        ("gen_ai.prompt.0.content.0.text", "sensitive-value"),
        (
            "gen_ai.prompt.0.content.1.image.url",
            "https://private.example/sensitive-value.png",
        ),
    ),
)
def test_readback_rejects_documented_and_flattened_sensitive_fields(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    module = load_module(
        "galileo_documented_privacy_test_"
        + hashlib.sha256(field.encode()).hexdigest()[:8],
        SKILL / "scripts/galileo_readback.py",
    )
    detail = {
        "id": "galileo-id",
        "name": "privacy-canary",
        "is_complete": True,
        "input": "[REDACTED]",
        "output": "[REDACTED]",
        "spans": [{"type": "agent", "attributes": {field: value}}],
    }
    monkeypatch.setattr(module, "request_json", lambda *_args, **_kwargs: detail)
    args = type(
        "Args",
        (),
        {
            "api_base": "https://api.example.com",
            "project_id": "project-id",
            "require_span_type": ["agent"],
            "require_redacted_content": True,
        },
    )()

    with pytest.raises(RuntimeError, match="non-redacted content"):
        module.get_trace_summary(args, "not-printed", {"id": "galileo-id"})


def test_readback_rejects_otlp_key_value_array_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module(
        "galileo_otlp_kv_privacy_test",
        SKILL / "scripts/galileo_readback.py",
    )
    detail = {
        "id": "galileo-id",
        "name": "privacy-canary",
        "is_complete": True,
        "input": "[REDACTED]",
        "output": "[REDACTED]",
        "spans": [
            {
                "type": "agent",
                "attributes": [
                    {
                        "key": "input.value",
                        "value": {"stringValue": "sensitive-value"},
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(module, "request_json", lambda *_args, **_kwargs: detail)
    args = type(
        "Args",
        (),
        {
            "api_base": "https://api.example.com",
            "project_id": "project-id",
            "require_span_type": ["agent"],
            "require_redacted_content": True,
        },
    )()

    with pytest.raises(RuntimeError, match="non-redacted content"):
        module.get_trace_summary(args, "not-printed", {"id": "galileo-id"})


def test_readback_recognizes_nested_image_url_as_sensitive() -> None:
    module = load_module(
        "galileo_nested_image_privacy_test",
        SKILL / "scripts/galileo_readback.py",
    )
    states = module.recursive_content_states(
        {"message": {"image": {"url": "https://private.example/image.png"}}}
    )
    assert states["present"] == 1


def test_reference_client_declares_hardened_transports_and_pinned_runtime() -> None:
    client = (SKILL / "assets/lemonade_openinference_client.py").read_text(
        encoding="utf-8"
    )
    for required_source in (
        "trust_env=False",
        "follow_redirects=False",
        'kwargs["allow_redirects"] = False',
        "self.trust_env = False",
        "session=session",
        "O_NOFOLLOW",
        "MAX_SECRET_BYTES + 1",
        "hide_input_images=True",
        "hide_embedding_vectors=True",
        "hide_embeddings_vectors=True",
        "hide_embeddings_text=True",
        "hide_prompts=True",
        "hide_choices=True",
        "enable_genai_semconv=False",
        'required("LEMONADE_DEPLOYMENT_ENVIRONMENT")',
        'required("LEMONADE_MODEL")',
        '"deployment.environment.name": deployment_environment',
        '"gen_ai.request.model": model',
        '"gen_ai.response.model": model',
        'print(f"TRACE_ID={trace_id}")',
        'print(f"CREATED_AFTER={created_after}")',
        'print(f"CREATED_BEFORE={created_before}")',
    ):
        assert required_source in client
    requirements = (
        SKILL / "assets/lemonade_openinference_client.requirements.txt"
    ).read_text(encoding="utf-8")
    packages = [
        line for line in requirements.splitlines() if line and not line.startswith("#")
    ]
    assert packages
    assert all("==" in package for package in packages)


def test_reference_client_help_does_not_require_optional_dependencies() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(SKILL / "assets/lemonade_openinference_client.py"),
            "--help",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--check" in result.stdout
    assert "Traceback" not in result.stderr


def test_api_helpers_disable_ambient_proxies_and_redirects() -> None:
    for relative in (
        "scripts/send_galileo_canary.py",
        "scripts/galileo_readback.py",
        "scripts/galileo_target_discovery.py",
    ):
        source = (SKILL / relative).read_text(encoding="utf-8")
        assert "ProxyHandler({})" in source
        assert "NoRedirect()" in source
