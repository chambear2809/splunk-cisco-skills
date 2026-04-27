from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .common import ValidationError, bool_from_any, canonicalize, compact, deep_merge, listify, subset_matches


DEFAULT_TEAM = "default_itsi_security_group"


@dataclass(frozen=True)
class ConfigObjectSection:
    section: str
    object_type: str
    interface: str = "itoa"
    label: str | None = None
    default_sec_grp: bool = True
    default_description: bool = True
    set_object_type: bool = True
    identity_field: str = "title"

    @property
    def display_label(self) -> str:
        return self.label or self.object_type


PRE_SERVICE_CONFIG_SECTIONS = (
    ConfigObjectSection("teams", "team", default_sec_grp=False),
    ConfigObjectSection("entity_types", "entity_type"),
    ConfigObjectSection("entity_management_policies", "entity_management_policies", label="entity_management_policy"),
    ConfigObjectSection("entity_management_rules", "entity_management_rules", label="entity_management_rule"),
    ConfigObjectSection("data_integration_templates", "data_integration_template"),
    ConfigObjectSection("kpi_base_searches", "kpi_base_search"),
    ConfigObjectSection("kpi_threshold_templates", "kpi_threshold_template"),
    ConfigObjectSection("kpi_templates", "kpi_template"),
    ConfigObjectSection("custom_threshold_windows", "custom_threshold_windows"),
    ConfigObjectSection("custom_content_packs", "content_pack", interface="content_pack_authorship", label="custom_content_pack", default_sec_grp=False),
    ConfigObjectSection("service_templates", "base_service_template", label="service_template"),
)

POST_SERVICE_CONFIG_SECTIONS = (
    ConfigObjectSection("event_management_states", "event_management_state"),
    ConfigObjectSection("correlation_searches", "correlation_search", interface="event_management", identity_field="name"),
    ConfigObjectSection("notable_event_email_templates", "notable_event_email_template", interface="event_management"),
    ConfigObjectSection("maintenance_windows", "maintenance_calendar", interface="maintenance"),
    ConfigObjectSection("backup_restore_jobs", "backup_restore", interface="backup_restore", label="backup_restore_job", default_sec_grp=False),
    ConfigObjectSection("deep_dives", "deep_dive"),
    ConfigObjectSection("glass_tables", "glass_table"),
    ConfigObjectSection(
        "glass_table_icons",
        "icon",
        interface="icon_collection",
        label="glass_table_icon",
        default_sec_grp=False,
        default_description=False,
        set_object_type=False,
    ),
    ConfigObjectSection("home_views", "home_view"),
    ConfigObjectSection("kpi_entity_thresholds", "kpi_entity_threshold"),
    ConfigObjectSection("refresh_queue_jobs", "refresh_queue_job"),
    ConfigObjectSection("sandboxes", "sandbox"),
    ConfigObjectSection("sandbox_services", "sandbox_service"),
    ConfigObjectSection("sandbox_sync_logs", "sandbox_sync_log"),
    ConfigObjectSection("upgrade_readiness_prechecks", "upgrade_readiness_prechecks", label="upgrade_readiness_precheck"),
    ConfigObjectSection("summarizations", "summarization"),
    ConfigObjectSection("summarization_feedback", "summarization_feedback"),
    ConfigObjectSection("user_preferences", "user_preference", default_sec_grp=False),
)
ALL_CONFIG_SECTIONS = PRE_SERVICE_CONFIG_SECTIONS + POST_SERVICE_CONFIG_SECTIONS
CONFIG_SECTIONS_BY_SECTION = {section.section: section for section in ALL_CONFIG_SECTIONS}
CONFIG_SECTIONS_BY_OBJECT_TYPE = {section.object_type: section for section in ALL_CONFIG_SECTIONS}
HIGH_RISK_CLEANUP_SECTIONS = {
    "custom_content_packs": "content-pack authorship cleanup can remove packaged authoring state.",
    "glass_table_icons": "icon collection deletes remove shared visual assets.",
    "kpi_entity_thresholds": "KPI entity threshold deletes can remove per-entity alert tuning.",
}
CLEANUP_CONFIRMATION = "DELETE_UNMANAGED_ITSI_OBJECTS"
HIGH_RISK_CLEANUP_CONFIRMATION = "DELETE_HIGH_RISK_ITSI_OBJECTS"
PROTECTED_CLEANUP_KEYS = {
    "default_itsi_security_group",
    "itsi_example_kpi_collection",
    "ItsiDefaultScheduledBackup",
}
PROTECTED_CLEANUP_KEY_PREFIXES = (
    "da-itsi-",
    "kpi_threshold_template_",
    "sai-",
    "vmware_",
)
PROTECTED_CLEANUP_TITLES_BY_SECTION = {
    "backup_restore_jobs": {"Default Scheduled Backup"},
    "correlation_searches": {
        "BMC Remedy Bidirectional Ticketing",
        "Bidirectional Ticketing",
        "High Scale EA Backfill",
        "Jira Bidirectional Ticketing",
        "Monitor Critical Services Based on Health Score",
        "Normalized Correlation Search",
        "SNMP Traps",
        "Splunk App for Infrastructure Alerts",
    },
    "entity_types": {
        "*nix",
        "Kubernetes Node",
        "Kubernetes Pod",
        "Unix/Linux Add-on",
        "Windows",
    },
    "kpi_templates": {"Templates"},
    "teams": {"Global"},
}
PROTECTED_CLEANUP_TITLE_PREFIXES = (
    "DA-ITSI-",
    "SAI:",
    "Splunk AppDynamics ",
    "VMware ",
)

CONFIG_OBJECT_RESERVED_KEYS = {"payload", "title", "description", "sec_grp", "object_type", "allow_restore"}
ENTITY_RESERVED_KEYS = {
    "payload",
    "title",
    "description",
    "sec_grp",
    "object_type",
    "identifier_fields",
    "informational_fields",
    "entity_type_ids",
    "entity_type_titles",
}
SERVICE_RESERVED_KEYS = {
    "payload",
    "title",
    "description",
    "sec_grp",
    "object_type",
    "enabled",
    "entity_rules",
    "service_tags",
    "kpis",
    "depends_on",
    "service_template",
    "from_template",
}
KPI_RESERVED_KEYS = {"payload", "thresholds", "aggregate_thresholds", "entity_thresholds", "enabled"}
NEAP_RESERVED_KEYS = {"payload", "title", "description", "sec_grp", "object_type"}
NEAP_SECTION = ConfigObjectSection(
    "neaps",
    "notable_event_aggregation_policy",
    interface="event_management",
)


@dataclass
class ChangeRecord:
    object_type: str
    title: str
    action: str
    status: str
    detail: str
    key: str | None = None


@dataclass
class NativeResult:
    mode: str
    changes: list[ChangeRecord] = field(default_factory=list)
    validations: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    service_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    object_snapshots: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    exports: dict[str, Any] = field(default_factory=dict)
    inventory: dict[str, Any] = field(default_factory=dict)
    prune_plan: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return any(change.status == "error" for change in self.changes) or any(
            item.get("status") == "fail" for item in self.validations
        ) or any(
            item.get("status") == "error" for item in self.diagnostics
        )

    def summary(self) -> dict[str, int]:
        counts = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
        for change in self.changes:
            if change.status == "error":
                counts["failed"] += 1
            elif change.action == "create":
                counts["created"] += 1
            elif change.action == "update":
                counts["updated"] += 1
            elif change.action == "noop":
                counts["unchanged"] += 1
        return counts


