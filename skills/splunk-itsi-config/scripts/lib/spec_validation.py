from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .common import ValidationError, bool_from_any, listify


SCHEMA_VERSION = 1

COMMON_TOP_LEVEL_KEYS = {
    "schema_version",
    "metadata",
    "connection",
    "itsi",
    "content_library",
    "defaults",
    "packs",
}

NATIVE_LIST_SECTIONS = {
    "teams",
    "entity_types",
    "entity_filter_rules",
    "entity_management_policies",
    "entity_management_rules",
    "data_integration_templates",
    "kpi_base_searches",
    "kpi_threshold_templates",
    "kpi_templates",
    "custom_threshold_windows",
    "custom_content_packs",
    "service_templates",
    "entities",
    "services",
    "custom_threshold_window_links",
    "neaps",
    "event_management_states",
    "correlation_searches",
    "notable_event_email_templates",
    "maintenance_windows",
    "backup_restore_jobs",
    "deep_dives",
    "glass_tables",
    "glass_table_icons",
    "home_views",
    "kpi_entity_thresholds",
    "refresh_queue_jobs",
    "sandboxes",
    "sandbox_services",
    "sandbox_sync_logs",
    "upgrade_readiness_prechecks",
    "summarizations",
    "summarization_feedback",
    "summarization_rules",
    "user_preferences",
    "operational_actions",
}

NATIVE_MAPPING_SECTIONS = {"bulk_apply", "apply", "cleanup", "export", "inventory"}

IDENTITY_BY_SECTION = {
    "correlation_searches": "name",
}

# Fields that can enable writes, disable security controls, or change runtime
# behavior. Every occurrence is parsed strictly so misspellings fail lint.
BOOLEAN_FIELDS = {
    "allow_bulk_update",
    "allow_destroy",
    "allow_dispatch",
    "allow_experimental_api",
    "allow_episode_export_bulk_delete",
    "allow_episode_export_delete",
    "allow_episode_field_change",
    "allow_high_risk_deletes",
    "allow_insecure_http",
    "allow_insecure_tls",
    "allow_large_template_import",
    "allow_lookup_file_replace",
    "allow_lookup_file_upload",
    "allow_non_outputlookup",
    "allow_notable_event_action_execute",
    "allow_operational_action",
    "allow_restore",
    "allow_service_import",
    "allow_system_objects",
    "backfill",
    "bulk_update",
    "create",
    "count_only",
    "disconnect_all",
    "enabled",
    "force_reinstall",
    "include_count_endpoint",
    "include_empty",
    "include_managed_neaps",
    "install_all",
    "install_if_missing",
    "is_entity_breakdown",
    "is_service_entity_filter",
    "isadhoc",
    "links_service_templates",
    "list_episode_exports",
    "list_notable_events",
    "managed",
    "partial",
    "refresh_catalog",
    "require_present",
    "retire_all_retirable",
    "template",
    "use_bulk_update",
    "use_count_endpoints",
    "uses_service_templates",
    "verify_ssl",
}

PLACEHOLDER_PATTERNS = (
    re.compile(r"(?i)replace[-_ ]?with"),
    re.compile(r"(?i)\bchange[-_ ]?me\b"),
    re.compile(r"(?i)\bexample\.com\b"),
    re.compile(r"^<[^>]+>$"),
)

INLINE_SECRET_FIELDS = {
    "password",
    "passwd",
    "session_key",
    "token",
    "api_key",
    "client_secret",
    "secret",
}

OPERATIONAL_RECORD_SECTIONS = {"summarizations", "summarization_feedback"}
EXPERIMENTAL_API_SECTIONS = {
    "entity_management_policies",
    "entity_management_rules",
    "data_integration_templates",
    "refresh_queue_jobs",
    "sandboxes",
    "sandbox_services",
    "sandbox_sync_logs",
    "summarization_rules",
    "upgrade_readiness_prechecks",
    "user_preferences",
}


def _path(parent: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]" if parent else f"[{key}]"
    return f"{parent}.{key}" if parent else key


