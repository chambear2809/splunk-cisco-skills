#!/usr/bin/env python3
"""Load shared Splunk Platform version defaults and compatibility metadata."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_PLATFORM_VERSIONS_PATH = (
    Path(__file__).resolve().parents[1] / "references" / "splunk_platform_versions.json"
)


@lru_cache(maxsize=1)
def load_platform_versions(path: Path | None = None) -> dict[str, Any]:
    source = path or _PLATFORM_VERSIONS_PATH
    with source.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object in {source}")
    return payload


def platform_default(key: str, *, path: Path | None = None) -> str:
    payload = load_platform_versions(path)
    defaults = payload.get("defaults") or {}
    value = defaults.get(key)
    if not isinstance(value, str) or not value.strip():
        raise KeyError(f"defaults.{key} is missing in splunk_platform_versions.json")
    return value


def svd_enterprise_floors(*, path: Path | None = None) -> dict[str, str]:
    payload = load_platform_versions(path)
    floors = payload.get("svd_enterprise_floors") or {}
    if not isinstance(floors, dict):
        raise ValueError("svd_enterprise_floors must be an object")
    return {str(branch): str(floor) for branch, floor in floors.items()}


def splunkbase_pin(app_id: str, *, path: Path | None = None) -> dict[str, Any]:
    payload = load_platform_versions(path)
    pins = payload.get("splunkbase_pins") or {}
    entry = pins.get(str(app_id))
    if not isinstance(entry, dict):
        raise KeyError(f"splunkbase_pins.{app_id} is missing")
    return entry


def platform_minor_train(value: str) -> str:
    """Return MAJOR.MINOR from an exact numeric platform version.

    Runtime classifiers intentionally fail closed on prerelease labels, Cloud
    date-builds used as Enterprise versions, and arbitrary text. Callers that
    discover a normal Enterprise patch version such as ``10.4.1`` receive the
    corresponding ``10.4`` train.
    """

    match = re.fullmatch(r"\s*(\d+)\.(\d+)(?:\.\d+)?\s*", value or "")
    if not match:
        raise ValueError(
            f"invalid Splunk platform version {value!r}; expected MAJOR.MINOR or MAJOR.MINOR.PATCH"
        )
    return f"{int(match.group(1))}.{int(match.group(2))}"


def classify_enterprise_version(
    value: str, *, path: Path | None = None
) -> str:
    """Classify a version against the public self-managed Enterprise contract.

    Returns one of ``supported``, ``cloud-only``, ``not-publicly-released``, or
    ``unsupported``. Splunkbase compatibility targets and Splunk Cloud doc
    trains are deliberately not accepted as Enterprise runtime evidence.
    """

    train = platform_minor_train(value)
    payload = load_platform_versions(path)
    supported = {str(item) for item in payload.get("enterprise_platform_versions", [])}
    cloud_only = {str(item) for item in payload.get("enterprise_cloud_only_trains", [])}
    not_public = {
        str(item)
        for item in payload.get("enterprise_not_publicly_released_trains", [])
    }
    if train in supported:
        return "supported"
    if train in cloud_only:
        return "cloud-only"
    if train in not_public:
        return "not-publicly-released"
    return "unsupported"


def require_supported_enterprise_version(
    value: str, *, path: Path | None = None
) -> str:
    """Return the normalized train or raise for an unsupported runtime target."""

    train = platform_minor_train(value)
    classification = classify_enterprise_version(value, path=path)
    if classification != "supported":
        raise ValueError(
            f"Splunk Enterprise {value} is {classification}; supported public "
            "self-managed trains are "
            + ", ".join(
                str(item)
                for item in load_platform_versions(path).get(
                    "enterprise_platform_versions", []
                )
            )
        )
    return train
