from __future__ import annotations

import importlib.util
import io
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills/lemonade-splunk-otel/scripts/collector_evidence.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lemonade_collector_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module() -> ModuleType:
    return load_script()


def metrics_fixture(*, accepted: int = 12, sent: int = 11) -> str:
    return f"""\
# HELP otelcol_receiver_accepted_spans Number of spans accepted.
otelcol_receiver_accepted_spans{{receiver="otlp/lemonade",transport="http"}} {accepted}
otelcol_receiver_failed_spans{{receiver="otlp/lemonade",transport="http"}} 2
otelcol_receiver_refused_spans{{receiver="otlp/lemonade",transport="http"}} 1
otelcol_receiver_accepted_spans{{receiver="otlp/other",transport="grpc"}} 900
otelcol_exporter_sent_spans{{exporter="signalfx",server_address="https://secret.example",url_path="/v2/trace"}} {sent}
otelcol_exporter_send_failed_spans{{exporter="signalfx",error_type="Unavailable",server_address="secret.example"}} 2
otelcol_exporter_send_failed_spans{{exporter="signalfx",error_type="DeadlineExceeded",url_path="/private"}} 1
otelcol_exporter_enqueue_failed_spans{{exporter="signalfx"}} 4
otelcol_exporter_queue_size{{exporter="signalfx"}} 5
otelcol_exporter_queue_capacity{{exporter="signalfx"}} 1000
otelcol_exporter_in_flight_requests{{exporter="signalfx"}} 2
otelcol_exporter_sent_spans{{exporter="otlphttp/other",server_address="other.example"}} 999
"""


def test_exact_v0156_metric_allowlist_and_sensitive_labels_are_not_emitted(
    module,
) -> None:
    metrics = module.parse_metrics(metrics_fixture(), "otlp/lemonade", "signalfx")

    assert set(metrics) == {
        "otelcol_receiver_accepted_spans",
        "otelcol_receiver_failed_spans",
        "otelcol_receiver_refused_spans",
        "otelcol_exporter_sent_spans",
        "otelcol_exporter_send_failed_spans",
        "otelcol_exporter_enqueue_failed_spans",
        "otelcol_exporter_queue_size",
        "otelcol_exporter_queue_capacity",
        "otelcol_exporter_in_flight_requests",
    }
    assert metrics["otelcol_receiver_accepted_spans"]["value"] == 12
    assert metrics["otelcol_exporter_sent_spans"]["value"] == 11
    assert metrics["otelcol_exporter_send_failed_spans"]["value"] == 3
    serialized = json.dumps(metrics, sort_keys=True)
    assert "secret.example" not in serialized
    assert "/v2/trace" not in serialized
    assert "/private" not in serialized
    assert "server_address" not in serialized
    assert "url_path" not in serialized


def test_missing_metric_is_explicitly_unobserved_not_assumed_zero(module) -> None:
    metrics = module.parse_metrics(
        'otelcol_receiver_accepted_spans{receiver="otlp/lemonade"} 1\n',
        "otlp/lemonade",
        "signalfx",
    )

    assert metrics["otelcol_receiver_accepted_spans"] == {
        "kind": "counter",
        "present": True,
        "value": 1,
    }
    assert metrics["otelcol_exporter_send_failed_spans"] == {
        "kind": "counter",
        "present": False,
        "value": None,
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8888/metrics",
        "http://127.99.4.3:8888/metrics",
        "http://[::1]:8888/metrics",
    ],
)
def test_strict_url_validation_accepts_loopback_ip_literals(module, url: str) -> None:
    assert module.validate_loopback_http_url(url, "metrics URL") == url


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8888/metrics",
        "http://localhost:8888/metrics",
        "http://192.0.2.50:8888/metrics",
        "http://127.0.0.1/metrics",
        "http://127.0.0.1:0/metrics",
        "http://user:password@127.0.0.1:8888/metrics",
        "http://127.0.0.1:8888/metrics?token=secret",
        "http://127.0.0.1:8888/metrics#fragment",
        "http://127%2e0%2e0%2e1:8888/metrics",
    ],
)
def test_strict_url_validation_rejects_unsafe_or_ambiguous_urls(
    module, url: str
) -> None:
    with pytest.raises(module.EvidenceError):
        module.validate_loopback_http_url(url, "metrics URL")