def _walk(value: Any, parent: str = "") -> list[tuple[str, str | None, Any]]:
    items: list[tuple[str, str | None, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = _path(parent, str(key))
            items.append((child_path, str(key), child))
            items.extend(_walk(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = _path(parent, index)
            items.append((child_path, None, child))
            items.extend(_walk(child, child_path))
    return items


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a mapping.")
    return value


def _mapping_list(value: Any, label: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list of mappings.")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValidationError(f"{label}[{index}] must be a mapping.")
        result.append(item)
    return result


def _validate_schema_version(spec: dict[str, Any], warnings: list[dict[str, str]]) -> None:
    version = spec.get("schema_version")
    if version is None:
        warnings.append(
            {
                "path": "schema_version",
                "message": f"schema_version is omitted; schema {SCHEMA_VERSION} is assumed.",
            }
        )
        return
    if version != SCHEMA_VERSION:
        raise ValidationError(
            f"schema_version must be {SCHEMA_VERSION}; got {version!r}."
        )


def _validate_top_level(spec: dict[str, Any], workflow: str) -> None:
    allowed = set(COMMON_TOP_LEVEL_KEYS)
    if workflow in {"native", "topology"}:
        allowed.update(NATIVE_LIST_SECTIONS)
        allowed.update(NATIVE_MAPPING_SECTIONS)
        allowed.add("topology")
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValidationError(
            "Unknown top-level field(s): "
            + ", ".join(unknown)
            + ". Put version-specific REST fields under an object's payload mapping."
        )


def _validate_shapes(spec: dict[str, Any], workflow: str) -> None:
    for section in ("metadata", "connection", "itsi", "content_library", "defaults"):
        if section in spec:
            _mapping(spec[section], section)
    if workflow in {"native", "topology"}:
        for section in NATIVE_LIST_SECTIONS:
            if section in spec:
                _mapping_list(spec[section], section)
        for section in NATIVE_MAPPING_SECTIONS:
            if section in spec:
                _mapping(spec[section], section)
    if "packs" in spec:
        _mapping_list(spec["packs"], "packs")
    if workflow == "topology" and "topology" in spec:
        _mapping(spec["topology"], "topology")
    itsi = spec.get("itsi") if isinstance(spec.get("itsi"), dict) else {}
    if not bool_from_any(
        itsi.get("require_present"), default=True, field="itsi.require_present"
    ):
        raise ValidationError(
            "itsi.require_present cannot be false: splunk-itsi-config requires an existing ITSI deployment."
        )
    content_library = spec.get("content_library") if isinstance(spec.get("content_library"), dict) else {}
    if spec.get("packs") and not bool_from_any(
        content_library.get("require_present"),
        default=True,
        field="content_library.require_present",
    ):
        raise ValidationError(
            "content_library.require_present cannot be false when packs are declared."
        )


def _validate_boolean_fields(spec: dict[str, Any]) -> None:
    for path, key, value in _walk(spec):
        if key in BOOLEAN_FIELDS:
            bool_from_any(value, field=path)


def _validate_inline_secrets(spec: dict[str, Any]) -> None:
    for path, key, value in _walk(spec):
        if key is None:
            continue
        normalized = key.lower()
        if normalized.endswith(("_env", "_file", "_path")):
            continue
        if normalized in INLINE_SECRET_FIELDS and value is not None and value != "":
            raise ValidationError(
                f"{path} contains an inline secret. Use an *_env or file-backed secret reference."
            )


def _identity(entry: dict[str, Any], section: str) -> str:
    identity_field = IDENTITY_BY_SECTION.get(section, "title")
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    return str(
        entry.get(identity_field)
        or entry.get("title")
        or payload.get(identity_field)
        or payload.get("title")
        or ""
    ).strip()


def _validate_identities(spec: dict[str, Any], workflow: str) -> None:
    if workflow not in {"native", "topology"}:
        return
    title_optional = {"operational_actions", "custom_threshold_window_links"}
    for section in NATIVE_LIST_SECTIONS - title_optional:
        seen: dict[str, int] = {}
        for index, entry in enumerate(_mapping_list(spec.get(section), section)):
            title = _identity(entry, section)
            if not title:
                raise ValidationError(f"{section}[{index}] must define title.")
            normalized = title.casefold()
            if normalized in seen:
                raise ValidationError(
                    f"{section}[{index}].title duplicates {section}[{seen[normalized]}].title ({title!r})."
                )
            seen[normalized] = index

    for service_index, service in enumerate(_mapping_list(spec.get("services"), "services")):
        seen_kpis: dict[str, int] = {}
        for kpi_index, kpi in enumerate(_mapping_list(service.get("kpis"), f"services[{service_index}].kpis")):
            title = str(kpi.get("title") or "").strip()
            if not title:
                raise ValidationError(
                    f"services[{service_index}].kpis[{kpi_index}] must define title."
                )
            normalized = title.casefold()
            if normalized in seen_kpis:
                raise ValidationError(
                    f"services[{service_index}].kpis[{kpi_index}].title duplicates KPI "
                    f"#{seen_kpis[normalized]} in the same service ({title!r})."
                )
            seen_kpis[normalized] = kpi_index


def _validate_entity_teams(spec: dict[str, Any]) -> None:
    for index, entity in enumerate(_mapping_list(spec.get("entities"), "entities")):
        team = entity.get("sec_grp")
        if team not in {None, "", "default_itsi_security_group"}:
            raise ValidationError(
                f"entities[{index}].sec_grp must be default_itsi_security_group; ITSI entities are Global objects."
            )


def _validate_entity_rules(spec: dict[str, Any]) -> None:
    for service_index, service in enumerate(_mapping_list(spec.get("services"), "services")):
        rules = service.get("entity_rules")
        if rules is None:
            continue
        entries = _mapping_list(rules, f"services[{service_index}].entity_rules")
        for rule_index, rule in enumerate(entries):
            label = f"services[{service_index}].entity_rules[{rule_index}]"
            if "rule_items" in rule:
                condition = str(rule.get("rule_condition") or "AND").upper()
                if condition not in {"AND", "OR"}:
                    raise ValidationError(f"{label}.rule_condition must be AND or OR.")
                items = _mapping_list(rule.get("rule_items"), f"{label}.rule_items")
                if not items:
                    raise ValidationError(f"{label}.rule_items must not be empty.")
            elif not str(rule.get("field") or "").strip():
                raise ValidationError(
                    f"{label} must be a canonical rule group or define field/value for the convenience form."
                )


def _dependency_name(value: Any, label: str) -> str:
    if isinstance(value, str):
        name = value.strip()
    elif isinstance(value, dict):
        name = str(value.get("service") or "").strip()
    else:
        raise ValidationError(f"{label} must be a service title or mapping.")
    if not name:
        raise ValidationError(f"{label} must identify a service.")
    return name


def _validate_dependency_graph(spec: dict[str, Any]) -> None:
    services = _mapping_list(spec.get("services"), "services")
    graph: dict[str, list[str]] = defaultdict(list)
    titles = {str(item.get("title") or "").strip() for item in services}
    for service_index, service in enumerate(services):
        title = str(service.get("title") or "").strip()
        for dependency_index, value in enumerate(listify(service.get("depends_on"))):
            dependency = _dependency_name(
                value,
                f"services[{service_index}].depends_on[{dependency_index}]",
            )
            if dependency.casefold() == title.casefold():
                raise ValidationError(f"Service {title!r} cannot depend on itself.")
            if dependency in titles:
                graph[title].append(dependency)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, trail: list[str]) -> None:
        if node in visiting:
            start = trail.index(node) if node in trail else 0
            cycle = trail[start:] + [node]
            raise ValidationError("Service dependency cycle detected: " + " -> ".join(cycle))
        if node in visited:
            return
        visiting.add(node)
        for child in graph.get(node, []):
            visit(child, trail + [node])
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node, [])


def _validate_neap_priorities(spec: dict[str, Any]) -> None:
    for index, neap in enumerate(_mapping_list(spec.get("neaps"), "neaps")):
        payload = neap.get("payload") if isinstance(neap.get("payload"), dict) else {}
        priority = neap.get("priority", payload.get("priority"))
        if priority is None:
            continue
        if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 999:
            raise ValidationError(f"neaps[{index}].priority must be an integer from 0 through 999.")


def _validate_packs(spec: dict[str, Any]) -> None:
    seen: dict[str, int] = {}
    for index, pack in enumerate(_mapping_list(spec.get("packs"), "packs")):
        identity = str(
            pack.get("profile")
            or pack.get("pack_id")
            or pack.get("id")
            or pack.get("catalog_title")
            or pack.get("title")
            or ""
        ).strip()
        if not identity:
            raise ValidationError(
                f"packs[{index}] must define profile, pack_id/id, catalog_title, or title."
            )
        normalized = identity.casefold()
        if normalized in seen:
            raise ValidationError(
                f"packs[{index}] duplicates packs[{seen[normalized]}] ({identity!r})."
            )
        seen[normalized] = index


def _validate_apply_sentinels(spec: dict[str, Any], source_path: str | None) -> None:
    metadata = spec.get("metadata") if isinstance(spec.get("metadata"), dict) else {}
    if bool_from_any(metadata.get("template"), default=False, field="metadata.template"):
        raise ValidationError(
            "Refusing apply because metadata.template is true. Copy the starter, replace every placeholder, "
            "review the preview, then set metadata.template: false."
        )
    if source_path and Path(source_path).name.endswith(".example.yaml"):
        raise ValidationError(
            "Refusing to apply a *.example.yaml file. Copy it to a local reviewed spec first."
        )
    for path, _key, value in _walk(spec):
        if not isinstance(value, str):
            continue
        if any(pattern.search(value.strip()) for pattern in PLACEHOLDER_PATTERNS):
            raise ValidationError(f"Refusing apply because {path} still contains placeholder value {value!r}.")


def _validate_automation_tiers(
    spec: dict[str, Any],
    *,
    for_apply: bool,
    warnings: list[dict[str, str]],
) -> None:
    for path, key, value in _walk(spec):
        if key == "anomaly_detection":
            enabled_value = value.get("enabled") if isinstance(value, dict) else value
            if not bool_from_any(enabled_value, default=False, field=f"{path}.enabled" if isinstance(value, dict) else path):
                continue
            message = (
                "Metric anomaly detection is deprecated in ITSI 4.20+; inventory or migrate it instead of enabling new configuration."
            )
            if for_apply:
                raise ValidationError(f"{path}: {message}")
            warnings.append({"path": path, "message": message})

    if not for_apply:
        return
    present_operational = sorted(section for section in OPERATIONAL_RECORD_SECTIONS if spec.get(section))
    if present_operational:
        raise ValidationError(
            "These sections are operational Event iQ records, not idempotent configuration: "
            + ", ".join(present_operational)
            + ". Use inventory/validate or a separately reviewed operational workflow."
        )
    present_experimental = sorted(section for section in EXPERIMENTAL_API_SECTIONS if spec.get(section))
    metadata = spec.get("metadata") if isinstance(spec.get("metadata"), dict) else {}
    allowed = bool_from_any(
        metadata.get("allow_experimental_api"),
        default=False,
        field="metadata.allow_experimental_api",
    )
    if present_experimental and not allowed:
        raise ValidationError(
            "The following sections use runtime-discovered or non-public schemas and are blocked by default: "
            + ", ".join(present_experimental)
            + ". Prefer export/inventory or set metadata.allow_experimental_api: true only with a target-version live fixture and explicit review."
        )


def validate_spec(
    spec: Any,
    workflow: str,
    *,
    for_apply: bool = False,
    source_path: str | None = None,
    allow_empty: bool = False,
) -> list[dict[str, str]]:
    """Validate an ITSI config specification without network access.

    Returns non-fatal lint warnings. Any unsafe or structurally ambiguous value
    raises :class:`ValidationError` with a field path.
    """

    if workflow not in {"native", "content-packs", "topology"}:
        raise ValidationError(f"Unsupported workflow {workflow!r}.")
    if not isinstance(spec, dict):
        raise ValidationError("The spec root must be a mapping.")
    if not spec and not allow_empty:
        raise ValidationError("The spec is empty.")

    warnings: list[dict[str, str]] = []
    _validate_schema_version(spec, warnings)
    _validate_top_level(spec, workflow)
    _validate_shapes(spec, workflow)
    _validate_boolean_fields(spec)
    _validate_inline_secrets(spec)
    _validate_identities(spec, workflow)
    _validate_entity_teams(spec)
    _validate_entity_rules(spec)
    _validate_dependency_graph(spec)
    _validate_neap_priorities(spec)
    _validate_packs(spec)
    _validate_automation_tiers(spec, for_apply=for_apply, warnings=warnings)
    if for_apply:
        _validate_apply_sentinels(spec, source_path)
    return warnings
