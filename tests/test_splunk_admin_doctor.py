#!/usr/bin/env python3
"""Regression coverage for the Splunk Admin Doctor skill."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent.splunk_cisco_skills_mcp import core
from skills.shared.skill_catalog import load_catalog
from tests.regression_helpers import REPO_ROOT


DOCTOR_PATH = REPO_ROOT / "skills/splunk-admin-doctor/scripts/doctor.py"
CLOUD_FIXTURE = REPO_ROOT / "skills/splunk-admin-doctor/fixtures/cloud_acs_rest_denied.json"
ENTERPRISE_FIXTURE = REPO_ROOT / "skills/splunk-admin-doctor/fixtures/enterprise_unhealthy.json"

spec = importlib.util.spec_from_file_location("splunk_admin_doctor", DOCTOR_PATH)
doctor = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(doctor)


LEGACY_RULE_IDS = [
    "SAD-APPS-RESTART-REQUIRED",
    "SAD-APPS-UPDATE-GAP",
    "SAD-AUTH-RBAC-GAP",
    "SAD-AUTH-TOKEN-RISK",
    "SAD-BACKUP-STALE",
    "SAD-CLOUD-ACS-ALLOWLIST-GAP",
    "SAD-CLOUD-ACS-DEGRADED",
    "SAD-CLOUD-CMC-ISSUE",
    "SAD-CONNECTIVITY-REST-DENIED",
    "SAD-CONNECTIVITY-TLS-UNVERIFIED",
    "SAD-DIAG-NOT-READY",
    "SAD-DISTSEARCH-PEER-DOWN",
    "SAD-ENT-BTOOL-ERRORS",
    "SAD-ENT-CONFIG-VALIDATION-104",
    "SAD-ENT-HEALTH-RED",
    "SAD-FWD-STALE",
    "SAD-IDXCLUSTER-DEGRADED",
    "SAD-INDEX-MISSING",
    "SAD-INDEX-RETENTION-RISK",
    "SAD-INGEST-COLLECTOR-GAP",
    "SAD-INGEST-HEC-DISABLED",
    "SAD-KO-ACCELERATION-RISK",
    "SAD-KVSTORE-FAILED",
    "SAD-LICENSE-CLOUD-ENTITLEMENT",
    "SAD-LICENSE-ENTERPRISE-VIOLATION",
    "SAD-MC-ALERTS-DISABLED",
    "SAD-MC-NOT-CONFIGURED",
    "SAD-PREMIUM-HANDOFFS",
    "SAD-SEARCH-EXPENSIVE",
    "SAD-SEARCH-SKIPPED",
    "SAD-SECURITY-DEFAULT-CERTS",
    "SAD-SECURITY-PUBLIC-EXPOSURE",
    "SAD-SECURITY-WEAK-TLS",
    "SAD-SHC-DEGRADED",
    "SAD-WLM-CLOUD-CMC-ISSUE",
    "SAD-WLM-GUARDRAILS-MISSING",
]


class SplunkAdminDoctorTests(unittest.TestCase):
    def test_compatibility_routes_derive_aliases_plus_one_canonical_override(self) -> None:
        catalog = load_catalog()
        expected_override = {
            "splunk-cloud-acs-allowlist-setup": "splunk-cloud-acs-admin-setup"
        }

        self.assertEqual(doctor.DEPRECATED_SKILL_ALIASES, dict(catalog.aliases))
        self.assertEqual(doctor.CANONICAL_ROUTING_OVERRIDES, expected_override)
        self.assertEqual(
            doctor.CANONICAL_SKILL_ALIASES,
            {**dict(catalog.aliases), **expected_override},
        )
        for source, target in expected_override.items():
            self.assertFalse(catalog.by_name[source].deprecated)
            self.assertFalse(catalog.by_name[target].deprecated)

    def test_direct_cli_help_documents_strict_platform_uri_status_and_exit_contracts(self) -> None:
        help_result = self.run_doctor("--help")
        self.assertEqual(help_result.returncode, 0, msg=help_result.stderr)
        for expected in (
            "never silently defaults to",
            "Enterprise.",
            "Credential-free HTTPS management origin",
            "report_valid",
            "health_status",
            "Exit codes: 0 success",
        ):
            self.assertIn(expected, help_result.stdout)

    def test_doctor_output_writer_rejects_symlink_and_hardlink_destinations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            victim = root / "victim"
            victim.write_text("keep\n", encoding="utf-8")
            victim.chmod(0o600)
            linked = root / "linked.json"
            linked.symlink_to(victim)
            with self.assertRaises(OSError):
                doctor.write_file(linked, "replacement\n")
            self.assertEqual("keep\n", victim.read_text(encoding="utf-8"))

            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaises(OSError):
                doctor.write_file(linked_parent / "report.json", "{}\n")
            self.assertFalse((real_parent / "report.json").exists())

            hardlink = root / "hardlink.json"
            os.link(victim, hardlink)
            with self.assertRaises(OSError):
                doctor.write_file(hardlink, "replacement\n")
            self.assertEqual("keep\n", victim.read_text(encoding="utf-8"))

    def test_cli_reports_secure_output_rejections_without_tracebacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            victim = root / "victim"
            victim.mkdir()
            linked_output = root / "linked-output"
            linked_output.symlink_to(victim, target_is_directory=True)
            result = self.run_doctor(
                "--evidence-file",
                str(CLOUD_FIXTURE),
                "--output-dir",
                str(linked_output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ERROR: secure file operation failed", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(list(victim.iterdir()), [])

            output = root / "output"
            output.mkdir()
            real_handoffs = root / "real-handoffs"
            real_handoffs.mkdir()
            (output / "handoffs").symlink_to(real_handoffs, target_is_directory=True)
            nested = self.run_doctor(
                "--phase",
                "apply",
                "--platform",
                "cloud",
                "--evidence-file",
                str(CLOUD_FIXTURE),
                "--output-dir",
                str(output),
                "--fixes",
                "SAD-CONNECTIVITY-REST-DENIED",
            )
            self.assertNotEqual(nested.returncode, 0)
            self.assertIn("ERROR: secure file operation failed", nested.stderr)
            self.assertNotIn("Traceback", nested.stderr)
            self.assertEqual(list(real_handoffs.iterdir()), [])

    def run_doctor(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(DOCTOR_PATH), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_rule_catalog_has_full_domain_coverage_and_required_fields(self) -> None:
        validation = doctor.validate_catalog()
        self.assertTrue(validation["ok"], validation)
        rule_ids = [item["id"] for item in doctor.RULE_CATALOG]
        self.assertEqual(rule_ids, sorted(set(rule_ids)))
        self.assertTrue(set(LEGACY_RULE_IDS).issubset(rule_ids))
        expected_skill_count = len(load_catalog().skills)
        self.assertEqual(validation["repository_skill_count"], expected_skill_count)
        self.assertEqual(validation["routed_repository_skill_count"], expected_skill_count)
        self.assertEqual(validation["unmapped_skills"], [])
        self.assertTrue(
            {
                "splunk-platform",
                "splunk-security",
                "splunk-itsi",
                "splunk-soar",
                "splunk-observability",
                "splunk-oncall",
                "splunk-appdynamics",
                "splunk-data-management",
                "splunk-ai",
                "splunk-mcp",
                "cisco",
            }.issubset({route["id"] for route in doctor.PRODUCT_ROUTE_CATALOG})
        )

        required = doctor.REQUIRED_RULE_FIELDS
        domains = {entry["domain"] for entry in doctor.COVERAGE_MANIFEST}
        rule_domains = {item["domain"] for item in doctor.RULE_CATALOG}
        self.assertTrue(domains.issubset(rule_domains))
        for item in doctor.RULE_CATALOG:
            with self.subTest(rule=item["id"]):
                self.assertTrue(required.issubset(item))
                self.assertIn(item["fix_kind"], doctor.FIX_KINDS)
                self.assertIn(item["platform"], {"cloud", "enterprise", "both"})

    def test_platform_gating_marks_non_applicable_domains(self) -> None:
        cloud_report, _, cloud_evidence = doctor.build_report(
            doctor.parse_args(["--platform", "cloud", "--evidence-file", str(CLOUD_FIXTURE)])
        )
        enterprise_report, _, enterprise_evidence = doctor.build_report(
            doctor.parse_args(["--platform", "enterprise", "--evidence-file", str(ENTERPRISE_FIXTURE)])
        )

        self.assertEqual(cloud_evidence["platform"], "cloud")
        self.assertEqual(enterprise_evidence["platform"], "enterprise")
        self.assertEqual(
            cloud_report["coverage"]["domains"]["Enterprise health"]["coverage"],
            "not_applicable",
        )
        self.assertEqual(
            enterprise_report["coverage"]["domains"]["Cloud ACS control plane"]["coverage"],
            "not_applicable",
        )
        for report in (cloud_report, enterprise_report):
            for domain, item in report["coverage"]["domains"].items():
                with self.subTest(platform=report["platform"], domain=domain):
                    self.assertIn(item["coverage"], doctor.FIX_KINDS)

    def test_cloud_fixture_covers_acs_rest_denied_cmc_hec_apps_and_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_doctor(
                "--phase",
                "doctor",
                "--evidence-file",
                str(CLOUD_FIXTURE),
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            report = json.loads(result.stdout)
            finding_ids = {item["id"] for item in report["findings"]}

            expected = {
                "SAD-CONNECTIVITY-REST-DENIED",
                "SAD-CLOUD-ACS-DEGRADED",
                "SAD-CLOUD-ACS-ALLOWLIST-GAP",
                "SAD-CLOUD-CMC-ISSUE",
                "SAD-INGEST-HEC-DISABLED",
                "SAD-APPS-UPDATE-GAP",
                "SAD-APPS-RESTART-REQUIRED",
                "SAD-LICENSE-CLOUD-ENTITLEMENT",
                "SAD-WLM-CLOUD-CMC-ISSUE",
                "SAD-PREMIUM-HANDOFFS",
            }
            self.assertTrue(expected.issubset(finding_ids))
            coverage = json.loads((Path(tmpdir) / "coverage-report.json").read_text(encoding="utf-8"))
            self.assertEqual(coverage["domains"]["Cloud Monitoring Console"]["coverage"], "delegated_fix")
            self.assertFalse(coverage["complete"])
            self.assertEqual(
                coverage["domains"]["Federated search"]["assessment"],
                "unknown",
            )

    def test_enterprise_fixture_covers_health_btool_kvstore_clusters_and_app_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_doctor(
                "--phase",
                "doctor",
                "--evidence-file",
                str(ENTERPRISE_FIXTURE),
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            report = json.loads(result.stdout)
            finding_ids = {item["id"] for item in report["findings"]}

            expected = {
                "SAD-CONNECTIVITY-TLS-UNVERIFIED",
                "SAD-ENT-HEALTH-RED",
                "SAD-ENT-BTOOL-ERRORS",
                "SAD-KVSTORE-FAILED",
                "SAD-SHC-DEGRADED",
                "SAD-IDXCLUSTER-DEGRADED",
                "SAD-APPS-UPDATE-GAP",
                "SAD-LICENSE-ENTERPRISE-VIOLATION",
                "SAD-SEARCH-SKIPPED",
                "SAD-SECURITY-PUBLIC-EXPOSURE",
            }
            self.assertTrue(expected.issubset(finding_ids))
            self.assertTrue((Path(tmpdir) / "doctor-report.md").exists())
            self.assertTrue((Path(tmpdir) / "fix-plan.json").exists())

    def test_every_rule_has_a_reachable_trigger(self) -> None:
        def set_path(payload: dict, dotted: str, value) -> None:
            current = payload
            parts = dotted.split(".")
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = value

        def matching_value(predicate: dict):
            if "equals" in predicate:
                return predicate["equals"]
            if "truthy" in predicate:
                return ["finding"] if predicate["truthy"] else []
            if "gt" in predicate:
                return float(predicate["gt"]) + 1
            if "in" in predicate:
                return next((item for item in predicate["in"] if item is not None), None)
            if "not_in" in predicate:
                return "__outside_expected_values__"
            if "prefix" in predicate:
                return str(predicate["prefix"]) + ".0"
            if "version_gte" in predicate:
                return predicate["version_gte"]
            self.fail(f"Unsupported predicate: {predicate}")

        for item in doctor.RULE_CATALOG:
            platform = "cloud" if item["platform"] == "cloud" else "enterprise"
            evidence = {"platform": platform}
            predicates = item["trigger"].get("all") or [item["trigger"]["any"][0]]
            for predicate in predicates:
                set_path(evidence, predicate["path"], matching_value(predicate))
            for predicate in doctor.trigger_predicates(item.get("applies_when", {})):
                set_path(evidence, predicate["path"], matching_value(predicate))
            products = doctor.build_product_coverage(evidence, platform)
            finding_ids = {finding["id"] for finding in doctor.evaluate_rules(evidence, platform, products)}
            with self.subTest(rule=item["id"]):
                self.assertIn(item["id"], finding_ids)

    def test_complete_healthy_evidence_can_assess_every_applicable_rule(self) -> None:
        def set_path(payload: dict, dotted: str, value) -> None:
            current = payload
            parts = dotted.split(".")
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = value

        def nonmatching_value(predicate: dict):
            if "equals" in predicate:
                expected = predicate["equals"]
                return not expected if isinstance(expected, bool) else "__different__"
            if "truthy" in predicate:
                return [] if predicate["truthy"] else ["present"]
            if "gt" in predicate:
                return predicate["gt"]
            if "in" in predicate:
                return "healthy"
            if "not_in" in predicate:
                return next((item for item in predicate["not_in"] if item is not None), "ok")
            if "prefix" in predicate:
                return "9.0"
            if "version_gte" in predicate:
                return "9.0"
            self.fail(f"Unsupported predicate: {predicate}")

        for platform in ("cloud", "enterprise"):
            evidence = {"platform": platform}
            for item in doctor.RULE_CATALOG:
                if not doctor.platform_applies(item["platform"], platform):
                    continue
                # A false OR trigger is resolved only when every branch has
                # assessed, non-matching evidence.  Supplying just the first
                # branch would incorrectly treat missing evidence as health.
                predicates = item["trigger"].get("all") or item["trigger"]["any"]
                for predicate in predicates:
                    set_path(evidence, predicate["path"], nonmatching_value(predicate))
                for predicate in doctor.trigger_predicates(item.get("applies_when", {})):
                    if "version_gte" in predicate:
                        set_path(evidence, predicate["path"], predicate["version_gte"])
                    else:
                        self.fail(f"Unsupported applicability predicate: {predicate}")
            products = doctor.build_product_coverage(evidence, platform)
            findings = doctor.evaluate_rules(evidence, platform, products)
            coverage = doctor.build_coverage(platform, findings, evidence, products)
            with self.subTest(platform=platform):
                self.assertEqual(findings, [])
                self.assertTrue(coverage["complete"])
                self.assertEqual(coverage["evidence_status_summary"].get("unknown", 0), 0)
                self.assertEqual(coverage["evidence_status_summary"].get("partial", 0), 0)

    def test_or_rules_require_boolean_proof_and_sentinels_are_unassessed(self) -> None:
        rest_rule = next(
            item for item in doctor.RULE_CATALOG if item["id"] == "SAD-CONNECTIVITY-REST-DENIED"
        )
        partial = {"rest": {"denied": False}}
        self.assertFalse(doctor.trigger_matches(rest_rule["trigger"], partial))
        self.assertFalse(doctor.rule_is_assessed(rest_rule, partial))

        resolved = {
            "rest": {
                "denied": False,
                "reachable": True,
                "status_code": 200,
                "probe_errors": [],
            }
        }
        self.assertTrue(doctor.rule_is_assessed(rest_rule, resolved))

        health_rule = next(
            item for item in doctor.RULE_CATALOG if item["id"] == "SAD-ENT-HEALTH-RED"
        )
        sentinel = {"splunkd": {"health": {"status": "unknown"}}}
        self.assertFalse(doctor.trigger_matches(health_rule["trigger"], sentinel))
        self.assertFalse(doctor.rule_is_assessed(health_rule, sentinel))

        all_trigger = {
            "all": [
                {"path": "feature.available", "equals": True},
                {"path": "feature.enabled", "equals": True},
            ]
        }
        self.assertTrue(
            doctor.trigger_is_resolved(all_trigger, {"feature": {"available": False}})
        )
        self.assertFalse(
            doctor.trigger_is_resolved(all_trigger, {"feature": {"available": True}})
        )
        self.assertTrue(
            doctor.trigger_matches(
                all_trigger,
                {"feature": {"available": True, "enabled": True}},
            )
        )

    def test_product_detection_routes_only_to_matching_specialists(self) -> None:
        evidence = {
            "platform": "cloud",
            "products": {"detected": ["Enterprise Security Cloud"]},
        }
        products = doctor.build_product_coverage(evidence, "cloud")
        findings = doctor.evaluate_rules(evidence, "cloud", products)
        finding = next(item for item in findings if item["id"] == "SAD-PREMIUM-HANDOFFS")
        handoffs = set(finding["handoff_skill"].split(","))

        self.assertEqual(
            handoffs,
            {"splunk-security-portfolio-setup", "splunk-data-source-readiness-doctor"},
        )
        self.assertEqual(products["detected_route_count"], 1)
        self.assertEqual(products["unresolved_detected_values"], [])

    def test_product_routing_uses_specific_precedence_and_inferred_apps(self) -> None:
        specific = doctor.build_product_coverage(
            {"products": {"detected": ["Splunk Enterprise Security Cloud"]}},
            "cloud",
        )
        detected_ids = {route["id"] for route in specific["routes"] if route["detected"]}
        self.assertEqual(detected_ids, {"splunk-security"})

        evidence = {
            "platform": "cloud",
            "products": {"detected": []},
            "apps": {"installed": [{"name": "SplunkEnterpriseSecuritySuite"}]},
        }
        explicit, inferred = doctor.detected_product_values(evidence)
        self.assertEqual(explicit, [])
        self.assertEqual(inferred, ["SplunkEnterpriseSecuritySuite"])
        products = doctor.build_product_coverage(evidence, "cloud")
        findings = doctor.evaluate_rules(
            {**evidence, "products": {"detected": inferred}},
            "cloud",
            products,
        )
        premium = next(item for item in findings if item["id"] == "SAD-PREMIUM-HANDOFFS")
        self.assertEqual(
            set(premium["handoff_skill"].split(",")),
            {"splunk-security-portfolio-setup", "splunk-data-source-readiness-doctor"},
        )
        galileo = doctor.build_product_coverage(
            {"products": {"detected": ["Galileo Agent Control"]}},
            "enterprise",
        )
        route = next(item for item in galileo["routes"] if item["detected"])
        self.assertEqual(route["id"], "galileo-agent-control")
        self.assertEqual(route["handoff_skills"], ["galileo-agent-control-setup"])

        soar = doctor.build_product_coverage(
            {"products": {"detected": ["SOAR"]}},
            "enterprise",
        )
        soar_route = next(item for item in soar["routes"] if item["detected"])
        self.assertEqual(soar_route["id"], "splunk-soar")
        self.assertEqual(soar["unresolved_detected_values"], [])

    def test_cloud_config_cluster_and_workload_are_applicable(self) -> None:
        report, _, _ = doctor.build_report(
            doctor.parse_args(["--platform", "cloud", "--evidence-file", str(CLOUD_FIXTURE)])
        )
        domains = report["coverage"]["domains"]

        self.assertTrue(domains["Config validation"]["platform_applicable"])
        self.assertTrue(domains["Distributed search and SHC"]["platform_applicable"])
        self.assertTrue(domains["Indexer clustering"]["platform_applicable"])
        self.assertEqual(domains["Workload management"]["coverage"], "direct_fix")

    def test_config_validation_rules_only_find_actual_validation_gaps(self) -> None:
        evidence = {
            "platform": "enterprise",
            "server": {"version": "10.4.1"},
            "config_validation": {"available": True, "validated": True, "errors": []},
        }
        doctor.augment_lifecycle_evidence(evidence, "enterprise")
        products = doctor.build_product_coverage(evidence, "enterprise")
        findings = doctor.evaluate_rules(evidence, "enterprise", products)
        self.assertNotIn(
            "SAD-ENT-CONFIG-VALIDATION-104",
            {item["id"] for item in findings},
        )
        rule = next(
            item for item in doctor.RULE_CATALOG if item["id"] == "SAD-ENT-CONFIG-VALIDATION-104"
        )
        self.assertTrue(doctor.rule_environment_applicable(rule, evidence))
        self.assertTrue(doctor.rule_is_assessed(rule, evidence))

        older = {"server": {"version": "10.2.4"}}
        self.assertFalse(doctor.rule_environment_applicable(rule, older))

        no_version_healthy = {
            "config_validation": {"available": True, "validated": True, "errors": []}
        }
        self.assertTrue(doctor.rule_environment_applicable(rule, no_version_healthy))
        self.assertFalse(doctor.rule_eligibility_confirmed(rule, no_version_healthy))
        self.assertFalse(doctor.rule_is_assessed(rule, no_version_healthy))
        self.assertIn("server.version", doctor.rule_evidence_paths(rule))
        self.assertNotIn(
            rule["id"],
            {
                item["id"]
                for item in doctor.evaluate_rules(
                    {"config_validation": {"available": False}},
                    "enterprise",
                    doctor.build_product_coverage({}, "enterprise"),
                )
            },
        )

    def test_optional_features_require_explicit_applicability_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_path = Path(tmpdir) / "applicability.json"
            evidence_path.write_text(
                json.dumps(
                    {
                        "platform": "cloud",
                        "applicability": {
                            "domains": {"Federated search": False},
                            "rules": {"SAD-SECURE-GATEWAY-GAP": False},
                        },
                    }
                ),
                encoding="utf-8",
            )
            report, _, _ = doctor.build_report(
                doctor.parse_args(["--evidence-file", str(evidence_path)])
            )

        federated = report["coverage"]["domains"]["Federated search"]
        dashboards = report["coverage"]["domains"]["Dashboards and user experience"]
        self.assertEqual(federated["assessment"], "not_applicable")
        self.assertFalse(federated["environment_applicable"])
        self.assertIn("SAD-SECURE-GATEWAY-GAP", dashboards["explicitly_not_applicable_rule_ids"])
        self.assertNotIn("SAD-SECURE-GATEWAY-GAP", dashboards["unassessed_rule_ids"])

    def test_mandatory_applicability_cannot_be_disabled(self) -> None:
        for applicability in (
            {"domains": {"Connectivity and credentials": False}},
            {"rules": {"SAD-CONNECTIVITY-REST-DENIED": False}},
        ):
            with self.subTest(applicability=applicability), tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "evidence.json"
                path.write_text(
                    json.dumps({"platform": "cloud", "applicability": applicability}),
                    encoding="utf-8",
                )
                result = self.run_doctor("--evidence-file", str(path), "--dry-run")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mandatory", result.stderr)

    def test_semantic_version_predicate_covers_newer_enterprise_versions(self) -> None:
        evidence = {"server": {"version": "11.0.1"}}
        predicate = {"path": "server.version", "version_gte": "10.4"}
        self.assertTrue(doctor.predicate_matches(predicate, evidence))
        self.assertFalse(doctor.predicate_matches(predicate, {"server": {"version": "10.2.9"}}))

    def test_lifecycle_contract_flags_eos_and_unreleased_enterprise_trains(self) -> None:
        eos = {"server": {"version": "9.2.5"}}
        unreleased = {"server": {"version": "10.1.0"}}
        doctor.augment_lifecycle_evidence(eos, "enterprise")
        doctor.augment_lifecycle_evidence(unreleased, "enterprise")

        self.assertTrue(eos["lifecycle"]["version_unsupported"])
        self.assertTrue(eos["lifecycle"]["eos"])
        self.assertTrue(unreleased["lifecycle"]["version_unsupported"])
        self.assertIn("Cloud-only", unreleased["lifecycle"]["upgrade_path_issues"][0])

    def test_lifecycle_contract_recognizes_cloud_10_5_and_rejects_enterprise_10_5(self) -> None:
        cloud = {"server": {"version": "10.5.2605"}}
        enterprise = {"server": {"version": "10.5.0"}}
        doctor.augment_lifecycle_evidence(cloud, "cloud")
        doctor.augment_lifecycle_evidence(enterprise, "enterprise")

        self.assertFalse(cloud["lifecycle"]["version_unsupported"])
        self.assertIn("10.5.2605", cloud["lifecycle"]["documented_cloud_trains"])
        self.assertTrue(enterprise["lifecycle"]["version_unsupported"])
        self.assertIn("not in the current public Enterprise release contract", enterprise["lifecycle"]["upgrade_path_issues"][0])

    def test_lifecycle_derivation_cannot_be_suppressed_and_timestamps_are_consistent(self) -> None:
        evidence = {
            "server": {"version": "9.2.5"},
            "lifecycle": {"version_unsupported": False, "eos": False},
        }
        doctor.augment_lifecycle_evidence(evidence, "enterprise")
        self.assertTrue(evidence["lifecycle"]["version_unsupported"])
        self.assertTrue(evidence["lifecycle"]["eos"])

        report, plan, _ = doctor.build_report(
            doctor.parse_args(["--evidence-file", str(ENTERPRISE_FIXTURE)])
        )
        timestamps = {report["generated_at"], plan["generated_at"]}
        timestamps.update(item["observed_at"] for item in report["findings"])
        self.assertEqual(len(timestamps), 1)

    def test_health_summary_separates_findings_from_evidence_completeness(self) -> None:
        sentinel = {"id": "SAD-EVIDENCE-INCOMPLETE", "severity": "medium"}
        finding = {"id": "SAD-CONNECTIVITY-REST-DENIED", "severity": "high"}
        cases = (
            ([], True, "healthy", True),
            ([sentinel], False, "incomplete", False),
            ([finding], True, "findings", False),
            ([sentinel, finding], False, "findings_and_incomplete", False),
        )
        for findings, complete, expected_status, healthy in cases:
            with self.subTest(expected_status=expected_status):
                summary = doctor.report_health_summary(findings, {"complete": complete})
                self.assertTrue(summary["report_valid"])
                self.assertEqual(summary["evidence_complete"], complete)
                self.assertEqual(summary["health_status"], expected_status)
                self.assertEqual(summary["healthy"], healthy)
                self.assertEqual(summary["severity_counts"]["total"], len(findings))
                self.assertEqual(
                    summary["health_relevant_finding_count"],
                    sum(item["id"] != "SAD-EVIDENCE-INCOMPLETE" for item in findings),
                )

    def test_apply_selected_fix_renders_local_packet_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_doctor(
                "--phase",
                "apply",
                "--evidence-file",
                str(CLOUD_FIXTURE),
                "--output-dir",
                tmpdir,
                "--fixes",
                "SAD-CONNECTIVITY-REST-DENIED,SAD-CLOUD-ACS-ALLOWLIST-GAP",
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            applied = json.loads(result.stdout)
            report = json.loads((Path(tmpdir) / "doctor-report.json").read_text(encoding="utf-8"))
            self.assertEqual(applied["generated_at"], report["generated_at"])
            self.assertTrue(applied["selected_fixes"])
            self.assertFalse(any(item["live_mutation_performed"] for item in applied["selected_fixes"]))
            self.assertTrue((Path(tmpdir) / "handoffs" / "SAD-CONNECTIVITY-REST-DENIED.md").exists())
            self.assertTrue((Path(tmpdir) / "handoffs" / "SAD-CLOUD-ACS-ALLOWLIST-GAP.md").exists())
            manifest = json.loads((Path(tmpdir) / "artifact-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["phase"], "apply")
            expected_artifacts = {
                *doctor.BASE_ARTIFACT_RELATIVE_PATHS,
                "applied-fixes.json",
                "handoffs/SAD-CONNECTIVITY-REST-DENIED.md",
                "handoffs/SAD-CLOUD-ACS-ALLOWLIST-GAP.md",
            }
            self.assertEqual(set(manifest["artifacts"]), expected_artifacts)
            self.assertEqual(manifest["artifact_count"], len(expected_artifacts))
            for relative, metadata in manifest["artifacts"].items():
                with self.subTest(relative=relative):
                    self.assertEqual(metadata, doctor.artifact_metadata(Path(tmpdir) / relative))
            status = self.run_doctor(
                "--phase",
                "status",
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(status.returncode, 0, msg=status.stdout + status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertTrue(status_payload["report_valid"])
            self.assertEqual(status_payload["ok"], status_payload["report_valid"])
            self.assertTrue(status_payload["integrity_verified"])
            for field in (
                "healthy",
                "evidence_complete",
                "health_status",
                "severity_counts",
                "highest_severity",
                "health_relevant_finding_count",
                "strict_ready",
            ):
                self.assertEqual(status_payload[field], report[field])

    def test_status_rejects_missing_or_tampered_integrity_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            generated = self.run_doctor(
                "--evidence-file",
                str(CLOUD_FIXTURE),
                "--output-dir",
                tmpdir,
            )
            self.assertEqual(generated.returncode, 0, msg=generated.stdout + generated.stderr)
            coverage = Path(tmpdir) / "coverage-report.json"
            with coverage.open("a", encoding="utf-8") as handle:
                handle.write(" \n")
            tampered = self.run_doctor(
                "--phase",
                "status",
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(tampered.returncode, 1)
            tampered_payload = json.loads(tampered.stdout)
            self.assertFalse(tampered_payload["report_valid"])
            self.assertFalse(tampered_payload["ok"])
            self.assertFalse(tampered_payload["integrity_verified"])
            self.assertTrue(any("mismatch" in item for item in tampered_payload["errors"]))

            regenerated = self.run_doctor(
                "--evidence-file",
                str(CLOUD_FIXTURE),
                "--output-dir",
                tmpdir,
            )
            self.assertEqual(regenerated.returncode, 0, msg=regenerated.stdout + regenerated.stderr)
            (Path(tmpdir) / "artifact-manifest.json").unlink()
            missing = self.run_doctor(
                "--phase",
                "status",
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(missing.returncode, 1)
            missing_payload = json.loads(missing.stdout)
            self.assertEqual(missing_payload["status"], "invalid")
            self.assertTrue(any("manifest is missing" in item for item in missing_payload["errors"]))

    def test_secret_redaction_keeps_token_values_out_of_rendered_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_path = Path(tmpdir) / "evidence.json"
            output_dir = Path(tmpdir) / "out"
            evidence_path.write_text(
                json.dumps(
                    {
                        "platform": "cloud",
                        "rest": {"denied": True, "status_code": 403},
                        "auth": {
                            "token_value": "SUPER_SECRET_TOKEN_VALUE",
                            "weak_tokens": ["automation-token"],
                        },
                        "credential": "CREDENTIAL_SECRET_VALUE",
                        "clientSecret": "CLIENT_SECRET_VALUE",
                        "authToken": "AUTH_TOKEN_VALUE",
                        "pass4SymmKey": "SYMMETRIC_SECRET_VALUE",
                        "sslPassword": "SSL_PASSWORD_VALUE",
                        "privateKeyPassword": "PRIVATE_KEY_PASSWORD_VALUE",
                        "db_password": "DB_PASSWORD_VALUE",
                        "admin_token": "ADMIN_TOKEN_VALUE",
                        "apiSecret": "API_SECRET_VALUE",
                        "sessionToken": "SESSION_TOKEN_VALUE",
                        "secret_key": "SECRET_KEY_VALUE",
                        "authorization_header": "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
                        "notes": [
                            "db_password=STRING_DB_PASSWORD",
                            "admin_token=x",
                            "Bearer short-token",
                            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.signature",
                            "-----BEGIN PRIVATE KEY-----\nPRIVATE_MATERIAL\n-----END PRIVATE KEY-----",
                            "Authorization: Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
                            'password = "OPEN SESAME VALUE"',
                            '{"db_password":"TWO WORD SECRET","admin_token":"QUOTED TOKEN"}',
                            'password="ROW_ONE_123\nROW_TWO_456\nROW_THREE_789"',
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_doctor(
                "--phase",
                "doctor",
                "--evidence-file",
                str(evidence_path),
                "--output-dir",
                str(output_dir),
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            rendered = "\n".join(
                path.read_text(encoding="utf-8")
                for path in output_dir.rglob("*")
                if path.is_file()
            )
            self.assertNotIn("SUPER_SECRET_TOKEN_VALUE", rendered)
            self.assertNotIn("CREDENTIAL_SECRET_VALUE", rendered)
            self.assertNotIn("CLIENT_SECRET_VALUE", rendered)
            self.assertNotIn("AUTH_TOKEN_VALUE", rendered)
            self.assertNotIn("SYMMETRIC_SECRET_VALUE", rendered)
            self.assertNotIn("SSL_PASSWORD_VALUE", rendered)
            self.assertNotIn("PRIVATE_KEY_PASSWORD_VALUE", rendered)
            for secret in (
                "DB_PASSWORD_VALUE",
                "ADMIN_TOKEN_VALUE",
                "API_SECRET_VALUE",
                "SESSION_TOKEN_VALUE",
                "SECRET_KEY_VALUE",
                "QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
                "STRING_DB_PASSWORD",
                "short-token",
                "eyJhbGciOiJIUzI1NiJ9",
                "PRIVATE_MATERIAL",
                "OPEN SESAME VALUE",
                "TWO WORD SECRET",
                "QUOTED TOKEN",
                "ROW_ONE_123",
                "ROW_TWO_456",
                "ROW_THREE_789",
            ):
                self.assertNotIn(secret, rendered)
            self.assertIn("[REDACTED]", rendered)
            for path in output_dir.rglob("*"):
                if path.is_file():
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_normalized_evidence_artifact_and_supplied_collection_notes_are_truthful(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            evidence_path = root / "supplied.json"
            output = root / "output"
            legacy_path = output / "evidence" / "input-evidence.redacted.json"
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text("stale legacy artifact\n", encoding="utf-8")
            legacy_path.chmod(0o600)
            evidence_path.write_text(
                json.dumps(
                    {
                        "platform": "cloud",
                        "collection": {
                            "notes": [
                                "upstream collector supplied this snapshot",
                                "password=COLLECTION_NOTE_SECRET",
                                "```\n# markdown-looking source note",
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_doctor(
                "--evidence-file",
                str(evidence_path),
                "--output-dir",
                str(output),
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            normalized_path = output / "evidence" / "normalized-evidence.redacted.json"
            self.assertTrue(normalized_path.is_file())
            self.assertFalse(legacy_path.exists())
            normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
            self.assertEqual(normalized["doctor_normalization"]["source"], "supplied_evidence_snapshot")
            self.assertFalse(
                normalized["doctor_normalization"]["local_collection_performed_by_doctor"]
            )
            notes = (output / "evidence" / "collection-notes.md").read_text(encoding="utf-8")
            self.assertIn("normalized, augmented, and redacted", notes)
            self.assertIn("did not independently collect", notes)
            self.assertIn("upstream collector supplied this snapshot", notes)
            self.assertIn("[REDACTED]", notes)
            self.assertNotIn("COLLECTION_NOTE_SECRET", notes)

    def test_local_collection_notes_report_actual_bounded_probe_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            splunk_home = root / "missing-splunk"
            output = root / "output"
            result = self.run_doctor(
                "--platform",
                "enterprise",
                "--splunk-home",
                str(splunk_home),
                "--output-dir",
                str(output),
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            normalized = json.loads(
                (output / "evidence" / "normalized-evidence.redacted.json").read_text(encoding="utf-8")
            )
            self.assertEqual(normalized["doctor_normalization"]["source"], "local_enterprise_probe")
            self.assertTrue(
                normalized["doctor_normalization"]["local_collection_performed_by_doctor"]
            )
            notes = (output / "evidence" / "collection-notes.md").read_text(encoding="utf-8")
            self.assertIn("Local collection performed by this doctor run: `yes`", notes)
            self.assertIn("Splunk binary not found", notes)

    def test_uri_userinfo_path_and_secret_query_are_rejected_without_echo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_doctor(
                "--phase",
                "doctor",
                "--platform",
                "cloud",
                "--splunk-uri",
                "https://admin:URI_PASSWORD@example.test:8089/services?authToken=QUERY_TOKEN_VALUE",
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            rendered = result.stdout + "\n" + "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(tmpdir).rglob("*")
                if path.is_file()
            )
            self.assertNotIn("URI_PASSWORD", rendered)
            self.assertNotIn("QUERY_TOKEN_VALUE", rendered)
            self.assertNotIn("admin:", rendered)
            self.assertFalse((Path(tmpdir) / "doctor-report.json").exists())

    def test_management_uri_validation_and_platform_auto_detection_fail_closed(self) -> None:
        inferred = self.run_doctor(
            "--splunk-uri",
            "HTTPS://Stack.SplunkCloud.Com.:8089/",
            "--dry-run",
            "--json",
        )
        self.assertEqual(inferred.returncode, 0, msg=inferred.stdout + inferred.stderr)
        inferred_report = json.loads(inferred.stdout)
        self.assertEqual(inferred_report["platform"], "cloud")
        self.assertEqual(inferred_report["splunk_uri"], "https://stack.splunkcloud.com:8089")

        for ambiguous_uri in (
            "",
            "https://splunkcloud.com",
            "https://evil-splunkcloud.com",
            "https://example.test:8089",
        ):
            with self.subTest(ambiguous_uri=ambiguous_uri):
                args = ["--dry-run", "--json"]
                if ambiguous_uri:
                    args.extend(["--splunk-uri", ambiguous_uri])
                ambiguous = self.run_doctor(*args)
                self.assertNotEqual(ambiguous.returncode, 0)
                self.assertIn("auto-detection is ambiguous", ambiguous.stderr)

        enterprise_cloud_host = self.run_doctor(
            "--platform",
            "enterprise",
            "--splunk-uri",
            "https://stack.splunkcloud.com:8089",
            "--dry-run",
        )
        self.assertNotEqual(enterprise_cloud_host.returncode, 0)
        self.assertIn("conflicts", enterprise_cloud_host.stderr)

        with tempfile.TemporaryDirectory() as tmpdir:
            no_platform = Path(tmpdir) / "evidence.json"
            no_platform.write_text(json.dumps({"acs": {"reachable": True}}), encoding="utf-8")
            evidence_ambiguous = self.run_doctor(
                "--evidence-file",
                str(no_platform),
                "--dry-run",
            )
        self.assertNotEqual(evidence_ambiguous.returncode, 0)
        self.assertIn("auto-detection is ambiguous", evidence_ambiguous.stderr)

    def test_management_uri_rejects_invalid_origins_and_original_control_characters(self) -> None:
        invalid_values = (
            "http://example.test:8089",
            "https://example.test:8089/services",
            "https://example.test:8089?token=secret-value",
            "https://example.test:8089?",
            "https://example.test:8089#fragment",
            "https://example.test:8089#",
            "https://example.test:not-a-port",
            "https://example.test:65536",
            "https://bad host.test:8089",
            "https://example.test:8089\n.evil.test",
            "https://example.test:8089\t.evil.test",
        )
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                rejected = self.run_doctor(
                    "--platform",
                    "cloud",
                    "--splunk-uri",
                    value,
                    "--dry-run",
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertNotIn("secret-value", rejected.stderr)
                self.assertNotIn("Traceback", rejected.stderr)

        for value in (
            "https://example.test:8089\r.evil.test",
            "https://example.test:8089\x00.evil.test",
            " https://example.test:8089",
        ):
            with self.subTest(direct_value=repr(value)):
                with self.assertRaisesRegex(ValueError, "whitespace or control"):
                    doctor.normalize_management_uri(value)

    def test_apply_dry_run_validates_selection_and_complete_evidence_mode_fails_closed(self) -> None:
        invalid = self.run_doctor(
            "--phase",
            "apply",
            "--evidence-file",
            str(CLOUD_FIXTURE),
            "--fixes",
            "SAD-NOT-A-RULE",
            "--dry-run",
        )
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("not active", invalid.stderr)

        incomplete = self.run_doctor(
            "--phase",
            "doctor",
            "--evidence-file",
            str(CLOUD_FIXTURE),
            "--require-complete-evidence",
            "--dry-run",
        )
        self.assertEqual(incomplete.returncode, 3, msg=incomplete.stdout + incomplete.stderr)

    def test_invalid_apply_preserves_an_existing_output_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out"
            output.mkdir()
            report = output / "doctor-report.json"
            report.write_text("previous-report\n", encoding="utf-8")
            report.chmod(0o600)
            handoffs = output / "handoffs"
            handoffs.mkdir()
            packet = handoffs / "SAD-KEEP.md"
            packet.write_text("previous-packet\n", encoding="utf-8")
            packet.chmod(0o600)

            result = self.run_doctor(
                "--phase",
                "apply",
                "--evidence-file",
                str(CLOUD_FIXTURE),
                "--output-dir",
                str(output),
                "--fixes",
                "SAD-NOT-A-RULE",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report.read_text(encoding="utf-8"), "previous-report\n")
            self.assertEqual(packet.read_text(encoding="utf-8"), "previous-packet\n")

    def test_evidence_schema_rejects_platform_conflicts_and_nonobject_inputs(self) -> None:
        conflict = self.run_doctor(
            "--platform",
            "enterprise",
            "--evidence-file",
            str(CLOUD_FIXTURE),
            "--dry-run",
        )
        self.assertNotEqual(conflict.returncode, 0)
        self.assertIn("conflicts with evidence platform", conflict.stderr)

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = Path(tmpdir) / "bad.json"
            bad_path.write_text(json.dumps({"platform": "cloud", "inputs": []}), encoding="utf-8")
            bad = self.run_doctor("--evidence-file", str(bad_path), "--dry-run")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("must be a JSON object", bad.stderr)

        with tempfile.TemporaryDirectory() as tmpdir:
            unknown_path = Path(tmpdir) / "unknown-applicability.json"
            unknown_path.write_text(
                json.dumps(
                    {
                        "platform": "cloud",
                        "applicability": {"rules": {"SAD-NOT-A-RULE": False}},
                    }
                ),
                encoding="utf-8",
            )
            unknown = self.run_doctor("--evidence-file", str(unknown_path), "--dry-run")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("unknown names", unknown.stderr)

    def test_evidence_reader_rejects_symlinks_hardlinks_and_nonfinite_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target.json"
            target.write_text('{"platform":"cloud"}\n', encoding="utf-8")
            symlink = root / "linked.json"
            symlink.symlink_to(target)
            linked = self.run_doctor("--evidence-file", str(symlink), "--dry-run")
            self.assertNotEqual(linked.returncode, 0)
            self.assertNotIn("Traceback", linked.stderr)

            hardlink = root / "hardlinked.json"
            os.link(target, hardlink)
            hardlinked = self.run_doctor("--evidence-file", str(hardlink), "--dry-run")
            self.assertNotEqual(hardlinked.returncode, 0)
            self.assertIn("exactly one hard link", hardlinked.stderr)

            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"platform":"cloud","value":NaN}\n', encoding="utf-8")
            invalid = self.run_doctor("--evidence-file", str(nonfinite), "--dry-run")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("non-finite", invalid.stderr)
            self.assertNotIn("Traceback", invalid.stderr)

            fifo = root / "fifo.json"
            os.mkfifo(fifo)
            blocked = self.run_doctor("--evidence-file", str(fifo), "--dry-run")
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("not a regular file", blocked.stderr)
            self.assertNotIn("Traceback", blocked.stderr)

    def test_status_rejects_incompatible_schema_and_outputs_reject_shared_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "output"
            output.mkdir()
            report = output / "doctor-report.json"
            incompatible_report = {
                "schema_version": 1,
                "skill": "splunk-admin-doctor",
                "generated_at": "2026-07-03T00:00:00+00:00",
                "platform": "cloud",
                "findings": [],
                "coverage": {},
                "product_coverage": {"routes": []},
                "catalog": {"rule_count": len(doctor.RULE_CATALOG)},
            }
            self.assertIn("coverage.complete must be boolean", doctor.report_schema_errors(incompatible_report))
            report.write_text(json.dumps(incompatible_report), encoding="utf-8")
            report.chmod(0o600)
            lock = output / doctor.OUTPUT_LOCK_NAME
            lock.write_text("pid=test\n", encoding="utf-8")
            lock.chmod(0o600)
            status = self.run_doctor(
                "--phase",
                "status",
                "--output-dir",
                str(output),
                "--json",
            )
            self.assertEqual(status.returncode, 1)
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload["status"], "invalid")
            self.assertFalse(status_payload["report_valid"])
            self.assertEqual(status_payload["ok"], status_payload["report_valid"])
            self.assertTrue(any("manifest is missing" in item for item in status_payload["errors"]))

            shared = Path(tmpdir) / "shared"
            shared.mkdir(mode=0o777)
            shared.chmod(0o777)
            unsafe = self.run_doctor(
                "--evidence-file",
                str(CLOUD_FIXTURE),
                "--output-dir",
                str(shared),
            )
            self.assertNotEqual(unsafe.returncode, 0)
            self.assertIn("not group/world writable", unsafe.stderr)
            self.assertFalse((shared / "doctor-report.json").exists())

    def test_local_btool_timeout_remains_unassessed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            splunk = Path(tmpdir) / "bin" / "splunk"
            splunk.parent.mkdir()
            splunk.write_text("#!/bin/sh\n", encoding="utf-8")
            args = doctor.parse_args(["--splunk-home", tmpdir])
            with mock.patch.object(
                doctor,
                "run_local_command",
                return_value={"returncode": None, "error": "timed out"},
            ):
                evidence = doctor.collect_local_enterprise_evidence(args)
        self.assertNotIn("btool", evidence)
        self.assertTrue(any("not assessed" in item for item in evidence["collection"]["notes"]))

    def test_output_bundle_writer_lock_is_secure_and_nonblocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "output"
            with doctor.output_bundle_lock(output):
                started = time.monotonic()
                blocked = self.run_doctor(
                    "--evidence-file",
                    str(CLOUD_FIXTURE),
                    "--output-dir",
                    str(output),
                )
                elapsed = time.monotonic() - started
                self.assertNotEqual(blocked.returncode, 0)
                self.assertIn("locked by another process", blocked.stderr)
                self.assertLess(elapsed, 5)
            lock_path = output / doctor.OUTPUT_LOCK_NAME
            self.assertEqual(lock_path.stat().st_mode & 0o777, 0o600)
            self.assertFalse((output / "doctor-report.json").exists())

    def test_two_writers_racing_to_create_missing_output_root_reach_bundle_lock(self) -> None:
        worker_code = """
