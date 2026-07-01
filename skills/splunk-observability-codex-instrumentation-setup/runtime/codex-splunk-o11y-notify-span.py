#!/usr/bin/env python3
"""Emit metadata-only Codex turn telemetry to an OTLP/HTTP destination.

This program deliberately has no runtime package installation behavior.  The
companion installer creates a pinned virtual environment before the notifier is
enabled.  Keep imports from that environment lazy so the parser and resource
contract remain testable with the repository's standard Python runtime.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib
import importlib.metadata
import json
import os
import pathlib
import re
import socket
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlsplit


DEFAULT_SERVICE_NAME = "codex-cli"
DEFAULT_ENVIRONMENT = "prod"
DEFAULT_REALM = "us0"
RUNTIME_CONFIG_NAME = "codex-splunk-o11y-runtime.json"
STATE_FILE_NAME = "codex-splunk-o11y-emitted-turns.json"
OUTBOX_FILE_NAME = "codex-splunk-o11y-outbox.json"
SUPPORTED_EVENTS = {"turn-ended", "agent-turn-complete"}
REQUIRED_DISTRIBUTIONS = {
    "opentelemetry-api": "1.38.0",
    "opentelemetry-sdk": "1.38.0",
    "opentelemetry-exporter-otlp-proto-http": "1.38.0",
}
GENAI_DURATION_BUCKET_BOUNDARIES = (
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
GENAI_TOKEN_BUCKET_BOUNDARIES = (
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


@dataclass
class TurnRecord:
    turn_id: str
    session_id: str
    session_file: pathlib.Path
    model: str = "unknown"
    started_at: float | None = None
    completed_at: float | None = None
    duration_s: float | None = None
    time_to_first_token_s: float | None = None
    user_message_count: int = 0
    assistant_message_count: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    tool_names: list[str] = field(default_factory=list)
    retrieval_count: int = 0
    completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "session_file": str(self.session_file),
            "model": self.model,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_s": self.duration_s,
            "time_to_first_token_s": self.time_to_first_token_s,
            "user_message_count": self.user_message_count,
            "assistant_message_count": self.assistant_message_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "tool_names": self.tool_names,
            "retrieval_count": self.retrieval_count,
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TurnRecord":
        def optional_number(key: str) -> float | None:
            item = value.get(key)
            return float(item) if isinstance(item, (int, float)) else None

        def optional_int(key: str) -> int | None:
            item = value.get(key)
            return int(item) if isinstance(item, int) and item >= 0 else None

        names = value.get("tool_names")
        tool_names = [str(item) for item in names if isinstance(item, str)] if isinstance(names, list) else []
        return cls(
            turn_id=str(value.get("turn_id") or ""),
            session_id=str(value.get("session_id") or ""),
            session_file=pathlib.Path(str(value.get("session_file") or "unknown.jsonl")),
            model=str(value.get("model") or "unknown"),
            started_at=optional_number("started_at"),
            completed_at=optional_number("completed_at"),
            duration_s=optional_number("duration_s"),
            time_to_first_token_s=optional_number("time_to_first_token_s"),
            user_message_count=optional_int("user_message_count") or 0,
            assistant_message_count=optional_int("assistant_message_count") or 0,
            input_tokens=optional_int("input_tokens"),
            output_tokens=optional_int("output_tokens"),
            cached_input_tokens=optional_int("cached_input_tokens"),
            reasoning_output_tokens=optional_int("reasoning_output_tokens"),
            tool_names=tool_names,
            retrieval_count=optional_int("retrieval_count") or 0,
            completed=bool(value.get("completed")),
        )


@dataclass(frozen=True)
class SpanPlan:
    name: str
    operation: str
    parent: int | None
    kind: str
    attributes: dict[str, str | int | float | bool]


def _codex_home() -> pathlib.Path:
    configured = os.environ.get("CODEX_HOME", "").strip()
    return pathlib.Path(configured).expanduser() if configured else pathlib.Path.home() / ".codex"


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def runtime_config() -> dict[str, Any]:
    codex_home = _codex_home()
    config_path = pathlib.Path(
        os.environ.get("CODEX_SPLUNK_O11Y_RUNTIME_CONFIG", codex_home / RUNTIME_CONFIG_NAME)
    ).expanduser()
    stored = _read_json(config_path)
    realm = os.environ.get("SPLUNK_REALM", str(stored.get("realm") or DEFAULT_REALM)).strip()
    service = os.environ.get(
        "CODEX_OTEL_SERVICE_NAME",
        os.environ.get("OTEL_SERVICE_NAME", str(stored.get("service_name") or DEFAULT_SERVICE_NAME)),
    ).strip()
    environment = os.environ.get(
        "CODEX_OTEL_ENVIRONMENT",
        os.environ.get("SPLUNK_ENVIRONMENT", str(stored.get("environment") or DEFAULT_ENVIRONMENT)),
    ).strip()
    trace_endpoint = os.environ.get(
        "CODEX_SPLUNK_TRACE_ENDPOINT",
        str(stored.get("trace_endpoint") or f"https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp"),
    ).strip()
    metrics_endpoint = os.environ.get(
        "CODEX_SPLUNK_METRICS_ENDPOINT",
        str(stored.get("metrics_endpoint") or f"https://ingest.{realm}.observability.splunkcloud.com/v2/datapoint/otlp"),
    ).strip()
    if not service:
        raise ValueError("service_name must not be empty")
    if not environment:
        raise ValueError("environment must not be empty")
    for label, endpoint in (("trace", trace_endpoint), ("metrics", metrics_endpoint)):
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"{label} endpoint must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password:
            raise ValueError(f"{label} endpoint must not contain credentials")
        if parsed.scheme == "http" and (parsed.hostname or "").lower() not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError(f"{label} endpoint must use HTTPS unless it is loopback")
    return {
        "config_path": str(config_path),
        "realm": realm,
        "service_name": service,
        "environment": environment,
        "trace_endpoint": trace_endpoint,
        "metrics_endpoint": metrics_endpoint,
    }


def resource_attributes(config: dict[str, Any]) -> dict[str, str]:
    service = str(config["service_name"])
    environment = str(config["environment"])
    return {
        "service.name": service,
        "sf_service": service,
        "deployment.environment": environment,
        "deployment.environment.name": environment,
        "sf_environment": environment,
        "host.name": socket.gethostname(),
        "gen_ai.agent.name": "codex",
        "gen_ai.framework": "codex",
    }


def _parse_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _find_value(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys:
                return child
            found = _find_value(child, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_value(child, keys)
            if found is not None:
                return found
    return None


def parse_payload(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _session_id_from_path(path: pathlib.Path) -> str:
    stem = path.stem
    return stem.removeprefix("rollout-") if stem.startswith("rollout-") else stem


def _is_under(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def session_file_from_payload(payload: dict[str, Any]) -> pathlib.Path | None:
    candidate = _find_value(
        payload,
        {"session_path", "session_file", "transcript_path", "rollout_path"},
    )
    if not isinstance(candidate, str) or not candidate.endswith(".jsonl"):
        return None
    path = pathlib.Path(candidate).expanduser()
    sessions = _codex_home() / "sessions"
    return path if path.is_file() and _is_under(path, sessions) else None


def session_file_from_thread_id(payload: dict[str, Any]) -> pathlib.Path | None:
    thread_id = _find_value(
        payload,
        {"thread-id", "thread_id", "conversation-id", "conversation_id", "session-id", "session_id"},
    )
    if not isinstance(thread_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{8,128}", thread_id):
        return None
    sessions = _codex_home() / "sessions"
    try:
        candidates = list(sessions.glob(f"*/*/*/*{thread_id}*.jsonl"))
        return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None
    except OSError:
        return None


def turn_id_from_payload(payload: dict[str, Any]) -> str:
    value = _find_value(payload, {"turn-id", "turn_id"})
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9-]{8,128}", value) else ""


def latest_session_file(payload: dict[str, Any], explicit: str = "") -> pathlib.Path | None:
    if explicit:
        path = pathlib.Path(explicit).expanduser()
        return path if path.is_file() else None
    payload_path = session_file_from_payload(payload)
    if payload_path is not None:
        return payload_path
    thread_path = session_file_from_thread_id(payload)
    if thread_path is not None:
        return thread_path
    sessions = _codex_home() / "sessions"
    try:
        candidates = list(sessions.glob("*/*/*/*.jsonl"))
        return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None
    except OSError:
        return None


def configured_model() -> str:
    configured = os.environ.get("CODEX_MODEL", "").strip()
    if configured:
        return configured
    try:
        import tomllib

        with (_codex_home() / "config.toml").open("rb") as handle:
            value = tomllib.load(handle).get("model")
        return value if isinstance(value, str) and value else "unknown"
    except (OSError, ValueError):
        return "unknown"


def load_session_turns(path: pathlib.Path) -> list[TurnRecord]:
    """Parse only metadata needed for telemetry; never retain message/tool content."""

    turns: dict[str, TurnRecord] = {}
    order: list[str] = []
    current_turn_id: str | None = None
    session_id = _session_id_from_path(path)
    model = configured_model()

    def record(turn_id: str) -> TurnRecord:
        if turn_id not in turns:
            turns[turn_id] = TurnRecord(turn_id, session_id, path, model=model)
            order.append(turn_id)
        return turns[turn_id]

    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return []
    with handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            payload_type = payload.get("type")

            if item.get("type") == "session_meta":
                candidate = payload.get("session_id") or payload.get("id")
                if isinstance(candidate, str) and candidate:
                    session_id = candidate
                candidate_model = payload.get("model")
                if isinstance(candidate_model, str) and candidate_model:
                    model = candidate_model
                continue

            metadata = payload.get("internal_chat_message_metadata_passthrough")
            metadata = metadata if isinstance(metadata, dict) else {}
            turn_id_value = payload.get("turn_id") or metadata.get("turn_id") or current_turn_id

            if payload_type == "task_started":
                candidate = payload.get("turn_id")
                current_turn_id = candidate if isinstance(candidate, str) and candidate else f"turn-{line_number}"
                turn = record(current_turn_id)
                turn.session_id = session_id
                turn.model = model
                turn.started_at = _parse_timestamp(payload.get("started_at")) or _parse_timestamp(item.get("timestamp"))
                continue

            if not isinstance(turn_id_value, str) or not turn_id_value:
                continue
            turn = record(turn_id_value)
            turn.session_id = session_id
            turn.model = model

            if payload_type == "task_complete":
                turn.completed = True
                turn.completed_at = _parse_timestamp(payload.get("completed_at")) or _parse_timestamp(item.get("timestamp"))
                duration_ms = payload.get("duration_ms")
                if isinstance(duration_ms, (int, float)):
                    turn.duration_s = max(0.0, float(duration_ms) / 1000.0)
                ttft_ms = payload.get("time_to_first_token_ms")
                if isinstance(ttft_ms, (int, float)):
                    turn.time_to_first_token_s = max(0.0, float(ttft_ms) / 1000.0)
                if isinstance(payload.get("last_agent_message"), str):
                    turn.assistant_message_count += 1
                if current_turn_id == turn_id_value:
                    current_turn_id = None
                continue

            if payload_type == "user_message" or (
                payload_type == "message" and payload.get("role") == "user"
            ):
                turn.user_message_count += 1
                continue

            if payload_type == "agent_message" or (
                payload_type == "message" and payload.get("role") == "assistant"
            ):
                turn.assistant_message_count += 1
                continue

            if payload_type == "token_count":
                info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
                usage = info.get("last_token_usage") if isinstance(info.get("last_token_usage"), dict) else {}
                for source, target in (
                    ("input_tokens", "input_tokens"),
                    ("output_tokens", "output_tokens"),
                    ("cached_input_tokens", "cached_input_tokens"),
                    ("reasoning_output_tokens", "reasoning_output_tokens"),
                ):
                    value = usage.get(source)
                    if isinstance(value, int) and value >= 0:
                        setattr(turn, target, value)
                continue

            if payload_type in {"function_call", "custom_tool_call"}:
                name = payload.get("name")
                turn.tool_names.append(name if isinstance(name, str) and name else "unknown_tool")
                continue

            if payload_type in {"web_search_call", "web_search_end"}:
                if payload_type == "web_search_call":
                    turn.retrieval_count += 1

    return [turns[turn_id] for turn_id in order]


def latest_completed_turn(path: pathlib.Path) -> TurnRecord | None:
    turns = load_session_turns(path)
    completed = [turn for turn in turns if turn.completed]
    return completed[-1] if completed else None


def completed_turn_for_payload(path: pathlib.Path, payload: dict[str, Any]) -> TurnRecord | None:
    turns = [turn for turn in load_session_turns(path) if turn.completed]
    requested = turn_id_from_payload(payload)
    if requested:
        return next((turn for turn in turns if turn.turn_id == requested), None)
    return turns[-1] if turns else None


def span_plan(turn: TurnRecord, event_name: str, *, synthetic: bool = False) -> list[SpanPlan]:
    duration = max(0.001, turn.duration_s or 0.001)
    common: dict[str, str | int | float | bool] = {
        "gen_ai.system": "openai",
        "gen_ai.provider.name": "openai",
        "gen_ai.framework": "codex",
        "gen_ai.agent.name": "codex",
        "gen_ai.conversation.id": turn.session_id,
        "codex.turn.id": turn.turn_id,
        "codex.event.name": event_name,
        "codex.content_captured": False,
        "codex.synthetic": synthetic,
    }
    plans = [
        SpanPlan(
            "codex.turn",
            "invoke_workflow",
            None,
            "internal",
            {
                **common,
                "gen_ai.workflow.name": "codex.turn",
                "codex.user_message.count": turn.user_message_count,
                "codex.assistant_message.count": turn.assistant_message_count,
                "codex.tool.count": len(turn.tool_names),
                "codex.retrieval.count": turn.retrieval_count,
                "codex.turn.duration": duration,
            },
        ),
        SpanPlan(
            "invoke_agent codex",
            "invoke_agent",
            0,
            "internal",
            {**common, "gen_ai.agent.id": turn.turn_id, "gen_ai.request.model": turn.model},
        ),
    ]
    token_attrs: dict[str, str | int | float | bool] = {
        **common,
        "gen_ai.request.model": turn.model,
        "gen_ai.response.model": turn.model,
    }
    for key, value in (
        ("gen_ai.usage.input_tokens", turn.input_tokens),
        ("gen_ai.usage.output_tokens", turn.output_tokens),
        ("gen_ai.usage.cached_input_tokens", turn.cached_input_tokens),
        ("gen_ai.usage.reasoning_tokens", turn.reasoning_output_tokens),
        ("gen_ai.response.time_to_first_token", turn.time_to_first_token_s),
    ):
        if value is not None:
            token_attrs[key] = value
    plans.append(SpanPlan(f"chat {turn.model}", "chat", 1, "client", token_attrs))
    for name in turn.tool_names:
        plans.append(
            SpanPlan(
                f"execute_tool {name}",
                "execute_tool",
                1,
                "internal",
                {**common, "gen_ai.tool.name": name},
            )
        )
    for index in range(turn.retrieval_count):
        plans.append(
            SpanPlan(
                "retrieval web_search",
                "retrieval",
                1,
                "client",
                {**common, "gen_ai.retrieval.type": "web_search", "codex.retrieval.index": index},
            )
        )
    return plans


def _required_imports() -> dict[str, str]:
    failures: dict[str, str] = {}
    modules = (
        "opentelemetry.trace",
        "opentelemetry.sdk.metrics",
        "opentelemetry.sdk.resources",
        "opentelemetry.sdk.trace",
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    )
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - depends on broken runtime
            failures[name] = f"{type(exc).__name__}: {exc}"
    return failures


def health_report(config: dict[str, Any]) -> dict[str, Any]:
    versions: dict[str, str] = {}
    version_errors: dict[str, str] = {}
    for distribution, expected in REQUIRED_DISTRIBUTIONS.items():
        try:
            actual = importlib.metadata.version(distribution)
            versions[distribution] = actual
            if actual != expected:
                version_errors[distribution] = f"expected {expected}, found {actual}"
        except importlib.metadata.PackageNotFoundError:
            version_errors[distribution] = "not installed"
    imports = _required_imports()
    attrs = resource_attributes(config)
    required_attrs = {"service.name", "sf_service", "deployment.environment", "sf_environment"}
    missing_attrs = sorted(required_attrs - attrs.keys())
    return {
        "ok": not imports and not version_errors and not missing_attrs,
        "python": sys.executable,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "versions": versions,
        "version_errors": version_errors,
        "import_errors": imports,
        "resource_attributes": attrs,
        "missing_resource_attributes": missing_attrs,
        "trace_endpoint": config["trace_endpoint"],
        "metrics_endpoint": config["metrics_endpoint"],
        "token_present": bool(os.environ.get("SPLUNK_ACCESS_TOKEN")),
        "config_path": config["config_path"],
    }


def _span_times(turn: TurnRecord) -> tuple[int, int]:
    end = turn.completed_at or time.time()
    duration = max(0.001, turn.duration_s or 0.001)
    start = turn.started_at if turn.started_at and turn.started_at <= end else end - duration
    return int(start * 1_000_000_000), int(end * 1_000_000_000)


def _emit_plans(provider: Any, plans: list[SpanPlan], turn: TurnRecord) -> str:
    trace = importlib.import_module("opentelemetry.trace")
    tracer = provider.get_tracer("codex.splunk.notify", "1.0.0")
    start_ns, end_ns = _span_times(turn)
    spans: list[Any] = []
    for plan in plans:
        parent_context = None
        if plan.parent is not None:
            parent_context = trace.set_span_in_context(spans[plan.parent])
        kind = trace.SpanKind.CLIENT if plan.kind == "client" else trace.SpanKind.INTERNAL
        span = tracer.start_span(plan.name, context=parent_context, kind=kind, start_time=start_ns)
        span.set_attribute("gen_ai.operation.name", plan.operation)
        for key, value in plan.attributes.items():
            span.set_attribute(key, value)
        spans.append(span)
    trace_id = f"{spans[0].get_span_context().trace_id:032x}"
    for span in reversed(spans):
        span.end(end_time=end_ns)
    return trace_id


def _record_metrics(meter_provider: Any, turn: TurnRecord) -> None:
    meter = meter_provider.get_meter("codex.splunk.notify", "1.0.0")
    common_attrs = {
        "gen_ai.agent.name": "codex",
        "gen_ai.framework": "codex",
        "gen_ai.provider.name": "openai",
        "gen_ai.system": "openai",
        "gen_ai.request.model": turn.model,
        "gen_ai.response.model": turn.model,
    }
    duration = max(0.001, turn.duration_s or 0.001)
    workflow_attrs = {
        **common_attrs,
        "gen_ai.operation.name": "invoke_workflow",
        "gen_ai.workflow.name": "codex.turn",
    }
    agent_attrs = {**common_attrs, "gen_ai.operation.name": "invoke_agent"}
    client_attrs = {**common_attrs, "gen_ai.operation.name": "chat"}
    duration_kwargs = {
        "unit": "s",
        "explicit_bucket_boundaries_advisory": GENAI_DURATION_BUCKET_BOUNDARIES,
    }
    meter.create_histogram("gen_ai.workflow.duration", **duration_kwargs).record(duration, workflow_attrs)
    meter.create_histogram("gen_ai.agent.duration", **duration_kwargs).record(duration, agent_attrs)
    meter.create_histogram("gen_ai.client.operation.duration", **duration_kwargs).record(duration, client_attrs)
    token_histogram = meter.create_histogram(
        "gen_ai.client.token.usage",
        unit="{token}",
        explicit_bucket_boundaries_advisory=GENAI_TOKEN_BUCKET_BOUNDARIES,
    )
    if turn.input_tokens is not None:
        token_histogram.record(turn.input_tokens, {**client_attrs, "gen_ai.token.type": "input"})
    if turn.output_tokens is not None:
        token_histogram.record(turn.output_tokens, {**client_attrs, "gen_ai.token.type": "output"})
    meter.create_counter("codex.turns").add(1, workflow_attrs)


class _ConfirmingSpanExporter:
    """Wrap the OTLP exporter so dedupe state advances only after a successful export."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.successful_batches = 0
        self.failed_batches = 0

    def export(self, spans: Iterable[Any]) -> Any:
        result = self.delegate.export(spans)
        success = importlib.import_module("opentelemetry.sdk.trace.export").SpanExportResult.SUCCESS
        if result == success:
            self.successful_batches += 1
        else:
            self.failed_batches += 1
        return result

    def shutdown(self) -> None:
        self.delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        method = getattr(self.delegate, "force_flush", None)
        return bool(method(timeout_millis)) if method else True


