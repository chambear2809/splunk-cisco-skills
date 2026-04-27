#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.common import SkillError, load_json  # noqa: E402
from lib.native import NativeWorkflow  # noqa: E402


class OfflineNativeClient:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, dict[str, Any]]] = {}
        self.custom_threshold_links: dict[str, set[tuple[str, str]]] = {}

    def _store(self, object_type: str) -> dict[str, dict[str, Any]]:
        return self.objects.setdefault(object_type, {})

    @staticmethod
    def _label(payload: dict[str, Any]) -> str:
        label = str(payload.get("title") or payload.get("name") or "").strip()
        if not label:
            raise SkillError(f"Offline object is missing title/name: {payload}")
        return label

    def list_objects(self, object_type: str, interface: str = "itoa") -> list[dict[str, Any]]:
        return [deepcopy(value) for value in self._store(object_type).values()]

    def find_object_by_title(self, object_type: str, title: str, interface: str = "itoa") -> dict[str, Any] | None:
        found = self._store(object_type).get(title)
        return deepcopy(found) if found else None

    def find_object_by_field(self, object_type: str, field: str, value: str, interface: str = "itoa") -> dict[str, Any] | None:
        for item in self._store(object_type).values():
            if str(item.get(field) or "") == value:
                return deepcopy(item)
        return None

    def get_object(self, object_type: str, key: str, interface: str = "itoa") -> dict[str, Any] | None:
        for item in self._store(object_type).values():
            if str(item.get("_key") or "") == key:
                return deepcopy(item)
        return None

    def create_object(self, object_type: str, payload: dict[str, Any], interface: str = "itoa") -> dict[str, Any]:
        created = deepcopy(payload)
        created.setdefault("_key", f"{object_type}:{len(self._store(object_type)) + 1}")
        if object_type == "service":
            self._assign_service_kpi_keys(created)
        self._store(object_type)[self._label(created)] = created
        return {"_key": created["_key"]}

    def update_object(self, object_type: str, key: str, payload: dict[str, Any], interface: str = "itoa") -> dict[str, Any]:
        updated = deepcopy(payload)
        updated["_key"] = key
        if object_type == "service":
            self._assign_service_kpi_keys(updated)
        self._store(object_type)[self._label(updated)] = updated
        return {"_key": key}

    def delete_object(self, object_type: str, key: str, interface: str = "itoa") -> dict[str, Any]:
        for label, value in list(self._store(object_type).items()):
            if str(value.get("_key") or "") == key:
                del self._store(object_type)[label]
                return {"_key": key}
        raise SkillError(f"Unknown {object_type} key {key}")

    @staticmethod
    def _assign_service_kpi_keys(service: dict[str, Any]) -> None:
        service_key = str(service.get("_key") or "service")
        for index, kpi in enumerate(service.get("kpis", []), start=1):
            if isinstance(kpi, dict):
                kpi.setdefault("_key", f"{service_key}::kpi::{index}")

    def get_service_template_link(self, service_key: str) -> str | None:
        service = self.get_object("service", service_key)
        return str((service or {}).get("base_service_template_id") or "").strip() or None

    def link_service_to_template(self, service_key: str, template_key: str) -> dict[str, Any]:
        service = self.get_object("service", service_key)
        if not service:
            raise SkillError(f"Unknown service key {service_key}")
        service["base_service_template_id"] = template_key
        self._store("service")[self._label(service)] = service
        return {"_key": service_key}

    def custom_threshold_window_linked_kpis(self, window_key: str) -> dict[str, Any]:
        services: dict[str, list[str]] = {}
        for service_key, kpi_key in sorted(self.custom_threshold_links.get(window_key, set())):
            services.setdefault(service_key, []).append(kpi_key)
        return {"services": [{"_key": service_key, "kpi_ids": kpi_ids} for service_key, kpi_ids in services.items()]}

    def associate_custom_threshold_window_kpis(self, window_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        for service in payload.get("services", []):
            service_key = str(service.get("_key") or "")
            for kpi_id in service.get("kpi_ids", []):
                self.custom_threshold_links.setdefault(window_key, set()).add((service_key, str(kpi_id)))
        return {"_key": window_key}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an offline native ITSI workflow smoke test with no Splunk connection.")
    parser.add_argument("--spec-json", required=True, help="Path to a JSON native spec.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        spec = load_json(args.spec_json)
        client = OfflineNativeClient()
        workflow = NativeWorkflow(client)
        outputs = {}
        for mode in ("preview", "apply", "validate", "export", "inventory", "prune-plan"):
            result = workflow.run(spec, mode)
            outputs[mode] = {
                "failed": result.failed,
                "summary": result.summary(),
                "validations": result.validations,
                "diagnostics": result.diagnostics,
                "export_sections": sorted(result.exports.get("native_spec", {}).keys()) if result.exports else [],
                "inventory_sections": sorted(result.inventory.get("objects", {}).keys()) if result.inventory else [],
                "prune_candidates": len(result.prune_plan.get("candidates", [])) if result.prune_plan else 0,
            }
        client.create_object("service", {"title": "Offline Cleanup Orphan"})
        cleanup_plan = workflow.run(spec, "prune-plan").prune_plan
        cleanup_candidate = next(
            candidate for candidate in cleanup_plan["candidates"] if candidate.get("title") == "Offline Cleanup Orphan"
        )
        cleanup_spec = deepcopy(spec)
        cleanup_spec["cleanup"] = {
            "allow_destroy": True,
            "confirm": "DELETE_UNMANAGED_ITSI_OBJECTS",
            "plan_id": cleanup_plan["plan_id"],
            "max_deletes": 1,
            "candidate_ids": [cleanup_candidate["candidate_id"]],
        }
        cleanup_result = workflow.run(cleanup_spec, "cleanup-apply")
        outputs["cleanup-apply"] = {
            "failed": cleanup_result.failed,
            "summary": cleanup_result.summary(),
            "deleted": [change.title for change in cleanup_result.changes if change.action == "delete"],
            "prune_candidates": len(cleanup_result.prune_plan.get("candidates", [])),
        }
        print(json.dumps(outputs, indent=2, sort_keys=True))
        return 1 if any(item["failed"] for item in outputs.values()) else 0
    except SkillError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
