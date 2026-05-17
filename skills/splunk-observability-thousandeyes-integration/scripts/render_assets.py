"""Render the Splunk Observability ThousandEyes Integration artifacts.

Produces:
  - te-payloads/stream.json                       (POST /v7/streams)
  - te-payloads/connector.json                    (POST /v7/connectors/generic)
  - te-payloads/apm-operation.json                (Integrations 2.0 APM op assignment)
  - te-payloads/tests/<slug>.json                 (POST /v7/tests/{type})
  - te-payloads/alert-rules/<slug>.json           (POST /v7/alerts/rules)
  - te-payloads/labels/<slug>.json
  - te-payloads/tags/<slug>.json
  - te-payloads/te-dashboards/<slug>.json
  - te-payloads/templates/<slug>.json
  - dashboards/<test_type>.signalflow.yaml        (for splunk-observability-dashboard-builder)
  - detectors/<test_type>.yaml                    (for splunk-observability-native-ops)
  - scripts/apply-*.sh, list-*.sh, validate-signalflow.sh, handoff-*.sh
  - metadata.json

The renderer never reads token files. Apply scripts read tokens from chmod-600
files at runtime and keep secret values out of argv and rendered files.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SKILL_NAME = "splunk-observability-thousandeyes-integration"


def _load_yaml_module():
    """Lazy import PyYAML with a clear actionable error.

    Mirrors the pattern in
    skills/splunk-observability-cloud-integration-setup/scripts/render_assets.py
    so JSON specs work even when PyYAML is not installed in the operator's
    Python.
    """
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise SpecError(
            "PyYAML is required to parse YAML specs. Install with "
            "'python3 -m pip install -r requirements-agent.txt' or pass a "
            "JSON spec."
        ) from exc
    return yaml
TE_API_BASE = "https://api.thousandeyes.com/v7"
APM_OPERATION_TYPE = "splunk-observability-apm"

VALID_REALMS = {"us0", "us1", "eu0", "eu1", "eu2", "au0", "jp0", "sg0", "us2-gcp"}
VALID_SIGNALS = {"metric", "trace", "log"}
VALID_ENDPOINT_TYPES = {"http", "grpc"}
VALID_DOMAINS = {"cea", "endpoint"}
VALID_TEST_TYPES = {
    "http-server",
    "page-load",
    "web-transactions",
    "api",
    "api-step",
    "agent-to-server",
    "agent-to-agent",
    "bgp",
    "dns-server",
    "dns-trace",
    "dnssec",
    "sip-server",
    "voice",
    "ftp-server",
}
VALID_ALERT_TYPES = {
    "page-load",
    "http-server",
    "end-to-end-server",
    "end-to-end-agent",
    "voice",
    "dns-server",
    "dns-trace",
    "dnssec",
    "bgp",
    "path-trace",
    "ftp",
    "sip-server",
    "transactions",
    "web-transactions",
    "agent",
    "network-outage",
    "application-outage",
    "device-device",
    "device-interface",
    "endpoint-network-server",
    "endpoint-http-server",
    "endpoint-path-trace",
    "endpoint-browser-sessions-agent",
    "endpoint-browser-sessions-application",
    "api",
    "web-transaction",
    "unknown",
}
ALERT_TYPE_BY_TEST_TYPE = {
    "agent-to-server": "end-to-end-server",
    "agent-to-agent": "end-to-end-agent",
    "ftp-server": "ftp",
    "api-step": "api",
}
ALERT_SEVERITY_ALIASES = {
    "info": "info",
    "informational": "info",
    "minor": "minor",
    "warning": "minor",
    "warn": "minor",
    "major": "major",
    "critical": "critical",
    "crit": "critical",
    "unknown": "unknown",
}
ALERT_ROUNDS_MODE_ALIASES = {"exact": "exact", "any": "any", "auto": "auto"}
ALERT_SENSITIVITY_ALIASES = {"high": "high", "medium": "medium", "low": "low"}
ALERT_DIRECTIONS = {"to-target", "from-target", "bidirectional"}
ALERT_GROUP_TYPES = {"bgp", "browser-session", "cloud-enterprise", "endpoint"}
THIRD_PARTY_NOTIFICATION_ALIASES = {
    "app-dynamics": "app-dynamics",
    "appdynamics": "app-dynamics",
    "pager-duty": "pager-duty",
    "pagerduty": "pager-duty",
    "service-now": "service-now",
    "servicenow": "service-now",
    "slack": "slack",
}

# Canonical TE OpenTelemetry Data Model v2 metric mapping per test type.
# Sourced from docs.thousandeyes.com/.../opentelemetry/data-model/data-model-v2/metrics.
# When ThousandEyes adds a new metric, append to the list below; the
# renderer treats each entry as a chart in the per-test-type dashboard.
PER_TYPE_METRICS: dict[str, list[str]] = {
    "agent-to-server": ["network.latency", "network.loss", "network.jitter"],
    "agent-to-agent": ["network.latency", "network.loss", "network.jitter"],
    "http-server": [
        "http.server.request.availability",
        "http.server.throughput",
        "http.client.request.duration",
    ],
    "page-load": ["web.page_load.duration", "web.page_load.completion"],
    "web-transactions": [
        "web.transaction.duration",
        "web.transaction.errors.count",
        "web.transaction.completion",
    ],
    "api": ["api.duration", "api.completion"],
    "api-step": ["api.step.duration", "api.step.completion"],
    "bgp": ["bgp.path_changes.count", "bgp.reachability", "bgp.updates.count"],
    "dns-server": ["dns.lookup.availability", "dns.lookup.duration"],
    "dns-trace": ["dns.lookup.availability", "dns.lookup.duration"],
    "dnssec": ["dns.lookup.validity"],
    "voice": [
        "rtp.client.request.mos",
        "rtp.client.request.loss",
        "rtp.client.request.discards",
        "rtp.client.request.duration",
        "rtp.client.request.pdv",
    ],
    "sip-server": [
        "sip.server.request.availability",
        "sip.client.request.duration",
        "sip.client.request.total_time",
    ],
    "ftp-server": [
        "ftp.server.request.availability",
        "ftp.client.request.duration",
        "ftp.server.throughput",
    ],
}

# Default starter detectors per test type. Each entry is parameterised by
# the spec.detectors.thresholds.<test_type> block.
DEFAULT_DETECTORS: dict[str, list[dict[str, Any]]] = {
    "agent-to-server": [
        {"metric": "network.latency", "threshold_key": "latency_ms_max", "direction": "above", "severity": "Warning"},
        {"metric": "network.loss", "threshold_key": "loss_pct_max", "direction": "above", "severity": "Major"},
    ],
    "agent-to-agent": [
        {"metric": "network.latency", "threshold_key": "latency_ms_max", "direction": "above", "severity": "Warning"},
        {"metric": "network.loss", "threshold_key": "loss_pct_max", "direction": "above", "severity": "Major"},
    ],
    "http-server": [
        {"metric": "http.server.request.availability", "threshold_key": "availability_floor", "direction": "below", "severity": "Major"},
        {"metric": "http.client.request.duration", "threshold_key": "duration_p95_ms", "direction": "above", "severity": "Warning", "aggregation": "p95"},
    ],
    "bgp": [
        {"metric": "bgp.reachability", "threshold_key": "reachability_floor", "direction": "below", "severity": "Critical"},
    ],
    "voice": [
        {"metric": "rtp.client.request.mos", "threshold_key": "mos_floor", "direction": "below", "severity": "Major"},
    ],
}


class SpecError(ValueError):
    """Raised when the input spec violates skill constraints."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--realm", default="")
    parser.add_argument("--te-token-file", default="")
    parser.add_argument("--o11y-ingest-token-file", default="")
    parser.add_argument("--o11y-api-token-file", default="")
    parser.add_argument("--apply", default="", help="comma-separated apply sections")
    parser.add_argument("--accept-te-mutations", default="false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def bool_flag(value: str) -> bool:
    return str(value).lower() == "true"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "item"


def load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            data = json.loads(text)
        else:
            yaml = _load_yaml_module()
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError:
                data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SpecError(f"Failed to parse spec {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"Spec {path} did not parse to a mapping.")
    if data.get("api_version") != f"{SKILL_NAME}/v1":
        raise SpecError(
            f"Spec api_version must be '{SKILL_NAME}/v1'; got {data.get('api_version')!r}"
        )
    return data


def reject_inline_secrets(payload: Any, *, path: str = "") -> None:
    """Walk a payload and raise SpecError if a likely secret value appears.

    The skill must never embed credentials in rendered payloads; tokens are
    supplied via --o11y-ingest-token-file at apply time. We block obvious
    hits (X-SF-Token, Bearer, Authorization values that look like real
    secrets) so a misconfigured spec doesn't ship a token to disk.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            sub_path = f"{path}.{key}" if path else key
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            if normalized in {"x_sf_token", "access_token", "bearer_token", "api_token", "te_token", "token", "authorization"}:
                if isinstance(value, str) and len(value) >= 12 and not value.startswith("{{") and "PLACEHOLDER" not in value.upper():
                    raise SpecError(
                        f"Inline secret field at {sub_path}; remove the value from the spec "
                        f"(use file-based --*-token-file flags or Handlebars placeholders for templates)."
                    )
            reject_inline_secrets(value, path=sub_path)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            reject_inline_secrets(item, path=f"{path}[{index}]")


def resolve_realm(args: argparse.Namespace, spec: dict[str, Any]) -> str:
    realm = args.realm or spec.get("realm") or ""
    if not realm:
        raise SpecError("realm is required (set in spec or pass --realm).")
    if realm not in VALID_REALMS:
        raise SpecError(f"Invalid realm {realm!r}. Valid: {sorted(VALID_REALMS)}")
    return realm


def stream_payload(spec: dict[str, Any], realm: str) -> dict[str, Any] | None:
    block = spec.get("stream") or {}
    if not block.get("enabled", False):
        return None
    signal = block.get("signal", "metric")
    if signal not in VALID_SIGNALS:
        raise SpecError(f"stream.signal must be one of {sorted(VALID_SIGNALS)}; got {signal!r}")
    endpoint_type = block.get("endpoint_type", "http")
    if endpoint_type not in VALID_ENDPOINT_TYPES:
        raise SpecError(f"stream.endpoint_type must be one of {sorted(VALID_ENDPOINT_TYPES)}; got {endpoint_type!r}")
    data_model_version = block.get("data_model_version", "v2")
    if data_model_version not in {"v1", "v2"}:
        raise SpecError(f"stream.data_model_version must be v1 or v2; got {data_model_version!r}")
    endpoint_url = block.get("endpoint_url") or default_ingest_url(realm, endpoint_type)
    custom_headers = {
        # Splunk ingest endpoint authenticates via X-SF-Token. The actual
        # token value is supplied at apply time from --o11y-ingest-token-file
        # via a runtime placeholder substitution.
        "X-SF-Token": "${O11Y_INGEST_TOKEN}",
        "Content-Type": "application/x-protobuf" if endpoint_type == "http" else "application/grpc",
    }
    payload: dict[str, Any] = {
        "type": "opentelemetry",
        "signal": signal,
        "endpointType": endpoint_type,
        "streamEndpointUrl": endpoint_url,
        "dataModelVersion": data_model_version,
        "customHeaders": custom_headers,
        "enabled": bool(block.get("enabled", True)),
    }
    test_match = block.get("test_match") or []
    filters_block = block.get("filters") or {}
    test_types = filters_block.get("test_types") or []
    mode = (block.get("mode") or "").lower()
    selectors_used = sum(bool(x) for x in (test_match, test_types, mode == "all"))
    if selectors_used == 0:
        raise SpecError(
            "stream selection is required: provide stream.test_match[] OR "
            "stream.filters.test_types[] OR stream.mode='all'."
        )
    if mode == "all":
        # No testMatch / filters -> stream every enabled test in the account group.
        pass
    if test_match:
        normalized: list[dict[str, Any]] = []
        for index, entry in enumerate(test_match):
            if not isinstance(entry, dict):
                raise SpecError(f"stream.test_match[{index}] must be a mapping.")
            test_id = str(entry.get("id", "")).strip()
            domain = entry.get("domain", "cea")
            if not test_id:
                raise SpecError(f"stream.test_match[{index}].id is required.")
            if domain not in VALID_DOMAINS:
                raise SpecError(
                    f"stream.test_match[{index}].domain must be one of {sorted(VALID_DOMAINS)}; got {domain!r}"
                )
            normalized.append({"id": test_id, "domain": domain})
        payload["testMatch"] = normalized
    if test_types:
        for test_type in test_types:
            if test_type not in VALID_TEST_TYPES:
                raise SpecError(
                    f"stream.filters.test_types includes unknown type {test_type!r}. "
                    f"Valid: {sorted(VALID_TEST_TYPES)}"
                )
        payload.setdefault("filters", {})["testTypes"] = list(test_types)
    return payload


def default_ingest_url(realm: str, endpoint_type: str) -> str:
    if endpoint_type == "http":
        return f"https://ingest.{realm}.signalfx.com/v2/datapoint/otlp"
    return f"https://ingest.{realm}.signalfx.com:443"


def default_api_url(realm: str) -> str:
    return f"https://api.{realm}.signalfx.com"


def apm_connector_payload(spec: dict[str, Any], realm: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    block = spec.get("apm_connector") or {}
    if not block.get("enabled", False):
        return None
    name = block.get("connector_name", "Splunk Observability APM")
    op_name = block.get("operation_name", "Splunk Observability APM")
    target_url = block.get("api_url") or default_api_url(realm)
    connector = {
        "type": "generic",
        "name": name,
        # The TE generic-connector model holds the URL on `target` and any
        # custom headers under `headers[]`.
        "target": target_url.rstrip("/"),
        "headers": [{"name": "X-SF-Token", "value": "${O11Y_API_TOKEN}"}],
    }
    operation = {
        "type": APM_OPERATION_TYPE,
        "name": op_name,
        "enabled": True,
        # Connector ID is filled in at apply time after the connector POST
        # returns; we render the placeholder so the operator sees the shape.
        "connectorId": "${TE_CONNECTOR_ID}",
    }
    return connector, operation


def test_payloads(spec: dict[str, Any]) -> list[dict[str, Any]]:
    items = spec.get("tests") or []
    rendered: list[dict[str, Any]] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise SpecError(f"tests[{index}] must be a mapping.")
        test_type = raw.get("type")
        if test_type not in VALID_TEST_TYPES:
            raise SpecError(
                f"tests[{index}].type must be one of {sorted(VALID_TEST_TYPES)}; got {test_type!r}"
            )
        name = raw.get("name")
        if not name:
            raise SpecError(f"tests[{index}].name is required.")
        # Common TE test fields. Per-type fields (target/url/server/agents/...)
        # are passed through verbatim.
        body = {
            "interval": int(raw.get("interval", 60)),
            "enabled": bool(raw.get("enabled", True)),
            "alertsEnabled": bool(raw.get("alerts_enabled", False)),
            "testName": name,
        }
        if "agents" in raw:
            body["agents"] = [{"agentId": str(agent_id)} for agent_id in raw["agents"]]
        if "alert_rules" in raw:
            body["alertRules"] = [{"ruleId": str(rule_id)} for rule_id in raw["alert_rules"]]
        # Pass through type-specific fields under their TE-canonical names.
        for source_key, target_key in (
            ("target", "url"),
            ("url", "url"),
            ("server", "server"),
            ("port", "port"),
            ("protocol", "protocol"),
            ("description", "description"),
            ("source_agent_id", "sourceAgentId"),
            ("target_agent_id", "targetAgentId"),
            ("dscp_id", "dscpId"),
            ("throughput_rate_mbps", "throughputRate"),
            ("codec_id", "codecId"),
            ("duration", "duration"),
        ):
            if source_key in raw:
                body[target_key] = raw[source_key]
        rendered.append({"type": test_type, "slug": slugify(name), "body": body})
    return rendered


def alert_type_for_rule(raw: dict[str, Any], test_type: str | None, index: int) -> str:
    alert_type = str(raw.get("alert_type") or raw.get("alertType") or "").strip()
    if not alert_type and test_type:
        alert_type = ALERT_TYPE_BY_TEST_TYPE.get(test_type, test_type)
    if not alert_type:
        raise SpecError(
            f"alert_rules[{index}].alert_type is required when test_type is omitted."
        )
    if alert_type not in VALID_ALERT_TYPES:
        raise SpecError(
            f"alert_rules[{index}].alert_type {alert_type!r} is not a known ThousandEyes v7 alertType."
        )
    return alert_type


def normalize_alert_severity(raw: dict[str, Any], index: int) -> str:
    value = str(raw.get("severity") or "minor").strip().lower()
    severity = ALERT_SEVERITY_ALIASES.get(value)
    if severity is None:
        allowed = ", ".join(sorted(set(ALERT_SEVERITY_ALIASES.values())))
        raise SpecError(
            f"alert_rules[{index}].severity {value!r} is invalid; use one of: {allowed}."
        )
    return severity


def normalize_notification_entry(entry: dict[str, Any], rule_index: int, notification_index: int) -> tuple[str, dict[str, Any]]:
    kind = str(entry.get("type") or entry.get("integrationType") or "").strip().lower()
    kind = kind.replace("_", "-")
    if kind == "customwebhook":
        kind = "custom-webhook"

    if kind == "email":
        recipients = entry.get("recipients") or entry.get("recipient")
        if isinstance(recipients, str):
            recipients = [recipients]
        if not isinstance(recipients, list) or not recipients:
            raise SpecError(
                f"alert_rules[{rule_index}].notifications[{notification_index}] email requires recipients."
            )
        return "email", {"recipients": [str(item) for item in recipients]}

    if kind == "custom-webhook":
        integration_id = str(entry.get("integrationId") or entry.get("integration_id") or "").strip()
        if not integration_id:
            raise SpecError(
                f"alert_rules[{rule_index}].notifications[{notification_index}] custom webhook requires integrationId."
            )
        payload = {
            "integrationId": integration_id,
            "integrationType": "custom-webhook",
        }
        for source_key, target_key in (
            ("integrationName", "integrationName"),
            ("integration_name", "integrationName"),
            ("target", "target"),
        ):
            if entry.get(source_key):
                payload[target_key] = entry[source_key]
        return "customWebhook", payload

    if kind == "webhook":
        integration_id = str(entry.get("integrationId") or entry.get("integration_id") or "").strip()
        if not integration_id:
            raise SpecError(
                f"alert_rules[{rule_index}].notifications[{notification_index}] webhook requires integrationId."
            )
        payload = {
            "integrationId": integration_id,
            "integrationType": "webhook",
        }
        if entry.get("integrationName") or entry.get("integration_name"):
            payload["integrationName"] = entry.get("integrationName") or entry.get("integration_name")
        if entry.get("target"):
            payload["target"] = entry["target"]
        return "webhook", payload

    if kind in THIRD_PARTY_NOTIFICATION_ALIASES:
        integration_id = str(entry.get("integrationId") or entry.get("integration_id") or "").strip()
        if not integration_id:
            raise SpecError(
                f"alert_rules[{rule_index}].notifications[{notification_index}] {kind} requires integrationId."
            )
        payload = {
            "integrationId": integration_id,
            "integrationType": THIRD_PARTY_NOTIFICATION_ALIASES[kind],
        }
        if entry.get("integrationName") or entry.get("integration_name"):
            payload["integrationName"] = entry.get("integrationName") or entry.get("integration_name")
        return "thirdParty", payload

    raise SpecError(
        f"alert_rules[{rule_index}].notifications[{notification_index}].type {kind!r} is not supported."
    )


def normalize_alert_notifications(raw: Any, index: int) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    if isinstance(raw, dict):
        normalized: dict[str, Any] = {}
        for key, value in raw.items():
            if key in {"email", "thirdParty", "webhook", "customWebhook"}:
                if key == "email":
                    if not isinstance(value, dict):
                        raise SpecError(f"alert_rules[{index}].notifications.email must be a mapping.")
                    email = dict(value)
                    if "recipient" in email and "recipients" not in email:
                        email["recipients"] = email.pop("recipient")
                    normalized[key] = email
                elif not isinstance(value, list):
                    raise SpecError(f"alert_rules[{index}].notifications.{key} must be a list.")
                else:
                    normalized[key] = value
            else:
                normalized[key] = value
        return normalized
    if not isinstance(raw, list):
        raise SpecError(f"alert_rules[{index}].notifications must be a mapping or list.")

    normalized: dict[str, Any] = {}
    for notification_index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise SpecError(
                f"alert_rules[{index}].notifications[{notification_index}] must be a mapping."
            )
        key, payload = normalize_notification_entry(entry, index, notification_index)
        if key == "email":
            if "email" in normalized:
                existing = normalized["email"].setdefault("recipients", [])
                existing.extend(payload["recipients"])
            else:
                normalized["email"] = payload
            continue
        normalized.setdefault(key, []).append(payload)
    return normalized


def append_alert_optional_fields(body: dict[str, Any], raw: dict[str, Any], index: int) -> None:
    if raw.get("description"):
        body["description"] = raw["description"]
    for source_key, target_key in (
        ("notify_on_clear", "notifyOnClear"),
        ("notifyOnClear", "notifyOnClear"),
        ("is_default", "isDefault"),
        ("isDefault", "isDefault"),
        ("include_covered_prefixes", "includeCoveredPrefixes"),
        ("includeCoveredPrefixes", "includeCoveredPrefixes"),
    ):
        if source_key in raw:
            body[target_key] = bool(raw[source_key])

    mode = raw.get("rounds_violating_mode") or raw.get("roundsViolatingMode")
    if mode is not None:
        normalized_mode = ALERT_ROUNDS_MODE_ALIASES.get(str(mode).strip().lower())
        if normalized_mode is None:
            raise SpecError(
                f"alert_rules[{index}].rounds_violating_mode {mode!r} is invalid; use exact, any, or auto."
            )
        body["roundsViolatingMode"] = normalized_mode

    sensitivity = raw.get("sensitivity_level") or raw.get("sensitivityLevel")
    if sensitivity is not None:
        normalized_sensitivity = ALERT_SENSITIVITY_ALIASES.get(str(sensitivity).strip().lower())
        if normalized_sensitivity is None:
            raise SpecError(
                f"alert_rules[{index}].sensitivity_level {sensitivity!r} is invalid; use high, medium, or low."
            )
        body["sensitivityLevel"] = normalized_sensitivity

    alert_group_type = raw.get("alert_group_type") or raw.get("alertGroupType")
    if alert_group_type is not None:
        normalized_group = str(alert_group_type).strip().lower()
        if normalized_group not in ALERT_GROUP_TYPES:
            allowed = ", ".join(sorted(ALERT_GROUP_TYPES))
            raise SpecError(
                f"alert_rules[{index}].alert_group_type {alert_group_type!r} is invalid; use one of: {allowed}."
            )
        body["alertGroupType"] = normalized_group

    direction = raw.get("direction")
    if direction is not None:
        normalized_direction = str(direction).strip().lower()
        if normalized_direction not in ALERT_DIRECTIONS:
            allowed = ", ".join(sorted(ALERT_DIRECTIONS))
            raise SpecError(
                f"alert_rules[{index}].direction {direction!r} is invalid; use one of: {allowed}."
            )
        body["direction"] = normalized_direction

    if raw.get("minimum_sources_pct") is not None:
        body["minimumSourcesPct"] = int(raw["minimum_sources_pct"])

    for source_key, target_key in (
        ("endpoint_agent_ids", "endpointAgentIds"),
        ("endpointAgentIds", "endpointAgentIds"),
        ("endpoint_label_ids", "endpointLabelIds"),
        ("endpointLabelIds", "endpointLabelIds"),
        ("visited_sites_filter", "visitedSitesFilter"),
        ("visitedSitesFilter", "visitedSitesFilter"),
        ("test_ids", "testIds"),
        ("testIds", "testIds"),
    ):
        if source_key in raw:
            value = raw[source_key]
            if not isinstance(value, list):
                raise SpecError(f"alert_rules[{index}].{source_key} must be a list.")
            body[target_key] = [str(item) for item in value]


def alert_rule_payloads(spec: dict[str, Any]) -> list[dict[str, Any]]:
    items = spec.get("alert_rules") or []
    rendered: list[dict[str, Any]] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise SpecError(f"alert_rules[{index}] must be a mapping.")
        name = raw.get("name")
        if not name:
            raise SpecError(f"alert_rules[{index}].name is required.")
        test_type = raw.get("test_type")
        if test_type and test_type not in VALID_TEST_TYPES:
            raise SpecError(
                f"alert_rules[{index}].test_type {test_type!r} is not a canonical TE OTel v2 type."
            )
        deprecated_fields = sorted({"threshold", "window_seconds", "windowSeconds"} & set(raw))
        if deprecated_fields:
            raise SpecError(
                f"alert_rules[{index}] uses deprecated synthetic fields {deprecated_fields}; "
                "use ThousandEyes v7 expression instead."
            )
        expression = str(raw.get("expression") or "").strip()
        if not expression:
            raise SpecError(f"alert_rules[{index}].expression is required.")
        rounds_required = int(raw.get("rounds_violating_required", 1))
        rounds_out_of = int(raw.get("rounds_violating_out_of", 1))
        if rounds_required < 1 or rounds_out_of < 1 or rounds_required > rounds_out_of:
            raise SpecError(
                f"alert_rules[{index}] rounds_violating_required must be between 1 and rounds_violating_out_of."
            )
        body = {
            "ruleName": name,
            "expression": expression,
            "alertType": alert_type_for_rule(raw, test_type, index),
            "minimumSources": int(raw.get("min_sources", raw.get("minimumSources", 1))),
            "roundsViolatingRequired": rounds_required,
            "roundsViolatingOutOf": rounds_out_of,
            "severity": normalize_alert_severity(raw, index),
            "notifications": normalize_alert_notifications(raw.get("notifications"), index),
        }
        append_alert_optional_fields(body, raw, index)
        rendered.append({"slug": slugify(name), "body": body})
    return rendered


def label_payloads(spec: dict[str, Any]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for index, raw in enumerate(spec.get("labels") or []):
        if not isinstance(raw, dict):
            raise SpecError(f"labels[{index}] must be a mapping.")
        name = raw.get("name")
        if not name:
            raise SpecError(f"labels[{index}].name is required.")
        rendered.append(
            {"slug": slugify(name), "body": {"name": name, "color": raw.get("color")}}
        )
    return rendered


def tag_payloads(spec: dict[str, Any]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for index, raw in enumerate(spec.get("tags") or []):
        if not isinstance(raw, dict):
            raise SpecError(f"tags[{index}] must be a mapping.")
        name = raw.get("name")
        if not name:
            raise SpecError(f"tags[{index}].name is required.")
        rendered.append({"slug": slugify(name), "body": {"name": name}})
    return rendered


def te_dashboard_payloads(spec: dict[str, Any]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for index, raw in enumerate(spec.get("te_dashboards") or []):
        if not isinstance(raw, dict):
            raise SpecError(f"te_dashboards[{index}] must be a mapping.")
        name = raw.get("name")
        if not name:
            raise SpecError(f"te_dashboards[{index}].name is required.")
        rendered.append({"slug": slugify(name), "body": raw})
    return rendered


def template_payloads(spec: dict[str, Any]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for index, raw in enumerate(spec.get("templates") or []):
        if not isinstance(raw, dict):
            raise SpecError(f"templates[{index}] must be a mapping.")
        name = raw.get("name")
        if not name:
            raise SpecError(f"templates[{index}].name is required.")
        body = {"name": name, "description": raw.get("description", "")}
        if "template_body" in raw:
            template_body = raw["template_body"]
            # Enforce Handlebars placeholders for credentials. We walk the
            # template_body and reject any inline secret-looking value that
            # is not a {{handlebars}} reference. The TE API itself returns
            # HTTP 400 for plain-text credentials; we fail render-time so the
            # operator catches it before the network call.
            _enforce_handlebars_credentials(template_body, path="template_body")
            body["templateBody"] = template_body
        rendered.append({"slug": slugify(name), "body": body})
    return rendered


def _enforce_handlebars_credentials(payload: Any, *, path: str) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            if normalized in {"password", "secret", "token", "api_key", "client_secret", "bearer", "authorization"}:
                if isinstance(value, str) and value and not (value.startswith("{{") and value.endswith("}}")):
                    raise SpecError(
                        f"templates field {path}.{key} must be a Handlebars placeholder "
                        f"(e.g. '{{{{te_credentials.api_key}}}}'); plain text is rejected by the TE API."
                    )
            _enforce_handlebars_credentials(value, path=f"{path}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            _enforce_handlebars_credentials(item, path=f"{path}[{index}]")


def collect_test_types_for_handoff(spec: dict[str, Any]) -> list[str]:
    """Resolve the test-type set used for dashboards/detectors hand-off.

    Order of precedence:
      1. Explicit dashboards.test_types or detectors.test_types from spec.
      2. Union of stream.filters.test_types and tests[].type.
    """
    explicit = (spec.get("dashboards") or {}).get("test_types") or []
    if explicit:
        return [t for t in explicit if t in VALID_TEST_TYPES]
    derived: list[str] = []
    for test_type in (spec.get("stream") or {}).get("filters", {}).get("test_types", []) or []:
        if test_type in VALID_TEST_TYPES and test_type not in derived:
            derived.append(test_type)
    for entry in spec.get("tests") or []:
        test_type = entry.get("type") if isinstance(entry, dict) else None
        if test_type in VALID_TEST_TYPES and test_type not in derived:
            derived.append(test_type)
    return derived


def signalflow_dashboard_spec(test_type: str) -> dict[str, Any]:
    metrics = PER_TYPE_METRICS.get(test_type, [])
    charts = []
    for metric in metrics:
        program_text = (
            f"data('{metric}', filter=filter('thousandeyes.account.id', '${{ACCOUNT_GROUP_ID}}')"
            f" and filter('thousandeyes.test.id', '${{TEST_ID}}'))"
            f".publish(label='{metric}')"
        )
        charts.append(
            {
                "name": metric,
                "description": f"{metric} for ThousandEyes {test_type} tests",
                "program_text": program_text,
                "publish_label": metric,
            }
        )
    return {
        "name": f"ThousandEyes {test_type}",
        "description": f"Auto-rendered SignalFlow dashboard for ThousandEyes {test_type} tests",
        "charts": charts,
        "filters": [
            {"property": "thousandeyes.account.id", "value": "${ACCOUNT_GROUP_ID}"},
        ],
    }


def detector_spec(test_type: str, thresholds: dict[str, Any]) -> dict[str, Any]:
    detectors = []
    for entry in DEFAULT_DETECTORS.get(test_type, []):
        threshold_value = thresholds.get(entry["threshold_key"])
        if threshold_value is None:
            continue
        detectors.append(
            {
                "name": f"TE {test_type} {entry['metric']}",
                "metric": entry["metric"],
                "direction": entry["direction"],
                "threshold": threshold_value,
                "severity": entry["severity"],
                "aggregation": entry.get("aggregation", "mean"),
            }
        )
    return {
        "test_type": test_type,
        "detectors": detectors,
    }


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_yaml(path: Path, payload: Any) -> None:
    yaml = _load_yaml_module()
    write_text(path, yaml.safe_dump(payload, sort_keys=True, default_flow_style=False))


def render_apply_script(
    name: str,
    *,
    body: str,
    requires_te_token: bool = False,
    requires_o11y_ingest: bool = False,
    requires_o11y_api: bool = False,
    requires_mutation_gate: bool = False,
) -> str:
    head = ["#!/usr/bin/env bash", "set -euo pipefail", "", f"# {name}"]
    if requires_mutation_gate:
        head.extend(
            [
                'if [[ "${ACCEPT_TE_MUTATIONS:-false}" != "true" ]]; then',
                "    echo \"ERROR: TE-side mutations require --i-accept-te-mutations.\" >&2",
                "    exit 1",
                "fi",
                "",
            ]
        )
    if requires_te_token:
        head.extend(
            [
                'if [[ -z "${TE_TOKEN_FILE:-}" || ! -r "${TE_TOKEN_FILE}" ]]; then',
                "    echo \"ERROR: TE_TOKEN_FILE must point at a readable token file.\" >&2",
                "    exit 1",
                "fi",
                'TE_CURL_CONFIG="$(mktemp)"',
                'chmod 600 "${TE_CURL_CONFIG}"',
                '{ printf \'header = "Authorization: Bearer \'; tr -d \'\\r\\n\' < "${TE_TOKEN_FILE}"; printf \'"\\n\'; } > "${TE_CURL_CONFIG}"',
                'trap \'rm -f "${TE_CURL_CONFIG}"\' EXIT',
                "",
            ]
        )
    if requires_o11y_ingest:
        head.extend(
            [
                'if [[ -z "${O11Y_INGEST_TOKEN_FILE:-}" || ! -r "${O11Y_INGEST_TOKEN_FILE}" ]]; then',
                "    echo \"ERROR: O11Y_INGEST_TOKEN_FILE must point at a readable token file.\" >&2",
                "    exit 1",
                "fi",
                "",
            ]
        )
    if requires_o11y_api:
        head.extend(
            [
                'if [[ -z "${O11Y_API_TOKEN_FILE:-}" || ! -r "${O11Y_API_TOKEN_FILE}" ]]; then',
                "    echo \"ERROR: O11Y_API_TOKEN_FILE must point at a readable token file.\" >&2",
                "    exit 1",
                "fi",
                "",
            ]
        )
    head.append(body)
    return "\n".join(head) + "\n"


APPLY_STREAM_BODY = """\
# Apply: POST /v7/streams (or PUT if --te-stream-id supplied).
# Substitutes the X-SF-Token placeholder in stream.json with the live token.
PAYLOAD_FILE="$(dirname "${BASH_SOURCE[0]}")/../te-payloads/stream.json"
SUBST_PAYLOAD="$(python3 -c "import json,sys;
data=json.load(open(sys.argv[1]));
data['customHeaders']['X-SF-Token']=open(sys.argv[2]).read().strip();
print(json.dumps(data))" "${PAYLOAD_FILE}" "${O11Y_INGEST_TOKEN_FILE}")"
if [[ -n "${TE_STREAM_ID:-}" ]]; then
    METHOD=PUT
    URL="https://api.thousandeyes.com/v7/streams/${TE_STREAM_ID}"
else
    METHOD=POST
    URL="https://api.thousandeyes.com/v7/streams"
fi
curl -sS -X "${METHOD}" "${URL}" \\
    -K "${TE_CURL_CONFIG}" \\
    -H "Content-Type: application/json" \\
    --data-binary "${SUBST_PAYLOAD}" \\
    -o /tmp/te-stream-response.json -w '%{http_code}\\n'
"""

APPLY_APM_CONNECTOR_BODY = """\
# Apply: POST /v7/connectors/generic, then enable splunk-observability-apm operation.
CONNECTOR_FILE="$(dirname "${BASH_SOURCE[0]}")/../te-payloads/connector.json"
OPERATION_FILE="$(dirname "${BASH_SOURCE[0]}")/../te-payloads/apm-operation.json"
SUBST_CONNECTOR="$(python3 -c "import json,sys;
data=json.load(open(sys.argv[1]));
for h in data.get('headers', []):
    if h.get('name')=='X-SF-Token':
        h['value']=open(sys.argv[2]).read().strip();
print(json.dumps(data))" "${CONNECTOR_FILE}" "${O11Y_API_TOKEN_FILE}")"
CONNECTOR_RESPONSE="$(curl -sS -X POST 'https://api.thousandeyes.com/v7/connectors/generic' \\
    -K "${TE_CURL_CONFIG}" \\
    -H "Content-Type: application/json" \\
    --data-binary "${SUBST_CONNECTOR}")"
echo "${CONNECTOR_RESPONSE}" > /tmp/te-connector-response.json
CONNECTOR_ID="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('id',''))" "${CONNECTOR_RESPONSE}")"
if [[ -z "${CONNECTOR_ID}" ]]; then
    echo "ERROR: connector POST did not return an id." >&2
    exit 1
