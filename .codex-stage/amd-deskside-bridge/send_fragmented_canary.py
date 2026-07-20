#!/usr/bin/env python3
"""Send one privacy-safe Agent/Tool/LLM trace as three OTLP fragments."""

from __future__ import annotations

import datetime as dt
import json
import secrets
import time
import urllib.error
import urllib.request

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)


ENDPOINT = "http://127.0.0.1:14320/v1/traces"
SENTINEL = "AMD_DESKSIDE_PRIVACY_CANARY"


def add_attribute(span, key: str, value: str | int) -> None:
    attribute = span.attributes.add()
    attribute.key = key
    if isinstance(value, int):
        attribute.value.int_value = value
    else:
        attribute.value.string_value = value


def make_fragment(
    trace_id: bytes,
    span_id: bytes,
    parent_id: bytes,
    kind: str,
    start_ns: int,
) -> bytes:
    request = ExportTraceServiceRequest()
    resource_spans = request.resource_spans.add()
    resource = resource_spans.resource
    add_attribute(resource, "service.name", "lemonade-galileo-client")
    scope = resource_spans.scope_spans.add()
    span = scope.spans.add()
    span.trace_id = trace_id
    span.span_id = span_id
    span.parent_span_id = parent_id
    span.name = f"{SENTINEL}-{kind.lower()}"
    span.start_time_unix_nano = start_ns
    span.end_time_unix_nano = start_ns + 10_000_000
    add_attribute(span, "openinference.span.kind", kind)
    add_attribute(span, "input.value", SENTINEL)
    add_attribute(span, "output.value", SENTINEL)
    if kind == "LLM":
        add_attribute(span, "gen_ai.operation.name", "chat")
        add_attribute(span, "gen_ai.request.model", "Qwen3.6-27B-GGUF")
        add_attribute(span, "gen_ai.response.model", "Qwen3.6-27B-GGUF")
        add_attribute(span, "gen_ai.usage.input_tokens", 4)
        add_attribute(span, "gen_ai.usage.output_tokens", 2)
    if kind == "TOOL":
        add_attribute(span, "gen_ai.operation.name", "execute_tool")
        add_attribute(span, "gen_ai.tool.call.arguments", SENTINEL)
        add_attribute(span, "gen_ai.tool.call.result", SENTINEL)
    if kind == "AGENT":
        add_attribute(span, "gen_ai.operation.name", "invoke_agent")
    return request.SerializeToString()


def post(payload: bytes) -> None:
    request = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/x-protobuf",
            "Content-Encoding": "identity",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read(1024)
            if response.status != 200:
                raise RuntimeError("collector_status_invalid")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("collector_request_failed") from exc
    parsed = ExportTraceServiceResponse()
    try:
        parsed.ParseFromString(body)
    except Exception as exc:
        raise RuntimeError("collector_response_invalid") from exc


def main() -> None:
    created_after = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    trace_id = secrets.token_bytes(16)
    agent_id = secrets.token_bytes(8)
    tool_id = secrets.token_bytes(8)
    llm_id = secrets.token_bytes(8)
    now = time.time_ns()
    # Children end before their parent. Sending them separately proves that the
    # sidecar assembles a complete trace before the bridge sees it.
    post(make_fragment(trace_id, tool_id, agent_id, "TOOL", now + 1_000_000))
    post(make_fragment(trace_id, llm_id, agent_id, "LLM", now + 2_000_000))
    post(make_fragment(trace_id, agent_id, b"", "AGENT", now))
    print(
        json.dumps(
            {
                "created_after": created_after,
                "expected_span_count": 3,
                "trace_id": trace_id.hex(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
