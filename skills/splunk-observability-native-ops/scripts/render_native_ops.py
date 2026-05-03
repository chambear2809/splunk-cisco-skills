#!/usr/bin/env python3
"""Render native Splunk Observability Cloud operations plans from YAML or JSON specs."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode


API_VERSION = "splunk-observability-native-ops/v1"
ALLOWED_COVERAGE = {"api_apply", "api_validate", "deeplink", "handoff"}
SECTIONS = (
    "teams",
    "detectors",
    "alert_routing",
    "muting_rules",
    "slo_links",
    "synthetics",
    "apm",
    "rum",
    "logs",
    "on_call",
)
DETECTOR_SEVERITIES = {"Critical", "Major", "Minor", "Warning", "Info"}
DIRECT_SECRET_KEYS = {
    "token",
    "access_token",
    "api_token",
    "sf_token",
    "x_sf_token",
    "o11y_token",
    "oncall_api_key",
    "on_call_api_key",
    "x_vo_api_key",
    "service_api_key",
    "client_secret",
    "password",
    "secret",
}
DOC_SOURCES = {
    "detectors": "https://dev.splunk.com/observability/reference/api/detectors/latest",
    "teams": "https://dev.splunk.com/observability/reference/api/teams/latest",
    "incidents": "https://dev.splunk.com/observability/reference/api/incidents/latest",
    "integrations": "https://dev.splunk.com/observability/reference/api/integrations/latest",
    "metrics_metadata": "https://dev.splunk.com/observability/docs/datamodel/metrics_metadata",
    "apm_topology": "https://dev.splunk.com/observability/reference/api/apm_service_topology/latest",
    "trace": "https://dev.splunk.com/observability/reference/api/trace_id/latest",
    "synthetics_tests": "https://dev.splunk.com/observability/reference/api/synthetics_tests/latest",
    "synthetics_artifacts": "https://dev.splunk.com/observability/reference/api/synthetics_artifacts/latest",
    "rum_sessions": "https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/search-for-user-sessions",
    "synthetic_waterfall": "https://help.splunk.com/splunk-observability-cloud/monitor-end-user-experience/synthetic-monitoring/browser-tests-for-webpages/interpret-browser-test-results",
    "logs_charts": "https://help.splunk.com/en/splunk-observability-cloud/create-dashboards-and-charts/create-dashboards/use-new-dashboard-experience/add-a-logs-chart",
    "on_call": "https://help.splunk.com/en/splunk-observability-cloud/splunk-on-call/introduction-to-splunk-on-call/splunk-on-call-api",
}


class SpecError(ValueError):
    """Raised for invalid native operations specs."""


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - setup.sh normally preflights this.
            raise SpecError("YAML specs require PyYAML. Use JSON or install repo dependencies.") from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise SpecError("Spec root must be a mapping/object.")
    return data


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-").lower()
    return slug or "item"


def get_any(mapping: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


def as_list(value: Any, label: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SpecError(f"{label} must be a list.")
    return value


def mapping_item(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SpecError(f"{label} must be a mapping/object.")
    return value


def reject_inline_secrets(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            normalized = key_text.lower().replace("-", "_")
            allow_file_reference = normalized.endswith("_file") or normalized.endswith("_path")
            direct_secret = normalized in DIRECT_SECRET_KEYS
            direct_secret = direct_secret or (
                normalized.endswith("_token") and not normalized.endswith("_token_file")
            )
            direct_secret = direct_secret or (
                normalized.endswith("_api_key") and normalized != "routing_key" and not normalized.endswith("_api_key_file")
            )
            if direct_secret and not allow_file_reference:
                dotted = ".".join((*path, key_text))
                raise SpecError(
                    f"Inline secret field {dotted!r} is not allowed. Use a local secret file path instead."
                )
            reject_inline_secrets(child, (*path, key_text))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_inline_secrets(child, (*path, str(index)))


def validate_sections(spec: dict[str, Any]) -> None:
    api_version = str(spec.get("api_version", ""))
    if api_version != API_VERSION:
        raise SpecError(f"api_version must be {API_VERSION!r}.")
    for section in SECTIONS:
        as_list(spec.get(section, []), section)
    for detector in as_list(spec.get("detectors", []), "detectors"):
        validate_detector(mapping_item(detector, "detectors[]"))
    for route in as_list(spec.get("alert_routing", []), "alert_routing"):
        mapping_item(route, "alert_routing[]")
    for test in as_list(spec.get("synthetics", []), "synthetics"):
        validate_synthetic(mapping_item(test, "synthetics[]"))
    for entry in as_list(spec.get("apm", []), "apm"):
        mapping_item(entry, "apm[]")
    for entry in as_list(spec.get("rum", []), "rum"):
        mapping_item(entry, "rum[]")
    for entry in as_list(spec.get("logs", []), "logs"):
        validate_log_chart(mapping_item(entry, "logs[]"))
    for entry in as_list(spec.get("on_call", []), "on_call"):
        mapping_item(entry, "on_call[]")


def validate_spec(spec: dict[str, Any]) -> None:
    reject_inline_secrets(spec)
    validate_sections(spec)


def validate_detector(detector: dict[str, Any]) -> None:
    name = str(detector.get("name", "")).strip()
    program_text = str(get_any(detector, "programText", "program_text", default="")).strip()
    if not name:
        raise SpecError("detectors[] requires name.")
    if not program_text:
        raise SpecError(f"detector {name!r} requires programText or program_text.")
    rules = as_list(detector.get("rules", []), f"detector {name!r} rules")
    if not rules:
        raise SpecError(f"detector {name!r} requires at least one rule.")
    for index, raw_rule in enumerate(rules):
        rule = mapping_item(raw_rule, f"detector {name!r} rules[{index}]")
        validate_detector_rule(rule, f"detector {name!r} rules[{index}]")
    for delay_field in ("minDelay", "maxDelay", "min_delay", "max_delay"):
        if delay_field in detector and not isinstance(detector[delay_field], int):
            raise SpecError(f"detector {name!r} {delay_field} must be an integer number of seconds.")
    detector_teams = get_any(detector, "teamIds", "team_ids", "teams", default=[])
    for team_index, team_id in enumerate(as_list(detector_teams, f"detector {name!r} teams")):
        if not isinstance(team_id, str) or not team_id.strip() or any(char.isspace() for char in team_id):
            raise SpecError(
                f"detector {name!r} teams[{team_index}] must be an Observability team ID, not a display name."
            )


def validate_synthetic(test: dict[str, Any]) -> None:
    name = str(test.get("name", "")).strip()
    kind = str(test.get("kind", "")).strip().lower()
    payload = test.get("payload", test)
    if not isinstance(payload, dict):
        raise SpecError(f"synthetic test {name or '<unnamed>'!r} payload must be an object.")
    if not name and kind not in {"run", "artifact"}:
        raise SpecError("synthetics[] requires name.")
    if kind in {"browser", "api", "http", "ssl", "port"} and not get_any(payload, "url", "endpoint", "host", default=""):
        raise SpecError(f"synthetic test {name!r} requires url, endpoint, or host.")


def validate_log_chart(chart: dict[str, Any]) -> None:
    name = str(chart.get("name", "")).strip()
    query = str(chart.get("query", "")).strip()
    if not name:
        raise SpecError("logs[] requires name.")
    if not query:
        raise SpecError(f"logs chart {name!r} requires query.")


def validate_detector_rule(rule: dict[str, Any], label: str) -> None:
    severity = str(rule.get("severity", "")).strip()
    if severity not in DETECTOR_SEVERITIES:
        raise SpecError(f"{label} severity must be one of {', '.join(sorted(DETECTOR_SEVERITIES))}.")
    detect_label = str(get_any(rule, "detectLabel", "detect_label", default="")).strip()
    if not detect_label:
        raise SpecError(f"{label} requires detectLabel or detect_label.")
    for field in ("notifications", "notifications_when_resolved", "notificationsWhenResolved"):
        if field in rule:
            notifications = as_list(rule[field], f"{label} {field}")
            for notification_index, notification in enumerate(notifications):
                validate_notification(
                    mapping_item(notification, f"{label} {field}[{notification_index}]"),
                    f"{label} {field}[{notification_index}]",
                )


def validate_notification(notification: dict[str, Any], label: str) -> None:
    notification_type = str(notification.get("type", "")).strip()
    if notification_type in {"Team", "TeamEmail"}:
        team_id = get_any(notification, "team_id", "teamId", "team")
        if not isinstance(team_id, str) or not team_id.strip() or any(char.isspace() for char in team_id):
            raise SpecError(
                f"{label} uses type {notification_type!r}; specify team_id with the Observability team ID."
            )


def normalize_detector(detector: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "name": detector["name"],
        "programText": get_any(detector, "programText", "program_text"),
        "rules": [normalize_detector_rule(rule) for rule in detector.get("rules", [])],
    }
    optional_map = {
        "description": ("description",),
        "teams": ("teamIds", "team_ids", "teams"),
        "tags": ("tags",),
        "minDelay": ("minDelay", "min_delay"),
        "maxDelay": ("maxDelay", "max_delay"),
        "timezone": ("timezone",),
        "runbookUrl": ("runbookUrl", "runbook_url"),
        "customProperties": ("customProperties", "custom_properties"),
        "visualizationOptions": ("visualizationOptions", "visualization_options"),
    }
    for output_key, names in optional_map.items():
        value = get_any(detector, *names)
        if value is not None:
            payload[output_key] = value
    return payload


def normalize_detector_rule(rule: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "detectLabel": get_any(rule, "detectLabel", "detect_label"),
        "severity": rule["severity"],
        "notifications": [normalize_notification(notification) for notification in rule.get("notifications", [])],
    }
    optional_map = {
        "description": ("description",),
        "disabled": ("disabled",),
        "notificationsWhenResolved": ("notificationsWhenResolved", "notifications_when_resolved"),
        "parameterizedBody": ("parameterizedBody", "parameterized_body"),
        "parameterizedSubject": ("parameterizedSubject", "parameterized_subject"),
        "runbookUrl": ("runbookUrl", "runbook_url"),
        "tip": ("tip",),
    }
    for output_key, names in optional_map.items():
        value = get_any(rule, *names)
        if value is not None:
            if output_key == "notificationsWhenResolved":
                payload[output_key] = [normalize_notification(notification) for notification in value]
            else:
                payload[output_key] = value
    return payload


def normalize_notification(notification: dict[str, Any]) -> dict[str, Any]:
    payload = dict(notification)
    team_id = get_any(payload, "team_id", "teamId")
    if team_id is not None:
        payload["team"] = team_id
        payload.pop("team_id", None)
        payload.pop("teamId", None)
    return payload


def is_concrete_id(value: str) -> bool:
    return bool(value.strip()) and "{" not in value and "}" not in value


def o11y_app_base(realm: str) -> str:
    return f"https://app.{realm}.observability.splunkcloud.com"


def o11y_api_base(realm: str) -> str:
    return f"https://api.{realm}.observability.splunkcloud.com/v2"


def synthetics_api_base(realm: str) -> str:
    return f"{o11y_api_base(realm)}/synthetics"


def deeplink(base: str, path: str, params: dict[str, Any] | None = None) -> str:
    cleaned = path if path.startswith("/") else f"/{path}"
    if not params:
        return f"{base}{cleaned}"
    flat_params = {key: value for key, value in params.items() if value not in (None, "", [])}
    return f"{base}{cleaned}?{urlencode(flat_params, doseq=True)}"


class RenderContext:
    def __init__(self, output_dir: Path, realm: str) -> None:
        self.output_dir = output_dir
        self.realm = realm
        self.api_base = o11y_api_base(realm)
        self.synthetics_api_base = synthetics_api_base(realm)
        self.app_base = o11y_app_base(realm)
        self.actions: list[dict[str, Any]] = []
        self.coverage: list[dict[str, Any]] = []
        self.links: list[dict[str, Any]] = []
        self.handoffs: list[dict[str, Any]] = []
        self.rendered_files: set[str] = set()

    def rel(self, *parts: str) -> Path:
        return Path(*parts)

    def write_payload(self, rel_path: Path, payload: Any) -> str:
        write_json(self.output_dir / rel_path, payload)
        rel_text = rel_path.as_posix()
        self.rendered_files.add(rel_text)
        return rel_text

    def add_coverage(
        self,
        object_type: str,
        name: str,
        coverage: str,
        reason: str,
        outputs: list[str] | None = None,
        source: str | None = None,
    ) -> None:
        if coverage not in ALLOWED_COVERAGE:
            raise SpecError(f"Invalid coverage status {coverage!r}.")
        self.coverage.append(
            {
                "coverage": coverage,
                "name": name,
                "object_type": object_type,
                "outputs": sorted(outputs or []),
                "reason": reason,
                "source": source,
            }
        )

    def add_action(
        self,
        action: str,
        object_type: str,
        name: str,
        coverage: str,
        method: str,
        path: str,
        payload_file: str | None = None,
        writes: bool = False,
        service: str = "o11y",
    ) -> None:
        if service == "o11y":
            url = f"{self.api_base}{path}"
        elif service == "synthetics":
            url = f"{self.synthetics_api_base}{path}"
        else:
            url = f"https://api.victorops.com/api-public/v1{path}"
        item = {
            "action": action,
            "coverage": coverage,
            "method": method,
            "name": name,
            "object_type": object_type,
            "path": path,
            "service": service,
            "url": url,
            "writes": writes,
        }
        if payload_file:
            item["payload_file"] = payload_file
        self.actions.append(item)

    def add_link(
        self,
        object_type: str,
        name: str,
        coverage: str,
        url: str,
        description: str,
    ) -> None:
        item = {
            "coverage": coverage,
            "description": description,
            "name": name,
            "object_type": object_type,
            "url": url,
        }
        self.links.append(item)
        self.add_coverage(object_type, name, coverage, description, ["deeplinks.json"], None)

    def add_handoff(self, object_type: str, name: str, title: str, steps: list[str], source: str | None = None) -> None:
        self.handoffs.append(
            {
                "coverage": "handoff",
                "name": name,
                "object_type": object_type,
                "source": source,
                "steps": steps,
                "title": title,
            }
        )
        self.add_coverage(object_type, name, "handoff", title, ["handoff.md"], source)


def prepare_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        marker = output_dir / "metadata.json"
        if not marker.exists():
            raise SpecError(f"Refusing to overwrite non-rendered directory: {output_dir}")
        try:
            metadata = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SpecError(f"Refusing to overwrite directory with invalid metadata.json: {output_dir}") from exc
        if metadata.get("mode") != "native-ops":
            raise SpecError(f"Refusing to overwrite directory not marked as native-ops: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def render_teams(ctx: RenderContext, teams: list[Any]) -> None:
    for raw_team in teams:
        team = mapping_item(raw_team, "teams[]")
        name = str(team.get("name", "")).strip()
        if not name:
            raise SpecError("teams[] requires name.")
        payload = {
            "name": name,
            "description": team.get("description", ""),
        }
        for key in ("members", "notificationLists", "notification_policy", "properties"):
            if key in team:
                output_key = "notificationLists" if key == "notification_policy" else key
                payload[output_key] = team[key]
        rel = ctx.write_payload(Path("payloads") / "teams" / f"{slugify(name)}.json", payload)
        team_id = str(team.get("id", "")).strip()
        method = "PUT" if team_id else "POST"
        path = f"/team/{team_id}" if team_id else "/team"
        ctx.add_action("upsert-team", "team", name, "api_apply", method, path, rel, writes=True)
        ctx.add_coverage("team", name, "api_apply", "Teams API supports create and update.", [rel], DOC_SOURCES["teams"])


def render_detectors(ctx: RenderContext, detectors: list[Any]) -> None:
    for raw_detector in detectors:
        detector = mapping_item(raw_detector, "detectors[]")
        name = str(detector["name"])
        payload = normalize_detector(detector)
        payload_path = Path("payloads") / "detectors" / f"{slugify(name)}.json"
        validate_path = Path("payloads") / "detectors" / f"{slugify(name)}.validate.json"
        rel_payload = ctx.write_payload(payload_path, payload)
        rel_validate = ctx.write_payload(validate_path, payload)
        detector_id = str(detector.get("id", "")).strip()
        method = "PUT" if detector_id else "POST"
        path = f"/detector/{detector_id}" if detector_id else "/detector"
        ctx.add_action("validate-detector", "detector", name, "api_apply", "POST", "/detector/validate", rel_validate)
        ctx.add_action("upsert-detector", "detector", name, "api_apply", method, path, rel_payload, writes=True)
        if detector.get("enabled") is not None and detector_id:
            enable_path = f"/detector/{detector_id}/{'enable' if detector.get('enabled') else 'disable'}"
            ctx.add_action("set-detector-enabled", "detector", name, "api_apply", "PUT", enable_path, writes=True)
        if detector_id:
            ctx.add_action("list-detector-events", "detector", name, "api_validate", "GET", f"/detector/{detector_id}/events")
            ctx.add_action("list-detector-incidents", "detector", name, "api_validate", "GET", f"/detector/{detector_id}/incidents")
        ctx.add_coverage(
            "detector",
            name,
            "api_apply",
            "Detector API supports validation, create/update, enable/disable, events, incidents, teams, rules, notifications, runbooks, tags, and delay fields.",
            [rel_payload, rel_validate],
            DOC_SOURCES["detectors"],
        )


def render_alert_routing(ctx: RenderContext, routes: list[Any]) -> None:
    for raw_route in routes:
        route = mapping_item(raw_route, "alert_routing[]")
        name = str(route.get("name", route.get("kind", "alert-routing"))).strip() or "alert-routing"
        kind = str(route.get("kind", "handoff")).strip().lower()
        payload = route.get("payload", {})
        if kind == "team_notification_policy":
            team_id = str(route.get("team_id", "")).strip()
            if team_id:
                body = {
                    "notificationLists": get_any(route, "notificationLists", "notification_policy", default=payload),
                }
                rel = ctx.write_payload(Path("payloads") / "alert-routing" / f"{slugify(name)}.json", body)
                ctx.add_action("update-team-notification-policy", "alert_routing", name, "api_apply", "PUT", f"/team/{team_id}", rel, writes=True)
                ctx.add_coverage("alert_routing", name, "api_apply", "Team notification policy can be applied through the Teams API.", [rel], DOC_SOURCES["teams"])
                continue
        if kind == "detector_recipients":
            detector_id = str(route.get("detector_id", "")).strip()
            if detector_id:
                raw_rules = as_list(route.get("rules", []), f"alert_routing {name!r} rules")
                if not raw_rules:
                    raise SpecError(f"alert_routing {name!r} detector_recipients requires rules.")
                rules = []
                for index, raw_rule in enumerate(raw_rules):
                    rule = mapping_item(raw_rule, f"alert_routing {name!r} rules[{index}]")
                    validate_detector_rule(rule, f"alert_routing {name!r} rules[{index}]")
                    rules.append(normalize_detector_rule(rule))
                body = {"rules": rules}
                rel = ctx.write_payload(Path("payloads") / "alert-routing" / f"{slugify(name)}.json", body)
                ctx.add_action("update-detector-recipients", "alert_routing", name, "api_apply", "PUT", f"/detector/{detector_id}", rel, writes=True)
                ctx.add_coverage("alert_routing", name, "api_apply", "Detector recipients can be applied as detector rule updates.", [rel], DOC_SOURCES["detectors"])
                continue
        if kind == "integration":
            integration_id = str(route.get("id", "")).strip()
            rel = ctx.write_payload(Path("payloads") / "alert-routing" / f"{slugify(name)}.json", payload or route)
            method = "PUT" if integration_id else "POST"
            path = f"/integration/{integration_id}" if integration_id else "/integration"
            ctx.add_action("upsert-alert-integration", "alert_routing", name, "api_apply", method, path, rel, writes=True)
            ctx.add_coverage("alert_routing", name, "api_apply", "Observability integrations are represented as API payloads when configured in Observability.", [rel], DOC_SOURCES["integrations"])
            continue
        ctx.add_handoff(
            "alert_routing",
            name,
            "External alert routing requires operator confirmation outside Observability.",
            [
                f"Open {deeplink(ctx.app_base, '/alerts')}.",
                "Confirm the detector rule recipients and any external destination ownership.",
                "Configure external system secrets and endpoints in that system, not in this spec.",
            ],
            DOC_SOURCES["incidents"],
        )


def render_muting_rules(ctx: RenderContext, rules: list[Any]) -> None:
    for raw_rule in rules:
        rule = mapping_item(raw_rule, "muting_rules[]")
        name = str(rule.get("name", "muting-rule")).strip() or "muting-rule"
        rel = ctx.write_payload(Path("payloads") / "muting-rules" / f"{slugify(name)}.json", rule.get("payload", rule))
        rule_id = str(rule.get("id", "")).strip()
        method = "PUT" if rule_id else "POST"
        path = f"/alertmuting/{rule_id}" if rule_id else "/alertmuting"
        ctx.add_action("upsert-muting-rule", "muting_rule", name, "api_apply", method, path, rel, writes=True)
        ctx.add_coverage("muting_rule", name, "api_apply", "Alert muting rules are handled by the alert muting API.", [rel], DOC_SOURCES["incidents"])


def render_slo_links(ctx: RenderContext, slo_links: list[Any]) -> None:
    for raw_slo in slo_links:
        slo = mapping_item(raw_slo, "slo_links[]")
        name = str(slo.get("name", "slo")).strip() or "slo"
        rel = None
        if "payload" in slo:
            rel = ctx.write_payload(Path("payloads") / "slo" / f"{slugify(name)}.intent.json", slo["payload"])
        url = deeplink(ctx.app_base, "/slo", {"query": slo.get("query", name)})
        ctx.add_link("slo", name, "deeplink", url, "Open the referenced SLO in Observability Cloud.")
        if rel:
            ctx.add_handoff(
                "slo",
                name,
                "SLO links are UI-guided unless a documented public SLO API is added.",
                [
                    f"Use rendered SLO intent: {rel}",
                    f"Open SLO management: {url}",
                    "Create or update the SLO in Observability Cloud, then link detectors or dashboards to the resulting SLO.",
                ],
                "https://help.splunk.com/en/splunk-observability-cloud/create-alerts-detectors-and-service-level-objectives/create-service-level-objectives-slos",
            )


def render_synthetics(ctx: RenderContext, tests: list[Any]) -> None:
    for raw_test in tests:
        test = mapping_item(raw_test, "synthetics[]")
        name = str(test.get("name", "synthetic")).strip() or "synthetic"
        kind = str(test.get("kind", "browser")).strip().lower()
        slug = slugify(name)
        if kind in {"browser", "api", "http", "ssl", "port"}:
            if isinstance(test.get("payload"), dict):
                payload = dict(test["payload"])
            else:
                payload = {key: value for key, value in test.items() if key not in {"id", "run_now", "artifact", "artifacts"}}
            rel = ctx.write_payload(Path("payloads") / "synthetics" / f"{slug}.{kind}.json", payload)
            test_id = str(test.get("id", "")).strip()
            method = "PUT" if test_id else "POST"
            path = f"/tests/{kind}/{test_id}" if test_id else f"/tests/{kind}"
            if kind != "ssl":
                validate_path = f"/tests/{kind}/{test_id}/validate" if test_id else f"/tests/{kind}/validate"
                ctx.add_action("validate-synthetic-test", "synthetic_test", name, "api_apply", "POST", validate_path, rel, service="synthetics")
            ctx.add_action("upsert-synthetic-test", "synthetic_test", name, "api_apply", method, path, rel, writes=True, service="synthetics")
            if test.get("run_now") and test_id:
                ctx.add_action("run-synthetic-test", "synthetic_test", name, "api_apply", "POST", f"/tests/{test_id}/run_now", writes=True, service="synthetics")
            elif test.get("run_now"):
                ctx.add_handoff(
                    "synthetic_test",
                    name,
                    "Run-now requires an existing Synthetics test ID.",
                    [
                        "Create the test first, capture its ID, then rerun with id and run_now: true.",
                        f"Rendered create payload: {rel}",
                    ],
                    DOC_SOURCES["synthetics_tests"],
                )
            if test_id:
                ctx.add_action("list-synthetic-runs", "synthetic_test", name, "api_validate", "GET", f"/tests/{test_id}/runs", service="synthetics")
            ctx.add_coverage(
                "synthetic_test",
                name,
                "api_apply",
                "Synthetics API supports test rendering, validation, create/update, run-now, and run lookup plans.",
                [rel],
                DOC_SOURCES["synthetics_tests"],
            )
            artifacts = as_list(test.get("artifacts", []), f"synthetic {name!r} artifacts")
            if test.get("artifact"):
                artifacts.append(test["artifact"])
            for artifact in artifacts:
                render_synthetic_artifact(ctx, name, test_id, artifact)
            continue
        if kind == "run":
            test_id = str(get_any(test, "test_id", "id", default="")).strip()
            run_id = str(test.get("run_id", "")).strip()
            if is_concrete_id(run_id):
                path = f"/runs/{quote(run_id, safe='')}"
                ctx.add_action("lookup-synthetic-run", "synthetic_run", name, "api_validate", "GET", path, service="synthetics")
                ctx.add_coverage("synthetic_run", name, "api_validate", "Synthetics run detail is read through the Synthetics API.", [], DOC_SOURCES["synthetics_tests"])
            elif is_concrete_id(test_id):
                path = f"/tests/{test_id}/runs"
                ctx.add_action("lookup-synthetic-run", "synthetic_run", name, "api_validate", "GET", path, service="synthetics")
                ctx.add_coverage("synthetic_run", name, "api_validate", "Synthetics run detail is read through the Synthetics API.", [], DOC_SOURCES["synthetics_tests"])
            else:
                ctx.add_handoff(
                    "synthetic_run",
                    name,
                    "Synthetic run lookup requires a concrete test ID or run ID.",
                    [
                        "Provide test_id to render /tests/{id}/runs, or provide run_id to render /runs/{id}.",
                        "Use the Synthetics UI deeplinks from related tests to find the run identifier.",
                    ],
                    DOC_SOURCES["synthetics_tests"],
                )
            continue
        if kind == "artifact":
            render_synthetic_artifact(ctx, name, str(test.get("test_id", "{test_id}")), test)
            continue
        raise SpecError(f"synthetics[] kind {kind!r} is not supported.")


def render_synthetic_artifact(ctx: RenderContext, name: str, test_id: str, artifact: Any) -> None:
    artifact_map = mapping_item(artifact, f"synthetic artifact for {name!r}")
    run_id = str(artifact_map.get("run_id", "{run_id}"))
    filename = str(artifact_map.get("filename", artifact_map.get("type", artifact_map.get("artifact_type", "network.har"))))
    location_id = str(get_any(artifact_map, "location_id", "locationId", default=""))
    timestamp = str(artifact_map.get("timestamp", ""))
    concrete_test_id = is_concrete_id(test_id)
    if concrete_test_id:
        if location_id and timestamp and is_concrete_id(run_id):
            path = f"/tests/{test_id}/artifacts/{location_id}/{timestamp}/{run_id}/{quote(filename, safe='')}"
        else:
            path = f"/tests/{test_id}/artifacts"
        ctx.add_action("download-synthetic-artifact", "synthetic_artifact", name, "api_validate", "GET", path, service="synthetics")
        if artifact_map.get("download") and location_id and timestamp and is_concrete_id(run_id):
            ctx.add_action("download-synthetic-artifact-file", "synthetic_artifact", name, "api_validate", "GET", f"{path}/download", service="synthetics")
        ctx.add_coverage("synthetic_artifact", name, "api_validate", "Synthetics artifacts are retrieved through the Synthetics artifacts API when test and run coordinates are known.", [], DOC_SOURCES["synthetics_artifacts"])
    else:
        path = "/tests/{test_id}/artifacts"
    url = deeplink(
        ctx.app_base,
        "/synthetics/runs",
        {"testId": test_id if concrete_test_id else None, "runId": run_id if is_concrete_id(run_id) else None},
    )
    ctx.add_link("synthetic_artifact", name, "deeplink", url, "Open Synthetics waterfall detail and artifacts in Observability Cloud.")
    artifact_label = filename.rsplit(".", 1)[-1].upper() if "." in filename else filename.upper()
    ctx.add_handoff(
        "synthetic_artifact",
        name,
        f"Retrieve {artifact_label} artifact for Synthetics waterfall review.",
        [
            f"Run dry-run apply to confirm GET {path}.",
            "Provide location_id, timestamp, run_id, and filename to render an exact artifact download URL.",
            "Use a readable Observability token file for live artifact download.",
            f"Open the waterfall detail link: {url}",
        ],
        DOC_SOURCES["synthetic_waterfall"],
    )


def render_apm(ctx: RenderContext, entries: list[Any]) -> None:
    for raw_entry in entries:
        entry = mapping_item(raw_entry, "apm[]")
        name = str(entry.get("name", entry.get("service", "apm-workflow"))).strip() or "apm-workflow"
        kind = str(entry.get("kind", "service_map")).strip().lower()
        if kind in {"service_map", "topology"}:
            service = get_any(entry, "service", "service_name")
            time_range = entry.get("time_range", entry.get("timeRange"))
            if not time_range:
                raise SpecError(f"apm service map {name!r} requires time_range or timeRange.")
            tag_filters = get_any(entry, "tagFilters", "tag_filters", "filters", default=[])
            if entry.get("environment"):
                tag_filters = [
                    *as_list(tag_filters, f"apm service map {name!r} tag filters"),
                    {
                        "name": "sf_environment",
                        "operator": "equals",
                        "scope": "GLOBAL",
                        "value": entry["environment"],
                    },
                ]
            payload = {
                "timeRange": time_range,
            }
            if tag_filters:
                payload["tagFilters"] = tag_filters
            rel = ctx.write_payload(Path("payloads") / "apm" / f"{slugify(name)}.topology.json", payload)
            topology_path = f"/apm/topology/{quote(str(service), safe='')}" if service else "/apm/topology"
            ctx.add_action("validate-apm-topology", "apm_service_map", name, "api_validate", "POST", topology_path, rel)
            url = deeplink(ctx.app_base, "/apm/service-map", {"service": service, "environment": entry.get("environment")})
            ctx.add_link("apm_service_map", name, "deeplink", url, "Open the generated APM service map.")
            ctx.add_coverage("apm_service_map", name, "api_validate", "Service maps are generated from telemetry; validate topology instead of creating maps.", [rel], DOC_SOURCES["apm_topology"])
            continue
        if kind in {"trace", "trace_waterfall"}:
            trace_id = str(entry.get("trace_id", entry.get("traceId", ""))).strip()
            if not is_concrete_id(trace_id):
                ctx.add_handoff(
                    "apm_trace",
                    name,
                    "Trace download requires a concrete trace ID.",
                    [
                        "Provide trace_id to render /apm/trace/{traceId}/latest or a segment timestamp for /apm/trace/{traceId}/{segmentTimestamp}.",
                        "Use Trace Analyzer or the APM UI to identify the trace ID before rendering a live validation plan.",
                    ],
                    DOC_SOURCES["trace"],
                )
                continue
            segment_timestamp = get_any(entry, "segment_timestamp", "segmentTimestamp", "segment")
            trace_path = f"/apm/trace/{trace_id}/{segment_timestamp}" if segment_timestamp else f"/apm/trace/{trace_id}/latest"
            ctx.add_action("download-apm-trace", "apm_trace", name, "api_validate", "GET", trace_path)
            if entry.get("include_segments"):
                ctx.add_action("download-apm-trace-segments", "apm_trace", name, "api_validate", "GET", f"/apm/trace/{trace_id}/segments")
            url = deeplink(ctx.app_base, "/apm/traces", {"traceId": trace_id, "service": get_any(entry, "service", "service_name")})
            ctx.add_link("apm_trace", name, "deeplink", url, "Open Trace Analyzer or trace waterfall for the trace ID.")
            ctx.add_handoff(
                "apm_trace",
                name,
                "Trace workflow review links RUM, span logs, and business workflow context.",
                [
                    f"Open trace waterfall: {url}",
                    "Use the trace download API request in apply-plan.json for offline review.",
                    "Inspect span log links and RUM links in the Observability UI when present.",
                ],
                DOC_SOURCES["trace"],
            )
            ctx.add_coverage("apm_trace", name, "api_validate", "Trace download APIs validate traces without creating workflow objects.", [], DOC_SOURCES["trace"])
            continue
        raise SpecError(f"apm[] kind {kind!r} is not supported.")


def render_rum(ctx: RenderContext, entries: list[Any]) -> None:
    for raw_entry in entries:
        entry = mapping_item(raw_entry, "rum[]")
        name = str(entry.get("name", "rum-session-workflow")).strip() or "rum-session-workflow"
        url = deeplink(
            ctx.app_base,
            "/rum/sessions",
            {
                "query": entry.get("query"),
                "application": entry.get("application"),
                "sessionId": entry.get("session_id", entry.get("sessionId")),
            },
        )
        metric_validation_outputs: list[str] = []
        ctx.add_link("rum_session", name, "deeplink", url, "Open RUM session search or session replay.")
        for metric in as_list(entry.get("metrics", []), f"rum {name!r} metrics"):
            ctx.add_action("validate-rum-metric-metadata", "rum_session", name, "api_validate", "GET", f"/metric/{metric}")
            metric_validation_outputs.append("apply-plan.json")
        if metric_validation_outputs:
            ctx.add_coverage(
                "rum_session",
                name,
                "api_validate",
                "Referenced RUM metrics are validated through the metric metadata API.",
                metric_validation_outputs,
                DOC_SOURCES["metrics_metadata"],
            )
        ctx.add_handoff(
            "rum_session",
            name,
            "RUM session replay and setup remain UI-guided workflows.",
            [
                f"Open session search: {url}",
                "Verify session replay instrumentation, privacy settings, and RUM/APM linking in the UI.",
                "Use metric metadata validation for referenced RUM metrics where configured.",
            ],
            DOC_SOURCES["rum_sessions"],
        )


def render_logs(ctx: RenderContext, entries: list[Any]) -> None:
    for raw_entry in entries:
        entry = mapping_item(raw_entry, "logs[]")
        name = str(entry.get("name", "logs-chart")).strip() or "logs-chart"
        intent = {
            "chart_type": entry.get("chart_type", "logs"),
            "dashboard": entry.get("dashboard"),
            "fields": entry.get("fields", []),
            "index": entry.get("index"),
            "indexes": entry.get("indexes", []),
            "query": entry["query"],
            "query_language": entry.get("query_language", "SPL2"),
            "rollup": entry.get("rollup"),
            "visualization": entry.get("visualization", "table"),
        }
        rel = ctx.write_payload(Path("payloads") / "logs" / f"{slugify(name)}.intent.json", intent)
        url = deeplink(ctx.app_base, "/logs", {"query": entry.get("query"), "index": entry.get("index")})
        ctx.add_link("logs_chart", name, "deeplink", url, "Open Log Observer with the intended chart query.")
        ctx.add_handoff(
            "logs_chart",
            name,
            "Modern logs charts are UI-authored from the new dashboard experience.",
            [
                f"Use rendered chart intent: {rel}",
                "Verify Log Observer Connect prerequisites and index access.",
                f"Open the query in Log Observer: {url}",
                "Add the logs chart in the new dashboard experience using the rendered query, fields, and visualization intent.",
            ],
            DOC_SOURCES["logs_charts"],
        )


def render_on_call(ctx: RenderContext, entries: list[Any]) -> None:
    for raw_entry in entries:
        entry = mapping_item(raw_entry, "on_call[]")
        name = str(entry.get("name", "on-call-workflow")).strip() or "on-call-workflow"
        kind = str(entry.get("kind", "handoff")).strip().lower()
        if kind == "api_request":
            method = str(entry.get("method", "GET")).upper()
            path = str(entry.get("path", "/")).strip()
            if not path.startswith("/"):
                raise SpecError(f"on_call {name!r} api_request path must start with '/'.")
            payload_file = None
            if "payload" in entry:
                payload_file = ctx.write_payload(Path("payloads") / "on-call" / f"{slugify(name)}.json", entry["payload"])
            writes = method not in {"GET", "HEAD", "OPTIONS"}
            coverage = "api_apply" if writes else "api_validate"
            ctx.add_action("on-call-api-request", "on_call", name, coverage, method, path, payload_file, writes=writes, service="on_call")
            ctx.add_coverage(
                "on_call",
                name,
                coverage,
                "Optional Splunk On-Call API request rendered with separate API ID and key file handling.",
                [payload_file] if payload_file else [],
                DOC_SOURCES["on_call"],
            )
            continue
        rendered = {key: value for key, value in entry.items() if key != "api_request"}
        rel = ctx.write_payload(Path("payloads") / "on-call" / f"{slugify(name)}.handoff.json", rendered)
        ctx.add_handoff(
            "on_call",
            name,
            "On-Call schedules, rotations, escalation policies, routing keys, and calendars require operator handoff unless an explicit On-Call API request is supplied.",
            [
                f"Use rendered handoff object: {rel}",
                "Confirm schedule ownership, rotations, shift boundaries, escalation policy targets, and calendar publishing in Splunk On-Call.",
                "Use --oncall-api-id and --oncall-api-key-file only for explicit on_call kind: api_request entries.",
            ],
            DOC_SOURCES["on_call"],
        )


def render_handoff_md(ctx: RenderContext) -> str:
    lines = [
        "# Splunk Observability Native Operations Handoff",
        "",
        f"Realm: `{ctx.realm}`",
        "",
    ]
    if not ctx.handoffs:
        lines.extend(["No UI-only handoffs were rendered.", ""])
    for handoff in ctx.handoffs:
        lines.extend(
            [
                f"## {handoff['title']}",
                "",
                f"- Object: `{handoff['object_type']}` / `{handoff['name']}`",
                "- Coverage: `handoff`",
            ]
        )
        if handoff.get("source"):
            lines.append(f"- Source: {handoff['source']}")
        for step in handoff["steps"]:
            lines.append(f"- {step}")
        lines.append("")
    rel = "handoff.md"
    (ctx.output_dir / rel).write_text("\n".join(lines), encoding="utf-8")
    ctx.rendered_files.add(rel)
    return rel


def render_spec(spec: dict[str, Any], output_dir: Path, realm_override: str | None = None) -> dict[str, Any]:
    validate_spec(spec)
    realm = realm_override or str(spec.get("realm", "us0") or "us0")
    prepare_output_dir(output_dir)
    ctx = RenderContext(output_dir, realm)

    render_teams(ctx, as_list(spec.get("teams", []), "teams"))
    render_detectors(ctx, as_list(spec.get("detectors", []), "detectors"))
    render_alert_routing(ctx, as_list(spec.get("alert_routing", []), "alert_routing"))
    render_muting_rules(ctx, as_list(spec.get("muting_rules", []), "muting_rules"))
    render_slo_links(ctx, as_list(spec.get("slo_links", []), "slo_links"))
    render_synthetics(ctx, as_list(spec.get("synthetics", []), "synthetics"))
    render_apm(ctx, as_list(spec.get("apm", []), "apm"))
    render_rum(ctx, as_list(spec.get("rum", []), "rum"))
    render_logs(ctx, as_list(spec.get("logs", []), "logs"))
    render_on_call(ctx, as_list(spec.get("on_call", []), "on_call"))

    deeplinks_rel = ctx.write_payload(Path("deeplinks.json"), {"realm": realm, "links": ctx.links})
    handoff_rel = render_handoff_md(ctx)
    for item in ctx.coverage:
        if item["coverage"] in {"deeplink", "handoff"}:
            continue
        if item["coverage"] == "api_validate":
            item["outputs"] = sorted(set(item.get("outputs", [])) | {deeplinks_rel})
    summary = Counter(item["coverage"] for item in ctx.coverage)
    coverage_report = {
        "api_version": API_VERSION,
        "objects": ctx.coverage,
        "realm": realm,
        "summary": {coverage: summary.get(coverage, 0) for coverage in sorted(ALLOWED_COVERAGE)},
    }
    coverage_rel = ctx.write_payload(Path("coverage-report.json"), coverage_report)
    apply_plan = {
        "actions": ctx.actions,
        "api_base_url": ctx.api_base,
        "api_version": API_VERSION,
        "coverage_report": coverage_rel,
        "deeplinks": deeplinks_rel,
        "handoff": handoff_rel,
        "mode": "native-ops",
        "realm": realm,
    }
    plan_rel = ctx.write_payload(Path("apply-plan.json"), apply_plan)
    metadata = {
        "api_version": API_VERSION,
        "mode": "native-ops",
        "realm": realm,
        "rendered_files": sorted(ctx.rendered_files | {coverage_rel, plan_rel}),
    }
    metadata_rel = ctx.write_payload(Path("metadata.json"), metadata)
    return {
        "api_version": API_VERSION,
        "coverage_report": coverage_report,
        "files": sorted(ctx.rendered_files | {metadata_rel}),
        "ok": True,
        "output_dir": str(output_dir),
        "realm": realm,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--realm", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        spec = load_structured(args.spec)
        result = render_spec(spec, args.output_dir, args.realm or None)
    except (OSError, SpecError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Rendered native Observability operations to {args.output_dir}")
        print(f"Coverage objects: {len(result['coverage_report']['objects'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
