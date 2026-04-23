from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "splunk-itsi-config" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.common import ValidationError
from lib.native import NativeWorkflow


class FakeNativeClient:
    def __init__(self, objects: dict[str, dict[str, dict]] | None = None):
        self.objects = copy.deepcopy(objects or {})
        self.operations: list[tuple[str, str, str]] = []

    def _object_store(self, object_type: str) -> dict[str, dict]:
        return self.objects.setdefault(object_type, {})

    def _assign_service_kpi_keys(self, payload: dict, existing: dict | None = None) -> dict:
        normalized = copy.deepcopy(payload)
        existing_titles = {
            kpi.get("title"): kpi.get("_key")
            for kpi in (existing or {}).get("kpis", [])
            if kpi.get("title") and kpi.get("_key")
        }
        next_index = 1
        for kpi in normalized.get("kpis", []):
            if kpi.get("_key"):
                continue
            if kpi.get("title") in existing_titles:
                kpi["_key"] = existing_titles[kpi["title"]]
                continue
            kpi["_key"] = f"{normalized['_key']}::kpi::{next_index}"
            next_index += 1
        return normalized

    def find_object_by_title(self, object_type: str, title: str) -> dict | None:
        found = self._object_store(object_type).get(title)
        return copy.deepcopy(found) if found else None

    def get_object(self, object_type: str, key: str) -> dict | None:
        for obj in self._object_store(object_type).values():
            if obj.get("_key") == key:
                return copy.deepcopy(obj)
        return None

    def create_object(self, object_type: str, payload: dict) -> dict:
        store = self._object_store(object_type)
        created = copy.deepcopy(payload)
        created["_key"] = created.get("_key") or f"{object_type}:{len(store) + 1}"
        if object_type == "service":
            created = self._assign_service_kpi_keys(created)
        store[created["title"]] = created
        self.operations.append(("create", object_type, created["title"]))
        return {"_key": created["_key"]}

    def update_object(self, object_type: str, key: str, payload: dict) -> dict:
        store = self._object_store(object_type)
        existing = next((value for value in store.values() if value.get("_key") == key), None)
        updated = copy.deepcopy(payload)
        updated["_key"] = key
        if object_type == "service":
            updated = self._assign_service_kpi_keys(updated, existing=existing)
        store[updated["title"]] = updated
        self.operations.append(("update", object_type, updated["title"]))
        return {"_key": key}


