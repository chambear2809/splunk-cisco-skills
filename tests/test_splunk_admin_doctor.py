#!/usr/bin/env python3
"""Regression coverage for the Splunk Admin Doctor skill."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.splunk_cisco_skills_mcp import core
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
        self.assertEqual(validation["repository_skill_count"], 165)
        self.assertEqual(validation["routed_repository_skill_count"], 165)
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
                predicates = item["trigger"].get("all") or [item["trigger"]["any"][0]]
                for predicate in predicates:
                    set_path(evidence, predicate["path"], nonmatching_value(predicate))
            products = doctor.build_product_coverage(evidence, platform)
            findings = doctor.evaluate_rules(evidence, platform, products)
            coverage = doctor.build_coverage(platform, findings, evidence, products)
            with self.subTest(platform=platform):
                self.assertEqual(findings, [])
                self.assertTrue(coverage["complete"])
                self.assertEqual(coverage["evidence_status_summary"].get("unknown", 0), 0)
                self.assertEqual(coverage["evidence_status_summary"].get("partial", 0), 0)

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

    def test_cloud_config_cluster_and_workload_are_applicable(self) -> None:
        report, _, _ = doctor.build_report(
            doctor.parse_args(["--platform", "cloud", "--evidence-file", str(CLOUD_FIXTURE)])
        )
        domains = report["coverage"]["domains"]

        self.assertTrue(domains["Config validation"]["platform_applicable"])
        self.assertTrue(domains["Distributed search and SHC"]["platform_applicable"])
        self.assertTrue(domains["Indexer clustering"]["platform_applicable"])
        self.assertEqual(domains["Workload management"]["coverage"], "direct_fix")

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
            self.assertTrue(applied["selected_fixes"])
            self.assertFalse(any(item["live_mutation_performed"] for item in applied["selected_fixes"]))
            self.assertTrue((Path(tmpdir) / "handoffs" / "SAD-CONNECTIVITY-REST-DENIED.md").exists())
            self.assertTrue((Path(tmpdir) / "handoffs" / "SAD-CLOUD-ACS-ALLOWLIST-GAP.md").exists())

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
            self.assertIn("[REDACTED]", rendered)
            for path in output_dir.rglob("*"):
                if path.is_file():
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_uri_userinfo_and_secret_query_are_never_rendered(self) -> None:
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
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            rendered = result.stdout + "\n" + "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(tmpdir).rglob("*")
                if path.is_file()
            )
            self.assertNotIn("URI_PASSWORD", rendered)
            self.assertNotIn("QUERY_TOKEN_VALUE", rendered)
            self.assertNotIn("admin:", rendered)

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
