#!/usr/bin/env python3
"""Capture a small, sanitized evidence snapshot from a local OTel Collector.

The helper intentionally emits only health state, selected component IDs, and
the Collector v0.156 trace counters/gauges needed by the Lemonade runbook. It
does not copy endpoint URLs, response bodies, or arbitrary Prometheus labels
into its output.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "lemonade-collector-evidence/v1"
COLLECTOR_METRIC_BASELINE = "0.156"
DEFAULT_HEALTH_URL = "http://127.0.0.1:13133/"
DEFAULT_METRICS_URL = "http://127.0.0.1:8888/metrics"
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_TIMEOUT_SECONDS = 30.0
MAX_METRICS_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 1024 * 1024
MAX_SELECTED_SERIES = 10_000
MAX_METRIC_VALUE = (1 << 63) - 1

COMPONENT_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)?$"
)
METRIC_NAME_RE = re.compile(r"^[A-Za-z_:][A-Za-z0-9_:]*$")
LABEL_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class MetricSpec:
    __slots__ = ("component_label", "kind")

    def __init__(self, component_label: str, kind: str) -> None:
        self.component_label = component_label
        self.kind = kind


# These names are from Collector v0.156's receiverhelper/exporterhelper
# generated telemetry. Keep the explicit allowlist so a changed Collector
# surface fails visibly instead of silently copying unexpected metrics.
METRIC_SPECS: Mapping[str, MetricSpec] = {
    "otelcol_receiver_accepted_spans": MetricSpec("receiver", "counter"),
    "otelcol_receiver_failed_spans": MetricSpec("receiver", "counter"),
    "otelcol_receiver_refused_spans": MetricSpec("receiver", "counter"),
    "otelcol_exporter_sent_spans": MetricSpec("exporter", "counter"),
    "otelcol_exporter_send_failed_spans": MetricSpec("exporter", "counter"),
    "otelcol_exporter_enqueue_failed_spans": MetricSpec("exporter", "counter"),
    "otelcol_exporter_queue_size": MetricSpec("exporter", "gauge"),
    "otelcol_exporter_queue_capacity": MetricSpec("exporter", "gauge"),
    "otelcol_exporter_in_flight_requests": MetricSpec("exporter", "gauge"),
}


class EvidenceError(RuntimeError):
    """A safe-to-display evidence collection error."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects without reflecting a Location header or target URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise EvidenceError("HTTP redirects are not allowed")


def validate_component_id(value: str, option_name: str) -> str:
    if len(value) > 256 or not COMPONENT_ID_RE.fullmatch(value):
        raise EvidenceError(f"{option_name} must be a valid Collector component ID")
    return value


def validate_loopback_http_url(value: str, option_name: str) -> str:
    """Accept only explicit-port HTTP URLs whose host is a loopback IP literal."""

    if len(value) > 2048 or any(
        ord(char) < 0x20 or ord(char) == 0x7F for char in value
    ):
        raise EvidenceError(f"{option_name} is not a valid loopback HTTP URL")

    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise EvidenceError(f"{option_name} is not a valid loopback HTTP URL") from exc

    if (
        parsed.scheme != "http"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is None
        or port < 1
        or not parsed.hostname
    ):
        raise EvidenceError(f"{option_name} must be an explicit-port loopback HTTP URL")

    try:
        host = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise EvidenceError(
            f"{option_name} host must be a loopback IP literal"
        ) from exc
    if not host.is_loopback:
        raise EvidenceError(f"{option_name} host must be a loopback IP literal")

    # urlsplit normalizes the hostname accessor. Requiring the netloc to contain
    # no percent escape closes off alternate textual host representations.
    if "%" in parsed.netloc:
        raise EvidenceError(f"{option_name} is not a valid loopback HTTP URL")

    return value


def validate_timeout(value: float) -> float:
    if not math.isfinite(value) or value <= 0 or value > MAX_TIMEOUT_SECONDS:
        raise EvidenceError(
            f"timeout must be greater than zero and at most {MAX_TIMEOUT_SECONDS:g} seconds"
        )
    return value


def build_local_opener() -> urllib.request.OpenerDirector:
    """Build an opener that cannot inherit proxies and cannot follow redirects."""

    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirectHandler(),
    )


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "text/plain, application/openmetrics-text;q=0.9, */*;q=0.1",
            "Accept-Encoding": "identity",
            "User-Agent": "lemonade-collector-evidence/1",
        },
    )


def query_health(
    opener: urllib.request.OpenerDirector,
    url: str,
    timeout: float,
) -> dict[str, Any]:
    """Return health status without reading or returning the response body."""

    try:
        response = opener.open(_request(url), timeout=timeout)
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        exc.close()
        return {"ok": False, "status_code": status_code}
    except EvidenceError:
        raise
    except Exception as exc:
        raise EvidenceError("health endpoint request failed") from exc

    try:
        status_code = int(response.getcode())
    finally:
        response.close()
    return {"ok": 200 <= status_code < 300, "status_code": status_code}