def test_local_opener_disables_ambient_proxies_and_redirects(
    module, monkeypatch
) -> None:
    captured: list[object] = []

    class DummyOpener:
        pass

    def fake_build_opener(*handlers):
        captured.extend(handlers)
        return DummyOpener()

    monkeypatch.setattr(module.urllib.request, "build_opener", fake_build_opener)
    assert isinstance(module.build_local_opener(), DummyOpener)
    proxy = next(
        handler
        for handler in captured
        if isinstance(handler, urllib.request.ProxyHandler)
    )
    redirect = next(
        handler for handler in captured if isinstance(handler, module.NoRedirectHandler)
    )
    assert proxy.proxies == {}
    with pytest.raises(module.EvidenceError, match="redirects are not allowed"):
        redirect.redirect_request(
            None, None, 302, "Found", {}, "http://secret.example/"
        )


def test_prometheus_parser_rejects_nonfinite_noninteger_and_malformed_selected_samples(
    module,
) -> None:
    invalid_samples = [
        'otelcol_exporter_sent_spans{exporter="signalfx"} NaN',
        'otelcol_exporter_sent_spans{exporter="signalfx"} +Inf',
        'otelcol_exporter_sent_spans{exporter="signalfx"} 1.5',
        'otelcol_exporter_sent_spans{exporter="signalfx"} -1',
        f'otelcol_exporter_sent_spans{{exporter="signalfx"}} {(1 << 63)}',
        'otelcol_exporter_sent_spans{exporter="signalfx"}',
        'otelcol_exporter_sent_spans{exporter="signalfx",exporter="other"} 1',
    ]
    for sample in invalid_samples:
        with pytest.raises(module.EvidenceError):
            module.parse_metrics(sample, "otlp/lemonade", "signalfx")


def test_deltas_distinguish_counter_reset_and_gauge_change(module) -> None:
    before = module.parse_metrics(
        metrics_fixture(accepted=10, sent=15), "otlp/lemonade", "signalfx"
    )
    current = module.parse_metrics(
        metrics_fixture(accepted=13, sent=4), "otlp/lemonade", "signalfx"
    )
    current["otelcol_exporter_queue_size"]["value"] = 8
    deltas = module.compute_deltas(current, before)

    assert deltas["otelcol_receiver_accepted_spans"] == {
        "available": True,
        "reset": False,
        "value": 3,
    }
    assert deltas["otelcol_exporter_sent_spans"] == {
        "available": False,
        "reset": True,
        "value": None,
    }
    assert deltas["otelcol_exporter_queue_size"] == {
        "available": True,
        "reset": False,
        "value": 3,
    }


def test_before_snapshot_is_bounded_validated_and_arbitrary_fields_are_not_reflected(
    module, tmp_path: Path
) -> None:
    metrics = module.parse_metrics(metrics_fixture(), "otlp/lemonade", "signalfx")
    snapshot = {
        "schema_version": module.SCHEMA_VERSION,
        "selection": {"receiver": "otlp/lemonade", "exporter": "signalfx"},
        "metrics": metrics,
        "untrusted": {"body": "dummy-secret", "server_address": "secret.example"},
    }
    path = tmp_path / "before.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    loaded = module.load_before_snapshot(path, "otlp/lemonade", "signalfx")
    serialized = json.dumps(loaded, sort_keys=True)
    assert "dummy-secret" not in serialized
    assert "secret.example" not in serialized
    assert set(loaded) == set(module.METRIC_SPECS)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (module.MAX_SNAPSHOT_BYTES + 1))
    with pytest.raises(module.EvidenceError, match="size limit"):
        module.load_before_snapshot(oversized, "otlp/lemonade", "signalfx")


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, *, status: int = 200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def getcode(self) -> int:
        return self.status


