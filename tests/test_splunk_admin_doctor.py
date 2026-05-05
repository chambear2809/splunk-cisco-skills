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


STABLE_RULE_IDS = [
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
        self.assertEqual([item["id"] for item in doctor.RULE_CATALOG], STABLE_RULE_IDS)

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
            self.assertEqual(coverage["domains"]["Cloud Monitoring Console"]["coverage"], "manual_support")

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
            self.assertIn("[REDACTED]", rendered)

    def test_no_direct_fix_contains_disruptive_apply_action(self) -> None:
        for item in doctor.RULE_CATALOG:
            if item["fix_kind"] == "direct_fix":
                with self.subTest(rule=item["id"]):
                    self.assertIsNone(doctor.DIRECT_DANGEROUS_RE.search(item["apply_command"]))

    def test_mcp_classifies_doctor_phases_and_apply_safely(self) -> None:
        read_only_cases = [
            ["--phase", "doctor"],
            ["--phase", "fix-plan", "--evidence-file", str(CLOUD_FIXTURE)],
            ["--phase", "validate"],
            ["--phase", "status"],
            ["--phase", "apply", "--fixes", "SAD-CONNECTIVITY-REST-DENIED", "--dry-run"],
        ]
        for args in read_only_cases:
            with self.subTest(args=args):
                plan = core.plan_skill_script("splunk-admin-doctor", "setup.sh", args)
                self.assertTrue(plan["read_only"])
                direct_plan = core.plan_skill_script("splunk-admin-doctor", "doctor.py", args)
                self.assertTrue(direct_plan["read_only"])

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
        live_read_only_plan = core.plan_skill_script(
            "splunk-admin-doctor",
            "live_validate_all.py",
            ["--profile", "onprem_2535", "--once"],
        )
        self.assertTrue(live_read_only_plan["read_only"])
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
