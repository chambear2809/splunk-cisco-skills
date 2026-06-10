#!/usr/bin/env python3
"""Regression coverage for the Splunk Data Source Readiness Doctor skill."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from agent.splunk_cisco_skills_mcp import core
from tests.regression_helpers import REPO_ROOT


DOCTOR_PATH = REPO_ROOT / "skills/splunk-data-source-readiness-doctor/scripts/doctor.py"
UNREADY_FIXTURE = REPO_ROOT / "skills/splunk-data-source-readiness-doctor/fixtures/comprehensive_unready.json"
READY_FIXTURE = REPO_ROOT / "skills/splunk-data-source-readiness-doctor/fixtures/ready.json"
SOURCE_PACKS_FILE = REPO_ROOT / "skills/splunk-data-source-readiness-doctor/source_packs.json"

spec = importlib.util.spec_from_file_location("splunk_data_source_readiness_doctor", DOCTOR_PATH)
doctor = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(doctor)


STABLE_RULE_IDS = [
    "DSRD-ARI-DATA-SOURCE-INACTIVE",
    "DSRD-ARI-FIELD-MAPPING-GAP",
    "DSRD-ARI-INDEX-GAP",
    "DSRD-ARI-PRIORITY-GAP",
    "DSRD-ARI-RELEVANT-EVENT-FILTER-GAP",
    "DSRD-CIM-DATAMODEL-NO-EVENTS",
    "DSRD-CIM-FIELD-GAP",
    "DSRD-CIM-TAG-EVENTTYPE-GAP",
    "DSRD-CIM-VALIDATION-GAP",
    "DSRD-DASHBOARDS-MACRO-GAP",
    "DSRD-DASHBOARDS-PANEL-ZERO",
    "DSRD-DASHBOARDS-SEARCH-DEFINITION-GAP",
    "DSRD-DM-ACCELERATION-GAP",
    "DSRD-DM-CONSTRAINT-GAP",
    "DSRD-ES-ASSET-IDENTITY-GAP",
    "DSRD-ES-CONTENT-ACTION-GAP",
    "DSRD-ES-CONTENT-UPDATE-GAP",
    "DSRD-ES-DETECTION-GAP",
    "DSRD-ES-PRODUCT-MISSING",
    "DSRD-ES-RISK-MODIFIER-GAP",
    "DSRD-ES-THREAT-INTEL-GAP",
    "DSRD-FEDERATED-DATASET-GAP",
    "DSRD-HANDOFF-COVERAGE-GAP",
    "DSRD-INDEX-SOURCETYPE-GAP",
    "DSRD-INGEST-PIPELINE-FLOW-GAP",
    "DSRD-ITSI-CONTENT-PACK-GAP",
    "DSRD-ITSI-ENTITY-KPI-GAP",
    "DSRD-ITSI-EVENT-ANALYTICS-GAP",
    "DSRD-ITSI-KPI-THRESHOLD-GAP",
    "DSRD-ITSI-SUMMARY-INDEX-GAP",
    "DSRD-KNOWLEDGE-ENRICHMENT-GAP",
    "DSRD-METRICS-READINESS-GAP",
    "DSRD-OCSF-ADDON-GAP",
    "DSRD-OCSF-MAPPING-GAP",
    "DSRD-OCSF-SOURCETYPE-CONFIG-GAP",
    "DSRD-PARSER-QUALITY-GAP",
    "DSRD-REGISTRY-CONTRACT-GAP",
    "DSRD-RETENTION-LOOKBACK-GAP",
    "DSRD-SAMPLE-FRESHNESS-GAP",
    "DSRD-SAMPLE-VOLUME-BASELINE-GAP",
    "DSRD-SCHEDULED-CONTENT-EXECUTION-GAP",
    "DSRD-SEARCH-RBAC-GAP",
]


class SplunkDataSourceReadinessDoctorTests(unittest.TestCase):
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
        source_pack_validation = doctor.validate_source_packs_payload(json.loads(SOURCE_PACKS_FILE.read_text(encoding="utf-8")))
        self.assertTrue(source_pack_validation["ok"], source_pack_validation)
        self.assertGreaterEqual(source_pack_validation["source_pack_count"], 20)

        required = doctor.REQUIRED_RULE_FIELDS
        domains = {entry["domain"] for entry in doctor.COVERAGE_MANIFEST}
        rule_domains = {item["domain"] for item in doctor.RULE_CATALOG}
        self.assertTrue(domains.issubset(rule_domains))
        for item in doctor.RULE_CATALOG:
            with self.subTest(rule=item["id"]):
                self.assertTrue(required.issubset(item))
                self.assertIn(item["fix_kind"], doctor.FIX_KINDS)
                self.assertIn(item["scope"], {"global", "data_source", "both"})
                self.assertTrue(set(item["target_impacts"]).issubset(doctor.ALL_TARGETS))

    def test_unready_fixture_triggers_full_readiness_stack_and_low_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_doctor(
                "--phase",
                "doctor",
                "--evidence-file",
                str(UNREADY_FIXTURE),
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            report = json.loads(result.stdout)
            finding_ids = {item["id"] for item in report["findings"]}

            expected = {
                "DSRD-INDEX-SOURCETYPE-GAP",
                "DSRD-SAMPLE-FRESHNESS-GAP",
                "DSRD-CIM-TAG-EVENTTYPE-GAP",
                "DSRD-CIM-FIELD-GAP",
                "DSRD-DM-ACCELERATION-GAP",
                "DSRD-OCSF-ADDON-GAP",
                "DSRD-OCSF-MAPPING-GAP",
                "DSRD-ES-ASSET-IDENTITY-GAP",
                "DSRD-ES-DETECTION-GAP",
                "DSRD-SCHEDULED-CONTENT-EXECUTION-GAP",
                "DSRD-ITSI-CONTENT-PACK-GAP",
                "DSRD-ITSI-ENTITY-KPI-GAP",
                "DSRD-ARI-INDEX-GAP",
                "DSRD-ARI-DATA-SOURCE-INACTIVE",
                "DSRD-ARI-FIELD-MAPPING-GAP",
                "DSRD-ARI-RELEVANT-EVENT-FILTER-GAP",
                "DSRD-HANDOFF-COVERAGE-GAP",
                "DSRD-REGISTRY-CONTRACT-GAP",
                "DSRD-RETENTION-LOOKBACK-GAP",
                "DSRD-CIM-VALIDATION-GAP",
                "DSRD-DASHBOARDS-SEARCH-DEFINITION-GAP",
                "DSRD-DM-CONSTRAINT-GAP",
                "DSRD-ES-CONTENT-ACTION-GAP",
                "DSRD-ES-CONTENT-UPDATE-GAP",
                "DSRD-ES-RISK-MODIFIER-GAP",
                "DSRD-ES-THREAT-INTEL-GAP",
                "DSRD-FEDERATED-DATASET-GAP",
                "DSRD-INGEST-PIPELINE-FLOW-GAP",
                "DSRD-ITSI-EVENT-ANALYTICS-GAP",
                "DSRD-ITSI-KPI-THRESHOLD-GAP",
                "DSRD-ITSI-SUMMARY-INDEX-GAP",
                "DSRD-KNOWLEDGE-ENRICHMENT-GAP",
                "DSRD-METRICS-READINESS-GAP",
                "DSRD-OCSF-SOURCETYPE-CONFIG-GAP",
                "DSRD-SAMPLE-VOLUME-BASELINE-GAP",
            }
            self.assertTrue(expected.issubset(finding_ids))
            self.assertEqual(report["scores"]["es"]["status"], "blocked")
            self.assertEqual(report["scores"]["itsi"]["status"], "blocked")
            self.assertEqual(report["scores"]["ari"]["status"], "blocked")
            self.assertLess(report["scores"]["es"]["score"], 75)
            self.assertTrue((Path(tmpdir) / "readiness-report.md").exists())
            self.assertTrue((Path(tmpdir) / "collection-searches.spl").exists())
            self.assertTrue((Path(tmpdir) / "collector-manifest.json").exists())
            self.assertTrue((Path(tmpdir) / "source-pack-report.json").exists())
            self.assertTrue((Path(tmpdir) / "registry-projection.json").exists())

    def test_ready_fixture_resolves_registry_and_scores_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_doctor(
                "--phase",
                "doctor",
                "--evidence-file",
                str(READY_FIXTURE),
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["findings"], [])
            for target in ("es", "itsi", "ari"):
                with self.subTest(target=target):
                    self.assertEqual(report["scores"][target]["score"], 100)
                    self.assertEqual(report["scores"][target]["status"], "ready")
            self.assertTrue(report["data_sources"][0]["registry"]["resolved"])
            self.assertEqual(
                report["data_sources"][0]["registry"]["skill"],
                "splunk-asset-risk-intelligence-setup",
            )

    def test_source_pack_defaults_are_applied_without_overriding_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_path = Path(tmpdir) / "evidence.json"
            output_dir = Path(tmpdir) / "out"
            evidence_path.write_text(
                json.dumps(
                    {
                        "platform": "cloud",
                        "data_sources": [
                            {
                                "name": "cloudtrail",
                                "source_pack_id": "aws_cloudtrail",
                                "sample_events": {"count": 1},
                                "cim": {"required_fields": ["custom_user_field"]},
                            }
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
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            report = json.loads(result.stdout)
            source = report["data_sources"][0]
            self.assertEqual(source["source_pack"]["id"], "aws_cloudtrail")
            self.assertIn("expected_sourcetypes", source["source_pack"]["applied_defaults"])
            self.assertNotIn("cim.required_fields", source["source_pack"]["applied_defaults"])
            self.assertFalse(source["registry"]["expected_contract_missing"])
            manifest = json.loads((output_dir / "collector-manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["id"].startswith("pack-aws_cloudtrail") for item in manifest["searches"]))

    def test_source_packs_phase_lists_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_doctor(
                "--phase",
                "source-packs",
                "--source-pack",
                "aws_cloudtrail,windows_security",
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            catalog = json.loads(result.stdout)
            self.assertEqual(catalog["source_pack_count"], 2)
            self.assertEqual({pack["id"] for pack in catalog["packs"]}, {"aws_cloudtrail", "windows_security"})
            self.assertTrue((Path(tmpdir) / "source-pack-catalog.json").exists())

    def test_source_pack_matchers_avoid_generic_json_and_hec_sourcetypes(self) -> None:
        source_packs = json.loads(SOURCE_PACKS_FILE.read_text(encoding="utf-8"))
        catalog = {pack["id"]: pack for pack in source_packs["packs"]}
        packs_by_id = doctor.source_pack_index(source_packs)
        for pack_id, blocked in {
            "kubernetes_audit": "_json",
            "github_audit": "httpevent",
            "sysmon": "XmlWinEventLog",
        }.items():
            with self.subTest(pack=pack_id):
                self.assertNotIn(blocked, catalog[pack_id]["match"].get("sourcetypes", []))
        self.assertIsNone(
            doctor.find_source_pack({"name": "generic json", "sourcetype": "_json"}, packs_by_id, set())
        )
        self.assertEqual(
            doctor.find_source_pack(
                {"name": "k8s", "source": "kubernetes", "sourcetype": "_json"},
                packs_by_id,
                set(),
            )["id"],
            "kubernetes_audit",
        )
        self.assertIsNone(
            doctor.find_source_pack({"name": "generic hec", "sourcetype": "httpevent"}, packs_by_id, set())
        )
        self.assertIsNone(
            doctor.find_source_pack({"name": "generic xml", "sourcetype": "XmlWinEventLog"}, packs_by_id, set())
        )
        self.assertIsNone(
            doctor.find_source_pack(
                {"name": "generic firehose json", "sourcetype": "_json"},
                packs_by_id,
                set(),
            )
        )
        self.assertIsNone(
            doctor.find_source_pack(
                {"name": "generic firehose hec", "sourcetype": "httpevent"},
                packs_by_id,
                set(),
            )
        )
        self.assertEqual(
            doctor.find_source_pack(
                {
                    "name": "firehose raw json",
                    "source": "aws:firehose:raw-json",
                    "sourcetype": "_json",
                },
                packs_by_id,
                set(),
            )["id"],
            "amazon_kinesis_firehose",
        )
        self.assertEqual(
            doctor.find_source_pack(
                {
                    "name": "firehose raw hec",
                    "source": "aws:firehose:raw",
                    "sourcetype": "httpevent",
                },
                packs_by_id,
                set(),
            )["id"],
            "amazon_kinesis_firehose",
        )
        self.assertIsNone(
            doctor.find_source_pack(
                {"name": "generic raw json source only", "source": "aws:firehose:raw-json"},
                packs_by_id,
                set(),
            )
        )
        self.assertEqual(
            doctor.find_source_pack(
                {"name": "github enterprise", "source": "http:github", "sourcetype": "httpevent"},
                packs_by_id,
                set(),
            )["id"],
            "github_audit",
        )
        self.assertEqual(
            doctor.find_source_pack(
                {
                    "name": "sysmon",
                    "source": "XmlWinEventLog:Microsoft-Windows-Sysmon/Operational",
                    "sourcetype": "XmlWinEventLog",
                },
                packs_by_id,
                set(),
            )["id"],
            "sysmon",
        )

    def test_new_source_pack_matching_and_generic_false_positives(self) -> None:
        source_packs = json.loads(SOURCE_PACKS_FILE.read_text(encoding="utf-8"))
        packs_by_id = doctor.source_pack_index(source_packs)
        self.assertIsNone(doctor.find_source_pack({"name": "generic cef", "sourcetype": "cef"}, packs_by_id, set()))
        self.assertIsNone(doctor.find_source_pack({"name": "generic syslog", "sourcetype": "syslog"}, packs_by_id, set()))
        self.assertIsNone(doctor.find_source_pack({"name": "generic access", "sourcetype": "access_combined"}, packs_by_id, set()))
        cases = [
            ({"name": "Salesforce", "sourcetype": "sfdc:loginhistory"}, "salesforce"),
            ({"name": "Box", "sourcetype": "box:events"}, "box"),
            ({"name": "CyberArk EPM", "sourcetype": "cyberark:epm:threat:detection"}, "cyberark_epm"),
            ({"name": "CyberArk Vault", "sourcetype": "cyberark:epv:cef"}, "cyberark_epv_pta"),
            ({"name": "RSA CAS", "sourcetype": "rsa:securid:cas:adminlog:json"}, "rsa_securid_cas"),
            ({"name": "RSA AM", "sourcetype": "rsa:securid:syslog"}, "rsa_securid_am"),
            ({"name": "Apache", "sourcetype": "apache:access:combined"}, "apache_web"),
            ({"name": "Blue Coat", "sourcetype": "bluecoat:proxysg:access:syslog"}, "bluecoat_proxy"),
            ({"name": "Cisco ISE", "sourcetype": "cisco:ise:syslog"}, "cisco_ise"),
            ({"name": "AppDynamics", "sourcetype": "appdynamics_events"}, "appdynamics"),
        ]
        for evidence, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(doctor.find_source_pack(evidence, packs_by_id, set())["id"], expected)

    def test_source_pack_matchers_cover_new_supported_tas(self) -> None:
        source_packs = json.loads(SOURCE_PACKS_FILE.read_text(encoding="utf-8"))
        catalog = {pack["id"]: pack for pack in source_packs["packs"]}
        expectations = {
            "google_workspace": ["gws:reports:admin", "gws:gmail", "gws:alerts", "gws:users:identity"],
            "microsoft_security": ["ms365:defender:incident", "ms:defender:eventhub", "ms:defender:ti:articles"],
            "sysmon": ["XmlWinEventLog", "XmlWinEventLog:WEC-Sysmon"],
            "google_gcp": [
                "google:gcp:pubsub:message",
                "google:gcp:pubsub:audit:admin_activity",
                "google:gcp:pubsub:audit:data_access",
                "google:gcp:pubsub:audit:system_event",
                "google:gcp:pubsub:audit:policy_denied",
            ],
            "github_audit": [
                "github:cloud:audit",
                "github:enterprise:audit",
                "github:cloud:code:scanning:alerts",
                "github:cloud:dependabot:scanning:alerts",
                "github:cloud:secret:scanning:alerts",
            ],
            "salesforce": ["sfdc:object", "sfdc:logfile", "sfdc:loginhistory"],
            "box": ["box:events", "box:users", "box:filecontent:json"],
            "cyberark_epm": ["cyberark:epm:raw:events", "cyberark:epm:threat:detection"],
            "cyberark_epv_pta": ["cyberark:epv:cef", "cyberark:pta:cef"],
            "rsa_securid_cas": ["rsa:securid:cas:adminlog:json", "rsa:securid:cas:riskuser:json"],
            "rsa_securid_am": ["rsa:securid:syslog", "rsa:securid:admin:syslog"],
            "apache_web": ["apache:access:combined", "apache:error"],
            "bluecoat_proxy": ["bluecoat:proxysg:access:syslog", "bluecoat:proxysg:access:kv"],
            "f5_bigip": ["f5:bigip:syslog", "f5:telemetry:json"],
            "cisco_asa": ["cisco:asa"],
            "vmware": ["vmware:events", "vmware:tasks", "vmware:inv:hierarchy", "vmware:perf:host"],
            "amazon_kinesis_firehose": [
                "aws:cloudtrail",
                "aws:cloudwatchlogs:vpcflow",
                "aws:cloudwatch:events",
                "_json",
                "httpevent",
            ],
            "mssql_database": [
                "mssql:errorlog",
                "mssql:agentlog",
                "mssql:audit",
                "mssql:execution:dm_exec_query_stats",
            ],
            "mysql_database": [
                "mysql:errorLog",
                "mysql:generalQueryLog",
                "mysql:slowQueryLog",
                "mysql:audit",
            ],
            "oracle_database": [
                "oracle:audit:unified",
                "oracle:listener:text",
                "oracle:alert:text",
                "oracle:sysPerf",
            ],
            "microsoft_exchange": [
                "MSExchange:2013:MessageTracking",
                "MSExchange:2013:MailboxAudit",
                "MSExchange:2013:RPCClientAccess",
                "MSExchange:Reputation",
            ],
            "microsoft_scom": [
                "microsoft:scom",
                "microsoft:scom:alert",
                "microsoft:scom:events",
                "microsoft:scom:performance",
            ],
            "netapp_ontap": [
                "ontap:perf",
                "ontap:volume",
                "ontap:aggr",
                "ontap:system",
            ],
            "carbon_black": ["bit9:carbonblack:json"],
            "symantec_endpoint_protection": [
                "symantec:ep:syslog",
                "symantec:ep:risk:file",
                "symantec:ep:security:syslog",
            ],
        }
        for pack_id, sourcetypes in expectations.items():
            with self.subTest(pack=pack_id):
                self.assertIn(pack_id, catalog)
                expected = set(catalog[pack_id]["defaults"]["expected_sourcetypes"])
                self.assertTrue(set(sourcetypes).issubset(expected))
        self.assertIn("cisco-asa-ta-setup", catalog["cisco_asa"]["handoffs"])
        self.assertIn(
            "splunk-amazon-kinesis-firehose-setup",
            catalog["amazon_kinesis_firehose"]["handoffs"],
        )
        self.assertIn("splunk-database-ta-setup", catalog["mssql_database"]["handoffs"])
        self.assertIn("splunk-microsoft-exchange-ta-setup", catalog["microsoft_exchange"]["handoffs"])
        self.assertIn("splunk-netapp-ontap-ta-setup", catalog["netapp_ontap"]["handoffs"])
        self.assertIn("splunk-security-appliance-ta-setup", catalog["carbon_black"]["handoffs"])

    def test_source_packs_remain_limited_to_raw_telemetry_sources(self) -> None:
        source_packs = json.loads(SOURCE_PACKS_FILE.read_text(encoding="utf-8"))
        pack_ids = {pack["id"] for pack in source_packs["packs"]}
        self.assertFalse(
            {
                "security_content_update",
                "pci_compliance",
                "infosec",
                "fraud_analytics",
                "cim",
                "lookup_file_editing",
            }
            & pack_ids
        )

    def test_source_pack_docs_are_specific_not_generic_catalog_fallbacks(self) -> None:
        source_packs = json.loads(SOURCE_PACKS_FILE.read_text(encoding="utf-8"))
        for pack in source_packs["packs"]:
            with self.subTest(pack=pack["id"]):
                self.assertFalse(set(pack.get("docs", [])) & doctor.GENERIC_SOURCE_PACK_DOC_URLS)

    def test_source_pack_matchers_defaults_and_profiles_are_consistent(self) -> None:
        source_packs = json.loads(SOURCE_PACKS_FILE.read_text(encoding="utf-8"))
        for pack in source_packs["packs"]:
            with self.subTest(pack=pack["id"]):
                match = pack.get("match", {})
                defaults = pack.get("defaults", {})
                match_sourcetypes = set(match.get("sourcetypes", []))
                pair_sourcetypes = {
                    item["sourcetype"]
                    for item in match.get("source_sourcetype_pairs", [])
                    if isinstance(item, dict) and item.get("sourcetype")
                }
                expected_sourcetypes = set(defaults.get("expected_sourcetypes", []))
                self.assertTrue(match_sourcetypes.issubset(expected_sourcetypes))
                self.assertTrue(pair_sourcetypes.issubset(expected_sourcetypes))
                self.assertTrue(expected_sourcetypes.issubset(match_sourcetypes | pair_sourcetypes))
                ari_profile = defaults.get("ari.processing_profile")
                if ari_profile:
                    self.assertEqual(
                        set(ari_profile.get("processing_types", [])),
                        set(defaults.get("ari.expected_processing_types", [])),
                    )
                if defaults.get("itsi.content_pack_profile"):
                    self.assertTrue(defaults.get("itsi.expected_content_packs"))

    def test_collector_manifest_does_not_request_hec_token_values(self) -> None:
        evidence = {
            "data_sources": [
                {
                    "name": "cloudtrail",
                    "source_pack_id": "aws_cloudtrail",
                    "expected_indexes": ["aws"],
                    "expected_sourcetypes": ["aws:cloudtrail"],
                }
            ]
        }
        manifest = doctor.collector_manifest(evidence)
        hec_specs = [item for item in manifest["searches"] if item["id"] == "global-hec-token-inventory"]
        self.assertEqual(len(hec_specs), 1)
        self.assertNotIn(" token", hec_specs[0]["spl"])
        self.assertIn("useACK", hec_specs[0]["spl"])

    def test_cloud_10_4_data_management_docs_and_collection_handoff_are_current(self) -> None:
        stale_fragments = ("9.2.2406", "9.3.2408", "9.3.2411")
        docs_blob = "\n".join(doctor.SOURCE_DOCS.values())
        reference = (REPO_ROOT / "skills/splunk-data-source-readiness-doctor/reference.md").read_text(
            encoding="utf-8"
        )
        collection_searches = doctor.render_collection_searches(
            {"data_sources": [{"name": "aws_s3_dataset", "expected_indexes": ["main"]}]}
        )

        for fragment in stale_fragments:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, docs_blob)
                self.assertNotIn(fragment, reference)
        self.assertIn("10.4.2604", doctor.SOURCE_DOCS["data_management_s3_dataset"])
        self.assertIn("10.4.2604", doctor.SOURCE_DOCS["data_management_azure_dataset"])
        self.assertIn("Data Management dataset readiness", collection_searches)
        self.assertIn("edit_datasets", collection_searches)
        self.assertIn("does not claim private Data Management API CRUD", collection_searches)

    def test_generic_sourcetype_source_pairs_constrain_generated_base_search(self) -> None:
        registry_index = doctor.build_registry_index({})
        source_packs = json.loads(SOURCE_PACKS_FILE.read_text(encoding="utf-8"))
        args = doctor.parse_args(["--phase", "doctor"])
        evidence = {
            "data_sources": [
                {"name": "k8s", "source": "kubernetes", "sourcetype": "_json"},
                {"name": "github enterprise", "source": "http:github", "sourcetype": "httpevent"},
                {
                    "name": "sysmon",
                    "source": "XmlWinEventLog:Microsoft-Windows-Sysmon/Operational",
                    "sourcetype": "XmlWinEventLog",
                },
            ]
        }
        normalized, _, _ = doctor.normalized_evidence(args, registry_index, source_packs)
        normalized["data_sources"] = doctor.enrich_sources(evidence, registry_index, source_packs, set())
        bases = {source["name"]: doctor.source_base_search(source) for source in normalized["data_sources"]}
        self.assertIn('source="kubernetes"', bases["k8s"])
        self.assertIn('sourcetype IN ("_json", "kube:audit")', bases["k8s"])
        self.assertIn('source IN ("github", "http:github")', bases["github enterprise"])
        self.assertIn("httpevent", bases["github enterprise"])
        self.assertIn('source="XmlWinEventLog:Microsoft-Windows-Sysmon/Operational"', bases["sysmon"])
        self.assertIn("XmlWinEventLog:WEC-Sysmon", bases["sysmon"])

    def test_collect_phase_renders_manifest_without_live_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_doctor(
                "--phase",
                "collect",
                "--evidence-file",
                str(READY_FIXTURE),
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["live_executed"])
            self.assertTrue(payload["ok"])
            self.assertTrue((Path(tmpdir) / "collector-manifest.json").exists())
            self.assertTrue((Path(tmpdir) / "source-pack-report.json").exists())
            self.assertTrue((Path(tmpdir) / "live-collector-results.redacted.json").exists())
            self.assertTrue((Path(tmpdir) / "evidence" / "live-evidence.synthesized.json").exists())

    def test_synthesize_phase_turns_collector_rows_into_readiness_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            evidence_path = tmp_path / "evidence.json"
            collector_path = tmp_path / "live-results.json"
            output_dir = tmp_path / "out"
            evidence_path.write_text(
                json.dumps(
                    {
                        "platform": "cloud",
                        "data_sources": [
                            {
                                "name": "cloudtrail",
                                "source_pack_id": "aws_cloudtrail",
                                "expected_indexes": ["aws"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            collector_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-17T00:00:00+00:00",
                        "live_executed": True,
                        "ok": True,
                        "results": [
                            {
                                "ok": True,
                                "id": "source-cloudtrail-sample-freshness",
                                "data_source": "cloudtrail",
                                "rows": [
                                    {
                                        "count": "5",
                                        "latest": str(int(time.time())),
                                        "index": "aws",
                                        "sourcetype": "aws:cloudtrail",
                                    }
                                ],
                            },
                            {
                                "ok": True,
                                "id": "source-cloudtrail-fieldsummary",
                                "data_source": "cloudtrail",
                                "rows": [{"field": "user"}, {"field": "eventName"}],
                            },
                            {
                                "ok": True,
                                "id": "global-dashboard-inventory",
                                "data_source": "global",
                                "rows": [
                                    {
                                        "title": "AWS dashboard",
                                        "eai:acl.app": "search",
                                        "eai:data": json.dumps(
                                            {
                                                "dataSources": {
                                                    "ds1": {
                                                        "type": "ds.search",
                                                        "options": {
                                                            "query": "index=aws sourcetype=aws:cloudtrail `cloudtrail`"
                                                        },
                                                    }
                                                }
                                            }
                                        ),
                                    }
                                ],
                            },
                            {
                                "ok": True,
                                "id": "global-macro-inventory",
                                "data_source": "global",
                                "rows": [{"title": "cloudtrail", "definition": "index=aws sourcetype=aws:cloudtrail"}],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_doctor(
                "--phase",
                "synthesize",
                "--evidence-file",
                str(evidence_path),
                "--collector-results-file",
                str(collector_path),
                "--output-dir",
                str(output_dir),
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["synthesis"]["source_count"], 1)
            self.assertEqual(payload["synthesis"]["dashboard_count"], 1)
            self.assertEqual(payload["dashboard_dependency_graph"]["missing_macros"], [])
            finding_ids = {item["id"] for item in payload["report"]["findings"]}
            self.assertIn("DSRD-CIM-FIELD-GAP", finding_ids)

            synthesized = json.loads((output_dir / "evidence" / "live-evidence.synthesized.json").read_text(encoding="utf-8"))
            source = synthesized["data_sources"][0]
            self.assertEqual(source["sample_events"]["count"], 5)
            self.assertEqual(source["indexes"]["missing"], [])
            self.assertEqual(source["sourcetypes"]["missing"], [])
            self.assertIn("aws_account_id", source["cim"]["missing_required_fields"])
            self.assertTrue((output_dir / "dashboard-dependency-graph.json").exists())
            self.assertTrue((output_dir / "synthesis-report.json").exists())

    def test_apply_selected_fix_renders_packets_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_doctor(
                "--phase",
                "apply",
                "--evidence-file",
                str(UNREADY_FIXTURE),
                "--output-dir",
                tmpdir,
                "--fixes",
                "DSRD-CIM-TAG-EVENTTYPE-GAP,DSRD-HANDOFF-COVERAGE-GAP",
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            applied = json.loads(result.stdout)
            self.assertTrue(applied["selected_fixes"])
            self.assertFalse(any(item["live_mutation_performed"] for item in applied["selected_fixes"]))
            self.assertTrue(list((Path(tmpdir) / "handoffs").glob("DSRD-CIM-TAG-EVENTTYPE-GAP-*.md")))
            self.assertTrue(list((Path(tmpdir) / "support-tickets").glob("DSRD-HANDOFF-COVERAGE-GAP-*.md")))

    def test_secret_redaction_keeps_token_values_out_of_rendered_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_path = Path(tmpdir) / "evidence.json"
            output_dir = Path(tmpdir) / "out"
            evidence_path.write_text(
                json.dumps(
                    {
                        "platform": "cloud",
                        "data_sources": [
                            {
                                "name": "secret source",
                                "expected_indexes": ["main"],
                                "sample_events": {"count": 1},
                                "api_token": "SUPER_SECRET_TOKEN_VALUE",
                            }
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
            self.assertIn("[REDACTED]", rendered)

    def test_no_direct_fix_contains_disruptive_apply_action(self) -> None:
        for item in doctor.RULE_CATALOG:
            if item["fix_kind"] == "direct_fix":
                with self.subTest(rule=item["id"]):
                    self.assertIsNone(doctor.DIRECT_DANGEROUS_RE.search(item["apply_command"]))

    def test_mcp_classifies_doctor_phases_and_apply_safely(self) -> None:
        read_only_cases = [
            ["--phase", "doctor"],
            ["--phase", "fix-plan", "--evidence-file", str(UNREADY_FIXTURE)],
            ["--phase", "validate"],
            ["--phase", "status"],
            ["--phase", "source-packs"],
            ["--phase", "collect"],
            ["--phase", "synthesize"],
            ["--phase", "apply", "--fixes", "DSRD-CIM-TAG-EVENTTYPE-GAP", "--dry-run"],
        ]
        for args in read_only_cases:
            with self.subTest(args=args):
                plan = core.plan_skill_script("splunk-data-source-readiness-doctor", "setup.sh", args)
                self.assertTrue(plan["read_only"])
                direct_plan = core.plan_skill_script("splunk-data-source-readiness-doctor", "doctor.py", args)
                self.assertTrue(direct_plan["read_only"])

        mutating_plan = core.plan_skill_script(
            "splunk-data-source-readiness-doctor",
            "setup.sh",
            ["--phase", "apply", "--fixes", "DSRD-CIM-TAG-EVENTTYPE-GAP"],
        )
        self.assertFalse(mutating_plan["read_only"])
        direct_mutating_plan = core.plan_skill_script(
            "splunk-data-source-readiness-doctor",
            "doctor.py",
            ["--phase", "apply", "--fixes", "DSRD-CIM-TAG-EVENTTYPE-GAP"],
        )
        self.assertFalse(direct_mutating_plan["read_only"])

        with self.assertRaisesRegex(core.SkillMCPError, "Direct secret flag"):
            core.plan_skill_script("splunk-data-source-readiness-doctor", "setup.sh", ["--password", "secret"])
        with self.assertRaisesRegex(core.SkillMCPError, "Direct secret flag"):
            core.plan_skill_script("splunk-data-source-readiness-doctor", "setup.sh", ["--session-key", "secret"])


if __name__ == "__main__":
    unittest.main()
