#!/usr/bin/env python3
"""Translate loopback OTLP/HTTP traces into Galileo's native trace API.

The bridge deliberately forwards no user/model content or arbitrary metadata.
All content-bearing fields are replaced with the constant ``[REDACTED]`` and
only structural span type, timing, model name, token counts, and status survive.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import logging
import os
import re
import signal
import socket
import ssl
import stat
import threading
import time
import urllib.parse
import uuid
from collections import defaultdict
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)


REDACTED = "[REDACTED]"
MAX_CONFIG_BYTES = 64 * 1024
MAX_SECRET_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PRIVACY_NODES = 100_000
MAX_TRACE_DEPTH = 128
MAX_NATIVE_INTEGER = 2**63 - 1
CLIENT_SOCKET_TIMEOUT_SECONDS = 5
ALLOWED_MODELS = {"Qwen3.6-27B-GGUF"}
HEX_TRACE = re.compile(r"[0-9a-f]{32}")
HEX_SPAN = re.compile(r"[0-9a-f]{16}")
UUID4 = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
TYPE_NAMES = {
    "agent": "lemonade.agent",
    "workflow": "lemonade.workflow",
    "llm": "lemonade.llm",
    "tool": "lemonade.tool",
    "retriever": "lemonade.retriever",
}
OI_KIND_MAP = {
    "AGENT": "agent",
    "CHAIN": "workflow",
    "WORKFLOW": "workflow",
    "LLM": "llm",
    "TOOL": "tool",
    "RETRIEVER": "retriever",
}
LLM_OPERATIONS = {
    "chat",
    "text_completion",
    "generate_content",
    "completion",
}
AGENT_OPERATIONS = {"invoke_agent", "create_agent", "execute_agent"}
TOOL_OPERATIONS = {"execute_tool", "tool_call"}
CONTENT_BEARING_KEYS = {
    "arguments",
    "assistant_response",
    "completion",
    "content",
    "dataset_metadata",
    "document_content",
    "error_message",
    "events",
    "exception_message",
    "exception_stacktrace",
    "files",
    "function_arguments",
    "input",
    "input_messages",
    "input_text",
    "input_value",
    "invocation_parameters",
    "llm_invocation_parameters",
    "llm_tools",
    "messages",
    "output",
    "output_messages",
    "output_text",
    "output_value",
    "prompt",
    "prompt_template",
    "progress_message",
    "query",
    "reasoning",
    "redacted_input",
    "redacted_output",
    "request_body",
    "response",
    "response_body",
    "result",
    "stacktrace",
    "system_prompt",
    "summary",
    "tags",
    "text",
    "tool_call_arguments",
    "tool_call_result",
    "tool_json_schema",
    "tool_output",
    "tool_parameters",
    "tools",
    "user_metadata",
    "user_prompt",
}
DUPLICATE_PREFIX = "Cannot ingest records with IDs that already exist:"


class BridgeError(RuntimeError):
    """A sanitized error suitable for a stable log code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ClientRequestError(BridgeError):
    """A permanent malformed OTLP request that should not be retried."""


@dataclass(frozen=True)
class Config:
    bind_host: str
    bind_port: int
    api_origin: str
    project_id: str
    log_stream_id: str
    api_key_file: Path
    proxy_url: str
    destination_namespace: str
    request_timeout_seconds: float
    max_request_bytes: int
    max_spans_per_request: int
    max_traces_per_request: int
    max_concurrent_requests: int

    @property
    def traces_url(self) -> str:
        return f"{self.api_origin}/v2/projects/{self.project_id}/traces"


