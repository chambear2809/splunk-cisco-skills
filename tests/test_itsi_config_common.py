from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "splunk-itsi-config" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.common import infer_platform, semver_key, write_yaml  # noqa: E402


class SemverKeyTests(unittest.TestCase):
    def test_ga_release_outranks_pre_release_with_same_main_components(self) -> None:
        self.assertGreater(semver_key("1.0.0"), semver_key("1.0.0-rc1"))
        self.assertGreater(semver_key("2.5.0"), semver_key("2.5.0-beta"))
        self.assertGreater(semver_key("1.0.0"), semver_key("1.0.0-0"))

    def test_main_components_compare_numerically_not_lexically(self) -> None:
        self.assertGreater(semver_key("1.10.0"), semver_key("1.2.0"))
        self.assertGreater(semver_key("0.10.0"), semver_key("0.9.5"))

    def test_pre_release_identifiers_compare_alphanumerically(self) -> None:
        self.assertLess(semver_key("1.0.0-alpha"), semver_key("1.0.0-beta"))
        self.assertLess(semver_key("1.0.0-beta"), semver_key("1.0.0-rc"))

    def test_numeric_pre_release_id_ranks_below_alphanumeric_id(self) -> None:
        self.assertLess(semver_key("1.0.0-1"), semver_key("1.0.0-alpha"))

    def test_build_metadata_does_not_affect_ordering(self) -> None:
        self.assertEqual(semver_key("1.0.0"), semver_key("1.0.0+build1"))
        self.assertEqual(semver_key("1.0.0+abc"), semver_key("1.0.0+xyz"))

    def test_resolve_catalog_entry_picks_ga_over_rc_when_sorting_reverse(self) -> None:
        # Mirrors how resolve_catalog_entry chooses the "newest" version:
        # sorted(reverse=True)[0] must be the GA, never a pre-release.
        versions = ["1.0.0-rc1", "1.0.0-rc2", "1.0.0", "0.9.5"]
        newest = sorted(versions, key=semver_key, reverse=True)[0]
        self.assertEqual(newest, "1.0.0")


class InferPlatformTests(unittest.TestCase):
    def test_recognizes_splunkcloud_dot_com_hostnames(self) -> None:
        spec = {"connection": {"platform": "auto", "base_url": "https://example.splunkcloud.com:8089"}}
        self.assertEqual(infer_platform(spec), "cloud")

    def test_recognizes_cloud_dot_splunk_dot_com_hostnames(self) -> None:
        spec = {"connection": {"platform": "auto", "base_url": "https://example.cloud.splunk.com:8089"}}
        self.assertEqual(infer_platform(spec), "cloud")

    def test_falls_back_to_enterprise_for_unknown_hostnames(self) -> None:
        spec = {"connection": {"platform": "auto", "base_url": "https://splunk.internal:8089"}}
        self.assertEqual(infer_platform(spec), "enterprise")

    def test_explicit_platform_overrides_hostname_inference(self) -> None:
        spec = {"connection": {"platform": "enterprise", "base_url": "https://example.splunkcloud.com:8089"}}
        self.assertEqual(infer_platform(spec), "enterprise")


class ItsiCommonTests(unittest.TestCase):
    def test_write_yaml_quotes_reserved_scalars_and_mapping_keys_for_roundtrip(self) -> None:
        payload = {
            "correlation_searches": [
                {
                    "title": "Dispatch Window",
                    "payload": {
                        "dispatch.latest_time": "@m",
                        "eai:acl": {"app": "SA-ITOA"},
                        "date_key": "2024-01-01",
                        "numeric_string": "123",
                        "float_string": "1.5",
                        "zero_string": "0",
                        "ip_string": "192.0.2.10",
                        "time_string": "12:34",
                        "2024-01-01": "date-shaped key",
                    },
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tempdir:
            spec_path = Path(tempdir) / "exported.native.yaml"
            json_path = Path(tempdir) / "exported.native.json"
            write_yaml(spec_path, payload)

            completed = subprocess.run(
                [
                    "ruby",
                    str(SCRIPTS_DIR / "spec_to_json.rb"),
                    "--spec",
                    str(spec_path),
                    "--output",
                    str(json_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            parsed = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual(parsed, payload)


if __name__ == "__main__":
    unittest.main()
