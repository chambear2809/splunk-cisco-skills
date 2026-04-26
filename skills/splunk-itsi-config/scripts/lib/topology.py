from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .common import ValidationError, bool_from_any, canonicalize, compact, deep_merge, listify, subset_matches
from .native import (
    DEFAULT_TEAM,
    _apply_preview_keys,
    _existing_kpis_by_title,
    _merge_dependencies,
    _normalize_kpi,
)


@dataclass
class TopologyChange:
    object_type: str
    title: str
    action: str
    status: str
    detail: str
    key: str | None = None


@dataclass
class TopologyResult:
    mode: str
    changes: list[TopologyChange] = field(default_factory=list)
    validations: list[dict[str, Any]] = field(default_factory=list)
    resolved_nodes: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return any(change.status == "error" for change in self.changes) or any(
            item.get("status") == "fail" for item in self.validations
        )


@dataclass
class ResolvedNode:
    node_id: str
    service: dict[str, Any]
    preview_only: bool = False
    template_key: str | None = None


def _normalize_title_ref(value: Any, label: str, *, require_profile: bool = False) -> dict[str, str | None]:
    if isinstance(value, str):
        title = value.strip()
        if not title:
            raise ValidationError(f"{label} must not be blank.")
        if require_profile:
            raise ValidationError(f"{label} must provide profile and title.")
        return {"profile": None, "title": title}
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a string or mapping.")
    title = str(value.get("title") or "").strip()
    if not title:
        raise ValidationError(f"{label}.title is required.")
    profile = value.get("profile")
    if require_profile and not str(profile or "").strip():
        raise ValidationError(f"{label}.profile is required.")
    normalized_profile = str(profile).strip() if profile is not None else None
    return {"profile": normalized_profile or None, "title": title}


def _normalize_edge_kpis(value: Any, label: str) -> list[str] | None:
    if value is None:
        return None
    titles = [str(item).strip() for item in listify(value)]
    if not titles or any(not item for item in titles):
        raise ValidationError(f"{label} must contain non-empty KPI titles.")
    return titles


def compile_topology(spec: dict[str, Any]) -> dict[str, Any]:
    topology = spec.get("topology") or {}
    roots = listify(topology.get("roots"))
    compiled = {"roots": [], "nodes": {}, "edges": []}
    if not roots:
        return compiled

    def visit(node: Any, path: str, *, parent_id: str | None = None) -> None:
        if not isinstance(node, dict):
            raise ValidationError(f"{path} must be a mapping.")
        if "ref" in node:
            if parent_id is None:
                raise ValidationError(f"{path} cannot use ref at the root level.")
            ref_id = str(node.get("ref") or "").strip()
            if not ref_id:
                raise ValidationError(f"{path}.ref is required.")
            unexpected = sorted(set(node) - {"ref", "kpis"})
            if unexpected:
                raise ValidationError(f"{path} contains unsupported keys for a ref node: {', '.join(unexpected)}.")
            compiled["edges"].append(
                {
                    "parent_id": parent_id,
                    "child_id": ref_id,
                    "kpis": _normalize_edge_kpis(node.get("kpis"), f"{path}.kpis"),
                }
            )
            return

        node_id = str(node.get("id") or "").strip()
        if not node_id:
            raise ValidationError(f"{path}.id is required.")
        if node_id in compiled["nodes"]:
            raise ValidationError(f"topology node id '{node_id}' is declared more than once.")

        has_service = "service" in node
        has_service_ref = "service_ref" in node
        if has_service == has_service_ref:
            raise ValidationError(f"{path} must define exactly one of service or service_ref.")

        service_spec = deepcopy(node.get("service")) if has_service else None
        if service_spec is not None and not isinstance(service_spec, dict):
            raise ValidationError(f"{path}.service must be a mapping.")
        if service_spec is not None:
            title = str(service_spec.get("title") or "").strip()
            if not title:
                raise ValidationError(f"{path}.service.title is required.")

        from_template = node.get("from_template")
        if from_template is not None and not has_service:
            raise ValidationError(f"{path}.from_template requires a service block.")
        if from_template is not None:
            conflicting = sorted({"depends_on", "entity_rules", "kpis"} & set(service_spec or {}))
            if conflicting:
                raise ValidationError(
                    f"{path}.service cannot define {', '.join(conflicting)} when from_template is used."
                )

        compiled["nodes"][node_id] = {
            "id": node_id,
            "service": service_spec,
            "service_ref": _normalize_title_ref(node.get("service_ref"), f"{path}.service_ref")
            if has_service_ref
            else None,
            "from_template": _normalize_title_ref(from_template, f"{path}.from_template", require_profile=True)
            if from_template is not None
            else None,
        }
        if parent_id is None:
            compiled["roots"].append(node_id)
        else:
            compiled["edges"].append(
                {
                    "parent_id": parent_id,
                    "child_id": node_id,
                    "kpis": _normalize_edge_kpis(node.get("kpis"), f"{path}.kpis"),
                }
            )
        for index, child in enumerate(listify(node.get("children"))):
            visit(child, f"{path}.children[{index}]", parent_id=node_id)

    for index, root in enumerate(roots):
        visit(root, f"topology.roots[{index}]")

    for edge in compiled["edges"]:
        if edge["child_id"] not in compiled["nodes"]:
            raise ValidationError(
                f"topology references node id '{edge['child_id']}', but no node with that id was declared."
            )
        if edge["parent_id"] == edge["child_id"]:
            raise ValidationError(f"topology node '{edge['parent_id']}' cannot depend on itself.")

    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in compiled["edges"]:
        adjacency[edge["parent_id"]].append(edge["child_id"])
    visiting: set[str] = set()
    visited: set[str] = set()

    def check_cycles(node_id: str, trail: list[str]) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            cycle = " -> ".join(trail + [node_id])
            raise ValidationError(f"topology contains a dependency cycle: {cycle}.")
        visiting.add(node_id)
        for child_id in adjacency.get(node_id, []):
            check_cycles(child_id, trail + [node_id])
        visiting.remove(node_id)
        visited.add(node_id)

    for root_id in compiled["roots"]:
        check_cycles(root_id, [])
    return compiled