def _read_regular_file(path: Path, maximum: int, *, private: bool) -> bytes:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BridgeError("file_open_failed") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise BridgeError("file_not_regular")
        mode = stat.S_IMODE(before.st_mode)
        if private:
            if before.st_uid != os.geteuid():
                raise BridgeError("secret_owner_invalid")
            if mode not in {0o400, 0o600}:
                raise BridgeError("secret_mode_invalid")
        else:
            if before.st_uid not in {0, os.geteuid()}:
                raise BridgeError("config_owner_invalid")
            if mode & 0o022:
                raise BridgeError("config_mode_invalid")
        if not 1 <= before.st_size <= maximum:
            raise BridgeError("file_size_invalid")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(8192, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise BridgeError("file_changed")
        if len(payload) != before.st_size:
            raise BridgeError("file_short_read")
        return payload
    finally:
        os.close(descriptor)


def _uuid4(value: Any, code: str) -> str:
    if not isinstance(value, str) or not UUID4.fullmatch(value.lower()):
        raise BridgeError(code)
    parsed = uuid.UUID(value)
    if parsed.version != 4 or parsed.variant != uuid.RFC_4122:
        raise BridgeError(code)
    return str(parsed)


def load_config(path: Path) -> Config:
    try:
        raw = _read_regular_file(path, MAX_CONFIG_BYTES, private=False)
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise BridgeError("config_invalid") from exc
    if not isinstance(document, dict):
        raise BridgeError("config_invalid")
    required = {
        "bind_host",
        "bind_port",
        "api_origin",
        "project_id",
        "log_stream_id",
        "api_key_file",
        "proxy_url",
        "destination_namespace",
        "request_timeout_seconds",
        "max_request_bytes",
        "max_spans_per_request",
        "max_traces_per_request",
        "max_concurrent_requests",
    }
    if set(document) != required:
        raise BridgeError("config_keys_invalid")
    if document["bind_host"] != "127.0.0.1":
        raise BridgeError("bind_host_invalid")
    bind_port = document["bind_port"]
    if isinstance(bind_port, bool) or not isinstance(bind_port, int) or not 1024 <= bind_port <= 65535:
        raise BridgeError("bind_port_invalid")
    origin = document["api_origin"]
    if not isinstance(origin, str) or origin != origin.strip() or origin.endswith("/"):
        raise BridgeError("api_origin_invalid")
    parsed = urllib.parse.urlsplit(origin)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api-demo-amd.gcp-dev.galileo.ai"
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise BridgeError("api_origin_invalid")
    proxy = document["proxy_url"]
    if proxy != "http://127.0.0.1:18889":
        raise BridgeError("proxy_invalid")
    key_file_raw = document["api_key_file"]
    if not isinstance(key_file_raw, str):
        raise BridgeError("key_path_invalid")
    key_file = Path(key_file_raw)
    if not key_file.is_absolute():
        raise BridgeError("key_path_invalid")
    namespace = document["destination_namespace"]
    if not isinstance(namespace, str) or not re.fullmatch(r"[0-9a-f]{64}", namespace):
        raise BridgeError("namespace_invalid")

    def bounded_int(name: str, low: int, high: int) -> int:
        value = document[name]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise BridgeError(f"{name}_invalid")
        return value

    timeout = document["request_timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 60:
        raise BridgeError("request_timeout_invalid")
    return Config(
        bind_host="127.0.0.1",
        bind_port=bind_port,
        api_origin=origin,
        project_id=_uuid4(document["project_id"], "project_id_invalid"),
        log_stream_id=_uuid4(document["log_stream_id"], "log_stream_id_invalid"),
        api_key_file=key_file,
        proxy_url=proxy,
        destination_namespace=namespace,
        request_timeout_seconds=float(timeout),
        max_request_bytes=bounded_int("max_request_bytes", 1024, 64 * 1024 * 1024),
        max_spans_per_request=bounded_int("max_spans_per_request", 1, 100_000),
        max_traces_per_request=bounded_int("max_traces_per_request", 1, 10_000),
        max_concurrent_requests=bounded_int("max_concurrent_requests", 1, 64),
    )


def read_api_key(path: Path) -> str:
    payload = _read_regular_file(path, MAX_SECRET_BYTES, private=True)
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise BridgeError("secret_invalid") from exc
    if (
        len(lines) != 1
        or not lines[0]
        or any(ord(character) < 32 or ord(character) == 127 for character in lines[0])
    ):
        raise BridgeError("secret_invalid")
    return lines[0]


def deterministic_uuid(namespace: str, *parts: str) -> str:
    digest = bytearray(hashlib.sha256((namespace + "\0" + "\0".join(parts)).encode("ascii")).digest()[:16])
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def _any_value(value: Any) -> str | int | float | bool | None:
    selected = value.WhichOneof("value")
    if selected == "string_value":
        return value.string_value
    if selected == "int_value":
        return int(value.int_value)
    if selected == "double_value":
        return float(value.double_value)
    if selected == "bool_value":
        return bool(value.bool_value)
    return None


def span_attributes(span: Any) -> dict[str, str | int | float | bool]:
    result: dict[str, str | int | float | bool] = {}
    for attribute in span.attributes:
        if not isinstance(attribute.key, str) or len(attribute.key) > 256:
            continue
        value = _any_value(attribute.value)
        if value is not None:
            result[attribute.key] = value
    return result


def span_type(attributes: dict[str, Any]) -> str:
    raw_kind = attributes.get("openinference.span.kind")
    if isinstance(raw_kind, str):
        mapped = OI_KIND_MAP.get(raw_kind.upper())
        if mapped:
            if mapped == "retriever":
                raise BridgeError("retriever_unsupported")
            return mapped
    operation = attributes.get("gen_ai.operation.name")
    if isinstance(operation, str):
        lowered = operation.lower()
        if lowered in LLM_OPERATIONS:
            return "llm"
        if lowered in AGENT_OPERATIONS:
            return "agent"
        if lowered in TOOL_OPERATIONS:
            return "tool"
    raise BridgeError("span_kind_unsupported")


def safe_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= MAX_NATIVE_INTEGER:
        return value
    if isinstance(value, float) and value.is_integer() and 0 <= value <= MAX_NATIVE_INTEGER:
        return int(value)
    return None


def first_int(attributes: dict[str, Any], names: Iterable[str]) -> int | None:
    for name in names:
        value = safe_nonnegative_int(attributes.get(name))
        if value is not None:
            return value
    return None


def safe_model(attributes: dict[str, Any]) -> str:
    for name in (
        "gen_ai.response.model",
        "gen_ai.request.model",
        "llm.model_name",
    ):
        value = attributes.get(name)
        if isinstance(value, str) and value in ALLOWED_MODELS:
            return value
    return "lemonade"


def iso_from_nanos(value: int) -> str:
    if not isinstance(value, int) or value <= 0:
        raise BridgeError("timestamp_invalid")
    seconds, nanos = divmod(value, 1_000_000_000)
    try:
        moment = dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise BridgeError("timestamp_invalid") from exc
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + f".{nanos:09d}Z"


@dataclass(frozen=True)
class SourceSpan:
    trace_hex: str
    span_hex: str
    parent_hex: str
    start_ns: int
    end_ns: int
    kind: str
    attributes: dict[str, Any]
    status_error: bool


@dataclass(frozen=True)
class ExpectedSpan:
    kind: str
    parent_id: str
    external_id: str


def source_spans(request: ExportTraceServiceRequest, config: Config) -> list[SourceSpan]:
    result: list[SourceSpan] = []
    for resource_spans in request.resource_spans:
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                trace_hex = bytes(span.trace_id).hex()
                span_hex = bytes(span.span_id).hex()
                parent_hex = bytes(span.parent_span_id).hex()
                if (
                    not HEX_TRACE.fullmatch(trace_hex)
                    or not HEX_SPAN.fullmatch(span_hex)
                    or trace_hex == "0" * 32
                    or span_hex == "0" * 16
                ):
                    raise BridgeError("otel_id_invalid")
                if parent_hex and (
                    not HEX_SPAN.fullmatch(parent_hex) or parent_hex == "0" * 16
                ):
                    raise BridgeError("otel_parent_id_invalid")
                if span.end_time_unix_nano < span.start_time_unix_nano:
                    raise BridgeError("duration_invalid")
                duration_ns = int(span.end_time_unix_nano) - int(span.start_time_unix_nano)
                if duration_ns > MAX_NATIVE_INTEGER:
                    raise BridgeError("duration_invalid")
                attributes = span_attributes(span)
                result.append(
                    SourceSpan(
                        trace_hex=trace_hex,
                        span_hex=span_hex,
                        parent_hex=parent_hex,
                        start_ns=int(span.start_time_unix_nano),
                        end_ns=int(span.end_time_unix_nano),
                        kind=span_type(attributes),
                        attributes=attributes,
                        status_error=int(span.status.code) == 2,
                    )
                )
                if len(result) > config.max_spans_per_request:
                    raise BridgeError("span_limit_exceeded")
    return result


def _base_record(
    *,
    record_id: str,
    trace_id: str,
    parent_id: str | None,
    external_id: str,
    kind: str,
    created_at: str,
    duration_ns: int,
    status_error: bool,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": record_id,
        "trace_id": trace_id,
        "external_id": external_id,
        "type": kind,
        "name": "lemonade.chat" if kind == "trace" else TYPE_NAMES[kind],
        "created_at": created_at,
        "input": REDACTED,
        "output": REDACTED,
        "redacted_input": REDACTED,
        "redacted_output": REDACTED,
        "metrics": {"duration_ns": duration_ns},
        "status_code": 500 if status_error else 200,
        "tags": [],
        "user_metadata": {},
        "dataset_metadata": {},
    }
    if parent_id is not None:
        record["parent_id"] = parent_id
    return record


def translate_trace(
    trace_hex: str,
    spans: list[SourceSpan],
    config: Config,
) -> tuple[dict[str, Any], dict[str, ExpectedSpan]]:
    if not spans:
        raise BridgeError("empty_trace")
    by_id: dict[str, SourceSpan] = {}
    children: dict[str, list[SourceSpan]] = defaultdict(list)
    for span in spans:
        if span.span_hex in by_id:
            raise BridgeError("duplicate_span_id")
        by_id[span.span_hex] = span
    for span in spans:
        if span.parent_hex and span.parent_hex not in by_id:
            raise BridgeError("orphan_parent")
        parent = span.parent_hex
        children[parent].append(span)
    for values in children.values():
        values.sort(key=lambda item: (item.start_ns, item.span_hex))
    roots = children.get("", [])
    if not roots:
        raise BridgeError("trace_cycle")
    root_id = deterministic_uuid(config.destination_namespace, "trace", trace_hex)
    expected: dict[str, ExpectedSpan] = {}
    visited: set[str] = set()

    def convert(span: SourceSpan, parent_id: str, depth: int) -> dict[str, Any]:
        if depth > MAX_TRACE_DEPTH:
            raise BridgeError("trace_depth_exceeded")
        if span.span_hex in visited:
            raise BridgeError("trace_cycle")
        visited.add(span.span_hex)
        span_id = deterministic_uuid(config.destination_namespace, "span", trace_hex, span.span_hex)
        expected[span_id] = ExpectedSpan(span.kind, parent_id, span.span_hex)
        record = _base_record(
            record_id=span_id,
            trace_id=root_id,
            parent_id=parent_id,
            external_id=span.span_hex,
            kind=span.kind,
            created_at=iso_from_nanos(span.start_ns),
            duration_ns=max(0, span.end_ns - span.start_ns),
            status_error=span.status_error,
        )
        if span.kind == "agent":
            record["agent_type"] = "default"
        if span.kind == "llm":
            user_message = {"role": "user", "content": REDACTED}
            assistant_message = {"role": "assistant", "content": REDACTED}
            record["input"] = [dict(user_message)]
            record["redacted_input"] = [dict(user_message)]
            record["output"] = dict(assistant_message)
            record["redacted_output"] = dict(assistant_message)
            record["model"] = safe_model(span.attributes)
            input_tokens = first_int(
                span.attributes,
                ("gen_ai.usage.input_tokens", "llm.token_count.prompt", "llm.token_count.input"),
            )
            output_tokens = first_int(
                span.attributes,
                ("gen_ai.usage.output_tokens", "llm.token_count.completion", "llm.token_count.output"),
            )
            total_tokens = first_int(
                span.attributes,
                ("gen_ai.usage.total_tokens", "llm.token_count.total"),
            )
            if total_tokens is None and input_tokens is not None and output_tokens is not None:
                total_tokens = input_tokens + output_tokens
                if total_tokens > MAX_NATIVE_INTEGER:
                    raise BridgeError("token_count_invalid")
            record["metrics"].update(
                {
                    "num_input_tokens": input_tokens,
                    "num_output_tokens": output_tokens,
                    "num_total_tokens": total_tokens,
                }
            )
        descendants = children.get(span.span_hex, [])
        if descendants:
            if span.kind not in {"agent", "workflow"}:
                raise BridgeError("leaf_has_children")
            record["spans"] = [convert(child, span_id, depth + 1) for child in descendants]
        return record

    earliest = min(span.start_ns for span in spans)
    latest = max(span.end_ns for span in spans)
    trace_duration = latest - earliest
    if trace_duration < 0 or trace_duration > MAX_NATIVE_INTEGER:
        raise BridgeError("duration_invalid")
    trace = _base_record(
        record_id=root_id,
        trace_id=root_id,
        parent_id=None,
        external_id=trace_hex,
        kind="trace",
        created_at=iso_from_nanos(earliest),
        duration_ns=trace_duration,
        status_error=any(span.status_error for span in spans),
    )
    trace["spans"] = [convert(root, root_id, 1) for root in roots]
    if len(visited) != len(spans):
        raise BridgeError("trace_cycle")
    return trace, expected


def translate_request(
    request: ExportTraceServiceRequest,
    config: Config,
) -> list[tuple[dict[str, Any], dict[str, ExpectedSpan]]]:
    spans = source_spans(request, config)
    grouped: dict[str, list[SourceSpan]] = defaultdict(list)
    for span in spans:
        grouped[span.trace_hex].append(span)
    if len(grouped) > config.max_traces_per_request:
        raise BridgeError("trace_limit_exceeded")
    translated = [translate_trace(trace_id, grouped[trace_id], config) for trace_id in sorted(grouped)]
    for trace, _expected in translated:
        assert_private_payload(trace)
    return translated


def assert_private_payload(value: Any) -> None:
    pending: list[tuple[Any, tuple[str, ...]]] = [(value, ())]
    visited = 0
    while pending:
        node, path = pending.pop()
        visited += 1
        if visited > MAX_PRIVACY_NODES:
            raise BridgeError("privacy_limit_exceeded")
        if isinstance(node, dict):
            for child_key, child in node.items():
                next_path = (*path, str(child_key))
                if not is_galileo_protection_status_path(next_path) and (
                    is_content_bearing_key(child_key)
                    or is_content_bearing_key(".".join(next_path))
                ):
                    if content_key_state(child_key, child) == "present":
                        raise BridgeError("privacy_assertion_failed")
                pending.append((child, next_path))
        elif isinstance(node, (list, tuple)):
            pending.extend((child, path) for child in node)


def content_state(value: Any) -> str:
    pending = [value]
    saw_redacted = False
    visited = 0
    while pending:
        item = pending.pop()
        visited += 1
        if visited > MAX_PRIVACY_NODES:
            return "present"
        if item in (None, "", [], {}):
            continue
        if isinstance(item, str):
            if item.strip().lower() in {"[redacted]", "__redacted__"}:
                saw_redacted = True
                continue
            return "present"
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
        else:
            return "present"
    return "redacted" if saw_redacted else "absent"


def normalized_content_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return re.sub(r"[^a-zA-Z0-9]+", "_", snake).strip("_").lower()


def is_content_bearing_key(value: Any) -> bool:
    key = normalized_content_key(value)
    return key in CONTENT_BEARING_KEYS or any(
        key.endswith(f"_{suffix}")
        for suffix in (
            "arguments",
            "completion",
            "content",
            "dataset_metadata",
            "document_content",
            "error_message",
            "events",
            "exception_message",
            "exception_stacktrace",
            "files",
            "function_arguments",
            "image_url",
            "input",
            "input_text",
            "input_value",
            "invocation_parameters",
            "json_schema",
            "llm_tools",
            "output",
            "output_text",
            "output_value",
            "parameters",
            "prompt",
            "progress_message",
            "reasoning",
            "result",
            "stacktrace",
            "summary",
            "tags",
            "text",
            "tools",
            "user_metadata",
        )
    )


def is_galileo_protection_status_path(parts: tuple[str, ...]) -> bool:
    normalized_parts = tuple(normalized_content_key(part) for part in parts)
    return (
        bool(normalized_parts)
        and normalized_parts[-1] == "protect_status_error_message"
    ) or (
        len(normalized_parts) >= 2
        and normalized_parts[-2:] == ("protect_status", "error_message")
    )


STRUCTURAL_CONTENT_KEYS = {
    "finish_reason",
    "id",
    "index",
    "name",
    "role",
    "tool_call_id",
    "type",
}
MESSAGE_CONTAINER_KEYS = {
    "input",
    "input_messages",
    "input_value",
    "messages",
    "output",
    "output_messages",
    "output_value",
    "redacted_input",
    "redacted_output",
}


def content_key_state(key: Any, value: Any) -> str:
    normalized_key = normalized_content_key(key)
    if normalized_key in MESSAGE_CONTAINER_KEYS or normalized_key.endswith("_messages"):
        return structured_content_state(value)
    return content_state(value)


def structured_content_state(value: Any) -> str:
    if isinstance(value, str):
        direct = content_state(value)
        if direct != "present":
            return direct
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                decoded = json.loads(stripped)
            except (json.JSONDecodeError, RecursionError):
                return "present"
            if isinstance(decoded, (dict, list)):
                return structured_content_state(decoded)
        return "present"

    pending = [value]
    saw_redacted = False
    visited = 0
    while pending:
        item = pending.pop()
        visited += 1
        if visited > MAX_PRIVACY_NODES:
            return "present"
        if item in (None, "", [], {}):
            continue
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized_key = normalized_content_key(key)
                if is_content_bearing_key(key):
                    state = content_key_state(key, nested)
                    if state == "present":
                        return "present"
                    if state == "redacted":
                        saw_redacted = True
                elif normalized_key == "role":
                    if nested not in {"assistant", "developer", "system", "tool", "user"}:
                        return "present"
                elif normalized_key in STRUCTURAL_CONTENT_KEYS:
                    continue
                elif isinstance(nested, (dict, list, tuple)):
                    pending.append(nested)
                elif nested not in (None, ""):
                    return "present"
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
        else:
            state = content_state(item)
            if state == "present":
                return "present"
            if state == "redacted":
                saw_redacted = True
    return "redacted" if saw_redacted else "absent"


def flatten_native_spans(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        raise BridgeError("reconcile_shape_invalid")
    result: list[dict[str, Any]] = []
    pending = list(reversed(values))
    while pending:
        item = pending.pop()
        if not isinstance(item, dict):
            raise BridgeError("reconcile_shape_invalid")
        result.append(item)
        children = item.get("spans", [])
        if not isinstance(children, list):
            raise BridgeError("reconcile_shape_invalid")
        pending.extend(reversed(children))
    return result


class GalileoClient:
    def __init__(self, config: Config, api_key: str) -> None:
        self.config = config
        self.api_key = api_key

    def _json_request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        *,
        deadline: float,
    ) -> tuple[int, Any]:
        headers = {
            "Accept": "application/json",
            "Splunk-AO-API-Key": self.api_key,
            "User-Agent": "galileo-amd-otlp-bridge/1.0",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api-demo-amd.gcp-dev.galileo.ai"
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.path.startswith(f"/v2/projects/{self.config.project_id}/")
            or parsed.query
            or parsed.fragment
        ):
            raise BridgeError("galileo_url_invalid")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BridgeError("galileo_deadline_exceeded")
        connection = http.client.HTTPSConnection(
            "127.0.0.1",
            18889,
            timeout=remaining,
            context=ssl.create_default_context(),
        )
        connection.set_tunnel(
            parsed.hostname,
            port=443,
            headers={"User-Agent": "galileo-amd-otlp-bridge/1.0"},
        )

        def abort_request() -> None:
            try:
                if connection.sock is not None:
                    connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

        timer = threading.Timer(remaining, abort_request)
        timer.daemon = True
        timer.start()
        try:
            connection.request(
                method,
                parsed.path,
                body=data,
                headers={**headers, "Connection": "close"},
            )
            response = connection.getresponse()
            status_code = response.status
            chunks: list[bytes] = []
            total = 0
            while True:
                if time.monotonic() >= deadline:
                    raise BridgeError("galileo_deadline_exceeded")
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise BridgeError("galileo_response_too_large")
                chunks.append(chunk)
            body = b"".join(chunks)
        except BridgeError:
            raise
        except (http.client.HTTPException, ssl.SSLError, TimeoutError, OSError) as exc:
            raise BridgeError("galileo_request_failed") from exc
        finally:
            timer.cancel()
            connection.close()
        try:
            document = json.loads(body) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise BridgeError("galileo_response_invalid") from exc
        return status_code, document

    @staticmethod
    def _duplicate_ids(response: Any) -> set[str]:
        if not isinstance(response, dict) or not isinstance(response.get("detail"), str):
            raise BridgeError("duplicate_detail_invalid")
        detail = response["detail"]
        if not detail.startswith(DUPLICATE_PREFIX + " "):
            raise BridgeError("duplicate_detail_invalid")
        raw_ids = detail[len(DUPLICATE_PREFIX) + 1 :].split(", ")
        if not raw_ids or any(not UUID4.fullmatch(item.lower()) for item in raw_ids):
            raise BridgeError("duplicate_detail_invalid")
        return {str(uuid.UUID(item)) for item in raw_ids}

    def ingest_many(
        self,
        translated: list[tuple[dict[str, Any], dict[str, ExpectedSpan]]],
    ) -> int:
        if not translated:
            return 0
        deadline = time.monotonic() + self.config.request_timeout_seconds
        pending = list(translated)
        duplicate_count = 0
        while pending:
            traces = [trace for trace, _expected in pending]
            payload = {
                "log_stream_id": self.config.log_stream_id,
                "logging_method": "api_direct",
                "reliable": True,
                "is_complete": True,
                "include_trace_ids": True,
                "traces": traces,
            }
            status_code, response = self._json_request(
                "POST", self.config.traces_url, payload, deadline=deadline
            )
            if status_code == HTTPStatus.OK:
                if not isinstance(response, dict):
                    raise BridgeError("galileo_success_invalid")
                root_ids = [trace["id"] for trace, _expected in pending]
                span_count = sum(len(expected) for _trace, expected in pending)
                if (
                    response.get("project_id") != self.config.project_id
                    or response.get("log_stream_id") != self.config.log_stream_id
                    or response.get("traces_count") != len(pending)
                    or response.get("spans_count") != span_count
                    or response.get("records_count") != len(pending) + span_count
                    or response.get("trace_ids") != root_ids
                ):
                    raise BridgeError("galileo_success_mismatch")
                return duplicate_count
            if status_code == HTTPStatus.UNPROCESSABLE_ENTITY:
                duplicate_ids = self._duplicate_ids(response)
                duplicate_traces: list[tuple[dict[str, Any], dict[str, ExpectedSpan]]] = []
                remaining_traces: list[tuple[dict[str, Any], dict[str, ExpectedSpan]]] = []
                accounted: set[str] = set()
                for trace, expected in pending:
                    record_ids = {trace["id"], *expected.keys()}
                    overlap = record_ids & duplicate_ids
                    if overlap:
                        if overlap != record_ids:
                            raise BridgeError("duplicate_partial_trace")
                        duplicate_traces.append((trace, expected))
                        accounted.update(record_ids)
                    else:
                        remaining_traces.append((trace, expected))
                if not duplicate_traces or accounted != duplicate_ids:
                    raise BridgeError("duplicate_detail_mismatch")
                for trace, expected in duplicate_traces:
                    self._reconcile(trace, expected, deadline)
                duplicate_count += len(duplicate_traces)
                pending = remaining_traces
                continue
            if status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
                raise BridgeError("galileo_auth_failed")
            if status_code == HTTPStatus.TOO_MANY_REQUESTS:
                raise BridgeError("galileo_rate_limited")
            raise BridgeError("galileo_ingest_failed")
        return duplicate_count

    def _reconcile(
        self,
        trace: dict[str, Any],
        expected: dict[str, ExpectedSpan],
        deadline: float,
    ) -> None:
        root_id = trace["id"]
        search_url = (
            f"{self.config.api_origin}/v2/projects/{self.config.project_id}/traces/search"
        )
        search_payload = {
            "starting_token": 0,
            "limit": 10,
            "log_stream_id": self.config.log_stream_id,
            "filters": [
                {
                    "type": "id",
                    "column_id": "id",
                    "operator": "eq",
                    "value": root_id,
                }
            ],
            "truncate_fields": True,
            "include_counts": True,
            "include_code_metric_metadata": False,
        }
        search_status, search = self._json_request(
            "POST", search_url, search_payload, deadline=deadline
        )
        if search_status != HTTPStatus.OK or not isinstance(search, dict):
            raise BridgeError("duplicate_search_failed")
        records = search.get("records")
        if (
            search.get("starting_token") != 0
            or search.get("limit") != 10
            or search.get("num_records") != 1
            or search.get("paginated") is not False
            or search.get("last_row_id") != root_id
            or not isinstance(records, list)
            or len(records) != 1
        ):
            raise BridgeError("duplicate_search_mismatch")
        record = records[0]
        if not isinstance(record, dict) or (
            record.get("id") != root_id
            or record.get("trace_id") != root_id
            or record.get("project_id") != self.config.project_id
            or record.get("run_id") != self.config.log_stream_id
            or record.get("external_id") != trace["external_id"]
            or record.get("type") != "trace"
            or record.get("is_complete") is not True
            or record.get("num_spans") != len(expected)
        ):
            raise BridgeError("duplicate_search_mismatch")
        url = f"{self.config.api_origin}/v2/projects/{self.config.project_id}/traces/{root_id}"
        status_code, detail = self._json_request("GET", url, deadline=deadline)
        if status_code != HTTPStatus.OK or not isinstance(detail, dict):
            raise BridgeError("duplicate_reconcile_failed")
        if (
            detail.get("id") != root_id
            or detail.get("trace_id") != root_id
            or detail.get("project_id") != self.config.project_id
            or detail.get("external_id") != trace["external_id"]
            or detail.get("is_complete") is not True
            or detail.get("type") != "trace"
            or detail.get("name") != "lemonade.chat"
            or detail.get("run_id") != self.config.log_stream_id
            or detail.get("num_spans") not in (None, len(expected))
        ):
            raise BridgeError("duplicate_reconcile_mismatch")
        assert_private_payload(detail)
        actual: dict[str, ExpectedSpan] = {}
        for span in flatten_native_spans(detail.get("spans")):
            span_id = span.get("id")
            span_type_value = span.get("type")
            parent_id = span.get("parent_id")
            external_id = span.get("external_id")
            if not all(
                isinstance(item, str)
                for item in (span_id, span_type_value, parent_id, external_id)
            ):
                raise BridgeError("duplicate_reconcile_mismatch")
            if span_id in actual:
                raise BridgeError("duplicate_reconcile_mismatch")
            if (
                span.get("trace_id") != root_id
                or span.get("project_id") != self.config.project_id
                or span.get("run_id") != self.config.log_stream_id
                or span.get("is_complete") is not True
                or span.get("name") != TYPE_NAMES.get(span_type_value)
            ):
                raise BridgeError("duplicate_reconcile_mismatch")
            actual[span_id] = ExpectedSpan(span_type_value, parent_id, external_id)
        if actual != expected:
            raise BridgeError("duplicate_reconcile_mismatch")


class Metrics:
    NAMES = (
        "requests_total",
        "requests_failed_total",
        "traces_received_total",
        "spans_received_total",
        "traces_ingested_total",
        "duplicates_reconciled_total",
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values = {name: 0 for name in self.NAMES}

    def add(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._values[name] += amount

    def render(self) -> bytes:
        with self._lock:
            values = dict(self._values)
        lines = [f"galileo_amd_bridge_{name} {values[name]}" for name in self.NAMES]
        return ("\n".join(lines) + "\n").encode("ascii")


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config: Config, client: GalileoClient, metrics: Metrics) -> None:
        super().__init__((config.bind_host, config.bind_port), BridgeHandler)
        self.config = config
        self.galileo_client = client
        self.metrics = metrics
        self.semaphore = threading.BoundedSemaphore(config.max_concurrent_requests)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self.semaphore.acquire(blocking=False):
            self.metrics.add("requests_failed_total")
            try:
                request.settimeout(1)
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.semaphore.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.semaphore.release()


class BridgeHandler(BaseHTTPRequestHandler):
    server: BridgeServer
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(CLIENT_SOCKET_TIMEOUT_SECONDS)

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(HTTPStatus.OK, b'{"status":"ok"}\n', "application/json")
            return
        if self.path == "/metrics":
            self._send(HTTPStatus.OK, self.server.metrics.render(), "text/plain; version=0.0.4")
            return
        self._send(HTTPStatus.NOT_FOUND, b"", "text/plain")

    def do_POST(self) -> None:
        self.server.metrics.add("requests_total")
        if self.path != "/v1/traces":
            self.server.metrics.add("requests_failed_total")
            self._send(HTTPStatus.NOT_FOUND, b"", "text/plain")
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/x-protobuf":
            self.server.metrics.add("requests_failed_total")
            self._send(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, b"", "text/plain")
            return
        if self.headers.get("Content-Encoding", "identity").strip().lower() not in ("", "identity"):
            self.server.metrics.add("requests_failed_total")
            self._send(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, b"", "text/plain")
            return
        if self.headers.get("Transfer-Encoding"):
            self.server.metrics.add("requests_failed_total")
            self._send(HTTPStatus.BAD_REQUEST, b"", "text/plain")
            return
        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError:
            length = -1
        if not 0 <= length <= self.server.config.max_request_bytes:
            self.server.metrics.add("requests_failed_total")
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b"", "text/plain")
            return
        try:
            try:
                body = self.rfile.read(length)
            except (TimeoutError, OSError) as exc:
                raise ClientRequestError("request_read_failed") from exc
            if len(body) != length:
                raise ClientRequestError("request_short_read")
            request = ExportTraceServiceRequest()
            try:
                request.ParseFromString(body)
            except Exception as exc:
                raise ClientRequestError("protobuf_invalid") from exc
            translated = translate_request(request, self.server.config)
            span_count = sum(len(expected) for _trace, expected in translated)
            self.server.metrics.add("traces_received_total", len(translated))
            self.server.metrics.add("spans_received_total", span_count)
            duplicate_count = self.server.galileo_client.ingest_many(translated)
            for trace, expected in translated:
                trace_hash = hashlib.sha256(trace["external_id"].encode("ascii")).hexdigest()[:16]
                logging.info("event=trace_ingested trace_hash=%s spans=%d", trace_hash, len(expected))
            self.server.metrics.add("traces_ingested_total", len(translated))
            self.server.metrics.add("duplicates_reconciled_total", duplicate_count)
            response = ExportTraceServiceResponse().SerializeToString()
            self._send(HTTPStatus.OK, response, "application/x-protobuf")
        except ClientRequestError as exc:
            self.server.metrics.add("requests_failed_total")
            logging.warning("event=request_rejected code=%s", exc.code)
            self._send(HTTPStatus.BAD_REQUEST, b"", "text/plain")
        except BridgeError as exc:
            self.server.metrics.add("requests_failed_total")
            logging.warning("event=request_failed code=%s", exc.code)
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, b"", "text/plain")
        except Exception:
            self.server.metrics.add("requests_failed_total")
            logging.error("event=request_failed code=unexpected")
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, b"", "text/plain")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(args.config)
    api_key = read_api_key(config.api_key_file)
    if args.check:
        print(
            json.dumps(
                {
                    "api_origin": config.api_origin,
                    "bind": f"{config.bind_host}:{config.bind_port}",
                    "log_stream_id": config.log_stream_id,
                    "ok": True,
                    "project_id": config.project_id,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return
    client = GalileoClient(config, api_key)
    server = BridgeServer(config, client, Metrics())

    def stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logging.info("event=bridge_started bind=%s:%d", config.bind_host, config.bind_port)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        logging.info("event=bridge_stopped")


if __name__ == "__main__":
    main()