def _bounded_response_bytes(response: Any, limit: int) -> bytes:
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding not in {"", "identity"}:
        raise EvidenceError("metrics endpoint returned an unsupported content encoding")

    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length, 10)
        except ValueError as exc:
            raise EvidenceError(
                "metrics endpoint returned an invalid content length"
            ) from exc
        if declared_length < 0 or declared_length > limit:
            raise EvidenceError("metrics response exceeds the size limit")

    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise EvidenceError("metrics response exceeds the size limit")
    return payload


def query_metrics_text(
    opener: urllib.request.OpenerDirector,
    url: str,
    timeout: float,
) -> str:
    try:
        response = opener.open(_request(url), timeout=timeout)
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        exc.close()
        raise EvidenceError(
            f"metrics endpoint returned HTTP status {status_code}"
        ) from exc
    except EvidenceError:
        raise
    except Exception as exc:
        raise EvidenceError("metrics endpoint request failed") from exc

    try:
        status_code = int(response.getcode())
        if not 200 <= status_code < 300:
            raise EvidenceError(f"metrics endpoint returned HTTP status {status_code}")
        payload = _bounded_response_bytes(response, MAX_METRICS_BYTES)
    finally:
        response.close()
    try:
        return payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EvidenceError("metrics endpoint did not return UTF-8 text") from exc


def _find_label_block_end(text: str, start: int) -> int:
    in_quotes = False
    escaped = False
    for index in range(start + 1, len(text)):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\" and in_quotes:
            escaped = True
        elif char == '"':
            in_quotes = not in_quotes
        elif char == "}" and not in_quotes:
            return index
    return -1


def _parse_labels(text: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    index = 0
    length = len(text)

    while index < length:
        while index < length and text[index].isspace():
            index += 1
        if index == length:
            break

        match = LABEL_NAME_RE.match(text, index)
        if match is None:
            raise EvidenceError("selected metric has malformed labels")
        name = match.group(0)
        if name in labels:
            raise EvidenceError("selected metric has duplicate labels")
        index = match.end()

        while index < length and text[index].isspace():
            index += 1
        if index >= length or text[index] != "=":
            raise EvidenceError("selected metric has malformed labels")
        index += 1
        while index < length and text[index].isspace():
            index += 1
        if index >= length or text[index] != '"':
            raise EvidenceError("selected metric has malformed labels")
        index += 1

        value_chars: list[str] = []
        while index < length:
            char = text[index]
            index += 1
            if char == '"':
                break
            if char != "\\":
                value_chars.append(char)
                continue
            if index >= length:
                raise EvidenceError("selected metric has malformed labels")
            escaped = text[index]
            index += 1
            escapes = {"\\": "\\", '"': '"', "n": "\n"}
            if escaped not in escapes:
                raise EvidenceError("selected metric has malformed labels")
            value_chars.append(escapes[escaped])
        else:
            raise EvidenceError("selected metric has malformed labels")

        labels[name] = "".join(value_chars)
        while index < length and text[index].isspace():
            index += 1
        if index == length:
            break
        if text[index] != ",":
            raise EvidenceError("selected metric has malformed labels")
        index += 1
        if index == length:
            raise EvidenceError("selected metric has malformed labels")

    return labels


def _parse_selected_sample(line: str) -> tuple[str, dict[str, str], int] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    name_end = 0
    while name_end < len(stripped) and stripped[name_end] not in "{ \t":
        name_end += 1
    name = stripped[:name_end]
    if name not in METRIC_SPECS:
        return None
    if not METRIC_NAME_RE.fullmatch(name):
        raise EvidenceError("selected metric has an invalid name")

    index = name_end
    labels: dict[str, str] = {}
    if index < len(stripped) and stripped[index] == "{":
        block_end = _find_label_block_end(stripped, index)
        if block_end < 0:
            raise EvidenceError("selected metric has malformed labels")
        labels = _parse_labels(stripped[index + 1 : block_end])
        index = block_end + 1

    if index >= len(stripped) or not stripped[index].isspace():
        raise EvidenceError("selected metric has no sample value")
    remainder = stripped[index:].lstrip()
    if not remainder:
        raise EvidenceError("selected metric has no sample value")
    value_token = remainder.split(None, 1)[0]
    try:
        numeric_value = Decimal(value_token)
    except InvalidOperation as exc:
        raise EvidenceError("selected metric has an invalid sample value") from exc
    if (
        not numeric_value.is_finite()
        or numeric_value != numeric_value.to_integral_value()
    ):
        raise EvidenceError("selected metric must have a finite integer sample value")
    if numeric_value < 0 or numeric_value > MAX_METRIC_VALUE:
        raise EvidenceError("selected metric sample value is outside the int64 range")
    value = int(numeric_value)
    return name, labels, value


def parse_metrics(
    text: str,
    receiver_label: str,
    exporter_label: str,
) -> dict[str, dict[str, Any]]:
    totals = {name: 0 for name in METRIC_SPECS}
    present = {name: False for name in METRIC_SPECS}
    selected_series = 0

    for line in text.splitlines():
        parsed = _parse_selected_sample(line)
        if parsed is None:
            continue
        name, labels, value = parsed
        spec = METRIC_SPECS[name]
        expected_label = (
            receiver_label if spec.component_label == "receiver" else exporter_label
        )
        if labels.get(spec.component_label) != expected_label:
            continue
        selected_series += 1
        if selected_series > MAX_SELECTED_SERIES:
            raise EvidenceError("metrics response contains too many selected series")
        totals[name] += value
        if totals[name] > MAX_METRIC_VALUE:
            raise EvidenceError("selected metric aggregate is outside the int64 range")
        present[name] = True

    return {
        name: {
            "kind": METRIC_SPECS[name].kind,
            "present": present[name],
            "value": totals[name] if present[name] else None,
        }
        for name in METRIC_SPECS
    }


def load_before_snapshot(
    path: Path,
    receiver_label: str,
    exporter_label: str,
) -> dict[str, dict[str, Any]]:
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_SNAPSHOT_BYTES + 1)
    except OSError as exc:
        raise EvidenceError("before snapshot could not be read") from exc
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise EvidenceError("before snapshot exceeds the size limit")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as exc:
        raise EvidenceError("before snapshot is not valid JSON") from exc
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != SCHEMA_VERSION
    ):
        raise EvidenceError("before snapshot has an incompatible schema")

    selection = document.get("selection")
    if not isinstance(selection, dict) or selection != {
        "exporter": exporter_label,
        "receiver": receiver_label,
    }:
        raise EvidenceError("before snapshot selects different Collector components")
    metrics = document.get("metrics")
    if not isinstance(metrics, dict):
        raise EvidenceError("before snapshot has invalid metrics")

    sanitized: dict[str, dict[str, Any]] = {}
    for name, spec in METRIC_SPECS.items():
        entry = metrics.get(name)
        if not isinstance(entry, dict):
            raise EvidenceError("before snapshot has invalid metrics")
        is_present = entry.get("present")
        value = entry.get("value")
        if not isinstance(is_present, bool):
            raise EvidenceError("before snapshot has invalid metrics")
        if is_present:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise EvidenceError("before snapshot has invalid metrics")
        elif value is not None:
            raise EvidenceError("before snapshot has invalid metrics")
        sanitized[name] = {
            "kind": spec.kind,
            "present": is_present,
            "value": value,
        }
    return sanitized


