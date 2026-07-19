#!/usr/bin/env python3
"""Validate a persisted Splunk APM trace without exposing credentials or content."""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


SHARED_LIB_DIR = Path(__file__).resolve().parents[2] / "shared" / "lib"
if str(SHARED_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_LIB_DIR))

from secure_secret_file import (  # noqa: E402
    SecureSecretFileError,
    read_private_text_file,
)


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TRACE_SEGMENTS = 10_000
MAX_SPANS_PER_SEGMENT = 10_000
MAX_TOTAL_SPANS = 20_000
MAX_SCAN_NODES = 250_000
# The public deadline is capped at 900 seconds and every unstable segment
# index incurs a one-second pause. Keep an independent iteration ceiling for
# test clients and future callers whose pause implementation does not track time.
MAX_SEGMENT_STABILITY_ATTEMPTS = 901
RETRYABLE_HTTP_STATUSES = {429, 502, 503, 504}
TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SPAN_ID_RE = re.compile(r"^[0-9a-f]{16}$")
REALM_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{1,256}$")
DIRECT_SECRET_OPTIONS = {
    "--access-token",
    "--api-token",
    "--sf-token",
    "--splunk-access-token",
    "--token",
    "--x-sf-token",
}


class ReadbackError(RuntimeError):
    """A sanitized readback failure safe to display to an operator."""


class SafeArgumentParser(argparse.ArgumentParser):
    """Keep arbitrary rejected argv values out of validation output."""

    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "ERROR: invalid command-line arguments\n")


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the API token never leaves the reviewed origin."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def control_free(value: str, label: str, *, maximum: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise ReadbackError(f"{label} must be nonempty and control-free")
    return value


def parse_timestamp(value: str, label: str) -> dt.datetime:
    control_free(value, label, maximum=128)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ReadbackError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ReadbackError(f"{label} must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def isoformat_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def read_token_file(path: Path) -> str:
    try:
        token = read_private_text_file(path, label="Splunk API token")
    except SecureSecretFileError as exc:
        raise ReadbackError(str(exc)) from exc
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in token):
        raise ReadbackError(
            "Splunk API token file must contain one printable ASCII token"
        )
    return token


def read_forbidden_content(path: Path) -> str:
    try:
        value = read_private_text_file(
            path,
            label="forbidden-content",
            maximum_bytes=1024 * 1024,
        )
    except SecureSecretFileError as exc:
        raise ReadbackError(str(exc)) from exc
    if len(value) < 8:
        raise ReadbackError(
            "forbidden-content file must contain at least eight characters"
        )
    return value


def announced_length(headers: Any) -> int | None:
    raw = headers.get("Content-Length") if headers is not None else None
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ReadbackError("Splunk API returned an invalid Content-Length") from exc
    if value < 0:
        raise ReadbackError("Splunk API returned an invalid Content-Length")
    return value


def json_media_type(headers: Any) -> bool:
    raw = headers.get("Content-Type") if headers is not None else None
    return bool(raw) and str(raw).split(";", 1)[0].strip().lower() == "application/json"


def retry_after_seconds(headers: Any, now: dt.datetime) -> float | None:
    raw = headers.get("Retry-After") if headers is not None else None
    if raw is None:
        return None
    value = str(raw).strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        seconds = (parsed.astimezone(dt.timezone.utc) - now).total_seconds()
    if seconds < 0:
        return 0.0
    return min(seconds, 30.0)


def reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


