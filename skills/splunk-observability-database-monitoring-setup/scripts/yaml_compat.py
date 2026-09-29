"""Small skill-local YAML adapter used when the repository helper is absent.

The repository provides a richer no-dependency fallback at
``skills/shared/lib/yaml_compat.py``. A copied skill uses PyYAML instead; the
entrypoint reports an actionable dependency error rather than failing to
import from a repository path.
"""

from __future__ import annotations

import json
from typing import Any


def _yaml() -> Any:
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "DBMon rendering requires PyYAML when this skill is used outside "
            "the repository (install with: python3 -m pip install PyYAML)."
        ) from exc
    return yaml


def load_yaml_or_json(text: str, *, source: str = "<string>") -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return _yaml().safe_load(text)
    except Exception as exc:  # noqa: BLE001 - normalize parser failures for CLI callers.
        raise ValueError(f"Failed to parse YAML {source}: {exc}") from exc


def dump_yaml(payload: Any, *, sort_keys: bool = True) -> str:
    try:
        return _yaml().safe_dump(payload, sort_keys=sort_keys, default_flow_style=False)
    except Exception as exc:  # noqa: BLE001 - normalize serializer failures for CLI callers.
        raise ValueError(f"Failed to serialize YAML: {exc}") from exc
