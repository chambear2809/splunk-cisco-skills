#!/usr/bin/env python3
"""Validate sanitized live SOK evidence and its matrix registry entry."""

from __future__ import annotations

import json
import re
import unittest
from typing import Any

from tests.regression_helpers import REPO_ROOT


SKILL = "splunk-enterprise-kubernetes-setup"
EVIDENCE_RELATIVE = (
    "skills/shared/references/"
    "splunk_enterprise_kubernetes_validation_evidence.json"
)
EVIDENCE_PATH = REPO_ROOT / EVIDENCE_RELATIVE
REGISTRY_PATH = REPO_ROOT / "skills/shared/skill_validation_registry.json"


def nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        result = {str(key).lower() for key in value}
        for child in value.values():
            result.update(nested_keys(child))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for child in value:
            result.update(nested_keys(child))
        return result
    return set()


class SplunkEnterpriseKubernetesValidationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.evidence_run = cls.payload["runs"][0]

    def test_release_and_environment_contract(self) -> None:
        self.assertEqual(self.payload["schema_version"], 1)
        self.assertEqual(self.payload["skill"], SKILL)
        self.assertEqual(len(self.payload["runs"]), 1)
        self.assertEqual(self.evidence_run["date"], "2026-07-08")
        self.assertEqual(self.evidence_run["result"], "partial")
        self.assertEqual(self.evidence_run["environment"]["kubernetes"], "1.34.8")
        self.assertEqual(self.evidence_run["environment"]["helm_major"], 4)
        contract = self.evidence_run["evidence"]["release_contract"]
        self.assertEqual(contract["splunk_operator_for_kubernetes"], "3.1.0")
        self.assertEqual(contract["splunk_enterprise"], "10.4.1")
        self.assertEqual(
            contract["operator_chart_sha256"],
            "c71c1a7fe495c1122c1b0b1b689a366f759107950130c6fcf1f0c453e5d57efd",
        )
        self.assertEqual(
            contract["enterprise_chart_sha256"],
            "0d46b934f78a270b2c9bbacb9f442855f125069800d0a1373eb5f21c54e7fc71",
        )
        self.assertEqual(
            contract["crds_sha256"],
            "d974a6f2c768ad60d8eb56b2dc571354b4dfe48873cbff4e478ca6aa3e2fb3fe",
        )
        self.assertEqual(
            contract["operator_image_digest"],
            "sha256:40faf52d127166a4cccb9284897bdb7d09f7d1e2860dbd554433ddcb3b983968",
        )
        self.assertEqual(
            contract["enterprise_image_digest"],
            "sha256:af4f671c9c931bfd80954e7f1baaff8540d1378ae26b098666cf05256bb24311",
        )

    def test_lifecycle_and_application_evidence(self) -> None:
        lifecycle = self.evidence_run["evidence"]["cluster_lifecycle"]
        for key, value in lifecycle.items():
            if isinstance(value, bool):
                with self.subTest(lifecycle=key):
                    self.assertTrue(value)
        self.assertEqual(lifecycle["verified_crd_count"], 11)
        self.assertEqual(lifecycle["bound_persistent_volume_claim_count"], 3)
        self.assertEqual(lifecycle["encrypted_persistent_volume_count"], 3)

        application = self.evidence_run["evidence"]["application_e2e"]
        for key, value in application.items():
            if isinstance(value, bool):
                with self.subTest(application=key):
                    self.assertTrue(value)
        self.assertEqual(application["search_result_count"], 1)
        self.assertEqual(application["canary_before_pod_recreation_count"], 1)
        self.assertEqual(application["canary_after_pod_recreation_count"], 1)

    def test_cleanup_is_zero_residue(self) -> None:
        cleanup = self.evidence_run["cleanup"]
        remaining = {
            key: value for key, value in cleanup.items() if key.endswith("_remaining")
        }
        self.assertGreaterEqual(len(remaining), 20)
        self.assertTrue(all(value == 0 for value in remaining.values()))
        self.assertIs(cleanup["baseline_restored"], True)

    def test_registry_matches_evidence(self) -> None:
        entry = self.registry["evidence"][SKILL]["live_apply_e2e"]
        self.assertEqual(entry["status"], "partial")
        self.assertEqual(entry["last_verified"], self.evidence_run["date"])
        self.assertEqual(entry["evidence"], [EVIDENCE_RELATIVE])
        self.assertIn("SOK 3.1.0", entry["notes"])
        self.assertIn("zero-residue cleanup", entry["notes"])
        self.assertGreaterEqual(len(self.evidence_run["limitations"]), 2)
        self.assertTrue(
            any(
                "not a full production-profile" in item
                for item in self.evidence_run["limitations"]
            )
        )

    def test_evidence_contains_no_environment_identifiers_or_secrets(self) -> None:
        forbidden_keys = {
            "account_id",
            "arn",
            "cluster_name",
            "context",
            "api_server",
            "region",
            "namespace_name",
            "release_name",
            "node_group",
            "node_name",
            "instance_id",
            "volume_id",
            "volume_handle",
            "pv_name",
            "pvc_name",
            "uid",
            "secret_name",
            "token",
            "credential_path",
            "license_path",
            "query_text",
            "raw_logs",
            "rest_payload",
            "local_path",
        }
        self.assertFalse(nested_keys(self.payload) & forbidden_keys)
        serialized = json.dumps(self.payload, sort_keys=True)
        forbidden_patterns = (
            r"arn:aws",
            r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
            r"(?<![0-9a-f])\d{12}(?![0-9a-f])",
            r"https://[^\s\"]+\.eks\.amazonaws\.com",
            r"\b(?:i|vol|eni|subnet|sg|vpc|lt)-[0-9a-f]{8,17}\b",
            r"\b(?:af|ap|ca|eu|il|me|mx|sa|us)-(?:gov-)?[a-z]+-\d\b",
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
            r"/(?:Users|home|tmp)/",
        )
        for pattern in forbidden_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, serialized, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
