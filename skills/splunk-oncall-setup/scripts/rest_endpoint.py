#!/usr/bin/env python3
"""Send Splunk On-Call alerts through the REST Endpoint Integration.

Reads alert payloads from a YAML or JSON spec (typically the rendered
``rest_alerts`` payloads under ``payloads/rest_alerts/`` produced by
``render_oncall.py``) and POSTs them to:

    https://alert.victorops.com/integrations/generic/20131114/alert/<INTEGRATION_KEY>/<ROUTING_KEY>

The integration key is read from a chmod-600 file via ``--integration-key-file``.
A ``--self-test`` mode fires an INFO followed by a RECOVERY for a synthetic
``entity_id`` so operators can verify wiring without ever creating a real
incident.

Annotations declared as ``vo_annotate.{u|s|i}.<title>`` keys are passed
through as-is. The validator caps each annotation value at 1,124 characters,
matching the documented REST endpoint limit.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import stat
import sys
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_DEFAULT_REST_BASE = "https://alert.victorops.com/integrations/generic/20131114/alert"
_DEFAULT_USER_AGENT = "splunk-oncall-setup/1 (+splunk-cisco-skills)"
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

ALLOWED_MESSAGE_TYPES = {"CRITICAL", "WARNING", "INFO", "ACKNOWLEDGEMENT", "RECOVERY", "OK"}
ANNOTATION_VALUE_LIMIT = 1124
ANNOTATION_KEY_RE = re.compile(r"^vo_annotate\.[usi]\..+$")

# Routing keys must be alphanumeric with `.`, `_`, `-` per the docs and the
# routing-key UI form.
ROUTING_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# Integration key: 8-4-4-4-12 hex UUID per Splunk On-Call's documented format.
# We accept the broader pattern (alphanumeric + hyphens) to support legacy
# keys, but reject anything containing whitespace or path separators that
# could leak into the URL path.
INTEGRATION_KEY_RE = re.compile(r"^[A-Za-z0-9-]+$")


class RestEndpointError(Exception):
    """Raised when an alert payload is invalid or POST fails."""


def _max_retries() -> int:
    raw = os.environ.get("ONCALL_REST_MAX_RETRIES")
    if raw is None:
        return 3
    try:
        value = int(raw)
    except ValueError:
        return 3
    return max(1, value)


def read_secret_file(path: Path, label: str) -> str:
    if not path.is_file():
        raise RestEndpointError(f"{label} file does not exist: {path}")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise RestEndpointError(f"Cannot stat {label} file {path}: {exc}") from exc
    if mode & 0o077:
        raise RestEndpointError(
            f"{label} file {path} has overly permissive mode {oct(mode)}; require 0600."
        )
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RestEndpointError(f"{label} file is empty: {path}")
    return value


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RestEndpointError(f"{path} is not valid JSON: {exc}") from exc
    else:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - setup.sh preflights this.
            raise RestEndpointError(
                "YAML alert specs require PyYAML. Use JSON or install repo dependencies."
            ) from exc
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise RestEndpointError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise RestEndpointError(f"{path} must contain a JSON/YAML object.")
    return data


def normalize_alert(alert: dict[str, Any], default_routing_key: str) -> dict[str, Any]:
    if not isinstance(alert, dict):
        raise RestEndpointError("Each alert must be a mapping/object.")
    payload: OrderedDict[str, Any] = OrderedDict()

    message_type = str(alert.get("message_type", "")).strip().upper()
    if message_type not in ALLOWED_MESSAGE_TYPES:
        raise RestEndpointError(
            f"alert message_type must be one of {sorted(ALLOWED_MESSAGE_TYPES)} (got {message_type!r})."
        )
    payload["message_type"] = message_type

    for field in ("entity_id", "entity_display_name", "state_message", "monitoring_tool", "hostname"):
        if field in alert:
            payload[field] = alert[field]

    payload.setdefault("entity_id", f"splunk-oncall-setup-{uuid.uuid4()}")

    state_start_time = alert.get("state_start_time")
    if state_start_time is not None:
        if not isinstance(state_start_time, int):
            raise RestEndpointError("state_start_time must be an integer (epoch seconds).")
        payload["state_start_time"] = state_start_time

    is_multi = alert.get("isMultiResponder")
    if is_multi is not None:
        if not isinstance(is_multi, bool):
            raise RestEndpointError("isMultiResponder must be a boolean.")
        payload["isMultiResponder"] = is_multi

    routing_key = alert.get("routing_key") or default_routing_key
    if routing_key:
        payload["routing_key"] = routing_key

    # Pre-built `vo_annotate.*` keys flow through as-is; the structured
    # `annotations[]` shape is converted to `vo_annotate.*`.
    for key, value in alert.items():
        if isinstance(key, str) and ANNOTATION_KEY_RE.match(key):
            check_annotation_value(key, value)
            payload[key] = value
    for index, ann in enumerate(alert.get("annotations") or []):
        if not isinstance(ann, dict):
            raise RestEndpointError(f"annotations[{index}] must be a mapping/object.")
        kind = str(ann.get("kind", "")).strip().lower()
        title = str(ann.get("title", "")).strip()
        value = ann.get("value", "")
        if kind not in {"url", "note", "image"}:
            raise RestEndpointError(f"annotations[{index}].kind must be url | note | image.")
        if not title:
            raise RestEndpointError(f"annotations[{index}] requires title.")
        if not isinstance(value, str):
            raise RestEndpointError(f"annotations[{index}] value must be a string.")
        check_annotation_value(f"annotations[{index}]", value)
        prefix = {"url": "vo_annotate.u.", "note": "vo_annotate.s.", "image": "vo_annotate.i."}[kind]
        payload[f"{prefix}{title}"] = value

    # Pass-through for other timeline fields (no allow-list — the REST
    # endpoint accepts arbitrary JSON), but skip the wrapper keys we already
    # consumed.
    for key, value in alert.items():
        if key in {
            "alert_name",
            "annotations",
            "message_type",
            "entity_id",
            "entity_display_name",
            "state_message",
            "monitoring_tool",
            "hostname",
            "state_start_time",
            "isMultiResponder",
            "routing_key",
        }:
            continue
        if isinstance(key, str) and ANNOTATION_KEY_RE.match(key):
            continue
        payload[key] = value

    return dict(payload)


def check_annotation_value(label: str, value: Any) -> None:
    if not isinstance(value, str):
        raise RestEndpointError(f"{label} value must be a string.")
    if len(value) > ANNOTATION_VALUE_LIMIT:
        raise RestEndpointError(
            f"{label} exceeds the {ANNOTATION_VALUE_LIMIT}-char limit (got {len(value)})."
        )


def build_url(rest_base: str, integration_key: str, routing_key: str) -> str:
    if not INTEGRATION_KEY_RE.match(integration_key or ""):
        raise RestEndpointError("integration key must match [A-Za-z0-9-]+.")
    if not ROUTING_KEY_RE.match(routing_key or ""):
        raise RestEndpointError("routing key must match [A-Za-z0-9_.-]+.")
    return f"{rest_base.rstrip('/')}/{integration_key}/{routing_key}"


def post_alert(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": _DEFAULT_USER_AGENT,
    }
    request = Request(url, data=data, headers=headers, method="POST")
    max_attempts = _max_retries()
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - operator-rendered URL
                text = response.read().decode("utf-8")
                if not text:
                    return {}
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"_raw_text": text[:4096]}
        except HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRYABLE_STATUSES and attempt < max_attempts - 1:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after:
                    try:
                        time.sleep(max(0.0, float(retry_after)))
                        continue
                    except (TypeError, ValueError):
                        pass
                time.sleep(min(15.0, (2.0 ** attempt) + random.random()))
                continue
            try:
                error_text = exc.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                error_text = ""
            raise RestEndpointError(
                f"POST {redact_url(url)} failed with HTTP {exc.code}: {error_text[:2048]}"
            ) from exc
        except URLError as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                time.sleep(min(15.0, (2.0 ** attempt) + random.random()))
                continue
            raise RestEndpointError(f"POST {redact_url(url)} failed: {exc.reason}") from exc
    raise RestEndpointError(
        f"POST {redact_url(url)} failed after {max_attempts} attempts: {last_exc}"
    )


def redact_url(url: str) -> str:
    """Strip the integration key from a logged URL.

    The integration key forms part of the URL path; we replace it with
    ``[REDACTED]`` so log lines never carry the secret material.
    """
    parts = url.split("/integrations/generic/20131114/alert/", 1)
    if len(parts) != 2:
        return url
    suffix = parts[1].split("/", 1)
    routing_key = suffix[1] if len(suffix) > 1 else ""
    return f"{parts[0]}/integrations/generic/20131114/alert/[REDACTED]/{routing_key}"


def dedupe_check(alerts: list[dict[str, Any]]) -> None:
    """Best-effort dedupe sanity check.

    A common operator mistake is to send a CRITICAL with one entity_id and
    a RECOVERY with a different one. We don't reject mismatches outright,
    but we surface them as a structured warning for the operator.
    """
    by_entity: dict[str, list[str]] = {}
    for alert in alerts:
        entity_id = str(alert.get("entity_id", ""))
        message_type = str(alert.get("message_type", ""))
        by_entity.setdefault(entity_id, []).append(message_type)
    warnings: list[dict[str, Any]] = []
    for entity_id, message_types in by_entity.items():
        if "RECOVERY" in message_types and "CRITICAL" not in message_types:
            warnings.append({
                "entity_id": entity_id,
                "message": "RECOVERY without preceding CRITICAL (this is allowed but unusual).",
            })
    if warnings:
        for warning in warnings:
            print(
                f"WARN: entity_id={warning['entity_id']}: {warning['message']}",
                file=sys.stderr,
            )


def send_alerts(
    alerts: list[dict[str, Any]],
    *,
    integration_key: str,
    routing_key: str,
    rest_base: str = _DEFAULT_REST_BASE,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not alerts:
        raise RestEndpointError("No alerts to send.")
    normalized = [normalize_alert(alert, default_routing_key=routing_key) for alert in alerts]
    dedupe_check(normalized)
    results: list[dict[str, Any]] = []
    for index, payload in enumerate(normalized, start=1):
        per_alert_routing_key = str(payload.pop("routing_key", routing_key))
        url = build_url(rest_base, integration_key, per_alert_routing_key)
        result: dict[str, Any] = {
            "index": index,
            "message_type": payload.get("message_type"),
            "entity_id": payload.get("entity_id"),
            "url_template": redact_url(url),
        }
        if dry_run:
            result["dry_run"] = True
            result["payload"] = payload
        else:
            response = post_alert(url, payload)
            result["response"] = response
        results.append(result)
    return {"ok": True, "dry_run": dry_run, "results": results}


def self_test_alerts() -> list[dict[str, Any]]:
    """Synthetic INFO + RECOVERY pair that never opens a real incident."""
    entity_id = f"splunk-oncall-setup-self-test-{uuid.uuid4()}"
    return [
        {
            "alert_name": "self_test_info",
            "message_type": "INFO",
            "entity_id": entity_id,
            "entity_display_name": "splunk-oncall-setup self-test",
            "state_message": "Connectivity self-test from the splunk-oncall-setup skill.",
            "monitoring_tool": "splunk-oncall-setup",
        },
        {
            "alert_name": "self_test_recovery",
            "message_type": "RECOVERY",
            "entity_id": entity_id,
            "state_message": "splunk-oncall-setup self-test complete.",
            "monitoring_tool": "splunk-oncall-setup",
        },
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alert-spec", type=Path)
    parser.add_argument("--integration-key-file", type=Path, required=True)
    parser.add_argument("--routing-key", required=True)
    parser.add_argument("--rest-base", default=_DEFAULT_REST_BASE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args(argv)

    try:
        if args.self_test:
            alerts = self_test_alerts()
        else:
            if args.alert_spec is None:
                parser.error("--alert-spec is required when --self-test is not used")
            spec = load_structured(args.alert_spec)
            alerts = spec.get("rest_alerts") or []
            if not isinstance(alerts, list):
                raise RestEndpointError("rest_alerts must be a list.")
        integration_key = read_secret_file(
            args.integration_key_file, "REST endpoint integration key"
        )
        result = send_alerts(
            alerts,
            integration_key=integration_key,
            routing_key=args.routing_key,
            rest_base=args.rest_base,
            dry_run=args.dry_run,
        )
    except (OSError, RestEndpointError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