def _headers_for(config: dict[str, Any]) -> dict[str, str]:
    token = os.environ.get("SPLUNK_ACCESS_TOKEN", "").strip()
    parsed = urlsplit(str(config["trace_endpoint"]))
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and hostname in {"127.0.0.1", "localhost", "::1"}:
        return {}
    trusted_splunk_ingest = bool(
        re.fullmatch(r"ingest\.[a-z0-9-]+\.observability\.splunkcloud\.com", hostname)
    )
    if trusted_splunk_ingest:
        if parsed.scheme != "https":
            raise RuntimeError("direct Splunk ingest requires HTTPS")
        if not token:
            raise RuntimeError("SPLUNK_ACCESS_TOKEN is required for direct Splunk ingest")
        return {"X-SF-TOKEN": token}
    # Arbitrary external collectors are intentionally tokenless. Never attach a
    # Splunk credential merely because it happens to be present in the process.
    return {}


def _delta_metric_temporality(metrics_sdk: Any, metrics_export: Any) -> dict[type, Any]:
    """Export GenAI histograms with explicit delta temporality."""

    delta = metrics_export.AggregationTemporality.DELTA
    return {metrics_sdk.Histogram: delta}


def emit_live(turn: TurnRecord, event_name: str, config: dict[str, Any], *, synthetic: bool = False) -> dict[str, Any]:
    failures = _required_imports()
    if failures:
        raise RuntimeError(f"runtime imports failed: {', '.join(sorted(failures))}")
    Resource = importlib.import_module("opentelemetry.sdk.resources").Resource
    TracerProvider = importlib.import_module("opentelemetry.sdk.trace").TracerProvider
    trace_export = importlib.import_module("opentelemetry.sdk.trace.export")
    OTLPSpanExporter = importlib.import_module(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter"
    ).OTLPSpanExporter
    metrics_sdk = importlib.import_module("opentelemetry.sdk.metrics")
    metrics_export = importlib.import_module("opentelemetry.sdk.metrics.export")
    OTLPMetricExporter = importlib.import_module(
        "opentelemetry.exporter.otlp.proto.http.metric_exporter"
    ).OTLPMetricExporter

    resource = Resource.create(resource_attributes(config))
    trace_headers = _headers_for({**config, "trace_endpoint": config["trace_endpoint"]})
    metric_headers = _headers_for({**config, "trace_endpoint": config["metrics_endpoint"]})
    confirming = _ConfirmingSpanExporter(
        OTLPSpanExporter(endpoint=config["trace_endpoint"], headers=trace_headers, timeout=10)
    )
    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(trace_export.SimpleSpanProcessor(confirming))
    metric_success = metrics_export.MetricExportResult.SUCCESS

    class ConfirmingMetricExporter(OTLPMetricExporter):
        def __init__(self) -> None:
            super().__init__(
                endpoint=config["metrics_endpoint"],
                headers=metric_headers,
                timeout=10,
                preferred_temporality=_delta_metric_temporality(metrics_sdk, metrics_export),
            )
            self.successful_batches = 0
            self.failed_batches = 0

        def export(self, metrics_data: Any, timeout_millis: float = 10_000, **kwargs: Any) -> Any:
            result = super().export(metrics_data, timeout_millis=timeout_millis, **kwargs)
            if result == metric_success:
                self.successful_batches += 1
            else:
                self.failed_batches += 1
            return result

    metric_exporter = ConfirmingMetricExporter()
    metric_reader = metrics_export.PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=60_000,
    )
    meter_provider = metrics_sdk.MeterProvider(resource=resource, metric_readers=[metric_reader])
    try:
        plans = span_plan(turn, event_name, synthetic=synthetic)
        trace_id = _emit_plans(trace_provider, plans, turn)
        _record_metrics(meter_provider, turn)
        traces_flushed = bool(trace_provider.force_flush(15_000))
        metrics_flushed = bool(meter_provider.force_flush(15_000))
        if not traces_flushed or confirming.failed_batches or not confirming.successful_batches:
            raise RuntimeError("OTLP trace exporter did not confirm a successful batch")
        if not metrics_flushed or metric_exporter.failed_batches or not metric_exporter.successful_batches:
            raise RuntimeError("OTLP metric exporter did not confirm a successful batch")
        return {
            "ok": True,
            "trace_id": trace_id,
            "trace_exported": True,
            "metrics_flushed": metrics_flushed,
            "service_name": config["service_name"],
            "environment": config["environment"],
        }
    finally:
        trace_provider.shutdown()
        meter_provider.shutdown()


