#!/usr/bin/env python3
"""Offline tests for the scheduled repository documentation URL audit."""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT = REPO_ROOT / "skills/shared/scripts/audit_documentation_urls.py"


def load_module():
    spec = importlib.util.spec_from_file_location("documentation_url_audit", AUDIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_documentation_host_scope_includes_current_vendor_sources() -> None:
    module = load_module()
    for url in (
        "https://help.splunk.com/en/splunk-enterprise",
        "https://docs.galileo.ai/release-notes",
        "https://developer.cisco.com/docs/example",
        "https://docs.cilium.io/en/stable/",
        "https://tetragon.io/docs/installation/tetra-cli/",
        "https://github.com/example/project/blob/main/README.md",
    ):
        assert module.is_documentation_url(url), url


def test_runtime_and_api_urls_are_not_documentation_citations() -> None:
    module = load_module()
    for url in (
        "https://api.galileo.ai/v1/projects",
        "https://ingest.us1.signalfx.com/v2/datapoint",
        "https://portal.victorops.com/client/example",
    ):
        assert not module.is_documentation_url(url), url


def test_composed_url_bases_and_repository_placeholders_are_excluded() -> None:
    module = load_module()
    for url in (
        "https://github.com/example/project/releases/download/",
        "https://github.com/example/project/tree/",
        "https://raw.githubusercontent.com/example/project/",
        "https://github.com/your-org/platform-iac",
    ):
        assert module.documentation_exclusion_reason(url) in {
            "composed-url-base",
            "placeholder",
        }


def test_helm_repository_base_probes_its_index() -> None:
    module = load_module()
    assert module.probe_target(
        "https://nvidia.github.io/dcgm-exporter/helm-charts"
    ) == "https://nvidia.github.io/dcgm-exporter/helm-charts/index.yaml"


def test_terminal_not_found_is_a_finding_but_redirected_success_is_ok() -> None:
    module = load_module()
    dead = module.evaluate(
        "https://docs.vendor.invalid/old",
        {"status": 404, "effective_url": "https://docs.vendor.invalid/old"},
    )
    moved = module.evaluate(
        "https://docs.vendor.invalid/old",
        {"status": 200, "effective_url": "https://docs.vendor.invalid/new"},
    )
    assert dead["state"] == "finding"
    assert dead["detail"] == "terminal HTTP 404"
    assert moved["state"] == "ok"
    assert moved["redirected"] is True


def test_bot_block_and_transport_failure_are_unverifiable() -> None:
    module = load_module()
    for result in (
        {"status": 403, "effective_url": "https://docs.vendor.invalid/page"},
        {
            "status": None,
            "effective_url": "https://docs.vendor.invalid/page",
            "error": "timeout",
        },
    ):
        record = module.evaluate("https://docs.vendor.invalid/page", result)
        assert record["state"] == "unverifiable"


def test_scheduled_workflow_runs_broad_audit_but_push_ci_does_not() -> None:
    drift = (REPO_ROOT / ".github/workflows/catalog-drift.yml").read_text(
        encoding="utf-8"
    )
    ci = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "audit_documentation_urls.py" in drift
    assert "audit_documentation_urls.py" not in ci
