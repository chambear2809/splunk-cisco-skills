from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]
REVIEW = ROOT / "docs" / "cisco-package-review-network-dc-2026-11-16.md"


def test_network_data_center_review_records_downloaded_binary_evidence():
    text = REVIEW.read_text(encoding="utf-8")
    for app_id, version, digest in (
        (
            "6872",
            "4.0.0",
            "94722579e0f120e0b5c93c9eac2873fb94f4749134b08652f578bb398803fc52",
        ),
        (
            "7777",
            "2.0.0",
            "297cab257d5b608e2f9aee987eea3f2041b8944c93e2bc5e6a57fd1371fc09a9",
        ),
        (
            "7828",
            "3.2.2",
            "5046084bbe9d0ce76dcdd442e1b231f9f0a86cc5aef5bb3536d0e73b2c333a5f",
        ),
        (
            "2731",
            "5.0.0",
            "dbda2c808b0cd56881e34b43c07ccfb0d6de4ec8623e9ffc6d6356efae181570",
        ),
    ):
        assert f"| {app_id} |" in text
        assert version in text
        assert digest in text


def test_review_records_preserved_pins_and_latest_contract_boundaries():
    text = REVIEW.read_text(encoding="utf-8")
    assert "7538 `4.0.60`" in text
    assert "7539 `4.0.20`" in text
    assert "remain unchanged" in text
    assert "cisco_catalyst_app_index" in text
    assert "summariesonly=false allow_old_summaries=true" in text
    assert "43 modular-input stanzas" in text


def test_dc_classinfo_dry_run_serializes_the_reviewed_input_contract():
    script = ROOT / "skills/cisco-dc-networking-setup/scripts/setup.sh"
    result = subprocess.run(
        [
            "bash",
            str(script),
            "--classinfo-preset",
            "application-atlas",
            "--account",
            "FABRIC_A",
            "--index",
            "cisco_aci",
            "--dry-run",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "apic_account = FABRIC_A" in result.stdout
    assert "apic_input_type = classInfo" in result.stdout
    assert "index = cisco_aci" in result.stdout
    assert "fabricLink lldpAdjEp" in result.stdout


def test_setup_help_exposes_reviewed_pins_and_ucs_dashboard_contract():
    checks = (
        (
            ROOT / "skills/cisco-intersight-setup/scripts/setup.sh",
            "repo-verified 3.1.1",
        ),
        (
            ROOT / "skills/cisco-ucs-ta-setup/scripts/validate.sh",
            "Monitoring Dashboard",
        ),
    )
    for script, expected in checks:
        result = subprocess.run(
            ["bash", str(script), "--help"], cwd=ROOT, text=True, capture_output=True
        )
        assert result.returncode == 0
        assert expected in (result.stdout + result.stderr)


def test_intersight_guards_all_supported_targets_and_direct_account_path():
    setup = (ROOT / "skills/cisco-intersight-setup/scripts/setup.sh").read_text(
        encoding="utf-8"
    )
    account = (
        ROOT / "skills/cisco-intersight-setup/scripts/configure_account.sh"
    ).read_text(encoding="utf-8")
    assert 'VERIFIED_APP_VERSION="3.1.1"' in setup
    assert 'TARGET_SPLUNK_VERSION}" == "10.5" ]] || return 0' not in setup
    assert 'VERIFIED_APP_VERSION="3.1.1"' in account
    assert "rest_get_app_version" in account


def test_enterprise_networking_rejects_unapproved_4x_on_enterprise_10_6():
    result = subprocess.run(
        ["bash", str(ROOT / "skills/cisco-enterprise-networking-setup/scripts/setup.sh"),
         "--macros-only", "--app-version", "4.0.20", "--target-splunk-version", "10.6"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 1
    assert "not the repo-reviewed package contract" in result.stdout
    assert "Refusing configuration before any REST mutation" in result.stdout


def test_ucs_enablement_matches_shipped_disabled_default_and_wrapper_override():
    report = (ROOT / "docs/cisco-package-review-network-dc-2026-11-16.md").read_text(
        encoding="utf-8"
    )
    wrapper = (ROOT / "skills/cisco-ucs-ta-setup/scripts/configure_task.sh").read_text(
        encoding="utf-8"
    )
    assert "disabled (`disabled=1`)" in report
    assert "300-second default" in report
    assert 'disabled "0"' in wrapper
