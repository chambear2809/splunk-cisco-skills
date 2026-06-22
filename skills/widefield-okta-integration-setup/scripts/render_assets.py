#!/usr/bin/env python3
"""Render WideField Okta integration assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills/shared"))

from widefield_render_common import main, q  # noqa: E402


def apply_commands(args):
    return [
        "bash skills/widefield-okta-integration-setup/scripts/setup.sh --apply --accept-apply "
        f"--okta-org-url {q(args.okta_org_url or 'https://example.okta.com')} "
        "--okta-token-file /secure/okta/api_token "
        f"--receiver-url {q(args.receiver_url or 'https://widefield.example.com/okta/events')}",
        "bash skills/widefield-okta-integration-setup/scripts/setup.sh --apply --accept-apply "
        "--okta-org-url https://example.okta.com --okta-token-file /secure/okta/api_token "
        "--verify-event-hook-id EVENT_HOOK_ID",
    ]


PROFILE = {
    "name": "widefield-okta-integration-setup",
    "display_name": "WideField Okta Integration Setup",
    "target": "Okta OIN, shared-signal receiver, and event hook handoff",
    "render_root": "widefield-okta-integration-rendered",
    "child_skills": ["widefield-splunk-siem-setup", "widefield-identity-threat-doctor"],
    "outcomes": "Render Okta OIN/shared-signal setup and optionally create, update, verify, or deactivate documented Okta event hooks that point to a WideField receiver URL.",
    "steps": [
        ("Confirm OIN app path", "Document WideField Security - Detect and Remediate and required Okta administrator handoffs."),
        ("Render event hook payload", "Prepare a documented `/api/v1/eventHooks` payload with selected event types."),
        ("Validate System Log", "Check event hook reachability and shared-signal `security.events.provider.receive_event` evidence."),
    ],
    "handoffs": "OIN app assignment and Shared Signals provider details remain UI/provider handoffs unless Okta exposes a documented API for that exact object.",
    "validation_notes": "Use Okta System Log evidence for `security.events.provider.receive_event` and `user.risk.detect` when WideField sends SSF/CAEP risk events.",
    "mutation_model": "Live apply is limited to documented Okta Event Hooks Management API calls. OIN and shared-signal provider configuration are rendered as handoffs.",
    "apply_commands": apply_commands,
}


if __name__ == "__main__":
    raise SystemExit(main(PROFILE))