def test_metrics_response_size_and_encoding_are_bounded(module) -> None:
    response = FakeResponse(
        b"ignored",
        headers={"Content-Length": str(module.MAX_METRICS_BYTES + 1)},
    )
    with pytest.raises(module.EvidenceError, match="size limit"):
        module._bounded_response_bytes(response, module.MAX_METRICS_BYTES)

    response = FakeResponse(b"compressed", headers={"Content-Encoding": "gzip"})
    with pytest.raises(module.EvidenceError, match="content encoding"):
        module._bounded_response_bytes(response, module.MAX_METRICS_BYTES)


def test_metrics_query_rejects_non_success_without_reading_body(module) -> None:
    class BodyMustNotBeRead(FakeResponse):
        def read(self, *args, **kwargs):
            raise AssertionError("error response body was read")

    class Opener:
        def open(self, request, timeout):
            return BodyMustNotBeRead(b"dummy-secret", status=503)

    with pytest.raises(module.EvidenceError, match="HTTP status 503") as raised:
        module.query_metrics_text(Opener(), "http://127.0.0.1:8888/metrics", 1.0)
    assert "dummy-secret" not in str(raised.value)


def test_health_does_not_read_or_emit_body(module) -> None:
    class BodyMustNotBeRead(FakeResponse):
        def read(self, *args, **kwargs):
            raise AssertionError("health response body was read")

    class Opener:
        def open(self, request, timeout):
            return BodyMustNotBeRead(b"dummy-secret", status=200)

    health = module.query_health(Opener(), "http://127.0.0.1:13133/", 1.0)
    assert health == {"ok": True, "status_code": 200}
    assert "dummy-secret" not in json.dumps(health)


def test_end_to_end_local_collection_is_sanitized_deterministic_and_supports_before(
    module, tmp_path: Path, monkeypatch
) -> None:
    fixture = metrics_fixture()
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            requests.append(self.path)
            if self.path == "/health":
                body = b'{"secret":"dummy-secret"}'
            elif self.path == "/metrics":
                body = fixture.encode("utf-8")
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        port = server.server_address[1]
        first = module.collect_evidence(
            health_url=f"http://127.0.0.1:{port}/health",
            metrics_url=f"http://127.0.0.1:{port}/metrics",
            receiver_label="otlp/lemonade",
            exporter_label="signalfx",
            timeout=2.0,
        )
        before = tmp_path / "before.json"
        before.write_text(json.dumps(first), encoding="utf-8")
        second = module.collect_evidence(
            health_url=f"http://127.0.0.1:{port}/health",
            metrics_url=f"http://127.0.0.1:{port}/metrics",
            receiver_label="otlp/lemonade",
            exporter_label="signalfx",
            timeout=2.0,
            before_path=before,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert requests == ["/health", "/metrics", "/health", "/metrics"]
    assert first["deltas"] is None
    assert second["deltas"]["otelcol_receiver_accepted_spans"]["value"] == 0
    assert second["health"] == {"ok": True, "status_code": 200}
    output_once = json.dumps(second, indent=2, sort_keys=True)
    output_twice = json.dumps(second, indent=2, sort_keys=True)
    assert output_once == output_twice
    assert "dummy-secret" not in output_once
    assert "secret.example" not in output_once
    assert "/v2/trace" not in output_once


def test_redirect_is_rejected_without_reflecting_target(module) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(302)
            self.send_header(
                "Location", "http://127.0.0.1:9/private?token=dummy-secret"
            )
            self.end_headers()

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with pytest.raises(module.EvidenceError) as raised:
            module.query_health(
                module.build_local_opener(),
                f"http://127.0.0.1:{port}/health",
                2.0,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert "dummy-secret" not in str(raised.value)
    assert "/private" not in str(raised.value)
