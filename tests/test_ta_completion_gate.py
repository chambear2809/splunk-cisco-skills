#!/usr/bin/env python3
"""Coverage for Splunk TA ingest and dashboard completion requirements."""

from __future__ import annotations

from tests.regression_helpers import REPO_ROOT


SKILLS = REPO_ROOT / "skills"

TA_COMPANION_SKILLS = {
    "cisco-appdynamics-setup",
    "cisco-catalyst-enhanced-netflow-setup",
    "cisco-dc-networking-setup",
    "cisco-enterprise-networking-setup",
    "cisco-intersight-setup",
    "cisco-secure-access-setup",
    "cisco-secure-email-web-gateway-setup",
    "cisco-security-cloud-setup",
    "cisco-spaces-setup",
    "cisco-talos-intelligence-setup",
    "cisco-thousandeyes-setup",
    "cisco-webex-setup",
    "splunk-attack-analyzer-setup",
    "splunk-microsoft-cloud-setup",
    "splunk-stream-setup",
    "splunk-supported-addons-setup",
}

SKILL_REQUIRED_PHRASES = (
    "## TA Completion Gate",
    "../shared/ta_completion_gate.md",
    "data ingest path",
    "pre-built/package-shipped dashboards",
    "macro-aligned",
    "returning data",
    "package ships no dashboards",
)


def ta_skill_names() -> list[str]:
    suffix_skills = {path.name for path in SKILLS.glob("*-ta-setup") if path.is_dir()}
    return sorted(suffix_skills | TA_COMPANION_SKILLS)


def test_shared_ta_completion_gate_defines_ingest_and_dashboard_evidence() -> None:
    text = (SKILLS / "shared/ta_completion_gate.md").read_text(encoding="utf-8")
    for phrase in (
        "## Data Ingest",
        "## Pre-Built Dashboards",
        "data/ui/views",
        "visible",
        "index macros",
        "return data after ingest",
        "no pre-built dashboards",
    ):
        assert phrase in text


def test_ta_skills_reference_completion_gate() -> None:
    failures: list[str] = []
    for skill_name in ta_skill_names():
        skill_file = SKILLS / skill_name / "SKILL.md"
        text = skill_file.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        missing = [
            phrase
            for phrase in SKILL_REQUIRED_PHRASES
            if " ".join(phrase.split()) not in normalized
        ]
        if missing:
            failures.append(f"{skill_name}: missing {', '.join(missing)}")

    assert not failures, "\n".join(failures)


def test_requirements_catalog_mentions_ta_completion_gate() -> None:
    text = (REPO_ROOT / "SKILL_REQUIREMENTS.md").read_text(encoding="utf-8")
    for phrase in (
        "skills/shared/ta_completion_gate.md",
        "data ingest must be configured",
        "pre-built dashboards",
        "returning data",
    ):
        assert phrase in text


def test_agent_contexts_mention_ta_completion_gate() -> None:
    for name in ("AGENTS.md", "CLAUDE.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for phrase in (
            "skills/shared/ta_completion_gate.md",
            "package install alone",
            "dashboard companion",
            "validate data ingest",
            "ships no pre-built dashboards",
        ):
            assert phrase in text
