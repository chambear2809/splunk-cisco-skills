#!/usr/bin/env python3
"""Render WideField Google SecOps assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills/shared"))

from widefield_render_common import main  # noqa: E402


def apply_commands(_args):
    return [
        "# Live Google SecOps feed creation is disabled until a documented API path is added.",
        '# Set WIDEFIELD_EVIDENCE_FILE to exported Google SecOps feed/parser evidence.',
        ': "${WIDEFIELD_EVIDENCE_FILE:?Set WIDEFIELD_EVIDENCE_FILE to a local evidence JSON file}"',
        'grep -q "WIDEFIELD_SECURITY" "${WIDEFIELD_EVIDENCE_FILE}" || { echo "ERROR: evidence does not reference WIDEFIELD_SECURITY" >&2; exit 1; }',
        'bash skills/widefield-google-secops-setup/scripts/validate.sh --evidence-file "${WIDEFIELD_EVIDENCE_FILE}"',
    ]


PROFILE = {
    "name": "widefield-google-secops-setup",
    "display_name": "WideField Google SecOps Setup",
    "target": "Google SecOps WIDEFIELD_SECURITY ingestion and parser readiness",
    "render_root": "widefield-google-secops-rendered",
    "child_skills": ["widefield-identity-threat-doctor"],
    "outcomes": "Render feed, webhook, parser, and evidence assets for the Google SecOps `WIDEFIELD_SECURITY` default parser.",
    "steps": [
        ("Render feed intent", "Create a reviewable webhook/feed payload that names `WIDEFIELD_SECURITY`."),
        ("Plan parser readiness", "Document default-parser evidence and post-ingest search checks."),
        ("Collect evidence", "Validate supplied evidence from Google SecOps rather than assuming feed creation succeeded."),
    ],
    "handoffs": "Feed creation and parser assignment remain Google SecOps UI/API handoffs unless an official documented API path is added to this skill.",
    "validation_notes": "Evidence should show the feed name, log type `WIDEFIELD_SECURITY`, parser visibility, and sample UDM events.",
    "mutation_model": "Live Google SecOps mutation fails closed until a documented feed/webhook API path is added to `reference.md`.",
    "apply_commands": apply_commands,
}


if __name__ == "__main__":
    raise SystemExit(main(PROFILE))
