#!/usr/bin/env python3
"""Render WideField Saviynt integration assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills/shared"))

from widefield_render_common import main  # noqa: E402


def apply_commands(_args):
    return [
        "# Live Saviynt mutation is intentionally disabled until official/customer API docs are attached.",
        "bash skills/widefield-saviynt-integration-setup/scripts/setup.sh --apply --accept-apply",
    ]


PROFILE = {
    "name": "widefield-saviynt-integration-setup",
    "display_name": "WideField Saviynt Integration Setup",
    "target": "Saviynt Identity Cloud remediation handoff",
    "render_root": "widefield-saviynt-integration-rendered",
    "child_skills": ["widefield-identity-threat-doctor"],
    "outcomes": "Map WideField findings to Saviynt-certified remediation patterns and render evidence templates for customer-owned Saviynt workflows.",
    "steps": [
        ("Classify findings", "Map identity threat categories to access revocation, password reset, and micro-certification."),
        ("Render remediation map", "Emit a reviewable policy/action map with no Saviynt secrets."),
        ("Collect evidence", "Validate customer evidence that Saviynt remediation ran and closed the WideField finding."),
    ],
    "handoffs": "Saviynt policy creation, connector configuration, and remediation execution are operator/customer handoffs unless an official API reference is supplied.",
    "validation_notes": "Attach Saviynt remediation evidence showing revoke access, password reset, or micro-certification outcomes.",
    "mutation_model": "Live Saviynt mutation fails closed until official Saviynt or customer-provided API documentation is added to `reference.md`.",
    "apply_commands": apply_commands,
}


if __name__ == "__main__":
    raise SystemExit(main(PROFILE))
