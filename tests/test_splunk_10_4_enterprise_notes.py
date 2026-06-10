"""Regressions for Splunk 10.4 enterprise deployment coverage notes."""

from __future__ import annotations

from tests.regression_helpers import REPO_ROOT


SHARED_NOTE = REPO_ROOT / "skills/shared/splunk_10_4_enterprise_deployment_notes.md"


def test_shared_10_4_note_covers_enterprise_deployment_gates() -> None:
    text = SHARED_NOTE.read_text(encoding="utf-8")
    for phrase in (
        "10.4.0",
        "10.4.2604",
        "non-root service user",
        "NT SERVICE\\Splunkd",
        "dedicated non-admin",
        "supported upgrade paths",
        "KV Store/Mongo",
        "Python 3.13",
        "Node.js removal",
        "SHA-1",
        "jQuery 2",
        "serverclass",
        "kvstoreSslClientConfig",
        "remote.azure.tenant_id",
        "auto_refresh_dashboards",
        "Victoria has no IDM",
    ):
        assert phrase in text


def test_plan_scope_references_link_shared_10_4_note() -> None:
    refs = [
        "skills/splunk-admin-doctor/reference.md",
        "skills/splunk-agent-management-setup/reference.md",
        "skills/splunk-monitoring-console-setup/reference.md",
        "skills/splunk-hec-service-setup/reference.md",
        "skills/splunk-platform-restart-orchestrator/reference.md",
        "skills/splunk-search-head-cluster-setup/reference.md",
        "skills/splunk-enterprise-host-setup/reference.md",
        "skills/splunk-cloud-acs-allowlist-setup/reference.md",
        "skills/splunk-cloud-acs-admin-setup/reference.md",
        "skills/splunk-license-manager-setup/reference.md",
    ]
    for rel in refs:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "splunk_10_4_enterprise_deployment_notes.md" in text, rel
