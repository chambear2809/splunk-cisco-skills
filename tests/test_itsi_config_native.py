from __future__ import annotations

import copy
import json
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
        self.custom_threshold_links: dict[str, set[tuple[str, str]]] = {}

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

    def _template_by_key(self, template_key: str) -> dict | None:
        for template in self._object_store("base_service_template").values():
            if template.get("_key") == template_key:
                return copy.deepcopy(template)
        return None

    def _sync_service_template(self, payload: dict, existing: dict | None = None) -> dict:
        normalized = copy.deepcopy(payload)
        template_key = str(normalized.get("base_service_template_id") or "").strip()
        if not template_key:
            return self._assign_service_kpi_keys(normalized, existing=existing)
        template = self._template_by_key(template_key)
        if not template:
            return self._assign_service_kpi_keys(normalized, existing=existing)
        current_kpis = {kpi.get("title"): copy.deepcopy(kpi) for kpi in normalized.get("kpis", []) if kpi.get("title")}
        for template_kpi in template.get("kpis", []):
            if template_kpi.get("title") not in current_kpis:
                current_kpis[template_kpi["title"]] = copy.deepcopy(template_kpi)
        normalized["kpis"] = list(current_kpis.values())
        if template.get("entity_rules") and not normalized.get("entity_rules"):
            normalized["entity_rules"] = copy.deepcopy(template["entity_rules"])
        return self._assign_service_kpi_keys(normalized, existing=existing)

    def find_object_by_title(self, object_type: str, title: str) -> dict | None:
        found = self._object_store(object_type).get(title)
        return copy.deepcopy(found) if found else None

    @staticmethod
    def _object_label(payload: dict) -> str:
        label = str(payload.get("title") or payload.get("name") or "").strip()
        if not label:
            raise AssertionError(f"Test object is missing an identity label: {payload}")
        return label

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
            created = self._sync_service_template(created)
        label = self._object_label(created)
        store[label] = created
        self.operations.append(("create", object_type, label))
        return {"_key": created["_key"]}

    def update_object(self, object_type: str, key: str, payload: dict) -> dict:
        store = self._object_store(object_type)
        existing = next((value for value in store.values() if value.get("_key") == key), None)
        updated = copy.deepcopy(payload)
        updated["_key"] = key
        if object_type == "service":
            updated = self._sync_service_template(updated, existing=existing)
        label = self._object_label(updated)
        store[label] = updated
        self.operations.append(("update", object_type, label))
        return {"_key": key}

    def get_service_template_link(self, service_key: str) -> str | None:
        service = self.get_object("service", service_key)
        if not service:
            return None
        return str(service.get("base_service_template_id") or "").strip() or None

    def link_service_to_template(self, service_key: str, template_key: str) -> dict:
        service = self.get_object("service", service_key)
        if not service:
            raise AssertionError(f"Unknown service key {service_key}")
        service["base_service_template_id"] = template_key
        synced = self._sync_service_template(service, existing=service)
        self._object_store("service")[synced["title"]] = synced
        self.operations.append(("link", "base_service_template", synced["title"]))
        return {"_key": service_key}

    def custom_threshold_window_linked_kpis(self, window_key: str) -> dict:
        services: dict[str, list[str]] = {}
        for service_key, kpi_key in sorted(self.custom_threshold_links.get(window_key, set())):
            services.setdefault(service_key, []).append(kpi_key)
        return {"services": [{"_key": service_key, "kpi_ids": kpi_ids} for service_key, kpi_ids in services.items()]}

    def associate_custom_threshold_window_kpis(self, window_key: str, payload: dict) -> dict:
        for service in payload.get("services", []):
            service_key = service["_key"]
            for kpi_id in service.get("kpi_ids", []):
                self.custom_threshold_links.setdefault(window_key, set()).add((service_key, kpi_id))
        self.operations.append(("link", "custom_threshold_window", window_key))
        return {"_key": window_key}

    def disconnect_custom_threshold_window_kpis(self, window_key: str) -> dict:
        self.custom_threshold_links[window_key] = set()
        self.operations.append(("operational", "custom_threshold_window_disconnect", window_key))
        return {"_key": window_key}

    def stop_custom_threshold_window(self, window_key: str) -> dict:
        self.operations.append(("operational", "custom_threshold_window_stop", window_key))
        return {"_key": window_key}

    def retire_entities(self, payload: dict) -> dict:
        self.operations.append(("operational", "entity_retire", str(payload)))
        return {"status": "ok"}

    def restore_entities(self, payload: dict) -> dict:
        self.operations.append(("operational", "entity_restore", str(payload)))
        return {"status": "ok"}

    def retire_retirable_entities(self) -> dict:
        self.operations.append(("operational", "entity_retire_retirable"))
        return {"status": "ok"}

    def apply_kpi_threshold_recommendation(self, payload: dict) -> dict:
        self.operations.append(("operational", "kpi_threshold_recommendation", str(payload)))
        return {"status": "ok"}

    def apply_kpi_entity_threshold_recommendation(self, payload: dict) -> dict:
        self.operations.append(("operational", "kpi_entity_threshold_recommendation", str(payload)))
        return {"status": "ok"}

    def shift_time_offset(self, payload: dict) -> dict:
        self.operations.append(("operational", "shift_time_offset", str(payload)))
        return {"status": "ok"}