fi
SUBST_OPERATION="$(python3 -c "import json,sys;
data=json.load(open(sys.argv[1]));
data['connectorId']=sys.argv[2];
print(json.dumps(data))" "${OPERATION_FILE}" "${CONNECTOR_ID}")"
curl -sS -X PUT "https://api.thousandeyes.com/v7/operations/splunk-observability-apm/${CONNECTOR_ID}" \\
    -K "${TE_CURL_CONFIG}" \\
    -H "Content-Type: application/json" \\
    --data-binary "${SUBST_OPERATION}" \\
    -o /tmp/te-apm-operation-response.json -w '%{http_code}\\n'
"""

APPLY_TESTS_BODY = """\
# Apply: POST /v7/tests/{type} for each rendered test payload.
PAYLOADS_DIR="$(dirname "${BASH_SOURCE[0]}")/../te-payloads/tests"
if [[ ! -d "${PAYLOADS_DIR}" ]]; then
    echo "No tests/ payloads directory; nothing to apply."
    exit 0
fi
INDEX_FILE="${PAYLOADS_DIR}/_index.json"
if [[ ! -f "${INDEX_FILE}" ]]; then
    echo "ERROR: ${INDEX_FILE} missing; cannot resolve test types." >&2
    exit 1
fi
python3 - "${INDEX_FILE}" <<'PY'
import json
import os
import subprocess
import sys

