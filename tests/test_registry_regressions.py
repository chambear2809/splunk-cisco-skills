#!/usr/bin/env python3
"""Regression tests for app_registry.json and deployment role matrices."""

import json

from tests.regression_helpers import REPO_ROOT, ShellScriptRegressionBase


class RegistryRegressionTests(ShellScriptRegressionBase):
    def test_enterprise_networking_registry_declares_companion_ta_dependency(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        enterprise_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "7539"
        )
        enhanced_netflow_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "6872"
        )

        self.assertEqual(enterprise_entry["app_name"], "cisco-catalyst-app")
        self.assertEqual(enterprise_entry.get("install_requires"), ["7538"])
        self.assertEqual(enhanced_netflow_entry["skill"], "cisco-catalyst-enhanced-netflow-setup")
        self.assertEqual(enhanced_netflow_entry["app_name"], "splunk_app_stream_ipfix_cisco_hsl")
        self.assertIn(
            "cisco-catalyst-enhanced-netflow-add-on-for-splunk_*",
            enhanced_netflow_entry.get("package_patterns", []),
        )


    def test_app_registry_declares_deployment_roles_and_complete_role_support(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        expected_roles = [
            "search-tier",
            "indexer",
            "heavy-forwarder",
            "universal-forwarder",
            "external-collector",
        ]
        allowed_values = {"required", "supported", "none"}

        self.assertEqual(registry.get("deployment_roles"), expected_roles)

        for app in registry.get("apps", []):
            with self.subTest(app=app.get("app_name")):
                role_support = app.get("role_support")
                self.assertIsInstance(role_support, dict)
                self.assertEqual(sorted(role_support.keys()), sorted(expected_roles))
                self.assertTrue(set(role_support.values()).issubset(allowed_values))


    def test_app_registry_declares_capabilities_for_every_app(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        expected_capabilities = {
            "needs_custom_rest",
            "needs_search_time_objects",
            "needs_kvstore",
            "needs_python_runtime",
            "needs_packet_capture",
            "uf_safe",
        }

        apps_by_id = {
            app["splunkbase_id"]: app
            for app in registry.get("apps", [])
        }

        for app in registry.get("apps", []):
            with self.subTest(app=app.get("app_name")):
                capabilities = app.get("capabilities")
                self.assertIsInstance(capabilities, dict)
                self.assertEqual(set(capabilities.keys()), expected_capabilities)
                self.assertTrue(all(isinstance(value, bool) for value in capabilities.values()))

        self.assertEqual(
            apps_by_id["7538"]["capabilities"],
            {
                "needs_custom_rest": True,
                "needs_search_time_objects": False,
                "needs_kvstore": False,
                "needs_python_runtime": True,
                "needs_packet_capture": False,
                "uf_safe": False,
            },
        )
        self.assertEqual(
            apps_by_id["5238"]["capabilities"],
            {
                "needs_custom_rest": False,
                "needs_search_time_objects": False,
                "needs_kvstore": False,
                "needs_python_runtime": False,
                "needs_packet_capture": True,
                "uf_safe": True,
            },
        )
        self.assertEqual(
            apps_by_id["5234"]["capabilities"],
            {
                "needs_custom_rest": False,
                "needs_search_time_objects": True,
                "needs_kvstore": False,
                "needs_python_runtime": False,
                "needs_packet_capture": False,
                "uf_safe": False,
            },
        )


    def test_skill_topologies_cover_registry_skills_and_special_cases(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        expected_roles = set(registry["deployment_roles"])
        allowed_values = {"required", "supported", "none"}
        skill_topologies = {
            entry["skill"]: entry
            for entry in registry.get("skill_topologies", [])
        }

        for app_skill in {app["skill"] for app in registry.get("apps", [])}:
            self.assertIn(app_skill, skill_topologies)

        self.assertIn("cisco-product-setup", skill_topologies)
        self.assertIn("splunk-connect-for-syslog-setup", skill_topologies)
        self.assertIn("splunk-connect-for-snmp-setup", skill_topologies)
        self.assertIn("splunk-agent-management-setup", skill_topologies)
        self.assertIn("splunk-workload-management-setup", skill_topologies)
        self.assertIn("splunk-hec-service-setup", skill_topologies)
        self.assertIn("splunk-federated-search-setup", skill_topologies)
        self.assertIn("splunk-index-lifecycle-smartstore-setup", skill_topologies)
        self.assertIn("splunk-monitoring-console-setup", skill_topologies)
        self.assertIn("splunk-enterprise-kubernetes-setup", skill_topologies)
        self.assertIn("splunk-app-install", skill_topologies)

        for skill, topology in skill_topologies.items():
            with self.subTest(skill=skill):
                role_support = topology.get("role_support")
                self.assertIsInstance(role_support, dict)
                self.assertEqual(set(role_support.keys()), expected_roles)
                self.assertTrue(set(role_support.values()).issubset(allowed_values))
                self.assertTrue(set(topology.get("cloud_pairing", [])).issubset(expected_roles))

        sc4s = skill_topologies["splunk-connect-for-syslog-setup"]
        self.assertEqual(sc4s["role_support"]["external-collector"], "required")
        sc4snmp = skill_topologies["splunk-connect-for-snmp-setup"]
        self.assertEqual(sc4snmp["role_support"]["external-collector"], "required")
        enterprise_k8s = skill_topologies["splunk-enterprise-kubernetes-setup"]
        self.assertEqual(enterprise_k8s["role_support"]["external-collector"], "none")
        self.assertEqual(enterprise_k8s["cloud_pairing"], [])
        agent_management = skill_topologies["splunk-agent-management-setup"]
        self.assertEqual(agent_management["role_support"]["universal-forwarder"], "supported")
        workload_management = skill_topologies["splunk-workload-management-setup"]
        self.assertEqual(workload_management["role_support"]["indexer"], "supported")
        self.assertEqual(workload_management["role_support"]["heavy-forwarder"], "none")
        hec_service = skill_topologies["splunk-hec-service-setup"]
        self.assertEqual(hec_service["role_support"]["heavy-forwarder"], "supported")
        federated_search = skill_topologies["splunk-federated-search-setup"]
        self.assertEqual(federated_search["role_support"]["search-tier"], "required")
        smartstore = skill_topologies["splunk-index-lifecycle-smartstore-setup"]
        self.assertEqual(smartstore["role_support"]["indexer"], "required")
        monitoring_console = skill_topologies["splunk-monitoring-console-setup"]
        self.assertEqual(monitoring_console["role_support"]["search-tier"], "required")


    def test_role_matrix_keeps_search_tier_only_and_collector_defaults_explicit(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        entries_by_id = {
            app["splunkbase_id"]: app
            for app in registry.get("apps", [])
        }
        self.assertEqual(
            entries_by_id["7539"]["role_support"],
            {
                "search-tier": "required",
                "indexer": "none",
                "heavy-forwarder": "none",
                "universal-forwarder": "none",
                "external-collector": "none",
            },
        )

        collector_ids = ["7538", "7777", "7404", "5558", "7828", "3471", "5580", "7719"]
        for app_id in collector_ids:
            with self.subTest(app_id=app_id):
                role_support = entries_by_id[app_id]["role_support"]
                self.assertEqual(role_support["search-tier"], "supported")
                self.assertEqual(role_support["heavy-forwarder"], "supported")
                self.assertEqual(role_support["indexer"], "none")
                self.assertEqual(role_support["universal-forwarder"], "none")


    def test_cisco_security_registry_entries_are_present(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        security_cloud_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "7404"
        )
        secure_access_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "5558"
        )

        self.assertEqual(security_cloud_entry["skill"], "cisco-security-cloud-setup")
        self.assertEqual(security_cloud_entry["app_name"], "CiscoSecurityCloud")
        self.assertIn("cisco-security-cloud_*", security_cloud_entry.get("package_patterns", []))

        self.assertEqual(secure_access_entry["skill"], "cisco-secure-access-setup")
        self.assertEqual(secure_access_entry["app_name"], "cisco-cloud-security")
        self.assertIn(
            "cisco-secure-access-app-for-splunk_*",
            secure_access_entry.get("package_patterns", []),
        )

    def test_content_library_registry_entry_is_present(self):
        registry = json.loads(
            (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
        )

        content_library_entry = next(
            app for app in registry.get("apps", []) if app.get("splunkbase_id") == "5391"
        )

        self.assertEqual(content_library_entry["skill"], "splunk-itsi-config")
        self.assertEqual(content_library_entry["app_name"], "DA-ITSI-ContentLibrary")
        self.assertEqual(content_library_entry.get("install_requires"), ["1841"])
        self.assertIn("splunk-app-for-content-packs_*", content_library_entry.get("package_patterns", []))