class InterfaceRecordingNativeClient(FakeNativeClient):
    def __init__(self, objects: dict[str, dict[str, dict]] | None = None):
        super().__init__(objects)
        self.interfaces: list[tuple[str, str, str]] = []

    def find_object_by_title(self, object_type: str, title: str, interface: str = "itoa") -> dict | None:
        self.interfaces.append(("find", object_type, interface))
        return super().find_object_by_title(object_type, title)

    def create_object(self, object_type: str, payload: dict, interface: str = "itoa") -> dict:
        self.interfaces.append(("create", object_type, interface))
        return super().create_object(object_type, payload)

    def update_object(self, object_type: str, key: str, payload: dict, interface: str = "itoa") -> dict:
        self.interfaces.append(("update", object_type, interface))
        return super().update_object(object_type, key, payload)


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

    def test_default_neap_is_protected(self) -> None:
        client = FakeNativeClient(
            {
                "notable_event_aggregation_policy": {
                    "Default": {
                        "_key": "neap:default",
                        "title": "Default",
                        "description": "",
                        "is_default": "1",
                    }
                }
            }
        )
        spec = {"neaps": [{"title": "Default", "payload": {"rule_type": "custom"}}]}

        with self.assertRaises(ValidationError):
            NativeWorkflow(client).run(spec, "apply")

    def test_neap_uses_event_management_interface(self) -> None:
        client = InterfaceRecordingNativeClient()
        spec = {"neaps": [{"title": "Disk Episodes", "payload": {"rule_type": "custom"}}]}

        NativeWorkflow(client).run(spec, "apply")

        self.assertIn(("find", "notable_event_aggregation_policy", "event_management"), client.interfaces)
        self.assertIn(("create", "notable_event_aggregation_policy", "event_management"), client.interfaces)

    def test_neap_accepts_top_level_policy_fields(self) -> None:
        client = FakeNativeClient()
        spec = {
            "neaps": [
                {
                    "title": "Disk Episodes",
                    "filtering_criteria": [{"field": "signature", "value": "disk"}],
                    "split_by_field": "host",
                    "payload": {"rule_type": "custom"},
                }
            ]
        }

        NativeWorkflow(client).run(spec, "apply")

        neap = client.find_object_by_title("notable_event_aggregation_policy", "Disk Episodes")
        self.assertEqual(neap["filtering_criteria"][0]["value"], "disk")
        self.assertEqual(neap["split_by_field"], "host")
        self.assertEqual(neap["rule_type"], "custom")

    def test_validate_marks_missing_objects_as_fail(self) -> None:
        client = FakeNativeClient()
        spec = {"services": [{"title": "Missing Service", "kpis": [{"title": "Errors", "threshold_field": "errors"}]}]}

        result = NativeWorkflow(client).run(spec, "validate")

        self.assertEqual(result.validations, [{"status": "fail", "object_type": "service", "title": "Missing Service"}])

    def test_apply_preserves_omitted_fields_for_existing_objects(self) -> None:
        client = FakeNativeClient(
            {
                "entity": {
                    "edge-sw-01": {
                        "_key": "entity:1",
                        "title": "edge-sw-01",
                        "description": "Keep entity description",
                        "sec_grp": "network_team",
                        "identifier": {"fields": ["host"], "values": ["edge-sw-01"]},
                    }
                },
                "service": {
                    "API": {
                        "_key": "service:api",
                        "title": "API",
                        "description": "Keep service description",
                        "sec_grp": "app_team",
                        "kpis": [],
                    }
                },
                "notable_event_aggregation_policy": {
                    "Example NEAP": {
                        "_key": "neap:1",
                        "title": "Example NEAP",
                        "description": "Keep NEAP description",
                        "sec_grp": "ops_team",
                        "rule_type": "custom",
                    }
                },
            }
        )
        spec = {
            "entities": [{"title": "edge-sw-01"}],
            "services": [{"title": "API"}],
            "neaps": [{"title": "Example NEAP"}],
        }

        preview = NativeWorkflow(client).run(spec, "preview")
        apply = NativeWorkflow(client).run(spec, "apply")

        self.assertTrue(all(change.action == "noop" for change in preview.changes))
        self.assertEqual(client.operations, [])
        self.assertEqual(apply.summary()["unchanged"], 3)
        self.assertEqual(client.objects["entity"]["edge-sw-01"]["description"], "Keep entity description")
        self.assertEqual(client.objects["entity"]["edge-sw-01"]["sec_grp"], "network_team")
        self.assertEqual(client.objects["service"]["API"]["description"], "Keep service description")
        self.assertEqual(client.objects["service"]["API"]["sec_grp"], "app_team")
        self.assertEqual(client.objects["notable_event_aggregation_policy"]["Example NEAP"]["description"], "Keep NEAP description")
        self.assertEqual(client.objects["notable_event_aggregation_policy"]["Example NEAP"]["sec_grp"], "ops_team")

    def test_apply_preserves_omitted_service_metadata_when_updating_kpis(self) -> None:
        client = FakeNativeClient(
            {
                "service": {
                    "API": {
                        "_key": "service:api",
                        "title": "API",
                        "description": "Keep service description",
                        "sec_grp": "app_team",
                        "kpis": [],
                    }
                }
            }
        )
        spec = {
            "services": [
                {
                    "title": "API",
                    "kpis": [
                        {
                            "title": "Error Rate",
                            "search": "index=api | stats sum(errors) as error_rate by host",
                            "threshold_field": "error_rate",
                            "aggregate_statop": "sum",
                        }
                    ],
                }
            ]
        }

        NativeWorkflow(client).run(spec, "apply")

        service = client.objects["service"]["API"]
        self.assertEqual(service["description"], "Keep service description")
        self.assertEqual(service["sec_grp"], "app_team")
        self.assertEqual(service["kpis"][0]["title"], "Error Rate")

    def test_core_objects_accept_top_level_schema_fields(self) -> None:
        client = FakeNativeClient()
        spec = {
            "entities": [
                {
                    "title": "edge-sw-01",
                    "identifier_fields": [{"field": "host", "value": "edge-sw-01"}],
                    "sai_entity_key": "sai:edge-sw-01",
                    "payload": {"entity_class": "network"},
                }
            ],
            "services": [
                {
                    "title": "API",
                    "base_service_template_id": "template:direct",
                    "kpis": [
                        {
                            "title": "Latency",
                            "threshold_field": "latency",
                            "alert_period": "5",
                            "alert_lag": "30",
                            "adaptive_thresholds_is_enabled": True,
                            "gap_severity": "critical",
                            "payload": {"search_type": "ad hoc"},
                        }
                    ],
                }
            ],
        }

        NativeWorkflow(client).run(spec, "apply")
        result = NativeWorkflow(client).run(spec, "validate")

        entity = client.find_object_by_title("entity", "edge-sw-01")
        service = client.find_object_by_title("service", "API")
        kpi = service["kpis"][0]
        self.assertEqual(entity["sai_entity_key"], "sai:edge-sw-01")
        self.assertEqual(entity["entity_class"], "network")
        self.assertEqual(service["base_service_template_id"], "template:direct")
        self.assertEqual(kpi["alert_period"], "5")
        self.assertEqual(kpi["alert_lag"], "30")
        self.assertTrue(kpi["adaptive_thresholds_is_enabled"])
        self.assertEqual(kpi["gap_severity"], "critical")
        self.assertEqual(kpi["search_type"], "ad hoc")
        self.assertIn({"status": "pass", "object_type": "entity", "title": "edge-sw-01"}, result.validations)
        self.assertIn({"status": "pass", "object_type": "service", "title": "API"}, result.validations)

    def test_extended_config_sections_preview_without_mutating(self) -> None:
        client = FakeNativeClient()
        spec = {
            "teams": [{"title": "network_team", "payload": {"roles": {"read": ["net_reader"], "write": ["net_admin"]}}}],
            "entity_types": [{"title": "Network Device", "data_drilldowns": [{"title": "Events", "type": "events"}]}],
            "kpi_base_searches": [{"title": "Interface Metrics", "search": "index=net | stats sum(errors) as errors by host"}],
            "kpi_threshold_templates": [{"title": "Interface Error Thresholds", "thresholdLevels": [{"severityValue": 5}]}],
            "service_templates": [{"title": "Edge Template", "kpis": [{"title": "Errors"}]}],
            "custom_content_packs": [{"title": "Network Pack", "cp_version": "1.0.0"}],
            "event_management_states": [{"title": "Network Episode View", "viewingOption": "standard"}],
            "correlation_searches": [{"title": "Edge Device Down", "search": "index=alerts status=down"}],
            "maintenance_windows": [{"title": "Edge Maintenance", "start_time": 1, "end_time": 2}],
            "backup_restore_jobs": [{"title": "Nightly ITSI Backup", "job_type": "Backup"}],
            "glass_tables": [{"title": "Network Overview", "payload": {"layout": {"type": "absolute"}}}],
            "glass_table_icons": [{"title": "Network Router", "svg_path": "M0 0h10v10H0z", "category": "Network"}],
        }

        result = NativeWorkflow(client).run(spec, "preview")

        self.assertEqual(client.operations, [])
        self.assertEqual(result.summary()["created"], 12)
        self.assertEqual(result.object_snapshots["correlation_search"]["Edge Device Down"]["name"], "Edge Device Down")
        self.assertNotIn("title", result.object_snapshots["correlation_search"]["Edge Device Down"])
        self.assertEqual(
            [change.object_type for change in result.changes],
            [
                "team",
                "entity_type",
                "kpi_base_search",
                "kpi_threshold_template",
                "custom_content_pack",
                "service_template",
                "event_management_state",
                "correlation_search",
                "maintenance_calendar",
                "backup_restore_job",
                "glass_table",
                "glass_table_icon",
            ],
        )

    def test_event_management_sections_use_event_management_interface(self) -> None:
        client = InterfaceRecordingNativeClient()
        spec = {
            "event_management_states": [{"title": "Network Episode View", "viewingOption": "standard"}],
            "correlation_searches": [{"title": "Edge Device Down", "search": "index=alerts status=down"}],
            "notable_event_email_templates": [{"title": "Network Email", "subject": "Network alert"}],
            "neaps": [{"title": "Network Episodes", "payload": {"rule_type": "custom"}}],
        }

        NativeWorkflow(client).run(spec, "apply")

        self.assertIn(("find", "event_management_state", "event_management"), client.interfaces)
        self.assertIn(("create", "event_management_state", "event_management"), client.interfaces)
        self.assertIn(("find", "correlation_search", "event_management"), client.interfaces)
        self.assertIn(("create", "correlation_search", "event_management"), client.interfaces)
        self.assertIn(("find", "notable_event_email_template", "event_management"), client.interfaces)
        self.assertIn(("create", "notable_event_email_template", "event_management"), client.interfaces)
        self.assertIn(("find", "notable_event_aggregation_policy", "event_management"), client.interfaces)
        self.assertIn(("create", "notable_event_aggregation_policy", "event_management"), client.interfaces)

    def test_apply_creates_extended_config_and_links_service_template(self) -> None:
        client = FakeNativeClient()
        spec = {
            "service_templates": [
                {
                    "title": "API Template",
                    "kpis": [{"title": "Latency", "threshold_field": "latency"}],
                    "entity_rules": [{"field": "host", "value": "api-*"}],
                }
            ],
            "services": [{"title": "API", "service_template": "API Template"}],
        }

        result = NativeWorkflow(client).run(spec, "apply")

        self.assertEqual(
            client.operations,
            [
                ("create", "base_service_template", "API Template"),
                ("create", "service", "API"),
                ("link", "base_service_template", "API"),
            ],
        )
        self.assertTrue(any(change.object_type == "service_template_link" and change.action == "update" for change in result.changes))
        service = client.find_object_by_title("service", "API")
        template = client.find_object_by_title("base_service_template", "API Template")
        self.assertEqual(service["base_service_template_id"], template["_key"])
        self.assertEqual(service["kpis"][0]["title"], "Latency")
        self.assertEqual(service["entity_rules"][0]["value"], "api-*")

    def test_apply_links_custom_threshold_window_to_service_kpis(self) -> None:
        client = FakeNativeClient()
        spec = {
            "custom_threshold_windows": [{"title": "Business Hours"}],
            "services": [
                {
                    "title": "API",
                    "kpis": [{"title": "Latency", "threshold_field": "latency"}],
                }
            ],
            "custom_threshold_window_links": [
                {
                    "window": "Business Hours",
                    "services": [{"service": "API", "kpis": ["Latency"]}],
                }
            ],
        }

        result = NativeWorkflow(client).run(spec, "apply")

        window = client.find_object_by_title("custom_threshold_windows", "Business Hours")
        service = client.find_object_by_title("service", "API")
        kpi_key = service["kpis"][0]["_key"]
        self.assertIn(("link", "custom_threshold_window", window["_key"]), client.operations)
        self.assertEqual(client.custom_threshold_links[window["_key"]], {(service["_key"], kpi_key)})
        self.assertTrue(any(change.object_type == "custom_threshold_window_link" and change.action == "update" for change in result.changes))

    def test_validate_custom_threshold_window_links(self) -> None:
        client = FakeNativeClient(
            {
                "custom_threshold_windows": {
                    "Business Hours": {
                        "_key": "ctw:business-hours",
                        "object_type": "custom_threshold_windows",
                        "title": "Business Hours",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                    }
                },
                "service": {
                    "API": {
                        "_key": "service:api",
                        "title": "API",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "kpis": [{"_key": "service:api::kpi::1", "title": "Latency", "description": ""}],
                    }
                },
            }
        )
        client.custom_threshold_links["ctw:business-hours"] = {("service:api", "service:api::kpi::1")}
        spec = {
            "custom_threshold_windows": [{"title": "Business Hours"}],
            "services": [{"title": "API", "kpis": [{"title": "Latency"}]}],
            "custom_threshold_window_links": [
                {
                    "window": "Business Hours",
                    "services": [{"service": "API", "kpis": ["Latency"]}],
                }
            ],
        }

        result = NativeWorkflow(client).run(spec, "validate")

        self.assertIn({"status": "pass", "object_type": "custom_threshold_window_link", "title": "Business Hours"}, result.validations)

    def test_apply_custom_threshold_window_link_is_idempotent(self) -> None:
        client = FakeNativeClient(
            {
                "custom_threshold_windows": {
                    "Business Hours": {
                        "_key": "ctw:business-hours",
                        "object_type": "custom_threshold_windows",
                        "title": "Business Hours",
                    }
                },
                "service": {
                    "API": {
                        "_key": "service:api",
                        "title": "API",
                        "kpis": [{"_key": "service:api::kpi::1", "title": "Latency"}],
                    }
                },
            }
        )
        client.custom_threshold_links["ctw:business-hours"] = {("service:api", "service:api::kpi::1")}
        spec = {
            "custom_threshold_window_links": [
                {
                    "window": "Business Hours",
                    "services": [{"service": "API", "kpis": ["Latency"]}],
                }
            ]
        }

        result = NativeWorkflow(client).run(spec, "apply")

        self.assertEqual(client.operations, [])
        self.assertTrue(any(change.object_type == "custom_threshold_window_link" and change.action == "noop" for change in result.changes))

    def test_custom_threshold_window_links_require_resolvable_kpis(self) -> None:
        client = FakeNativeClient(
            {
                "custom_threshold_windows": {
                    "Business Hours": {
                        "_key": "ctw:business-hours",
                        "object_type": "custom_threshold_windows",
                        "title": "Business Hours",
                    }
                },
                "service": {
                    "API": {
                        "_key": "service:api",
                        "title": "API",
                        "kpis": [],
                    }
                },
            }
        )
        spec = {
            "custom_threshold_window_links": [
                {
                    "window": "Business Hours",
                    "services": [{"service": "API", "kpis": ["Latency"]}],
                }
            ]
        }

        with self.assertRaisesRegex(ValidationError, "unknown KPI 'Latency'"):
            NativeWorkflow(client).run(spec, "preview")

    def test_operational_actions_are_blocked_without_explicit_allow(self) -> None:
        client = FakeNativeClient()
        spec = {"operational_actions": [{"action": "entity_retire", "payload": {"entities": [{"_key": "entity:1"}]}}]}

        result = NativeWorkflow(client).run(spec, "preview")

        self.assertTrue(result.failed)
        self.assertEqual(client.operations, [])
        self.assertTrue(any(change.object_type == "operational_action" and change.status == "error" for change in result.changes))

    def test_apply_guarded_operational_actions(self) -> None:
        client = FakeNativeClient(
            {
                "custom_threshold_windows": {
                    "Business Hours": {
                        "_key": "ctw:business-hours",
                        "object_type": "custom_threshold_windows",
                        "title": "Business Hours",
                    }
                },
                "service": {
                    "API": {
                        "_key": "service:api",
                        "title": "API",
                        "kpis": [{"_key": "service:api::kpi::1", "title": "Latency"}],
                    }
                },
            }
        )
        client.custom_threshold_links["ctw:business-hours"] = {("service:api", "service:api::kpi::1")}
        spec = {
            "operational_actions": [
                {
                    "action": "custom_threshold_window_disconnect",
                    "allow_operational_action": True,
                    "disconnect_all": True,
                    "window": "Business Hours",
                },
                {
                    "action": "custom_threshold_window_stop",
                    "allow_operational_action": True,
                    "window": "Business Hours",
                },
                {
                    "action": "shift_time_offset",
                    "allow_operational_action": True,
                    "payload": {"offset": 3600, "service": {"_keys": ["service:api"]}},
                },
                {
                    "action": "entity_retire_retirable",
                    "allow_operational_action": True,
                    "retire_all_retirable": True,
                },
            ]
        }

        result = NativeWorkflow(client).run(spec, "apply")

        self.assertFalse(result.failed)
        self.assertNotIn(("service:api", "service:api::kpi::1"), client.custom_threshold_links["ctw:business-hours"])
        self.assertIn(("operational", "custom_threshold_window_disconnect", "ctw:business-hours"), client.operations)
        self.assertIn(("operational", "custom_threshold_window_stop", "ctw:business-hours"), client.operations)
        self.assertTrue(any(operation[0:2] == ("operational", "shift_time_offset") for operation in client.operations))
        self.assertIn(("operational", "entity_retire_retirable"), client.operations)

    def test_custom_threshold_disconnect_requires_disconnect_all(self) -> None:
        client = FakeNativeClient(
            {
                "custom_threshold_windows": {
                    "Business Hours": {
                        "_key": "ctw:business-hours",
                        "object_type": "custom_threshold_windows",
                        "title": "Business Hours",
                    }
                }
            }
        )
        spec = {
            "operational_actions": [
                {
                    "action": "custom_threshold_window_disconnect",
                    "allow_operational_action": True,
                    "window": "Business Hours",
                }
            ]
        }

        with self.assertRaisesRegex(ValidationError, "disconnect_all"):
            NativeWorkflow(client).run(spec, "preview")

    def test_retire_retirable_requires_second_guard(self) -> None:
        client = FakeNativeClient()
        spec = {
            "operational_actions": [
                {
                    "action": "entity_retire_retirable",
                    "allow_operational_action": True,
                }
            ]
        }

        with self.assertRaisesRegex(ValidationError, "retire_all_retirable"):
            NativeWorkflow(client).run(spec, "preview")

    def test_entity_operational_action_normalizes_entity_keys(self) -> None:
        client = FakeNativeClient()
        spec = {
            "operational_actions": [
                {
                    "action": "entity_retire",
                    "allow_operational_action": True,
                    "entity_keys": ["entity:1"],
                }
            ]
        }

        result = NativeWorkflow(client).run(spec, "apply")

        self.assertFalse(result.failed)
        self.assertIn(("operational", "entity_retire", "{'data': ['entity:1']}"), client.operations)

    def test_entity_operational_action_requires_documented_data_payload(self) -> None:
        client = FakeNativeClient()
        spec = {
            "operational_actions": [
                {
                    "action": "entity_restore",
                    "allow_operational_action": True,
                    "payload": {"entities": [{"_key": "entity:1"}]},
                }
            ]
        }

        with self.assertRaisesRegex(ValidationError, "payload.data"):
            NativeWorkflow(client).run(spec, "preview")

    def test_validate_reports_unresolved_references_with_diagnostics(self) -> None:
        client = FakeNativeClient()
        spec = {"services": [{"title": "API", "service_template": "Missing Template"}]}

        result = NativeWorkflow(client).run(spec, "validate")

        self.assertTrue(result.failed)
        self.assertIn({"status": "fail", "object_type": "service", "title": "API"}, result.validations)
        self.assertTrue(any(item["object_type"] == "service_template_link" and "not found" in item["message"] for item in result.diagnostics))

    def test_entity_type_titles_resolve_from_same_spec(self) -> None:
        client = FakeNativeClient()
        spec = {
            "entity_types": [{"title": "Network Device"}],
            "entities": [{"title": "edge-sw-01", "entity_type_titles": ["Network Device"]}],
        }

        NativeWorkflow(client).run(spec, "apply")

        entity = client.find_object_by_title("entity", "edge-sw-01")
        entity_type = client.find_object_by_title("entity_type", "Network Device")
        self.assertEqual(entity["entity_type_ids"], [entity_type["_key"]])

    def test_validate_extended_config_and_service_template_link(self) -> None:
        client = FakeNativeClient(
            {
                "base_service_template": {
                    "API Template": {
                        "_key": "template:api",
                        "object_type": "base_service_template",
                        "title": "API Template",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "kpis": [{"title": "Latency"}],
                    }
                },
                "service": {
                    "API": {
                        "_key": "service:api",
                        "title": "API",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "base_service_template_id": "template:api",
                        "kpis": [{"_key": "service:api::kpi::1", "title": "Latency"}],
                    }
                },
                "maintenance_calendar": {
                    "API Maintenance": {
                        "_key": "maintenance:1",
                        "object_type": "maintenance_calendar",
                        "title": "API Maintenance",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "start_time": 1,
                    }
                },
                "backup_restore": {
                    "Nightly ITSI Backup": {
                        "_key": "backup:1",
                        "object_type": "backup_restore",
                        "title": "Nightly ITSI Backup",
                        "description": "",
                        "job_type": "Backup",
                    }
                },
                "icon": {
                    "API Icon": {
                        "_key": "icon:1",
                        "title": "API Icon",
                        "svg_path": "M0 0h10v10H0z",
                    }
                },
            }
        )
        spec = {
            "service_templates": [{"title": "API Template", "kpis": [{"title": "Latency"}]}],
            "services": [{"title": "API", "service_template": "API Template"}],
            "maintenance_windows": [{"title": "API Maintenance", "start_time": 1}],
            "backup_restore_jobs": [{"title": "Nightly ITSI Backup", "job_type": "Backup"}],
            "glass_table_icons": [{"title": "API Icon", "svg_path": "M0 0h10v10H0z"}],
        }

        result = NativeWorkflow(client).run(spec, "validate")

        self.assertIn({"status": "pass", "object_type": "service_template", "title": "API Template"}, result.validations)
        self.assertIn({"status": "pass", "object_type": "service_template_link", "title": "API"}, result.validations)
        self.assertIn({"status": "pass", "object_type": "maintenance_calendar", "title": "API Maintenance"}, result.validations)
        self.assertIn({"status": "pass", "object_type": "backup_restore_job", "title": "Nightly ITSI Backup"}, result.validations)
        self.assertIn({"status": "pass", "object_type": "glass_table_icon", "title": "API Icon"}, result.validations)

    def test_restore_backup_job_requires_explicit_allow_restore(self) -> None:
        client = FakeNativeClient()
        spec = {"backup_restore_jobs": [{"title": "Restore ITSI", "job_type": "Restore"}]}

        with self.assertRaisesRegex(ValidationError, "allow_restore"):
            NativeWorkflow(client).run(spec, "preview")

    def test_restore_allow_flag_is_not_sent_to_itsi_payload(self) -> None:
        client = FakeNativeClient()
        spec = {"backup_restore_jobs": [{"title": "Restore ITSI", "job_type": "Restore", "allow_restore": True}]}

        NativeWorkflow(client).run(spec, "apply")

        backup_job = client.find_object_by_title("backup_restore", "Restore ITSI")
        self.assertEqual(backup_job["job_type"], "Restore")
        self.assertNotIn("allow_restore", backup_job)

    def test_deep_dive_update_preserves_required_owner_fields(self) -> None:
        client = FakeNativeClient(
            {
                "deep_dive": {
                    "API Triage": {
                        "_key": "deep:api",
                        "object_type": "deep_dive",
                        "title": "API Triage",
                        "description": "Old",
                        "owner": "nobody",
                        "_owner": "nobody",
                        "_user": "nobody",
                    }
                }
            }
        )
        spec = {"deep_dives": [{"title": "API Triage", "description": "New"}]}

        result = NativeWorkflow(client).run(spec, "apply")

        self.assertFalse(result.failed)
        updated = client.find_object_by_title("deep_dive", "API Triage")
        self.assertEqual(updated["description"], "New")
        self.assertEqual(updated["owner"], "nobody")
        self.assertEqual(updated["_owner"], "nobody")
        self.assertEqual(updated["_user"], "nobody")

    def test_export_shaped_fixture_roundtrips_offline(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "itsi" / "native_export_roundtrip.json"
        spec = json.loads(fixture.read_text(encoding="utf-8"))
        client = FakeNativeClient()

        apply_result = NativeWorkflow(client).run(spec, "apply")
        validate_result = NativeWorkflow(client).run(spec, "validate")

        self.assertFalse(apply_result.failed, apply_result.diagnostics)
        self.assertFalse(validate_result.failed, validate_result.diagnostics)
        self.assertTrue(validate_result.validations)
        self.assertTrue(all(item["status"] == "pass" for item in validate_result.validations), validate_result.validations)


if __name__ == "__main__":
    unittest.main()