def _field_map(entries: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {
        "fields": [entry["field"] for entry in entries],
        "values": [entry["value"] for entry in entries],
    }


def _schema_overlay(object_spec: dict[str, Any], reserved_keys: set[str], label: str = "payload") -> dict[str, Any]:
    overlay = {
        key: deepcopy(value)
        for key, value in object_spec.items()
        if key not in reserved_keys
    }
    payload = object_spec.get("payload") or {}
    if not isinstance(payload, dict):
        raise ValidationError(f"{label} must be a mapping when provided.")
    return deep_merge(overlay, payload)


def _normalize_entity(
    entity_spec: dict[str, Any],
    default_team: str,
    existing: dict[str, Any] | None = None,
    entity_types_by_title: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = deepcopy(existing or {})
    payload["object_type"] = "entity"
    payload["title"] = entity_spec["title"]
    if existing is None or "description" in entity_spec:
        payload["description"] = entity_spec.get("description", "")
    if existing is None or "sec_grp" in entity_spec:
        payload["sec_grp"] = entity_spec.get("sec_grp", default_team)
    identifiers = listify(entity_spec.get("identifier_fields"))
    informational = listify(entity_spec.get("informational_fields"))
    if identifiers:
        payload["identifier"] = _field_map(identifiers)
    if informational:
        payload["informational"] = _field_map(informational)
    if "entity_type_ids" in entity_spec:
        payload["entity_type_ids"] = list(entity_spec.get("entity_type_ids") or [])
    if "entity_type_titles" in entity_spec:
        entity_types_by_title = entity_types_by_title or {}
        entity_type_ids = list(payload.get("entity_type_ids") or [])
        for title in listify(entity_spec.get("entity_type_titles")):
            normalized_title = str(title or "").strip()
            if not normalized_title:
                raise ValidationError(f"Entity '{entity_spec['title']}' has a blank entity_type_titles entry.")
            entity_type = entity_types_by_title.get(normalized_title)
            if not entity_type or not entity_type.get("_key"):
                raise ValidationError(f"Entity '{entity_spec['title']}' references unknown entity type '{normalized_title}'.")
            entity_type_key = str(entity_type["_key"])
            if entity_type_key not in entity_type_ids:
                entity_type_ids.append(entity_type_key)
        payload["entity_type_ids"] = entity_type_ids
    payload = deep_merge(payload, _schema_overlay(entity_spec, ENTITY_RESERVED_KEYS))
    return compact(payload)


def _normalize_threshold_block(block: dict[str, Any], metric_field: str | None) -> dict[str, Any]:
    normalized = deepcopy(block)
    normalized.setdefault("baseSeverityLabel", "normal")
    normalized.setdefault("baseSeverityValue", 2)
    if metric_field and "metricField" not in normalized:
        normalized["metricField"] = metric_field
    if "thresholdLevels" in normalized:
        normalized["thresholdLevels"] = sorted(
            list(normalized.get("thresholdLevels") or []), key=lambda item: item.get("thresholdValue", 0)
        )
    return compact(normalized)


def _existing_kpis_by_title(service_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {kpi.get("title"): deepcopy(kpi) for kpi in listify(service_payload.get("kpis")) if kpi.get("title")}


def _stable_kpi_key(service_title: str | None, kpi_title: str) -> str:
    seed = f"{service_title or 'service'}::{kpi_title}".encode("utf-8")
    return hashlib.sha1(seed).hexdigest()[:24]


def _normalize_kpi(
    kpi_spec: dict[str, Any],
    existing: dict[str, Any] | None = None,
    service_title: str | None = None,
) -> dict[str, Any]:
    payload = deepcopy(existing or {})
    updates = {
        "title": kpi_spec["title"],
        "description": kpi_spec.get("description", ""),
        "type": kpi_spec.get("type", "kpi_primary"),
        "search": kpi_spec.get("search"),
        "base_search": kpi_spec.get("base_search") or kpi_spec.get("search"),
        "search_type": kpi_spec.get("search_type"),
        "threshold_field": kpi_spec.get("threshold_field"),
        "aggregate_statop": kpi_spec.get("aggregate_statop"),
        "entity_statop": kpi_spec.get("entity_statop"),
        "entity_id_fields": kpi_spec.get("entity_id_fields"),
        "entity_breakdown_id_field": kpi_spec.get("entity_breakdown_id_field"),
        "search_alert_earliest": kpi_spec.get("search_alert_earliest", "5"),
        "search_alert_latest": kpi_spec.get("search_alert_latest"),
        "threshold_direction": kpi_spec.get("threshold_direction"),
        "urgency": kpi_spec.get("urgency", kpi_spec.get("importance", "5")),
        "unit": kpi_spec.get("unit"),
        "importance": kpi_spec.get("importance"),
        "alert_on": kpi_spec.get("alert_on", "aggregate"),
        "alert_period": kpi_spec.get("alert_period", "5"),
        "alert_lag": kpi_spec.get("alert_lag", "30"),
        "kpi_threshold_template_id": kpi_spec.get("kpi_threshold_template_id"),
        "kpi_base_search_id": kpi_spec.get("kpi_base_search_id"),
        "base_search_id": kpi_spec.get("base_search_id"),
        "isadhoc": kpi_spec.get("isadhoc"),
        "is_service_entity_filter": kpi_spec.get("is_service_entity_filter"),
        "is_entity_breakdown": kpi_spec.get("is_entity_breakdown"),
        "adaptive_thresholding": kpi_spec.get("adaptive_thresholding"),
        "anomaly_detection": kpi_spec.get("anomaly_detection"),
    }
    if (
        updates["base_search"]
        and not updates["search_type"]
        and not kpi_spec.get("base_search_id")
        and not kpi_spec.get("kpi_base_search_id")
    ):
        updates["search_type"] = "adhoc"
    payload.update({key: value for key, value in updates.items() if value is not None})
    if "enabled" in kpi_spec:
        payload["enabled"] = bool_from_any(kpi_spec.get("enabled"))
    thresholds = kpi_spec.get("thresholds", {})
    aggregate = kpi_spec.get("aggregate_thresholds") or thresholds.get("aggregate")
    entity = kpi_spec.get("entity_thresholds") or thresholds.get("entity")
    if aggregate:
        payload["aggregate_thresholds"] = _normalize_threshold_block(aggregate, kpi_spec.get("threshold_field"))
    if entity:
        payload["entity_thresholds"] = _normalize_threshold_block(entity, kpi_spec.get("threshold_field"))
    payload = deep_merge(payload, _schema_overlay(kpi_spec, KPI_RESERVED_KEYS, label="kpi payload"))
    if existing is None and not payload.get("_key"):
        payload["_key"] = _stable_kpi_key(service_title, payload["title"])
    return compact(payload)


def _normalize_service(service_spec: dict[str, Any], existing: dict[str, Any] | None, default_team: str) -> dict[str, Any]:
    payload = deepcopy(existing or {})
    payload["object_type"] = "service"
    payload["title"] = service_spec["title"]
    if existing is None or "description" in service_spec:
        payload["description"] = service_spec.get("description", "")
    if existing is None or "sec_grp" in service_spec:
        payload["sec_grp"] = service_spec.get("sec_grp", default_team)
    if "enabled" in service_spec:
        payload["enabled"] = bool_from_any(service_spec.get("enabled"))
    if "entity_rules" in service_spec:
        payload["entity_rules"] = deepcopy(service_spec.get("entity_rules") or [])
    if "service_tags" in service_spec:
        payload["service_tags"] = deepcopy(service_spec.get("service_tags") or {})
    existing_kpis = _existing_kpis_by_title(existing or {})
    desired_kpis: list[dict[str, Any]] = []
    desired_titles: set[str] = set()
    for kpi_spec in listify(service_spec.get("kpis")):
        desired_titles.add(kpi_spec["title"])
        desired_kpis.append(_normalize_kpi(kpi_spec, existing_kpis.get(kpi_spec["title"]), service_spec["title"]))
    for title, kpi in existing_kpis.items():
        if title not in desired_titles:
            desired_kpis.append(kpi)
    if desired_kpis:
        payload["kpis"] = desired_kpis
    payload = deep_merge(payload, _schema_overlay(service_spec, SERVICE_RESERVED_KEYS))
    return compact(payload)


def _normalize_neap(neap_spec: dict[str, Any], existing: dict[str, Any] | None, default_team: str) -> dict[str, Any]:
    payload = deepcopy(existing or {})
    payload["object_type"] = "notable_event_aggregation_policy"
    payload["title"] = neap_spec["title"]
    if existing is None or "description" in neap_spec:
        payload["description"] = neap_spec.get("description", "")
    if existing is None or "sec_grp" in neap_spec:
        payload["sec_grp"] = neap_spec.get("sec_grp", default_team)
    overlay = {key: deepcopy(value) for key, value in neap_spec.items() if key not in NEAP_RESERVED_KEYS}
    payload = deep_merge(payload, overlay)
    payload = deep_merge(payload, neap_spec.get("payload", {}))
    return compact(payload)


def _config_object_title(object_spec: dict[str, Any], section: ConfigObjectSection) -> str:
    title = str(object_spec.get("title") or "").strip()
    if not title and isinstance(object_spec.get("payload"), dict):
        title = str(object_spec["payload"].get(section.identity_field) or object_spec["payload"].get("title") or "").strip()
    if not title and section.identity_field in object_spec:
        title = str(object_spec.get(section.identity_field) or "").strip()
    if not title:
        raise ValidationError(f"{section.section} entries must define title.")
    return title


def _config_object_overlay(object_spec: dict[str, Any]) -> dict[str, Any]:
    return _schema_overlay(object_spec, CONFIG_OBJECT_RESERVED_KEYS)


def _normalize_config_object(
    object_spec: dict[str, Any],
    section: ConfigObjectSection,
    existing: dict[str, Any] | None,
    default_team: str,
) -> dict[str, Any]:
    title = _config_object_title(object_spec, section)
    payload = deepcopy(existing or {})
    if section.set_object_type:
        payload["object_type"] = section.object_type
    payload[section.identity_field] = title
    if section.default_description and (existing is None or "description" in object_spec):
        payload["description"] = object_spec.get("description", "")
    if section.default_sec_grp and (existing is None or "sec_grp" in object_spec):
        payload["sec_grp"] = object_spec.get("sec_grp", default_team)
    payload = deep_merge(payload, _config_object_overlay(object_spec))
    return compact(payload)


def _expected_config_object(object_spec: dict[str, Any], section: ConfigObjectSection, default_team: str) -> dict[str, Any]:
    expected: dict[str, Any] = {section.identity_field: _config_object_title(object_spec, section)}
    if section.default_description and "description" in object_spec:
        expected["description"] = object_spec.get("description", "")
    if section.default_sec_grp and "sec_grp" in object_spec:
        expected["sec_grp"] = object_spec.get("sec_grp", default_team)
    expected = deep_merge(expected, _config_object_overlay(object_spec))
    return compact(expected)


def _compare_config_object(
    existing: dict[str, Any],
    object_spec: dict[str, Any],
    section: ConfigObjectSection,
    default_team: str,
) -> bool:
    return subset_matches(canonicalize(existing), canonicalize(_expected_config_object(object_spec, section, default_team)))


def _apply_preview_config_key(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(payload)
    title = normalized.get("title") or normalized.get("name") or normalized.get("label") or "unknown"
    normalized.setdefault("_key", f"preview-{normalized.get('object_type', 'object')}::{title}")
    return normalized


def _normalize_service_template_ref(value: Any, label: str) -> dict[str, str | None]:
    if isinstance(value, str):
        title = value.strip()
        if not title:
            raise ValidationError(f"{label} must not be blank.")
        return {"title": title, "key": None}
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a string or mapping.")
    key = str(value.get("_key") or value.get("key") or "").strip()
    title = str(value.get("title") or "").strip()
    if not title and not key:
        raise ValidationError(f"{label} must define title or key.")
    return {"title": title or None, "key": key or None}


def _normalize_ref(value: Any, label: str) -> dict[str, str | None]:
    return _normalize_service_template_ref(value, label)


def _unique_nonblank_strings(values: Any, label: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in listify(values):
        item = str(value or "").strip()
        if not item:
            raise ValidationError(f"{label} must not include blank entries.")
        if item not in seen:
            seen.add(item)
            normalized.append(item)
    return normalized


def _nonempty_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValidationError(f"{label} must define a non-empty mapping.")
    return deepcopy(value)


def _first_nonblank_field(mapping: dict[str, Any], keys: tuple[str, ...], label: str) -> str:
    for key in keys:
        value = str(mapping.get(key) or "").strip()
        if value:
            return value
    raise ValidationError(f"{label} must define one of: {', '.join(keys)}.")


def _custom_threshold_window_ref(link_spec: dict[str, Any]) -> Any:
    for key in ("window", "custom_threshold_window"):
        if key in link_spec:
            return link_spec[key]
    ref: dict[str, Any] = {}
    for key in ("window_key", "custom_threshold_window_key", "_key", "key"):
        if link_spec.get(key):
            ref["key"] = link_spec[key]
            break
    for key in ("title", "window_title", "custom_threshold_window_title"):
        if link_spec.get(key):
            ref["title"] = link_spec[key]
            break
    return ref


def _service_link_ref(service_spec: Any, label: str) -> dict[str, str | None]:
    if isinstance(service_spec, str):
        return {"title": service_spec.strip(), "key": None}
    if not isinstance(service_spec, dict):
        raise ValidationError(f"{label} must be a string or mapping.")
    if "service" in service_spec:
        return _normalize_ref(service_spec["service"], label)
    ref: dict[str, Any] = {}
    for key in ("service_key", "_key", "key"):
        if service_spec.get(key):
            ref["key"] = service_spec[key]
            break
    for key in ("title", "service_title"):
        if service_spec.get(key):
            ref["title"] = service_spec[key]
            break
    return _normalize_ref(ref, label)


def _kpi_link_ids(service_spec: dict[str, Any], service: dict[str, Any], label: str) -> list[str]:
    kpi_ids = _unique_nonblank_strings(
        listify(service_spec.get("kpi_ids")) + listify(service_spec.get("kpi_keys")),
        f"{label} kpi_ids",
    )
    kpis_by_title = {kpi.get("title"): kpi for kpi in listify(service.get("kpis")) if kpi.get("title")}
    for kpi_ref in listify(service_spec.get("kpis")):
        if isinstance(kpi_ref, str):
            title = kpi_ref.strip()
            if not title:
                raise ValidationError(f"{label} kpis must not include blank entries.")
            kpi = kpis_by_title.get(title)
            if not kpi:
                raise ValidationError(f"{label} references unknown KPI '{title}'.")
            kpi_key = str(kpi.get("_key") or "").strip()
            if not kpi_key:
                raise ValidationError(f"{label} KPI '{title}' does not have a resolvable _key.")
            if kpi_key not in kpi_ids:
                kpi_ids.append(kpi_key)
            continue
        if not isinstance(kpi_ref, dict):
            raise ValidationError(f"{label} kpis entries must be strings or mappings.")
        kpi_key = str(kpi_ref.get("_key") or kpi_ref.get("key") or kpi_ref.get("kpi_key") or kpi_ref.get("kpi_id") or "").strip()
        if kpi_key:
            if kpi_key not in kpi_ids:
                kpi_ids.append(kpi_key)
            continue
        title = str(kpi_ref.get("title") or "").strip()
        if not title:
            raise ValidationError(f"{label} KPI mapping must define title or key.")
        kpi = kpis_by_title.get(title)
        if not kpi:
            raise ValidationError(f"{label} references unknown KPI '{title}'.")
        resolved_key = str(kpi.get("_key") or "").strip()
        if not resolved_key:
            raise ValidationError(f"{label} KPI '{title}' does not have a resolvable _key.")
        if resolved_key not in kpi_ids:
            kpi_ids.append(resolved_key)
    if not kpi_ids:
        raise ValidationError(f"{label} must define at least one KPI by title or ID.")
    return kpi_ids


def _custom_threshold_link_pairs(response: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for item in listify(response.get("linked_kpis")):
        if not isinstance(item, dict):
            continue
        service_key = str(item.get("service_key") or item.get("service_id") or "").strip()
        kpi_key = str(item.get("kpi_key") or item.get("kpi_id") or "").strip()
        if service_key and kpi_key:
            pairs.add((service_key, kpi_key))
    service_items: list[Any] = []
    for key in ("services", "service_kpis_dict", "linked_services"):
        service_items.extend(listify(response.get(key)))
    for item in service_items:
        if not isinstance(item, dict):
            continue
        service_key = str(item.get("_key") or item.get("service_key") or item.get("service_id") or "").strip()
        if not service_key:
            continue
        for kpi_key in listify(item.get("kpi_ids") or item.get("linked_kpi_ids") or item.get("kpis")):
            if isinstance(kpi_key, dict):
                kpi_key = kpi_key.get("_key") or kpi_key.get("key") or kpi_key.get("kpi_key") or kpi_key.get("kpi_id")
            normalized_kpi_key = str(kpi_key or "").strip()
            if normalized_kpi_key:
                pairs.add((service_key, normalized_kpi_key))
    return pairs


def _custom_threshold_payload_for_pairs(
    services_payload: list[dict[str, Any]],
    pairs: set[tuple[str, str]],
) -> dict[str, Any]:
    services: list[dict[str, Any]] = []
    for service_payload in services_payload:
        service_key = str(service_payload.get("_key") or "").strip()
        kpi_ids = [
            kpi_key
            for kpi_key in service_payload.get("kpi_ids", [])
            if (service_key, kpi_key) in pairs
        ]
        if kpi_ids:
            services.append({"_key": service_key, "kpi_ids": kpi_ids})
    return {"services": services}


def _inventory_titles(items: list[dict[str, Any]]) -> list[str]:
    titles = []
    for item in items:
        title = str(item.get("title") or item.get("name") or item.get("label") or item.get("id") or item.get("_key") or "").strip()
        if title:
            titles.append(title)
    return sorted(titles)


def _uses_preview_key(value: str) -> bool:
    return value.startswith("preview-") or (value.startswith("preview-service::") and "::kpi::" in value)


def _validate_config_object_safety(object_spec: dict[str, Any], section: ConfigObjectSection) -> None:
    if section.section != "backup_restore_jobs":
        return
    payload = object_spec.get("payload") if isinstance(object_spec.get("payload"), dict) else {}
    job_type = str(object_spec.get("job_type") or payload.get("job_type") or "").strip().lower()
    if job_type == "restore" and not bool_from_any(object_spec.get("allow_restore")):
        title = _config_object_title(object_spec, section)
        raise ValidationError(
            f"backup_restore_jobs entry '{title}' is a restore job. Set allow_restore: true only after explicit operator review."
        )


def _compare_entity(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
    return subset_matches(canonicalize(existing), canonicalize(_expected_entity(desired)))


def _expected_entity(desired: dict[str, Any]) -> dict[str, Any]:
    expected = compact(
        {
            "title": desired.get("title"),
            "description": desired.get("description", ""),
            "sec_grp": desired.get("sec_grp"),
            "identifier": desired.get("identifier"),
            "informational": desired.get("informational"),
            "entity_type_ids": desired.get("entity_type_ids"),
        }
    )
    payload_keys = set(desired.keys()) - {"_key", "title", "description", "object_type"}
    for key in payload_keys:
        if key not in expected:
            expected[key] = deepcopy(desired[key])
    return expected


def _desired_kpi_subset(service_spec: dict[str, Any]) -> list[dict[str, Any]]:
    subset: list[dict[str, Any]] = []
    for kpi_spec in listify(service_spec.get("kpis")):
        normalized = _normalize_kpi(kpi_spec, service_title=service_spec.get("title"))
        normalized.pop("_key", None)
        # ITSI rewrites the runtime search fields after save. base_search is the
        # stable field that preserves the user's SPL for ad hoc KPIs.
        normalized.pop("search", None)
        subset.append(compact(normalized))
    return subset


def _compare_service(existing: dict[str, Any], desired: dict[str, Any], service_spec: dict[str, Any]) -> bool:
    return subset_matches(canonicalize(existing), canonicalize(_expected_service(desired, service_spec)))


def _expected_service(desired: dict[str, Any], service_spec: dict[str, Any]) -> dict[str, Any]:
    expected = compact(
        {
            "title": desired.get("title"),
            "description": desired.get("description", ""),
            "sec_grp": desired.get("sec_grp"),
            "enabled": desired.get("enabled"),
            "entity_rules": desired.get("entity_rules"),
            "service_tags": desired.get("service_tags"),
            "kpis": _desired_kpi_subset(service_spec),
        }
    )
    payload_keys = set(desired.keys()) - {"_key", "title", "description", "object_type"}
    for key in payload_keys:
        if key not in expected:
            expected[key] = deepcopy(desired[key])
    return expected


def _compare_neap(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
    return subset_matches(canonicalize(existing), canonicalize(_expected_neap(desired)))


def _expected_neap(desired: dict[str, Any]) -> dict[str, Any]:
    expected = compact(
        {
            "title": desired.get("title"),
            "description": desired.get("description", ""),
            "sec_grp": desired.get("sec_grp"),
        }
    )
    payload_keys = set(desired.keys()) - {"_key", "title", "description", "object_type"}
    for key in payload_keys:
        expected[key] = deepcopy(desired[key])
    return expected


def _diff_subset(actual: Any, expected: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [{"path": path or "$", "expected": expected, "actual": actual}]
        diffs: list[dict[str, Any]] = []
        for key, value in expected.items():
            child_path = f"{path}.{key}" if path else key
            if key not in actual:
                diffs.append({"path": child_path, "expected": value, "actual": None})
                continue
            diffs.extend(_diff_subset(actual[key], value, child_path))
        return diffs
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [{"path": path or "$", "expected": expected, "actual": actual}]
        remaining = list(actual)
        diffs = []
        for index, expected_item in enumerate(expected):
            match_index = next(
                (candidate_index for candidate_index, actual_item in enumerate(remaining) if subset_matches(actual_item, expected_item)),
                None,
            )
            if match_index is None:
                diffs.append({"path": f"{path}[{index}]", "expected": expected_item, "actual": None})
            else:
                remaining.pop(match_index)
        return diffs
    if not subset_matches(actual, expected):
        return [{"path": path or "$", "expected": expected, "actual": actual}]
    return []


def _clean_export_payload(payload: dict[str, Any]) -> dict[str, Any]:
    volatile_keys = {
        "_key",
        "acl",
        "eai:acl.app",
        "eai:acl.owner",
        "eai:acl.sharing",
        "eai:appName",
        "eai:userName",
        "mod_time",
        "updated_at",
    }
    def clean_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: clean_value(child)
                for key, child in value.items()
                if key not in volatile_keys and child is not None
            }
        if isinstance(value, list):
            return [clean_value(item) for item in value if item is not None]
        return deepcopy(value)

    return {
        key: clean_value(value)
        for key, value in payload.items()
        if key not in volatile_keys and value is not None
    }


def _export_object_spec(payload: dict[str, Any], identity_field: str = "title") -> dict[str, Any]:
    exported = _clean_export_payload(payload)
    title = str(exported.get(identity_field) or exported.get("title") or exported.get("name") or "").strip()
    for key in ("title", "name"):
        exported.pop(key, None)
    if identity_field != "title":
        exported.pop(identity_field, None)
    spec: dict[str, Any] = {"title": title} if title else {}
    if exported:
        spec["payload"] = exported
    return spec


def _search_preflight_warnings(spec: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for service_spec in listify(spec.get("services")):
        service_title = str(service_spec.get("title") or "<unknown>")
        for kpi_spec in listify(service_spec.get("kpis")):
            title = str(kpi_spec.get("title") or "<unknown>")
            search = str(kpi_spec.get("search") or "")
            if not search:
                continue
            if not re.search(r"(?i)\bindex\s*=", search) and not re.search(r"(?i)\bindex\s+in\s*\(", search):
                warnings.append(
                    {
                        "status": "warn",
                        "object_type": "kpi_search",
                        "title": f"{service_title} / {title}",
                        "message": "KPI search does not explicitly constrain index=; preview/apply will not fail, but live performance and correctness should be reviewed.",
                    }
                )
            threshold_field = str(kpi_spec.get("threshold_field") or "").strip()
            if threshold_field and threshold_field not in search:
                warnings.append(
                    {
                        "status": "warn",
                        "object_type": "kpi_search",
                        "title": f"{service_title} / {title}",
                        "message": f"KPI threshold_field '{threshold_field}' is not visibly produced by the search string.",
                    }
                )
            if bool_from_any(kpi_spec.get("is_entity_breakdown")) and not (
                kpi_spec.get("entity_id_fields") or kpi_spec.get("entity_breakdown_id_field")
            ):
                warnings.append(
                    {
                        "status": "warn",
                        "object_type": "kpi_search",
                        "title": f"{service_title} / {title}",
                        "message": "Entity-breakdown KPI is enabled but no entity ID/breakdown field is declared.",
                    }
                )
    for correlation_spec in listify(spec.get("correlation_searches")):
        title = str(correlation_spec.get("title") or correlation_spec.get("name") or "<unknown>")
        payload = correlation_spec.get("payload") if isinstance(correlation_spec.get("payload"), dict) else {}
        search = str(correlation_spec.get("search") or payload.get("search") or "")
        if search and not re.search(r"(?i)\bindex\s*=", search) and not re.search(r"(?i)\bindex\s+in\s*\(", search):
            warnings.append(
                {
                    "status": "warn",
                    "object_type": "correlation_search",
                    "title": title,
                    "message": "Correlation search does not explicitly constrain index=; review before enabling in production.",
                }
            )
    return warnings


def _drift_diagnostic(object_type: str, title: str, message: str, diffs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "status": "error",
        "object_type": object_type,
        "title": title,
        "message": message,
    }
    if diffs:
        diagnostic["diffs"] = diffs
    return diagnostic


def _neap_is_managed(existing: dict[str, Any]) -> bool:
    return bool(
        existing.get("source_itsi_da")
        or existing.get("managed_by")
        or bool_from_any(existing.get("managed"))
        or bool_from_any(existing.get("is_default"))
    )


def _build_dependency_entry(dependency_spec: Any, services_by_title: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if isinstance(dependency_spec, str):
        dependency_spec = {"service": dependency_spec}
    dependency_title = dependency_spec["service"]
    dependency_service = services_by_title.get(dependency_title)
    if not dependency_service or not dependency_service.get("_key"):
        raise ValidationError(f"Dependency service '{dependency_title}' was not found after the service upsert pass.")
    dependency_kpis = {kpi.get("title"): kpi.get("_key") for kpi in listify(dependency_service.get("kpis")) if kpi.get("title")}
    selected_titles = dependency_spec.get("kpis")
    if selected_titles:
        missing_titles = [title for title in selected_titles if title not in dependency_kpis]
        if missing_titles:
            raise ValidationError(
                f"Dependency service '{dependency_title}' is missing KPI(s): {', '.join(sorted(missing_titles))}."
            )
        selected_kpis = [dependency_kpis[title] for title in selected_titles]
    else:
        selected_kpis = [value for value in dependency_kpis.values() if value]
    return {"service_id": dependency_service["_key"], "kpis_depending_on": selected_kpis}


def _merge_dependencies(
    existing_service: dict[str, Any],
    dependency_specs: list[Any],
    services_by_title: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    current_dependencies = listify(existing_service.get("services_depends_on"))
    merged_dependencies = deepcopy(current_dependencies)
    seen_ids = {dependency.get("service_id"): index for index, dependency in enumerate(current_dependencies)}
    changed = False
    desired_subset: list[dict[str, Any]] = []
    for dependency_spec in dependency_specs:
        dependency_entry = _build_dependency_entry(dependency_spec, services_by_title)
        desired_subset.append(dependency_entry)
        service_id = dependency_entry["service_id"]
        if service_id not in seen_ids:
            merged_dependencies.append(dependency_entry)
            changed = True
            continue
        existing_entry = merged_dependencies[seen_ids[service_id]]
        if canonicalize(existing_entry.get("kpis_depending_on", [])) != canonicalize(dependency_entry["kpis_depending_on"]):
            merged_dependencies[seen_ids[service_id]] = dependency_entry
            changed = True
    payload = deepcopy(existing_service)
    if merged_dependencies:
        payload["services_depends_on"] = merged_dependencies
    if not subset_matches(canonicalize(payload), canonicalize({"services_depends_on": desired_subset})):
        changed = True
    return compact(payload), changed


def _apply_preview_keys(service_payload: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(service_payload)
    payload.setdefault("_key", f"preview-service::{payload.get('title', 'unknown')}")
    updated_kpis = []
    for kpi in listify(payload.get("kpis")):
        normalized = deepcopy(kpi)
        normalized.setdefault("_key", f"{payload['_key']}::kpi::{normalized.get('title', 'unknown')}")
        updated_kpis.append(normalized)
    if updated_kpis:
        payload["kpis"] = updated_kpis
    return payload


def _apply_service_template_snapshot(service_payload: dict[str, Any], template_payload: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(service_payload)
    payload["base_service_template_id"] = template_payload.get("_key")
    if template_payload.get("entity_rules") and not payload.get("entity_rules"):
        payload["entity_rules"] = deepcopy(template_payload["entity_rules"])
    current_kpis = _existing_kpis_by_title(payload)
    for template_kpi in listify(template_payload.get("kpis")):
        title = template_kpi.get("title")
        if title and title not in current_kpis:
            current_kpis[title] = deepcopy(template_kpi)
    if current_kpis:
        payload["kpis"] = list(current_kpis.values())
    return _apply_preview_keys(payload)


class NativeWorkflow:
    def __init__(self, client: Any):
        self.client = client

    def run(self, spec: dict[str, Any], mode: str) -> NativeResult:
        if mode not in {"preview", "apply", "validate", "export", "inventory", "prune-plan", "cleanup-apply"}:
            raise ValidationError(f"Unsupported native mode '{mode}'.")
        if mode == "export":
            return self._export(spec)
        if mode == "inventory":
            return self._inventory(spec)
        if mode == "prune-plan":
            return self._prune_plan(spec)
        if mode == "cleanup-apply":
            return self._cleanup_apply(spec)
        if mode == "validate":
            return self._validate(spec)
        return self._upsert(spec, apply=(mode == "apply"), mode=mode)

    def _list_objects(self, section: ConfigObjectSection) -> list[dict[str, Any]]:
        if hasattr(self.client, "list_objects"):
            try:
                return self.client.list_objects(section.object_type, interface=section.interface)
            except TypeError:
                return self.client.list_objects(section.object_type)
        return []

    @staticmethod
    def _unavailable_section_diagnostic(section: ConfigObjectSection, exc: Exception) -> dict[str, Any]:
        return {
            "status": "warn",
            "object_type": section.display_label,
            "title": section.section,
            "message": f"Could not list {section.section}; this section was skipped: {exc}",
        }

    @staticmethod
    def _is_optional_list_unavailable(exc: Exception) -> bool:
        if not isinstance(exc, ValidationError):
            return False
        message = str(exc)
        return "ITSI REST endpoint is unavailable" in message or "feature is not enabled" in message.lower()

    def _list_objects_best_effort(
        self,
        section: ConfigObjectSection,
        result: NativeResult | None = None,
        unavailable_sections: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            return self._list_objects(section)
        except Exception as exc:
            if not self._is_optional_list_unavailable(exc):
                raise
            skipped = {
                "section": section.section,
                "object_type": section.object_type,
                "interface": section.interface,
                "message": str(exc),
            }
            if unavailable_sections is not None:
                unavailable_sections.append(skipped)
            if result is not None:
                result.diagnostics.append(self._unavailable_section_diagnostic(section, exc))
            return []

    def _add_preflight_diagnostics(self, spec: dict[str, Any], result: NativeResult) -> None:
        result.diagnostics.extend(_search_preflight_warnings(spec))

    def _export(self, spec: dict[str, Any]) -> NativeResult:
        result = NativeResult(mode="export")
        export_options = spec.get("export", {}) if isinstance(spec.get("export"), dict) else {}
        sections = set(listify(export_options.get("sections")))
        exported: dict[str, Any] = {}
        unavailable_sections: list[dict[str, Any]] = []
        for section in ALL_CONFIG_SECTIONS:
            if sections and section.section not in sections and section.object_type not in sections:
                continue
            objects = [
                _export_object_spec(item, section.identity_field)
                for item in self._list_objects_best_effort(section, result, unavailable_sections)
            ]
            objects = [item for item in objects if item.get("title")]
            if objects or bool_from_any(export_options.get("include_empty")):
                exported[section.section] = objects
        if not sections or "entities" in sections or "entity" in sections:
            entities = [_export_object_spec(item) for item in self.client.list_objects("entity")] if hasattr(self.client, "list_objects") else []
            if entities or bool_from_any(export_options.get("include_empty")):
                exported["entities"] = [item for item in entities if item.get("title")]
        services = self.client.list_objects("service") if hasattr(self.client, "list_objects") and (not sections or "services" in sections or "service" in sections) else []
        service_titles_by_key = {str(service.get("_key")): str(service.get("title")) for service in services if service.get("_key") and service.get("title")}
        if services or (not sections and bool_from_any(export_options.get("include_empty"))):
            exported_services: list[dict[str, Any]] = []
            for service in services:
                service_spec = _export_object_spec(service)
                payload = service_spec.setdefault("payload", {})
                if not isinstance(payload, dict):
                    continue
                dependencies = []
                for dependency in listify(service.get("services_depends_on")):
                    service_id = str(dependency.get("service_id") or "").strip() if isinstance(dependency, dict) else ""
                    dependency_title = service_titles_by_key.get(service_id)
                    if not dependency_title:
                        continue
                    entry: dict[str, Any] = {"service": dependency_title}
                    kpi_ids = listify(dependency.get("kpis_depending_on")) if isinstance(dependency, dict) else []
                    if kpi_ids:
                        entry["kpi_ids"] = kpi_ids
                    dependencies.append(entry)
                if dependencies:
                    payload.pop("services_depends_on", None)
                    service_spec["depends_on"] = dependencies
                exported_services.append(service_spec)
            exported["services"] = exported_services
        if not sections or "neaps" in sections or "notable_event_aggregation_policy" in sections:
            neap_objects = self._list_objects(NEAP_SECTION)
            neaps = [_export_object_spec(item) for item in neap_objects]
            if neaps or bool_from_any(export_options.get("include_empty")):
                exported["neaps"] = [item for item in neaps if item.get("title")]
        result.exports = {"native_spec": exported, "unavailable_sections": unavailable_sections}
        result.changes.append(
            ChangeRecord(
                "native_export",
                "live ITSI",
                "export",
                "ok",
                "Exported live ITSI objects into a native spec skeleton.",
            )
        )
        return result

    def _inventory(self, spec: dict[str, Any]) -> NativeResult:
        result = NativeResult(mode="inventory")
        inventory_options = spec.get("inventory", {}) if isinstance(spec.get("inventory"), dict) else {}
        inventory: dict[str, Any] = {"apps": {}, "objects": {}}
        for app in ("SA-ITOA", "itsi", "DA-ITSI-ContentLibrary"):
            if hasattr(self.client, "get_app_version"):
                inventory["apps"][app] = {"version": self.client.get_app_version(app)}
        if hasattr(self.client, "kvstore_status"):
            try:
                inventory["kvstore_status"] = self.client.kvstore_status()
            except Exception as exc:  # read-only report should keep going
                inventory["kvstore_status"] = f"unavailable: {exc}"
        for section in ALL_CONFIG_SECTIONS:
            try:
                objects = self._list_objects(section)
                inventory["objects"][section.section] = {
                    "object_type": section.object_type,
                    "count": len(objects),
                    "titles": sorted(str(item.get(section.identity_field) or item.get("title") or item.get("name")) for item in objects if item.get(section.identity_field) or item.get("title") or item.get("name")),
                }
            except Exception as exc:  # keep inventory best-effort
                inventory["objects"][section.section] = {"object_type": section.object_type, "status": "unavailable", "message": str(exc)}
        for section_name, object_type in (("entities", "entity"), ("services", "service")):
            try:
                objects = self.client.list_objects(object_type) if hasattr(self.client, "list_objects") else []
                inventory["objects"][section_name] = {
                    "object_type": object_type,
                    "count": len(objects),
                    "titles": sorted(str(item.get("title")) for item in objects if item.get("title")),
                }
            except Exception as exc:
                inventory["objects"][section_name] = {"object_type": object_type, "status": "unavailable", "message": str(exc)}
        if hasattr(self.client, "content_pack_catalog"):
            try:
                packs = self.client.content_pack_catalog()
                inventory["content_packs"] = {
                    "count": len(packs),
                    "installed": sorted(str(pack.get("title") or pack.get("id")) for pack in packs if bool_from_any(pack.get("installed"))),
                }
            except Exception as exc:
                inventory["content_packs"] = {"status": "unavailable", "message": str(exc)}
        discovery: dict[str, Any] = {}
        if hasattr(self.client, "itsi_supported_object_types"):
            supported: dict[str, Any] = {}
            for interface in ("itoa", "event_management", "maintenance", "backup_restore"):
                try:
                    items = self.client.itsi_supported_object_types(interface)
                    supported[interface] = {"count": len(items), "titles": _inventory_titles(items)}
                except Exception as exc:
                    supported[interface] = {"status": "unavailable", "message": str(exc)}
            discovery["supported_object_types"] = supported
        if hasattr(self.client, "itsi_alias_list"):
            try:
                aliases = self.client.itsi_alias_list()
                if isinstance(aliases, dict):
                    alias_items = aliases.get("items") or aliases.get("aliases") or aliases.get("fields") or []
                    discovery["aliases"] = {
                        "count": len(alias_items) if isinstance(alias_items, list) else len(aliases),
                        "fields": sorted(str(item) for item in alias_items) if isinstance(alias_items, list) else sorted(str(key) for key in aliases),
                    }
                else:
                    discovery["aliases"] = {"count": 0, "fields": []}
            except Exception as exc:
                discovery["aliases"] = {"status": "unavailable", "message": str(exc)}
        if hasattr(self.client, "notable_event_actions"):
            try:
                actions = self.client.notable_event_actions()
                discovery["notable_event_actions"] = {"count": len(actions), "titles": _inventory_titles(actions)}
            except Exception as exc:
                discovery["notable_event_actions"] = {"status": "unavailable", "message": str(exc)}
        if discovery:
            inventory["discovery"] = discovery
        if hasattr(self.client, "event_management_count"):
            try:
                inventory["event_management_counts"] = {
                    "notable_event_group": self.client.event_management_count(
                        "notable_event_group",
                        inventory_options.get("notable_event_group_filter")
                        if isinstance(inventory_options.get("notable_event_group_filter"), dict)
                        else None,
                    )
                }
            except Exception as exc:
                inventory["event_management_counts"] = {"status": "unavailable", "message": str(exc)}
        maintenance_keys = _unique_nonblank_strings(inventory_options.get("maintenance_object_keys"), "inventory.maintenance_object_keys")
        if maintenance_keys:
            maintenance_status: dict[str, Any] = {}
            for object_key in maintenance_keys:
                item: dict[str, Any] = {}
                try:
                    if hasattr(self.client, "active_maintenance_window"):
                        item["active"] = self.client.active_maintenance_window(object_key)
                    if hasattr(self.client, "maintenance_windows_count_for_object"):
                        item["count"] = self.client.maintenance_windows_count_for_object(object_key)
                    if hasattr(self.client, "maintenance_windows_for_object"):
                        windows = self.client.maintenance_windows_for_object(object_key)
                        item["titles"] = _inventory_titles(windows)
                except Exception as exc:
                    item = {"status": "unavailable", "message": str(exc)}
                maintenance_status[object_key] = item
            inventory["maintenance_status"] = maintenance_status
        result.inventory = inventory
        result.changes.append(ChangeRecord("inventory", "live ITSI", "read", "ok", "Collected read-only ITSI inventory."))
        return result

    @staticmethod
    def _candidate_id(candidate: dict[str, Any]) -> str:
        identity = {
            "section": candidate.get("section"),
            "object_type": candidate.get("object_type"),
            "title": candidate.get("title"),
            "key": candidate.get("key"),
        }
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _plan_id(candidates: list[dict[str, Any]]) -> str:
        plan_identity = [
            {
                "candidate_id": candidate.get("candidate_id"),
                "section": candidate.get("section"),
                "object_type": candidate.get("object_type"),
                "title": candidate.get("title"),
                "key": candidate.get("key"),
                "delete_supported": candidate.get("delete_supported"),
            }
            for candidate in candidates
        ]
        return hashlib.sha256(json.dumps(plan_identity, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _protected_cleanup_reason(section_name: str, candidate: dict[str, Any], allow_system_objects: bool) -> str | None:
        if allow_system_objects:
            return None
        key = str(candidate.get("key") or "").strip()
        title = str(candidate.get("title") or "").strip()
        key_lower = key.lower()
        if key in PROTECTED_CLEANUP_KEYS or key_lower in {item.lower() for item in PROTECTED_CLEANUP_KEYS}:
            return "candidate looks like a default ITSI object; set cleanup.allow_system_objects: true only after manual review."
        if any(key_lower.startswith(prefix) for prefix in PROTECTED_CLEANUP_KEY_PREFIXES):
            return "candidate looks like shipped ITSI/content-pack content; set cleanup.allow_system_objects: true only after manual review."
        if title in PROTECTED_CLEANUP_TITLES_BY_SECTION.get(section_name, set()):
            return "candidate title matches known default ITSI content; set cleanup.allow_system_objects: true only after manual review."
        if any(title.startswith(prefix) for prefix in PROTECTED_CLEANUP_TITLE_PREFIXES):
            return "candidate title looks like shipped ITSI/content-pack content; set cleanup.allow_system_objects: true only after manual review."
        return None

    @classmethod
    def _cleanup_support(
        cls,
        section_name: str,
        candidate: dict[str, Any],
        allow_system_objects: bool = False,
        allow_high_risk: bool = False,
    ) -> tuple[bool, str | None]:
        if section_name in HIGH_RISK_CLEANUP_SECTIONS and not allow_high_risk:
            return False, (
                f"{HIGH_RISK_CLEANUP_SECTIONS[section_name]} "
                f"Set cleanup.allow_high_risk_deletes: true and cleanup.confirm_high_risk: {HIGH_RISK_CLEANUP_CONFIRMATION} after manual review."
            )
        if not str(candidate.get("key") or "").strip():
            return False, "cleanup-apply requires a stable object key; this live object did not expose one."
        protected_reason = cls._protected_cleanup_reason(section_name, candidate, allow_system_objects)
        if protected_reason:
            return False, protected_reason
        return True, None

    def _build_prune_plan(self, spec: dict[str, Any], result: NativeResult | None = None) -> dict[str, Any]:
        cleanup = spec.get("cleanup") if isinstance(spec.get("cleanup"), dict) else {}
        allow_system_objects = bool_from_any(cleanup.get("allow_system_objects")) if isinstance(cleanup, dict) else False
        allow_high_risk = (
            bool_from_any(cleanup.get("allow_high_risk_deletes"))
            and str(cleanup.get("confirm_high_risk") or "") == HIGH_RISK_CLEANUP_CONFIRMATION
        ) if isinstance(cleanup, dict) else False
        plan: dict[str, Any] = {
            "destructive_apply_supported": True,
            "cleanup_mode": "cleanup-apply",
            "confirmation": CLEANUP_CONFIRMATION,
            "high_risk_confirmation": HIGH_RISK_CLEANUP_CONFIRMATION,
            "system_object_cleanup_allowed": allow_system_objects,
            "high_risk_cleanup_allowed": allow_high_risk,
            "candidates": [],
            "unavailable_sections": [],
        }
        desired_by_section: dict[str, set[str]] = {}
        for section in ALL_CONFIG_SECTIONS:
            desired_by_section[section.section] = {
                _config_object_title(item, section)
                for item in listify(spec.get(section.section))
                if isinstance(item, dict)
            }
            for live in self._list_objects_best_effort(section, result, plan["unavailable_sections"]):
                title = str(live.get(section.identity_field) or live.get("title") or live.get("name") or "").strip()
                if title and title not in desired_by_section[section.section]:
                    candidate = {
                        "section": section.section,
                        "object_type": section.object_type,
                        "interface": section.interface,
                        "title": title,
                        "key": live.get("_key"),
                    }
                    supported, reason = self._cleanup_support(section.section, candidate, allow_system_objects, allow_high_risk)
                    candidate["high_risk_delete"] = section.section in HIGH_RISK_CLEANUP_SECTIONS
                    candidate["delete_supported"] = supported
                    candidate["unsupported_reason"] = reason
                    candidate["action"] = "would_delete_if_cleanup_apply_is_confirmed" if supported else "manual_review_required"
                    candidate["candidate_id"] = self._candidate_id(candidate)
                    plan["candidates"].append(candidate)
        for section_name, object_type in (("entities", "entity"), ("services", "service")):
            desired_titles = {str(item.get("title") or "").strip() for item in listify(spec.get(section_name)) if isinstance(item, dict)}
            live_objects = self.client.list_objects(object_type) if hasattr(self.client, "list_objects") else []
            for live in live_objects:
                title = str(live.get("title") or "").strip()
                if title and title not in desired_titles:
                    candidate = {
                        "section": section_name,
                        "object_type": object_type,
                        "interface": "itoa",
                        "title": title,
                        "key": live.get("_key"),
                    }
                    supported, reason = self._cleanup_support(section_name, candidate, allow_system_objects, allow_high_risk)
                    candidate["high_risk_delete"] = section_name in HIGH_RISK_CLEANUP_SECTIONS
                    candidate["delete_supported"] = supported
                    candidate["unsupported_reason"] = reason
                    candidate["action"] = "would_delete_if_cleanup_apply_is_confirmed" if supported else "manual_review_required"
                    candidate["candidate_id"] = self._candidate_id(candidate)
                    plan["candidates"].append(candidate)
        plan["candidates"] = sorted(
            plan["candidates"],
            key=lambda item: (str(item.get("section")), str(item.get("title")), str(item.get("key"))),
        )
        plan["plan_id"] = self._plan_id(plan["candidates"])
        example_candidate_ids = [
            candidate["candidate_id"]
            for candidate in plan["candidates"]
            if candidate.get("delete_supported") and not candidate.get("high_risk_delete")
        ][:1]
        plan["cleanup_spec_example"] = {
            "cleanup": {
                "allow_destroy": True,
                "confirm": CLEANUP_CONFIRMATION,
                "plan_id": plan["plan_id"],
                "max_deletes": 1,
                "candidate_ids": example_candidate_ids,
                "allow_high_risk_deletes": False,
                "confirm_high_risk": HIGH_RISK_CLEANUP_CONFIRMATION,
                "high_risk_candidate_ids": [],
            }
        }
        return plan

    def _prune_plan(self, spec: dict[str, Any]) -> NativeResult:
        result = NativeResult(mode="prune-plan")
        plan = self._build_prune_plan(spec, result)
        result.prune_plan = plan
        result.changes.append(ChangeRecord("prune_plan", "live ITSI", "plan", "ok", "Generated read-only prune candidate plan."))
        return result

    def _delete_cleanup_candidate(self, candidate: dict[str, Any]) -> None:
        key = str(candidate.get("key") or "").strip()
        if not key:
            raise ValidationError(f"Cleanup candidate '{candidate.get('title')}' does not have a key.")
        if not hasattr(self.client, "delete_object"):
            raise ValidationError("The configured client does not support cleanup deletion.")
        self.client.delete_object(str(candidate["object_type"]), key, interface=str(candidate.get("interface") or "itoa"))

    def _cleanup_apply(self, spec: dict[str, Any]) -> NativeResult:
        result = NativeResult(mode="cleanup-apply")
        cleanup = spec.get("cleanup")
        if not isinstance(cleanup, dict):
            raise ValidationError("cleanup-apply requires a cleanup mapping in the spec.")
        if not bool_from_any(cleanup.get("allow_destroy")):
            raise ValidationError("cleanup-apply requires cleanup.allow_destroy: true.")
        if str(cleanup.get("confirm") or "") != CLEANUP_CONFIRMATION:
            raise ValidationError(f"cleanup-apply requires cleanup.confirm: {CLEANUP_CONFIRMATION}.")
        plan = self._build_prune_plan(spec, result)
        requested_plan_id = str(cleanup.get("plan_id") or "").strip()
        if requested_plan_id != plan["plan_id"]:
            raise ValidationError(
                f"cleanup.plan_id '{requested_plan_id}' does not match the current prune plan '{plan['plan_id']}'. Rerun prune-plan and review candidates."
            )
        candidate_ids = set(_unique_nonblank_strings(cleanup.get("candidate_ids"), "cleanup.candidate_ids"))
        for candidate in listify(cleanup.get("candidates")):
            if not isinstance(candidate, dict):
                raise ValidationError("cleanup.candidates entries must be mappings.")
            candidate_id = str(candidate.get("candidate_id") or "").strip()
            if candidate_id:
                candidate_ids.add(candidate_id)
        if not candidate_ids:
            raise ValidationError("cleanup-apply requires at least one cleanup.candidate_ids entry.")
        candidates_by_id = {candidate["candidate_id"]: candidate for candidate in plan["candidates"]}
        unknown = sorted(candidate_id for candidate_id in candidate_ids if candidate_id not in candidates_by_id)
        if unknown:
            raise ValidationError(f"cleanup.candidate_ids contains candidates not present in the current prune plan: {', '.join(unknown)}.")
        selected = [candidates_by_id[candidate_id] for candidate_id in sorted(candidate_ids)]
        high_risk = [candidate for candidate in selected if candidate.get("high_risk_delete")]
        if high_risk:
            if not bool_from_any(cleanup.get("allow_high_risk_deletes")):
                raise ValidationError("cleanup-apply selected high-risk candidates and requires cleanup.allow_high_risk_deletes: true.")
            if str(cleanup.get("confirm_high_risk") or "") != HIGH_RISK_CLEANUP_CONFIRMATION:
                raise ValidationError(
                    f"cleanup-apply selected high-risk candidates and requires cleanup.confirm_high_risk: {HIGH_RISK_CLEANUP_CONFIRMATION}."
                )
        unsupported = [candidate for candidate in selected if not candidate.get("delete_supported")]
        if unsupported:
            titles = ", ".join(str(candidate.get("title")) for candidate in unsupported)
            raise ValidationError(f"cleanup-apply selected unsupported cleanup candidates: {titles}.")
        if high_risk:
            high_risk_ids = set(_unique_nonblank_strings(cleanup.get("high_risk_candidate_ids"), "cleanup.high_risk_candidate_ids"))
            missing_high_risk_ids = sorted(str(candidate["candidate_id"]) for candidate in high_risk if candidate["candidate_id"] not in high_risk_ids)
            if missing_high_risk_ids:
                raise ValidationError(
                    "cleanup-apply high-risk deletes require each selected high-risk candidate id to also be listed in "
                    f"cleanup.high_risk_candidate_ids: {', '.join(missing_high_risk_ids)}."
                )
        max_deletes = int(cleanup.get("max_deletes") or 0)
        if max_deletes <= 0:
            raise ValidationError("cleanup-apply requires cleanup.max_deletes to be a positive integer.")
        if len(selected) > max_deletes:
            raise ValidationError(f"cleanup selected {len(selected)} candidates, which exceeds cleanup.max_deletes={max_deletes}.")
        result.prune_plan = plan
        for candidate in selected:
            self._delete_cleanup_candidate(candidate)
            result.changes.append(
                ChangeRecord(
                    str(candidate["object_type"]),
                    str(candidate["title"]),
                    "delete",
                    "ok",
                    "Deleted unmanaged ITSI object selected from the confirmed prune plan.",
                    key=str(candidate.get("key") or ""),
                )
            )
        return result

    def _find_object(self, section: ConfigObjectSection, title: str) -> dict[str, Any] | None:
        if hasattr(self.client, "find_object_by_field"):
            try:
                return self.client.find_object_by_field(section.object_type, section.identity_field, title, interface=section.interface)
            except TypeError:
                return self.client.find_object_by_field(section.object_type, section.identity_field, title)
        try:
            return self.client.find_object_by_title(section.object_type, title, interface=section.interface)
        except TypeError:
            return self.client.find_object_by_title(section.object_type, title)

    def _get_object(self, section: ConfigObjectSection, key: str) -> dict[str, Any] | None:
        try:
            return self.client.get_object(section.object_type, key, interface=section.interface)
        except TypeError:
            return self.client.get_object(section.object_type, key)

    def _create_object(self, section: ConfigObjectSection, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.client.create_object(section.object_type, payload, interface=section.interface)
        except TypeError:
            return self.client.create_object(section.object_type, payload)

    def _update_object(self, section: ConfigObjectSection, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.client.update_object(section.object_type, key, payload, interface=section.interface)
        except TypeError:
            return self.client.update_object(section.object_type, key, payload)

    def _upsert_config_sections(
        self,
        spec: dict[str, Any],
        result: NativeResult,
        sections: tuple[ConfigObjectSection, ...],
        *,
        apply: bool,
        default_team: str,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        snapshots: dict[str, dict[str, dict[str, Any]]] = {}
        for section in sections:
            seen_titles: set[str] = set()
            for object_spec in listify(spec.get(section.section)):
                if not isinstance(object_spec, dict):
                    raise ValidationError(f"{section.section} entries must be mappings.")
                title = _config_object_title(object_spec, section)
                if title in seen_titles:
                    raise ValidationError(f"{section.section} declares '{title}' more than once.")
                seen_titles.add(title)
                _validate_config_object_safety(object_spec, section)
                existing = self._find_object(section, title)
                desired = _normalize_config_object(object_spec, section, existing, default_team)
                if not existing:
                    if apply:
                        created = self._create_object(section, desired)
                        desired["_key"] = created.get("_key")
                    snapshot = desired if apply else _apply_preview_config_key(desired)
                    snapshots.setdefault(section.object_type, {})[title] = snapshot
                    result.changes.append(
                        ChangeRecord(
                            section.display_label,
                            title,
                            "create",
                            "ok",
                            f"Created {section.display_label}." if apply else f"Would create {section.display_label}.",
                            key=snapshot.get("_key"),
                        )
                    )
                    continue
                if _compare_config_object(existing, object_spec, section, default_team):
                    snapshots.setdefault(section.object_type, {})[title] = deepcopy(existing)
                    result.changes.append(
                        ChangeRecord(
                            section.display_label,
                            title,
                            "noop",
                            "ok",
                            f"{section.display_label} already matches.",
                            key=existing.get("_key"),
                        )
                    )
                    continue
                if apply:
                    self._update_object(section, existing["_key"], desired)
                    desired["_key"] = existing["_key"]
                snapshot = desired if apply else _apply_preview_config_key(desired)
                snapshots.setdefault(section.object_type, {})[title] = snapshot
                result.changes.append(
                    ChangeRecord(
                        section.display_label,
                        title,
                        "update",
                        "ok",
                        f"Updated {section.display_label}." if apply else f"Would update {section.display_label}.",
                        key=snapshot.get("_key"),
                    )
                )
        return snapshots

    @staticmethod
    def _merge_object_snapshots(*snapshots: dict[str, dict[str, dict[str, Any]]]) -> dict[str, dict[str, dict[str, Any]]]:
        merged: dict[str, dict[str, dict[str, Any]]] = {}
        for snapshot in snapshots:
            for object_type, objects in snapshot.items():
                merged.setdefault(object_type, {}).update(deepcopy(objects))
        return merged

    def _resolve_entity_types_by_title(
        self,
        spec: dict[str, Any],
        object_snapshots: dict[str, dict[str, dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        resolved = deepcopy(object_snapshots.get("entity_type", {}))
        section = ConfigObjectSection("entity_types", "entity_type")
        for entity_spec in listify(spec.get("entities")):
            for title in listify(entity_spec.get("entity_type_titles")):
                normalized_title = str(title or "").strip()
                if not normalized_title or normalized_title in resolved:
                    continue
                found = self._find_object(section, normalized_title)
                if found:
                    resolved[normalized_title] = found
        return resolved

    def _resolve_service_template(
        self,
        ref_value: Any,
        template_snapshots: dict[str, dict[str, Any]],
        label: str,
    ) -> dict[str, Any]:
        ref = _normalize_service_template_ref(ref_value, label)
        if ref["key"]:
            title = ref["title"] or str(ref["key"])
            return {"_key": ref["key"], "title": title, "object_type": "base_service_template"}
        title = str(ref["title"])
        if title in template_snapshots:
            return deepcopy(template_snapshots[title])
        section = ConfigObjectSection("service_templates", "base_service_template", label="service_template")
        found = self._find_object(section, title)
        if not found:
            raise ValidationError(f"{label} references unknown service template '{title}'.")
        return found

    def _resolve_custom_threshold_window(
        self,
        link_spec: dict[str, Any],
        window_snapshots: dict[str, dict[str, Any]],
        label: str,
    ) -> dict[str, Any]:
        ref = _normalize_ref(_custom_threshold_window_ref(link_spec), label)
        if ref["key"]:
            title = ref["title"] or str(ref["key"])
            return {"_key": ref["key"], "title": title, "object_type": "custom_threshold_windows"}
        title = str(ref["title"])
        if title in window_snapshots:
            return deepcopy(window_snapshots[title])
        section = ConfigObjectSection("custom_threshold_windows", "custom_threshold_windows")
        found = self._find_object(section, title)
        if not found:
            raise ValidationError(f"{label} references unknown custom threshold window '{title}'.")
        return found

    def _resolve_service_for_link(
        self,
        service_spec: Any,
        services_by_title: dict[str, dict[str, Any] | None],
        label: str,
    ) -> dict[str, Any]:
        ref = _service_link_ref(service_spec, label)
        if ref["key"]:
            if ref["title"] and services_by_title.get(ref["title"]):
                return deepcopy(services_by_title[str(ref["title"])])
            found = self.client.get_object("service", ref["key"])
            if found:
                return found
            title = ref["title"] or str(ref["key"])
            return {"_key": ref["key"], "title": title, "object_type": "service"}
        title = str(ref["title"])
        found = services_by_title.get(title)
        if found:
            return deepcopy(found)
        found = self.client.find_object_by_title("service", title)
        if not found:
            raise ValidationError(f"{label} references unknown service '{title}'.")
        services_by_title[title] = deepcopy(found)
        return found

    def _resolve_custom_threshold_link_payload(
        self,
        link_spec: dict[str, Any],
        services_by_title: dict[str, dict[str, Any] | None],
        window_snapshots: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], set[tuple[str, str]]]:
        window = self._resolve_custom_threshold_window(link_spec, window_snapshots, "custom_threshold_window_links window")
        window_key = str(window.get("_key") or "").strip()
        if not window_key:
            raise ValidationError(f"Custom threshold window '{window.get('title')}' does not have a resolvable _key.")
        services_payload: list[dict[str, Any]] = []
        desired_pairs: set[tuple[str, str]] = set()
        for index, service_spec in enumerate(listify(link_spec.get("services")), start=1):
            if not isinstance(service_spec, dict):
                raise ValidationError("custom_threshold_window_links services entries must be mappings.")
            label = f"custom_threshold_window_links service #{index}"
            service = self._resolve_service_for_link(service_spec, services_by_title, label)
            service_key = str(service.get("_key") or "").strip()
            if not service_key:
                raise ValidationError(f"{label} does not have a resolvable service _key.")
            kpi_ids = _kpi_link_ids(service_spec, service, label)
            services_payload.append({"_key": service_key, "kpi_ids": kpi_ids})
            desired_pairs.update((service_key, kpi_id) for kpi_id in kpi_ids)
        if not services_payload:
            raise ValidationError("custom_threshold_window_links entries must define at least one service.")
        return window, services_payload, desired_pairs

    @staticmethod
    def _service_template_ref_value(service_spec: dict[str, Any]) -> Any:
        if "service_template" in service_spec:
            return service_spec["service_template"]
        if "from_template" in service_spec:
            return service_spec["from_template"]
        return None

    def _apply_service_template_links(
        self,
        service_specs: list[dict[str, Any]],
        services_by_title: dict[str, dict[str, Any]],
        template_snapshots: dict[str, dict[str, Any]],
        result: NativeResult,
        *,
        apply: bool,
    ) -> None:
        for service_spec in service_specs:
            ref_value = self._service_template_ref_value(service_spec)
            if ref_value is None:
                continue
            service_title = service_spec["title"]
            service = services_by_title.get(service_title)
            if not service or not service.get("_key"):
                raise ValidationError(f"Service '{service_title}' must exist before it can be linked to a service template.")
            template = self._resolve_service_template(ref_value, template_snapshots, f"Service '{service_title}' service_template")
            template_key = str(template.get("_key") or "").strip()
            if not template_key:
                raise ValidationError(f"Service template '{template.get('title')}' does not have a resolvable _key.")
            current_template = None
            if apply and service.get("_key"):
                current_template = self.client.get_service_template_link(service["_key"])
            else:
                current_template = str(service.get("base_service_template_id") or "").strip() or None
            if current_template == template_key:
                result.changes.append(
                    ChangeRecord(
                        "service_template_link",
                        service_title,
                        "noop",
                        "ok",
                        "Service template link already matches.",
                        key=service.get("_key"),
                    )
                )
                if not apply:
                    services_by_title[service_title] = _apply_service_template_snapshot(service, template)
                continue
            if apply:
                self.client.link_service_to_template(service["_key"], template_key)
                refreshed = self.client.get_object("service", service["_key"]) or service
                services_by_title[service_title] = refreshed
            else:
                services_by_title[service_title] = _apply_service_template_snapshot(service, template)
            result.changes.append(
                ChangeRecord(
                    "service_template_link",
                    service_title,
                    "update",
                    "ok",
                    "Linked service to service template." if apply else "Would link service to service template.",
                    key=service.get("_key"),
                )
            )

    def _apply_custom_threshold_window_links(
        self,
        link_specs: list[dict[str, Any]],
        services_by_title: dict[str, dict[str, Any] | None],
        window_snapshots: dict[str, dict[str, Any]],
        result: NativeResult,
        *,
        apply: bool,
    ) -> None:
        for link_spec in link_specs:
            if not isinstance(link_spec, dict):
                raise ValidationError("custom_threshold_window_links entries must be mappings.")
            window, services_payload, desired_pairs = self._resolve_custom_threshold_link_payload(
                link_spec,
                services_by_title,
                window_snapshots,
            )
            window_key = str(window["_key"])
            window_title = str(window.get("title") or window_key)
            check_live = not _uses_preview_key(window_key) and not any(
                _uses_preview_key(service_key) or _uses_preview_key(kpi_key)
                for service_key, kpi_key in desired_pairs
            )
            linked_pairs = (
                _custom_threshold_link_pairs(self.client.custom_threshold_window_linked_kpis(window_key))
                if check_live
                else set()
            )
            missing_pairs = desired_pairs - linked_pairs
            if not missing_pairs:
                result.changes.append(
                    ChangeRecord(
                        "custom_threshold_window_link",
                        window_title,
                        "noop",
                        "ok",
                        "Custom threshold window links already match.",
                        key=window_key,
                    )
                )
                continue
            if apply:
                self.client.associate_custom_threshold_window_kpis(
                    window_key,
                    _custom_threshold_payload_for_pairs(services_payload, missing_pairs),
                )
            result.changes.append(
                ChangeRecord(
                    "custom_threshold_window_link",
                    window_title,
                    "update",
                    "ok",
                    "Linked service KPIs to custom threshold window."
                    if apply
                    else "Would link service KPIs to custom threshold window.",
                    key=window_key,
                )
            )

    def _validate_config_sections(
        self,
        spec: dict[str, Any],
        result: NativeResult,
        sections: tuple[ConfigObjectSection, ...],
        *,
        default_team: str,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        snapshots: dict[str, dict[str, dict[str, Any]]] = {}
        for section in sections:
            seen_titles: set[str] = set()
            for object_spec in listify(spec.get(section.section)):
                if not isinstance(object_spec, dict):
                    raise ValidationError(f"{section.section} entries must be mappings.")
                title = _config_object_title(object_spec, section)
                if title in seen_titles:
                    raise ValidationError(f"{section.section} declares '{title}' more than once.")
                seen_titles.add(title)
                _validate_config_object_safety(object_spec, section)
                existing = self._find_object(section, title)
                status = "pass" if existing and _compare_config_object(existing, object_spec, section, default_team) else "fail"
                if status == "fail":
                    if existing:
                        expected = _expected_config_object(object_spec, section, default_team)
                        diffs = _diff_subset(existing, expected)
                        result.diagnostics.append(
                            _drift_diagnostic(
                                section.display_label,
                                title,
                                f"{section.display_label} does not match the requested configuration.",
                                diffs,
                            )
                        )
                    else:
                        result.diagnostics.append(
                            _drift_diagnostic(section.display_label, title, f"{section.display_label} was not found.")
                        )
                result.validations.append({"status": status, "object_type": section.display_label, "title": title})
                if existing:
                    snapshots.setdefault(section.object_type, {})[title] = deepcopy(existing)
        return snapshots

    def _validate_service_template_links(
        self,
        service_specs: list[dict[str, Any]],
        services_by_title: dict[str, dict[str, Any] | None],
        template_snapshots: dict[str, dict[str, Any]],
        result: NativeResult,
    ) -> None:
        for service_spec in service_specs:
            ref_value = self._service_template_ref_value(service_spec)
            if ref_value is None:
                continue
            service_title = service_spec["title"]
            service = services_by_title.get(service_title)
            status = "fail"
            if service and service.get("_key"):
                try:
                    template = self._resolve_service_template(
                        ref_value,
                        template_snapshots,
                        f"Service '{service_title}' service_template",
                    )
                    current_template = self.client.get_service_template_link(service["_key"])
                    status = "pass" if current_template == template.get("_key") else "fail"
                    if status == "fail":
                        result.diagnostics.append(
                            {
                                "status": "error",
                                "object_type": "service_template_link",
                                "title": service_title,
                                "message": "Service template link does not match the requested template.",
                            }
                        )
                except ValidationError as exc:
                    status = "fail"
                    result.diagnostics.append(
                        {
                            "status": "error",
                            "object_type": "service_template_link",
                            "title": service_title,
                            "message": str(exc),
                        }
                    )
            elif ref_value is not None:
                result.diagnostics.append(
                    {
                        "status": "error",
                        "object_type": "service_template_link",
                        "title": service_title,
                        "message": f"Service '{service_title}' was not found for template-link validation.",
                    }
                )
            result.validations.append({"status": status, "object_type": "service_template_link", "title": service_title})

    def _validate_custom_threshold_window_links(
        self,
        link_specs: list[dict[str, Any]],
        services_by_title: dict[str, dict[str, Any] | None],
        window_snapshots: dict[str, dict[str, Any]],
        result: NativeResult,
    ) -> None:
        for link_spec in link_specs:
            title = "<unknown>"
            status = "fail"
            try:
                if not isinstance(link_spec, dict):
                    raise ValidationError("custom_threshold_window_links entries must be mappings.")
                window, _, desired_pairs = self._resolve_custom_threshold_link_payload(
                    link_spec,
                    services_by_title,
                    window_snapshots,
                )
                title = str(window.get("title") or window.get("_key") or title)
                linked_pairs = _custom_threshold_link_pairs(
                    self.client.custom_threshold_window_linked_kpis(str(window["_key"]))
                )
                status = "pass" if desired_pairs <= linked_pairs else "fail"
                if status == "fail":
                    result.diagnostics.append(
                        {
                            "status": "error",
                            "object_type": "custom_threshold_window_link",
                            "title": title,
                            "message": "Custom threshold window is missing one or more requested service/KPI links.",
                        }
                    )
            except ValidationError as exc:
                status = "fail"
                result.diagnostics.append(
                    {
                        "status": "error",
                        "object_type": "custom_threshold_window_link",
                        "title": title,
                        "message": str(exc),
                    }
                )
            result.validations.append({"status": status, "object_type": "custom_threshold_window_link", "title": title})

    @staticmethod
    def _operational_action_name(action_spec: dict[str, Any]) -> str:
        action = str(action_spec.get("action") or action_spec.get("type") or "").strip().lower()
        aliases = {
            "disconnect_custom_threshold_window_kpis": "custom_threshold_window_disconnect",
            "custom_threshold_window_disconnect_kpis": "custom_threshold_window_disconnect",
            "stop_custom_threshold_window": "custom_threshold_window_stop",
            "kpi_threshold_recommendations": "kpi_threshold_recommendation",
            "kpi_entity_threshold_recommendations": "kpi_entity_threshold_recommendation",
            "retire_retirable_entities": "entity_retire_retirable",
            "entity_retire_all_retirable": "entity_retire_retirable",
            "episode_update": "notable_event_group_update",
            "notable_event_group": "notable_event_group_update",
            "update_notable_event_group": "notable_event_group_update",
            "episode_action_execute": "notable_event_action_execute",
            "execute_notable_event_action": "notable_event_action_execute",
            "notable_event_actions_execute": "notable_event_action_execute",
            "episode_ticket_link": "ticket_link",
            "link_episode_ticket": "ticket_link",
            "episode_ticket_unlink": "ticket_unlink",
            "unlink_episode_ticket": "ticket_unlink",
            "episode_export": "episode_export_create",
            "create_episode_export": "episode_export_create",
        }
        return aliases.get(action, action)

    @staticmethod
    def _operational_action_title(action_spec: dict[str, Any], action: str) -> str:
        return str(
            action_spec.get("title")
            or action_spec.get("name")
            or action_spec.get("window")
            or action_spec.get("custom_threshold_window")
            or action_spec.get("action_name")
            or action_spec.get("ticket_id")
            or action_spec.get("group_key")
            or action_spec.get("episode_id")
            or action
        )

    @staticmethod
    def _operational_action_allowed(action_spec: dict[str, Any]) -> bool:
        return bool_from_any(action_spec.get("allow_operational_action"))

    @staticmethod
    def _operational_payload(action_spec: dict[str, Any], action: str) -> dict[str, Any]:
        payload = action_spec.get("payload")
        if action in {"entity_retire", "entity_restore"}:
            if "entity_keys" in action_spec:
                entity_keys = _unique_nonblank_strings(action_spec.get("entity_keys"), f"operational_actions '{action}' entity_keys")
                if not entity_keys:
                    raise ValidationError(f"operational_actions '{action}' entity_keys must define at least one key.")
                return {"data": entity_keys}
            if not isinstance(payload, dict):
                raise ValidationError(f"operational_actions '{action}' must define payload.data or entity_keys.")
            entity_keys = _unique_nonblank_strings(payload.get("data"), f"operational_actions '{action}' payload.data")
            if not entity_keys:
                raise ValidationError(f"operational_actions '{action}' payload.data must define at least one key.")
            return {"data": entity_keys}
        if not isinstance(payload, dict) or not payload:
            raise ValidationError(f"operational_actions '{action}' must define a non-empty payload mapping.")
        return deepcopy(payload)

    @staticmethod
    def _notable_event_group_update(action_spec: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        group_key = _first_nonblank_field(
            action_spec,
            ("group_key", "episode_key", "notable_event_group_key", "_key", "key"),
            "notable_event_group_update",
        )
        payload = _nonempty_mapping(action_spec.get("payload"), "notable_event_group_update payload")
        if any(field in payload for field in ("status", "state", "severity")) and not bool_from_any(action_spec.get("allow_episode_field_change")):
            raise ValidationError(
                "notable_event_group_update changes episode status/state/severity. "
                "Set allow_episode_field_change: true after explicit operator review."
            )
        return group_key, payload

    @staticmethod
    def _notable_event_action(action_spec: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if not bool_from_any(action_spec.get("allow_notable_event_action_execute")):
            raise ValidationError(
                "notable_event_action_execute can trigger ITSI actions. "
                "Set allow_notable_event_action_execute: true after explicit operator review."
            )
        action_name = _first_nonblank_field(
            action_spec,
            ("action_name", "notable_event_action", "name"),
            "notable_event_action_execute",
        )
        payload = deepcopy(action_spec.get("payload")) if isinstance(action_spec.get("payload"), dict) else {}
        if "params" in action_spec:
            if not isinstance(action_spec["params"], dict):
                raise ValidationError("notable_event_action_execute params must be a mapping.")
            payload["params"] = deepcopy(action_spec["params"])
        payload.setdefault("params", {})
        ids_source = action_spec.get("group_ids") or action_spec.get("episode_ids") or action_spec.get("notable_event_group_ids") or payload.get("ids")
        ids = _unique_nonblank_strings(ids_source, "notable_event_action_execute ids")
        if not ids:
            raise ValidationError("notable_event_action_execute must define group_ids or payload.ids.")
        payload["ids"] = ids
        return action_name, payload

    @staticmethod
    def _ticket_link_payload(action_spec: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        payload = deepcopy(action_spec.get("payload")) if isinstance(action_spec.get("payload"), dict) else {}
        group_key = str(action_spec.get("group_key") or action_spec.get("episode_key") or action_spec.get("notable_event_group_key") or "").strip() or None
        for source, target in (
            ("episode_id", "id"),
            ("notable_event_group_id", "id"),
            ("ticketing_system", "ticket_system"),
            ("ticket_system", "ticket_system"),
            ("ticket_id", "ticket_id"),
            ("ticket_url", "ticket_url"),
            ("ticket_title", "ticket_title"),
            ("status", "status"),
        ):
            if action_spec.get(source) is not None:
                payload[target] = action_spec[source]
        if group_key and "id" not in payload and "ids" not in payload:
            payload["id"] = group_key
        if not payload:
            raise ValidationError("ticket_link must define a payload or ticket fields.")
        return group_key, payload

    @staticmethod
    def _ticket_unlink_fields(action_spec: dict[str, Any]) -> tuple[str, str, str]:
        if not bool_from_any(action_spec.get("allow_ticket_unlink")):
            raise ValidationError("ticket_unlink removes an ITSI ticket association. Set allow_ticket_unlink: true after explicit operator review.")
        group_key = _first_nonblank_field(
            action_spec,
            ("group_key", "episode_key", "notable_event_group_key", "episode_id"),
            "ticket_unlink",
        )
        ticketing_system = _first_nonblank_field(action_spec, ("ticketing_system", "ticket_system"), "ticket_unlink")
        ticket_id = _first_nonblank_field(action_spec, ("ticket_id",), "ticket_unlink")
        return group_key, ticketing_system, ticket_id

    def _apply_operational_actions(
        self,
        action_specs: list[dict[str, Any]],
        services_by_title: dict[str, dict[str, Any] | None],
        window_snapshots: dict[str, dict[str, Any]],
        result: NativeResult,
        *,
        apply: bool,
    ) -> None:
        for index, action_spec in enumerate(action_specs, start=1):
            if not isinstance(action_spec, dict):
                raise ValidationError("operational_actions entries must be mappings.")
            action = self._operational_action_name(action_spec)
            title = self._operational_action_title(action_spec, action)
            if not action:
                raise ValidationError(f"operational_actions entry #{index} must define action or type.")
            if not self._operational_action_allowed(action_spec):
                detail = "Blocked operational action. Set allow_operational_action: true after explicit operator review."
                result.changes.append(ChangeRecord("operational_action", title, "blocked", "error", detail))
                continue
            if action == "custom_threshold_window_disconnect":
                if not bool_from_any(action_spec.get("disconnect_all")):
                    raise ValidationError(
                        "custom_threshold_window_disconnect disconnects all KPIs from the window. "
                        "Set disconnect_all: true after explicit operator review."
                    )
                window = self._resolve_custom_threshold_window(
                    action_spec,
                    window_snapshots,
                    "operational_actions custom_threshold_window_disconnect",
                )
                if apply:
                    self.client.disconnect_custom_threshold_window_kpis(str(window["_key"]))
                result.changes.append(
                    ChangeRecord(
                        "operational_action",
                        str(window.get("title") or title),
                        "apply" if apply else "preview",
                        "ok",
                        "Disconnected all service KPIs from custom threshold window."
                        if apply
                        else "Would disconnect all service KPIs from custom threshold window.",
                        key=window.get("_key"),
                    )
                )
                continue
            if action == "custom_threshold_window_stop":
                window = self._resolve_custom_threshold_window(action_spec, window_snapshots, "operational_actions custom_threshold_window_stop")
                if apply:
                    self.client.stop_custom_threshold_window(str(window["_key"]))
                result.changes.append(
                    ChangeRecord(
                        "operational_action",
                        str(window.get("title") or title),
                        "apply" if apply else "preview",
                        "ok",
                        "Stopped custom threshold window." if apply else "Would stop custom threshold window.",
                        key=window.get("_key"),
                    )
                )
                continue
            if action == "entity_retire_retirable":
                if not bool_from_any(action_spec.get("retire_all_retirable")):
                    raise ValidationError(
                        "entity_retire_retirable retires every entity currently marked retirable. "
                        "Set retire_all_retirable: true after explicit operator review."
                    )
                if apply:
                    self.client.retire_retirable_entities()
                result.changes.append(
                    ChangeRecord(
                        "operational_action",
                        title,
                        "apply" if apply else "preview",
                        "ok",
                        "Retired all retirable entities." if apply else "Would retire all retirable entities.",
                    )
                )
                continue
            if action == "notable_event_group_update":
                group_key, payload = self._notable_event_group_update(action_spec)
                if apply:
                    self.client.update_notable_event_group(group_key, payload)
                result.changes.append(
                    ChangeRecord(
                        "operational_action",
                        title,
                        "apply" if apply else "preview",
                        "ok",
                        "Updated notable event group." if apply else "Would update notable event group.",
                        key=group_key,
                    )
                )
                continue
            if action == "notable_event_action_execute":
                action_name, payload = self._notable_event_action(action_spec)
                if apply:
                    self.client.execute_notable_event_action(action_name, payload)
                result.changes.append(
                    ChangeRecord(
                        "operational_action",
                        title,
                        "apply" if apply else "preview",
                        "ok",
                        f"Executed notable event action '{action_name}'." if apply else f"Would execute notable event action '{action_name}'.",
                    )
                )
                continue
            if action == "ticket_link":
                group_key, payload = self._ticket_link_payload(action_spec)
                if apply:
                    self.client.link_episode_ticket(payload, group_key=group_key)
                result.changes.append(
                    ChangeRecord(
                        "operational_action",
                        title,
                        "apply" if apply else "preview",
                        "ok",
                        "Linked ticket to ITSI episode." if apply else "Would link ticket to ITSI episode.",
                        key=group_key,
                    )
                )
                continue
            if action == "ticket_unlink":
                group_key, ticketing_system, ticket_id = self._ticket_unlink_fields(action_spec)
                if apply:
                    self.client.unlink_episode_ticket(group_key, ticketing_system, ticket_id)
                result.changes.append(
                    ChangeRecord(
                        "operational_action",
                        title,
                        "apply" if apply else "preview",
                        "ok",
                        "Unlinked ticket from ITSI episode." if apply else "Would unlink ticket from ITSI episode.",
                        key=group_key,
                    )
                )
                continue
            if action == "episode_export_create":
                payload = _nonempty_mapping(action_spec.get("payload"), "episode_export_create payload")
                if apply:
                    self.client.create_episode_export(payload)
                result.changes.append(
                    ChangeRecord(
                        "operational_action",
                        title,
                        "apply" if apply else "preview",
                        "ok",
                        "Created episode export job." if apply else "Would create episode export job.",
                    )
                )
                continue
            dispatch = {
                "entity_retire": self.client.retire_entities,
                "entity_restore": self.client.restore_entities,
                "kpi_threshold_recommendation": self.client.apply_kpi_threshold_recommendation,
                "kpi_entity_threshold_recommendation": self.client.apply_kpi_entity_threshold_recommendation,
                "shift_time_offset": self.client.shift_time_offset,
            }
            handler = dispatch.get(action)
            if not handler:
                raise ValidationError(f"Unsupported operational action '{action}'.")
            payload = self._operational_payload(action_spec, action)
            if apply:
                handler(payload)
            result.changes.append(
                ChangeRecord(
                    "operational_action",
                    title,
                    "apply" if apply else "preview",
                    "ok",
                    f"Applied operational action '{action}'." if apply else f"Would apply operational action '{action}'.",
                )
            )

    def _validate_operational_actions(
        self,
        action_specs: list[dict[str, Any]],
        services_by_title: dict[str, dict[str, Any] | None],
        window_snapshots: dict[str, dict[str, Any]],
        result: NativeResult,
    ) -> None:
        for index, action_spec in enumerate(action_specs, start=1):
            title = "<unknown>"
            status = "pass"
            message = "Operational action is guarded and structurally valid."
            try:
                if not isinstance(action_spec, dict):
                    raise ValidationError("operational_actions entries must be mappings.")
                action = self._operational_action_name(action_spec)
                title = self._operational_action_title(action_spec, action)
                if not action:
                    raise ValidationError(f"operational_actions entry #{index} must define action or type.")
                if not self._operational_action_allowed(action_spec):
                    raise ValidationError("Set allow_operational_action: true after explicit operator review.")
                if action == "custom_threshold_window_disconnect":
                    if not bool_from_any(action_spec.get("disconnect_all")):
                        raise ValidationError(
                            "custom_threshold_window_disconnect disconnects all KPIs from the window. "
                            "Set disconnect_all: true after explicit operator review."
                        )
                    self._resolve_custom_threshold_window(
                        action_spec,
                        window_snapshots,
                        "operational_actions custom_threshold_window_disconnect",
                    )
                elif action == "custom_threshold_window_stop":
                    self._resolve_custom_threshold_window(action_spec, window_snapshots, "operational_actions custom_threshold_window_stop")
                elif action == "entity_retire_retirable":
                    if not bool_from_any(action_spec.get("retire_all_retirable")):
                        raise ValidationError(
                            "entity_retire_retirable retires every entity currently marked retirable. "
                            "Set retire_all_retirable: true after explicit operator review."
                        )
                elif action == "notable_event_group_update":
                    self._notable_event_group_update(action_spec)
                elif action == "notable_event_action_execute":
                    self._notable_event_action(action_spec)
                elif action == "ticket_link":
                    self._ticket_link_payload(action_spec)
                elif action == "ticket_unlink":
                    self._ticket_unlink_fields(action_spec)
                elif action == "episode_export_create":
                    _nonempty_mapping(action_spec.get("payload"), "episode_export_create payload")
                elif action in {
                    "entity_retire",
                    "entity_restore",
                    "kpi_threshold_recommendation",
                    "kpi_entity_threshold_recommendation",
                    "shift_time_offset",
                }:
                    self._operational_payload(action_spec, action)
                else:
                    raise ValidationError(f"Unsupported operational action '{action}'.")
            except ValidationError as exc:
                status = "fail"
                message = str(exc)
                result.diagnostics.append(
                    {"status": "error", "object_type": "operational_action", "title": title, "message": message}
                )
            result.validations.append({"status": status, "object_type": "operational_action", "title": title})

    def _upsert(self, spec: dict[str, Any], apply: bool, mode: str) -> NativeResult:
        result = NativeResult(mode=mode)
        self._add_preflight_diagnostics(spec, result)
        defaults = spec.get("defaults", {})
        default_team = defaults.get("sec_grp", DEFAULT_TEAM)
        pre_snapshots = self._upsert_config_sections(
            spec,
            result,
            PRE_SERVICE_CONFIG_SECTIONS,
            apply=apply,
            default_team=default_team,
        )
        entity_types_by_title = self._resolve_entity_types_by_title(spec, pre_snapshots)
        for entity_spec in listify(spec.get("entities")):
            existing = self.client.find_object_by_title("entity", entity_spec["title"])
            desired = _normalize_entity(entity_spec, default_team, existing, entity_types_by_title)
            if not existing:
                detail = "Would create entity." if not apply else "Created entity."
                if apply:
                    created = self.client.create_object("entity", desired)
                    desired["_key"] = created.get("_key")
                result.changes.append(
                    ChangeRecord("entity", entity_spec["title"], "create", "ok", detail, key=desired.get("_key"))
                )
                continue
            if _compare_entity(existing, desired):
                result.changes.append(ChangeRecord("entity", entity_spec["title"], "noop", "ok", "Entity already matches.", key=existing.get("_key")))
                continue
            if apply:
                self.client.update_object("entity", existing["_key"], desired)
            result.changes.append(
                ChangeRecord("entity", entity_spec["title"], "update", "ok", "Updated entity." if apply else "Would update entity.", key=existing.get("_key"))
            )

        service_titles = [service_spec["title"] for service_spec in listify(spec.get("services"))]
        dependency_titles = []
        for service_spec in listify(spec.get("services")):
            for dependency in listify(service_spec.get("depends_on")):
                dependency_titles.append(dependency if isinstance(dependency, str) else dependency["service"])
        services_by_title: dict[str, dict[str, Any]] = {}
        for service_spec in listify(spec.get("services")):
            existing = self.client.find_object_by_title("service", service_spec["title"])
            desired = _normalize_service(service_spec, existing, default_team)
            if not existing:
                if apply:
                    created = self.client.create_object("service", desired)
                    existing = self.client.get_object("service", created.get("_key")) or deep_merge(desired, created)
                preview_service = deep_merge(desired, existing or {})
                services_by_title[service_spec["title"]] = preview_service if apply else _apply_preview_keys(preview_service)
                result.changes.append(
                    ChangeRecord(
                        "service",
                        service_spec["title"],
                        "create",
                        "ok",
                        "Created service." if apply else "Would create service.",
                        key=(existing or {}).get("_key"),
                    )
                )
                continue
            if apply and not _compare_service(existing, desired, service_spec):
                self.client.update_object("service", existing["_key"], desired)
                existing = self.client.get_object("service", existing["_key"]) or desired
                result.changes.append(
                    ChangeRecord("service", service_spec["title"], "update", "ok", "Updated service.", key=existing.get("_key"))
                )
            elif not apply and not _compare_service(existing, desired, service_spec):
                result.changes.append(
                    ChangeRecord("service", service_spec["title"], "update", "ok", "Would update service.", key=existing.get("_key"))
                )
            else:
                result.changes.append(
                    ChangeRecord("service", service_spec["title"], "noop", "ok", "Service already matches.", key=existing.get("_key"))
                )
            services_by_title[service_spec["title"]] = deepcopy(existing if apply else _apply_preview_keys(desired))

        self._apply_service_template_links(
            listify(spec.get("services")),
            services_by_title,
            pre_snapshots.get("base_service_template", {}),
            result,
            apply=apply,
        )
        self._apply_custom_threshold_window_links(
            listify(spec.get("custom_threshold_window_links")),
            services_by_title,
            pre_snapshots.get("custom_threshold_windows", {}),
            result,
            apply=apply,
        )

        for service_title in service_titles:
            services_by_title[service_title] = (
                self.client.find_object_by_title("service", service_title) if apply else services_by_title[service_title]
            ) or services_by_title[service_title]
        for dependency_title in dependency_titles:
            if dependency_title in services_by_title:
                continue
            dependency_service = self.client.find_object_by_title("service", dependency_title)
            if dependency_service:
                services_by_title[dependency_title] = deepcopy(dependency_service if apply else _apply_preview_keys(dependency_service))

        for service_spec in listify(spec.get("services")):
            dependencies = listify(service_spec.get("depends_on"))
            if not dependencies:
                continue
            existing = services_by_title[service_spec["title"]]
            payload, changed = _merge_dependencies(existing, dependencies, services_by_title)
            if not changed:
                result.changes.append(
                    ChangeRecord("service_dependency", service_spec["title"], "noop", "ok", "Dependencies already match.", key=existing.get("_key"))
                )
                continue
            if apply:
                self.client.update_object("service", existing["_key"], payload)
                refreshed = self.client.get_object("service", existing["_key"]) or payload
                services_by_title[service_spec["title"]] = refreshed
            result.changes.append(
                ChangeRecord(
                    "service_dependency",
                    service_spec["title"],
                    "update",
                    "ok",
                    "Updated service dependencies." if apply else "Would update service dependencies.",
                    key=existing.get("_key"),
                )
            )

        for neap_spec in listify(spec.get("neaps")):
            existing = self._find_object(NEAP_SECTION, neap_spec["title"])
            if existing and _neap_is_managed(existing):
                raise ValidationError(
                    f"Refusing to update managed NEAP '{neap_spec['title']}'. Provide a custom policy title instead."
                )
            desired = _normalize_neap(neap_spec, existing, default_team)
            if not existing:
                if apply:
                    created = self._create_object(NEAP_SECTION, desired)
                    desired["_key"] = created.get("_key")
                result.changes.append(
                    ChangeRecord(
                        "notable_event_aggregation_policy",
                        neap_spec["title"],
                        "create",
                        "ok",
                        "Created NEAP." if apply else "Would create NEAP.",
                        key=desired.get("_key"),
                    )
                )
                continue
            if _compare_neap(existing, desired):
                result.changes.append(
                    ChangeRecord(
                        "notable_event_aggregation_policy",
                        neap_spec["title"],
                        "noop",
                        "ok",
                        "NEAP already matches.",
                        key=existing.get("_key"),
                    )
                )
                continue
            if apply:
                self._update_object(NEAP_SECTION, existing["_key"], desired)
            result.changes.append(
                ChangeRecord(
                    "notable_event_aggregation_policy",
                    neap_spec["title"],
                    "update",
                    "ok",
                    "Updated NEAP." if apply else "Would update NEAP.",
                    key=existing.get("_key"),
                )
            )
        post_snapshots = self._upsert_config_sections(
            spec,
            result,
            POST_SERVICE_CONFIG_SECTIONS,
            apply=apply,
            default_team=default_team,
        )
        self._apply_operational_actions(
            listify(spec.get("operational_actions")),
            services_by_title,
            pre_snapshots.get("custom_threshold_windows", {}),
            result,
            apply=apply,
        )
        result.service_snapshots = {title: deepcopy(payload) for title, payload in services_by_title.items()}
        result.object_snapshots = self._merge_object_snapshots(pre_snapshots, post_snapshots)
        return result

    def _validate(self, spec: dict[str, Any]) -> NativeResult:
        result = NativeResult(mode="validate")
        self._add_preflight_diagnostics(spec, result)
        defaults = spec.get("defaults", {})
        default_team = defaults.get("sec_grp", DEFAULT_TEAM)
        pre_snapshots = self._validate_config_sections(
            spec,
            result,
            PRE_SERVICE_CONFIG_SECTIONS,
            default_team=default_team,
        )
        entity_types_by_title = self._resolve_entity_types_by_title(spec, pre_snapshots)
        for entity_spec in listify(spec.get("entities")):
            existing = self.client.find_object_by_title("entity", entity_spec["title"])
            try:
                desired = _normalize_entity(entity_spec, default_team, existing, entity_types_by_title) if existing else None
                status = "pass" if existing and _compare_entity(existing, desired) else "fail"
                if status == "fail":
                    diffs = _diff_subset(existing, _expected_entity(desired)) if existing and desired else None
                    result.diagnostics.append(
                        _drift_diagnostic(
                            "entity",
                            entity_spec["title"],
                            "Entity was not found or does not match the requested configuration.",
                            diffs,
                        )
                    )
            except ValidationError as exc:
                status = "fail"
                result.diagnostics.append(
                    _drift_diagnostic("entity", entity_spec["title"], str(exc))
                )
            result.validations.append({"status": status, "object_type": "entity", "title": entity_spec["title"]})
        services_by_title = {
            service_spec["title"]: self.client.find_object_by_title("service", service_spec["title"])
            for service_spec in listify(spec.get("services"))
        }
        dependency_titles = []
        for service_spec in listify(spec.get("services")):
            for dependency in listify(service_spec.get("depends_on")):
                dependency_titles.append(dependency if isinstance(dependency, str) else dependency["service"])
        for dependency_title in dependency_titles:
            if dependency_title in services_by_title:
                continue
            dependency_service = self.client.find_object_by_title("service", dependency_title)
            if dependency_service:
                services_by_title[dependency_title] = dependency_service
        for service_spec in listify(spec.get("services")):
            existing = services_by_title[service_spec["title"]]
            desired = _normalize_service(service_spec, existing, default_team) if existing else None
            service_status = "pass" if existing and desired and _compare_service(existing, desired, service_spec) else "fail"
            if service_status == "fail":
                diffs = _diff_subset(existing, _expected_service(desired, service_spec)) if existing and desired else None
                result.diagnostics.append(
                    _drift_diagnostic(
                        "service",
                        service_spec["title"],
                        "Service was not found or does not match the requested configuration.",
                        diffs,
                    )
                )
            result.validations.append({"status": service_status, "object_type": "service", "title": service_spec["title"]})
        self._validate_service_template_links(
            listify(spec.get("services")),
            services_by_title,
            pre_snapshots.get("base_service_template", {}),
            result,
        )
        self._validate_custom_threshold_window_links(
            listify(spec.get("custom_threshold_window_links")),
            services_by_title,
            pre_snapshots.get("custom_threshold_windows", {}),
            result,
        )
        for service_spec in listify(spec.get("services")):
            existing = services_by_title[service_spec["title"]]
            dependencies = listify(service_spec.get("depends_on"))
            if dependencies and existing:
                try:
                    _, changed = _merge_dependencies(existing, dependencies, services_by_title)
                    if changed:
                        result.diagnostics.append(
                            {
                                "status": "error",
                                "object_type": "service_dependency",
                                "title": service_spec["title"],
                                "message": "Service dependencies do not match the requested configuration.",
                            }
                        )
                except ValidationError as exc:
                    changed = True
                    result.diagnostics.append(
                        {
                            "status": "error",
                            "object_type": "service_dependency",
                            "title": service_spec["title"],
                            "message": str(exc),
                        }
                    )
                result.validations.append(
                    {"status": "fail" if changed else "pass", "object_type": "service_dependency", "title": service_spec["title"]}
                )
        for neap_spec in listify(spec.get("neaps")):
            existing = self._find_object(NEAP_SECTION, neap_spec["title"])
            desired = _normalize_neap(neap_spec, existing, default_team) if existing else None
            status = (
                "pass"
                if existing and desired and not _neap_is_managed(existing) and _compare_neap(existing, desired)
                else "fail"
            )
            if status == "fail":
                diffs = _diff_subset(existing, _expected_neap(desired)) if existing and desired else None
                result.diagnostics.append(
                    _drift_diagnostic(
                        "notable_event_aggregation_policy",
                        neap_spec["title"],
                        "NEAP was not found, is managed/default, or does not match the requested configuration.",
                        diffs,
                    )
                )
            result.validations.append(
                {"status": status, "object_type": "notable_event_aggregation_policy", "title": neap_spec["title"]}
            )
        post_snapshots = self._validate_config_sections(
            spec,
            result,
            POST_SERVICE_CONFIG_SECTIONS,
            default_team=default_team,
        )
        self._validate_operational_actions(
            listify(spec.get("operational_actions")),
            services_by_title,
            pre_snapshots.get("custom_threshold_windows", {}),
            result,
        )
        result.service_snapshots = {title: deepcopy(payload) for title, payload in services_by_title.items() if payload}
        result.object_snapshots = self._merge_object_snapshots(pre_snapshots, post_snapshots)
        return result