def offline_smoke(config: dict[str, Any]) -> dict[str, Any]:
    failures = _required_imports()
    if failures:
        return {"ok": False, "import_errors": failures}
    Resource = importlib.import_module("opentelemetry.sdk.resources").Resource
    TracerProvider = importlib.import_module("opentelemetry.sdk.trace").TracerProvider
    trace_export = importlib.import_module("opentelemetry.sdk.trace.export")
    memory_export = importlib.import_module(
        "opentelemetry.sdk.trace.export.in_memory_span_exporter"
    ).InMemorySpanExporter
    turn = synthetic_turn()
    exporter = memory_export()
    provider = TracerProvider(resource=Resource.create(resource_attributes(config)))
    provider.add_span_processor(trace_export.SimpleSpanProcessor(exporter))
    trace_id = _emit_plans(provider, span_plan(turn, "turn-ended", synthetic=True), turn)
    provider.force_flush()
    spans = exporter.get_finished_spans()
    operations = sorted(
        {
            str(span.attributes.get("gen_ai.operation.name"))
            for span in spans
            if span.attributes.get("gen_ai.operation.name")
        }
    )
    attrs = dict(spans[0].resource.attributes) if spans else {}
    required_operations = {"invoke_workflow", "invoke_agent", "chat", "execute_tool", "retrieval"}
    required_attrs = resource_attributes(config)
    attrs_ok = all(attrs.get(key) == value for key, value in required_attrs.items())
    ok = required_operations.issubset(operations) and attrs_ok and len(trace_id) == 32
    provider.shutdown()
    return {
        "ok": ok,
        "trace_id": trace_id,
        "span_count": len(spans),
        "operations": operations,
        "resource_attributes": {key: attrs.get(key) for key in required_attrs},
        "network_used": False,
    }