class NativeWorkflowTests(unittest.TestCase):
    def test_preview_identifies_new_objects_without_mutating(self) -> None:
        client = FakeNativeClient()
        spec = {
            "entities": [
                {
                    "title": "edge-sw-01",
                    "description": "Edge switch",
                    "identifier_fields": [{"field": "host", "value": "edge-sw-01"}],
                }
            ],
            "services": [
                {
                    "title": "Network Edge",
                    "description": "Edge network service",
                    "entity_rules": [{"field": "host", "value": "edge-*"}],
                    "kpis": [
                        {
                            "title": "Errors",
                            "search": "index=net | stats sum(errors) as errors by host",
                            "threshold_field": "errors",
                            "aggregate_statop": "sum",
                        }
                    ],
                }
            ],
            "neaps": [{"title": "Example NEAP", "payload": {"rule_type": "custom"}}],
        }

        result = NativeWorkflow(client).run(spec, "preview")

        self.assertEqual(result.summary()["created"], 3)
        self.assertEqual(client.operations, [])
        self.assertEqual([change.action for change in result.changes], ["create", "create", "create"])

    def test_preview_is_idempotent_for_matching_objects(self) -> None:
        client = FakeNativeClient(
            {
                "entity": {
                    "edge-sw-01": {
                        "_key": "entity:1",
                        "title": "edge-sw-01",
                        "description": "Edge switch",
                        "sec_grp": "default_itsi_security_group",
                        "identifier": {"fields": ["host"], "values": ["edge-sw-01"]},
                    }
                },
                "service": {
                    "Network Edge": {
                        "_key": "service:1",
                        "title": "Network Edge",
                        "description": "Edge network service",
                        "sec_grp": "default_itsi_security_group",
                        "entity_rules": [{"field": "host", "value": "edge-*"}],
                        "kpis": [
                            {
                                "_key": "service:1::kpi::1",
                                "title": "Errors",
                                "description": "",
                                "search": "index=net | stats sum(errors) as errors by host",
                                "threshold_field": "errors",
                                "aggregate_statop": "sum",
                            }
                        ],
                    }
                },
                "notable_event_aggregation_policy": {
                    "Example NEAP": {
                        "_key": "neap:1",
                        "title": "Example NEAP",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "rule_type": "custom",
                    }
                },
            }
        )
        spec = {
            "entities": [
                {
                    "title": "edge-sw-01",
                    "description": "Edge switch",
                    "identifier_fields": [{"field": "host", "value": "edge-sw-01"}],
                }
            ],
            "services": [
                {
                    "title": "Network Edge",
                    "description": "Edge network service",
                    "entity_rules": [{"field": "host", "value": "edge-*"}],
                    "kpis": [
                        {
                            "title": "Errors",
                            "search": "index=net | stats sum(errors) as errors by host",
                            "threshold_field": "errors",
                            "aggregate_statop": "sum",
                        }
                    ],
                }
            ],
            "neaps": [{"title": "Example NEAP", "payload": {"rule_type": "custom"}}],
        }

        result = NativeWorkflow(client).run(spec, "preview")

        self.assertTrue(all(change.action == "noop" for change in result.changes))
        self.assertEqual(result.summary()["unchanged"], 3)

    def test_dependencies_are_applied_in_second_pass(self) -> None:
        client = FakeNativeClient()
        spec = {
            "services": [
                {
                    "title": "WAN Core",
                    "description": "Dependency service",
                    "kpis": [
                        {
                            "title": "Availability",
                            "search": "index=net | stats count as availability by host",
                            "threshold_field": "availability",
                            "aggregate_statop": "avg",
                        }
                    ],
                },
                {
                    "title": "Network Edge",
                    "description": "Primary service",
                    "kpis": [
                        {
                            "title": "Errors",
                            "search": "index=net | stats sum(errors) as errors by host",
                            "threshold_field": "errors",
                            "aggregate_statop": "sum",
                        }
                    ],
                    "depends_on": [{"service": "WAN Core", "kpis": ["Availability"]}],
                },
            ]
        }

        result = NativeWorkflow(client).run(spec, "apply")

        self.assertEqual(
            client.operations,
            [
                ("create", "service", "WAN Core"),
                ("create", "service", "Network Edge"),
                ("update", "service", "Network Edge"),
            ],
        )
        edge = client.find_object_by_title("service", "Network Edge")
        core = client.find_object_by_title("service", "WAN Core")
        self.assertEqual(edge["services_depends_on"][0]["service_id"], core["_key"])
        self.assertEqual(edge["services_depends_on"][0]["kpis_depending_on"], [core["kpis"][0]["_key"]])
        self.assertTrue(any(change.object_type == "service_dependency" and change.action == "update" for change in result.changes))

    def test_preview_dependencies_use_desired_service_payload_for_existing_services(self) -> None:
        client = FakeNativeClient(
            {
                "service": {
                    "DB": {
                        "_key": "service:db",
                        "title": "DB",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "kpis": [{"_key": "service:db::kpi::old", "title": "Old KPI", "threshold_field": "old_kpi"}],
                    },
                    "API": {
                        "_key": "service:api",
                        "title": "API",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "kpis": [],
                    },
                }
            }
        )
        spec = {
            "services": [
                {"title": "DB", "kpis": [{"title": "New KPI", "threshold_field": "new_kpi"}]},
                {"title": "API", "depends_on": [{"service": "DB", "kpis": ["New KPI"]}]},
            ]
        }

        result = NativeWorkflow(client).run(spec, "preview")

        self.assertEqual(client.operations, [])
        self.assertTrue(any(change.object_type == "service_dependency" and change.action == "update" for change in result.changes))

    def test_validate_resolves_dependencies_to_live_services_outside_the_spec(self) -> None:
        client = FakeNativeClient(
            {
                "service": {
                    "External DB": {
                        "_key": "service:db",
                        "title": "External DB",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "kpis": [{"_key": "service:db::kpi::1", "title": "Availability", "threshold_field": "availability"}],
                    },
                    "API": {
                        "_key": "service:api",
                        "title": "API",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "kpis": [],
                        "services_depends_on": [{"service_id": "service:db", "kpis_depending_on": ["service:db::kpi::1"]}],
                    },
                }
            }
        )
        spec = {"services": [{"title": "API", "depends_on": [{"service": "External DB", "kpis": ["Availability"]}]}]}

        result = NativeWorkflow(client).run(spec, "validate")

        self.assertEqual(
            result.validations,
            [
                {"status": "pass", "object_type": "service", "title": "API"},
                {"status": "pass", "object_type": "service_dependency", "title": "API"},
            ],
        )

    def test_managed_neap_is_protected(self) -> None:
        client = FakeNativeClient(
            {
                "notable_event_aggregation_policy": {
                    "Built In NEAP": {
                        "_key": "neap:1",
                        "title": "Built In NEAP",
                        "description": "Managed policy",
                        "source_itsi_da": "itsi-packaged-module",
                    }
                }
            }
        )
        spec = {"neaps": [{"title": "Built In NEAP", "payload": {"rule_type": "custom"}}]}

        with self.assertRaises(ValidationError):
            NativeWorkflow(client).run(spec, "preview")

    def test_validate_marks_missing_objects_as_fail(self) -> None:
        client = FakeNativeClient()
        spec = {"services": [{"title": "Missing Service", "kpis": [{"title": "Errors", "threshold_field": "errors"}]}]}

        result = NativeWorkflow(client).run(spec, "validate")

        self.assertEqual(result.validations, [{"status": "fail", "object_type": "service", "title": "Missing Service"}])


if __name__ == "__main__":
    unittest.main()
