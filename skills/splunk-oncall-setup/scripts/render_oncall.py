#!/usr/bin/env python3
"""Render Splunk On-Call (formerly VictorOps) plans from YAML or JSON specs.

This module is the canonical home for all Splunk On-Call object rendering.
It produces:

- ``coverage-report.json`` — every spec object with its coverage tag, plus a
  rate-limit / monthly-budget summary.
- ``apply-plan.json`` — ordered API actions for ``api_apply`` and
  ``api_validate`` objects, with secrets stripped.
- ``deeplinks.json`` — UI links for ``deeplink`` and ``handoff`` objects.
- ``handoff.md`` — human-readable operator checklist.
- ``payloads/<section>/<slug>.json`` — request bodies referenced from
  ``apply-plan.json``.
- ``metadata.json`` — top-level mode, api_version, and counts.

The renderer is render-first: it never makes network calls. The companion
``oncall_api.py`` consumes ``apply-plan.json`` for ``--apply`` and
``rest_endpoint.py`` consumes the spec's ``rest_alerts`` for ``--send-alert``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote


API_VERSION = "splunk-oncall-setup/v1"
ALLOWED_COVERAGE = {"api_apply", "api_validate", "deeplink", "handoff", "install_apply"}

SECTIONS = (
    "users",
    "teams",
    "rotations",
    "escalation_policies",
    "routing_keys",
    "paging_policies",
    "scheduled_overrides",
    "alert_rules",
    "maintenance_mode",
    "incidents",
    "notes",
    "chat_messages",
    "stakeholder_messages",
    "webhooks",
    "reporting",
    "schedules",
    "rest_alerts",
    "email_alerts",
    "integrations",
    "sso",
    "reports",
    "calendars",
    "mobile",
    "recovery_polling",
    "splunk_side",
)

# Verified from product docs. Stakeholders are read-only paging-only and
# cannot be placed in on-call schedules.
ALLOWED_ROLES = {
    "global_admin",
    "alert_admin",
    "team_admin",
    "user",
    "stakeholder",
}

# Verified from the Splunk On-Call REST endpoint integration docs.
# RECOVERY/OK is a documented alias.
ALLOWED_MESSAGE_TYPES = {
    "CRITICAL",
    "WARNING",
    "INFO",
    "ACKNOWLEDGEMENT",
    "RECOVERY",
    "OK",
}

# Verified from the Splunkbase 5863 SOAR connector schema.
ALLOWED_INCIDENT_PHASES = {"UNACKED", "ACKED", "RESOLVED"}
ALLOWED_ENTITY_STATES = {"CRITICAL", "WARNING", "INFO"}

# Verified from product docs for outbound webhooks.
ALLOWED_WEBHOOK_EVENT_TYPES = {
    "Any-Incident",
    "Incident-Triggered",
    "Incident-Acknowledged",
    "Incident-Resolved",
    "Incident-Chats",
    "All-Chats",
    "Any-On-Call",
    "On-Call",
    "Off-Call",
    "Any-Paging",
    "Paging-Start",
    "Paging-Stop",
}
ALLOWED_WEBHOOK_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}

# Verified from the public API spec at portal.victorops.com/public/api-docs.html.
ALLOWED_MATCH_TYPES = {"WILDCARD", "REGEX"}

# Each annotation value has a 1,124-char limit per the REST endpoint docs.
ANNOTATION_VALUE_LIMIT = 1124

# Documented per-endpoint limits (see references/rate-limits.md).
RATE_LIMITS = {
    "default_per_sec": 2.0,
    "user_batch_per_sec": 1.0,
    "personal_paging_v1_read_per_sec": 1.0,
    "reporting_v2_incidents_per_min": 1.0,
}

# Direct secret keys that must never appear inline in a spec. The list mirrors
# the orchestrator's MCP secret-flag set so the validator catches secrets in
# the spec body before the API client is ever called.
DIRECT_SECRET_KEYS = {
    "api_key",
    "api_secret",
    "client_secret",
    "integration_key",
    "oncall_api_key",
    "on_call_api_key",
    "password",
    "rest_key",
    "secret",
    "token",
    "vo_api_key",
    "x_vo_api_key",
}

# Keys that legitimately end with `_key` or `_secret` but carry non-secret
# values. We allow these through the inline-secret guard rail.
NON_SECRET_KEYS = {
    "routing_key",
    "default_routing_key",
    "route_key",
    "policy_key",
    "policySlug",
    "shiftId",
    "publicId",
    "alertField",
    "fieldName",
}


class SpecError(ValueError):
    """Raised for invalid Splunk On-Call specs."""


# ---------------------------------------------------------------------------
# Spec loading + validation
# ---------------------------------------------------------------------------


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SpecError(f"{path} is not valid JSON: {exc}") from exc
    else:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - setup.sh preflights this.
            raise SpecError(
                "YAML On-Call specs require PyYAML. Use JSON or install repo dependencies."
            ) from exc
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SpecError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"{path} root must be a mapping/object.")
    return data


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-").lower()
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
            if normalized in NON_SECRET_KEYS or key_text in NON_SECRET_KEYS:
                reject_inline_secrets(child, (*path, key_text))
                continue
            allow_file_reference = normalized.endswith("_file") or normalized.endswith("_path")
            looks_secret = normalized in DIRECT_SECRET_KEYS or (
                normalized.endswith("_token") and not normalized.endswith("_token_file")
            ) or (
                normalized.endswith("_api_key") and not normalized.endswith("_api_key_file")
            ) or (
                normalized.endswith("_secret") and not normalized.endswith("_secret_file")
            )
            if looks_secret and not allow_file_reference:
                dotted = ".".join((*path, key_text))
                raise SpecError(
                    f"Inline secret field {dotted!r} is not allowed. Use a local secret file path instead."
                )
            reject_inline_secrets(child, (*path, key_text))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_inline_secrets(child, (*path, str(index)))


def validate_spec(spec: dict[str, Any]) -> None:
    api_version = str(spec.get("api_version", ""))
    if api_version != API_VERSION:
        raise SpecError(f"api_version must be {API_VERSION!r}.")
    reject_inline_secrets(spec)
    for section in SECTIONS:
        if section in {"paging_policies", "splunk_side", "sso", "recovery_polling"}:
            # Mappings, not lists.
            value = spec.get(section)
            if value is not None and not isinstance(value, dict):
                raise SpecError(f"{section} must be a mapping/object.")
            continue
        as_list(spec.get(section, []), section)

    # Per-section validators
    for entry in as_list(spec.get("users", []), "users"):
        validate_user(mapping_item(entry, "users[]"))
    for entry in as_list(spec.get("teams", []), "teams"):
        validate_team(mapping_item(entry, "teams[]"))
    for entry in as_list(spec.get("rotations", []), "rotations"):
        validate_rotation(mapping_item(entry, "rotations[]"))
    for entry in as_list(spec.get("escalation_policies", []), "escalation_policies"):
        validate_escalation_policy(mapping_item(entry, "escalation_policies[]"))
    for entry in as_list(spec.get("routing_keys", []), "routing_keys"):
        validate_routing_key(mapping_item(entry, "routing_keys[]"))
    if isinstance(spec.get("paging_policies"), dict):
        validate_paging_policies(spec["paging_policies"])
    for entry in as_list(spec.get("scheduled_overrides", []), "scheduled_overrides"):
        validate_scheduled_override(mapping_item(entry, "scheduled_overrides[]"))
    for entry in as_list(spec.get("alert_rules", []), "alert_rules"):
        validate_alert_rule(mapping_item(entry, "alert_rules[]"))
    for entry in as_list(spec.get("maintenance_mode", []), "maintenance_mode"):
        mapping_item(entry, "maintenance_mode[]")
    for entry in as_list(spec.get("incidents", []), "incidents"):
        validate_incident(mapping_item(entry, "incidents[]"))
    for entry in as_list(spec.get("notes", []), "notes"):
        validate_note(mapping_item(entry, "notes[]"))
    for entry in as_list(spec.get("webhooks", []), "webhooks"):
        validate_webhook(mapping_item(entry, "webhooks[]"))
    for entry in as_list(spec.get("rest_alerts", []), "rest_alerts"):
        validate_rest_alert(mapping_item(entry, "rest_alerts[]"))
    for entry in as_list(spec.get("integrations", []), "integrations"):
        mapping_item(entry, "integrations[]")
    for entry in as_list(spec.get("reports", []), "reports"):
        mapping_item(entry, "reports[]")
    for entry in as_list(spec.get("schedules", []), "schedules"):
        validate_schedule(mapping_item(entry, "schedules[]"))
    for entry in as_list(spec.get("calendars", []), "calendars"):
        mapping_item(entry, "calendars[]")
    for entry in as_list(spec.get("mobile", []), "mobile"):
        validate_mobile(mapping_item(entry, "mobile[]"))

    validate_referential_integrity(spec)


def validate_user(entry: dict[str, Any]) -> None:
    kind = str(entry.get("kind", "create"))
    if kind not in {"create", "update", "delete"}:
        raise SpecError(f"users[] kind must be create | update | delete (got {kind!r}).")
    username = str(entry.get("username", "")).strip()
    if not username:
        raise SpecError("users[] requires username.")
    if any(ch.isspace() or ch in {"/", "\\"} for ch in username):
        raise SpecError(
            f"users[{username!r}].username must not contain whitespace or path separators."
        )
    role = str(entry.get("role", "user"))
    if role not in ALLOWED_ROLES:
        raise SpecError(
            f"users[{username}].role must be one of {sorted(ALLOWED_ROLES)} (got {role!r})."
        )
    contact_methods = entry.get("contact_methods")
    if contact_methods is not None:
        if not isinstance(contact_methods, dict):
            raise SpecError(
                f"users[{username}].contact_methods must be a mapping/object."
            )
        for kind_label, value_field in (("emails", "email"), ("phones", "phone")):
            for cm_index, cm in enumerate(
                as_list(contact_methods.get(kind_label, []), f"users[{username}].contact_methods.{kind_label}")
            ):
                cm_obj = mapping_item(
                    cm, f"users[{username}].contact_methods.{kind_label}[{cm_index}]"
                )
                value = cm_obj.get(value_field)
                if not isinstance(value, str) or not value.strip():
                    raise SpecError(
                        f"users[{username}].contact_methods.{kind_label}[{cm_index}] requires "
                        f"a non-empty {value_field!r} string."
                    )
                rank = cm_obj.get("rank")
                if rank is not None and not isinstance(rank, int):
                    raise SpecError(
                        f"users[{username}].contact_methods.{kind_label}[{cm_index}].rank must be an integer."
                    )
        # Devices are read-only via the public API (GET / PUT / DELETE only;
        # no POST). Reject create-style device entries to avoid silently
        # dropping them at render time.
        if "devices" in contact_methods:
            raise SpecError(
                f"users[{username}].contact_methods.devices is read-only via the Splunk On-Call public API; "
                "manage device contact methods through the On-Call UI or PUT/DELETE only."
            )


def validate_team(entry: dict[str, Any]) -> None:
    name = str(entry.get("name", "")).strip()
    if not name:
        raise SpecError("teams[] requires name.")
    for label in ("members", "admins"):
        for index, value in enumerate(as_list(entry.get(label, []), f"teams[{name}].{label}")):
            if not isinstance(value, str) or not value.strip():
                raise SpecError(
                    f"teams[{name}].{label}[{index}] must be a non-empty username string."
                )


def validate_rotation(entry: dict[str, Any]) -> None:
    name = str(entry.get("name", "")).strip()
    team = str(entry.get("team", "")).strip()
    if not name:
        raise SpecError("rotations[] requires name.")
    if not team:
        raise SpecError(f"rotation {name!r} requires team.")
    shifts = as_list(entry.get("shifts", []), f"rotation {name!r} shifts")
    if not shifts:
        raise SpecError(f"rotation {name!r} requires at least one shift.")
    for index, shift in enumerate(shifts):
        mapping_item(shift, f"rotation {name!r} shifts[{index}]")
        if not str(shift.get("name", "")).strip():
            raise SpecError(f"rotation {name!r} shifts[{index}] requires name.")


def validate_escalation_policy(entry: dict[str, Any]) -> None:
    name = str(entry.get("name", "")).strip()
    team = str(entry.get("team", "")).strip()
    if not name:
        raise SpecError("escalation_policies[] requires name.")
    if not team:
        raise SpecError(f"escalation policy {name!r} requires team.")
    steps = as_list(entry.get("steps", []), f"escalation policy {name!r} steps")
    if not steps:
        raise SpecError(f"escalation policy {name!r} requires at least one step.")
    for index, step in enumerate(steps):
        step_obj = mapping_item(step, f"escalation policy {name!r} steps[{index}]")
        targets = as_list(step_obj.get("targets", []), f"escalation policy {name!r} steps[{index}].targets")
        if not targets:
            raise SpecError(
                f"escalation policy {name!r} steps[{index}] requires at least one target."
            )
        for t_index, target in enumerate(targets):
            t_obj = mapping_item(target, f"escalation policy {name!r} steps[{index}].targets[{t_index}]")
            t_type = str(t_obj.get("type", "")).strip().lower()
            if t_type not in {"user", "team", "escalationpolicy", "escalation_policy", "rotation_group", "rotationgroup"}:
                raise SpecError(
                    f"escalation policy {name!r} steps[{index}].targets[{t_index}].type "
                    f"must be one of user | team | EscalationPolicy | RotationGroup (got {t_type!r})."
                )


def validate_routing_key(entry: dict[str, Any]) -> None:
    routing_key = str(entry.get("routingKey", "")).strip()
    if not routing_key:
        raise SpecError("routing_keys[] requires routingKey.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", routing_key):
        raise SpecError(
            f"routing_keys[].routingKey {routing_key!r} must be alphanumeric (with . _ -)."
        )
    targets = as_list(entry.get("targets", []), f"routing key {routing_key!r} targets")
    for index, target in enumerate(targets):
        mapping_item(target, f"routing key {routing_key!r} targets[{index}]")


def validate_paging_policies(entry: dict[str, Any]) -> None:
    for username_obj in as_list(entry.get("personal", []), "paging_policies.personal"):
        obj = mapping_item(username_obj, "paging_policies.personal[]")
        username = str(obj.get("username", "")).strip()
        if not username:
            raise SpecError("paging_policies.personal[] requires username.")
        steps = as_list(obj.get("steps", []), f"paging_policies.personal[{username}].steps")
        if not steps:
            raise SpecError(
                f"paging_policies.personal[{username}].steps must contain at least one step."
            )


def validate_scheduled_override(entry: dict[str, Any]) -> None:
    if not str(entry.get("origOnCallUser", "")).strip():
        raise SpecError("scheduled_overrides[] requires origOnCallUser.")
    if not str(entry.get("overrideOnCallUser", "")).strip():
        raise SpecError("scheduled_overrides[] requires overrideOnCallUser.")
    for field in ("start", "end"):
        if not str(entry.get(field, "")).strip():
            raise SpecError(f"scheduled_overrides[] requires {field}.")


def validate_alert_rule(entry: dict[str, Any]) -> None:
    if not str(entry.get("alertField", "")).strip():
        raise SpecError("alert_rules[] requires alertField.")
    match_type = str(entry.get("matchType", "WILDCARD"))
    if match_type not in ALLOWED_MATCH_TYPES:
        raise SpecError(
            f"alert_rules[].matchType must be one of {sorted(ALLOWED_MATCH_TYPES)} (got {match_type!r})."
        )
    rank = entry.get("rank")
    if rank is not None and not isinstance(rank, int):
        raise SpecError("alert_rules[].rank must be an integer.")
    annotations = as_list(entry.get("annotations", []), "alert_rules[].annotations")
    for index, ann in enumerate(annotations):
        ann_obj = mapping_item(ann, f"alert_rules[].annotations[{index}]")
        ann_type = str(ann_obj.get("annotationType", "")).strip().lower()
        if ann_type not in {"url", "note", "image"}:
            raise SpecError(
                f"alert_rules[].annotations[{index}].annotationType must be url | note | image."
            )


def validate_incident(entry: dict[str, Any]) -> None:
    kind = str(entry.get("kind", "")).strip().lower()
    if kind not in {"create", "ack", "resolve", "reroute", "by_user_ack", "by_user_resolve"}:
        raise SpecError(
            "incidents[].kind must be create | ack | resolve | reroute | by_user_ack | by_user_resolve."
        )
    if kind == "create":
        if not str(entry.get("summary", "")).strip():
            raise SpecError("incidents[] kind=create requires summary.")
        targets = as_list(entry.get("targets", []), "incidents[].targets")
        for index, target in enumerate(targets):
            t_obj = mapping_item(target, f"incidents[].targets[{index}]")
            t_type = str(t_obj.get("type", "")).strip()
            if t_type not in {"User", "Team", "EscalationPolicy", "RotationGroup"}:
                raise SpecError(
                    f"incidents[].targets[{index}].type must be User | Team | EscalationPolicy | RotationGroup."
                )
        is_multi = entry.get("isMultiResponder")
        if is_multi is not None and not isinstance(is_multi, bool):
            raise SpecError("incidents[].isMultiResponder must be boolean.")
        state_start_time = entry.get("state_start_time")
        if state_start_time is not None and not isinstance(state_start_time, int):
            raise SpecError("incidents[].state_start_time must be an integer (epoch seconds).")


def validate_note(entry: dict[str, Any]) -> None:
    if not str(entry.get("incidentNumber", "")).strip():
        raise SpecError("notes[] requires incidentNumber.")
    kind = str(entry.get("kind", "create"))
    if kind not in {"create", "update", "delete", "list"}:
        raise SpecError("notes[].kind must be create | update | delete | list.")


def validate_webhook(entry: dict[str, Any]) -> None:
    kind = str(entry.get("kind", "inventory")).strip()
    if kind not in {"inventory", "planned"}:
        raise SpecError("webhooks[].kind must be inventory | planned.")
    if kind == "planned":
        event_type = str(entry.get("eventType", "")).strip()
        if event_type not in ALLOWED_WEBHOOK_EVENT_TYPES:
            raise SpecError(
                f"webhooks[].eventType must be one of {sorted(ALLOWED_WEBHOOK_EVENT_TYPES)}."
            )
        method = str(entry.get("method", "POST")).strip().upper()
        if method not in ALLOWED_WEBHOOK_METHODS:
            raise SpecError(
                f"webhooks[].method must be one of {sorted(ALLOWED_WEBHOOK_METHODS)}."
            )


def validate_rest_alert(entry: dict[str, Any]) -> None:
    message_type = str(entry.get("message_type", "")).strip().upper()
    if message_type not in ALLOWED_MESSAGE_TYPES:
        raise SpecError(
            f"rest_alerts[].message_type must be one of {sorted(ALLOWED_MESSAGE_TYPES)}."
        )
    annotations = as_list(entry.get("annotations", []), "rest_alerts[].annotations")
    for index, ann in enumerate(annotations):
        ann_obj = mapping_item(ann, f"rest_alerts[].annotations[{index}]")
        kind = str(ann_obj.get("kind", "")).strip().lower()
        if kind not in {"url", "note", "image"}:
            raise SpecError(
                f"rest_alerts[].annotations[{index}].kind must be url | note | image."
            )
        title = str(ann_obj.get("title", "")).strip()
        if not title:
            raise SpecError(f"rest_alerts[].annotations[{index}] requires title.")
        value = ann_obj.get("value", "")
        if not isinstance(value, str):
            raise SpecError(f"rest_alerts[].annotations[{index}] value must be a string.")
        if len(value) > ANNOTATION_VALUE_LIMIT:
            raise SpecError(
                f"rest_alerts[].annotations[{index}] value exceeds the {ANNOTATION_VALUE_LIMIT}-char limit "
                f"(got {len(value)})."
            )


def validate_schedule(entry: dict[str, Any]) -> None:
    kind = str(entry.get("kind", "")).strip()
    if kind not in {"team", "user"}:
        raise SpecError("schedules[].kind must be team | user.")
    if kind == "team" and not str(entry.get("team", "")).strip():
        raise SpecError("schedules[] kind=team requires team.")
    if kind == "user" and not str(entry.get("user", "")).strip():
        raise SpecError("schedules[] kind=user requires user.")
    days_forward = entry.get("daysForward", 90)
    if not isinstance(days_forward, int) or days_forward <= 0 or days_forward > 365:
        raise SpecError("schedules[].daysForward must be an integer in 1..365.")


def validate_mobile(entry: dict[str, Any]) -> None:
    if not str(entry.get("user", "")).strip():
        raise SpecError("mobile[] requires user.")
    platform = str(entry.get("platform", "")).strip().lower()
    if platform not in {"ios", "android"}:
        raise SpecError("mobile[].platform must be ios | android.")


def validate_referential_integrity(spec: dict[str, Any]) -> None:
    teams = {str(item.get("name", "")).strip() for item in as_list(spec.get("teams", []), "teams")}
    usernames = {str(item.get("username", "")).strip() for item in as_list(spec.get("users", []), "users")}
    policies = {str(item.get("name", "")).strip() for item in as_list(spec.get("escalation_policies", []), "escalation_policies")}
    rotations = {str(item.get("name", "")).strip() for item in as_list(spec.get("rotations", []), "rotations")}

    # Cross-check rotations and escalation policies reference known teams.
    for rotation in as_list(spec.get("rotations", []), "rotations"):
        team = str(rotation.get("team", "")).strip()
        if teams and team not in teams:
            raise SpecError(
                f"rotation {rotation.get('name')!r} references unknown team {team!r}."
            )
    for policy in as_list(spec.get("escalation_policies", []), "escalation_policies"):
        team = str(policy.get("team", "")).strip()
        if teams and team not in teams:
            raise SpecError(
                f"escalation policy {policy.get('name')!r} references unknown team {team!r}."
            )
    for rotation in as_list(spec.get("rotations", []), "rotations"):
        for shift_index, shift in enumerate(as_list(rotation.get("shifts", []), "shifts")):
            for member in as_list(mapping_item(shift, "shift").get("members", []), "shift.members"):
                if usernames and str(member).strip() not in usernames:
                    raise SpecError(
                        f"rotation {rotation.get('name')!r} shifts[{shift_index}] member {member!r} "
                        "is not declared in users."
                    )

    # Routing keys may reference policies and teams that are declared only in
    # On-Call (not in this spec). Warnings rather than errors are surfaced via
    # coverage_report.
    _ = policies
    _ = rotations


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def reset_output_dir(output_dir: Path) -> None:
    """Reset the output directory in a way that refuses to wipe arbitrary data.

    The directory is wiped only when one of the following holds:

    1. The directory does not exist (no-op).
    2. The directory exists but is empty.
    3. The directory exists and contains the marker file
       ``metadata.json`` from a previous render with a matching
       ``mode == 'splunk-oncall'``.

    In all other cases we refuse to wipe and raise a ``SpecError``. This
    protects an operator who accidentally points ``--output-dir`` at a
    populated directory like ``~/Documents`` or the repo root.
    """
    if output_dir.exists():
        if not output_dir.is_dir():
            raise SpecError(f"Output path exists but is not a directory: {output_dir}")
        children = list(output_dir.iterdir())
        if children:
            metadata_path = output_dir / "metadata.json"
            safe_to_wipe = False
            if metadata_path.is_file():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    metadata = None
                if isinstance(metadata, dict) and metadata.get("mode") == "splunk-oncall":
                    safe_to_wipe = True
            if not safe_to_wipe:
                raise SpecError(
                    f"Refusing to wipe non-empty output directory {output_dir}: "
                    "no splunk-oncall metadata.json marker. Choose an empty directory "
                    "or a previously-rendered splunk-oncall-setup output."
                )
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def coverage_entry(
    *,
    object_type: str,
    name: str,
    coverage: str,
    notes: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if coverage not in ALLOWED_COVERAGE:
        raise SpecError(f"coverage {coverage!r} not in {sorted(ALLOWED_COVERAGE)}.")
    entry: dict[str, Any] = {
        "object_type": object_type,
        "name": name,
        "coverage": coverage,
    }
    if notes:
        entry["notes"] = notes
    if extra:
        entry.update(extra)
    return entry


def write_payload(output_dir: Path, section: str, slug: str, payload: dict[str, Any]) -> str:
    rel = f"payloads/{section}/{slug}.json"
    write_json(output_dir / rel, payload)
    return rel


def render_users(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for entry in as_list(spec.get("users", []), "users"):
        username = str(entry.get("username", "")).strip()
        kind = str(entry.get("kind", "create"))
        slug = slugify(username)
        if kind == "create":
            payload = {
                "username": username,
                "firstName": entry.get("firstName"),
                "lastName": entry.get("lastName"),
                "email": entry.get("email"),
                "admin": entry.get("role") == "global_admin",
            }
            payload_file = write_payload(output_dir, "users", slug, payload)
            actions.append({
                "action": "create_user",
                "object_type": "user",
                "name": username,
                "service": "on_call",
                "method": "POST",
                "path": "/api-public/v1/user",
                "payload_file": payload_file,
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
        elif kind == "update":
            payload = {key: value for key, value in entry.items() if key not in {"kind"}}
            payload_file = write_payload(output_dir, "users", f"{slug}.update", payload)
            actions.append({
                "action": "update_user",
                "object_type": "user",
                "name": username,
                "service": "on_call",
                "method": "PUT",
                "path": f"/api-public/v1/user/{quote(username, safe='')}",
                "payload_file": payload_file,
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
        elif kind == "delete":
            actions.append({
                "action": "delete_user",
                "object_type": "user",
                "name": username,
                "service": "on_call",
                "method": "DELETE",
                "path": f"/api-public/v1/user/{quote(username, safe='')}",
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })

        contact_methods = entry.get("contact_methods") or {}
        if isinstance(contact_methods, dict):
            for method_kind, plural_path in (
                ("emails", "emails"),
                ("phones", "phones"),
            ):
                for cm_index, cm in enumerate(as_list(contact_methods.get(method_kind, []), f"contact_methods.{method_kind}")):
                    cm_obj = mapping_item(cm, f"contact_methods.{method_kind}[{cm_index}]")
                    cm_slug = f"{slug}.{method_kind}.{cm_index}"
                    cm_path = write_payload(output_dir, "users", cm_slug, cm_obj)
                    actions.append({
                        "action": f"create_user_contact_{method_kind[:-1]}",
                        "object_type": f"user_contact_{method_kind[:-1]}",
                        "name": f"{username}/{method_kind}/{cm_index}",
                        "service": "on_call",
                        "method": "POST",
                        "path": f"/api-public/v1/user/{quote(username, safe='')}/contact-methods/{plural_path}",
                        "payload_file": cm_path,
                        "coverage": "api_apply",
                        "rate_bucket": "default",
                        "writes": True,
                    })

        coverage.append(coverage_entry(
            object_type="user",
            name=username,
            coverage="api_apply",
            extra={"role": entry.get("role", "user"), "kind": kind},
        ))
    return coverage, actions


def render_teams(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Render team create + member-add actions.

    Splunk On-Call assigns teams a system-generated slug like
    ``team-ClhQ5054yCuro0yW`` when the team is created. Subsequent member
    and admin operations require that real slug; the locally-slugified
    name will not work. Operators have two paths:

    1. Run ``--apply`` on the team-create action first, copy the slug from
       the response, paste it into the spec as ``slug:``, then re-render and
       apply the dependent actions.
    2. Look up the slug in the On-Call UI / ``GET /v1/team`` and supply it
       via ``slug:`` from the start.

    When ``slug:`` is provided, the renderer emits ``api_apply`` actions
    for member and admin grants. When ``slug:`` is absent, those grants
    become ``handoff`` coverage entries documenting the two-pass workflow,
    so the apply-plan never contains a path that would 404.
    """
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for entry in as_list(spec.get("teams", []), "teams"):
        name = str(entry.get("name", "")).strip()
        local_slug = slugify(name)
        team_slug = str(entry.get("slug", "")).strip()
        kind = str(entry.get("kind", "create"))
        admins = {str(item).strip() for item in as_list(entry.get("admins", []), f"team {name!r} admins")}
        if kind == "create":
            payload = {"name": name}
            payload_file = write_payload(output_dir, "teams", local_slug, payload)
            actions.append({
                "action": "create_team",
                "object_type": "team",
                "name": name,
                "service": "on_call",
                "method": "POST",
                "path": "/api-public/v1/team",
                "payload_file": payload_file,
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
        members = as_list(entry.get("members", []), f"team {name!r} members")
        if members and team_slug:
            for member_index, member in enumerate(members):
                mem_payload: dict[str, Any] = {"username": member}
                if member in admins:
                    mem_payload["isAdmin"] = True
                mem_path = write_payload(
                    output_dir, "teams", f"{local_slug}.member.{member_index}", mem_payload
                )
                actions.append({
                    "action": "add_team_member",
                    "object_type": "team_member",
                    "name": f"{name}/{member}",
                    "service": "on_call",
                    "method": "POST",
                    "path": f"/api-public/v1/team/{quote(team_slug, safe='')}/members",
                    "payload_file": mem_path,
                    "coverage": "api_apply",
                    "rate_bucket": "default",
                    "writes": True,
                })
        elif members:
            coverage.append(coverage_entry(
                object_type="team_membership_handoff",
                name=name,
                coverage="handoff",
                notes=(
                    "Members and admins cannot be added until the team's system-generated slug "
                    "is known. Apply the team-create action first, copy the returned slug into "
                    "the spec as `slug:`, then re-render and apply."
                ),
                extra={"members": list(members), "admins": sorted(admins)},
            ))
        coverage.append(coverage_entry(
            object_type="team",
            name=name,
            coverage="api_apply",
            extra={"slug": team_slug or None, "admins": sorted(admins)},
        ))
    return coverage, actions


def _team_slug_for(spec: dict[str, Any], team_name: str) -> str:
    """Resolve a team's system-generated slug from the spec, if provided.

    Splunk On-Call's API addresses teams by their system slug
    (e.g. ``team-ClhQ5054yCuro0yW``). When the operator declared the team
    inline with a ``slug:`` field, return it. Otherwise return an empty
    string so callers can render a handoff instead of a 404-bound action.
    """
    if not team_name:
        return ""
    for raw_team in as_list(spec.get("teams", []), "teams"):
        if not isinstance(raw_team, dict):
            continue
        if str(raw_team.get("name", "")).strip() == team_name:
            slug = str(raw_team.get("slug", "")).strip()
            if slug:
                return slug
    return ""


def render_rotations(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Render rotation create actions.

    The rotation-create path is ``POST /api-public/v1/teams/{team}/rotations``,
    where ``{team}`` is the team's system-generated slug. When the spec
    supplies the team's slug (either via the team's ``slug:`` field or the
    rotation's own ``team_slug:``), we emit an ``api_apply`` action.
    Otherwise we emit a ``handoff`` coverage entry only.
    """
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for entry in as_list(spec.get("rotations", []), "rotations"):
        name = str(entry.get("name", "")).strip()
        team_name = str(entry.get("team", "")).strip()
        # Prefer an explicit override, then look up the team's slug.
        team_slug = str(entry.get("team_slug", "")).strip() or _team_slug_for(spec, team_name)
        slug = slugify(name)
        payload = {
            "name": name,
            "timezone": entry.get("timezone"),
            "shifts": entry.get("shifts", []),
        }
        payload_file = write_payload(output_dir, "rotations", f"{slugify(team_name)}.{slug}", payload)
        if team_slug:
            actions.append({
                "action": "create_rotation",
                "object_type": "rotation",
                "name": name,
                "service": "on_call",
                "method": "POST",
                "path": f"/api-public/v1/teams/{quote(team_slug, safe='')}/rotations",
                "payload_file": payload_file,
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
            coverage.append(coverage_entry(
                object_type="rotation",
                name=name,
                coverage="api_apply",
                extra={"team_slug": team_slug},
            ))
        else:
            coverage.append(coverage_entry(
                object_type="rotation",
                name=name,
                coverage="handoff",
                notes=(
                    "Rotation create requires the team's system-generated slug. "
                    "Add `slug:` to the team in the spec (or `team_slug:` on the rotation) "
                    "and re-render."
                ),
                extra={"team": team_name, "payload_file": payload_file},
            ))
    return coverage, actions


def render_escalation_policies(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Render escalation policy create actions.

    The body's ``team`` field must contain the team's system-generated
    slug, not a slugified name. Without a real slug the API returns 400.
    When ``slug:`` is missing from the team, we render a handoff instead
    of an apply action so the operator gets a clear two-pass workflow.
    """
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for entry in as_list(spec.get("escalation_policies", []), "escalation_policies"):
        name = str(entry.get("name", "")).strip()
        slug = slugify(name)
        team_name = str(entry.get("team", "")).strip()
        team_slug = str(entry.get("team_slug", "")).strip() or _team_slug_for(spec, team_name)
        payload = {
            "name": name,
            "team": team_slug,
            "steps": entry.get("steps", []),
        }
        payload_file = write_payload(output_dir, "escalation_policies", slug, payload)
        if team_slug:
            actions.append({
                "action": "create_escalation_policy",
                "object_type": "escalation_policy",
                "name": name,
                "service": "on_call",
                "method": "POST",
                "path": "/api-public/v1/policies",
                "payload_file": payload_file,
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
                "notes": "Public API has no PUT for escalation policies; updates are delete + recreate.",
            })
            coverage.append(coverage_entry(
                object_type="escalation_policy",
                name=name,
                coverage="api_apply",
                extra={"team_slug": team_slug},
            ))
        else:
            coverage.append(coverage_entry(
                object_type="escalation_policy",
                name=name,
                coverage="handoff",
                notes=(
                    "Escalation policy create requires the team's system-generated slug in "
                    "the body. Add `slug:` to the team (or `team_slug:` on the policy) and "
                    "re-render."
                ),
                extra={"team": team_name, "payload_file": payload_file},
            ))
    return coverage, actions


def render_routing_keys(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for entry in as_list(spec.get("routing_keys", []), "routing_keys"):
        routing_key = str(entry.get("routingKey", "")).strip()
        slug = slugify(routing_key)
        payload = {"routingKey": routing_key, "targets": entry.get("targets", [])}
        payload_file = write_payload(output_dir, "routing_keys", slug, payload)
        actions.append({
            "action": "create_routing_key",
            "object_type": "routing_key",
            "name": routing_key,
            "service": "on_call",
            "method": "POST",
            "path": "/api-public/v1/org/routing-keys",
            "payload_file": payload_file,
            "coverage": "api_apply",
            "rate_bucket": "default",
            "writes": True,
        })
        coverage.append(coverage_entry(object_type="routing_key", name=routing_key, coverage="api_apply"))
    return coverage, actions


def render_paging_policies(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    paging = spec.get("paging_policies") or {}
    if not isinstance(paging, dict):
        return coverage, actions
    for entry in as_list(paging.get("personal", []), "paging_policies.personal"):
        username = str(entry.get("username", "")).strip()
        slug = slugify(username)
        steps = entry.get("steps", [])
        payload = {"steps": steps}
        payload_file = write_payload(output_dir, "paging_policies", slug, payload)
        actions.append({
            "action": "set_personal_paging_policy",
            "object_type": "personal_paging_policy",
            "name": username,
            "service": "on_call",
            "method": "POST",
            "path": f"/api-public/v1/profile/{quote(username, safe='')}/policies",
            "payload_file": payload_file,
            "coverage": "api_apply",
            "rate_bucket": "default",
            "writes": True,
        })
        coverage.append(coverage_entry(object_type="personal_paging_policy", name=username, coverage="api_apply"))
    for team in as_list(paging.get("team", []), "paging_policies.team"):
        team_obj = mapping_item(team, "paging_policies.team[]")
        team_name = str(team_obj.get("team", "")).strip()
        team_slug = str(team_obj.get("slug", "")).strip() or _team_slug_for(spec, team_name)
        if team_slug:
            actions.append({
                "action": "list_team_policies",
                "object_type": "team_paging_policy",
                "name": team_name or team_slug,
                "service": "on_call",
                "method": "GET",
                "path": f"/api-public/v1/team/{quote(team_slug, safe='')}/policies",
                "coverage": "api_validate",
                "rate_bucket": "default",
                "writes": False,
            })
            coverage.append(coverage_entry(
                object_type="team_paging_policy",
                name=team_name or team_slug,
                coverage="api_validate",
                extra={"team_slug": team_slug},
            ))
        else:
            coverage.append(coverage_entry(
                object_type="team_paging_policy",
                name=team_name or "<unknown>",
                coverage="handoff",
                notes=(
                    "Team paging policy read requires the team's system-generated slug. "
                    "Add `slug:` to the team and re-render."
                ),
            ))
    return coverage, actions


def render_scheduled_overrides(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("scheduled_overrides", []), "scheduled_overrides")):
        slug = slugify(f"{entry.get('origOnCallUser')}-to-{entry.get('overrideOnCallUser')}-{index}")
        payload = {key: value for key, value in entry.items() if key != "kind"}
        payload_file = write_payload(output_dir, "scheduled_overrides", slug, payload)
        actions.append({
            "action": "create_scheduled_override",
            "object_type": "scheduled_override",
            "name": slug,
            "service": "on_call",
            "method": "POST",
            "path": "/api-public/v1/overrides",
            "payload_file": payload_file,
            "coverage": "api_apply",
            "rate_bucket": "default",
            "writes": True,
        })
        coverage.append(coverage_entry(object_type="scheduled_override", name=slug, coverage="api_apply"))
    return coverage, actions


def render_alert_rules(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("alert_rules", []), "alert_rules")):
        name = entry.get("name", f"{entry.get('alertField', 'rule')}-{index}")
        slug = slugify(str(name))
        payload = {key: value for key, value in entry.items() if key != "kind"}
        payload_file = write_payload(output_dir, "alert_rules", slug, payload)
        actions.append({
            "action": "create_alert_rule",
            "object_type": "alert_rule",
            "name": name,
            "service": "on_call",
            "method": "POST",
            "path": "/api-public/v1/alertRules",
            "payload_file": payload_file,
            "coverage": "api_apply",
            "rate_bucket": "alert_rules",
            "writes": True,
        })
        coverage.append(coverage_entry(object_type="alert_rule", name=name, coverage="api_apply"))
    return coverage, actions


def render_maintenance_mode(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("maintenance_mode", []), "maintenance_mode")):
        kind = str(entry.get("kind", "status"))
        slug = slugify(f"maintenance-{kind}-{index}")
        if kind == "start":
            payload = {key: value for key, value in entry.items() if key != "kind"}
            payload_file = write_payload(output_dir, "maintenance_mode", slug, payload)
            actions.append({
                "action": "start_maintenance_mode",
                "object_type": "maintenance_mode",
                "name": slug,
                "service": "on_call",
                "method": "POST",
                "path": "/api-public/v1/maintenancemode/start",
                "payload_file": payload_file,
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
            coverage.append(coverage_entry(object_type="maintenance_mode", name=slug, coverage="api_apply"))
        elif kind == "end":
            mode_id = str(entry.get("maintenanceModeId", "")).strip()
            actions.append({
                "action": "end_maintenance_mode",
                "object_type": "maintenance_mode",
                "name": slug,
                "service": "on_call",
                "method": "PUT",
                "path": f"/api-public/v1/maintenancemode/{quote(mode_id, safe='')}/end",
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
            coverage.append(coverage_entry(object_type="maintenance_mode", name=slug, coverage="api_apply"))
        else:
            actions.append({
                "action": "get_maintenance_mode",
                "object_type": "maintenance_mode",
                "name": slug,
                "service": "on_call",
                "method": "GET",
                "path": "/api-public/v1/maintenancemode",
                "coverage": "api_validate",
                "rate_bucket": "default",
                "writes": False,
            })
            coverage.append(coverage_entry(object_type="maintenance_mode", name=slug, coverage="api_validate"))
    return coverage, actions


def render_incidents(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("incidents", []), "incidents")):
        kind = str(entry.get("kind", "create"))
        slug = slugify(f"incident-{kind}-{index}")
        if kind == "create":
            payload = {key: value for key, value in entry.items() if key != "kind"}
            payload_file = write_payload(output_dir, "incidents", slug, payload)
            actions.append({
                "action": "create_incident",
                "object_type": "incident",
                "name": slug,
                "service": "on_call",
                "method": "POST",
                "path": "/api-public/v1/incidents",
                "payload_file": payload_file,
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
        elif kind in {"ack", "resolve", "reroute"}:
            payload = {key: value for key, value in entry.items() if key != "kind"}
            payload_file = write_payload(output_dir, "incidents", slug, payload)
            method = "POST" if kind == "reroute" else "PATCH"
            path = f"/api-public/v1/incidents/{kind}" if kind != "reroute" else "/api-public/v1/incidents/reroute"
            actions.append({
                "action": f"{kind}_incident",
                "object_type": "incident",
                "name": slug,
                "service": "on_call",
                "method": method,
                "path": path,
                "payload_file": payload_file,
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
        elif kind in {"by_user_ack", "by_user_resolve"}:
            payload = {key: value for key, value in entry.items() if key != "kind"}
            payload_file = write_payload(output_dir, "incidents", slug, payload)
            sub = "ack" if kind == "by_user_ack" else "resolve"
            actions.append({
                "action": f"by_user_{sub}",
                "object_type": "incident",
                "name": slug,
                "service": "on_call",
                "method": "PATCH",
                "path": f"/api-public/v1/incidents/byUser/{sub}",
                "payload_file": payload_file,
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
        coverage.append(coverage_entry(object_type="incident", name=slug, coverage="api_apply"))
    return coverage, actions


def render_notes(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("notes", []), "notes")):
        incident_number = str(entry.get("incidentNumber", "")).strip()
        kind = str(entry.get("kind", "create"))
        note_name = str(entry.get("noteName", f"note-{index}")).strip()
        slug = slugify(f"{incident_number}-{note_name}-{kind}")
        if kind == "list":
            actions.append({
                "action": "list_notes",
                "object_type": "incident_note",
                "name": slug,
                "service": "on_call",
                "method": "GET",
                "path": f"/api-public/v1/incidents/{quote(incident_number, safe='')}/notes",
                "coverage": "api_validate",
                "rate_bucket": "default",
                "writes": False,
            })
            coverage.append(coverage_entry(object_type="incident_note", name=slug, coverage="api_validate"))
            continue
        body = {"noteName": note_name, "body": entry.get("body", "")}
        payload_file = write_payload(output_dir, "notes", slug, body)
        if kind == "create":
            actions.append({
                "action": "create_note",
                "object_type": "incident_note",
                "name": slug,
                "service": "on_call",
                "method": "POST",
                "path": f"/api-public/v1/incidents/{quote(incident_number, safe='')}/notes",
                "payload_file": payload_file,
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
        elif kind == "update":
            actions.append({
                "action": "update_note",
                "object_type": "incident_note",
                "name": slug,
                "service": "on_call",
                "method": "PUT",
                "path": f"/api-public/v1/incidents/{quote(incident_number, safe='')}/notes/{quote(note_name, safe='')}",
                "payload_file": payload_file,
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
        elif kind == "delete":
            actions.append({
                "action": "delete_note",
                "object_type": "incident_note",
                "name": slug,
                "service": "on_call",
                "method": "DELETE",
                "path": f"/api-public/v1/incidents/{quote(incident_number, safe='')}/notes/{quote(note_name, safe='')}",
                "coverage": "api_apply",
                "rate_bucket": "default",
                "writes": True,
            })
        coverage.append(coverage_entry(object_type="incident_note", name=slug, coverage="api_apply"))
    return coverage, actions


def render_chat_messages(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("chat_messages", []), "chat_messages")):
        slug = slugify(f"chat-{index}-{entry.get('team', '')}")
        payload = {"message": entry.get("message", ""), "team": entry.get("team")}
        payload_file = write_payload(output_dir, "chat_messages", slug, payload)
        actions.append({
            "action": "send_chat",
            "object_type": "chat_message",
            "name": slug,
            "service": "on_call",
            "method": "POST",
            "path": "/api-public/v1/chat",
            "payload_file": payload_file,
            "coverage": "api_apply",
            "rate_bucket": "default",
            "writes": True,
        })
        coverage.append(coverage_entry(object_type="chat_message", name=slug, coverage="api_apply"))
    return coverage, actions


def render_stakeholder_messages(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("stakeholder_messages", []), "stakeholder_messages")):
        slug = slugify(f"stakeholder-{index}")
        payload = {key: value for key, value in entry.items()}
        payload_file = write_payload(output_dir, "stakeholder_messages", slug, payload)
        actions.append({
            "action": "send_stakeholder_message",
            "object_type": "stakeholder_message",
            "name": slug,
            "service": "on_call",
            "method": "POST",
            "path": "/api-public/v1/stakeholders/sendMessage",
            "payload_file": payload_file,
            "coverage": "api_apply",
            "rate_bucket": "default",
            "writes": True,
        })
        coverage.append(coverage_entry(object_type="stakeholder_message", name=slug, coverage="api_apply"))
    return coverage, actions


def render_webhooks(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    enterprise_warning_emitted = False
    for index, entry in enumerate(as_list(spec.get("webhooks", []), "webhooks")):
        kind = str(entry.get("kind", "inventory"))
        slug = slugify(f"webhook-{kind}-{index}")
        if kind == "inventory":
            actions.append({
                "action": "list_webhooks",
                "object_type": "webhook",
                "name": slug,
                "service": "on_call",
                "method": "GET",
                "path": "/api-public/v1/webhooks",
                "coverage": "api_validate",
                "rate_bucket": "default",
                "writes": False,
            })
            coverage.append(coverage_entry(object_type="webhook", name=slug, coverage="api_validate"))
        else:
            payload = {key: value for key, value in entry.items() if key != "kind"}
            write_payload(output_dir, "webhooks", slug, payload)
            notes = "Outbound webhooks are configured in the UI; the public API only exposes GET /v1/webhooks."
            if not enterprise_warning_emitted:
                notes += " Outbound webhooks require an Enterprise plan."
                enterprise_warning_emitted = True
            coverage.append(coverage_entry(
                object_type="webhook",
                name=slug,
                coverage="handoff",
                notes=notes,
                extra={"event_type": entry.get("eventType"), "method": entry.get("method", "POST")},
            ))
    return coverage, actions


def render_reporting(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("reporting", []), "reporting")):
        kind = str(entry.get("kind", "")).strip()
        if kind == "shift_changes":
            team_name = str(entry.get("team", "")).strip()
            team_slug = str(entry.get("team_slug", "")).strip() or _team_slug_for(spec, team_name)
            slug_label = team_slug or slugify(team_name) or f"unknown-{index}"
            if team_slug:
                actions.append({
                    "action": "list_shift_changes",
                    "object_type": "report_shift_changes",
                    "name": f"shift-changes-{slug_label}",
                    "service": "on_call",
                    "method": "GET",
                    "path": f"/api-reporting/v1/team/{quote(team_slug, safe='')}/oncall/log",
                    "coverage": "api_validate",
                    "rate_bucket": "default",
                    "writes": False,
                })
                coverage.append(coverage_entry(
                    object_type="report_shift_changes",
                    name=f"shift-changes-{slug_label}",
                    coverage="api_validate",
                ))
            else:
                coverage.append(coverage_entry(
                    object_type="report_shift_changes",
                    name=f"shift-changes-{slug_label}",
                    coverage="handoff",
                    notes=(
                        "Shift-changes report requires the team's system-generated slug. "
                        "Add `slug:` to the team or `team_slug:` to the reporting entry."
                    ),
                ))
        elif kind == "incident_history":
            actions.append({
                "action": "list_incident_history",
                "object_type": "report_incident_history",
                "name": f"incident-history-{index}",
                "service": "on_call",
                "method": "GET",
                "path": "/api-reporting/v2/incidents",
                "coverage": "api_validate",
                "rate_bucket": "reporting_v2_incidents",
                "writes": False,
                "notes": "Rate-limited at 1 call/minute.",
            })
            coverage.append(coverage_entry(
                object_type="report_incident_history",
                name=f"incident-history-{index}",
                coverage="api_validate",
                notes="Rate-limited at 1 call/minute.",
            ))
    return coverage, actions


def render_schedules(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("schedules", []), "schedules")):
        kind = str(entry.get("kind", "")).strip()
        days_forward = int(entry.get("daysForward", 90))
        if kind == "team":
            team_name = str(entry.get("team", "")).strip()
            team_slug = str(entry.get("team_slug", "")).strip() or _team_slug_for(spec, team_name)
            slug_label = team_slug or slugify(team_name) or f"unknown-{index}"
            slug = f"team-{slug_label}-{index}"
            if team_slug:
                actions.append({
                    "action": "get_team_schedule",
                    "object_type": "team_schedule",
                    "name": slug,
                    "service": "on_call",
                    "method": "GET",
                    "path": f"/api-public/v2/team/{quote(team_slug, safe='')}/oncall/schedule?daysForward={days_forward}",
                    "coverage": "api_validate",
                    "rate_bucket": "default",
                    "writes": False,
                })
                coverage.append(coverage_entry(object_type="team_schedule", name=slug, coverage="api_validate"))
            else:
                coverage.append(coverage_entry(
                    object_type="team_schedule",
                    name=slug,
                    coverage="handoff",
                    notes=(
                        "Team on-call schedule read requires the team's system-generated slug. "
                        "Add `slug:` to the team or `team_slug:` to the schedules entry."
                    ),
                ))
        else:
            user = str(entry.get("user", "")).strip()
            slug = f"user-{slugify(user)}-{index}"
            actions.append({
                "action": "get_user_schedule",
                "object_type": "user_schedule",
                "name": slug,
                "service": "on_call",
                "method": "GET",
                "path": f"/api-public/v2/user/{quote(user, safe='')}/oncall/schedule",
                "coverage": "api_validate",
                "rate_bucket": "default",
                "writes": False,
            })
            coverage.append(coverage_entry(object_type="user_schedule", name=slug, coverage="api_validate"))
    return coverage, actions


def render_rest_alerts(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("rest_alerts", []), "rest_alerts")):
        name = str(entry.get("alert_name", f"alert-{index}"))
        slug = slugify(name)
        payload = build_rest_alert_payload(entry)
        write_payload(output_dir, "rest_alerts", slug, payload)
        coverage.append(coverage_entry(
            object_type="rest_alert",
            name=name,
            coverage="api_apply",
            extra={"message_type": payload.get("message_type"), "entity_id": payload.get("entity_id")},
            notes="Sent through the REST endpoint with --send-alert.",
        ))
    return coverage, actions


def build_rest_alert_payload(entry: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in entry.items():
        if key in {"alert_name", "annotations"}:
            continue
        payload[key] = value
    for ann in as_list(entry.get("annotations", []), "rest_alerts[].annotations"):
        ann_obj = mapping_item(ann, "rest_alerts[].annotations[]")
        kind = str(ann_obj.get("kind", "")).strip().lower()
        title = str(ann_obj.get("title", "")).strip()
        value = ann_obj.get("value", "")
        prefix = {"url": "vo_annotate.u.", "note": "vo_annotate.s.", "image": "vo_annotate.i."}[kind]
        payload[f"{prefix}{title}"] = value
    return payload


def render_email_alerts(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("email_alerts", []), "email_alerts")):
        name = str(entry.get("integration_name", f"email-alert-{index}"))
        coverage.append(coverage_entry(
            object_type="email_alert",
            name=name,
            coverage="handoff",
            notes="Generic Email Endpoint Integration; configured in UI then routed to the team.",
            extra={"routing_key": entry.get("routing_key")},
        ))
    return coverage, []


def render_integrations(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("integrations", []), "integrations")):
        kind = str(entry.get("kind", "")).strip()
        name = str(entry.get("name", f"integration-{index}"))
        coverage.append(coverage_entry(
            object_type=f"integration_{kind}" if kind else "integration",
            name=name,
            coverage="handoff",
            notes="UI-only third-party integration; rendered as a deeplink + checklist.",
        ))
    return coverage, []


def render_sso(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    sso = spec.get("sso") or {}
    if not isinstance(sso, dict) or not sso:
        return coverage, []
    coverage.append(coverage_entry(
        object_type="sso",
        name=str(sso.get("kind", "saml")),
        coverage="handoff",
        notes="SAML SSO is activated by Splunk On-Call Support; the skill renders the support ticket template.",
    ))
    return coverage, []


def render_reports(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("reports", []), "reports")):
        kind = str(entry.get("kind", "")).strip()
        coverage.append(coverage_entry(
            object_type=f"report_{kind}",
            name=f"{kind}-{index}",
            coverage="deeplink",
            notes="Rendered as a deeplink; no public API write surface.",
        ))
    return coverage, []


def render_calendars(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    for index, entry in enumerate(as_list(spec.get("calendars", []), "calendars")):
        kind = str(entry.get("kind", "team"))
        coverage.append(coverage_entry(
            object_type=f"calendar_{kind}",
            name=f"calendar-{kind}-{index}",
            coverage="handoff",
            notes="iCal feed export is configured in the On-Call UI.",
        ))
    return coverage, []


def render_mobile(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    for entry in as_list(spec.get("mobile", []), "mobile"):
        user = str(entry.get("user", ""))
        platform = str(entry.get("platform", ""))
        coverage.append(coverage_entry(
            object_type="mobile_setup",
            name=f"{user}-{platform}",
            coverage="handoff",
            notes="Per-user mobile-app checklist; iOS Critical Alerts; Android 13+ required.",
        ))
    return coverage, []


def render_recovery_polling(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    rp = spec.get("recovery_polling") or {}
    if not isinstance(rp, dict) or not rp:
        return coverage, []
    if not rp.get("enabled", False):
        coverage.append(coverage_entry(
            object_type="recovery_polling",
            name="victorops-alert-recovery",
            coverage="install_apply",
            notes="Recovery polling is disabled.",
            extra={"enabled": False},
        ))
        return coverage, []
    write_payload(output_dir, "recovery_polling", "victorops-alert-recovery", rp)
    coverage.append(coverage_entry(
        object_type="recovery_polling",
        name="victorops-alert-recovery",
        coverage="install_apply",
        notes="Toggles enable_recovery + the victorops-alert-recovery scheduled saved search.",
        extra={"enabled": True},
    ))
    return coverage, []


def render_splunk_side(spec: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    splunk_side = spec.get("splunk_side") or {}
    if not isinstance(splunk_side, dict) or not splunk_side:
        return coverage, []
    write_payload(output_dir, "splunk_side", "splunk-side", splunk_side)

    if splunk_side.get("alert_action_app"):
        coverage.append(coverage_entry(
            object_type="splunk_side_alert_action",
            name="victorops_app",
            coverage="install_apply",
            notes="Splunkbase 3546 alert-action app; install on search head or SHC deployer.",
            extra={"splunkbase_id": 3546},
        ))
    if splunk_side.get("add_on"):
        coverage.append(coverage_entry(
            object_type="splunk_side_add_on",
            name="TA-splunk-add-on-for-victorops",
            coverage="install_apply",
            notes="Splunkbase 4886 Add-on; install on heavy forwarder; pre-create 4 indexes.",
            extra={"splunkbase_id": 4886},
        ))
    if splunk_side.get("soar_connector"):
        coverage.append(coverage_entry(
            object_type="splunk_side_soar_connector",
            name="splunkoncall",
            coverage="install_apply",
            notes="Splunkbase 5863 SOAR connector; FIPS-compliant.",
            extra={"splunkbase_id": 5863},
        ))
    if splunk_side.get("itsi", {}).get("enabled"):
        coverage.append(coverage_entry(
            object_type="splunk_side_itsi",
            name="itsi-neap",
            coverage="install_apply",
            notes="ITSI Notable Event Action JSON for Splunk On-Call.",
        ))
    if splunk_side.get("enterprise_security", {}).get("adaptive_response"):
        coverage.append(coverage_entry(
            object_type="splunk_side_es_adaptive_response",
            name="es-adaptive-response",
            coverage="install_apply",
            notes="Splunk ES Adaptive Response action backed by [victorops].",
        ))
    if splunk_side.get("observability_handoff"):
        coverage.append(coverage_entry(
            object_type="splunk_side_observability_handoff",
            name="observability-detector-recipient",
            coverage="deeplink",
            notes="Adds On-Call as a Splunk Observability detector recipient (deeplink).",
        ))
    return coverage, []


SECTION_RENDERERS = (
    render_users,
    render_teams,
    render_rotations,
    render_escalation_policies,
    render_routing_keys,
    render_paging_policies,
    render_scheduled_overrides,
    render_alert_rules,
    render_maintenance_mode,
    render_incidents,
    render_notes,
    render_chat_messages,
    render_stakeholder_messages,
    render_webhooks,
    render_reporting,
    render_schedules,
    render_rest_alerts,
    render_email_alerts,
    render_integrations,
    render_sso,
    render_reports,
    render_calendars,
    render_mobile,
    render_recovery_polling,
    render_splunk_side,
)


def build_handoff_md(spec: dict[str, Any], coverage: list[dict[str, Any]]) -> str:
    lines: list[str] = ["# Splunk On-Call apply handoff", ""]
    counts: Counter[str] = Counter(item["coverage"] for item in coverage)
    lines.append(
        f"Coverage summary: api_apply={counts.get('api_apply', 0)} "
        f"api_validate={counts.get('api_validate', 0)} "
        f"deeplink={counts.get('deeplink', 0)} handoff={counts.get('handoff', 0)} "
        f"install_apply={counts.get('install_apply', 0)}."
    )
    lines.append("")
    org = spec.get("org_slug")
    if org:
        lines.append(f"Organization slug: `{org}`.")
        lines.append("")
    lines.append("## Action checklist")
    lines.append("")
    for item in coverage:
        marker = {
            "api_apply": "[apply]",
            "api_validate": "[validate]",
            "deeplink": "[deeplink]",
            "handoff": "[handoff]",
            "install_apply": "[install]",
        }.get(item["coverage"], "[?]")
        notes = f" — {item['notes']}" if item.get("notes") else ""
        lines.append(f"- {marker} {item['object_type']} `{item['name']}`{notes}")
    lines.append("")
    lines.append(
        "Run `--apply` only after confirming `apply-plan.json` matches the intended changes."
    )
    return "\n".join(lines) + "\n"


def build_deeplinks(spec: dict[str, Any], coverage: list[dict[str, Any]]) -> dict[str, Any]:
    org = str(spec.get("org_slug") or "")
    portal = "https://portal.victorops.com"
    deeplinks: list[dict[str, Any]] = []
    for item in coverage:
        if item["coverage"] not in {"deeplink", "handoff"}:
            continue
        otype = item["object_type"]
        name = item["name"]
        url = portal
        if otype.startswith("report_post_incident_review"):
            url = f"{portal}/client/{quote(org)}/reports"
        elif otype.startswith("report_team_dashboard"):
            url = f"{portal}/client/{quote(org)}/teams"
        elif otype.startswith("report_"):
            url = f"{portal}/client/{quote(org)}/reports"
        elif otype.startswith("calendar_"):
            url = f"{portal}/client/{quote(org)}/oncall/calendar-export"
        elif otype.startswith("integration_"):
            url = f"{portal}/client/{quote(org)}/integrations"
        elif otype == "sso":
            url = f"{portal}/auth/sso/<companyId>"
        elif otype == "splunk_side_observability_handoff":
            url = "https://app.us0.signalfx.com/#/me"
        elif otype == "webhook":
            url = f"{portal}/client/{quote(org)}/integrations/outgoing-webhooks"
        elif otype == "mobile_setup":
            url = "https://help.splunk.com/en/splunk-observability-cloud/splunk-on-call/mobile-app/splunk-on-call-mobile-app-settings"
        elif otype == "email_alert":
            url = f"{portal}/client/{quote(org)}/integrations/email-generic"
        deeplinks.append({
            "object_type": otype,
            "name": name,
            "url": url,
        })
    return {
        "api_version": API_VERSION,
        "org_slug": org,
        "deeplinks": deeplinks,
    }


def build_coverage_report(
    spec: dict[str, Any], coverage: list[dict[str, Any]]
) -> dict[str, Any]:
    summary: Counter[str] = Counter(item["coverage"] for item in coverage)
    api_apply = summary.get("api_apply", 0)
    api_validate = summary.get("api_validate", 0)
    estimated_total = api_apply + api_validate
    rough_minutes = max(1, int(estimated_total / 60) + 1)

    fedramp_warning = ""
    if any(
        str(value).lower() in {"fedramp", "il5", "govcloud"}
        for value in (spec.get("compliance"), spec.get("environment"), spec.get("notes"))
        if isinstance(value, str)
    ):
        fedramp_warning = (
            "Splunk Cloud Platform is FedRAMP Moderate and IL5 provisionally authorized, "
            "but Splunk On-Call is not separately listed in the public FedRAMP/IL5 docs as of this skill's authoring."
        )

    return {
        "api_version": API_VERSION,
        "org_slug": spec.get("org_slug"),
        "objects": coverage,
        "summary": {
            "api_apply": summary.get("api_apply", 0),
            "api_validate": summary.get("api_validate", 0),
            "deeplink": summary.get("deeplink", 0),
            "handoff": summary.get("handoff", 0),
            "install_apply": summary.get("install_apply", 0),
            "total": len(coverage),
        },
        "rate_limits": {
            **RATE_LIMITS,
            "monthly_quota_warning": (
                "Splunk On-Call may impose a per-account monthly call quota. "
                "Confirm in the org's portal."
            ),
        },
        "daily_budget": {
            "estimated_apply_calls": api_apply,
            "estimated_validate_calls": api_validate,
            "rough_minutes_to_complete": rough_minutes,
        },
        "fedramp_warning": fedramp_warning,
    }


def build_apply_plan(
    spec: dict[str, Any], actions: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "mode": "splunk-oncall",
        "org_slug": spec.get("org_slug"),
        "api_base": spec.get("api_base", "https://api.victorops.com"),
        "actions": actions,
    }


def render_spec(spec: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    validate_spec(spec)
    reset_output_dir(output_dir)
    coverage_objects: list[dict[str, Any]] = []
    apply_actions: list[dict[str, Any]] = []
    for fn in SECTION_RENDERERS:
        section_coverage, section_actions = fn(spec, output_dir)
        coverage_objects.extend(section_coverage)
        apply_actions.extend(section_actions)

    coverage_report = build_coverage_report(spec, coverage_objects)
    apply_plan = build_apply_plan(spec, apply_actions)
    deeplinks = build_deeplinks(spec, coverage_objects)
    handoff = build_handoff_md(spec, coverage_objects)

    write_json(output_dir / "coverage-report.json", coverage_report)
    write_json(output_dir / "apply-plan.json", apply_plan)
    write_json(output_dir / "deeplinks.json", deeplinks)
    (output_dir / "handoff.md").write_text(handoff, encoding="utf-8")
    write_json(output_dir / "metadata.json", {
        "api_version": API_VERSION,
        "mode": "splunk-oncall",
        "sections": {section: len(spec.get(section, []) or []) for section in SECTIONS},
    })
    return coverage_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        spec = load_structured(args.spec)
        result = render_spec(spec, args.output_dir)
    except (OSError, SpecError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({
            "ok": True,
            "output_dir": str(args.output_dir),
            "summary": result["summary"],
        }, indent=2, sort_keys=True))
    else:
        print(f"Rendered Splunk On-Call assets to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
