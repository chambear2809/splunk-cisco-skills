#!/usr/bin/env python3
"""Help-only compatibility handoff to splunk-ingest-actions-setup."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from deprecated_skill_alias import deprecated_alias_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(
        deprecated_alias_main(
            "splunk-ingest-actions",
            "splunk-ingest-actions-setup",
            "render_assets.py",
        )
    )