def synthetic_turn() -> TurnRecord:
    now = time.time()
    return TurnRecord(
        turn_id=f"smoke-{int(now)}",
        session_id=f"smoke-session-{int(now)}",
        session_file=pathlib.Path("synthetic.jsonl"),
        model="codex-smoke-model",
        started_at=now - 0.05,
        completed_at=now,
        duration_s=0.05,
        time_to_first_token_s=0.01,
        user_message_count=1,
        assistant_message_count=1,
        input_tokens=8,
        output_tokens=4,
        cached_input_tokens=2,
        tool_names=["exec_command"],
        retrieval_count=1,
        completed=True,
    )


def _state_path() -> pathlib.Path:
    configured = os.environ.get("CODEX_SPLUNK_O11Y_STATE_FILE", "").strip()
    return pathlib.Path(configured).expanduser() if configured else _codex_home() / "log" / STATE_FILE_NAME


def _outbox_path() -> pathlib.Path:
    configured = os.environ.get("CODEX_SPLUNK_O11Y_OUTBOX_FILE", "").strip()
    return pathlib.Path(configured).expanduser() if configured else _codex_home() / "log" / OUTBOX_FILE_NAME


def _with_locked_json(path: pathlib.Path, callback: Any) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = _read_json(path)
        result = callback(state)
        if result is not None:
            fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(result, handle, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, path)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        return state