def compute_deltas(
    current: Mapping[str, Mapping[str, Any]],
    before: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    deltas: dict[str, dict[str, Any]] = {}
    for name, spec in METRIC_SPECS.items():
        current_entry = current[name]
        before_entry = before[name]
        available = bool(current_entry["present"] and before_entry["present"])
        reset = False
        value = None
        if available:
            current_value = int(current_entry["value"])
            before_value = int(before_entry["value"])
            if spec.kind == "counter" and current_value < before_value:
                available = False
                reset = True
            else:
                value = current_value - before_value
        deltas[name] = {
            "available": available,
            "reset": reset,
            "value": value,
        }
    return deltas


def collect_evidence(
    *,
    health_url: str,
    metrics_url: str,
    receiver_label: str,
    exporter_label: str,
    timeout: float,
    before_path: Path | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> dict[str, Any]:
    health_url = validate_loopback_http_url(health_url, "health URL")
    metrics_url = validate_loopback_http_url(metrics_url, "metrics URL")
    receiver_label = validate_component_id(receiver_label, "receiver label")
    exporter_label = validate_component_id(exporter_label, "exporter label")
    timeout = validate_timeout(timeout)
    local_opener = opener if opener is not None else build_local_opener()

    health = query_health(local_opener, health_url, timeout)
    metrics = parse_metrics(
        query_metrics_text(local_opener, metrics_url, timeout),
        receiver_label,
        exporter_label,
    )
    before = (
        load_before_snapshot(before_path, receiver_label, exporter_label)
        if before_path is not None
        else None
    )

    return {
        "collector_metric_baseline": COLLECTOR_METRIC_BASELINE,
        "deltas": compute_deltas(metrics, before) if before is not None else None,
        "health": health,
        "metrics": metrics,
        "schema_version": SCHEMA_VERSION,
        "selection": {
            "exporter": exporter_label,
            "receiver": receiver_label,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture sanitized Lemonade collector health and trace-counter evidence."
    )
    parser.add_argument("--receiver-label", required=True)
    parser.add_argument("--exporter-label", required=True)
    parser.add_argument("--health-url", default=DEFAULT_HEALTH_URL)
    parser.add_argument("--metrics-url", default=DEFAULT_METRICS_URL)
    parser.add_argument(
        "--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--before",
        type=Path,
        help="Prior JSON output from this helper; enables counter/gauge deltas.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = collect_evidence(
            health_url=args.health_url,
            metrics_url=args.metrics_url,
            receiver_label=args.receiver_label,
            exporter_label=args.exporter_label,
            timeout=args.timeout_seconds,
            before_path=args.before,
        )
    except EvidenceError as exc:
        print(f"collector evidence failed: {exc}", file=sys.stderr)
        return 2

    json.dump(evidence, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if evidence["health"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
