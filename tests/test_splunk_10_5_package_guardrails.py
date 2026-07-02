"""Focused regressions for Splunk 10.5 package classification guardrails."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_unsupported_registry_entries_explain_their_product_boundary() -> None:
    registry = json.loads(
        (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
    )
    apps = {str(app.get("splunkbase_id")): app for app in registry["apps"]}

    for app_id in ("4147", "7404", "7539", "7828"):
        assert apps[app_id]["compatibility_status"] == "unsupported"
        assert "10.5" in apps[app_id]["notes"]

    assert apps["5863"]["compatibility_classification"] == "not_applicable"
    assert apps["5863"]["target_product"] == "Splunk SOAR"
    assert "SOAR-only" in apps["5863"]["notes"]


def test_legacy_ai_and_synthetic_packages_are_not_new_10_5_installs() -> None:
    ai_text = (
        REPO_ROOT / "skills/splunk-ai-ml-toolkit-setup/SKILL.md"
    ).read_text(encoding="utf-8")
    for app_id in ("2884", "6415", "6843"):
        assert app_id in ai_text
    assert "never install" in ai_text
    assert "Splunk 10.5" in ai_text

    synthetic_text = (
        REPO_ROOT / "skills/splunk-observability-cloud-integration-setup/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "Splunkbase `5608`" in synthetic_text
    assert "Do not install" in synthetic_text
    assert "native Splunk" in synthetic_text


def test_tomcat_package_gap_uses_the_shared_fail_closed_installer() -> None:
    text = (
        REPO_ROOT / "skills/splunk-syslog-web-proxy-ta-setup/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "app `2911`" in text
    assert "refuses" in text
    assert "--accept-unsupported-platform" in text


def test_verified_and_public_release_drift_is_explicit_in_owning_skills() -> None:
    expected = {
        "cisco-secure-email-web-gateway-setup": ("1.7.0", "1.7.1"),
        "splunk-itsi-setup": ("4.21.2", "5.0.0"),
        "splunk-servicenow-ta-setup": ("10.0.1", "11.0.0"),
        "splunk-observability-gcp-integration": ("5.0.2", "5.0.3"),
        "splunk-security-content-update-setup": ("6.0.0", "6.1.0"),
        "splunk-salesforce-ta-setup": ("6.0.2", "6.0.3"),
        "splunk-infosec-app-setup": ("1.7.1", "1.7.2"),
        "splunk-github-ta-setup": ("3.3.0", "3.3.1"),
        "splunk-okta-ta-setup": ("5.0.2", "5.0.3"),
        "splunk-ai-assistant-setup": ("2.0.0", "2.1.1"),
        "cisco-catalyst-ta-setup": ("3.1.0", "3.2.35"),
        "cisco-talos-intelligence-setup": ("1.0.1", "1.0.3"),
        "cisco-scan-setup": ("1.0.27", "1.0.29"),
    }

    for skill, (verified, public) in expected.items():
        text = (REPO_ROOT / "skills" / skill / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert verified in text, skill
        assert public in text, skill
        assert "--accept-unverified-release" in text, skill


def test_pki_uses_native_expiry_monitoring_and_correct_legacy_app_identity() -> None:
    reference = (
        REPO_ROOT
        / "skills/splunk-platform-pki-setup/references/post-install-monitoring.md"
    ).read_text(encoding="utf-8")
    assert "`ssl_certificate_checker`" in reference
    assert "--app-id 3172" in reference
    assert "--app splunk_ssl_certificate_checker" not in reference
    assert "Do not install\nit on Splunk 10.5" in reference
    assert "expire-watch.sh" in reference
