"""Focused regressions for Splunk 10.5 package classification guardrails."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_release_specific_registry_entries_explain_their_product_boundary() -> None:
    registry = json.loads(
        (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
    )
    apps = {str(app.get("splunkbase_id")): app for app in registry["apps"]}

    for app_id in ("7404", "7539", "7828"):
        assert apps[app_id]["compatibility_status"] == "unsupported"
        assert "10.5" in apps[app_id]["verified_platform_versions"]
        assert apps[app_id]["latest_verified_version"] in apps[app_id]["notes"]
        assert apps[app_id]["latest_release_version"] in apps[app_id]["notes"]
        assert "10.5" in apps[app_id]["notes"]

    assert apps["4147"]["compatibility_status"] == "unsupported"
    assert "10.5" not in apps["4147"].get("verified_platform_versions", [])
    assert "10.5" in apps["4147"]["notes"]

    assert apps["5863"]["compatibility_classification"] == "not_applicable"
    assert apps["5863"]["target_product"] == "Splunk SOAR"
    assert "SOAR-only" in apps["5863"]["notes"]


def test_release_specific_skill_docs_match_the_fail_closed_contract() -> None:
    version_pairs = {
        "cisco-enterprise-networking-setup": ("3.1.0", "3.2.0"),
        "cisco-security-cloud-setup": ("3.6.6", "3.6.7"),
        "cisco-intersight-setup": ("3.1.1", "3.2.0"),
    }
    for skill, (verified, public) in version_pairs.items():
        text = (REPO_ROOT / "skills" / skill / "reference.md").read_text(
            encoding="utf-8"
        )
        normalized = " ".join(text.split())
        assert verified in normalized, skill
        assert public in normalized, skill
        assert "--accept-unsupported-platform" in normalized, skill
        assert "vendor approval" in normalized, skill

    uba = (REPO_ROOT / "skills/splunk-uba-setup/SKILL.md").read_text(
        encoding="utf-8"
    )
    normalized_uba = " ".join(uba.split())
    assert "refuses" in normalized_uba
    assert "before mutation" in normalized_uba
    assert "--accept-unsupported-platform" in normalized_uba
    assert "vendor approval" in normalized_uba


WRAPPER_CASES = (
    (
        "skills/cisco-enterprise-networking-setup/scripts/setup.sh",
        "cisco-catalyst-app",
        "3.1.0",
        "3.2.0",
        (),
    ),
    (
        "skills/cisco-security-cloud-setup/scripts/setup.sh",
        "CiscoSecurityCloud",
        "3.6.6",
        "3.6.7",
        ("--set-log-level", "INFO"),
    ),
    (
        "skills/cisco-intersight-setup/scripts/setup.sh",
        "Splunk_TA_Cisco_Intersight",
        "3.1.1",
        "3.2.0",
        (),
    ),
)


def _write_fake_splunk_curl(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log_path = Path(os.environ["CURL_LOG"])
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\\n")

url = next((arg for arg in args if arg.startswith(("http://", "https://"))), "")
if url.endswith("/services/auth/login"):
    print("<response><sessionKey>test-session</sessionKey></response>", end="")
elif "/services/apps/local/" in url and "%{http_code}" in args:
    print("200", end="")
elif "/services/apps/local/" in url:
    print(json.dumps({"entry": [{"content": {"version": os.environ["INSTALLED_APP_VERSION"]}}]}), end="")
else:
    print("unexpected REST call", file=sys.stderr)
    raise SystemExit(91)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _wrapper_env(tmp_path: Path, installed_version: str) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_splunk_curl(bin_dir / "curl")
    credentials = tmp_path / "credentials"
    credentials.write_text(
        'SPLUNK_SEARCH_API_URI="https://example.invalid:8089"\n'
        'SPLUNK_USER="user"\n'
        'SPLUNK_PASS="pass"\n',
        encoding="utf-8",
    )
    curl_log = tmp_path / "curl.log"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "CURL_LOG": str(curl_log),
            "INSTALLED_APP_VERSION": installed_version,
            "SPLUNK_CREDENTIALS_FILE": str(credentials),
            "SPLUNK_PLATFORM": "enterprise",
        }
    )
    return env, curl_log


def test_cisco_wrappers_reject_explicit_public_release_before_authentication(
    tmp_path: Path,
) -> None:
    for index, (script, app_name, _verified, public, mutation_args) in enumerate(WRAPPER_CASES):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        env, curl_log = _wrapper_env(case_dir, public)
        result = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / script),
                "--target-splunk-version",
                "10.5.2605",
                "--app-version",
                public,
                *mutation_args,
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout + result.stderr
        assert result.returncode != 0, app_name
        assert "not the repo-verified Splunk 10.5 package" in output, app_name
        assert "before any REST mutation" in output, app_name
        assert not curl_log.exists(), app_name


def test_cisco_wrappers_read_actual_version_and_refuse_before_rest_mutation(
    tmp_path: Path,
) -> None:
    for index, (script, app_name, _verified, public, mutation_args) in enumerate(WRAPPER_CASES):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        env, curl_log = _wrapper_env(case_dir, public)
        result = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / script),
                "--target-splunk-version",
                "10.5",
                *mutation_args,
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout + result.stderr
        assert result.returncode != 0, app_name
        assert f"installed {app_name} {public}" in output, output
        assert "before any REST mutation" in output, app_name

        calls = [json.loads(line) for line in curl_log.read_text(encoding="utf-8").splitlines()]
        urls = [
            arg
            for call in calls
            for arg in call
            if arg.startswith(("http://", "https://"))
        ]
        assert any(url.endswith("/services/auth/login") for url in urls), app_name
        assert all(
            url.endswith("/services/auth/login") or "/services/apps/local/" in url
            for url in urls
        ), app_name


def test_cisco_wrappers_accept_verified_pin_and_vendor_override_at_preflight(
    tmp_path: Path,
) -> None:
    missing_credentials = tmp_path / "missing-credentials"
    for script, app_name, verified, public, mutation_args in WRAPPER_CASES:
        for args, expected in (
            (("--app-version", verified), "Splunk credentials are required"),
            (
                ("--app-version", public, "--accept-unsupported-platform"),
                "vendor-approved override accepted",
            ),
        ):
            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(missing_credentials)
            env["SPLUNK_PLATFORM"] = "enterprise"
            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / script),
                    "--target-splunk-version",
                    "10.5",
                    *args,
                    *mutation_args,
                ],
                cwd=REPO_ROOT,
                env=env,
                input="",
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout + result.stderr
            assert result.returncode != 0, app_name
            assert expected in output, output
            assert "not the repo-verified Splunk 10.5 package" not in output, output


def test_security_cloud_status_only_warns_without_refusing_public_release(
    tmp_path: Path,
) -> None:
    env, _curl_log = _wrapper_env(tmp_path, "3.6.7")
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "skills/cisco-security-cloud-setup/scripts/setup.sh"),
            "--target-splunk-version",
            "10.5",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Installed app: CiscoSecurityCloud (version: 3.6.7)" in output
    assert "Status reporting is read-only" in output


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