import importlib.util
import os
import sys
import time
from pathlib import Path

doctor_path = Path(sys.argv[1])
output = Path(sys.argv[2])
barrier = Path(sys.argv[3])
worker_id = sys.argv[4]
fixture = Path(sys.argv[5])
spec = importlib.util.spec_from_file_location("doctor_race_worker", doctor_path)
doctor = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(doctor)

original_mkdir = os.mkdir
ready = barrier / (worker_id + ".ready")

def synchronized_mkdir(component, mode=0o777, *, dir_fd=None):
    if component == output.name and not ready.exists():
        ready.write_text("ready\\n", encoding="utf-8")
        deadline = time.monotonic() + 5
        while len(list(barrier.glob("*.ready"))) < 2:
            if time.monotonic() >= deadline:
                raise RuntimeError("mkdir race barrier timed out")
            time.sleep(0.01)
    return original_mkdir(component, mode, dir_fd=dir_fd)

doctor.os.mkdir = synchronized_mkdir
original_write_base_outputs = doctor.write_base_outputs

def slow_write_base_outputs(*args, **kwargs):
    time.sleep(1)
    return original_write_base_outputs(*args, **kwargs)

doctor.write_base_outputs = slow_write_base_outputs
arguments = doctor.parse_args(
    [
        "--evidence-file",
        str(fixture),
        "--output-dir",
        str(output),
    ]
)
try:
    return_code = doctor.execute(arguments)
