#!/usr/bin/env python3
"""Validate documented Splunk Operator 3.1.0 compatibility combinations."""

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
    value: str, parts: int = 3, *, allow_platform_suffix: bool = False
) -> tuple[int, ...]:
    """Return canonical numeric version components, padding with zeroes.

    Splunk's matrix certifies GA release numbers, not arbitrary prerelease or
    build tags. Kubernetes server versions commonly carry a provider suffix,
    so only that call site opts into suffix parsing.
    """
    suffix = r"(?:[-+][0-9A-Za-z][0-9A-Za-z._-]*)?" if allow_platform_suffix else ""
    match = re.fullmatch(
        rf"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?{suffix}",
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
    """Check the release-note matrix for Splunk Operator 3.1.0.

    The 3.1.0 release notes list supported release lines rather than one broad
    semantic-version range. Keep the branches explicit so an unlisted future
    release is never silently presented as certified.
    """
    try:
        operator = version_tuple(operator_version)
        splunk = version_tuple(splunk_version)
    except ValueError as exc:
        return CompatibilityResult(False, False, str(exc))

    if operator != (3, 1, 0):
        return CompatibilityResult(
            False,
            False,
            "This skill's embedded support matrix is verified only for "
            "Splunk Operator 3.1.0; review that release's official notes.",
        )

    # The 3.1.0 release table names these Splunk release lines explicitly.
    # Do not treat an unlisted future release (for example, 10.6 or 11.0) as
    # verified merely because its semantic version is numerically greater.
    pre_separation_line = (splunk[0:2] == (9, 4) and splunk >= (9, 4, 3)) or (
        splunk[0:2] == (10, 0) and splunk <= (10, 0, 4)
    )
    separation_line = splunk[0:2] in {(10, 2), (10, 4)}

    if not kubernetes_version:
        supported_lines = pre_separation_line or separation_line
        if not supported_lines:
            return CompatibilityResult(
                False,
                True,
                "Splunk Enterprise is outside the release lines documented "
                "for Splunk Operator 3.1.0.",
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
            "The Splunk release line is documented for Operator 3.1.0; the "
            "live Kubernetes server version still must be checked.",
        )

    try:
        kubernetes = version_tuple(
            kubernetes_version, allow_platform_suffix=True
        )[:2]
    except ValueError as exc:
        return CompatibilityResult(False, False, str(exc))

    if kubernetes < (1, 25) or kubernetes > (1, 34):
        return CompatibilityResult(
            False,
            True,
            "Splunk Operator 3.1.0 supports Kubernetes 1.25 through 1.34.",
        )

    if kubernetes == (1, 34):
        supported = (
            (splunk[0:2] == (9, 4) and splunk >= (9, 4, 9))
            or (splunk[0:2] == (10, 0) and splunk >= (10, 0, 4))
            or (splunk[0:2] == (10, 4) and splunk >= (10, 4, 0))
        )
        if not supported:
            return CompatibilityResult(
                False,
                True,
                "Kubernetes 1.34 requires Splunk Enterprise 9.4.9+, "
                "10.0.4+, or 10.4+ on a release line listed by Splunk.",
            )
        if indexing_ingestion_separation and splunk[0:2] != (10, 4):
            return CompatibilityResult(
                False,
                True,
                "For Kubernetes 1.34, use Splunk Enterprise 10.4+ when "
                "enabling indexing and ingestion separation.",
            )
        return CompatibilityResult(
            True, True, "Supported Operator/Splunk/Kubernetes combination."
        )

    supported = pre_separation_line or separation_line
    if not supported:
        return CompatibilityResult(
            False,
            True,
            "Kubernetes 1.25-1.33 supports Splunk Enterprise 9.4.3 through "
            "10.0.4, or the listed 10.2.x and 10.4.x release lines, with "
            "Operator 3.1.0.",
        )
    if indexing_ingestion_separation and not separation_line:
        return CompatibilityResult(
            False,
            True,
            "Indexing and ingestion separation requires Splunk Enterprise "
            "on the listed 10.2.x or 10.4.x release lines.",
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
