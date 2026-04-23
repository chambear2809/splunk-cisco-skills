from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class SkillError(RuntimeError):
    """Base error for the skill."""


class ValidationError(SkillError):
    """Raised when the provided spec or live environment is invalid."""


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: str | Path, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def ensure_dir(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def timestamp_slug(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.strftime("%Y%m%dT%H%M%S%fZ")


def bool_from_any(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    return bool(value)


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def compact(value: Any) -> Any:
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, child in value.items():
            normalized = compact(child)
            if normalized is None:
                continue
            if normalized == []:
                continue
            compacted[key] = normalized
        return compacted
    if isinstance(value, list):
        return [compact(item) for item in value if compact(item) is not None]
    return value


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [canonicalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def subset_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        for key, value in expected.items():
            if key not in actual:
                return False
            if not subset_matches(actual[key], value):
                return False
        return True
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        remaining = list(actual)
        for expected_item in expected:
            match_index = next(
                (index for index, actual_item in enumerate(remaining) if subset_matches(actual_item, expected_item)),
                None,
            )
            if match_index is None:
                return False
            remaining.pop(match_index)
        return True
    return actual == expected


def semver_key(version: str) -> tuple[Any, ...]:
    parts: list[Any] = []
    for part in re.split(r"[.+-]", version or ""):
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part)
    return tuple(parts)


def infer_platform(spec: dict[str, Any]) -> str:
    connection = spec.get("connection", {})
    platform = str(connection.get("platform", "")).strip().lower()
    if platform in {"cloud", "enterprise"}:
        return platform
    base_url = str(connection.get("base_url") or "").strip()
    if not base_url:
        return "enterprise"
    hostname = urlparse(base_url).hostname or ""
    if "splunkcloud" in hostname:
        return "cloud"
    return "enterprise"


def normalize_index_expression(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


def macro_mentions_indexes(definition: str, indexes: list[str] | set[str]) -> bool:
    extracted = {index.lower() for index in extract_indexes_from_expression(definition)}
    if extracted:
        return all(index.lower() in extracted for index in indexes)
    normalized = normalize_index_expression(definition)
    return all(
        re.search(rf"(?<![A-Za-z0-9_.:-]){re.escape(index.lower())}(?![A-Za-z0-9_.:-])", normalized)
        for index in indexes
    )


def extract_indexes_from_expression(expression: str) -> list[str]:
    indexes: list[str] = []
    for match in re.finditer(r'index\s*=\s*"?(?P<index>[A-Za-z0-9_.:-]+)"?', expression, re.IGNORECASE):
        indexes.append(match.group("index"))
    for match in re.finditer(r'index\s+in\s*\((?P<body>[^)]+)\)', expression, re.IGNORECASE):
        body = match.group("body")
        indexes.extend(token.strip().strip('"').strip("'") for token in body.split(","))
    return [index for index in indexes if index]


def looks_like_metrics_index(index_name: str) -> bool:
    lowered = index_name.lower()
    return "metric" in lowered or lowered.startswith("m_")
