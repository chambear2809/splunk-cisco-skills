#!/usr/bin/env python3
"""Render WideField Security parent setup assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills/shared"))

from widefield_render_common import main  # noqa: E402


def apply_commands(args):
    return [
        "# Parent apply delegates child render/validate only; run child skills directly for documented live mutation.",
        "bash skills/widefield-security-setup/scripts/setup.sh --apply --accept-apply --children okta,saviynt,splunk,google,doctor",
    ]


PROFILE = {
    "name": "widefield-security-setup",
    "display_name": "WideField Security Setup",
    "target": "WideField Security adoption router",
    "render_root": "widefield-security-rendered",
    "child_skills": [
        "widefield-okta-integration-setup",
        "widefield-saviynt-integration-setup",
        "widefield-splunk-siem-setup",
        "widefield-google-secops-setup",
        "widefield-identity-threat-doctor",
    ],
    "outcomes": "Resolve the WideField adoption scope, render source-backed plans, and delegate child render/validate execution to the skill that owns each target system.",
    "steps": [
        ("Scope identity surfaces", "Collect non-secret WideField workspace, IdP, SIEM, Google SecOps, Saviynt, and evidence requirements."),
        ("Render child plans", "Create reviewable Okta, Splunk, Saviynt, Google SecOps, and doctor handoffs."),
        ("Apply only documented paths", "Use the parent apply gate for child render/validate only; run child skills directly for documented live mutation with explicit acceptance."),
    ],
    "handoffs": "Use child skills for target-specific execution. Do not call undocumented WideField APIs from the parent router.",
    "validation_notes": "Run child validations after render. Parent validation is a coverage check across child evidence.",
    "mutation_model": "Parent apply is an orchestration gate that delegates child render/validate only. Run child skills directly for documented live mutation with explicit acceptance. The parent never calls undocumented WideField APIs directly.",
    "apply_commands": apply_commands,
}


if __name__ == "__main__":
    raise SystemExit(main(PROFILE))
