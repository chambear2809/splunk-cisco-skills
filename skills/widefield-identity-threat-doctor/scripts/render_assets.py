#!/usr/bin/env python3
"""Render WideField identity threat doctor assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills/shared"))

from widefield_render_common import main  # noqa: E402


def apply_commands(_args):
    return [
        "# Destructive remediation requires target-specific acceptance and documented runbooks.",
        "bash skills/widefield-identity-threat-doctor/scripts/setup.sh --validate --dry-run",
    ]


PROFILE = {
    "name": "widefield-identity-threat-doctor",
    "display_name": "WideField Identity Threat Doctor",
    "target": "OAuth, connected app, NHI ownership, MFA posture, AI identity, and session checks",
    "render_root": "widefield-identity-threat-doctor-rendered",
    "child_skills": ["widefield-okta-integration-setup", "widefield-splunk-siem-setup", "widefield-saviynt-integration-setup"],
    "outcomes": "Run read-only checks where evidence or credentials exist and render remediation command packets that stay gated until target-specific acceptance.",
    "steps": [
        ("Check identity threats", "Look for OAuth token abuse, rogue or over-privileged apps, NHI ownership gaps, MFA posture issues, AI identity events, and anomalous sessions."),
        ("Correlate evidence", "Use Splunk searches, Okta System Log checks, and supplied evidence JSON."),
        ("Gate remediation", "Render remediation handoffs and require explicit target-specific acceptance before any destructive action."),
    ],
    "handoffs": "Send Okta hook issues to `widefield-okta-integration-setup`, Splunk ingest gaps to `widefield-splunk-siem-setup`, and governance remediation to `widefield-saviynt-integration-setup`.",
    "validation_notes": "Use read-only Splunk searches and Okta System Log queries first. Do not revoke sessions, reset passwords, or change app grants from doctor mode without a documented runbook.",
    "mutation_model": "Doctor mode is read-only by default. Destructive remediation fails closed unless a target-specific acceptance flag and documented runbook are present.",
    "apply_commands": apply_commands,
}


if __name__ == "__main__":
    raise SystemExit(main(PROFILE))