class SplunkApiClient:
    """Exact-origin, bounded JSON client with deadline-bound retries."""

    def __init__(
        self,
        *,
        realm: str,
        token: str,
        deadline_seconds: float,
        request_timeout: float,
        opener: Any | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], dt.datetime] | None = None,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        if not REALM_RE.fullmatch(realm):
            raise ReadbackError(
                "realm must be lowercase alphanumeric with optional hyphens"
            )
        if deadline_seconds <= 0 or deadline_seconds > 900:
            raise ReadbackError("deadline seconds must be in the range (0, 900]")
        if request_timeout <= 0 or request_timeout > 60:
            raise ReadbackError("request timeout must be in the range (0, 60]")
        if max_response_bytes < 1:
            raise ReadbackError("response byte limit must be positive")
        self.origin = f"https://api.{realm}.observability.splunkcloud.com"
        self.token = token
        self.request_timeout = request_timeout
        self.monotonic = monotonic
        self.sleep = sleep
        self.wall_clock = wall_clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self.deadline = monotonic() + deadline_seconds
        self.max_response_bytes = max_response_bytes
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirectHandler(),
        )

    def remaining(self) -> float:
        return self.deadline - self.monotonic()

    def pause(self, delay: float, exhausted_message: str) -> None:
        remaining = self.remaining()
        if remaining <= 0 or delay >= remaining:
            raise ReadbackError(exhausted_message)
        self.sleep(max(0.0, delay))

    def get_json(self, path: str, *, retry_not_found: bool) -> Any:
        if not path.startswith("/v2/") or any(
            character in path for character in ("\r", "\n", "?", "#")
        ):
            raise ReadbackError("internal API path validation failed")
        url = f"{self.origin}{path}"
        attempt = 0
        while self.remaining() > 0:
            remaining = self.remaining()
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "lemonade-splunk-otel-readback/1",
                    "X-SF-TOKEN": self.token,
                },
                method="GET",
            )
            try:
                with self.opener.open(
                    request,
                    timeout=min(self.request_timeout, remaining),
                ) as response:
                    status = getattr(response, "status", response.getcode())
                    if status != 200:
                        raise ReadbackError(
                            f"Splunk API returned unexpected HTTP {status}"
                        )
                    if not json_media_type(response.headers):
                        raise ReadbackError(
                            "Splunk API returned a non-JSON content type"
                        )
                    length = announced_length(response.headers)
                    if length is not None and length > self.max_response_bytes:
                        raise ReadbackError(
                            "Splunk API response exceeded the size limit"
                        )
                    body = response.read(self.max_response_bytes + 1)
            except urllib.error.HTTPError as exc:
                retryable = exc.code in RETRYABLE_HTTP_STATUSES or (
                    retry_not_found and exc.code == 404
                )
                retry_headers = exc.headers
                exc.close()
                if not retryable:
                    raise ReadbackError(f"Splunk API returned HTTP {exc.code}") from exc
                delay = retry_after_seconds(retry_headers, self.wall_clock())
                if delay is None:
                    delay = min(10.0, float(2 ** min(attempt, 3)))
                delay = max(0.25, delay)
                attempt += 1
                self.pause(delay, "Splunk API readback deadline expired")
                continue
            except (urllib.error.URLError, TimeoutError, OSError):
                delay = min(10.0, float(2 ** min(attempt, 3)))
                attempt += 1
                self.pause(delay, "Splunk API readback deadline expired")
                continue
            if len(body) > self.max_response_bytes:
                raise ReadbackError("Splunk API response exceeded the size limit")
            if not body:
                raise ReadbackError("Splunk API returned an empty response")
            try:
                return json.loads(
                    body.decode("utf-8"), parse_constant=reject_nonfinite_json
                )
            except (
                UnicodeDecodeError,
                ValueError,
                json.JSONDecodeError,
                RecursionError,
            ) as exc:
                raise ReadbackError("Splunk API returned invalid JSON") from exc
        raise ReadbackError("Splunk API readback deadline expired")


def parse_segments(document: Any) -> tuple[int, ...]:
    if not isinstance(document, list) or not document:
        raise ReadbackError("Splunk API returned no trace segments")
    if len(document) >= MAX_TRACE_SEGMENTS:
        raise ReadbackError("Splunk trace segment index might be truncated")
    segments: list[int] = []
    for value in document:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ReadbackError("Splunk API returned an invalid segment timestamp")
        segments.append(value)
    if len(set(segments)) != len(segments):
        raise ReadbackError("Splunk API returned duplicate segment timestamps")
    return tuple(sorted(segments))


