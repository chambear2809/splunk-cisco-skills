#!/usr/bin/env python3
"""Focused coverage for package-verified Supported Add-ons expansions."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.regression_helpers import REPO_ROOT


SECRET_ARG_RE = re.compile(r"--(?:password|secret|token|api-key|apikey)\b", re.IGNORECASE)

CASES = [
    pytest.param(
        "splunk-database-ta-setup",
        ["--products", "mssql", "--index", "database"],
        "splunk-database-ta",
        "Splunk_TA_microsoft-sqlserver",
        "mssql:errorlog",
        "mssql_database",
        id="database-mssql",
    ),
    pytest.param(
        "splunk-microsoft-exchange-ta-setup",
        ["--products", "exchange", "--index", "msexchange"],
        "splunk-microsoft-exchange-ta",
        "TA-Exchange-ClientAccess",
        "MSExchange:2013:MessageTracking",
        "microsoft_exchange",
        id="exchange",
    ),
    pytest.param(
        "splunk-microsoft-scom-ta-setup",
        ["--products", "scom", "--index", "scom"],
        "splunk-microsoft-scom-ta",
        "Splunk_TA_microsoft-scom",
        "microsoft:scom:alert",
        "microsoft_scom",
        id="scom",
    ),
    pytest.param(
        "splunk-netapp-ontap-ta-setup",
        ["--products", "ontap,extractions,indexes", "--index", "ontap"],
        "splunk-netapp-ontap-ta",
        "Splunk_TA_ontap",
        "ontap:perf",
        "netapp_ontap",
        id="netapp-ontap",
    ),
    pytest.param(
        "splunk-security-appliance-ta-setup",
        ["--products", "carbon_black,symantec_endpoint_protection", "--index", "endpoint"],
        "splunk-security-appliance-ta",
        "Splunk_TA_bit9-carbonblack",
        "bit9:carbonblack:json",
        "carbon_black",
        id="security-appliance",
    ),
]


def run_setup(skill: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(REPO_ROOT / "skills" / skill / "scripts" / "setup.sh"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest.mark.parametrize("skill,args,subdir,app_name,sourcetype,source_pack", CASES)
def test_new_package_verified_renderers_list_help_and_render(
    tmp_path: Path,
    skill: str,
    args: list[str],
    subdir: str,
    app_name: str,
    sourcetype: str,
    source_pack: str,
) -> None:
    list_result = run_setup(skill, "--phase", "list", *args, "--json")
    assert list_result.returncode == 0, list_result.stdout + list_result.stderr
    list_payload = json.loads(list_result.stdout)
    assert list_payload["ok"] is True

    help_result = run_setup(skill, "--help")
    assert help_result.returncode == 0
    assert not SECRET_ARG_RE.search(help_result.stderr + help_result.stdout)

    validate_result = subprocess.run(
        ["bash", str(REPO_ROOT / "skills" / skill / "scripts" / "validate.sh"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert validate_result.returncode == 0

    dry_run = run_setup(skill, "--phase", "render", *args, "--output-dir", str(tmp_path), "--dry-run", "--json")
    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
    dry_payload = json.loads(dry_run.stdout)
    assert dry_payload["dry_run"] is True
    assert "metadata.json" in dry_payload["files"]

    rendered = run_setup(skill, "--phase", "render", *args, "--output-dir", str(tmp_path), "--json")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    payload = json.loads(rendered.stdout)
    assert payload["ok"] is True

    rendered_dir = tmp_path / subdir
    metadata = json.loads((rendered_dir / "metadata.json").read_text(encoding="utf-8"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in rendered_dir.iterdir() if path.is_file())

    assert app_name in combined or app_name in json.dumps(metadata)
    assert sourcetype in combined
    assert source_pack in combined or source_pack in json.dumps(metadata)
    assert not SECRET_ARG_RE.search(combined)


def test_unresolved_security_products_remain_install_only() -> None:
    catalog = json.loads(
        (REPO_ROOT / "skills/splunk-supported-addons-setup/catalog.json").read_text(encoding="utf-8")
    )
    routes = catalog["official_glossary"]["routes"]
    for key in [
        "imperva-securesphere-waf",
        "mcafee-epo-syslog",
        "sophos",
        "symantec-dlp",
        "websense-dlp",
        "rsa-dlp",
        "ossec",
    ]:
        assert key not in routes, f"{key} should stay generic install-only until package extraction is verified"
