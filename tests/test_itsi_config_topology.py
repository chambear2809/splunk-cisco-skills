from __future__ import annotations

import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "splunk-itsi-config" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_topology  # noqa: E402
from lib.common import ValidationError  # noqa: E402
from lib.content_packs import CONTENT_LIBRARY_APP, ITSI_APP, TopologyWorkflow  # noqa: E402
from lib.topology import compile_topology  # noqa: E402

HEALTHY_ITSI_APPS = {ITSI_APP, "itsi", "SA-UserAccess", "SA-ITSI-Licensechecker"}


class FakeTopologyClient:
    def __init__(
        self,
        *,
        apps: set[str] | None = None,
        app_versions: dict[str, str] | None = None,
        objects: dict[str, dict[str, dict]] | None = None,
        catalog: list[dict] | None = None,
        previews: dict[tuple[str, str], object] | None = None,
        macros: dict[tuple[str, str], dict] | None = None,
        kvstore_status_value: str | None = "ready",
        kvstore_collections: dict[tuple[str, str], dict[str, str]] | None = None,
    ):
        self.apps = set(apps or set())
        self.app_versions = dict(app_versions or {})
        self.objects = copy.deepcopy(objects or {})
        self.catalog = list(catalog or [])
        self.previews = dict(previews or {})
        self.macros = dict(macros or {})
        self.inputs: dict[str, list[dict]] = {}
        self.confs: dict[tuple[str, str, str], dict] = {}
        self.endpoints: dict[tuple[str, str], list[dict]] = {}
        self.kvstore_status_value = kvstore_status_value
        self.kvstore_collections = dict(kvstore_collections or {})
        self.install_requests: list[tuple[str, str, dict]] = []
        self.operations: list[tuple[str, str, str]] = []
        self.template_links: list[tuple[str, str]] = []

    def _object_store(self, object_type: str) -> dict[str, dict]:
        return self.objects.setdefault(object_type, {})

    def _template_by_key(self, template_key: str) -> dict | None:
        for template in self._object_store("base_service_template").values():
            if template.get("_key") == template_key:
                return copy.deepcopy(template)
        return None

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

    def _sync_service_template(self, payload: dict, existing: dict | None = None) -> dict:
        normalized = copy.deepcopy(payload)
        template_key = str(normalized.get("base_service_template_id") or "").strip()
        if not template_key:
            return normalized
        template = self._template_by_key(template_key)
        if not template:
            return normalized
        current_kpis = {kpi.get("title"): copy.deepcopy(kpi) for kpi in normalized.get("kpis", []) if kpi.get("title")}
        for template_kpi in template.get("kpis", []):
            if template_kpi.get("title") not in current_kpis:
                current_kpis[template_kpi["title"]] = copy.deepcopy(template_kpi)
        normalized["kpis"] = list(current_kpis.values())
        if template.get("entity_rules") and not normalized.get("entity_rules"):
            normalized["entity_rules"] = copy.deepcopy(template.get("entity_rules"))
        return self._assign_service_kpi_keys(normalized, existing=existing)

    def app_exists(self, app_name: str) -> bool:
        return app_name in self.apps

    def get_app(self, app_name: str) -> dict | None:
        if app_name not in self.apps:
            return None
        return {"name": app_name, "version": self.app_versions.get(app_name, "1.0.0")}

    def get_app_version(self, app_name: str) -> str | None:
        app = self.get_app(app_name)
        if not app:
            return None
        return str(app["version"])

    def first_installed_app(self, candidates: list[str]) -> str | None:
        for candidate in candidates:
            if candidate in self.apps:
                return candidate
        return None

    def content_pack_catalog(self) -> list[dict]:
        return list(self.catalog)

    def preview_content_pack(self, pack_id: str, version: str):
        return self.previews[(pack_id, version)]

    def install_content_pack(self, pack_id: str, version: str, payload: dict):
        self.install_requests.append((pack_id, version, payload))
        return {"installed": True, "id": pack_id, "version": version}

    def get_macro(self, app_name: str, macro_name: str):
        return self.macros.get((app_name, macro_name))

    def list_macros(self, app_name: str):
        return []

    def list_inputs(self, app_name: str | None = None):
        return list(self.inputs.get(app_name or "", []))

    def get_conf_stanza(self, app_name: str, conf_name: str, stanza_name: str):
        return self.confs.get((app_name, conf_name, stanza_name))

    def list_endpoint_entries(self, app_name: str, endpoint_name: str):
        return list(self.endpoints.get((app_name, endpoint_name), []))

    def kvstore_status(self) -> str | None:
        return self.kvstore_status_value

    def kvstore_collection_health(self, app_name: str, collection_name: str) -> dict[str, str]:
        return dict(self.kvstore_collections.get((app_name, collection_name), {"status": "ok", "message": "accessible"}))

    def find_object_by_title(self, object_type: str, title: str) -> dict | None:
        found = self._object_store(object_type).get(title)
        return copy.deepcopy(found) if found else None

    def find_object_by_titles(self, object_type: str, titles: list[str]) -> dict | None:
        for title in titles:
            found = self.find_object_by_title(object_type, title)
            if found:
                return found
        return None

    def get_object(self, object_type: str, key: str) -> dict | None:
        for obj in self._object_store(object_type).values():
            if obj.get("_key") == key:
                return copy.deepcopy(obj)
        return None

    def list_objects(self, object_type: str, interface: str = "itoa") -> list[dict]:
        return [copy.deepcopy(value) for value in self._object_store(object_type).values()]

    def create_object(self, object_type: str, payload: dict) -> dict:
        store = self._object_store(object_type)
        created = copy.deepcopy(payload)
        created["_key"] = created.get("_key") or f"{object_type}:{len(store) + 1}"
        if object_type == "service":
            created = self._sync_service_template(created)
        store[created["title"]] = created
        self.operations.append(("create", object_type, created["title"]))
        return {"_key": created["_key"]}

    def update_object(self, object_type: str, key: str, payload: dict) -> dict:
        store = self._object_store(object_type)
        existing = next((value for value in store.values() if value.get("_key") == key), None)
        updated = copy.deepcopy(payload)
        updated["_key"] = key
        if object_type == "service":
            updated = self._sync_service_template(updated, existing=existing)
        store[updated["title"]] = updated
        self.operations.append(("update", object_type, updated["title"]))
        return {"_key": key}

    def delete_object(self, object_type: str, key: str, interface: str = "itoa") -> dict:
        store = self._object_store(object_type)
        for title, payload in list(store.items()):
            if payload.get("_key") == key:
                del store[title]
                self.operations.append(("delete", object_type, title))
                return {"_key": key}
        raise AssertionError(f"Unknown {object_type} key {key}")

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
        self.template_links.append((service_key, template_key))
        return {"_key": service_key}


