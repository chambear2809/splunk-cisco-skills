from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .common import ValidationError, bool_from_any, canonicalize, compact, deep_merge, listify, subset_matches


DEFAULT_TEAM = "default_itsi_security_group"


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
    service_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return any(change.status == "error" for change in self.changes) or any(
            item.get("status") == "fail" for item in self.validations
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


def _normalize_entity(
    entity_spec: dict[str, Any],
    default_team: str,
    existing: dict[str, Any] | None = None,
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
    payload = deep_merge(payload, entity_spec.get("payload", {}))
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
    payload = deep_merge(payload, kpi_spec.get("payload", {}))
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
    payload = deep_merge(payload, service_spec.get("payload", {}))
    return compact(payload)


def _normalize_neap(neap_spec: dict[str, Any], existing: dict[str, Any] | None, default_team: str) -> dict[str, Any]:
    payload = deepcopy(existing or {})
    payload["object_type"] = "notable_event_aggregation_policy"
    payload["title"] = neap_spec["title"]
    if existing is None or "description" in neap_spec:
        payload["description"] = neap_spec.get("description", "")
    if existing is None or "sec_grp" in neap_spec:
        payload["sec_grp"] = neap_spec.get("sec_grp", default_team)
    payload = deep_merge(payload, neap_spec.get("payload", {}))
    return compact(payload)


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
    return subset_matches(canonicalize(existing), canonicalize(expected))


def _desired_kpi_subset(service_spec: dict[str, Any]) -> list[dict[str, Any]]:
    subset: list[dict[str, Any]] = []
    for kpi_spec in listify(service_spec.get("kpis")):
        normalized = _normalize_kpi(kpi_spec)
        subset.append(
            compact(
                {
                    "title": normalized.get("title"),
                    "description": normalized.get("description", ""),
                    "search": normalized.get("search"),
                    "threshold_field": normalized.get("threshold_field"),
                    "aggregate_statop": normalized.get("aggregate_statop"),
                    "entity_statop": normalized.get("entity_statop"),
                    "entity_id_fields": normalized.get("entity_id_fields"),
                    "entity_breakdown_id_field": normalized.get("entity_breakdown_id_field"),
                    "aggregate_thresholds": normalized.get("aggregate_thresholds"),
                    "entity_thresholds": normalized.get("entity_thresholds"),
                    "urgency": normalized.get("urgency"),
                    "unit": normalized.get("unit"),
                }
            )
        )
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
    return bool(existing.get("source_itsi_da") or existing.get("managed_by") or existing.get("managed"))


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


class NativeWorkflow:
    def __init__(self, client: Any):
        self.client = client

    def run(self, spec: dict[str, Any], mode: str) -> NativeResult:
        if mode not in {"preview", "apply", "validate"}:
            raise ValidationError(f"Unsupported native mode '{mode}'.")
        if mode == "validate":
            return self._validate(spec)
        return self._upsert(spec, apply=(mode == "apply"), mode=mode)

    def _upsert(self, spec: dict[str, Any], apply: bool, mode: str) -> NativeResult:
        result = NativeResult(mode=mode)
        defaults = spec.get("defaults", {})
        default_team = defaults.get("sec_grp", DEFAULT_TEAM)
        for entity_spec in listify(spec.get("entities")):
            existing = self.client.find_object_by_title("entity", entity_spec["title"])
            desired = _normalize_entity(entity_spec, default_team, existing)
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
            existing = self.client.find_object_by_title("notable_event_aggregation_policy", neap_spec["title"])
            if existing and _neap_is_managed(existing):
                raise ValidationError(
                    f"Refusing to update managed NEAP '{neap_spec['title']}'. Provide a custom policy title instead."
                )
            desired = _normalize_neap(neap_spec, existing, default_team)
            if not existing:
                if apply:
                    created = self.client.create_object("notable_event_aggregation_policy", desired)
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
                self.client.update_object("notable_event_aggregation_policy", existing["_key"], desired)
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
        result.service_snapshots = {title: deepcopy(payload) for title, payload in services_by_title.items()}
        return result

    def _validate(self, spec: dict[str, Any]) -> NativeResult:
        result = NativeResult(mode="validate")
        defaults = spec.get("defaults", {})
        default_team = defaults.get("sec_grp", DEFAULT_TEAM)
        for entity_spec in listify(spec.get("entities")):
            existing = self.client.find_object_by_title("entity", entity_spec["title"])
            desired = _normalize_entity(entity_spec, default_team, existing) if existing else None
            status = "pass" if existing and _compare_entity(existing, desired) else "fail"
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
            result.validations.append({"status": service_status, "object_type": "service", "title": service_spec["title"]})
            dependencies = listify(service_spec.get("depends_on"))
            if dependencies and existing:
                try:
                    _, changed = _merge_dependencies(existing, dependencies, services_by_title)
                except ValidationError:
                    changed = True
                result.validations.append(
                    {"status": "fail" if changed else "pass", "object_type": "service_dependency", "title": service_spec["title"]}
                )
        for neap_spec in listify(spec.get("neaps")):
            existing = self.client.find_object_by_title("notable_event_aggregation_policy", neap_spec["title"])
            desired = _normalize_neap(neap_spec, existing, default_team) if existing else None
            status = "pass" if existing and desired and _compare_neap(existing, desired) else "fail"
            result.validations.append(
                {"status": status, "object_type": "notable_event_aggregation_policy", "title": neap_spec["title"]}
            )
        result.service_snapshots = {title: deepcopy(payload) for title, payload in services_by_title.items() if payload}
        return result
