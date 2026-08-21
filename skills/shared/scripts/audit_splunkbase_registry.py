#!/usr/bin/env python3
"""Audit and generate Splunkbase metadata/release provenance evidence.

Offline mode validates the registry and its tracked evidence snapshot. Live mode
fetches each public Splunkbase listing and release API response, compares their
normalized release facts with the registry, and can deterministically write a
new evidence snapshot. The snapshot proves which public metadata payloads were
reviewed; it does not prove the checksum or contents of downloadable packages.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "skills/shared/app_registry.json"
EVIDENCE_PATH = REPO_ROOT / "skills/shared/references/splunkbase_registry_evidence.json"
PLATFORM_VERSIONS_PATH = REPO_ROOT / "skills/shared/references/splunk_platform_versions.json"
USER_AGENT = "splunk-cisco-skills/platform-compatibility-audit"
EVIDENCE_SCHEMA_VERSION = 1
DEFAULT_MAX_EVIDENCE_AGE_DAYS = 90
EVIDENCE_POINTER_FIELD = "splunkbase_metadata_evidence"
EVIDENCE_SCOPE = (
    "Public Splunkbase listing and release API metadata/release provenance only; "
    "does not verify downloadable package binaries or package checksums."
)
SOURCE_VERIFIED_STATUS = "source-verified-current-release-api"
HISTORICAL_ONLY_STATUS = "historical-review-only-not-currently-reproducible"
TARGET_RE = re.compile(r"^(\d+)\.(\d+)(?:\.\d+)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NEXT_DATA_RE = re.compile(
    rb'<script[^>]*id="__NEXT_DATA__"[^>]*>(?P<payload>.*?)</script>',
    re.DOTALL,
)
CLOUD_RELEASE_FIELDS = (
    "cloud_compatible",
    "install_method_single",
    "install_method_distributed",
)
PACKAGE_FACT_FIELDS = (
    "skill",
    "app_name",
    "splunkbase_id",
    "label",
    "relationship",
    "license_ack_url",
    "package_patterns",
    "install_requires",
    "min_splunk_version",
    "role_support",
    "capabilities",
    "latest_verified_version",
    "verified_release_evidence_status",
    "latest_verified_date",
    "latest_release_version",
    "latest_release_date",
    "last_verified_date",
    "verified_platform_versions",
    "platform_versions",
    "compatibility_status",
    "compatibility_classification",
    "target_product",
    *CLOUD_RELEASE_FIELDS,
)


def default_compatibility_target() -> str:
    payload = json.loads(PLATFORM_VERSIONS_PATH.read_text(encoding="utf-8"))
    target = str((payload.get("defaults") or {}).get("splunkbase_compatibility_target", "")).strip()
    if not target:
        raise ValueError(
            "defaults.splunkbase_compatibility_target is missing from "
            f"{PLATFORM_VERSIONS_PATH}"
        )
    return target


def normalize_compatibility_target(value: str) -> str:
    match = TARGET_RE.fullmatch(str(value).strip())
    if not match:
        raise argparse.ArgumentTypeError(
            "target Splunk version must use MAJOR.MINOR or MAJOR.MINOR.PATCH"
        )
    return f"{match.group(1)}.{match.group(2)}"


def iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("evidence date must use YYYY-MM-DD") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit Splunkbase registry metadata and provenance evidence."
    )
    parser.add_argument("--registry", default=str(REGISTRY_PATH))
    parser.add_argument(
        "--target-splunk-version",
        default=normalize_compatibility_target(default_compatibility_target()),
        type=normalize_compatibility_target,
        help="Platform compatibility target (default: shared platform-version contract).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Fetch public Splunkbase listing and release API metadata.",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(EVIDENCE_PATH),
        metavar="PATH",
        help=(
            "With --live, atomically write the deterministic evidence snapshot "
            "(default: tracked shared reference path)."
        ),
    )
    parser.add_argument(
        "--evidence-date",
        type=iso_date,
        help=(
            "Snapshot date in YYYY-MM-DD. Defaults to the current UTC date; pass "
            "an explicit value when refreshing tracked evidence."
        ),
    )
    parser.add_argument(
        "--max-evidence-age-days",
        type=int,
        default=DEFAULT_MAX_EVIDENCE_AGE_DAYS,
        help=(
            "Read-only audit freshness window in days "
            f"(default: {DEFAULT_MAX_EVIDENCE_AGE_DAYS}; installers always use the default)."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--max-workers", type=int, default=12)
    args = parser.parse_args()
    if args.write_evidence and not args.live:
        parser.error("--write-evidence requires --live")
    if args.max_workers < 1:
        parser.error("--max-workers must be at least 1")
    if not 1 <= args.max_evidence_age_days <= 365:
        parser.error("--max-evidence-age-days must be between 1 and 365")
    if (
        args.write_evidence
        and args.max_evidence_age_days != DEFAULT_MAX_EVIDENCE_AGE_DAYS
    ):
        parser.error(
            "--max-evidence-age-days is a read-only audit option and cannot be "
            "combined with --write-evidence"
        )
    if args.evidence_date:
        requested_date = date.fromisoformat(args.evidence_date)
        today = datetime.now(timezone.utc).date()
        if requested_date > today:
            parser.error("--evidence-date cannot be in the future")
        if (today - requested_date).days > DEFAULT_MAX_EVIDENCE_AGE_DAYS:
            parser.error(
                "--evidence-date is outside the production evidence freshness window"
            )
    return args


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonicalize_json_arrays(value: Any) -> Any:
    """Recursively sort JSON arrays whose API order is not stable."""

    if isinstance(value, dict):
        return {key: canonicalize_json_arrays(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [canonicalize_json_arrays(item) for item in value]
        return sorted(items, key=canonical_json)
    return value


def parse_next_data(value: bytes) -> Any:
    """Extract the embedded Splunkbase listing JSON source payload."""

    match = NEXT_DATA_RE.search(value)
    if match is None:
        raise ValueError("Splunkbase listing omitted __NEXT_DATA__ source payload")
    return json.loads(match.group("payload").decode("utf-8"))


def canonical_listing_payload(value: bytes) -> bytes:
    """Extract and canonically serialize fetched Splunkbase listing JSON."""

    return canonical_json(canonicalize_json_arrays(parse_next_data(value)))


def listing_release_facts(payload: Any) -> dict[str, Any]:
    """Return the listed current release facts from a Splunkbase listing payload.

    The listing advertises one designated current release, which is not always the
    most recently published one when a vendor maintains parallel release lines.
    """

    props = payload.get("props") if isinstance(payload, dict) else None
    page_props = props.get("pageProps") if isinstance(props, dict) else None
    details = page_props.get("appDetails") if isinstance(page_props, dict) else None
    if not isinstance(details, dict):
        raise ValueError("Splunkbase listing omitted props.pageProps.appDetails")
    release = details.get("release")
    if not isinstance(release, dict):
        raise ValueError("Splunkbase listing omitted appDetails.release")
    version = str(release.get("name", "")).strip()
    if not version:
        raise ValueError("Splunkbase listing release omitted a version name")
    compatibility = release.get("versionCompatibility")
    platform_versions = [
        str(item.get("versionString", "")).strip()
        for item in compatibility
        if isinstance(item, dict) and str(item.get("versionString", "")).strip()
    ] if isinstance(compatibility, list) else []
    return {
        "version": version,
        "release_date": display_date_from_api(release.get("publishedDatetime")),
        "platform_versions": platform_versions,
    }


def package_facts(app: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical registry fields bound by release evidence."""

    return {field: app[field] for field in PACKAGE_FACT_FIELDS if field in app}


