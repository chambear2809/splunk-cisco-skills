#!/usr/bin/env python3
"""Render WideField Splunk SIEM assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills/shared"))

from widefield_render_common import main, q  # noqa: E402


def apply_commands(args):
    return [
        "bash skills/widefield-splunk-siem-setup/scripts/setup.sh --apply --accept-apply "
        f"--index {q(args.index)} --sourcetype {q(args.sourcetype)} "
        f"--hec-source {q(args.hec_source)} --hec-token-name {q(args.hec_token_name)} "
        "--splunk-platform enterprise --hec-token-file /secure/splunk/widefield_hec_token",
        "bash skills/widefield-splunk-siem-setup/scripts/setup.sh --apply --accept-apply "
        f"--index {q(args.index)} --splunk-platform cloud --write-hec-token-file /secure/splunk/widefield_hec_token",
    ]


PROFILE = {
    "name": "widefield-splunk-siem-setup",
    "display_name": "WideField Splunk SIEM Setup",
    "target": "Splunk Platform HEC, index, search, and dashboard readiness",
    "render_root": "widefield-splunk-siem-rendered",
    "child_skills": ["splunk-hec-service-setup", "widefield-identity-threat-doctor"],
    "outcomes": "Prepare Splunk to receive WideField Security events through HEC, search them with schema-light `spath`, and expose starter knowledge objects.",
    "steps": [
        ("Create data contract", "Use the `widefield` index, `widefield:security` sourcetype, and `widefield` source by default."),
        ("Prepare HEC", "Delegate HEC token creation to the documented Splunk HEC service skill with allowed-index constraints."),
        ("Install knowledge", "Create a macro, saved search, and starter dashboard for WideField events."),
    ],
    "handoffs": "Use `splunk-data-source-readiness-doctor` after ingest to score ES/CIM/dashboard readiness when WideField events are in Splunk.",
    "validation_notes": "Search the target index and sourcetype with `spath`; confirm HEC token state and dashboard visibility.",
    "mutation_model": "Live apply can create the Splunk index, create a constrained HEC token through `splunk-hec-service-setup`, and install search-tier knowledge objects.",
    "apply_commands": apply_commands,
}


if __name__ == "__main__":
    raise SystemExit(main(PROFILE))
