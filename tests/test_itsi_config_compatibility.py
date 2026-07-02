from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "skills" / "splunk-itsi-config" / "scripts" / "itsi_compatibility_report.py"


def load_report_module():
    spec = importlib.util.spec_from_file_location("itsi_compatibility_report", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ItsiCompatibilityReportTests(unittest.TestCase):
    def test_status_taxonomy_is_complete_and_every_row_is_well_formed(self) -> None:
        module = load_report_module()
        expected_statuses = {
            "typed-tested",
            "guarded-operational",
            "passthrough-experimental",
            "read-only/handoff",
            "excluded/version-gated",
        }
        source_ids = {source["id"] for source in module.SOURCES}
        row_ids: set[str] = set()

        self.assertEqual(expected_statuses, set(module.STATUS_TAXONOMY))
        self.assertEqual(expected_statuses, {row["status"] for row in module.COMPATIBILITY_ROWS})
        self.assertEqual(len(source_ids), len(module.SOURCES))

        for row in module.COMPATIBILITY_ROWS:
            with self.subTest(row=row["id"]):
                self.assertEqual(
                    {"id", "area", "status", "versions", "coverage", "notes", "source_ids"},
                    set(row),
                )
                self.assertNotIn(row["id"], row_ids)
                row_ids.add(row["id"])
                self.assertIn(row["status"], expected_statuses)
                self.assertTrue(row["versions"])
                self.assertTrue(row["coverage"].strip())
                self.assertTrue(row["notes"].strip())
                self.assertTrue(row["source_ids"])
                self.assertLessEqual(set(row["source_ids"]), source_ids)

    def test_sources_include_current_5_0_contract_release_notes_and_4_21_baseline(self) -> None:
        module = load_report_module()
        sources = {source["id"]: source for source in module.SOURCES}

        required = {
            "itsi-5.0-rest-reference",
            "itsi-5.0-rest-schema",
            "itsi-5.0-new-features",
            "itsi-5.0-known-issues",
            "itsi-5.0-removed-features",
            "itsi-4.21-rest-reference",
            "itsi-4.21-rest-schema",
        }
        self.assertLessEqual(required, set(sources))
        self.assertIn("/5.0/", module.REST_REFERENCE_URL)
        self.assertIn("/5.0/", module.REST_SCHEMA_URL)
        self.assertIn("/4.21/", module.BASELINE_REST_REFERENCE_URL)
        self.assertIn("/4.21/", module.BASELINE_REST_SCHEMA_URL)
        for source in module.SOURCES:
            self.assertTrue(source["url"].startswith("https://help.splunk.com/"))

    def test_event_iq_inventory_distinguishes_rules_from_operational_records(self) -> None:
        module = load_report_module()
        rows = {row["id"]: row for row in module.COMPATIBILITY_ROWS}
        rules = rows["event-iq-summarization-rules"]
        records = rows["event-iq-summary-records"]

        self.assertEqual("passthrough-experimental", rules["status"])
        self.assertIn("summarization_rule", rules["coverage"] + rules["notes"])
        self.assertIn("dedicated summarization_rules section", rules["coverage"])
        self.assertIn("ITSI 5.0-only payload passthrough", rules["notes"])
        self.assertIn("not a typed", rules["notes"])
        self.assertEqual("read-only/handoff", records["status"])
        self.assertIn("summarization_feedback", records["coverage"] + records["notes"])
        self.assertIn("non-idempotent operational records", records["notes"])
        self.assertIn("Declarative apply is blocked", records["notes"])

    def test_report_covers_5_0_features_and_honest_handoffs(self) -> None:
        module = load_report_module()
        rows = {row["id"]: row for row in module.COMPATIBILITY_ROWS}

        self.assertEqual("excluded/version-gated", rows["itsi-5.0-structured-tags"]["status"])
        self.assertIn("itsi_tags", rows["itsi-5.0-structured-tags"]["notes"])
        self.assertEqual("excluded/version-gated", rows["itsi-5.0-rbac-sharing"]["status"])
        self.assertIn("shared teams", rows["itsi-5.0-rbac-sharing"]["notes"])
        self.assertEqual("excluded/version-gated", rows["itsi-5.0-advanced-maintenance"]["status"])
        self.assertIn("external CIs", rows["itsi-5.0-advanced-maintenance"]["notes"])
        self.assertEqual("passthrough-experimental", rows["itsi-5.0-neap-priority"]["status"])
        self.assertIn("0 through 999", rows["itsi-5.0-neap-priority"]["notes"])
        self.assertEqual("read-only/handoff", rows["event-iq-detect-and-enrichment"]["status"])
        self.assertIn("enrichment policies", rows["event-iq-detect-and-enrichment"]["notes"])

    def test_deprecation_content_pack_and_predictive_caveats_are_explicit(self) -> None:
        module = load_report_module()
        rows = {row["id"]: row for row in module.COMPATIBILITY_ROWS}

        anomaly = rows["metric-anomaly-detection"]
        self.assertEqual("excluded/version-gated", anomaly["status"])
        self.assertIn("Deprecated since ITSI 4.20", anomaly["versions"])
        self.assertIn("Do not create", anomaly["notes"])

        content_pack = rows["content-pack-lifecycle"]
        self.assertEqual(["ITSI 4.20.x", "ITSI 4.21.x"], content_pack["versions"])
        self.assertIn("not 5.0", content_pack["notes"])
        self.assertIn("outside this configuration skill", content_pack["notes"])

        predictive = rows["predictive-analytics"]
        self.assertEqual("read-only/handoff", predictive["status"])
        self.assertIn("UI handoff", predictive["notes"])
        self.assertIn("must not claim", predictive["notes"])

    def test_rendering_is_deterministic_offline_and_machine_readable(self) -> None:
        module = load_report_module()
        first = module.render_json()
        second = module.render_json()
        payload = json.loads(first)
        markdown = module.render_markdown()

        self.assertEqual(first, second)
        self.assertEqual(module.report_payload(), payload)
        self.assertFalse(payload["metadata"]["report_generation_requires_network"])
        self.assertFalse(payload["metadata"]["report_generation_requires_live_itsi"])
        self.assertTrue(payload["metadata"]["live_preflight_and_validation_required_before_completion"])
        self.assertIn("ITSI 5.0 REST API reference", markdown)
        self.assertIn("ITSI 4.21 REST API reference baseline", markdown)
        self.assertIn("typed-tested", markdown)
        self.assertIn("read-only/handoff", markdown)
        self.assertNotIn("| supported |", markdown)


if __name__ == "__main__":
    unittest.main()
