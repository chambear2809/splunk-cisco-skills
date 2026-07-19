#!/usr/bin/env python3
"""Fail-closed helper for deprecated Python skill entrypoints."""

from __future__ import annotations

import sys
from collections.abc import Sequence


def deprecated_alias_main(
    legacy_skill: str,
    canonical_skill: str,
    entrypoint: str,
    argv: Sequence[str] | None = None,
) -> int:
    """Allow an exact help request and reject every operational invocation."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments in (["--help"], ["-h"]):
        print(
            f"DEPRECATED: {legacy_skill} is replaced_by {canonical_skill}.\n\n"
            "This compatibility entrypoint is help-only. It never renders assets "
            "or performs operational phases.\n\n"
            "Canonical handoff:\n"
            f"  python3 skills/{canonical_skill}/scripts/{entrypoint} --help"
        )
        return 0
    print(
        f"ERROR: deprecated skill '{legacy_skill}' is replaced_by "
        f"'{canonical_skill}'; legacy {entrypoint} is help-only and refuses all "
        "operational arguments.\n"
        f"HANDOFF: python3 skills/{canonical_skill}/scripts/{entrypoint} --help",
        file=sys.stderr,
    )
    return 2
