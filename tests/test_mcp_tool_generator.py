#!/usr/bin/env python3
"""Tests for manifest-backed Splunk MCP tool generation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

LIB_DIR = REPO_ROOT / "skills/shared/lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

import mcp_tooling  # noqa: E402


PRIORITY_MANIFEST_SKILLS = {
    "splunk-enterprise-security-config",
    "splunk-asset-risk-intelligence-setup",
    "splunk-attack-analyzer-setup",
    "splunk-soar-setup",
    "splunk-oncall-setup",
    "splunk-connect-for-syslog-setup",
    "splunk-connect-for-snmp-setup",
    "splunk-observability-cloud-integration-setup",
}

REQUIRED_FEATURE_COVERAGE = {
    "splunk-enterprise-security-config": {
        "es_app_health",
        "es_indexes",
        "es_kv_store",
        "es_kv_collections",
        "es_data_model_acceleration",
        "es_notable_risk_threat_data",
        "es_urgency_matrix",
        "es_notable_suppressions",
        "es_correlation_search_inventory",
        "es_glass_tables_views",
        "es_escu_content_library_state",
    },
    "splunk-asset-risk-intelligence-setup": {
        "ari_app_health",
        "ari_required_indexes",
        "ari_kv_store",
        "ari_roles_capabilities",
        "ari_app_saved_searches",
        "ari_ta_data",
        "ari_es_exposure_analytics_readiness",
    },
    "splunk-attack-analyzer-setup": {
        "splunk_ta_saa_app",
        "splunk_app_saa_app",
        "saa_index",
        "saa_indexes_macro",
        "enabled_ta_inputs",
        "recent_saa_data",
    },
    "splunk-soar-setup": {
        "splunk_side_apps",
        "export_app",
        "placement_warnings",
        "visible_app_owned_inputs",
        "visible_app_owned_indexes",
        "soar_server_api_checks",
    },
    "splunk-oncall-setup": {
        "victorops_app",
        "oncall_addon",
        "required_indexes",
        "modular_input_families",
        "recovery_saved_search",
        "kv_collections",
        "dashboards",
        "recent_indexed_data",
    },
    "splunk-connect-for-syslog-setup": {
        "default_indexes",
        "optional_metrics_index",
        "hec_token_state",
        "ack_diagnostics",
        "default_index_diagnostics",
        "startup_events",
        "recent_syslog_distribution",
    },
    "splunk-connect-for-snmp-setup": {
        "event_index",
        "metrics_index",
        "hec_token_state",
        "indexed_event_data",
        "metric_catalog_visibility",
        "collector_log_data",
    },
    "splunk-observability-cloud-integration-setup": {
        "o11y_splunk_side_app_health",
        "token_auth_visibility",
        "service_account_token_visibility",
        "pairing_discover_app_readable_state",
        "loc_splunk_side_readiness",
        "sim_addon_account_health",
        "sim_addon_input_health",
        "sim_metrics_data",
        "external_observability_mcp_gateway_tools",
    },
}

EXPECTED_EXCLUDED_FEATURES = {
    ("splunk-soar-setup", "soar_server_api_checks"),
    ("splunk-observability-cloud-integration-setup", "external_observability_mcp_gateway_tools"),
}

REQUIRED_TOOL_SPL_FRAGMENTS = {
    "splunk-enterprise-security-config": {
        "kv_collections": ["/storage/collections/config"],
    },
    "splunk-asset-risk-intelligence-setup": {
        "kvstore_status": ["kvStoreStatus", "/storage/collections/config"],
    },
    "splunk-soar-setup": {
        "visible_indexes": ["/services/data/indexes"],
    },
    "splunk-observability-cloud-integration-setup": {
        "token_auth_state": ["/services/admin/token-auth/tokens_auth"],
        "discover_app_state": ["related_content_discovery", "access_tokens", "token_configured"],
        "sim_accounts": ["splunk_infrastructure_monitoring_account", "token_configured"],
    },
}

LEGACY_MCP_JSON_SKILLS = {
    "cisco-appdynamics-setup",
    "cisco-catalyst-ta-setup",
    "cisco-dc-networking-setup",
    "cisco-enterprise-networking-setup",
    "cisco-intersight-setup",
    "cisco-meraki-ta-setup",
    "cisco-thousandeyes-setup",
}


class MCPToolGeneratorTests(unittest.TestCase):
    def test_priority_manifests_validate_and_generate_deterministically(self):
        for skill in sorted(PRIORITY_MANIFEST_SKILLS):
            with self.subTest(skill=skill):
                manifest_path = REPO_ROOT / "skills" / skill / "mcp_tools.source.yaml"
                generated_path = REPO_ROOT / "skills" / skill / "mcp_tools.json"
                manifest = mcp_tooling.load_manifest(manifest_path)

                errors = mcp_tooling.validate_manifest_payload(
                    manifest, source=str(manifest_path)
                )
                self.assertEqual(errors, [])

                expected = mcp_tooling.generated_json_text(
                    mcp_tooling.legacy_doc_from_manifest(
                        manifest, source=str(manifest_path)
                    )
                )
                self.assertEqual(generated_path.read_text(encoding="utf-8"), expected)

    def test_generated_legacy_json_schema_and_prefix_rules(self):
        allowed_prefixes = tuple(f"{prefix}_" for prefix in mcp_tooling.SUPPORTED_EXTERNAL_APP_IDS)
        for skill in sorted(PRIORITY_MANIFEST_SKILLS):
            with self.subTest(skill=skill):
                path = REPO_ROOT / "skills" / skill / "mcp_tools.json"
                payload = mcp_tooling.read_json(path)
                errors = mcp_tooling.validate_legacy_doc(
                    payload,
                    source=str(path),
                    enforce_generated_rules=True,
                )
                self.assertEqual(errors, [])
                for tool in payload["tools"]:
                    self.assertTrue(tool["name"].startswith(allowed_prefixes), tool["name"])
                    self.assertFalse(tool["name"].startswith("splunk_"), tool["name"])
                    self.assertEqual(tool["arguments"], [])
                    self.assertIs(tool["row_limiter"], True)

    def test_all_mcp_json_spl_is_read_only_safe(self):
        for path in sorted((REPO_ROOT / "skills").glob("*/mcp_tools.json")):
            payload = mcp_tooling.read_json(path)
            for index, tool in enumerate(payload["tools"]):
                with self.subTest(path=path.relative_to(REPO_ROOT).as_posix(), tool=index):
                    self.assertEqual(
                        mcp_tooling.validate_spl_safety(str(tool.get("spl", ""))),
                        [],
                    )

    def test_all_mcp_json_is_argument_free_v1(self):
        for path in sorted((REPO_ROOT / "skills").glob("*/mcp_tools.json")):
            payload = mcp_tooling.read_json(path)
            for index, tool in enumerate(payload["tools"]):
                with self.subTest(path=path.relative_to(REPO_ROOT).as_posix(), tool=index):
                    self.assertFalse(str(tool.get("name", "")).startswith("splunk_"))
                    self.assertIn(tool.get("arguments"), ([], None))
                    for example in tool.get("examples", []):
                        if isinstance(example, dict):
                            self.assertIn(example.get("arguments", {}), ({}, None))

    def test_rest_batch_payload_uses_supported_contract_only(self):
        path = REPO_ROOT / "skills/splunk-attack-analyzer-setup/mcp_tools.json"
        payload = mcp_tooling.rest_batch_payload(mcp_tooling.read_json(path))

        self.assertEqual(payload["external_app_id"], "saa")
        self.assertEqual(len(payload["tools"]), 5)
        for tool in payload["tools"]:
            self.assertEqual(set(tool), {"name", "title", "description", "inputSchema", "_meta"})
            self.assertNotIn("_key", tool)
            self.assertNotIn("category", tool)
            self.assertEqual(tool["inputSchema"], {"type": "object", "properties": {}})
            self.assertEqual(set(tool["_meta"]), {"external_app_id", "tags", "examples", "execution"})
            self.assertEqual(tool["_meta"]["execution"]["type"], "spl")
            self.assertNotIn("annotations", tool["_meta"])
            self.assertNotIn("coverage", tool["_meta"])

    def test_all_rest_batch_payloads_are_argument_free_and_supported_meta_only(self):
        expected_meta = {"external_app_id", "tags", "examples", "execution"}
        for path in sorted((REPO_ROOT / "skills").glob("*/mcp_tools.json")):
            with self.subTest(path=path.relative_to(REPO_ROOT).as_posix()):
                payload = mcp_tooling.rest_batch_payload(mcp_tooling.read_json(path))
                for tool in payload["tools"]:
                    self.assertEqual(tool["inputSchema"], {"type": "object", "properties": {}})
                    self.assertEqual(set(tool["_meta"]), expected_meta)
                    for example in tool["_meta"]["examples"]:
                        self.assertEqual(example.get("arguments", {}), {})

    def test_rest_batch_payload_drops_unsupported_meta_fields(self):
        tool = {
            "name": "es_example",
            "title": "Example",
            "description": "Example",
            "tags": [],
            "spl": "| rest /services/server/info | table serverName",
            "arguments": [],
            "examples": [],
            "required_app": "SplunkEnterpriseSecuritySuite",
            "annotations": {"readOnlyHint": True},
        }
        rest_tool = mcp_tooling.legacy_tool_to_rest_tool(tool, "es")

        self.assertEqual(
            set(rest_tool["_meta"]),
            {"external_app_id", "tags", "examples", "execution"},
        )

    def test_family_golden_tool_sets(self):
        cases = {
            "splunk-enterprise-security-config": {
                "es_app_health",
                "es_correlation_search_inventory",
                "es_content_library_state",
            },
            "splunk-connect-for-syslog-setup": {
                "sc4s_default_indexes",
                "sc4s_hec_tokens",
                "sc4s_syslog_distribution",
            },
            "splunk-observability-cloud-integration-setup": {
                "o11y_platform_token_auth_visibility",
                "o11y_platform_loc_readiness",
                "o11y_platform_sim_metrics_data",
            },
        }
        for skill, expected_names in cases.items():
            with self.subTest(skill=skill):
                payload = mcp_tooling.read_json(REPO_ROOT / "skills" / skill / "mcp_tools.json")
                actual_names = {tool["name"] for tool in payload["tools"]}
                self.assertTrue(expected_names.issubset(actual_names))

    def test_coverage_ledger_classifies_priority_checks_and_uncovered_skills(self):
        report = mcp_tooling.coverage_report()
        by_skill = {entry["skill"]: entry for entry in report["skills"]}

        for skill in PRIORITY_MANIFEST_SKILLS:
            self.assertEqual(by_skill[skill]["status"], "manifest")
            self.assertGreater(by_skill[skill]["tool_count"], 0)
            for check in by_skill[skill]["checks"]:
                self.assertIn(check["status"], mcp_tooling.VALID_COVERAGE_STATUSES)

        for skill in LEGACY_MCP_JSON_SKILLS:
            self.assertEqual(by_skill[skill]["status"], "legacy_mcp_json")
            self.assertGreater(by_skill[skill]["tool_count"], 0)

        self.assertEqual(by_skill["splunk-app-install"]["status"], "uncovered")
        self.assertEqual(report["totals"]["legacy_mcp_json"], len(LEGACY_MCP_JSON_SKILLS))
        self.assertGreater(report["totals"]["excluded_with_reason"], 0)
        self.assertGreater(report["totals"]["covered_by_builtin_mcp"], 0)

    def test_required_feature_coverage_has_no_gaps(self):
        self.assertEqual(set(REQUIRED_FEATURE_COVERAGE), PRIORITY_MANIFEST_SKILLS)

        for skill, expected_ids in sorted(REQUIRED_FEATURE_COVERAGE.items()):
            with self.subTest(skill=skill):
                manifest_path = REPO_ROOT / "skills" / skill / "mcp_tools.source.yaml"
                manifest = mcp_tooling.load_manifest(manifest_path)
                coverage_by_id = {
                    str(entry.get("id")): entry
                    for entry in manifest.get("coverage", [])
                    if isinstance(entry, dict)
                }

                missing = sorted(expected_ids - set(coverage_by_id))
                self.assertEqual(missing, [])

                for coverage_id in expected_ids:
                    entry = coverage_by_id[coverage_id]
                    if (skill, coverage_id) in EXPECTED_EXCLUDED_FEATURES:
                        self.assertEqual(entry["status"], "excluded_with_reason")
                        self.assertTrue(str(entry.get("reason", "")).strip())
                    else:
                        self.assertEqual(entry["status"], "mcp_tool")

    def test_gap_prone_tools_keep_required_spl_fragments(self):
        for skill, tools in sorted(REQUIRED_TOOL_SPL_FRAGMENTS.items()):
            manifest = mcp_tooling.load_manifest(
                REPO_ROOT / "skills" / skill / "mcp_tools.source.yaml"
            )
            by_tool = {
                str(tool.get("id")): str(tool.get("spl", ""))
                for tool in manifest.get("tools", [])
                if isinstance(tool, dict)
            }
            for tool_id, fragments in sorted(tools.items()):
                with self.subTest(skill=skill, tool=tool_id):
                    spl = by_tool[tool_id]
                    for fragment in fragments:
                        self.assertIn(fragment, spl)

    def test_manifest_schema_rejects_unknown_keys(self):
        manifest = mcp_tooling.load_manifest(
            REPO_ROOT / "skills/splunk-attack-analyzer-setup/mcp_tools.source.yaml"
        )
        manifest["unexpected"] = True
        manifest["tools"][0]["unexpected"] = True
        manifest["coverage"][0]["unexpected"] = True

        errors = mcp_tooling.validate_manifest_payload(manifest, source="test")

        self.assertTrue(any("unknown source keys: unexpected" in error for error in errors))
        self.assertTrue(any("tools[0] unknown keys: unexpected" in error for error in errors))
        self.assertTrue(any("coverage[0] unknown keys: unexpected" in error for error in errors))

    def test_manifest_annotations_are_source_only(self):
        manifest = mcp_tooling.load_manifest(
            REPO_ROOT / "skills/splunk-attack-analyzer-setup/mcp_tools.source.yaml"
        )
        manifest["tools"][0]["annotations"] = {"readOnlyHint": True}
        legacy = mcp_tooling.legacy_doc_from_manifest(manifest, source="test")
        rest = mcp_tooling.rest_batch_payload(legacy)

        self.assertNotIn("annotations", legacy["tools"][0])
        self.assertNotIn("annotations", rest["tools"][0]["_meta"])

    def test_spl_safety_rejects_mutating_and_api_execution_patterns(self):
        unsafe_queries = [
            "| makeresults | collect index=main",
            "search index=main | outputlookup unsafe.csv",
            "| rest /services/server/info | map search=\"| rest /services/apps/local\"",
            "| makeresults | sendemail to=admin@example.com",
            "| rest /servicesNS/nobody/-/configs/conf-passwords | table title clear_password",
            "| rest /servicesNS/nobody/-/configs/conf-passwords | fields title access_token",
            "| rest /servicesNS/nobody/-/configs/conf-passwords | fields *",
            "| makeresults | eval token=\"abcdef0123456789\" | table token",
            "| metadata type=hosts index=main",
            "| inputlookup users.csv | table user",
            "| mstats avg(_value) where index=metrics by metric_name",
        ]
        for query in unsafe_queries:
            with self.subTest(query=query):
                self.assertTrue(mcp_tooling.validate_spl_safety(query))

    def test_spl_safety_accepts_existing_implicit_search_patterns(self):
        safe_queries = [
            'index=catalyst sourcetype="cisco:dnac:issue" | spath | stats count by priority',
            'index=appdynamics sourcetype="appdynamics:events" | stats count by severity',
            'source=*sc4s* | stats count by host source',
        ]
        for query in safe_queries:
            with self.subTest(query=query):
                self.assertEqual(mcp_tooling.validate_spl_safety(query), [])

    def test_cli_check_generated_and_rest_payload(self):
        check = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "skills/shared/scripts/mcp_tools.py"),
                "check-generated",
                "--all",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(check.returncode, 0, msg=check.stdout + check.stderr)

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "payload.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "skills/shared/scripts/mcp_tools.py"),
                    "rest-batch-payload",
                    "skills/splunk-connect-for-syslog-setup/mcp_tools.json",
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["external_app_id"], "sc4s")
            self.assertGreaterEqual(len(payload["tools"]), 5)


if __name__ == "__main__":
    unittest.main()
