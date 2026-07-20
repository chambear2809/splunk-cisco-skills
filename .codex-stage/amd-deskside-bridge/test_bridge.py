from __future__ import annotations

import importlib.util
import http.client
import json
import sys
import tempfile
import threading
import unittest
import uuid
from dataclasses import replace
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("bridge.py")
SPEC = importlib.util.spec_from_file_location("amd_bridge", MODULE_PATH)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bridge
SPEC.loader.exec_module(bridge)


TRACE_ID = "0123456789abcdef0123456789abcdef"
AGENT_ID = "1111111111111111"
LLM_ID = "2222222222222222"
TOOL_ID = "3333333333333333"


def add_attribute(span, key: str, value):
    item = span.attributes.add()
    item.key = key
    if isinstance(value, str):
        item.value.string_value = value
    elif isinstance(value, bool):
        item.value.bool_value = value
    elif isinstance(value, int):
        item.value.int_value = value
    else:
        item.value.double_value = value


def make_span(
    scope,
    span_id: str,
    parent_id: str,
    kind: str,
    start: int,
    trace_id: str = TRACE_ID,
):
    span = scope.spans.add()
    span.trace_id = bytes.fromhex(trace_id)
    span.span_id = bytes.fromhex(span_id)
    if parent_id:
        span.parent_span_id = bytes.fromhex(parent_id)
    span.name = "SECRET prompt should never survive"
    span.start_time_unix_nano = start
    span.end_time_unix_nano = start + 10_000_000
    add_attribute(span, "openinference.span.kind", kind)
    add_attribute(span, "input.value", "SECRET user content")
    add_attribute(span, "output.value", "SECRET model content")
    return span


def add_trace(request, trace_id: str = TRACE_ID):
    scope = request.resource_spans.add().scope_spans.add()
    make_span(scope, AGENT_ID, "", "AGENT", 1_700_000_000_000_000_000, trace_id)
    llm = make_span(
        scope, LLM_ID, AGENT_ID, "LLM", 1_700_000_000_001_000_000, trace_id
    )
    add_attribute(llm, "gen_ai.request.model", "Qwen3.6-27B-GGUF")
    add_attribute(llm, "gen_ai.usage.input_tokens", 4)
    add_attribute(llm, "gen_ai.usage.output_tokens", 2)
    make_span(scope, TOOL_ID, AGENT_ID, "TOOL", 1_700_000_000_002_000_000, trace_id)


def make_request(trace_id: str = TRACE_ID):
    request = bridge.ExportTraceServiceRequest()
    add_trace(request, trace_id)
    return request


def extended_detail(trace, expected, config):
    detail = json.loads(json.dumps(trace))
    detail.update(
        {
            "project_id": config.project_id,
            "run_id": config.log_stream_id,
            "is_complete": True,
            "num_spans": len(expected),
        }
    )
    pending = list(detail["spans"])
    while pending:
        span = pending.pop()
        span.update(
            {
                "project_id": config.project_id,
                "run_id": config.log_stream_id,
                "is_complete": True,
                "trace_id": trace["id"],
            }
        )
        pending.extend(span.get("spans", []))
    return detail


class FakeRequests:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, payload=None, *, deadline):
        self.calls.append((method, url, payload, deadline))
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


def make_config():
    return bridge.Config(
        bind_host="127.0.0.1",
        bind_port=14321,
        api_origin="https://api-demo-amd.gcp-dev.galileo.ai",
        project_id="7ba7735b-ce29-49cd-b197-1b2e3ddbd248",
        log_stream_id="4a8f0eb8-0bf8-4453-91e9-4f23e01c3c29",
        api_key_file=Path("/unused"),
        proxy_url="http://127.0.0.1:18889",
        destination_namespace="a" * 64,
        request_timeout_seconds=10,
        max_request_bytes=8 * 1024 * 1024,
        max_spans_per_request=1000,
        max_traces_per_request=100,
        max_concurrent_requests=4,
    )


