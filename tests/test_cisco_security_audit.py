#!/usr/bin/env python3
"""Regression checks for the security/access package review boundary."""

import hashlib
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/cisco-package-review-security-2026-11-16.md"


class CiscoSecurityAuditTests(unittest.TestCase):
    def test_inventory_report_and_inspected_archive_exist(self) -> None:
        self.assertTrue(REPORT.is_file())
        self.assertGreaterEqual(
            REPORT.read_text(encoding="utf-8").count(
                "https://splunkbase.splunk.com/app/"
            ),
            18,
        )
        archive = ROOT / "splunk-ta/cisco-security-cloud_413.tar.gz"
        if not archive.is_file():
            self.skipTest("ignored package cache is not present in this checkout")
        self.assertEqual(
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            "54345d6220e288942ec245a0cfa2f1f9433b4b9f9e82c1426f9c4689505104a6",
        )

    def test_security_cloud_skill_keeps_ftd_boundary(self) -> None:
        text = (ROOT / "skills/cisco-security-cloud-setup/reference.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("4.1.3", text)
        self.assertIn("granular", text)
        self.assertIn("cisco:ftd:syslog", text)

    def test_security_cloud_setup_blocks_unreviewed_contract_without_rest_mutation(
        self,
    ) -> None:
        script = ROOT / "skills/cisco-security-cloud-setup/scripts/setup.sh"
        rejected = subprocess.run(
            [
                "bash",
                str(script),
                "--contract-check",
                "--target-splunk-version",
                "10.6",
                "--app-version",
                "4.1.3",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(
            "Refusing configuration before any REST mutation",
            rejected.stdout + rejected.stderr,
        )
        accepted = subprocess.run(
            [
                "bash",
                str(script),
                "--contract-check",
                "--target-splunk-version",
                "10.6",
                "--app-version",
                "3.6.10",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)

    def test_direct_input_entrypoint_checks_contract_before_index_or_input_mutation(
        self,
    ) -> None:
        text = (
            ROOT / "skills/cisco-security-cloud-setup/scripts/configure_input.sh"
        ).read_text(encoding="utf-8")
        version_check = text.index('installed_app_version="$(rest_get_app_version')
        index_mutation = text.index("platform_create_index")
        input_mutation = text.index("rest_create_or_update_account")
        self.assertLess(version_check, index_mutation)
        self.assertLess(version_check, input_mutation)
        self.assertIn("refusing configuration before REST mutation", text)


if __name__ == "__main__":
    unittest.main()


def test_direct_configuration_rejects_4x_before_any_write(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    products = ROOT / "skills/cisco-security-cloud-setup/products.json"
    (tmp_path / "products.json").write_bytes(products.read_bytes())
    helper = scripts / "helpers.sh"
    marker = tmp_path / "mutation"
    helper.write_text(r"""
log() { echo "$*"; }
require_arg() { [ "$2" -ge 2 ]; }
load_splunk_credentials() { SPLUNK_URI=https://example.invalid; }
get_session_key() { echo mock; }
rest_check_app() { return 0; }
rest_get_app_version() { echo 4.1.3; }
platform_create_index() { touch "$MUTATION_MARKER"; }
rest_create_or_update_account() { touch "$MUTATION_MARKER"; }
""")
    source = (
        ROOT / "skills/cisco-security-cloud-setup/scripts/configure_input.sh"
    ).read_text()
    source = source.replace(
        'source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"',
        'source "${SCRIPT_DIR}/helpers.sh"',
    )
    script = scripts / "configure_input.sh"
    script.write_text(source)
    env = {**os.environ, "MUTATION_MARKER": str(marker)}
    env.pop("SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM", None)
    result = subprocess.run(
        [
            "bash",
            str(script),
            "--input-type",
            "sbg_nvm_input",
            "--name",
            "test",
            "--set",
            "index",
            "cisco_nvm",
            "--disable",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "refusing configuration before REST mutation" in result.stdout
    assert not marker.exists()
