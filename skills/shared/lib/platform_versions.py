#!/usr/bin/env python3
"""Load shared Splunk Platform version defaults and compatibility metadata."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

# A train is flagged "approaching end of support" this many days out. Matches
# the window splunk-admin-doctor already uses for the same registry field so
# the doctor and the render-time gates never disagree about the same host.
NEAR_EOS_WINDOW_DAYS = 90

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


def enterprise_support_end_dates(*, path: Path | None = None) -> dict[str, str]:
    payload = load_platform_versions(path)
    ends = payload.get("enterprise_support_end_dates") or {}
    if not isinstance(ends, dict):
        raise ValueError("enterprise_support_end_dates must be an object")
    return {str(train): str(value) for train, value in ends.items()}


def enterprise_support_status(
    value: str, *, path: Path | None = None, today: date | None = None
) -> dict[str, Any]:
    """Return the end-of-support posture for a version's release train.

    ``enterprise_support_end_dates`` carries the published last-supported date
    per train. A train that is still listed in ``enterprise_platform_versions``
    but is past that date receives no further fixes, so a version can satisfy
    its SVD floor exactly and still be unpatchable. Both the runtime classifier
    and the public-exposure SVD gate read this one helper so they cannot reach
    different conclusions about the same host.

    ``today`` is injectable so tests are deterministic and do not silently
    change meaning as the wall clock passes a published date.
    """

    train = platform_minor_train(value)
    reference = today or datetime.now(timezone.utc).date()
    raw = enterprise_support_end_dates(path=path).get(train)
    status: dict[str, Any] = {
        "train": train,
        "support_end_date": raw,
        "days_remaining": None,
        "eos": False,
        "near_eos": False,
    }
    if not raw:
        return status
    try:
        end = date.fromisoformat(raw)
    except ValueError:
        # A malformed date must not silently become "supported forever".
        raise ValueError(
            f"enterprise_support_end_dates.{train} is not an ISO date: {raw!r}"
        ) from None
    days = (end - reference).days
    status["days_remaining"] = days
    status["eos"] = days < 0
    status["near_eos"] = 0 <= days <= NEAR_EOS_WINDOW_DAYS
    return status


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
    value: str, *, path: Path | None = None, today: date | None = None
) -> str:
    """Classify a version against the public self-managed Enterprise contract.

    Returns one of ``supported``, ``end-of-support``, ``cloud-only``,
    ``not-publicly-released``, or ``unsupported``. Splunkbase compatibility
    targets and Splunk Cloud doc trains are deliberately not accepted as
    Enterprise runtime evidence.

    ``end-of-support`` takes precedence over ``supported``: a train stays
    listed in ``enterprise_platform_versions`` after its published support end
    date, so membership in that list alone is not evidence that the runtime
    still receives fixes.
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
        if enterprise_support_status(value, path=path, today=today)["eos"]:
            return "end-of-support"
        return "supported"
    if train in cloud_only:
        return "cloud-only"
    if train in not_public:
        return "not-publicly-released"
    return "unsupported"


def require_supported_enterprise_version(
    value: str, *, path: Path | None = None, today: date | None = None
) -> str:
    """Return the normalized train or raise for an unsupported runtime target."""

    train = platform_minor_train(value)
    classification = classify_enterprise_version(value, path=path, today=today)
    if classification == "end-of-support":
        status = enterprise_support_status(value, path=path, today=today)
        raise ValueError(
            f"Splunk Enterprise {value} is on the {train} train, whose support "
            f"ended {status['support_end_date']}. An end-of-support train "
            "receives no further security fixes, so meeting its last published "
            "SVD floor does not make it patchable. Upgrade to a supported "
            "train: "
            + ", ".join(
                str(item)
                for item in load_platform_versions(path).get(
                    "enterprise_platform_versions", []
                )
                if not enterprise_support_status(
                    f"{item}.0", path=path, today=today
                )["eos"]
            )
        )
    if classification != "supported":
        active_trains = [
            str(item)
            for item in load_platform_versions(path).get(
                "enterprise_platform_versions", []
            )
            if not enterprise_support_status(
                f"{item}.0", path=path, today=today
            )["eos"]
        ]
        raise ValueError(
            f"Splunk Enterprise {value} is {classification}; supported public "
            "self-managed trains are "
            + ", ".join(active_trains)
        )
    return train
