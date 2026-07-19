#!/usr/bin/env python3
"""Help-only compatibility handoff to splunk-cim-data-model-setup."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from deprecated_skill_alias import deprecated_alias_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(
        deprecated_alias_main(
            "splunk-cim-data-model",
            "splunk-cim-data-model-setup",
            "render_assets.py",
        )
    )