class BridgeTests(unittest.TestCase):
    def test_deterministic_uuid_is_stable_uuid4(self):
        first = bridge.deterministic_uuid("a" * 64, "trace", TRACE_ID)
        second = bridge.deterministic_uuid("a" * 64, "trace", TRACE_ID)
        self.assertEqual(first, second)
        parsed = uuid.UUID(first)
        self.assertEqual(parsed.version, 4)
        self.assertEqual(parsed.variant, uuid.RFC_4122)

    def test_translate_preserves_hierarchy_but_not_content(self):
        translated = bridge.translate_request(make_request(), make_config())
        self.assertEqual(len(translated), 1)
        trace, expected = translated[0]
        self.assertEqual(trace["external_id"], TRACE_ID)
        self.assertEqual(trace["name"], "lemonade.chat")
        self.assertEqual(trace["input"], bridge.REDACTED)
        agent = trace["spans"][0]
        self.assertEqual(agent["type"], "agent")
        children = {item["type"]: item for item in agent["spans"]}
        self.assertEqual(set(children), {"llm", "tool"})
        self.assertEqual(children["llm"]["model"], "Qwen3.6-27B-GGUF")
        self.assertEqual(children["llm"]["metrics"]["num_input_tokens"], 4)
        self.assertEqual(children["llm"]["metrics"]["num_output_tokens"], 2)
        self.assertEqual(children["llm"]["metrics"]["num_total_tokens"], 6)
        self.assertEqual(
            children["llm"]["input"],
            [{"role": "user", "content": bridge.REDACTED}],
        )
        self.assertEqual(
            children["llm"]["redacted_input"],
            [{"role": "user", "content": bridge.REDACTED}],
        )
        self.assertEqual(
            children["llm"]["output"],
            {"role": "assistant", "content": bridge.REDACTED},
        )
        self.assertEqual(children["llm"]["redacted_output"], children["llm"]["output"])
        serialized = json.dumps(trace, sort_keys=True)
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("prompt should never survive", serialized)
        self.assertEqual(len(expected), 3)
        bridge.assert_private_payload(trace)

    def test_privacy_assertion_fails_closed(self):
        bridge.assert_private_payload(
            {
                "input": [{"role": "user", "content": bridge.REDACTED}],
                "output": {"role": "assistant", "content": bridge.REDACTED},
            }
        )
        with self.assertRaisesRegex(bridge.BridgeError, "privacy_assertion_failed"):
            bridge.assert_private_payload({"input": "unsafe"})
        with self.assertRaisesRegex(bridge.BridgeError, "privacy_assertion_failed"):
            bridge.assert_private_payload({"output": "unsafe"})
        with self.assertRaisesRegex(bridge.BridgeError, "privacy_assertion_failed"):
            bridge.assert_private_payload({"user_metadata": {"x": "unsafe"}})
        with self.assertRaisesRegex(bridge.BridgeError, "privacy_assertion_failed"):
            bridge.assert_private_payload(
                {"output": {"role": "assistant", "content": "unsafe"}}
            )
        with self.assertRaisesRegex(bridge.BridgeError, "privacy_assertion_failed"):
            bridge.assert_private_payload(
                {"output": {"role": "SECRET", "content": bridge.REDACTED}}
            )
        with self.assertRaisesRegex(bridge.BridgeError, "privacy_assertion_failed"):
            bridge.assert_private_payload({"exception": {"stacktrace": "unsafe"}})

    def test_model_is_exact_allowlist_only(self):
        request = make_request()
        llm = request.resource_spans[0].scope_spans[0].spans[1]
        for attribute in llm.attributes:
            if attribute.key == "gen_ai.request.model":
                attribute.value.string_value = "SecretHighEntropyValue123456789"
        add_attribute(llm, "gen_ai.response.model", "SecretHighEntropyValue123456789")
        trace, _expected = bridge.translate_request(request, make_config())[0]
        llm_record = next(
            child for child in trace["spans"][0]["spans"] if child["type"] == "llm"
        )
        self.assertEqual(llm_record["model"], "lemonade")

    def test_rejects_duplicate_span_ids(self):
        request = make_request()
        scope = request.resource_spans[0].scope_spans[0]
        make_span(scope, TOOL_ID, AGENT_ID, "TOOL", 1_700_000_000_003_000_000)
        with self.assertRaisesRegex(bridge.BridgeError, "duplicate_span_id"):
            bridge.translate_request(request, make_config())

    def test_rejects_leaf_with_children(self):
        request = bridge.ExportTraceServiceRequest()
        scope = request.resource_spans.add().scope_spans.add()
        make_span(scope, LLM_ID, "", "LLM", 1_700_000_000_000_000_000)
        make_span(scope, TOOL_ID, LLM_ID, "TOOL", 1_700_000_000_001_000_000)
        with self.assertRaisesRegex(bridge.BridgeError, "leaf_has_children"):
            bridge.translate_request(request, make_config())

    def test_rejects_orphan_parent(self):
        request = bridge.ExportTraceServiceRequest()
        scope = request.resource_spans.add().scope_spans.add()
        make_span(scope, TOOL_ID, AGENT_ID, "TOOL", 1_700_000_000_001_000_000)
        with self.assertRaisesRegex(bridge.BridgeError, "orphan_parent"):
            bridge.translate_request(request, make_config())

    def test_rejects_zero_ids_and_unknown_kinds(self):
        request = make_request()
        request.resource_spans[0].scope_spans[0].spans[0].trace_id = b"\0" * 16
        with self.assertRaisesRegex(bridge.BridgeError, "otel_id_invalid"):
            bridge.translate_request(request, make_config())
        request = make_request()
        request.resource_spans[0].scope_spans[0].spans[0].attributes[0].value.string_value = "EMBEDDING"
        with self.assertRaisesRegex(bridge.BridgeError, "span_kind_unsupported"):
            bridge.translate_request(request, make_config())

    def test_rejects_unvalidated_retriever_shape(self):
        request = bridge.ExportTraceServiceRequest()
        scope = request.resource_spans.add().scope_spans.add()
        make_span(scope, AGENT_ID, "", "RETRIEVER", 1_700_000_000_000_000_000)
        with self.assertRaisesRegex(bridge.BridgeError, "retriever_unsupported"):
            bridge.translate_request(request, make_config())

    def test_ingest_validates_exact_response(self):
        config = make_config()
        trace, expected = bridge.translate_request(make_request(), config)[0]
        client = object.__new__(bridge.GalileoClient)
        client.config = config
        client.api_key = "unused"
        fake = FakeRequests(
            [
                (
                    200,
                    {
                        "project_id": config.project_id,
                        "project_name": "AMD-Deskside",
                        "log_stream_id": config.log_stream_id,
                        "records_count": 4,
                        "traces_count": 1,
                        "spans_count": 3,
                        "trace_ids": [trace["id"]],
                    },
                )
            ]
        )
        client._json_request = fake
        self.assertEqual(client.ingest_many([(trace, expected)]), 0)
        self.assertEqual(len(fake.calls), 1)

    def test_multi_trace_uses_one_native_batch(self):
        config = make_config()
        request = make_request()
        add_trace(request, "abcdef0123456789abcdef0123456789")
        translated = bridge.translate_request(request, config)
        roots = [trace["id"] for trace, _expected in translated]
        client = object.__new__(bridge.GalileoClient)
        client.config = config
        client.api_key = "unused"
        fake = FakeRequests(
            [
                (
                    200,
                    {
                        "project_id": config.project_id,
                        "project_name": "AMD-Deskside",
                        "log_stream_id": config.log_stream_id,
                        "records_count": 8,
                        "traces_count": 2,
                        "spans_count": 6,
                        "trace_ids": roots,
                    },
                )
            ]
        )
        client._json_request = fake
        self.assertEqual(client.ingest_many(translated), 0)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(len(fake.calls[0][2]["traces"]), 2)

    def test_generic_422_is_never_acknowledged_as_duplicate(self):
        config = make_config()
        trace, expected = bridge.translate_request(make_request(), config)[0]
        client = object.__new__(bridge.GalileoClient)
        client.config = config
        client.api_key = "unused"
        client._json_request = FakeRequests([(422, {"detail": "schema validation failed"})])
        with self.assertRaisesRegex(bridge.BridgeError, "duplicate_detail_invalid"):
            client.ingest_many([(trace, expected)])

    def test_exact_duplicate_is_stream_scoped_and_reconciled(self):
        config = make_config()
        trace, expected = bridge.translate_request(make_request(), config)[0]
        all_ids = [trace["id"], *expected.keys(), trace["id"]]
        detail = extended_detail(trace, expected, config)
        search_record = {
            "id": trace["id"],
            "trace_id": trace["id"],
            "project_id": config.project_id,
            "run_id": config.log_stream_id,
            "external_id": trace["external_id"],
            "type": "trace",
            "is_complete": True,
            "num_spans": len(expected),
        }
        client = object.__new__(bridge.GalileoClient)
        client.config = config
        client.api_key = "unused"
        fake = FakeRequests(
            [
                (422, {"detail": bridge.DUPLICATE_PREFIX + " " + ", ".join(all_ids)}),
                (
                    200,
                    {
                        "starting_token": 0,
                        "limit": 10,
                        "num_records": 1,
                        "paginated": False,
                        "last_row_id": trace["id"],
                        "records": [search_record],
                    },
                ),
                (200, detail),
            ]
        )
        client._json_request = fake
        self.assertEqual(client.ingest_many([(trace, expected)]), 1)
        self.assertEqual(fake.calls[1][2]["log_stream_id"], config.log_stream_id)
        self.assertEqual(fake.calls[1][2]["filters"][0]["value"], trace["id"])

    def test_mixed_duplicate_and_new_trace_retries_only_new(self):
        config = make_config()
        request = make_request()
        add_trace(request, "abcdef0123456789abcdef0123456789")
        translated = bridge.translate_request(request, config)
        duplicate_trace, duplicate_expected = translated[0]
        new_trace, new_expected = translated[1]
        duplicate_ids = [duplicate_trace["id"], *duplicate_expected.keys()]
        detail = extended_detail(duplicate_trace, duplicate_expected, config)
        search_record = {
            "id": duplicate_trace["id"],
            "trace_id": duplicate_trace["id"],
            "project_id": config.project_id,
            "run_id": config.log_stream_id,
            "external_id": duplicate_trace["external_id"],
            "type": "trace",
            "is_complete": True,
            "num_spans": len(duplicate_expected),
        }
        client = object.__new__(bridge.GalileoClient)
        client.config = config
        client.api_key = "unused"
        fake = FakeRequests(
            [
                (
                    422,
                    {
                        "detail": bridge.DUPLICATE_PREFIX
                        + " "
                        + ", ".join(duplicate_ids)
                    },
                ),
                (
                    200,
                    {
                        "starting_token": 0,
                        "limit": 10,
                        "num_records": 1,
                        "paginated": False,
                        "last_row_id": duplicate_trace["id"],
                        "records": [search_record],
                    },
                ),
                (200, detail),
                (
                    200,
                    {
                        "project_id": config.project_id,
                        "project_name": "AMD-Deskside",
                        "log_stream_id": config.log_stream_id,
                        "records_count": 1 + len(new_expected),
                        "traces_count": 1,
                        "spans_count": len(new_expected),
                        "trace_ids": [new_trace["id"]],
                    },
                ),
            ]
        )
        client._json_request = fake
        self.assertEqual(client.ingest_many(translated), 1)
        self.assertEqual(fake.calls[-1][2]["traces"], [new_trace])

    def test_duplicate_readback_wrong_project_fails(self):
        config = make_config()
        trace, expected = bridge.translate_request(make_request(), config)[0]
        ids = [trace["id"], *expected.keys()]
        bad_record = {
            "id": trace["id"],
            "trace_id": trace["id"],
            "project_id": "00000000-0000-4000-8000-000000000000",
            "external_id": trace["external_id"],
            "type": "trace",
            "is_complete": True,
            "num_spans": len(expected),
        }
        client = object.__new__(bridge.GalileoClient)
        client.config = config
        client.api_key = "unused"
        client._json_request = FakeRequests(
            [
                (422, {"detail": bridge.DUPLICATE_PREFIX + " " + ", ".join(ids)}),
                (
                    200,
                    {
                        "starting_token": 0,
                        "num_records": 1,
                        "paginated": False,
                        "last_row_id": trace["id"],
                        "records": [bad_record],
                    },
                ),
            ]
        )
        with self.assertRaisesRegex(bridge.BridgeError, "duplicate_search_mismatch"):
            client.ingest_many([(trace, expected)])

    def test_partial_duplicate_trace_is_rejected(self):
        config = make_config()
        trace, expected = bridge.translate_request(make_request(), config)[0]
        client = object.__new__(bridge.GalileoClient)
        client.config = config
        client.api_key = "unused"
        client._json_request = FakeRequests(
            [(422, {"detail": bridge.DUPLICATE_PREFIX + " " + trace["id"]})]
        )
        with self.assertRaisesRegex(bridge.BridgeError, "duplicate_partial_trace"):
            client.ingest_many([(trace, expected)])

    def test_config_and_secret_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "key"
            key.write_text("test-key\n", encoding="utf-8")
            key.chmod(0o600)
            document = {
                "bind_host": "127.0.0.1",
                "bind_port": 14321,
                "api_origin": "https://api-demo-amd.gcp-dev.galileo.ai",
                "project_id": "7ba7735b-ce29-49cd-b197-1b2e3ddbd248",
                "log_stream_id": "4a8f0eb8-0bf8-4453-91e9-4f23e01c3c29",
                "api_key_file": str(key),
                "proxy_url": "http://127.0.0.1:18889",
                "destination_namespace": "b" * 64,
                "request_timeout_seconds": 10,
                "max_request_bytes": 8388608,
                "max_spans_per_request": 1000,
                "max_traces_per_request": 100,
                "max_concurrent_requests": 4,
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(document), encoding="utf-8")
            config = bridge.load_config(config_path)
            self.assertEqual(config.traces_url, f"{config.api_origin}/v2/projects/{config.project_id}/traces")
            self.assertEqual(bridge.read_api_key(key), "test-key")
            key.chmod(0o644)
            with self.assertRaisesRegex(bridge.BridgeError, "secret_mode_invalid"):
                bridge.read_api_key(key)
            key.chmod(0o440)
            with self.assertRaisesRegex(bridge.BridgeError, "secret_mode_invalid"):
                bridge.read_api_key(key)
            config_path.chmod(0o666)
            with self.assertRaisesRegex(bridge.BridgeError, "config_mode_invalid"):
                bridge.load_config(config_path)

    def test_malformed_protobuf_is_http_400(self):
        config = replace(make_config(), bind_port=0)
        client = object.__new__(bridge.GalileoClient)
        client.config = config
        client.api_key = "unused"
        client.ingest_many = lambda translated: 0
        server = bridge.BridgeServer(config, client, bridge.Metrics())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_address[1], timeout=5
            )
            connection.request(
                "POST",
                "/v1/traces",
                body=b"\xff",
                headers={"Content-Type": "application/x-protobuf"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
