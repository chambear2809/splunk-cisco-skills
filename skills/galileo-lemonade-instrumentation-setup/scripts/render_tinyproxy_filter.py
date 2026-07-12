#!/usr/bin/env python3
"""Render one exact-host tinyproxy ERE filter from a validated Galileo endpoint."""

from __future__ import annotations

import argparse
import os
import tempfile
import urllib.parse
from pathlib import Path

from collector_runtime_wrapper import exact_host_filter_rule, validate_endpoint


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--galileo-traces-endpoint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        _, endpoint = validate_endpoint(args.galileo_traces_endpoint)
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.port not in {None, 443} or not parsed.hostname:
            raise ValueError("Galileo traces endpoint must use HTTPS port 443")
        rule = exact_host_filter_rule(parsed.hostname) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{args.output.name}.", dir=args.output.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(rule)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, args.output)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