def parse_spans(document: Any, trace_id: str) -> list[dict[str, Any]]:
    if not isinstance(document, list) or not document:
        raise ReadbackError("Splunk API returned an empty trace segment")
    if len(document) >= MAX_SPANS_PER_SEGMENT:
        raise ReadbackError("Splunk trace segment might be truncated")
    spans: list[dict[str, Any]] = []
    for value in document:
        if not isinstance(value, dict):
            raise ReadbackError("Splunk API returned a malformed span")
        returned_trace_id = str(value.get("traceId") or "").lower()
        if returned_trace_id != trace_id:
            raise ReadbackError("Splunk API returned a span for a different trace")
        span_id = str(value.get("spanId") or "").lower()
        if not SPAN_ID_RE.fullmatch(span_id):
            raise ReadbackError("Splunk API returned an invalid span ID")
        if value.get("objectType") not in (None, "span"):
            raise ReadbackError("Splunk API returned an unexpected trace object")
        spans.append(value)
    return spans


def retrieve_all_segments(
    client: SplunkApiClient, trace_id: str
) -> tuple[tuple[int, ...], list[dict[str, Any]]]:
    """Read all segments and require a stable segment index across the read."""

    for _stability_attempt in range(MAX_SEGMENT_STABILITY_ATTEMPTS):
        first_document = client.get_json(
            f"/v2/apm/trace/{trace_id}/segments", retry_not_found=True
        )
        if first_document == []:
            client.pause(1.0, "Splunk trace was not indexed before the deadline")
            continue
        first = parse_segments(first_document)
        spans: list[dict[str, Any]] = []
        for timestamp in first:
            spans.extend(
                parse_spans(
                    client.get_json(
                        f"/v2/apm/trace/{trace_id}/{timestamp}",
                        retry_not_found=True,
                    ),
                    trace_id,
                )
            )
            if len(spans) > MAX_TOTAL_SPANS:
                raise ReadbackError("Splunk API returned too many spans")
        second_document = client.get_json(
            f"/v2/apm/trace/{trace_id}/segments", retry_not_found=True
        )
        if second_document == []:
            client.pause(1.0, "Splunk trace was not indexed before the deadline")
            continue
        second = parse_segments(second_document)
        if first == second:
            break
        client.pause(1.0, "Splunk trace segments did not stabilize before the deadline")
    else:
        raise ReadbackError("Splunk trace segments did not stabilize before the deadline")

    span_ids = [str(span["spanId"]).lower() for span in spans]
    if len(set(span_ids)) != len(span_ids):
        raise ReadbackError("Splunk API returned duplicate spans")
    return first, spans


def attribute_maps(span: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for container_name in ("processTags", "tags"):
        container = span.get(container_name)
        if container is None:
            continue
        if not isinstance(container, dict):
            raise ReadbackError(f"Splunk span {container_name} must be an object")
        for key, value in container.items():
            if not isinstance(key, str):
                raise ReadbackError("Splunk span attribute keys must be strings")
            if key in result and result[key] != value:
                raise ReadbackError("Splunk span contains conflicting attributes")
            result[key] = value
    return result


def scalar_text(value: Any) -> str | None:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict) and set(value) == {"value"}:
        return scalar_text(value["value"])
    return None


def require_attribute(
    attributes: dict[str, Any], aliases: tuple[str, ...], expected: str, label: str
) -> None:
    values = [scalar_text(attributes[key]) for key in aliases if key in attributes]
    if not values or any(value is None or value != expected for value in values):
        raise ReadbackError(f"persisted trace has an unexpected {label}")


def integer_field(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReadbackError(f"persisted trace has an invalid {label}")
    return value


def scan_forbidden_content(document: Any, forbidden: tuple[str, ...]) -> None:
    if not forbidden:
        return
    pending = [document]
    visited = 0
    while pending:
        value = pending.pop()
        visited += 1
        if visited > MAX_SCAN_NODES:
            raise ReadbackError("Splunk trace exceeded the privacy scan limit")
        if isinstance(value, str):
            if any(sentinel in value for sentinel in forbidden):
                raise ReadbackError(
                    "forbidden content was present in the persisted trace"
                )
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)