def already_emitted(turn_id: str) -> bool:
    state = _with_locked_json(_state_path(), lambda _state: None)
    return turn_id in state


def mark_emitted(turn_id: str, trace_id: str) -> None:
    def update(state: dict[str, Any]) -> dict[str, Any]:
        state[turn_id] = {"emitted_at": int(time.time()), "trace_id": trace_id}
        if len(state) > 500:
            recent = sorted(state.items(), key=lambda item: int(item[1].get("emitted_at", 0)))[-500:]
            state = dict(recent)
        return state

    _with_locked_json(_state_path(), update)


def enqueue_turn(turn: TurnRecord, event_name: str) -> None:
    """Durably queue metadata before attempting network export."""

    def update(outbox: dict[str, Any]) -> dict[str, Any]:
        if turn.turn_id not in outbox:
            outbox[turn.turn_id] = {
                "queued_at": int(time.time()),
                "event_name": event_name,
                "attempts": 0,
                "last_attempt_at": 0,
                "last_error_type": "",
                "turn": turn.to_dict(),
            }
        return outbox

    _with_locked_json(_outbox_path(), update)


def claim_pending_turn() -> tuple[TurnRecord, str] | None:
    """Claim the oldest item; stale claims become retryable after two minutes."""

    claimed: dict[str, Any] = {}
    now = int(time.time())

    def update(outbox: dict[str, Any]) -> dict[str, Any]:
        candidates = sorted(
            (
                (turn_id, entry)
                for turn_id, entry in outbox.items()
                if isinstance(entry, dict)
                and now - int(entry.get("last_attempt_at") or 0) >= 120
            ),
            key=lambda item: int(item[1].get("queued_at") or 0),
        )
        if not candidates:
            return outbox
        turn_id, entry = candidates[0]
        entry["last_attempt_at"] = now
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
        claimed["turn_id"] = turn_id
        claimed["entry"] = dict(entry)
        return outbox

    _with_locked_json(_outbox_path(), update)
    entry = claimed.get("entry")
    if not isinstance(entry, dict) or not isinstance(entry.get("turn"), dict):
        return None
    turn = TurnRecord.from_dict(entry["turn"])
    if not turn.turn_id:
        acknowledge_turn(str(claimed.get("turn_id") or ""))
        return None
    return turn, str(entry.get("event_name") or "turn-ended")


