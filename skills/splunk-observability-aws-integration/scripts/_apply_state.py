"""Shared apply-state.json helpers for the Splunk Observability AWS integration API client.

The renderer creates ``state/apply-state.json`` and ``state/idempotency-keys.json``
under the rendered output directory. Each API client appends a step record with
``timestamp``, ``section``, ``step``, ``idempotency_key``, ``result``
(``success | skipped | failed``), and a sanitized response body. Records never
contain a token, password, AWS access key, or external ID (the redactor strips
those).

This module is intentionally dependency-free so it works under the repo's
default Python 3.11 interpreter without installing anything.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REDACTORS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization|x-sf-token|aws[-_]secret[-_]access[-_]key)\s*[:=]\s*[^\s,'\"]+"),
    re.compile(r"eyJ[A-Za-z0-9._-]{20,}"),
    re.compile(r"(?i)(password|secret|api[_-]?key|token|external[_-]?id)\s*[:=]\s*[^\s,'\"]+"),
)

REDACT_PLACEHOLDER = "[REDACTED]"


def redact(value: Any) -> Any:
    """Walk a value and replace anything that looks like a secret."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _looks_secret_key(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        for pat in REDACTORS:
            value = pat.sub(REDACT_PLACEHOLDER, value)
        return value
    return value


def _looks_secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(s in lowered for s in (
        "token", "password", "secret", "apikey", "api_key", "jwt",
        "authorization", "x_sf_token", "external_id", "aws_secret",
        "aws_access_key", "key",
    ))


def append_step(
    state_dir: Path,
    section: str,
    step: str,
    idempotency_key: str,
    result: str,
    response: Any | None = None,
    notes: str | None = None,
) -> None:
    """Append a step record to ``apply-state.json`` (chmod 600)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "apply-state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {"steps": []}
    else:
        state = {"steps": []}
    state.setdefault("steps", []).append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "section": section,
        "step": step,
        "idempotency_key": idempotency_key,
        "result": result,
        "notes": notes,
        "response": redact(response),
    })
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    try:
        os.chmod(state_path, 0o600)
    except OSError:
        pass


def has_step(state_dir: Path, idempotency_key: str) -> bool:
    """Return True when a previous run recorded a successful step under the same idempotency key."""
    state_path = state_dir / "apply-state.json"
    if not state_path.exists():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    for entry in state.get("steps", []):
        if entry.get("idempotency_key") == idempotency_key and entry.get("result") == "success":
            return True
    return False


def read_secret_file(path: str | os.PathLike[str], allow_loose: bool = False) -> str:
    """Read a chmod-600 secret file and refuse looser permissions or world-readable paths."""
    p = Path(os.fspath(path))
    if not p.exists() or p.stat().st_size == 0:
        raise PermissionError(f"secret file is missing or empty: {p}")
    mode = p.stat().st_mode & 0o777
    if mode & 0o077 != 0 and not allow_loose:
        raise PermissionError(
            f"secret file {p} has loose permissions ({oct(mode)}); chmod 600 it or pass --allow-loose-token-perms."
        )
    return p.read_text(encoding="utf-8").strip()