except RuntimeError as exc:
    if "locked by another process" not in str(exc):
        raise
    print(f"ERROR: secure file operation failed: {exc}", file=sys.stderr)
    return_code = 1
raise SystemExit(return_code)
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output = root / "shared-first-create"
            barrier = root / "barrier"
            barrier.mkdir()
            self.assertFalse(output.exists())
            workers = [
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        worker_code,
                        str(DOCTOR_PATH),
                        str(output),
                        str(barrier),
                        str(index),
                        str(CLOUD_FIXTURE),
                    ],
                    cwd=REPO_ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for index in range(2)
            ]
            results = []
            for worker in workers:
                stdout, stderr = worker.communicate(timeout=15)
                results.append((worker.returncode, stdout, stderr))

            self.assertEqual(sorted(item[0] for item in results), [0, 1], results)
            combined = "\n".join(item[1] + item[2] for item in results)
            self.assertIn("locked by another process", combined)
            self.assertNotIn("File exists", combined)
            self.assertNotIn("[Errno 17]", combined)
            self.assertNotIn("Traceback", combined)
            self.assertTrue((output / "artifact-manifest.json").is_file())
            status = self.run_doctor(
                "--phase",
                "status",
                "--output-dir",
                str(output),
                "--json",
            )
            self.assertEqual(status.returncode, 0, msg=status.stdout + status.stderr)
            self.assertTrue(json.loads(status.stdout)["integrity_verified"])

    def test_local_command_timeout_does_not_wait_for_detached_descendant_pipe_eof(self) -> None:
        child_pid = 0
        command = (
            "import subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'], "
            "start_new_session=True,stdout=sys.stdout,stderr=sys.stderr); "
            "print(child.pid,flush=True); time.sleep(30)"
        )
        started = time.monotonic()
        try:
            result = doctor.run_local_command([sys.executable, "-c", command], timeout=0.2)
            elapsed = time.monotonic() - started
            self.assertIsNone(result["returncode"])
            self.assertIn("timed out", result["error"])
            self.assertLess(elapsed, 3)
            child_pid = int(result["stdout_tail"].strip().splitlines()[-1])
        finally:
            if child_pid:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_catalog_validator_rejects_ambiguous_expressions_and_platform_drift(self) -> None:
        ambiguous = copy.deepcopy(doctor.RULE_CATALOG)
        ambiguous[0]["trigger"] = {
            "any": [{"path": "x.y", "equals": True}],
            "all": [{"path": "x.y", "equals": True}],
        }
        with mock.patch.object(doctor, "RULE_CATALOG", ambiguous):
            validation = doctor.validate_catalog()
        self.assertFalse(validation["ok"])
        self.assertTrue(any("exactly one" in item for item in validation["errors"]))

        drift = copy.deepcopy(doctor.RULE_CATALOG)
        cloud_rule = next(item for item in drift if item["domain"] == "Cloud ACS control plane")
        cloud_rule["platform"] = "enterprise"
        with mock.patch.object(doctor, "RULE_CATALOG", drift):
            validation = doctor.validate_catalog()
        self.assertFalse(validation["ok"])
        self.assertTrue(any("platform exceeds" in item for item in validation["errors"]))

    def test_no_direct_fix_contains_disruptive_apply_action(self) -> None:
        for item in doctor.RULE_CATALOG:
            if item["fix_kind"] == "direct_fix":
                with self.subTest(rule=item["id"]):
                    self.assertIsNone(doctor.DIRECT_DANGEROUS_RE.search(item["apply_command"]))

    def test_mcp_generic_doctor_scripts_are_always_mutation_gated(self) -> None:
        generic_cases = [
            ["--phase", "doctor"],
            ["--phase", "fix-plan", "--evidence-file", str(CLOUD_FIXTURE)],
            ["--phase", "validate"],
            ["--phase", "status"],
            ["--phase", "apply", "--fixes", "SAD-CONNECTIVITY-REST-DENIED", "--dry-run"],
        ]
        for args in generic_cases:
            with self.subTest(args=args):
                plan = core.plan_skill_script("splunk-admin-doctor", "setup.sh", args)
                self.assertFalse(plan["read_only"])
                direct_plan = core.plan_skill_script("splunk-admin-doctor", "doctor.py", args)
                self.assertFalse(direct_plan["read_only"])

        mutating_plan = core.plan_skill_script(
            "splunk-admin-doctor",
            "setup.sh",
            ["--phase", "apply", "--fixes", "SAD-CONNECTIVITY-REST-DENIED"],
        )
        self.assertFalse(mutating_plan["read_only"])
        direct_mutating_plan = core.plan_skill_script(
            "splunk-admin-doctor",
            "doctor.py",
            ["--phase", "apply", "--fixes", "SAD-CONNECTIVITY-REST-DENIED"],
        )
        self.assertFalse(direct_mutating_plan["read_only"])
        live_plan = core.plan_skill_script(
            "splunk-admin-doctor",
            "live_validate_all.py",
            ["--profile", "onprem_2535", "--once"],
        )
        self.assertFalse(live_plan["read_only"])
        live_apply_plan = core.plan_skill_script(
            "splunk-admin-doctor",
            "live_validate_all.py",
            ["--profile", "onprem_2535", "--allow-apply", "--once"],
        )
        self.assertFalse(live_apply_plan["read_only"])

        with self.assertRaisesRegex(core.SkillMCPError, "Direct secret flag"):
            core.plan_skill_script("splunk-admin-doctor", "setup.sh", ["--password", "secret"])


if __name__ == "__main__":
    unittest.main()