def validate_trace(
    spans: list[dict[str, Any]],
    *,
    expected_service: str,
    expected_operation: str,
    created_after: dt.datetime,
    created_before: dt.datetime,
    expected_environment: str,
    expected_model: str,
    expected_provider: str,
    expected_genai_operation: str,
    expected_openinference_kind: str,
) -> dict[str, Any]:
    matches = [
        span
        for span in spans
        if span.get("serviceName") == expected_service
        and span.get("operationName") == expected_operation
    ]
    if not matches:
        raise ReadbackError("persisted trace did not contain the expected span")

    observed_starts: list[dt.datetime] = []
    observed_durations: list[int] = []
    for span in matches:
        start = parse_timestamp(str(span.get("startTime") or ""), "span startTime")
        if start < created_after or start > created_before:
            raise ReadbackError(
                "persisted trace span was outside the expected time window"
            )
        duration = integer_field(span.get("durationMicros"), "durationMicros")
        if duration < 1:
            raise ReadbackError("persisted trace span duration must be positive")
        attributes = attribute_maps(span)
        require_attribute(
            attributes,
            ("deployment.environment.name", "deployment.environment"),
            expected_environment,
            "deployment environment",
        )
        require_attribute(
            attributes,
            ("gen_ai.request.model",),
            expected_model,
            "request model",
        )
        require_attribute(
            attributes,
            ("gen_ai.response.model",),
            expected_model,
            "response model",
        )
        require_attribute(
            attributes,
            ("gen_ai.provider.name", "gen_ai.system"),
            expected_provider,
            "GenAI provider",
        )
        require_attribute(
            attributes,
            ("gen_ai.operation.name",),
            expected_genai_operation,
            "GenAI operation",
        )
        require_attribute(
            attributes,
            ("openinference.span.kind",),
            expected_openinference_kind,
            "OpenInference span kind",
        )
        observed_starts.append(start)
        observed_durations.append(duration)

    return {
        "matched_span_count": len(matches),
        "observed_start_min": isoformat_utc(min(observed_starts)),
        "observed_start_max": isoformat_utc(max(observed_starts)),
        "duration_micros_min": min(observed_durations),
        "duration_micros_max": max(observed_durations),
    }


def validate_organization(document: Any, expected_id: str) -> None:
    if not isinstance(document, dict) or document.get("id") != expected_id:
        raise ReadbackError("Splunk API token is bound to an unexpected organization")


