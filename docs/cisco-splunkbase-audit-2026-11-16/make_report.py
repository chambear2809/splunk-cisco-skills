#!/usr/bin/env python3
"""Compatibility entry point for regenerating the dated coverage report."""

from pathlib import Path
import runpy

root = Path(__file__).resolve().parent
runpy.run_path(str(root / "summarize_review.py"), run_name="__main__")
(root / "inventory.md").write_text((root / "coverage.md").read_text())