def vmware_spec() -> dict:
    return {
        "content_library": {"require_present": True},
        "packs": [
            {
                "profile": "vmware",
                "prefix": "Demo - ",
                "metrics_indexes": ["vmware-perf-metrics"],
            }
        ],
    }


class TopologyWorkflowTests(unittest.TestCase):
    def test_topology_prune_plan_protects_topology_only_services(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS,
            objects={
                "service": {
                    "Business Platform": {"_key": "service:business", "title": "Business Platform"},
                    "Retired API": {"_key": "service:retired", "title": "Retired API"},
                }
            },
        )
        spec = {
            "topology": {
                "roots": [
                    {
                        "id": "business",
                        "service_ref": "Business Platform",
                    }
                ]
            }
        }

        with tempfile.TemporaryDirectory() as tempdir:
            result = TopologyWorkflow(client, tempdir).run(spec, "prune-plan")

        candidates = result["native"]["prune_plan"]["candidates"]
        self.assertEqual([candidate["title"] for candidate in candidates], ["Retired API"])
        self.assertEqual(result["topology"]["changes"], [])

    def test_topology_cleanup_apply_deletes_reviewed_unmanaged_candidate(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS,
            objects={
                "service": {
                    "Business Platform": {"_key": "service:business", "title": "Business Platform"},
                    "Retired API": {"_key": "service:retired", "title": "Retired API"},
                }
            },
        )
        spec = {"topology": {"roots": [{"id": "business", "service_ref": "Business Platform"}]}}
        with tempfile.TemporaryDirectory() as tempdir:
            workflow = TopologyWorkflow(client, tempdir)
            plan_result = workflow.run(spec, "prune-plan")
            candidate = plan_result["native"]["prune_plan"]["candidates"][0]
            cleanup_spec = copy.deepcopy(spec)
            cleanup_spec["cleanup"] = {
                "allow_destroy": True,
                "confirm": "DELETE_UNMANAGED_ITSI_OBJECTS",
                "plan_id": plan_result["native"]["prune_plan"]["plan_id"],
                "max_deletes": 1,
                "candidate_ids": [candidate["candidate_id"]],
            }

            cleanup_result = workflow.run(cleanup_spec, "cleanup-apply")

        self.assertIn(("delete", "service", "Retired API"), client.operations)
        self.assertIn("Business Platform", client.objects["service"])
        self.assertEqual(cleanup_result["native"]["changes"][0]["action"], "delete")

    def test_preview_uses_content_pack_preview_for_pack_relative_refs(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_vmware_inframon", "DA-ITSI-CP-vmware"},
            catalog=[{"id": "DA-ITSI-CP-vmware-monitoring", "title": "VMware Monitoring", "version": "1.0.0", "installed_versions": []}],
            previews={
                ("DA-ITSI-CP-vmware-monitoring", "1.0.0"): {
                    "services": [{"title": "vCenter Core"}],
                    "service_templates": [{"title": "ESXi Hypervisor"}],
                }
            },
            macros={("DA-ITSI-CP-vmware", "cp_vmware_perf_metrics_index"): {"definition": "index=vmware-perf-metrics"}},
        )
        spec = {
            **vmware_spec(),
            "topology": {
                "roots": [
                    {
                        "id": "vcenter",
                        "service_ref": {"profile": "vmware", "title": "vCenter Core"},
                        "children": [
                            {
                                "id": "cluster",
                                "service": {"title": "Demo - VMware Cluster Health"},
                                "from_template": {"profile": "vmware", "title": "ESXi Hypervisor"},
                            }
                        ],
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as tempdir:
            result = TopologyWorkflow(client, tempdir).run(spec, "preview")
            self.assertTrue(Path(result["report_path"]).exists())

        self.assertEqual(client.operations, [])
        self.assertEqual(result["topology"]["changes"][0]["action"], "create")
        self.assertEqual(result["topology"]["changes"][1]["object_type"], "service_template_link")

    def test_apply_creates_and_links_services_then_applies_dependencies(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_vmware_inframon", "DA-ITSI-CP-vmware"},
            objects={
                "service": {
                    "Business Platform": {
                        "_key": "service:business",
                        "title": "Business Platform",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "kpis": [],
                    },
                    "Demo - VMware Cluster Health": {
                        "_key": "service:cluster",
                        "title": "Demo - VMware Cluster Health",
                        "description": "Existing cluster service",
                        "sec_grp": "default_itsi_security_group",
                        "kpis": [],
                    },
                },
                "base_service_template": {
                    "Demo - ESXi Hypervisor": {
                        "_key": "template:esxi",
                        "title": "Demo - ESXi Hypervisor",
                        "kpis": [{"title": "Host CPU"}],
                    }
                },
            },
            catalog=[{"id": "DA-ITSI-CP-vmware-monitoring", "title": "VMware Monitoring", "version": "1.0.0", "installed_versions": ["1.0.0"]}],
            previews={("DA-ITSI-CP-vmware-monitoring", "1.0.0"): {"service_templates": [{"title": "ESXi Hypervisor"}]}},
            macros={("DA-ITSI-CP-vmware", "cp_vmware_perf_metrics_index"): {"definition": "index=vmware-perf-metrics"}},
        )
        spec = {
            **vmware_spec(),
            "topology": {
                "roots": [
                    {
                        "id": "business",
                        "service_ref": "Business Platform",
                        "children": [
                            {
                                "id": "cluster",
                                "service": {"title": "Demo - VMware Cluster Health"},
                                "from_template": {"profile": "vmware", "title": "ESXi Hypervisor"},
                                "children": [
                                    {
                                        "id": "shared_db",
                                        "service": {
                                            "title": "Shared Database",
                                            "kpis": [{"title": "Availability", "threshold_field": "availability"}],
                                        },
                                    }
                                ],
                            },
                            {
                                "id": "reporting",
                                "service": {
                                    "title": "Reporting API",
                                    "kpis": [{"title": "Error Rate", "threshold_field": "error_rate"}],
                                },
                                "children": [{"ref": "shared_db", "kpis": ["Availability"]}],
                            },
                        ],
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as tempdir:
            result = TopologyWorkflow(client, tempdir).run(spec, "apply")
            self.assertTrue(Path(result["report_path"]).exists())

        shared_db = client.find_object_by_title("service", "Shared Database")
        reporting = client.find_object_by_title("service", "Reporting API")
        cluster = client.find_object_by_title("service", "Demo - VMware Cluster Health")
        business = client.find_object_by_title("service", "Business Platform")

        self.assertEqual(len(client.install_requests), 1)
        self.assertEqual(cluster["base_service_template_id"], "template:esxi")
        self.assertTrue(any(link == ("service:cluster", "template:esxi") for link in client.template_links))
        self.assertEqual(shared_db["kpis"][0]["title"], "Availability")
        self.assertRegex(shared_db["kpis"][0]["_key"], r"^[0-9a-f]{24}$")
        self.assertRegex(reporting["kpis"][0]["_key"], r"^[0-9a-f]{24}$")
        self.assertTrue(any(dep["service_id"] == shared_db["_key"] for dep in cluster["services_depends_on"]))
        self.assertTrue(any(dep["service_id"] == shared_db["_key"] for dep in reporting["services_depends_on"]))
        self.assertEqual(sorted(dep["service_id"] for dep in business["services_depends_on"]), sorted([cluster["_key"], reporting["_key"]]))
        self.assertEqual(len([op for op in client.operations if op == ("create", "service", "Shared Database")]), 1)

    def test_compile_topology_rejects_cycles(self) -> None:
        spec = {
            "topology": {
                "roots": [
                    {
                        "id": "a",
                        "service_ref": "A",
                        "children": [
                            {
                                "id": "b",
                                "service_ref": "B",
                                "children": [{"ref": "a"}],
                            }
                        ],
                    }
                ]
            }
        }

        with self.assertRaises(ValidationError):
            compile_topology(spec)

    def test_validate_unknown_service_ref_explains_starter_apply_flow(self) -> None:
        client = FakeTopologyClient(apps=HEALTHY_ITSI_APPS)
        spec = {"topology": {"roots": [{"id": "branch_network", "service_ref": "Branch Network"}]}}

        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaises(ValidationError) as error:
                TopologyWorkflow(client, tempdir).run(spec, "validate")

        message = str(error.exception)
        self.assertIn("could not resolve service reference 'Branch Network'", message)
        self.assertIn("run preview first", message)
        self.assertIn("before running validate", message)

    def test_apply_rejects_unknown_edge_kpis(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP},
            objects={
                "service": {
                    "API": {"_key": "service:api", "title": "API", "kpis": []},
                    "DB": {
                        "_key": "service:db",
                        "title": "DB",
                        "kpis": [{"_key": "service:db::kpi::1", "title": "Availability"}],
                    },
                }
            },
            catalog=[],
        )
        spec = {
            "content_library": {"require_present": True, "install_if_missing": False},
            "topology": {
                "roots": [
                    {
                        "id": "api",
                        "service_ref": "API",
                        "children": [{"id": "db", "service_ref": "DB", "kpis": ["Latency"]}],
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaises(ValidationError):
                TopologyWorkflow(client, tempdir).run(spec, "apply")

    def test_preview_rejects_unknown_edge_kpis_for_preview_only_children(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_vmware_inframon", "DA-ITSI-CP-vmware"},
            objects={"service": {"Parent": {"_key": "service:parent", "title": "Parent", "kpis": []}}},
            catalog=[{"id": "DA-ITSI-CP-vmware-monitoring", "title": "VMware Monitoring", "version": "1.0.0", "installed_versions": []}],
            previews={
                ("DA-ITSI-CP-vmware-monitoring", "1.0.0"): {
                    "service_templates": [{"title": "ESXi Hypervisor", "kpis": [{"title": "Host CPU"}]}]
                }
            },
            macros={("DA-ITSI-CP-vmware", "cp_vmware_perf_metrics_index"): {"definition": "index=vmware-perf-metrics"}},
        )
        spec = {
            **vmware_spec(),
            "topology": {
                "roots": [
                    {
                        "id": "parent",
                        "service_ref": "Parent",
                        "children": [
                            {
                                "id": "cluster",
                                "service": {"title": "Demo - VMware Cluster Health"},
                                "from_template": {"profile": "vmware", "title": "ESXi Hypervisor"},
                                "kpis": ["Latency"],
                            }
                        ],
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaises(ValidationError):
                TopologyWorkflow(client, tempdir).run(spec, "preview")

    def test_preview_accepts_edge_kpis_from_preview_only_template_children(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_vmware_inframon", "DA-ITSI-CP-vmware"},
            objects={"service": {"Parent": {"_key": "service:parent", "title": "Parent", "kpis": []}}},
            catalog=[{"id": "DA-ITSI-CP-vmware-monitoring", "title": "VMware Monitoring", "version": "1.0.0", "installed_versions": []}],
            previews={
                ("DA-ITSI-CP-vmware-monitoring", "1.0.0"): {
                    "service_templates": [{"title": "ESXi Hypervisor", "kpis": [{"title": "Host CPU"}]}]
                }
            },
            macros={("DA-ITSI-CP-vmware", "cp_vmware_perf_metrics_index"): {"definition": "index=vmware-perf-metrics"}},
        )
        spec = {
            **vmware_spec(),
            "topology": {
                "roots": [
                    {
                        "id": "parent",
                        "service_ref": "Parent",
                        "children": [
                            {
                                "id": "cluster",
                                "service": {"title": "Demo - VMware Cluster Health"},
                                "from_template": {"profile": "vmware", "title": "ESXi Hypervisor"},
                                "kpis": ["Host CPU"],
                            }
                        ],
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as tempdir:
            result = TopologyWorkflow(client, tempdir).run(spec, "preview")

        dependency_change = next(
            change for change in result["topology"]["changes"] if change["object_type"] == "service_dependency"
        )
        self.assertEqual(dependency_change["action"], "update")

    def test_preview_marks_existing_service_template_link_for_update_when_template_is_preview_only(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_vmware_inframon", "DA-ITSI-CP-vmware"},
            objects={
                "service": {
                    "Business Platform": {"_key": "service:business", "title": "Business Platform", "kpis": []},
                    "Demo - VMware Cluster Health": {
                        "_key": "service:cluster",
                        "title": "Demo - VMware Cluster Health",
                        "base_service_template_id": "template:old",
                        "kpis": [],
                    },
                }
            },
            catalog=[{"id": "DA-ITSI-CP-vmware-monitoring", "title": "VMware Monitoring", "version": "1.0.0", "installed_versions": []}],
            previews={
                ("DA-ITSI-CP-vmware-monitoring", "1.0.0"): {
                    "service_templates": [{"title": "ESXi Hypervisor", "kpis": [{"title": "Host CPU"}]}]
                }
            },
            macros={("DA-ITSI-CP-vmware", "cp_vmware_perf_metrics_index"): {"definition": "index=vmware-perf-metrics"}},
        )
        spec = {
            **vmware_spec(),
            "topology": {
                "roots": [
                    {
                        "id": "business",
                        "service_ref": "Business Platform",
                        "children": [
                            {
                                "id": "cluster",
                                "service": {"title": "Demo - VMware Cluster Health"},
                                "from_template": {"profile": "vmware", "title": "ESXi Hypervisor"},
                            }
                        ],
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as tempdir:
            result = TopologyWorkflow(client, tempdir).run(spec, "preview")

        template_change = next(
            change for change in result["topology"]["changes"] if change["object_type"] == "service_template_link"
        )
        self.assertEqual(template_change["action"], "update")
        self.assertIn("after the template is installed", template_change["detail"])

    def test_apply_pack_errors_block_native_and_topology_mutations(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP},
            objects={
                "service": {
                    "Business Platform": {
                        "_key": "service:business",
                        "title": "Business Platform",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "kpis": [],
                    }
                }
            },
            catalog=[{"id": "DA-ITSI-CP-vmware-monitoring", "title": "VMware Monitoring", "version": "1.0.0", "installed_versions": []}],
            previews={("DA-ITSI-CP-vmware-monitoring", "1.0.0"): {"service_templates": [{"title": "ESXi Hypervisor"}]}},
        )
        spec = {
            **vmware_spec(),
            "services": [{"title": "Business Platform", "description": "Mutated description"}],
            "topology": {"roots": [{"id": "business", "service_ref": "Business Platform"}]},
        }

        with tempfile.TemporaryDirectory() as tempdir:
            result = TopologyWorkflow(client, tempdir).run(spec, "apply")
            self.assertTrue(Path(result["report_path"]).exists())

        self.assertEqual(client.operations, [])
        self.assertEqual(client.install_requests, [])
        self.assertEqual(result["native"]["changes"], [])
        self.assertEqual(result["topology"]["changes"], [])
        self.assertTrue(any(finding["status"] == "error" for finding in result["runs"][0]["findings"]))

    def test_apply_static_topology_errors_block_pack_installs_and_native_mutations(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_vmware_inframon", "DA-ITSI-CP-vmware"},
            objects={
                "service": {
                    "Business Platform": {
                        "_key": "service:business",
                        "title": "Business Platform",
                        "description": "Keep me",
                        "sec_grp": "default_itsi_security_group",
                        "kpis": [],
                    }
                }
            },
            catalog=[{"id": "DA-ITSI-CP-vmware-monitoring", "title": "VMware Monitoring", "version": "1.0.0", "installed_versions": []}],
            previews={("DA-ITSI-CP-vmware-monitoring", "1.0.0"): {"service_templates": [{"title": "ESXi Hypervisor"}]}},
            macros={("DA-ITSI-CP-vmware", "cp_vmware_perf_metrics_index"): {"definition": "index=vmware-perf-metrics"}},
        )
        spec = {
            **vmware_spec(),
            "services": [{"title": "Business Platform", "description": "Should not apply"}],
            "topology": {
                "roots": [
                    {
                        "id": "business",
                        "service_ref": "Business Platform",
                        "children": [{"ref": "missing_node"}],
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaises(ValidationError):
                TopologyWorkflow(client, tempdir).run(spec, "apply")

        self.assertEqual(client.install_requests, [])
        self.assertEqual(client.operations, [])
        self.assertEqual(client.find_object_by_title("service", "Business Platform")["description"], "Keep me")

    def test_apply_rejects_unknown_edge_kpis_before_service_mutations(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS,
            objects={
                "service": {
                    "Parent": {
                        "_key": "service:parent",
                        "title": "Parent",
                        "description": "",
                        "sec_grp": "default_itsi_security_group",
                        "kpis": [],
                    }
                }
            },
        )
        spec = {
            "topology": {
                "roots": [
                    {
                        "id": "parent",
                        "service_ref": "Parent",
                        "children": [
                            {
                                "id": "child",
                                "service": {
                                    "title": "Child",
                                    "kpis": [{"title": "Availability", "threshold_field": "availability"}],
                                },
                                "kpis": ["Latency"],
                            }
                        ],
                    }
                ]
            }
        }

        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaises(ValidationError):
                TopologyWorkflow(client, tempdir).run(spec, "apply")

        self.assertEqual(client.operations, [])
        self.assertIsNone(client.find_object_by_title("service", "Child"))

    def test_preview_without_packs_does_not_require_content_library(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS,
            objects={
                "service": {
                    "A": {"_key": "service:a", "title": "A", "kpis": []},
                    "B": {"_key": "service:b", "title": "B", "kpis": [{"_key": "service:b::kpi::1", "title": "Availability"}]},
                }
            },
        )
        spec = {
            "topology": {
                "roots": [
                    {
                        "id": "a",
                        "service_ref": "A",
                        "children": [{"id": "b", "service_ref": "B"}],
                    }
                ]
            }
        }

        with tempfile.TemporaryDirectory() as tempdir:
            result = TopologyWorkflow(client, tempdir).run(spec, "preview")

        self.assertEqual(result["content_library"]["required"], False)
        self.assertIn("no content packs", result["content_library"]["message"].lower())
        self.assertEqual(result["topology"]["changes"][0]["object_type"], "service_dependency")

    def test_validate_reports_service_template_and_dependency_drift(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS | {CONTENT_LIBRARY_APP, "Splunk_TA_vmware_inframon", "DA-ITSI-CP-vmware"},
            objects={
                "service": {
                    "Business Platform": {
                        "_key": "service:business",
                        "title": "Business Platform",
                        "kpis": [],
                    },
                    "Demo - VMware Cluster Health": {
                        "_key": "service:cluster",
                        "title": "Demo - VMware Cluster Health",
                        "kpis": [{"_key": "service:cluster::kpi::1", "title": "Host CPU"}],
                    },
                },
                "base_service_template": {
                    "Demo - ESXi Hypervisor": {
                        "_key": "template:esxi",
                        "title": "Demo - ESXi Hypervisor",
                        "kpis": [{"title": "Host CPU"}],
                    }
                },
            },
            catalog=[{"id": "DA-ITSI-CP-vmware-monitoring", "title": "VMware Monitoring", "version": "1.0.0", "installed_versions": ["1.0.0"]}],
            macros={("DA-ITSI-CP-vmware", "cp_vmware_perf_metrics_index"): {"definition": "index=vmware-perf-metrics"}},
        )
        spec = {
            **vmware_spec(),
            "topology": {
                "roots": [
                    {
                        "id": "business",
                        "service_ref": "Business Platform",
                        "children": [
                            {
                                "id": "cluster",
                                "service": {"title": "Demo - VMware Cluster Health"},
                                "from_template": {"profile": "vmware", "title": "ESXi Hypervisor"},
                            }
                        ],
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as tempdir:
            result = TopologyWorkflow(client, tempdir).run(spec, "validate")

        statuses = {(item["object_type"], item["title"]): item["status"] for item in result["topology"]["validations"]}
        self.assertEqual(statuses[("service_template_link", "Demo - VMware Cluster Health")], "fail")
        self.assertEqual(statuses[("service_dependency", "Business Platform")], "fail")

    def test_topology_validate_returns_native_diagnostics(self) -> None:
        client = FakeTopologyClient(
            apps=HEALTHY_ITSI_APPS,
            objects={"service": {"API": {"_key": "service:api", "title": "API", "description": "Old"}}},
        )
        spec = {"services": [{"title": "API", "description": "New"}]}

        with tempfile.TemporaryDirectory() as tempdir:
            result = TopologyWorkflow(client, tempdir).run(spec, "validate")

        diagnostic = next(item for item in result["native"]["diagnostics"] if item["object_type"] == "service")
        self.assertEqual(diagnostic["title"], "API")
        self.assertIn({"path": "description", "expected": "New", "actual": "Old"}, diagnostic["diffs"])

    def test_topology_glass_table_generator_outputs_native_glass_table(self) -> None:
        script = SCRIPTS_DIR / "topology_glass_table.py"
        spec = {
            "topology": {
                "roots": [
                    {
                        "id": "business",
                        "service_ref": "Business Platform",
                        "children": [
                            {"id": "api", "service": {"title": "API"}, "children": [{"ref": "db", "kpis": ["Availability"]}]},
                            {"id": "db", "service": {"title": "Database"}},
                        ],
                    }
                ]
            }
        }

        with tempfile.TemporaryDirectory() as tempdir:
            spec_path = Path(tempdir) / "topology.json"
            output_path = Path(tempdir) / "glass.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--spec-json",
                    str(spec_path),
                    "--title",
                    "Business Map",
                    "--output",
                    str(output_path),
                    "--output-format",
                    "json",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertIn("Business Map", completed.stdout)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            glass_table = payload["glass_tables"][0]
            self.assertEqual(glass_table["title"], "Business Map")
            self.assertIn({"source": "api", "target": "db", "kpis": ["Availability"]}, glass_table["payload"]["edges"])


class RunTopologyCliExitCodeTests(unittest.TestCase):
    """End-to-end coverage for run_topology.py prune-plan and cleanup-apply modes."""

    @staticmethod
    def _write_spec(tempdir: str, payload: dict) -> str:
        spec_path = Path(tempdir) / "spec.json"
        spec_path.write_text(json.dumps(payload), encoding="utf-8")
        return str(spec_path)

    def _invoke(self, *, spec_payload: dict, fake_result: dict, mode: str, extra_args: list[str] | None = None) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tempdir:
            spec_json_path = self._write_spec(tempdir, spec_payload)
            backup_path = Path(tempdir) / "backup.yaml"
            argv = [
                "run_topology.py",
                "--spec-json",
                spec_json_path,
                "--mode",
                mode,
                "--report-root",
                str(Path(tempdir) / "reports"),
            ]
            if mode == "cleanup-apply":
                argv.extend(["--backup-output", str(backup_path)])
            if extra_args:
                argv.extend(extra_args)

            class FakeNativeWorkflowResult:
                exports = {"native_spec": {"services": []}}

            class FakeNativeWorkflow:
                def __init__(self, _client):
                    pass

                def run(self, _spec, _mode):
                    return FakeNativeWorkflowResult()

            class FakeTopologyWorkflow:
                def __init__(self, _client, _report_root):
                    pass

                def run(self, _spec, _mode):
                    return fake_result

            buffer = io.StringIO()
            with patch.object(run_topology, "SplunkRestClient") as mock_client_cls, \
                 patch.object(run_topology, "TopologyWorkflow", FakeTopologyWorkflow), \
                 patch.object(run_topology, "NativeWorkflow", FakeNativeWorkflow), \
                 patch.object(sys, "argv", argv), \
                 redirect_stdout(buffer):
                mock_client_cls.from_spec.return_value = object()
                exit_code = run_topology.main()
            return exit_code, buffer.getvalue()

    def _success_payload(self, mode: str) -> dict:
        return {
            "mode": mode,
            "itsi": {"checks": [{"status": "pass", "check": "itsi", "message": "ok"}]},
            "content_library": {"checks": [{"status": "pass", "check": "content_library", "message": "ok"}]},
            "report_path": "/tmp/report.md",
            "runs": [],
            "native": {"changes": [], "validations": [], "diagnostics": [], "prune_plan": {"candidates": []}},
            "topology": {"changes": [], "validations": [], "resolved_nodes": {}},
        }

    def test_run_topology_prune_plan_exits_zero_on_clean_result(self) -> None:
        spec = {"connection": {"base_url": "https://example:8089"}, "topology": {"roots": [{"id": "a", "service_ref": "A"}]}}
        exit_code, output = self._invoke(spec_payload=spec, fake_result=self._success_payload("prune-plan"), mode="prune-plan")
        self.assertEqual(exit_code, 0)
        payload = json.loads(output.strip())
        self.assertEqual(payload["mode"], "prune-plan")

    def test_run_topology_prune_plan_exits_nonzero_when_native_change_errors(self) -> None:
        result = self._success_payload("prune-plan")
        result["native"]["changes"] = [{"object_type": "service", "title": "Retired", "action": "delete", "status": "error", "detail": "blocked"}]
        spec = {"connection": {"base_url": "https://example:8089"}, "topology": {"roots": [{"id": "a", "service_ref": "A"}]}}
        exit_code, _ = self._invoke(spec_payload=spec, fake_result=result, mode="prune-plan")
        self.assertEqual(exit_code, 1)

    def test_run_topology_cleanup_apply_writes_backup_and_exits_zero(self) -> None:
        spec = {"connection": {"base_url": "https://example:8089"}, "topology": {"roots": [{"id": "a", "service_ref": "A"}]}}
        success_payload = self._success_payload("cleanup-apply")
        with tempfile.TemporaryDirectory() as tempdir:
            spec_json_path = self._write_spec(tempdir, spec)
            backup_path = Path(tempdir) / "backup.yaml"
            argv = [
                "run_topology.py",
                "--spec-json",
                spec_json_path,
                "--mode",
                "cleanup-apply",
                "--backup-output",
                str(backup_path),
                "--report-root",
                str(Path(tempdir) / "reports"),
            ]
            captured_native_modes: list[str] = []

            class FakeNativeWorkflowResult:
                exports = {"native_spec": {"services": [{"title": "Sample"}]}}

            class FakeNativeWorkflow:
                def __init__(self, _client):
                    pass

                def run(self, _spec, mode):
                    captured_native_modes.append(mode)
                    return FakeNativeWorkflowResult()

            class FakeTopologyWorkflow:
                def __init__(self, _client, _report_root):
                    pass

                def run(self, _spec, _mode):
                    return success_payload

            with patch.object(run_topology, "SplunkRestClient") as mock_client_cls, \
                 patch.object(run_topology, "TopologyWorkflow", FakeTopologyWorkflow), \
                 patch.object(run_topology, "NativeWorkflow", FakeNativeWorkflow), \
                 patch.object(sys, "argv", argv), \
                 redirect_stdout(io.StringIO()):
                mock_client_cls.from_spec.return_value = object()
                exit_code = run_topology.main()

            self.assertEqual(exit_code, 0)
            self.assertTrue(backup_path.exists(), "cleanup-apply must write the backup before deletion")
            self.assertIn("Sample", backup_path.read_text(encoding="utf-8"))
            self.assertEqual(captured_native_modes[0], "export")

    def test_run_topology_cleanup_apply_requires_backup_output(self) -> None:
        spec = {"connection": {"base_url": "https://example:8089"}, "topology": {"roots": [{"id": "a", "service_ref": "A"}]}}
        with tempfile.TemporaryDirectory() as tempdir:
            spec_json_path = self._write_spec(tempdir, spec)
            argv = [
                "run_topology.py",
                "--spec-json",
                spec_json_path,
                "--mode",
                "cleanup-apply",
            ]
            with patch.object(run_topology, "SplunkRestClient") as mock_client_cls, \
                 patch.object(sys, "argv", argv), \
                 redirect_stdout(io.StringIO()):
                mock_client_cls.from_spec.return_value = object()
                exit_code = run_topology.main()
            self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
