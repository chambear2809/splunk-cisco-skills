from __future__ import annotations

import json
import os
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


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "":
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_./:@-]+", text) and text.lower() not in {"true", "false", "null", "yes", "no", "on", "off"}:
        return text
    return json.dumps(text)


def render_yaml(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, child in value.items():
            if isinstance(child, (dict, list)) and child:
                lines.append(f"{prefix}{key}:")
                lines.append(render_yaml(child, indent + 2))
            elif child == {}:
                lines.append(f"{prefix}{key}: {{}}")
            elif child == []:
                lines.append(f"{prefix}{key}: []")
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(child)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{prefix}[]"
        lines = []
        for item in value:
            if isinstance(item, dict):
                if not item:
                    lines.append(f"{prefix}- {{}}")
                    continue
                keys = list(item)
                first_key = keys[0]
                first_value = item[first_key]
                if isinstance(first_value, (dict, list)) and first_value:
                    lines.append(f"{prefix}- {first_key}:")
                    lines.append(render_yaml(first_value, indent + 4))
                elif first_value == {}:
                    lines.append(f"{prefix}- {first_key}: {{}}")
                elif first_value == []:
                    lines.append(f"{prefix}- {first_key}: []")
                else:
                    lines.append(f"{prefix}- {first_key}: {_yaml_scalar(first_value)}")
                remainder = {key: item[key] for key in keys[1:]}
                if remainder:
                    lines.append(render_yaml(remainder, indent + 2))
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.append(render_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{_yaml_scalar(value)}"


def write_yaml(path: str | Path, payload: Any) -> None:
    Path(path).write_text(render_yaml(payload) + "\n", encoding="utf-8")


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
    if _scalar_equivalent(actual, expected):
        return True
    return actual == expected


def _scalar_equivalent(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return False
    if isinstance(actual, (int, float)) and isinstance(expected, str):
        return _numeric_string_equals(actual, expected)
    if isinstance(expected, (int, float)) and isinstance(actual, str):
        return _numeric_string_equals(expected, actual)
    return False


def _numeric_string_equals(number: int | float, text: str) -> bool:
    stripped = text.strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", stripped):
        return False
    try:
        return float(number) == float(stripped)
    except ValueError:
        return False


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
    env_platform = str(os.environ.get("SPLUNK_PLATFORM") or "").strip().lower()
    if env_platform in {"cloud", "enterprise"}:
        return env_platform
    base_url = str(
        connection.get("base_url") or os.environ.get("SPLUNK_SEARCH_API_URI") or os.environ.get("SPLUNK_URI") or ""
    ).strip()
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