def validate_topology_pack_references(compiled: dict[str, Any], pack_profiles: list[str]) -> None:
    declared_profiles = {profile for profile in pack_profiles if profile}
    referenced_profiles: set[str] = set()
    for node in compiled.get("nodes", {}).values():
        for key in ("service_ref", "from_template"):
            reference = node.get(key)
            if isinstance(reference, dict) and reference.get("profile"):
                referenced_profiles.add(str(reference["profile"]))
    missing_profiles = sorted(referenced_profiles - declared_profiles)
    if missing_profiles:
        raise ValidationError(
            "topology references content-pack profile(s) that are not present in packs: "
            + ", ".join(missing_profiles)
        )


def _pack_contexts_by_profile(pack_contexts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for context in pack_contexts:
        profile = str(context.get("profile") or "").strip()
        if not profile:
            continue
        if profile in contexts:
            raise ValidationError(f"Content-pack profile '{profile}' is declared more than once in this run.")
        contexts[profile] = context
    return contexts


def _title_candidates(reference: dict[str, str | None], pack_contexts: dict[str, dict[str, Any]]) -> list[str]:
    title = str(reference["title"] or "").strip()
    candidates: list[str] = []
    profile = str(reference.get("profile") or "").strip()
    if profile:
        context = pack_contexts.get(profile)
        if not context:
            raise ValidationError(
                f"topology references content-pack profile '{profile}', but that profile is not present in packs."
            )
        prefix = str(context.get("pack_spec", {}).get("prefix") or "")
        if prefix:
            candidates.append(f"{prefix}{title}")
    candidates.append(title)
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _preview_items(preview_payload: Any, keys: list[str]) -> list[dict[str, Any]]:
    if not isinstance(preview_payload, dict):
        return []
    items: list[dict[str, Any]] = []
    for key in keys:
        value = preview_payload.get(key)
        if isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
    return items


def _preview_title_exists(preview_payload: Any, keys: list[str], title: str) -> bool:
    for item in _preview_items(preview_payload, keys):
        if str(item.get("title") or "").strip() == title:
            return True
    return False


def _preview_item(preview_payload: Any, keys: list[str], title: str) -> dict[str, Any] | None:
    for item in _preview_items(preview_payload, keys):
        if str(item.get("title") or "").strip() == title:
            return deepcopy(item)
    return None


def _kpi_titles_from_payload(payload: dict[str, Any] | None) -> list[str]:
    titles: list[str] = []
    for kpi in listify((payload or {}).get("kpis")):
        title = str(kpi.get("title") or "").strip() if isinstance(kpi, dict) else ""
        if title and title not in titles:
            titles.append(title)
    return titles


def _merge_missing_kpi_titles(payload: dict[str, Any], kpi_titles: list[str]) -> dict[str, Any]:
    if not kpi_titles:
        return deepcopy(payload)
    merged = deepcopy(payload)
    existing_titles = set(_kpi_titles_from_payload(merged))
    kpis = [deepcopy(kpi) for kpi in listify(merged.get("kpis")) if isinstance(kpi, dict)]
    for title in kpi_titles:
        if title not in existing_titles:
            kpis.append({"title": title})
            existing_titles.add(title)
    if kpis:
        merged["kpis"] = kpis
    return merged


def _build_service_payload(
    service_spec: dict[str, Any],
    *,
    existing: dict[str, Any] | None,
    default_team: str,
    template_key: str | None = None,
) -> dict[str, Any]:
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
    if "kpis" in service_spec:
        existing_kpis = _existing_kpis_by_title(existing or {})
        desired_kpis: list[dict[str, Any]] = []
        desired_titles: set[str] = set()
        for kpi_spec in listify(service_spec.get("kpis")):
            desired_titles.add(kpi_spec["title"])
            desired_kpis.append(_normalize_kpi(kpi_spec, existing_kpis.get(kpi_spec["title"]), service_spec["title"]))
        for title, kpi in existing_kpis.items():
            if title not in desired_titles:
                desired_kpis.append(kpi)
        payload["kpis"] = desired_kpis
    payload = deep_merge(payload, service_spec.get("payload", {}))
    if template_key:
        payload["base_service_template_id"] = template_key
    return compact(payload)


def _service_subset(
    service_spec: dict[str, Any],
    desired: dict[str, Any],
    *,
    existing_present: bool,
    template_key: str | None = None,
) -> dict[str, Any]:
    expected: dict[str, Any] = {"title": desired.get("title")}
    if not existing_present or "description" in service_spec:
        expected["description"] = desired.get("description", "")
    if not existing_present or "sec_grp" in service_spec:
        expected["sec_grp"] = desired.get("sec_grp")
    if "enabled" in service_spec:
        expected["enabled"] = desired.get("enabled")
    if "entity_rules" in service_spec:
        expected["entity_rules"] = desired.get("entity_rules")
    if "service_tags" in service_spec:
        expected["service_tags"] = desired.get("service_tags")
    if "kpis" in service_spec:
        expected["kpis"] = [
            compact(
                {
                    "title": kpi.get("title"),
                    "description": kpi.get("description", ""),
                    "type": kpi.get("type"),
                    "base_search": kpi.get("base_search"),
                    "search_type": kpi.get("search_type"),
                    "threshold_field": kpi.get("threshold_field"),
                    "aggregate_statop": kpi.get("aggregate_statop"),
                    "entity_statop": kpi.get("entity_statop"),
                    "entity_id_fields": kpi.get("entity_id_fields"),
                    "entity_breakdown_id_field": kpi.get("entity_breakdown_id_field"),
                    "search_alert_earliest": kpi.get("search_alert_earliest"),
                    "aggregate_thresholds": kpi.get("aggregate_thresholds"),
                    "entity_thresholds": kpi.get("entity_thresholds"),
                    "urgency": kpi.get("urgency"),
                    "unit": kpi.get("unit"),
                    "alert_on": kpi.get("alert_on"),
                    "alert_period": kpi.get("alert_period"),
                    "alert_lag": kpi.get("alert_lag"),
                }
            )
            for kpi in listify(desired.get("kpis"))
            if kpi.get("title")
        ]
    payload_fields = set(service_spec.get("payload", {}))
    for field_name in payload_fields:
        expected[field_name] = deepcopy(desired.get(field_name))
    if template_key:
        expected["base_service_template_id"] = template_key
    return compact(expected)


def _matches_service(
    existing: dict[str, Any],
    desired: dict[str, Any],
    service_spec: dict[str, Any],
    *,
    template_key: str | None = None,
) -> bool:
    expected = _service_subset(service_spec, desired, existing_present=True, template_key=template_key)
    return subset_matches(canonicalize(existing), canonicalize(expected))


def _preview_service(title: str, *, source: str, kpi_titles: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"object_type": "service", "title": title, "source": source}
    if kpi_titles:
        payload["kpis"] = [
            {"title": kpi_title, "_key": f"preview-service::{title}::kpi::{kpi_title}"}
            for kpi_title in kpi_titles
        ]
    return _apply_preview_keys(payload)


class ServiceTopologyWorkflow:
    def __init__(self, client: Any):
        self.client = client

    def run(
        self,
        spec: dict[str, Any],
        mode: str,
        *,
        pack_contexts: list[dict[str, Any]],
        native_service_snapshots: dict[str, dict[str, Any]] | None = None,
    ) -> TopologyResult:
        if mode not in {"preview", "apply", "validate"}:
            raise ValidationError(f"Unsupported topology mode '{mode}'.")
        compiled = compile_topology(spec)
        result = TopologyResult(mode=mode)
        if not compiled["nodes"]:
            return result

        default_team = str(spec.get("defaults", {}).get("sec_grp") or DEFAULT_TEAM)
        pack_context_map = _pack_contexts_by_profile(pack_contexts)
        services_by_title = {title: deepcopy(payload) for title, payload in (native_service_snapshots or {}).items()}
        resolved_nodes: dict[str, ResolvedNode] = {}
        if mode == "apply":
            self.preflight_apply(
                spec,
                pack_contexts=pack_contexts,
                native_service_snapshots=native_service_snapshots,
                require_live_templates=True,
            )

        for node_id, node in compiled["nodes"].items():
            resolved = self._resolve_node(
                node,
                mode=mode,
                default_team=default_team,
                services_by_title=services_by_title,
                pack_contexts=pack_context_map,
                result=result,
            )
            if resolved.service["title"] in {
                item.service["title"]
                for existing_id, item in resolved_nodes.items()
                if existing_id != node_id
            }:
                raise ValidationError(
                    f"topology resolves multiple node ids to service '{resolved.service['title']}'. Reuse the node via ref instead."
                )
            services_by_title[resolved.service["title"]] = deepcopy(resolved.service)
            resolved_nodes[node_id] = resolved

        self._apply_edges(
            compiled["edges"],
            mode=mode,
            result=result,
            resolved_nodes=resolved_nodes,
            services_by_title=services_by_title,
        )
        result.resolved_nodes = {node_id: deepcopy(resolved.service) for node_id, resolved in resolved_nodes.items()}
        return result

    def preflight_apply(
        self,
        spec: dict[str, Any],
        *,
        pack_contexts: list[dict[str, Any]],
        native_service_snapshots: dict[str, dict[str, Any]] | None = None,
        require_live_templates: bool = True,
    ) -> None:
        compiled = compile_topology(spec)
        if not compiled["nodes"]:
            return

        default_team = str(spec.get("defaults", {}).get("sec_grp") or DEFAULT_TEAM)
        pack_context_map = _pack_contexts_by_profile(pack_contexts)
        services_by_title = {title: deepcopy(payload) for title, payload in (native_service_snapshots or {}).items()}
        resolved_nodes = self._resolve_planned_nodes(
            compiled,
            mode="plan" if require_live_templates else "preview",
            default_team=default_team,
            pack_contexts=pack_context_map,
            services_by_title=services_by_title,
        )
        self._preflight_edges(compiled["edges"], resolved_nodes=resolved_nodes, services_by_title=services_by_title)

    def _resolve_planned_nodes(
        self,
        compiled: dict[str, Any],
        *,
        mode: str,
        default_team: str,
        pack_contexts: dict[str, dict[str, Any]],
        services_by_title: dict[str, dict[str, Any]],
    ) -> dict[str, ResolvedNode]:
        resolved_nodes: dict[str, ResolvedNode] = {}
        result = TopologyResult(mode="apply")
        for node_id, node in compiled["nodes"].items():
            resolved = self._resolve_node(
                node,
                mode=mode,
                default_team=default_team,
                services_by_title=services_by_title,
                pack_contexts=pack_contexts,
                result=result,
            )
            if resolved.service["title"] in {
                item.service["title"]
                for existing_id, item in resolved_nodes.items()
                if existing_id != node_id
            }:
                raise ValidationError(
                    f"topology resolves multiple node ids to service '{resolved.service['title']}'. Reuse the node via ref instead."
                )
            services_by_title[resolved.service["title"]] = deepcopy(resolved.service)
            resolved_nodes[node_id] = resolved
        return resolved_nodes

    def _resolve_node(
        self,
        node: dict[str, Any],
        *,
        mode: str,
        default_team: str,
        services_by_title: dict[str, dict[str, Any]],
        pack_contexts: dict[str, dict[str, Any]],
        result: TopologyResult,
    ) -> ResolvedNode:
        if node.get("service_ref") is not None:
            return self._resolve_service_ref(
                node,
                mode=mode,
                services_by_title=services_by_title,
                pack_contexts=pack_contexts,
            )
        return self._materialize_service(
            node,
            mode=mode,
            default_team=default_team,
            services_by_title=services_by_title,
            pack_contexts=pack_contexts,
            result=result,
        )

    def _resolve_service_ref(
        self,
        node: dict[str, Any],
        *,
        mode: str,
        services_by_title: dict[str, dict[str, Any]],
        pack_contexts: dict[str, dict[str, Any]],
    ) -> ResolvedNode:
        reference = node["service_ref"]
        candidates = _title_candidates(reference, pack_contexts)
        for title in candidates:
            if title in services_by_title:
                payload = deepcopy(services_by_title[title])
                return ResolvedNode(
                    node["id"],
                    payload,
                    preview_only=str(payload.get("_key") or "").startswith("preview-service::"),
                )

        live = self.client.find_object_by_titles("service", candidates)
        if live:
            return ResolvedNode(node["id"], live, preview_only=False)
        if mode != "preview":
            raise ValidationError(
                f"Topology node '{node['id']}' could not resolve service reference '{reference['title']}'. "
                "In apply or validate mode, service_ref must point to an existing ITSI service or to a service "
                "created elsewhere in this spec. For a new starter topology, run preview first, then apply to "
                "create the services before running validate."
            )

        profile = str(reference.get("profile") or "").strip()
        if profile:
            context = pack_contexts[profile]
            preview_payload = context.get("preview")
            logical_title = str(reference["title"])
            preview_item = _preview_item(preview_payload, ["service", "services"], logical_title)
            if not preview_item:
                raise ValidationError(
                    f"Topology node '{node['id']}' could not resolve content-pack service '{logical_title}' in preview."
                )
            preview_title = _title_candidates(reference, pack_contexts)[0]
            return ResolvedNode(
                node["id"],
                _preview_service(
                    preview_title,
                    source=f"content-pack:{profile}",
                    kpi_titles=_kpi_titles_from_payload(preview_item),
                ),
                preview_only=True,
            )

        raise ValidationError(f"Topology node '{node['id']}' could not resolve service '{reference['title']}'.")

    def _resolve_template(
        self,
        reference: dict[str, str | None],
        *,
        mode: str,
        pack_contexts: dict[str, dict[str, Any]],
    ) -> tuple[str | None, bool, list[str]]:
        candidates = _title_candidates(reference, pack_contexts)
        live = self.client.find_object_by_titles("base_service_template", candidates)
        if live:
            return str(live.get("_key") or ""), False, _kpi_titles_from_payload(live)
        if mode != "preview":
            raise ValidationError(
                f"Topology could not resolve service template '{reference['title']}' for profile '{reference['profile']}'."
            )
        preview_payload = pack_contexts[str(reference["profile"])].get("preview")
        preview_item = _preview_item(preview_payload, ["service_template", "service_templates"], str(reference["title"]))
        if not preview_item:
            raise ValidationError(
                f"Topology preview could not resolve service template '{reference['title']}' for profile '{reference['profile']}'."
            )
        return None, True, _kpi_titles_from_payload(preview_item)

    def _materialize_service(
        self,
        node: dict[str, Any],
        *,
        mode: str,
        default_team: str,
        services_by_title: dict[str, dict[str, Any]],
        pack_contexts: dict[str, dict[str, Any]],
        result: TopologyResult,
    ) -> ResolvedNode:
        service_spec = deepcopy(node["service"])
        title = service_spec["title"]
        existing = deepcopy(services_by_title.get(title) or self.client.find_object_by_title("service", title))
        template_reference = node.get("from_template")
        template_key: str | None = None
        preview_template = False
        preview_template_kpis: list[str] = []
        if template_reference is not None:
            template_key, preview_template, preview_template_kpis = self._resolve_template(
                template_reference,
                mode=mode,
                pack_contexts=pack_contexts,
            )

        if mode == "preview":
            if existing:
                desired = _build_service_payload(service_spec, existing=existing, default_team=default_team)
                if template_reference is not None and preview_template and not service_spec.get("kpis"):
                    desired = _merge_missing_kpi_titles(desired, preview_template_kpis)
                action = "noop" if _matches_service(existing, desired, service_spec) else "update"
                detail = "Service instance already matches." if action == "noop" else "Would update service instance."
                result.changes.append(TopologyChange("service_instance", title, action, "ok", detail, key=existing.get("_key")))
                if template_reference is not None:
                    if preview_template:
                        action = "update"
                        detail = "Would update service template link after the template is installed."
                    else:
                        current_template = str(existing.get("base_service_template_id") or "").strip()
                        if existing.get("_key") and not str(existing.get("_key")).startswith("preview-service::"):
                            current_template = self.client.get_service_template_link(existing["_key"]) or current_template
                        action = "noop" if current_template == (template_key or current_template) else "update"
                        detail = "Service template already matches." if action == "noop" else "Would update service template link."
                    result.changes.append(
                        TopologyChange("service_template_link", title, action, "ok", detail, key=existing.get("_key"))
                    )
                return ResolvedNode(node["id"], _apply_preview_keys(desired), preview_only=False, template_key=template_key)

            preview_service = _build_service_payload(service_spec, existing=None, default_team=default_team, template_key=template_key)
            if preview_template_kpis and not preview_service.get("kpis"):
                preview_service["kpis"] = [{"title": kpi_title} for kpi_title in preview_template_kpis]
            result.changes.append(
                TopologyChange("service_instance", title, "create", "ok", "Would create service instance.", key=None)
            )
            if template_reference is not None:
                detail = "Would create service from template." if preview_template else "Would link service to template on create."
                result.changes.append(TopologyChange("service_template_link", title, "create", "ok", detail, key=None))
            return ResolvedNode(node["id"], _apply_preview_keys(preview_service), preview_only=True, template_key=template_key)

        if mode == "plan":
            desired = _build_service_payload(
                service_spec,
                existing=existing,
                default_team=default_team,
                template_key=template_key if not existing else None,
            )
            if template_reference is not None and preview_template_kpis and not service_spec.get("kpis"):
                desired = _merge_missing_kpi_titles(desired, preview_template_kpis)
            return ResolvedNode(
                node["id"],
                _apply_preview_keys(desired),
                preview_only=not bool(existing),
                template_key=template_key,
            )

        if mode == "validate":
            if not existing:
                result.validations.append({"status": "fail", "object_type": "service_instance", "title": title})
                if template_reference is not None:
                    result.validations.append({"status": "fail", "object_type": "service_template_link", "title": title})
                return ResolvedNode(node["id"], _preview_service(title, source="validate-missing"), preview_only=True, template_key=template_key)
            desired = _build_service_payload(service_spec, existing=existing, default_team=default_team)
            service_ok = _matches_service(existing, desired, service_spec)
            result.validations.append(
                {"status": "pass" if service_ok else "fail", "object_type": "service_instance", "title": title}
            )
            if template_reference is not None:
                linked_key = self.client.get_service_template_link(existing["_key"])
                result.validations.append(
                    {
                        "status": "pass" if linked_key == template_key else "fail",
                        "object_type": "service_template_link",
                        "title": title,
                    }
                )
            return ResolvedNode(node["id"], existing, preview_only=False, template_key=template_key)

        desired = _build_service_payload(
            service_spec,
            existing=existing,
            default_team=default_team,
            template_key=template_key if not existing else None,
        )
        if not existing:
            created = self.client.create_object("service", desired)
            live = self.client.get_object("service", created.get("_key")) or deep_merge(desired, created)
            result.changes.append(
                TopologyChange("service_instance", title, "create", "ok", "Created service instance.", key=live.get("_key"))
            )
            if template_reference is not None:
                result.changes.append(
                    TopologyChange(
                        "service_template_link",
                        title,
                        "create",
                        "ok",
                        "Created service from template.",
                        key=live.get("_key"),
                    )
                )
            return ResolvedNode(node["id"], live, preview_only=False, template_key=template_key)

        if _matches_service(existing, desired, service_spec):
            result.changes.append(
                TopologyChange("service_instance", title, "noop", "ok", "Service instance already matches.", key=existing.get("_key"))
            )
            live = existing
        else:
            self.client.update_object("service", existing["_key"], desired)
            live = self.client.get_object("service", existing["_key"]) or desired
            result.changes.append(
                TopologyChange("service_instance", title, "update", "ok", "Updated service instance.", key=existing.get("_key"))
            )

        if template_reference is not None:
            linked_key = self.client.get_service_template_link(live["_key"])
            if linked_key == template_key:
                result.changes.append(
                    TopologyChange("service_template_link", title, "noop", "ok", "Service template already matches.", key=live.get("_key"))
                )
            else:
                self.client.link_service_to_template(live["_key"], template_key or "")
                live = self.client.get_object("service", live["_key"]) or live
                result.changes.append(
                    TopologyChange("service_template_link", title, "update", "ok", "Updated service template link.", key=live.get("_key"))
                )
        return ResolvedNode(node["id"], live, preview_only=False, template_key=template_key)

    def _apply_edges(
        self,
        edges: list[dict[str, Any]],
        *,
        mode: str,
        result: TopologyResult,
        resolved_nodes: dict[str, ResolvedNode],
        services_by_title: dict[str, dict[str, Any]],
    ) -> None:
        edges_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            edges_by_parent[edge["parent_id"]].append(edge)

        for parent_id, child_edges in edges_by_parent.items():
            parent = resolved_nodes[parent_id]
            parent_title = parent.service["title"]
            if mode == "preview" and (parent.preview_only or any(resolved_nodes[edge["child_id"]].preview_only for edge in child_edges)):
                for edge in child_edges:
                    self._validate_edge_kpis(parent_title, resolved_nodes[edge["child_id"]].service, edge.get("kpis"))
                result.changes.append(
                    TopologyChange(
                        "service_dependency",
                        parent_title,
                        "update",
                        "ok",
                        "Would update service dependencies after materializing topology services.",
                        key=parent.service.get("_key"),
                    )
                )
                continue

            dependency_specs = [
                {
                    "service": resolved_nodes[edge["child_id"]].service["title"],
                    **({"kpis": edge["kpis"]} if edge.get("kpis") else {}),
                }
                for edge in child_edges
            ]
            payload, changed = _merge_dependencies(parent.service, dependency_specs, services_by_title)
            if mode == "validate":
                result.validations.append(
                    {
                        "status": "fail" if changed else "pass",
                        "object_type": "service_dependency",
                        "title": parent_title,
                    }
                )
                continue
            if not changed:
                result.changes.append(
                    TopologyChange(
                        "service_dependency",
                        parent_title,
                        "noop",
                        "ok",
                        "Dependencies already match.",
                        key=parent.service.get("_key"),
                    )
                )
                continue
            self.client.update_object("service", parent.service["_key"], payload)
            refreshed = self.client.get_object("service", parent.service["_key"]) or payload
            parent.service = refreshed
            services_by_title[parent_title] = deepcopy(refreshed)
            result.changes.append(
                TopologyChange(
                    "service_dependency",
                    parent_title,
                    "update",
                    "ok",
                    "Updated service dependencies." if mode == "apply" else "Would update service dependencies.",
                    key=parent.service.get("_key"),
                )
            )

    def _validate_edge_kpis(self, parent_title: str, child_service: dict[str, Any], selected_kpis: list[str] | None) -> None:
        if not selected_kpis:
            return
        available_titles = _kpi_titles_from_payload(child_service)
        child_title = str(child_service.get("title") or "<unknown>")
        if not available_titles:
            raise ValidationError(
                f"Preview cannot validate KPI selection for dependency '{parent_title}' -> '{child_title}' because no KPI titles were available for the child service."
            )
        missing_titles = [title for title in selected_kpis if title not in available_titles]
        if missing_titles:
            raise ValidationError(
                f"Dependency '{parent_title}' -> '{child_title}' references unknown KPI(s): {', '.join(sorted(missing_titles))}."
            )

    def _preflight_edges(
        self,
        edges: list[dict[str, Any]],
        *,
        resolved_nodes: dict[str, ResolvedNode],
        services_by_title: dict[str, dict[str, Any]],
    ) -> None:
        edges_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            edges_by_parent[edge["parent_id"]].append(edge)

        for parent_id, child_edges in edges_by_parent.items():
            parent = resolved_nodes[parent_id]
            dependency_specs = []
            for edge in child_edges:
                child = resolved_nodes[edge["child_id"]]
                self._validate_edge_kpis(parent.service["title"], child.service, edge.get("kpis"))
                dependency_specs.append(
                    {
                        "service": child.service["title"],
                        **({"kpis": edge["kpis"]} if edge.get("kpis") else {}),
                    }
                )
            _merge_dependencies(parent.service, dependency_specs, services_by_title)