def app_package_facts_sha256(app: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(package_facts(app)))


def registry_package_facts_sha256(apps: list[dict[str, Any]]) -> str:
    facts = sorted(
        (package_facts(app) for app in apps),
        key=lambda item: int(str(item["splunkbase_id"])),
    )
    return sha256_bytes(canonical_json(facts))


def registry_apps(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        app
        for app in registry.get("apps", [])
        if str(app.get("splunkbase_id", "")).strip().isdigit()
    ]


def release_objects(payload: Any) -> list[dict[str, Any]]:
    """Return release objects from supported Splunkbase API response shapes."""

    if isinstance(payload, list):
        releases = payload
    elif isinstance(payload, dict):
        releases = payload.get("releases") or payload.get("results") or [payload]
    else:
        releases = []
    return [item for item in releases if isinstance(item, dict)]


def parse_cloud_release_metadata(payload: Any) -> dict[str, Any]:
    """Extract optional Cloud install facts from a Splunkbase release response."""

    release = next(iter(release_objects(payload)), None)
    if release is None:
        raise ValueError("Splunkbase release API returned no release object")
    return {field: release.get(field) for field in CLOUD_RELEASE_FIELDS}


def find_release(payload: Any, version: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in release_objects(payload)
            if str(item.get("name", "")).strip() == str(version).strip()
        ),
        None,
    )


def parse_verified_platform_versions(payload: Any, verified_version: str) -> list[Any]:
    """Return the exact product_versions for a verified release, or [] if absent."""

    release = find_release(payload, verified_version)
    if release is None:
        return []
    product_versions = release.get("product_versions")
    return product_versions if isinstance(product_versions, list) else []


