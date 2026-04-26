from __future__ import annotations

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
    ConfigObjectSection("kpi_base_searches", "kpi_base_search"),
    ConfigObjectSection("kpi_threshold_templates", "kpi_threshold_template"),
    ConfigObjectSection("kpi_templates", "kpi_template"),
    ConfigObjectSection("custom_threshold_windows", "custom_threshold_windows"),
    ConfigObjectSection("custom_content_packs", "content_pack", interface="content_pack_authorship", label="custom_content_pack", default_sec_grp=False),
    ConfigObjectSection("service_templates", "base_service_template", label="service_template"),
)

POST_SERVICE_CONFIG_SECTIONS = (
    ConfigObjectSection("event_management_states", "event_management_state", interface="event_management"),
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


def _normalize_kpi(kpi_spec: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = deepcopy(existing or {})
    updates = {
        "title": kpi_spec["title"],
        "description": kpi_spec.get("description", ""),
        "search": kpi_spec.get("search"),
        "threshold_field": kpi_spec.get("threshold_field"),
        "aggregate_statop": kpi_spec.get("aggregate_statop"),
        "entity_statop": kpi_spec.get("entity_statop"),
        "entity_id_fields": kpi_spec.get("entity_id_fields"),
        "entity_breakdown_id_field": kpi_spec.get("entity_breakdown_id_field"),
        "search_alert_earliest": kpi_spec.get("search_alert_earliest"),
        "search_alert_latest": kpi_spec.get("search_alert_latest"),
        "threshold_direction": kpi_spec.get("threshold_direction"),
        "urgency": kpi_spec.get("urgency"),
        "unit": kpi_spec.get("unit"),
        "importance": kpi_spec.get("importance"),
        "kpi_threshold_template_id": kpi_spec.get("kpi_threshold_template_id"),
        "kpi_base_search_id": kpi_spec.get("kpi_base_search_id"),
        "base_search_id": kpi_spec.get("base_search_id"),
        "isadhoc": kpi_spec.get("isadhoc"),
        "is_service_entity_filter": kpi_spec.get("is_service_entity_filter"),
        "is_entity_breakdown": kpi_spec.get("is_entity_breakdown"),
        "adaptive_thresholding": kpi_spec.get("adaptive_thresholding"),
        "anomaly_detection": kpi_spec.get("anomaly_detection"),
    }
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
        desired_kpis.append(_normalize_kpi(kpi_spec, existing_kpis.get(kpi_spec["title"])))
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
    return subset_matches(canonicalize(existing), canonicalize(expected))


def _desired_kpi_subset(service_spec: dict[str, Any]) -> list[dict[str, Any]]:
    subset: list[dict[str, Any]] = []
    for kpi_spec in listify(service_spec.get("kpis")):
        normalized = _normalize_kpi(kpi_spec)
        normalized.pop("_key", None)
        subset.append(compact(normalized))
    return subset


def _compare_service(existing: dict[str, Any], desired: dict[str, Any], service_spec: dict[str, Any]) -> bool:
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
    return subset_matches(canonicalize(existing), canonicalize(expected))


def _compare_neap(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
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
    return subset_matches(canonicalize(existing), canonicalize(expected))


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
        if mode not in {"preview", "apply", "validate"}:
            raise ValidationError(f"Unsupported native mode '{mode}'.")
        if mode == "validate":
            return self._validate(spec)
        return self._upsert(spec, apply=(mode == "apply"), mode=mode)

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
        }
        return aliases.get(action, action)

    @staticmethod
    def _operational_action_title(action_spec: dict[str, Any], action: str) -> str:
        return str(
            action_spec.get("title")
            or action_spec.get("name")
            or action_spec.get("window")
            or action_spec.get("custom_threshold_window")
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
                    result.diagnostics.append(
                        {
                            "status": "error",
                            "object_type": "entity",
                            "title": entity_spec["title"],
                            "message": "Entity was not found or does not match the requested configuration.",
                        }
                    )
            except ValidationError as exc:
                status = "fail"
                result.diagnostics.append(
                    {
                        "status": "error",
                        "object_type": "entity",
                        "title": entity_spec["title"],
                        "message": str(exc),
                    }
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
                result.diagnostics.append(
                    {
                        "status": "error",
                        "object_type": "service",
                        "title": service_spec["title"],
                        "message": "Service was not found or does not match the requested configuration.",
                    }
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