def validate_private_output_parent(path: Path) -> Path:
    if not path.is_absolute():
        raise ReadbackError("output path must be absolute")
    if path.name in {"", ".", ".."}:
        raise ReadbackError("output path must name a regular evidence file")
    parent = path.parent.resolve()
    try:
        info = parent.stat()
    except OSError as exc:
        raise ReadbackError("output directory must already exist") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise ReadbackError("output parent must be a directory")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise ReadbackError("output directory must be owned by the current user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ReadbackError("output directory permissions must be 0700 or stricter")
    return parent


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    parent = validate_private_output_parent(path)
    target = parent / path.name
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        payload = (
            json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = -1
        os.replace(temporary, target)
        directory_descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--realm", required=True)
    parser.add_argument("--expected-organization-id", required=True)
    parser.add_argument("--api-token-file", required=True, type=Path)
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--expected-service", required=True)
    parser.add_argument("--expected-operation", required=True)
    parser.add_argument("--created-after", required=True)
    parser.add_argument("--created-before", required=True)
    parser.add_argument("--expected-environment", required=True)
    parser.add_argument("--expected-model", required=True)
    parser.add_argument("--expected-provider", required=True)
    parser.add_argument("--expected-genai-operation", default="chat")
    parser.add_argument("--expected-openinference-kind", default="LLM")
    parser.add_argument(
        "--forbidden-content-file", action="append", default=[], type=Path
    )
    parser.add_argument("--deadline-seconds", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=15.0)
    parser.add_argument("--output", type=Path)
    return parser


def reject_direct_secret_arguments(argv: list[str]) -> None:
    for argument in argv:
        if argument.split("=", 1)[0] in DIRECT_SECRET_OPTIONS:
            raise ReadbackError(
                "direct secret arguments are forbidden; use --api-token-file"
            )


def run(args: argparse.Namespace) -> dict[str, Any]:
    realm = control_free(args.realm, "realm", maximum=32)
    if not REALM_RE.fullmatch(realm):
        raise ReadbackError(
            "realm must be lowercase alphanumeric with optional hyphens"
        )
    organization_id = control_free(
        args.expected_organization_id, "organization ID", maximum=256
    )
    if not IDENTIFIER_RE.fullmatch(organization_id):
        raise ReadbackError("organization ID contains unsupported characters")
    trace_id = control_free(args.trace_id, "trace ID", maximum=32).lower()
    if not TRACE_ID_RE.fullmatch(trace_id):
        raise ReadbackError("trace ID must contain exactly 32 hexadecimal characters")

    expected_values = {
        "expected service": args.expected_service,
        "expected operation": args.expected_operation,
        "expected environment": args.expected_environment,
        "expected model": args.expected_model,
        "expected provider": args.expected_provider,
        "expected GenAI operation": args.expected_genai_operation,
        "expected OpenInference kind": args.expected_openinference_kind,
    }
    for label, value in expected_values.items():
        control_free(value, label)

    created_after = parse_timestamp(args.created_after, "created-after")
    created_before = parse_timestamp(args.created_before, "created-before")
    if created_before < created_after:
        raise ReadbackError("created-before must not precede created-after")

    if args.output is not None:
        protected_inputs = [args.api_token_file, *args.forbidden_content_file]
        output_resolved = args.output.resolve(strict=False)
        if any(
            output_resolved == path.resolve(strict=False) for path in protected_inputs
        ):
            raise ReadbackError("output path must not overwrite a protected input")
        validate_private_output_parent(args.output)

    token = read_token_file(args.api_token_file)
    forbidden = tuple(
        read_forbidden_content(path) for path in args.forbidden_content_file
    )
    client = SplunkApiClient(
        realm=realm,
        token=token,
        deadline_seconds=args.deadline_seconds,
        request_timeout=args.request_timeout,
    )
    organization = client.get_json("/v2/organization", retry_not_found=False)
    validate_organization(organization, organization_id)
    segments, spans = retrieve_all_segments(client, trace_id)
    scan_forbidden_content(spans, forbidden)
    validation = validate_trace(
        spans,
        expected_service=args.expected_service,
        expected_operation=args.expected_operation,
        created_after=created_after,
        created_before=created_before,
        expected_environment=args.expected_environment,
        expected_model=args.expected_model,
        expected_provider=args.expected_provider,
        expected_genai_operation=args.expected_genai_operation,
        expected_openinference_kind=args.expected_openinference_kind,
    )
    evidence = {
        "ok": True,
        "backend": "splunk-observability-cloud-apm",
        "realm": realm,
        "organization_id_sha256": hashlib.sha256(
            organization_id.encode("utf-8")
        ).hexdigest(),
        "trace_id": trace_id,
        "segment_count": len(segments),
        "span_count": len(spans),
        "expected_service": args.expected_service,
        "expected_operation": args.expected_operation,
        "expected_environment": args.expected_environment,
        "expected_model": args.expected_model,
        "expected_provider": args.expected_provider,
        "expected_genai_operation": args.expected_genai_operation,
        "expected_openinference_kind": args.expected_openinference_kind,
        "created_after": isoformat_utc(created_after),
        "created_before": isoformat_utc(created_before),
        "content_privacy": "verified" if forbidden else "not_evaluated",
        **validation,
    }
    if args.output is not None:
        write_evidence(args.output, evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_direct_secret_arguments(raw_arguments)
    except ReadbackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    parser = build_parser()
    args = parser.parse_args(raw_arguments)
    try:
        evidence = run(args)
    except (OSError, ReadbackError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