def display_date_from_api(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = date.fromisoformat(raw[:10])
    except ValueError:
        return ""
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def normalized_release(release: dict[str, Any] | None) -> dict[str, Any]:
    if release is None:
        return {}
    platforms = release.get("product_versions")
    result: dict[str, Any] = {
        "version": str(release.get("name", "")).strip(),
        "release_date": display_date_from_api(
            release.get("published_datetime") or release.get("created_datetime")
        ),
        "platform_versions": platforms if isinstance(platforms, list) else [],
    }
    result.update({field: release.get(field) for field in CLOUD_RELEASE_FIELDS})
    return result


def splunkbase_urls(app_id: str) -> tuple[str, str]:
    return (
        f"https://splunkbase.splunk.com/app/{app_id}",
        f"https://splunkbase.splunk.com/api/v1/app/{app_id}/release/",
    )


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()


def fetch_release_payload(app_id: str) -> Any:
    _, url = splunkbase_urls(app_id)
    return json.loads(fetch_bytes(url).decode("utf-8", "replace"))


def fetch_cloud_release_metadata(app_id: str) -> dict[str, Any]:
    return parse_cloud_release_metadata(fetch_release_payload(app_id))


def fetch_splunkbase(
    app_id: str,
    include_cloud_metadata: bool = False,
    verified_release_version: str | None = None,
) -> dict[str, Any]:
    """Fetch and normalize both public source payloads for one app."""

    listing_url, release_url = splunkbase_urls(app_id)
    listing_bytes = fetch_bytes(listing_url)
    release_bytes = fetch_bytes(release_url)
    listing_payload = parse_next_data(listing_bytes)
    release_payload = json.loads(release_bytes.decode("utf-8", "replace"))

    listing = listing_release_facts(listing_payload)
    latest_version = listing["version"]
    latest_release = find_release(release_payload, latest_version)
    if latest_release is None:
        latest_release = next(iter(release_objects(release_payload)), None)

    result: dict[str, Any] = {
        "splunkbase_id": app_id,
        "latest_version": latest_version,
        "latest_release_date": listing["release_date"],
        "platform_versions": listing["platform_versions"],
        "platform_raw": ", ".join(listing["platform_versions"]),
        "url": listing_url,
        "sources": {
            "listing": {
                "url": listing_url,
                "sha256": sha256_bytes(
                    canonical_json(canonicalize_json_arrays(listing_payload))
                ),
                "hash_input": "canonical-json-of-fetched-next-data-with-recursively-sorted-arrays",
            },
            "release_api": {
                "url": release_url,
                "sha256": sha256_bytes(release_bytes),
                "hash_input": "raw-fetched-payload",
            },
        },
        "latest_release_facts": normalized_release(latest_release),
    }
    if verified_release_version is not None:
        verified_release = find_release(release_payload, verified_release_version)
        result["verified_release_facts"] = normalized_release(verified_release)
        result["verified_platform_versions"] = (
            (verified_release or {}).get("product_versions", [])
            if isinstance((verified_release or {}).get("product_versions", []), list)
            else []
        )
        result["verified_release_date"] = display_date_from_api(
            (verified_release or {}).get("published_datetime")
            or (verified_release or {}).get("created_datetime")
        )
    if include_cloud_metadata:
        result.update(normalized_release(latest_release))
        result["latest_version"] = latest_version
        result["latest_release_date"] = listing["release_date"]
    return result


def compatibility_status(platform_versions: list[str], target: str) -> str:
    return "supported" if target in platform_versions else "unsupported"


def audit_install_dependencies(apps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate the numeric app dependency graph used by mutating installers."""

    findings: list[dict[str, Any]] = []
    known_ids = {str(app.get("splunkbase_id", "")) for app in apps}
    graph: dict[str, list[str]] = {app_id: [] for app_id in known_ids}
    for app in apps:
        app_id = str(app.get("splunkbase_id", ""))
        raw_dependencies = app.get("install_requires", [])
        if not isinstance(raw_dependencies, list):
            findings.append(
                {
                    "id": app_id,
                    "severity": "error",
                    "field": "install_requires",
                    "message": "must be a list of canonical numeric Splunkbase ID strings",
                }
            )
            continue
        seen: set[str] = set()
        for raw_dependency in raw_dependencies:
            if not isinstance(raw_dependency, str) or not re.fullmatch(
                r"[1-9]\d*", raw_dependency
            ):
                findings.append(
                    {
                        "id": app_id,
                        "severity": "error",
                        "field": "install_requires",
                        "message": (
                            "dependency IDs must be canonical non-zero numeric strings"
                        ),
                    }
                )
                continue
            if raw_dependency in seen:
                findings.append(
                    {
                        "id": app_id,
                        "severity": "error",
                        "field": "install_requires",
                        "message": f"duplicate dependency {raw_dependency}",
                    }
                )
                continue
            seen.add(raw_dependency)
            if raw_dependency == app_id:
                findings.append(
                    {
                        "id": app_id,
                        "severity": "error",
                        "field": "install_requires",
                        "message": "self-dependency is not allowed",
                    }
                )
                continue
            if raw_dependency not in known_ids:
                findings.append(
                    {
                        "id": app_id,
                        "severity": "error",
                        "field": "install_requires",
                        "message": f"dependency target {raw_dependency} is missing",
                    }
                )
                continue
            graph[app_id].append(raw_dependency)

    state: dict[str, int] = {}
    stack: list[str] = []
    reported_cycles: set[tuple[str, ...]] = set()

    def visit(app_id: str) -> None:
        state[app_id] = 1
        stack.append(app_id)
        for dependency in graph.get(app_id, []):
            if state.get(dependency, 0) == 0:
                visit(dependency)
            elif state.get(dependency) == 1:
                start = stack.index(dependency)
                cycle = tuple(stack[start:] + [dependency])
                canonical = min(
                    tuple(cycle[index:-1] + cycle[:index] + (cycle[index],))
                    for index in range(len(cycle) - 1)
                )
                if canonical not in reported_cycles:
                    reported_cycles.add(canonical)
                    findings.append(
                        {
                            "id": app_id,
                            "severity": "error",
                            "field": "install_requires",
                            "message": f"dependency cycle detected: {' -> '.join(cycle)}",
                        }
                    )
        stack.pop()
        state[app_id] = 2

    for app_id in sorted(graph, key=int):
        if state.get(app_id, 0) == 0:
            visit(app_id)
    return findings


def audit_offline(apps: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = audit_install_dependencies(apps)
    for app in apps:
        app_id = str(app.get("splunkbase_id", "")).strip()
        platforms = app.get("platform_versions")
        status = app.get("compatibility_status")
        expected = compatibility_status(platforms or [], target) if isinstance(platforms, list) else ""
        if not isinstance(platforms, list) or not all(isinstance(item, str) for item in platforms):
            findings.append({"id": app_id, "severity": "error", "field": "platform_versions", "message": "missing or invalid"})
        if status not in {"supported", "unsupported"}:
            findings.append({"id": app_id, "severity": "error", "field": "compatibility_status", "message": "missing or invalid"})
        elif expected and status != expected:
            findings.append(
                {
                    "id": app_id,
                    "severity": "error",
                    "field": "compatibility_status",
                    "message": f"{status} does not match platform_versions for {target}",
                }
            )
        if "cloud_compatible" in app:
            if not isinstance(app.get("cloud_compatible"), bool):
                findings.append(
                    {
                        "id": app_id,
                        "severity": "error",
                        "field": "cloud_compatible",
                        "message": "must be boolean when explicitly declared",
                    }
                )
            for field in ("install_method_single", "install_method_distributed"):
                if not isinstance(app.get(field), str) or not app[field].strip():
                    findings.append(
                        {
                            "id": app_id,
                            "severity": "error",
                            "field": field,
                            "message": "must be a non-empty string when cloud_compatible is declared",
                        }
                    )
            if app.get("cloud_compatible") is False:
                for field in ("install_method_single", "install_method_distributed"):
                    value = app.get(field)
                    if isinstance(value, str) and value.strip() and value != "rejected":
                        findings.append(
                            {
                                "id": app_id,
                                "severity": "error",
                                "field": field,
                                "message": "must be rejected when cloud_compatible is false",
                            }
                        )
        else:
            for field in ("install_method_single", "install_method_distributed"):
                if field in app and (
                    not isinstance(app.get(field), str) or not app[field].strip()
                ):
                    findings.append(
                        {
                            "id": app_id,
                            "severity": "error",
                            "field": field,
                            "message": "must be a non-empty string when explicitly declared",
                        }
                    )
        if app.get("latest_verified_version") != app.get("latest_release_version"):
            verified_platforms = app.get("verified_platform_versions")
            if not isinstance(verified_platforms, list) or not all(
                isinstance(item, str) for item in verified_platforms
            ):
                findings.append(
                    {
                        "id": app_id,
                        "severity": "error",
                        "field": "verified_platform_versions",
                        "message": (
                            "must be a list of strings when latest_verified_version "
                            "differs from latest_release_version"
                        ),
                    }
                )
        evidence_status = app.get("verified_release_evidence_status")
        if evidence_status not in (None, HISTORICAL_ONLY_STATUS):
            findings.append(
                {
                    "id": app_id,
                    "severity": "error",
                    "field": "verified_release_evidence_status",
                    "message": "missing or invalid provenance classification",
                }
            )
        if (
            evidence_status == HISTORICAL_ONLY_STATUS
            and app.get("latest_verified_version") == app.get("latest_release_version")
        ):
            findings.append(
                {
                    "id": app_id,
                    "severity": "error",
                    "field": "verified_release_evidence_status",
                    "message": "historical-only status is invalid when verified equals public latest",
                }
            )
        for field in (
            "latest_verified_version",
            "latest_verified_date",
            "latest_release_version",
            "latest_release_date",
            "last_verified_date",
        ):
            if not isinstance(app.get(field), str) or not app[field].strip():
                findings.append({"id": app_id, "severity": "error", "field": field, "message": "missing or invalid"})
    return findings


def registry_date_to_iso(value: Any) -> str:
    try:
        return datetime.strptime(str(value), "%B %d, %Y").date().isoformat()
    except ValueError:
        return ""


def expected_release_facts(app: dict[str, Any], *, verified: bool) -> dict[str, Any]:
    split = app.get("latest_verified_version") != app.get("latest_release_version")
    platforms = (
        app.get("verified_platform_versions", [])
        if verified and split
        else app.get("platform_versions", [])
    )
    prefix = "latest_verified" if verified else "latest_release"
    result: dict[str, Any] = {
        "version": app.get(f"{prefix}_version"),
        "release_date": app.get(f"{prefix}_date"),
        "platform_versions": platforms,
    }
    if not verified or not split:
        result.update(
            {field: app[field] for field in CLOUD_RELEASE_FIELDS if field in app}
        )
    return result


def resolve_evidence_path(registry_path: Path, declared_path: str) -> Path:
    path = Path(declared_path)
    if path.is_absolute():
        return path
    if registry_path.resolve() == REGISTRY_PATH.resolve() or path.parts[:1] == ("skills",):
        return REPO_ROOT / path
    return registry_path.parent / path


def evidence_finding(field: str, message: str, **values: Any) -> dict[str, Any]:
    return {
        "id": "registry-evidence",
        "severity": "error",
        "field": field,
        "message": message,
        **values,
    }


def audit_evidence(
    registry: dict[str, Any],
    apps: list[dict[str, Any]],
    registry_path: Path,
    *,
    today: date | None = None,
    max_age_days: int = DEFAULT_MAX_EVIDENCE_AGE_DAYS,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Fail closed if tracked provenance is absent, stale, or mismatched."""

    findings: list[dict[str, Any]] = []
    pointer = registry.get(EVIDENCE_POINTER_FIELD)
    if not isinstance(pointer, dict):
        return [
            evidence_finding(
                EVIDENCE_POINTER_FIELD,
                "missing top-level Splunkbase metadata evidence pointer",
            )
        ], None

    required_pointer = (
        "schema_version",
        "path",
        "sha256",
        "generated_date",
        "max_evidence_age_days",
        "registry_package_facts_sha256",
        "scope",
    )
    for field in required_pointer:
        if field not in pointer:
            findings.append(evidence_finding(f"pointer.{field}", "missing"))
    declared_path = str(pointer.get("path", "")).strip()
    evidence_path = resolve_evidence_path(registry_path, declared_path) if declared_path else None
    if evidence_path is None or not evidence_path.is_file():
        findings.append(evidence_finding("pointer.path", "evidence snapshot is missing"))
        return findings, None

    evidence_bytes = evidence_path.read_bytes()
    actual_file_hash = sha256_bytes(evidence_bytes)
    if pointer.get("sha256") != actual_file_hash:
        findings.append(
            evidence_finding(
                "pointer.sha256",
                "evidence snapshot hash mismatch",
                actual=pointer.get("sha256"),
                expected=actual_file_hash,
            )
        )
    try:
        evidence = json.loads(evidence_bytes)
    except json.JSONDecodeError as exc:
        findings.append(evidence_finding("snapshot", f"invalid JSON: {exc}"))
        return findings, None
    if not isinstance(evidence, dict):
        findings.append(evidence_finding("snapshot", "top level must be an object"))
        return findings, None

    registry_hash = registry_package_facts_sha256(apps)
    for location, actual in (
        ("pointer.registry_package_facts_sha256", pointer.get("registry_package_facts_sha256")),
        ("snapshot.registry_package_facts_sha256", evidence.get("registry_package_facts_sha256")),
    ):
        if actual != registry_hash:
            findings.append(
                evidence_finding(
                    location,
                    "stale registry package-facts binding",
                    actual=actual,
                    expected=registry_hash,
                )
            )
    if pointer.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        findings.append(evidence_finding("pointer.schema_version", "unsupported schema"))
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        findings.append(evidence_finding("snapshot.schema_version", "unsupported schema"))
    if pointer.get("max_evidence_age_days") != DEFAULT_MAX_EVIDENCE_AGE_DAYS:
        findings.append(evidence_finding("pointer.max_evidence_age_days", "unsupported policy"))
    if evidence.get("max_evidence_age_days") != DEFAULT_MAX_EVIDENCE_AGE_DAYS:
        findings.append(evidence_finding("snapshot.max_evidence_age_days", "unsupported policy"))
    if evidence.get("evidence_type") != "splunkbase-public-metadata-release-provenance":
        findings.append(evidence_finding("snapshot.evidence_type", "missing or altered"))
    if evidence.get("app_count") != len(apps):
        findings.append(
            evidence_finding(
                "snapshot.app_count",
                "numeric registry app count mismatch",
                actual=evidence.get("app_count"),
                expected=len(apps),
            )
        )
    if evidence.get("compatibility_target") != registry.get("compatibility_target"):
        findings.append(
            evidence_finding(
                "snapshot.compatibility_target",
                "registry/evidence target mismatch",
                actual=evidence.get("compatibility_target"),
                expected=registry.get("compatibility_target"),
            )
        )
    if evidence.get("registry_package_fact_fields") != list(PACKAGE_FACT_FIELDS):
        findings.append(
            evidence_finding(
                "snapshot.registry_package_fact_fields",
                "missing or altered canonical package-fact projection",
            )
        )
    if pointer.get("generated_date") != evidence.get("generated_date"):
        findings.append(evidence_finding("generated_date", "pointer/snapshot mismatch"))
    if pointer.get("scope") != EVIDENCE_SCOPE or evidence.get("scope") != EVIDENCE_SCOPE:
        findings.append(evidence_finding("scope", "missing or altered metadata-only scope"))

    generated_date = str(evidence.get("generated_date", ""))
    generated: date | None = None
    try:
        generated = date.fromisoformat(generated_date)
    except ValueError:
        findings.append(evidence_finding("generated_date", "must use YYYY-MM-DD"))
    audit_date = today or datetime.now(timezone.utc).date()
    if generated is not None:
        if generated > audit_date:
            findings.append(
                evidence_finding(
                    "generated_date",
                    "evidence date is in the future",
                    actual=generated_date,
                    expected=f"<={audit_date.isoformat()}",
                )
            )
        elif (audit_date - generated).days > max_age_days:
            findings.append(
                evidence_finding(
                    "generated_date",
                    "evidence exceeds the maximum age",
                    actual=(audit_date - generated).days,
                    expected=f"<={max_age_days} days",
                )
            )
    registry_dates = [registry_date_to_iso(app.get("last_verified_date")) for app in apps]
    newest_registry_date = max((item for item in registry_dates if item), default="")
    if newest_registry_date and generated_date < newest_registry_date:
        findings.append(
            evidence_finding(
                "generated_date",
                "evidence predates registry verification facts",
                actual=generated_date,
                expected=f">={newest_registry_date}",
            )
        )

    evidence_apps = evidence.get("apps")
    if not isinstance(evidence_apps, list):
        findings.append(evidence_finding("apps", "must be a list"))
        return findings, evidence
    by_id: dict[str, dict[str, Any]] = {}
    for item in evidence_apps:
        if not isinstance(item, dict):
            findings.append(evidence_finding("apps", "entries must be objects"))
            continue
        app_id = str(item.get("splunkbase_id", ""))
        if app_id in by_id:
            findings.append(evidence_finding("apps", f"duplicate app ID {app_id}"))
        by_id[app_id] = item
    expected_ids = {str(app["splunkbase_id"]) for app in apps}
    if set(by_id) != expected_ids:
        findings.append(
            evidence_finding(
                "apps",
                "evidence app IDs do not exactly match the numeric registry",
                actual=sorted(by_id),
                expected=sorted(expected_ids),
            )
        )

    for app in apps:
        app_id = str(app["splunkbase_id"])
        item = by_id.get(app_id)
        if item is None:
            continue
        if item.get("app_name") != app.get("app_name"):
            findings.append(evidence_finding(f"apps.{app_id}.app_name", "registry mismatch"))
        expected_app_hash = app_package_facts_sha256(app)
        if item.get("registry_package_facts_sha256") != expected_app_hash:
            findings.append(
                evidence_finding(
                    f"apps.{app_id}.registry_package_facts_sha256",
                    "stale app package-facts binding",
                )
            )
        sources = item.get("sources")
        if not isinstance(sources, dict):
            findings.append(evidence_finding(f"apps.{app_id}.sources", "must be an object"))
            sources = {}
        for name, expected_url in zip(
            ("listing", "release_api"),
            splunkbase_urls(app_id),
            strict=True,
        ):
            source = sources.get(name)
            if not isinstance(source, dict):
                findings.append(evidence_finding(f"apps.{app_id}.sources.{name}", "missing"))
                continue
            if source.get("url") != expected_url:
                findings.append(evidence_finding(f"apps.{app_id}.sources.{name}.url", "unexpected source URL"))
            if not SHA256_RE.fullmatch(str(source.get("sha256", ""))):
                findings.append(evidence_finding(f"apps.{app_id}.sources.{name}.sha256", "missing or invalid SHA-256"))
            expected_hash_input = (
                "canonical-json-of-fetched-next-data-with-recursively-sorted-arrays"
                if name == "listing"
                else "raw-fetched-payload"
            )
            if source.get("hash_input") != expected_hash_input:
                findings.append(
                    evidence_finding(
                        f"apps.{app_id}.sources.{name}.hash_input",
                        "missing or altered hash-input declaration",
                    )
                )
        for kind, verified in (("latest_release", False), ("verified_release", True)):
            expected = expected_release_facts(app, verified=verified)
            actual = item.get(kind)
            if not isinstance(actual, dict):
                findings.append(evidence_finding(f"apps.{app_id}.{kind}", "missing"))
                continue
            for field, value in expected.items():
                if actual.get(field) != value:
                    findings.append(
                        evidence_finding(
                            f"apps.{app_id}.{kind}.{field}",
                            "registry/evidence mismatch",
                            actual=actual.get(field),
                            expected=value,
                        )
                    )
            if verified:
                expected_source_status = (
                    HISTORICAL_ONLY_STATUS
                    if app.get("verified_release_evidence_status")
                    == HISTORICAL_ONLY_STATUS
                    else SOURCE_VERIFIED_STATUS
                )
                if actual.get("source_status") != expected_source_status:
                    findings.append(
                        evidence_finding(
                            f"apps.{app_id}.{kind}.source_status",
                            "registry/evidence provenance classification mismatch",
                            actual=actual.get("source_status"),
                            expected=expected_source_status,
                        )
                    )
    return findings, evidence


def audit_live(apps: list[dict[str, Any]], target: str, max_workers: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {str(app["splunkbase_id"]).strip(): app for app in apps}
    live_entries: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {
            executor.submit(
                fetch_splunkbase,
                app_id,
                any(field in app for field in CLOUD_RELEASE_FIELDS),
                str(app.get("latest_verified_version", "")).strip(),
            ): app_id
            for app_id, app in by_id.items()
        }
        for future in concurrent.futures.as_completed(future_to_id):
            app_id = future_to_id[future]
            try:
                live_entries.append(future.result())
            except Exception as exc:  # noqa: BLE001 - surface fetch failure, keep auditing
                findings.append(
                    {
                        "id": app_id,
                        "app_name": by_id[app_id].get("app_name", ""),
                        "severity": "error",
                        "field": "live_fetch",
                        "message": f"live fetch failed: {exc}",
                    }
                )

    live_entries.sort(key=lambda item: int(item["splunkbase_id"]))
    for live in live_entries:
        app = by_id[live["splunkbase_id"]]
        expected_status = compatibility_status(live["platform_versions"], target)
        comparisons = {
            "latest_release_version": live["latest_version"],
            "latest_release_date": live["latest_release_date"],
            "platform_versions": live["platform_versions"],
            "compatibility_status": expected_status,
        }
        if live.get("verified_release_date"):
            comparisons["latest_verified_date"] = live["verified_release_date"]
        for field in CLOUD_RELEASE_FIELDS:
            if field in app:
                comparisons[field] = live.get(field)
        if app.get("latest_verified_version") != app.get("latest_release_version"):
            comparisons["verified_platform_versions"] = live.get(
                "verified_platform_versions",
                [],
            )
        has_verified_source = bool(live.get("verified_release_facts"))
        declared_historical = (
            app.get("verified_release_evidence_status") == HISTORICAL_ONLY_STATUS
        )
        if not has_verified_source and not declared_historical:
            findings.append(
                {
                    "id": live["splunkbase_id"],
                    "app_name": app.get("app_name", ""),
                    "severity": "error",
                    "field": "latest_verified_version",
                    "actual": app.get("latest_verified_version"),
                    "expected": "release present in public release API",
                }
            )
        elif has_verified_source and declared_historical:
            findings.append(
                {
                    "id": live["splunkbase_id"],
                    "app_name": app.get("app_name", ""),
                    "severity": "error",
                    "field": "verified_release_evidence_status",
                    "actual": HISTORICAL_ONLY_STATUS,
                    "expected": SOURCE_VERIFIED_STATUS,
                }
            )
        for field, expected in comparisons.items():
            actual = app.get(field)
            if actual != expected:
                findings.append(
                    {
                        "id": live["splunkbase_id"],
                        "app_name": app.get("app_name", ""),
                        "severity": "error",
                        "field": field,
                        "actual": actual,
                        "expected": expected,
                    }
                )
        api_latest = live.get("latest_release_facts") or {}
        for field, expected in (
            ("version", live.get("latest_version")),
            ("release_date", live.get("latest_release_date")),
            ("platform_versions", live.get("platform_versions")),
        ):
            if api_latest.get(field) != expected:
                findings.append(
                    {
                        "id": live["splunkbase_id"],
                        "app_name": app.get("app_name", ""),
                        "severity": "error",
                        "field": f"source_consistency.{field}",
                        "actual": api_latest.get(field),
                        "expected": expected,
                    }
                )
    findings.sort(key=lambda item: (int(item["id"]) if str(item["id"]).isdigit() else -1, item["field"]))
    return live_entries, findings


def evidence_entry(app: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    latest = dict(live["latest_release_facts"])
    split = app.get("latest_verified_version") != app.get("latest_release_version")
    verified_from_api = bool(live.get("verified_release_facts"))
    verified = (
        dict(live["verified_release_facts"])
        if verified_from_api
        else expected_release_facts(app, verified=True)
    )
    verified["source_status"] = (
        SOURCE_VERIFIED_STATUS
        if verified_from_api
        else HISTORICAL_ONLY_STATUS
    )
    for facts, include_cloud in ((latest, True), (verified, not split)):
        if not include_cloud:
            for field in CLOUD_RELEASE_FIELDS:
                facts.pop(field, None)
        else:
            for field in CLOUD_RELEASE_FIELDS:
                if field not in app:
                    facts.pop(field, None)
    return {
        "splunkbase_id": str(app["splunkbase_id"]),
        "app_name": app["app_name"],
        "registry_package_facts_sha256": app_package_facts_sha256(app),
        "sources": live["sources"],
        "latest_release": latest,
        "verified_release": verified,
    }


def build_evidence(
    apps: list[dict[str, Any]],
    live_entries: list[dict[str, Any]],
    target: str,
    generated_date: str,
) -> dict[str, Any]:
    by_id = {str(item["splunkbase_id"]): item for item in live_entries}
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_type": "splunkbase-public-metadata-release-provenance",
        "scope": EVIDENCE_SCOPE,
        "generated_date": generated_date,
        "max_evidence_age_days": DEFAULT_MAX_EVIDENCE_AGE_DAYS,
        "compatibility_target": target,
        "registry_package_fact_fields": list(PACKAGE_FACT_FIELDS),
        "registry_package_facts_sha256": registry_package_facts_sha256(apps),
        "app_count": len(apps),
        "apps": [
            evidence_entry(app, by_id[str(app["splunkbase_id"])])
            for app in sorted(apps, key=lambda item: int(str(item["splunkbase_id"])))
        ],
    }


def evidence_bytes(evidence: dict[str, Any]) -> bytes:
    return (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_evidence(path: Path, evidence: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = evidence_bytes(evidence)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return sha256_bytes(payload)


def pointer_path_value(registry_path: Path, evidence_path: Path) -> str:
    """Return a stable repo-relative pointer when possible."""

    try:
        return evidence_path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        try:
            return evidence_path.resolve().relative_to(
                registry_path.resolve().parent
            ).as_posix()
        except ValueError:
            return str(evidence_path.resolve())


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def update_registry_evidence_pointer(
    registry_path: Path,
    evidence_path: Path,
    evidence: dict[str, Any],
    file_hash: str,
) -> dict[str, Any]:
    """Atomically refresh pointer metadata without changing package facts."""

    current = json.loads(registry_path.read_text(encoding="utf-8"))
    current_apps = registry_apps(current)
    current_hash = registry_package_facts_sha256(current_apps)
    evidence_hash = str(evidence["registry_package_facts_sha256"])
    if current_hash != evidence_hash:
        raise RuntimeError(
            "registry package facts changed during live evidence generation; rerun"
        )
    current[EVIDENCE_POINTER_FIELD] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "path": pointer_path_value(registry_path, evidence_path),
        "sha256": file_hash,
        "generated_date": evidence["generated_date"],
        "max_evidence_age_days": DEFAULT_MAX_EVIDENCE_AGE_DAYS,
        "registry_package_facts_sha256": evidence_hash,
        "scope": EVIDENCE_SCOPE,
    }
    atomic_write_json(registry_path, current)
    return current[EVIDENCE_POINTER_FIELD]


def main() -> int:
    args = parse_args()
    registry_path = Path(args.registry)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    apps = registry_apps(registry)
    offline_findings = audit_offline(apps, args.target_splunk_version)
    evidence_findings, _ = audit_evidence(
        registry,
        apps,
        registry_path,
        max_age_days=args.max_evidence_age_days,
    )
    configuration_findings: list[dict[str, Any]] = []
    declared_target = str(registry.get("compatibility_target", "")).strip()
    contract_target = default_compatibility_target()
    if declared_target != contract_target:
        configuration_findings.append(
            {
                "id": "registry",
                "severity": "error",
                "field": "compatibility_target",
                "actual": declared_target,
                "expected": contract_target,
            }
        )

    live_entries: list[dict[str, Any]] = []
    live_findings: list[dict[str, Any]] = []
    generated_evidence: dict[str, Any] | None = None
    written_evidence: dict[str, str] | None = None
    if args.live:
        live_entries, live_findings = audit_live(apps, args.target_splunk_version, args.max_workers)
        if not live_findings and len(live_entries) == len(apps):
            generated_date = args.evidence_date or datetime.now(timezone.utc).date().isoformat()
            generated_evidence = build_evidence(
                apps,
                live_entries,
                args.target_splunk_version,
                generated_date,
            )
            if args.write_evidence and not configuration_findings and not offline_findings:
                output_path = Path(args.write_evidence)
                file_hash = write_evidence(output_path, generated_evidence)
                pointer = update_registry_evidence_pointer(
                    registry_path,
                    output_path,
                    generated_evidence,
                    file_hash,
                )
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
                evidence_findings, _ = audit_evidence(
                    registry,
                    registry_apps(registry),
                    registry_path,
                    max_age_days=args.max_evidence_age_days,
                )
                written_evidence = {
                    "path": str(output_path),
                    "sha256": file_hash,
                    "generated_date": generated_date,
                    "registry_package_facts_sha256": generated_evidence[
                        "registry_package_facts_sha256"
                    ],
                    "registry_pointer_path": str(pointer["path"]),
                }

    payload = {
        "registry": str(registry_path),
        "target_splunk_version": args.target_splunk_version,
        "max_evidence_age_days": args.max_evidence_age_days,
        "splunkbase_app_count": len(apps),
        "configuration_findings": configuration_findings,
        "offline_findings": offline_findings,
        "evidence_findings": evidence_findings,
        "live_findings": live_findings,
        "live_entries": live_entries,
        "generated_evidence": generated_evidence,
        "written_evidence": written_evidence,
        "ok": not configuration_findings and not offline_findings and not evidence_findings and not live_findings,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Splunkbase registry apps: {len(apps)}")
        print(f"Target Splunk version: {args.target_splunk_version}")
        for finding in configuration_findings + offline_findings + evidence_findings + live_findings:
            print(
                "ERROR "
                f"{finding.get('id')}/{finding.get('app_name', '')} "
                f"{finding.get('field')}: {finding.get('actual', finding.get('message'))!r} "
                f"!= {finding.get('expected', '')!r}"
            )
        if written_evidence:
            print(
                "WROTE metadata/release provenance evidence "
                f"{written_evidence['path']} sha256={written_evidence['sha256']}"
            )
        print("OK" if payload["ok"] else "FAILED")

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
