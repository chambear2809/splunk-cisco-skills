#!/usr/bin/env python3
"""Validate documented Splunk Operator compatibility combinations."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CompatibilityResult:
    supported: bool
    verified: bool
    message: str


def version_tuple(
    value: str, parts: int = 3, *, allow_platform_suffix: bool = False,
    allow_four_segments: bool = False,
) -> tuple[int, ...]:
    """Return canonical numeric version components, padding with zeroes.

    Splunk's matrix certifies GA release numbers, not arbitrary prerelease or
    build tags. Kubernetes server versions commonly carry a provider suffix,
    so only that call site opts into suffix parsing.
    """
    suffix = r"(?:[-+][0-9A-Za-z][0-9A-Za-z._-]*)?" if allow_platform_suffix else ""
    fourth_segment = r"(?:\.(\d+))?" if allow_four_segments else ""
    match = re.fullmatch(
        rf"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?{fourth_segment}{suffix}",
        value or "",
    )
    if not match:
        raise ValueError(f"unable to parse version: {value!r}")
    values = [int(item or 0) for item in match.groups()]
    return tuple(values[:parts])


def check_sok_compatibility(
    operator_version: str,
    splunk_version: str,
    kubernetes_version: str = "",
    indexing_ingestion_separation: bool = False,
) -> CompatibilityResult:
    """Check the release-note matrix for the supported Operator release.

    The 3.2.0 release notes list supported release ranges rather than one broad
    semantic-version range. Keep the branches explicit so an unlisted future
    release is never silently presented as certified.
    """
    try:
        operator = version_tuple(operator_version)
        splunk = version_tuple(splunk_version, parts=4, allow_four_segments=True)
    except ValueError as exc:
        return CompatibilityResult(False, False, str(exc))

    if operator != (3, 2, 0):
        return CompatibilityResult(
            False,
            False,
            "This skill's embedded support matrix is verified only for "
            "Splunk Operator 3.2.0; review that release's official notes.",
        )

    # The 3.2.0 release table names exact supported ranges. Do not infer
    # support for future releases merely from a numerically greater version.
    supported_splunk = (9, 4, 15) <= splunk <= (10, 6, 0, 5)
    separation_line = supported_splunk

    if not kubernetes_version:
        supported_lines = supported_splunk
        if not supported_lines:
            return CompatibilityResult(
                False,
                True,
                "Splunk Enterprise is outside the release lines documented "
                "for Splunk Operator 3.2.0.",
            )
        if indexing_ingestion_separation and not separation_line:
            return CompatibilityResult(
                False,
                True,
                "Indexing and ingestion separation requires Splunk Enterprise "
                "on the listed 10.2.x or 10.4.x release lines.",
            )
        return CompatibilityResult(
            True,
            True,
            "The Splunk release line is documented for Operator 3.2.0; the "
            "live Kubernetes server version still must be checked.",
        )

    try:
        kubernetes = version_tuple(
            kubernetes_version, allow_platform_suffix=True
        )[:2]
    except ValueError as exc:
        return CompatibilityResult(False, False, str(exc))

    if kubernetes < (1, 32) or kubernetes > (1, 36):
        return CompatibilityResult(
            False,
            True,
            "Splunk Operator 3.2.0 supports Kubernetes 1.32 through 1.36.",
        )

    if not supported_splunk:
        return CompatibilityResult(
            False,
            True,
            "Splunk Operator 3.2.0 supports Splunk Enterprise 9.4.15 through 10.6.0.",
        )
    return CompatibilityResult(
        True, True, "Supported Operator/Splunk/Kubernetes combination."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-version", required=True)
    parser.add_argument("--splunk-version", required=True)
    parser.add_argument("--kubernetes-version", default="")
    parser.add_argument("--indexing-ingestion-separation", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = check_sok_compatibility(
        args.operator_version,
        args.splunk_version,
        args.kubernetes_version,
        args.indexing_ingestion_separation,
    )
    if args.json:
        print(json.dumps(asdict(result), sort_keys=True))
    else:
        prefix = "OK" if result.supported else "ERROR"
        print(f"{prefix}: {result.message}")
    return 0 if result.supported else 1


if __name__ == "__main__":
    raise SystemExit(main())
