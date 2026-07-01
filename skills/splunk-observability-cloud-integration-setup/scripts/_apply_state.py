"""Shared apply-state.json helpers for Splunk Observability Cloud integration API clients.

The renderer creates ``state/apply-state.json`` and ``state/idempotency-keys.json``
under the rendered output directory. Each API client appends a step record with
``timestamp``, ``section``, ``step``, ``idempotency_key``, ``result``
(``success | skipped | in_progress | failed``), and a sanitized response body. Records never
contain a token, password, JWT, or authorization header. Non-secret operation
identifiers such as a pairing job ID can be retained for required readback.

This module is intentionally dependency-free so it works under the repo's
default Python 3.11 interpreter without installing anything.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REDACTORS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization|x-vo-api-key|o11y-access-token)\s*[:=]\s*[^\s,'\"]+"),
    re.compile(r"eyJ[A-Za-z0-9._-]{20,}"),
    re.compile(r"(?i)(password|secret|api[_-]?key|token)\s*[:=]\s*[^\s,'\"]+"),
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
        "authorization", "x_vo_api_key", "o11y_access_token",
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
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = state_dir / "apply-state.json"
    if state_path.exists():
        state = _load_state(state_path)
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
    serialized = json.dumps(state, indent=2) + "\n"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=state_dir,
            prefix=".apply-state.",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            os.chmod(tmp_path, 0o600)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, state_path)
        os.chmod(state_path, 0o600)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()


def _load_state(state_path: Path) -> dict[str, Any]:
    """Load and validate state, failing closed on corruption."""
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"apply state is unreadable or corrupt: {state_path}; repair or remove it after review"
        ) from exc
    if not isinstance(state, dict) or not isinstance(state.get("steps"), list):
        raise RuntimeError(f"apply state has an invalid schema: {state_path}")
    if any(not isinstance(entry, dict) for entry in state["steps"]):
        raise RuntimeError(f"apply state contains a non-object step: {state_path}")
    return state


def has_step(state_dir: Path, idempotency_key: str) -> bool:
    """Return True when a previous run recorded a successful step under the same idempotency key."""
    state_path = state_dir / "apply-state.json"
    if not state_path.exists():
        return False
    state = _load_state(state_path)
    for entry in state.get("steps", []):
        if entry.get("idempotency_key") == idempotency_key and entry.get("result") == "success":
            return True
    return False


def successful_step_response(state_dir: Path, idempotency_key: str) -> Any | None:
    """Return the newest successful step response for readback, if present."""
    state_path = state_dir / "apply-state.json"
    if not state_path.exists():
        return None
    state = _load_state(state_path)
    for entry in reversed(state["steps"]):
        if entry.get("idempotency_key") == idempotency_key and entry.get("result") == "success":
            return entry.get("response")
    return None


def latest_step_response(
    state_dir: Path,
    idempotency_key: str,
    results: set[str] | None = None,
) -> Any | None:
    """Return the newest matching response, including asynchronous states.

    ``successful_step_response`` remains useful for fully converged actions;
    asynchronous operations such as pairing must also retain and resume an
    ``in_progress`` job rather than issuing a duplicate create request.
    """
    state_path = state_dir / "apply-state.json"
    if not state_path.exists():
        return None
    state = _load_state(state_path)
    for entry in reversed(state["steps"]):
        if entry.get("idempotency_key") != idempotency_key:
            continue
        if results is not None and entry.get("result") not in results:
            continue
        return entry.get("response")
    return None


def read_secret_file(path: str | os.PathLike[str]) -> str:
    """Read a chmod-600 secret file and refuse looser permissions or world-readable paths."""
    p = Path(os.fspath(path))
    if p.is_symlink() or not p.is_file() or p.stat().st_size == 0:
        raise PermissionError(f"secret file is missing or empty: {p}")
    mode = p.stat().st_mode & 0o777
    if mode != 0o600:
        raise PermissionError(
            f"secret file {p} must have mode 0o600 (found {oct(mode)}); chmod 600 it"
        )
    raw = p.read_text(encoding="utf-8")
    lines = raw.splitlines()
    if len(lines) != 1 or not lines[0]:
        raise ValueError(f"secret file must contain exactly one non-empty line: {p}")
    return lines[0]