items = json.load(open(sys.argv[1], encoding="utf-8"))
for item in items:
    payload_file = os.path.join(os.path.dirname(sys.argv[1]), item["file"])
    url = f"https://api.thousandeyes.com/v7/tests/{item['type']}"
    cmd = [
        "curl",
        "-sS",
        "-X",
        "POST",
        url,
        "-K",
        os.environ["TE_CURL_CONFIG"],
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        f"@{payload_file}",
        "-o",
        f"/tmp/te-test-{item['slug']}.json",
        "-w",
        "%{http_code}\\n",
    ]
    print(item["slug"], end=": ")
    sys.stdout.flush()
    subprocess.run(cmd, check=True)
PY
"""

APPLY_ALERT_RULES_BODY = """\
# Apply: POST /v7/alerts/rules for each rendered alert rule payload.
PAYLOADS_DIR="$(dirname "${BASH_SOURCE[0]}")/../te-payloads/alert-rules"
if [[ ! -d "${PAYLOADS_DIR}" ]]; then
    echo "No alert-rules/ payloads directory; nothing to apply."
    exit 0
fi
for payload in "${PAYLOADS_DIR}"/*.json; do
    [[ -f "${payload}" ]] || continue
    echo "$(basename "${payload}"): "
    curl -sS -X POST 'https://api.thousandeyes.com/v7/alerts/rules' \\
        -K "${TE_CURL_CONFIG}" \\
        -H "Content-Type: application/json" \\
        --data-binary @"${payload}" \\
        -o "/tmp/te-alert-rule-$(basename "${payload}")" -w '%{http_code}\\n'
done
"""

APPLY_LABELS_TAGS_BODY = """\
# Apply: POST /v7/labels and /v7/tags.
for kind in labels tags; do
    DIR="$(dirname "${BASH_SOURCE[0]}")/../te-payloads/${kind}"
    [[ -d "${DIR}" ]] || continue
    for payload in "${DIR}"/*.json; do
        [[ -f "${payload}" ]] || continue
        echo "${kind}/$(basename "${payload}"): "
        curl -sS -X POST "https://api.thousandeyes.com/v7/${kind}" \\
            -K "${TE_CURL_CONFIG}" \\
            -H "Content-Type: application/json" \\
            --data-binary @"${payload}" \\
            -o "/tmp/te-${kind}-$(basename "${payload}")" -w '%{http_code}\\n'
    done
done
"""

APPLY_TE_DASHBOARDS_BODY = """\
# Apply: POST /v7/dashboards.
PAYLOADS_DIR="$(dirname "${BASH_SOURCE[0]}")/../te-payloads/te-dashboards"
[[ -d "${PAYLOADS_DIR}" ]] || { echo "No te-dashboards/ payloads; nothing to apply."; exit 0; }
for payload in "${PAYLOADS_DIR}"/*.json; do
    [[ -f "${payload}" ]] || continue
    echo "$(basename "${payload}"): "
    curl -sS -X POST 'https://api.thousandeyes.com/v7/dashboards' \\
        -K "${TE_CURL_CONFIG}" \\
        -H "Content-Type: application/json" \\
        --data-binary @"${payload}" \\
        -o "/tmp/te-te-dashboard-$(basename "${payload}")" -w '%{http_code}\\n'
done
"""

APPLY_TEMPLATE_BODY = """\
# Apply: POST /v7/templates and (optionally) /v7/templates/{id}/deploy.
PAYLOADS_DIR="$(dirname "${BASH_SOURCE[0]}")/../te-payloads/templates"
[[ -d "${PAYLOADS_DIR}" ]] || { echo "No templates/ payloads; nothing to apply."; exit 0; }
for payload in "${PAYLOADS_DIR}"/*.json; do
    [[ -f "${payload}" ]] || continue
    echo "create $(basename "${payload}"): "
    RESPONSE="$(curl -sS -X POST 'https://api.thousandeyes.com/v7/templates' \\
        -K "${TE_CURL_CONFIG}" \\
        -H "Content-Type: application/json" \\
        --data-binary @"${payload}")"
    TEMPLATE_ID="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('id',''))" "${RESPONSE}")"
    if [[ -n "${TEMPLATE_ID:-}" && "${DEPLOY_TEMPLATES:-false}" == "true" ]]; then
        echo "  deploy ${TEMPLATE_ID}: "
        curl -sS -X POST "https://api.thousandeyes.com/v7/templates/${TEMPLATE_ID}/deploy" \\
            -K "${TE_CURL_CONFIG}" \\
            -H "Content-Type: application/json" \\
            -d '{}' \\
            -o "/tmp/te-template-deploy-${TEMPLATE_ID}.json" -w '%{http_code}\\n'
    fi
done
"""


def list_helper(name: str, description: str, url_path: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        f"# {description}\n"
        'if [[ -z "${TE_TOKEN_FILE:-}" || ! -r "${TE_TOKEN_FILE}" ]]; then\n'
        '    echo "ERROR: TE_TOKEN_FILE must point at a readable token file." >&2\n'
        "    exit 1\n"
        "fi\n"
        'TE_CURL_CONFIG="$(mktemp)"\n'
        'chmod 600 "${TE_CURL_CONFIG}"\n'
        '{ printf \'header = "Authorization: Bearer \'; tr -d \'\\r\\n\' < "${TE_TOKEN_FILE}"; printf \'"\\n\'; } > "${TE_CURL_CONFIG}"\n'
        'trap \'rm -f "${TE_CURL_CONFIG}"\' EXIT\n\n'
        f'curl -sS -K "${{TE_CURL_CONFIG}}" "https://api.thousandeyes.com/v7/{url_path}" \\\n'
        '    -H "Accept: application/json"\n'
    )


VALIDATE_SIGNALFLOW_BODY = """\
#!/usr/bin/env bash
set -euo pipefail

# Probe Splunk Observability Cloud for the per-test-type metrics we ship.
# Uses a SignalFlow WebSocket-style query via curl + the v2/signalflow
# endpoint (REST surface). For deeper validation, switch to a Node.js
# WebSocket client (the network-streaming-app reference uses
# wss://stream.<realm>.signalfx.com/v2/signalflow/connect; that pattern is
# documented in references/signalflow-validation.md).
REALM="${REALM:?REALM env var required}"
if [[ -z "${O11Y_API_TOKEN_FILE:-}" || ! -r "${O11Y_API_TOKEN_FILE}" ]]; then
    echo "ERROR: O11Y_API_TOKEN_FILE must point at a readable token file." >&2
    exit 1
fi
O11Y_CURL_CONFIG="$(mktemp)"
chmod 600 "${O11Y_CURL_CONFIG}"
{ printf 'header = "X-SF-Token: '; tr -d '\\r\\n' < "${O11Y_API_TOKEN_FILE}"; printf '"\\n'; } > "${O11Y_CURL_CONFIG}"
trap 'rm -f "${O11Y_CURL_CONFIG}"' EXIT
SPECS_DIR="$(dirname "${BASH_SOURCE[0]}")/../dashboards"
for spec in "${SPECS_DIR}"/*.signalflow.yaml; do
    [[ -f "${spec}" ]] || continue
    echo "Probing $(basename "${spec}") via api.${REALM}.signalfx.com ..."
    curl -sS -K "${O11Y_CURL_CONFIG}" "https://api.${REALM}.signalfx.com/v2/metric?query=thousandeyes&limit=1" \\
        -o /tmp/sfx-probe.json -w 'http=%{http_code}\\n' || true
done
"""


def render_metadata(args: argparse.Namespace, spec: dict[str, Any], realm: str, account_group_id: str) -> dict[str, Any]:
    return {
        "skill": SKILL_NAME,
        "realm": realm,
        "account_group_id": account_group_id,
        "stream_enabled": (spec.get("stream") or {}).get("enabled", False),
        "apm_connector_enabled": (spec.get("apm_connector") or {}).get("enabled", False),
        "tests_count": len(spec.get("tests") or []),
        "alert_rules_count": len(spec.get("alert_rules") or []),
        "labels_count": len(spec.get("labels") or []),
        "tags_count": len(spec.get("tags") or []),
        "te_dashboards_count": len(spec.get("te_dashboards") or []),
        "templates_count": len(spec.get("templates") or []),
        "test_types_for_handoff": collect_test_types_for_handoff(spec),
    }


def warnings(args: argparse.Namespace, spec: dict[str, Any]) -> list[str]:
    items: list[str] = []
    stream = spec.get("stream") or {}
    if stream.get("enabled") and stream.get("signal") in {"trace", "log"}:
        items.append(
            "Splunk Observability Cloud's /v2/datapoint/otlp endpoint is metrics-only; "
            f"signal={stream['signal']!r} renders the payload but no O11y target accepts it. "
            "For logs use Splunk Platform HEC; for traces use Splunk APM (separate endpoint)."
        )
    if (spec.get("apm_connector") or {}).get("enabled") and not (spec.get("dashboards") or {}).get("enabled", True):
        items.append("APM connector enabled but dashboards disabled; trace-link UX requires the matching SignalFlow dashboards.")
    if spec.get("templates") and not bool_flag(args.accept_te_mutations):
        items.append(
            "templates[] are present but --i-accept-te-mutations was not set; templates render only and apply will refuse."
        )
    return items


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"ERROR: spec not found: {spec_path}", file=__import__("sys").stderr)
        return 1
    try:
        spec = load_spec(spec_path)
    except SpecError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    try:
        reject_inline_secrets(spec)
        realm = resolve_realm(args, spec)
        stream = stream_payload(spec, realm)
        apm = apm_connector_payload(spec, realm)
        tests = test_payloads(spec)
        alerts = alert_rule_payloads(spec)
        labels = label_payloads(spec)
        tags = tag_payloads(spec)
        te_dashboards = te_dashboard_payloads(spec)
        templates = template_payloads(spec)
    except SpecError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1

    account_group_id = str(spec.get("account_group_id", "")).strip()
    test_types_for_handoff = collect_test_types_for_handoff(spec)
    detector_thresholds = (spec.get("detectors") or {}).get("thresholds") or {}

    plan = {
        "skill": SKILL_NAME,
        "output_dir": str(Path(args.output_dir).resolve()),
        "realm": realm,
        "stream": stream is not None,
        "apm_connector": apm is not None,
        "tests": [t["slug"] for t in tests],
        "alert_rules": [r["slug"] for r in alerts],
        "labels": [label["slug"] for label in labels],
        "tags": [t["slug"] for t in tags],
        "te_dashboards": [d["slug"] for d in te_dashboards],
        "templates": [t["slug"] for t in templates],
        "test_types_for_handoff": test_types_for_handoff,
        "warnings": warnings(args, spec),
    }

    if args.dry_run:
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("ThousandEyes Integration render plan")
            for key, value in plan.items():
                print(f"  {key}: {value}")
        return 0

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if stream is not None:
        write_json(out / "te-payloads/stream.json", stream)
    if apm is not None:
        connector, operation = apm
        write_json(out / "te-payloads/connector.json", connector)
        write_json(out / "te-payloads/apm-operation.json", operation)

    if tests:
        index = []
        for entry in tests:
            file_name = f"{entry['slug']}.json"
            write_json(out / "te-payloads/tests" / file_name, entry["body"])
            index.append({"slug": entry["slug"], "type": entry["type"], "file": file_name})
        write_json(out / "te-payloads/tests/_index.json", index)
    for entry in alerts:
        write_json(out / f"te-payloads/alert-rules/{entry['slug']}.json", entry["body"])
    for entry in labels:
        write_json(out / f"te-payloads/labels/{entry['slug']}.json", entry["body"])
    for entry in tags:
        write_json(out / f"te-payloads/tags/{entry['slug']}.json", entry["body"])
    for entry in te_dashboards:
        write_json(out / f"te-payloads/te-dashboards/{entry['slug']}.json", entry["body"])
    for entry in templates:
        write_json(out / f"te-payloads/templates/{entry['slug']}.json", entry["body"])

    dashboards_block = spec.get("dashboards") or {}
    if dashboards_block.get("enabled", True) and test_types_for_handoff:
        for test_type in test_types_for_handoff:
            spec_yaml = signalflow_dashboard_spec(test_type)
            write_yaml(out / f"dashboards/{test_type}.signalflow.yaml", spec_yaml)

    detectors_block = spec.get("detectors") or {}
    if detectors_block.get("enabled", True) and test_types_for_handoff:
        for test_type in test_types_for_handoff:
            thresholds = detector_thresholds.get(test_type) or {}
            spec_yaml = detector_spec(test_type, thresholds)
            if spec_yaml["detectors"]:
                write_yaml(out / f"detectors/{test_type}.yaml", spec_yaml)

    write_text(
        out / "scripts/apply-stream.sh",
        render_apply_script("apply-stream.sh", body=APPLY_STREAM_BODY, requires_te_token=True, requires_o11y_ingest=True),
        executable=True,
    )
    write_text(
        out / "scripts/apply-apm-connector.sh",
        render_apply_script("apply-apm-connector.sh", body=APPLY_APM_CONNECTOR_BODY, requires_te_token=True, requires_o11y_api=True),
        executable=True,
    )
    write_text(
        out / "scripts/apply-tests.sh",
        render_apply_script("apply-tests.sh", body=APPLY_TESTS_BODY, requires_te_token=True, requires_mutation_gate=True),
        executable=True,
    )
    write_text(
        out / "scripts/apply-alert-rules.sh",
        render_apply_script("apply-alert-rules.sh", body=APPLY_ALERT_RULES_BODY, requires_te_token=True, requires_mutation_gate=True),
        executable=True,
    )
    write_text(
        out / "scripts/apply-labels-tags.sh",
        render_apply_script("apply-labels-tags.sh", body=APPLY_LABELS_TAGS_BODY, requires_te_token=True, requires_mutation_gate=True),
        executable=True,
    )
    write_text(
        out / "scripts/apply-te-dashboards.sh",
        render_apply_script("apply-te-dashboards.sh", body=APPLY_TE_DASHBOARDS_BODY, requires_te_token=True, requires_mutation_gate=True),
        executable=True,
    )
    write_text(
        out / "scripts/apply-template.sh",
        render_apply_script("apply-template.sh", body=APPLY_TEMPLATE_BODY, requires_te_token=True, requires_mutation_gate=True),
        executable=True,
    )

    write_text(out / "scripts/list-account-groups.sh", list_helper("list-account-groups.sh", "List TE account groups.", "account-groups"), executable=True)
    write_text(out / "scripts/list-agents.sh", list_helper("list-agents.sh", "List TE Cloud + Enterprise agents.", "agents"), executable=True)
    write_text(out / "scripts/list-tests.sh", list_helper("list-tests.sh", "List TE tests.", "tests"), executable=True)
    write_text(out / "scripts/list-templates.sh", list_helper("list-templates.sh", "List TE templates.", "templates"), executable=True)
    write_text(out / "scripts/validate-signalflow.sh", VALIDATE_SIGNALFLOW_BODY, executable=True)

    handoffs = spec.get("handoffs") or {}
    if handoffs.get("dashboard_builder", True):
        write_text(
            out / "scripts/handoff-dashboards.sh",
            handoff_dashboards_body(out),
            executable=True,
        )
    if handoffs.get("native_ops", True):
        write_text(
            out / "scripts/handoff-detectors.sh",
            handoff_detectors_body(out),
            executable=True,
        )
    if handoffs.get("mcp_setup", True):
        write_text(
            out / "scripts/handoff-mcp.sh",
            handoff_mcp_body(),
            executable=True,
        )
    if handoffs.get("splunk_platform_ta", True):
        write_text(
            out / "scripts/handoff-ta.sh",
            handoff_ta_body(),
            executable=True,
        )

    write_json(out / "metadata.json", render_metadata(args, spec, realm, account_group_id))
    return 0


def handoff_dashboards_body(out: Path) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        "# Hand off the rendered SignalFlow specs to splunk-observability-dashboard-builder.\n"
        "SPECS_DIR=\"$(dirname \"${BASH_SOURCE[0]}\")/../dashboards\"\n"
        'echo "Run the following to import the rendered dashboards into Splunk Observability Cloud:"\n'
        "echo\n"
        'echo "  bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \\\\"\n'
        'echo "    --render --apply --realm \\$REALM \\\\"\n'
        'echo "    --spec \\${SPECS_DIR}/<test-type>.signalflow.yaml \\\\"\n'
        'echo "    --token-file \\$O11Y_API_TOKEN_FILE"\n'
    )


def handoff_detectors_body(out: Path) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        "# Hand off the rendered detector specs to splunk-observability-native-ops.\n"
        "SPECS_DIR=\"$(dirname \"${BASH_SOURCE[0]}\")/../detectors\"\n"
        'echo "Run the following to apply the rendered detectors into Splunk Observability Cloud:"\n'
        "echo\n"
        'echo "  bash skills/splunk-observability-native-ops/scripts/setup.sh \\\\"\n'
        'echo "    --render --apply --realm \\$REALM \\\\"\n'
        'echo "    --spec \\${SPECS_DIR}/<test-type>.yaml \\\\"\n'
        'echo "    --token-file \\$O11Y_API_TOKEN_FILE"\n'
    )


def handoff_mcp_body() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        "# Register the TE MCP Server with Cursor / Claude / Codex / VS Code / Kiro.\n"
        'echo "Run the following to register the TE MCP server with one or more clients:"\n'
        "echo\n"
        'echo "  bash skills/cisco-thousandeyes-mcp-setup/scripts/setup.sh \\\\"\n'
        'echo "    --render --client cursor,claude,codex,vscode,kiro \\\\"\n'
        'echo "    --auth bearer --te-token-file \\$TE_TOKEN_FILE"\n'
    )


def handoff_ta_body() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        "# Install the Splunk Platform TA for ThousandEyes (cisco-thousandeyes-setup).\n"
        'echo "If you also need the ThousandEyes Splunk Platform add-on (HEC streaming):"\n'
        "echo\n"
        'echo "  bash skills/cisco-thousandeyes-setup/scripts/setup.sh"\n'
    )


if __name__ == "__main__":
    raise SystemExit(main())
