#!/usr/bin/env python3
"""Load shared Splunk Platform version defaults and compatibility metadata."""

from __future__ import annotations

import json
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
