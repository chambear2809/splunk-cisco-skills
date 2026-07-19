#!/usr/bin/env python3
"""Send a privacy-safe OpenInference/GenAI canary to an OTLP/HTTP receiver."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


MAX_RESPONSE_BYTES = 1024 * 1024


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so validation never leaves the reviewed receiver URL."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def attribute(key: str, value: str) -> dict[str, object]:
    return {"key": key, "value": {"stringValue": value}}


def validate_endpoint(parser: argparse.ArgumentParser, endpoint: str) -> None:
    if endpoint != endpoint.strip() or any(
        unicodedata.category(character) == "Cc" for character in endpoint
    ):
        parser.error("--endpoint must not contain surrounding whitespace or controls")
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        parser.error(f"--endpoint is invalid: {exc}")
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "?" in endpoint
        or "#" in endpoint
        or parsed.path != "/v1/traces"
        or port is None
        or not 1 <= port <= 65535
    ):
        parser.error(
            "--endpoint must be an exact loopback HTTP URL with an explicit valid "
            "port and /v1/traces path; userinfo, query, and fragment are forbidden"
        )


def rejected_span_count(result: object) -> tuple[int, bool, bool]:
    if not isinstance(result, dict):
        raise ValueError("OTLP receiver response must be a JSON object")
    counts: list[int] = []
    partial_success_seen = False
    warning_message_seen = False
    for container_name in ("partialSuccess", "partial_success"):
        if container_name not in result:
            continue
        partial_success_seen = True
        partial = result[container_name]
        if partial is None:
            raise ValueError(f"{container_name} must be a JSON object")
        if not isinstance(partial, dict):
            raise ValueError(f"{container_name} must be a JSON object")
        for field_name in ("errorMessage", "error_message"):
            if field_name not in partial:
                continue
            raw_message = partial[field_name]
            if not isinstance(raw_message, str):
                raise ValueError(f"{container_name}.{field_name} must be a string")
            warning_message_seen = warning_message_seen or bool(raw_message)
        for field_name in ("rejectedSpans", "rejected_spans"):
            if field_name not in partial:
                continue
            raw = partial[field_name]
            if isinstance(raw, bool) or not isinstance(raw, (int, str)):
                raise ValueError(f"{container_name}.{field_name} must be an integer")
            if isinstance(raw, str) and not raw.isdigit():
                raise ValueError(
                    f"{container_name}.{field_name} must be a nonnegative integer"
                )
            count = int(raw)
            if count < 0:
                raise ValueError(f"{container_name}.{field_name} must be nonnegative")
            counts.append(count)
    if len(set(counts)) > 1:
        raise ValueError("OTLP receiver returned conflicting rejected-span counts")
    return (
        counts[0] if counts else 0,
        partial_success_seen,
        warning_message_seen,
    )


def reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:4318/v1/traces")
    parser.add_argument("--deployment-environment", default="lemonade-dev")
    args = parser.parse_args()
    validate_endpoint(parser, args.endpoint)
    if not args.deployment_environment.strip() or any(
        unicodedata.category(character) == "Cc"
        for character in args.deployment_environment
    ):
        parser.error("--deployment-environment must be nonempty and control-free")

    trace_id = secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    suffix = secrets.token_hex(4)
    name = f"chat lemonade-privacy-canary-{suffix}"
    created_after = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    started = time.time_ns()
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        attribute("service.name", "lemonade-otel-canary"),
                        attribute(
                            "deployment.environment.name", args.deployment_environment
                        ),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "lemonade.validation", "version": "1.0.0"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": name,
                                "kind": 3,
                                "startTimeUnixNano": str(started),
                                "endTimeUnixNano": str(started + 50_000_000),
                                "attributes": [
                                    attribute("openinference.span.kind", "LLM"),
                                    attribute("input.value", "[REDACTED]"),
                                    attribute("output.value", "[REDACTED]"),
                                    attribute("gen_ai.operation.name", "chat"),
                                    attribute("gen_ai.provider.name", "lemonade"),
                                    attribute(
                                        "gen_ai.request.model",
                                        "lemonade-privacy-canary",
                                    ),
                                    attribute(
                                        "gen_ai.response.model",
                                        "lemonade-privacy-canary",
                                    ),
                                    attribute("session.id", f"canary-{suffix}"),
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    request = urllib.request.Request(
        args.endpoint,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirectHandler(),
    )
    try:
        with opener.open(request, timeout=10) as response:
            status = getattr(response, "status", response.getcode())
            if status != 200:
                raise SystemExit(
                    f"ERROR: OTLP receiver returned unexpected HTTP {status}"
                )
            content_type = response.headers.get("Content-Type")
            media_type = (
                str(content_type).split(";", 1)[0].strip().lower()
                if content_type is not None
                else ""
            )
            if media_type != "application/json":
                raise SystemExit("ERROR: OTLP receiver returned non-JSON content")
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    announced_length = int(content_length)
                except ValueError as exc:
                    raise SystemExit(
                        "ERROR: OTLP receiver returned an invalid Content-Length"
                    ) from exc
                if announced_length < 0 or announced_length > MAX_RESPONSE_BYTES:
                    raise SystemExit(
                        "ERROR: OTLP receiver response exceeds the size limit"
                    )
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"ERROR: OTLP receiver returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit("ERROR: OTLP receiver request failed") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise SystemExit("ERROR: OTLP receiver response exceeds the size limit")
    if not body:
        raise SystemExit("ERROR: OTLP receiver returned an empty response")
    try:
        result = json.loads(body, parse_constant=reject_nonfinite_json)
    except (
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
        RecursionError,
    ) as exc:
        raise SystemExit("ERROR: OTLP receiver returned non-JSON content") from exc
    try:
        rejected, partial_success, warning_message = rejected_span_count(result)
    except ValueError as exc:
        raise SystemExit(f"ERROR: invalid OTLP receiver response: {exc}") from exc
    if rejected > 0:
        raise SystemExit(f"ERROR: OTLP receiver rejected {rejected} span(s)")
    if warning_message:
        raise SystemExit(
            "ERROR: OTLP receiver returned a partialSuccess warning; review receiver health"
        )
    created_before = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    print(f"TRACE_ID={trace_id}")
    print(f"TRACE_NAME={name}")
    print(f"CREATED_AFTER={created_after}")
    print(f"CREATED_BEFORE={created_before}")
    if partial_success:
        print("OTLP_PARTIAL_SUCCESS_PRESENT=true")


if __name__ == "__main__":
    main()