def acknowledge_turn(turn_id: str) -> None:
    def update(outbox: dict[str, Any]) -> dict[str, Any]:
        outbox.pop(turn_id, None)
        return outbox

    _with_locked_json(_outbox_path(), update)


def release_turn(turn_id: str, error_type: str) -> None:
    def update(outbox: dict[str, Any]) -> dict[str, Any]:
        entry = outbox.get(turn_id)
        if isinstance(entry, dict):
            # Permit the next notifier invocation to retry immediately. Only the
            # exception class is persisted; endpoint responses and content are not.
            entry["last_attempt_at"] = 0
            entry["last_error_type"] = error_type[:120]
        return outbox

    _with_locked_json(_outbox_path(), update)


def outbox_depth() -> int:
    outbox = _with_locked_json(_outbox_path(), lambda _outbox: None)
    return len(outbox)


def drain_outbox(config: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for _ in range(max(1, limit)):
        claimed = claim_pending_turn()
        if claimed is None:
            break
        turn, event_name = claimed
        if already_emitted(turn.turn_id):
            acknowledge_turn(turn.turn_id)
            continue
        try:
            result = emit_live(turn, event_name, config)
        except Exception as exc:
            release_turn(turn.turn_id, type(exc).__name__)
            raise
        mark_emitted(turn.turn_id, str(result["trace_id"]))
        acknowledge_turn(turn.turn_id)
        results.append(result)
    return results


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", default="turn-ended")
    parser.add_argument("--payload", default="")
    parser.add_argument("--payload-stdin", action="store_true")
    parser.add_argument("--session-file", default="")
    parser.add_argument("--allow-duplicate", action="store_true")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--offline-smoke", action="store_true")
    parser.add_argument("--live-smoke", action="store_true")
    parser.add_argument("--drain", action="store_true")
    args = parser.parse_args(argv)

    try:
        config = runtime_config()
        if args.health:
            report = health_report(config)
            _print_json(report)
            return 0 if report["ok"] else 2
        if args.offline_smoke:
            report = offline_smoke(config)
            _print_json(report)
            return 0 if report["ok"] else 2
        if args.live_smoke:
            _print_json(emit_live(synthetic_turn(), "turn-ended", config, synthetic=True))
            return 0
        if args.drain:
            results = drain_outbox(config)
            _print_json(
                {
                    "ok": True,
                    "exported": results,
                    "exported_count": len(results),
                    "outbox_depth": outbox_depth(),
                }
            )
            return 0
        if args.event not in SUPPORTED_EVENTS:
            return 0
        raw_payload = sys.stdin.read(2_000_000) if args.payload_stdin else args.payload
        payload = parse_payload(raw_payload)
        session_file = latest_session_file(payload, args.session_file)
        turn = completed_turn_for_payload(session_file, payload) if session_file is not None else None
        if turn is not None and (args.allow_duplicate or not already_emitted(turn.turn_id)):
            enqueue_turn(turn, args.event)
        results = drain_outbox(config)
        _print_json(
            {
                "ok": True,
                "exported": results,
                "exported_count": len(results),
                "outbox_depth": outbox_depth(),
            }
        )
        return 0
    except Exception as exc:
        # Do not print environment values, headers, payloads, or exception reprs that
        # could include request material.  The notifier records this safe summary.
        print(f"codex_splunk_o11y_error={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
