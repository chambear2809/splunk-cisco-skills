#!/usr/bin/env python3
"""Regression tests for generated deployment docs and related examples."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "skills/shared/app_registry.json"
GENERATOR_PATH = REPO_ROOT / "skills/shared/scripts/generate_deployment_docs.py"


class DeploymentDocRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        cls.architecture = (REPO_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
        cls.credentials_example = (REPO_ROOT / "credentials.example").read_text(encoding="utf-8")
        cls.cloud_matrix = (REPO_ROOT / "CLOUD_DEPLOYMENT_MATRIX.md").read_text(encoding="utf-8")
        cls.role_matrix = (REPO_ROOT / "DEPLOYMENT_ROLE_MATRIX.md").read_text(encoding="utf-8")
        cls.install_skill = (
            REPO_ROOT / "skills/splunk-app-install/SKILL.md"
        ).read_text(encoding="utf-8")
        cls.stream_skill = (
            REPO_ROOT / "skills/splunk-stream-setup/SKILL.md"
        ).read_text(encoding="utf-8")
        cls.package_cache_doc = (REPO_ROOT / "splunk-ta/README.md").read_text(encoding="utf-8")

    def test_generator_check_matches_committed_docs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GENERATOR_PATH), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_registry_declares_role_descriptions_for_all_roles(self) -> None:
        roles = self.registry["deployment_roles"]
        descriptions = self.registry["deployment_role_descriptions"]

        self.assertEqual(set(descriptions), set(roles))
        for role in roles:
            with self.subTest(role=role):
                self.assertTrue(descriptions[role])

    def test_cloud_matrix_rows_reference_known_apps_and_workflows(self) -> None:
        apps_by_name = {app["app_name"]: app for app in self.registry["apps"]}
        skills = {entry["skill"] for entry in self.registry["skill_topologies"]}
        rows = self.registry["documentation"]["cloud_matrix_rows"]

        app_rows = []
        workflow_rows = []
        for row in rows:
            with self.subTest(label=row["label"]):
                for key in ("kind", "label", "cloud_install_path", "cloud_config_path", "notes"):
                    self.assertTrue(row.get(key))

                if row["kind"] == "app":
                    app_name = row["app_name"]
                    self.assertIn(app_name, apps_by_name)
                    self.assertTrue(apps_by_name[app_name]["splunkbase_id"].isdigit())
                    app_rows.append(app_name)
                else:
                    self.assertEqual(row["kind"], "workflow")
                    self.assertIn(row["skill"], skills)
                    self.assertEqual(row["splunkbase_id"], "N/A")
                    workflow_rows.append(row["skill"])

        self.assertIn("Splunk_TA_AppDynamics", app_rows)
        self.assertIn("splunk-cisco-app-navigator", app_rows)
        self.assertIn("Splunk_AI_Assistant_Cloud", app_rows)
        self.assertIn("SplunkAssetRiskIntelligence", app_rows)
        self.assertIn("Splunk Asset and Risk Intelligence Technical Add-on For Windows", app_rows)
        self.assertIn("Splunk Asset and Risk Intelligence Technical Add-on For Linux", app_rows)
        self.assertIn("Splunk Asset and Risk Intelligence Technical Add-on For macOS", app_rows)
        self.assertIn("splunk_app_stream", app_rows)
        self.assertIn("Splunk_TA_stream", app_rows)
        self.assertIn("Splunk_TA_stream_wire_data", app_rows)
        self.assertIn("DA-ITSI-ContentLibrary", app_rows)
        self.assertIn("splunk-connect-for-otlp", app_rows)
        self.assertIn("cisco-product-setup", workflow_rows)
        self.assertIn("splunk-connect-for-syslog-setup", workflow_rows)
        self.assertIn("splunk-connect-for-snmp-setup", workflow_rows)
        self.assertIn("splunk-agent-management-setup", workflow_rows)
        self.assertIn("splunk-universal-forwarder-setup", workflow_rows)
        self.assertIn("splunk-workload-management-setup", workflow_rows)
        self.assertIn("splunk-hec-service-setup", workflow_rows)
        self.assertIn("splunk-federated-search-setup", workflow_rows)
        self.assertIn("splunk-index-lifecycle-smartstore-setup", workflow_rows)
        self.assertIn("splunk-monitoring-console-setup", workflow_rows)
        self.assertIn("splunk-enterprise-host-setup", workflow_rows)
        self.assertIn("splunk-enterprise-kubernetes-setup", workflow_rows)
        self.assertIn("splunk-mcp-server-setup", workflow_rows)
        self.assertIn("splunk-observability-otel-collector-setup", workflow_rows)
        self.assertIn("splunk-observability-dashboard-builder", workflow_rows)
        self.assertIn("splunk-observability-native-ops", workflow_rows)

    def test_generated_docs_cover_appdynamics_sc4s_host_bootstrap_and_numeric_stream_ids(self) -> None:
        self.assertIn("| `cisco-appdynamics-setup` | 3471 |", self.cloud_matrix)
        self.assertIn("| `cisco-scan-setup` | 8566 |", self.cloud_matrix)
        self.assertIn("| `cisco-product-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-connect-for-syslog-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-connect-for-snmp-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-agent-management-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-universal-forwarder-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-workload-management-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-hec-service-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-connect-for-otlp-setup` | 8704 |", self.cloud_matrix)
        self.assertIn("| `splunk-federated-search-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-index-lifecycle-smartstore-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-monitoring-console-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-enterprise-host-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-enterprise-kubernetes-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-observability-otel-collector-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-observability-dashboard-builder` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-observability-native-ops` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-ai-assistant-setup` | 7245 |", self.cloud_matrix)
        self.assertIn("| `splunk-mcp-server-setup` | N/A |", self.cloud_matrix)
        self.assertIn("| `splunk-stream-setup` search-tier app | 1809 |", self.cloud_matrix)
        self.assertIn("| `splunk-stream-setup` wire-data add-on | 5234 |", self.cloud_matrix)
        self.assertIn("| `splunk-stream-setup` forwarder add-on | 5238 |", self.cloud_matrix)
        self.assertIn("| `splunk-itsi-config` content library | 5391 |", self.cloud_matrix)
        self.assertIn("| `splunk-asset-risk-intelligence-setup` | 7180 |", self.cloud_matrix)
        self.assertIn("| `splunk-asset-risk-intelligence-setup` Windows TA handoff | 7214 |", self.cloud_matrix)
        self.assertIn("| `splunk-asset-risk-intelligence-setup` Linux TA handoff | 7416 |", self.cloud_matrix)
        self.assertIn("| `splunk-asset-risk-intelligence-setup` macOS TA handoff | 7417 |", self.cloud_matrix)
        self.assertIn("| `cisco-appdynamics-setup` | Supported |", self.role_matrix)
        self.assertIn("| `cisco-scan-setup` | Required | None | None | None | None |", self.role_matrix)
        self.assertIn("| `splunk-asset-risk-intelligence-setup` | Required | Supported | None | None | None |", self.role_matrix)
        self.assertIn("| `Splunk Asset and Risk Intelligence Technical Add-on For Windows` | `splunk-asset-risk-intelligence-setup` | None | Supported | None | Supported | None |", self.role_matrix)
        self.assertIn("| `Splunk Asset and Risk Intelligence Technical Add-on For Linux` | `splunk-asset-risk-intelligence-setup` | None | Supported | None | Supported | None |", self.role_matrix)
        self.assertIn("| `Splunk Asset and Risk Intelligence Technical Add-on For macOS` | `splunk-asset-risk-intelligence-setup` | None | Supported | None | Supported | None |", self.role_matrix)
        self.assertIn("| `splunk-ai-assistant-setup` | Required | None | None | None | None |", self.role_matrix)
        self.assertIn("| `cisco-product-setup` | Supported | None | Supported |", self.role_matrix)
        self.assertIn("| `splunk-connect-for-snmp-setup` | Supported | None | None | None | Required |", self.role_matrix)
        self.assertIn("| `splunk-agent-management-setup` | Supported | Supported | Supported | Supported | None |", self.role_matrix)
        self.assertIn("| `splunk-universal-forwarder-setup` | None | None | None | Required | None |", self.role_matrix)
        self.assertIn("| `splunk-workload-management-setup` | Supported | Supported | None | None | None |", self.role_matrix)
        self.assertIn("| `splunk-hec-service-setup` | Supported | Supported | Supported | None | None |", self.role_matrix)
        self.assertIn("| `splunk-connect-for-otlp-setup` | Supported | None | Supported | None | Supported |", self.role_matrix)
        self.assertIn("| `splunk-federated-search-setup` | Required | None | None | None | None |", self.role_matrix)
        self.assertIn("| `splunk-index-lifecycle-smartstore-setup` | None | Required | None | None | None |", self.role_matrix)
        self.assertIn("| `splunk-monitoring-console-setup` | Required | None | None | None | None |", self.role_matrix)
        self.assertIn("| `splunk-enterprise-host-setup` | Supported | Supported | Supported |", self.role_matrix)
        self.assertIn("| `splunk-enterprise-kubernetes-setup` | Supported | Supported | None | None | None |", self.role_matrix)
        self.assertIn("| `splunk-observability-native-ops` | None | None | None | None | None |", self.role_matrix)

    def test_ari_full_coverage_docs_are_visible(self) -> None:
        ari_skill = (
            REPO_ROOT / "skills/splunk-asset-risk-intelligence-setup/SKILL.md"
        ).read_text(encoding="utf-8")
        ari_reference = (
            REPO_ROOT / "skills/splunk-asset-risk-intelligence-setup/reference.md"
        ).read_text(encoding="utf-8")
        combined = "\n".join(
            [self.readme, self.cloud_matrix, self.role_matrix, ari_skill, ari_reference]
        )

        for phrase in (
            "post-install config",
            "usage data",
            "ARI Add-ons",
            "ARI Echo",
            "Exposure Analytics",
            "ES risk factors",
            "event searches",
            "data source priorities",
            "metric exceptions",
            "responses",
            "audit",
            "troubleshooting",
            "release notes",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_enterprise_install_docs_match_ssh_staging_behavior(self) -> None:
        stale_phrases = (
            "direct REST upload first",
            "tries REST upload first",
            "falls back to SSH staging",
        )
        for document in (
            self.readme,
            self.architecture,
            self.credentials_example,
            self.install_skill,
            self.stream_skill,
        ):
            for phrase in stale_phrases:
                with self.subTest(phrase=phrase):
                    self.assertNotIn(phrase, document)

        self.assertIn("stage local packages over SSH", self.readme)
        self.assertIn("stages remote local-package installs over SSH", self.architecture)
        self.assertIn("stage the package over SSH", self.install_skill)
        self.assertIn("stage the package over SSH", self.stream_skill)

    def test_staging_examples_use_staging_acs_server(self) -> None:
        self.assertIn(
            'PROFILE_cloud__SPLUNK_SEARCH_API_URI="https://my-stack.stg.splunkcloud.com:8089"',
            self.readme,
        )
        self.assertIn(
            'PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"',
            self.readme,
        )
        self.assertIn(
            'SPLUNK_SEARCH_API_URI="https://your-stack.splunkcloud.com:8089"',
            self.readme,
        )
        self.assertIn(
            '# PROFILE_cloud__SPLUNK_SEARCH_API_URI="https://your-stack.stg.splunkcloud.com:8089"',
            self.credentials_example,
        )
        self.assertIn(
            '# PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"',
            self.credentials_example,
        )
        self.assertIn(
            '# ACS_SERVER="https://staging.admin.splunk.com"',
            self.credentials_example,
        )

    def test_package_cache_readme_matches_cloud_policy(self) -> None:
        self.assertIn("public apps are installed from Splunkbase", self.package_cache_doc)
        self.assertIn("through ACS", self.package_cache_doc)
        self.assertIn("Use local/private uploads only for genuinely private or", self.package_cache_doc)


if __name__ == "__main__":
    unittest.main()
