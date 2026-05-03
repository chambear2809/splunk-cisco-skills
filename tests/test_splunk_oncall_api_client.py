"""Unit tests for the Splunk On-Call API client (oncall_api.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills/splunk-oncall-setup/scripts/oncall_api.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("oncall_api", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["oncall_api"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def test_token_bucket_acquires_at_configured_rate(mod) -> None:
    bucket = mod.TokenBucket(per_period=2.0, period_seconds=1.0)
    started = time.monotonic()
    bucket.acquire()
    bucket.acquire()
    bucket.acquire()
    elapsed = time.monotonic() - started
    # Bucket starts full so first two are free; the third must wait at least
    # ~0.5s (refill at 2/sec).
    assert elapsed >= 0.4


def test_secret_file_rejects_world_or_group_readable(tmp_path, mod) -> None:
    path = tmp_path / "secret"
    path.write_text("S3CRET", encoding="utf-8")
    path.chmod(0o644)  # world-readable
    with pytest.raises(mod.ApiError, match="overly permissive"):
        mod.read_secret_file(path, "API key")


def test_secret_file_rejects_empty(tmp_path, mod) -> None:
    path = tmp_path / "secret"
    path.write_text("", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(mod.ApiError, match="empty"):
        mod.read_secret_file(path, "API key")


def test_redact_headers_text_strips_api_key_and_id(mod) -> None:
    raw = "X-VO-Api-Id: abcd1234\nX-VO-Api-Key: SUPERSECRETKEY\nAuthorization: Bearer SECRETBEARER"
    redacted = mod.redact_headers_text(raw)
    assert "SUPERSECRETKEY" not in redacted
    assert "abcd1234" not in redacted
    assert "SECRETBEARER" not in redacted
    assert "[REDACTED]" in redacted


def test_validate_action_rejects_unsupported_service(mod) -> None:
    with pytest.raises(mod.ApiError, match="unsupported service"):
        mod.validate_action({"service": "synthetics", "path": "/foo", "method": "GET"}, 1)


def test_validate_action_rejects_unresolved_placeholder(mod) -> None:
    for bad_path in (
        "/api-public/v1/team/{team}",
        "/api-public/v1/team/<team_slug>/members",
        "/api-public/v1/team/{team_slug}/policies",
    ):
        with pytest.raises(mod.ApiError, match="placeholder"):
            mod.validate_action({"service": "on_call", "path": bad_path, "method": "GET"}, 1)


def test_validate_action_rejects_control_chars_in_path(mod) -> None:
    for bad_path in (
        "/api-public/v1/team/abc\nDELETE /etc",
        "/api-public/v1/team/abc\rdef",
        "/api-public/v1/team/\x00abc",
    ):
        with pytest.raises(mod.ApiError, match="control characters"):
            mod.validate_action({"service": "on_call", "path": bad_path, "method": "GET"}, 1)


def test_validate_action_rejects_unsupported_method(mod) -> None:
    with pytest.raises(mod.ApiError, match="unsupported method"):
        mod.validate_action({"service": "on_call", "path": "/api-public/v1/team", "method": "OPTIONS"}, 1)


def test_dry_run_emits_full_action_sequence_with_buckets(tmp_path, mod) -> None:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "apply-plan.json").write_text(json.dumps({
        "mode": "splunk-oncall",
        "api_base": "https://api.victorops.com",
        "actions": [
            {
                "action": "create_team",
                "object_type": "team",
                "name": "Checkout SRE",
                "service": "on_call",
                "method": "POST",
                "path": "/api-public/v1/team",
                "rate_bucket": "default",
                "writes": True,
            },
            {
                "action": "create_alert_rule",
                "object_type": "alert_rule",
                "name": "rule",
                "service": "on_call",
                "method": "POST",
                "path": "/api-public/v1/alertRules",
                "rate_bucket": "alert_rules",
                "writes": True,
            },
        ],
    }), encoding="utf-8")
    result = mod.apply_plan(plan_dir, api_id="ID", api_key_file=None, dry_run=True)
    assert result["dry_run"] is True
    assert result["bucket_counts"] == {"default": 1, "alert_rules": 1}
    assert all(action["service"] == "on_call" for action in result["sequence"])


def test_apply_plan_retries_429_then_succeeds(tmp_path, mod) -> None:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "apply-plan.json").write_text(json.dumps({
        "mode": "splunk-oncall",
        "api_base": "https://api.victorops.com",
        "actions": [
            {
                "action": "create_team",
                "object_type": "team",
                "name": "Checkout SRE",
                "service": "on_call",
                "method": "POST",
                "path": "/api-public/v1/team",
                "rate_bucket": "default",
                "writes": True,
            },
        ],
    }), encoding="utf-8")
    api_key = tmp_path / "key"
    api_key.write_text("APIKEY", encoding="utf-8")
    api_key.chmod(0o600)

    class FakeResponse:
        def __init__(self, body: bytes, request_id: str = "") -> None:
            self._body = body
            self.headers = {"X-VO-Request-Id": request_id}

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    responses = [
        HTTPError("https://api.victorops.com/api-public/v1/team", 429, "rate limit", {"Retry-After": "0"}, BytesIO(b"")),
        FakeResponse(json.dumps({"slug": "team-abc"}).encode("utf-8"), request_id="req-1"),
    ]

    def fake_urlopen(request, timeout=60):
        item = responses.pop(0)
        if isinstance(item, HTTPError):
            raise item
        return item

    with patch.object(mod, "urlopen", side_effect=fake_urlopen):
        result = mod.apply_plan(plan_dir, api_id="ID", api_key_file=api_key, dry_run=False)

    assert result["ok"] is True
    assert result["responses"][0]["response"]["slug"] == "team-abc"


def test_apply_plan_requires_credentials_for_live_apply(tmp_path, mod) -> None:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "apply-plan.json").write_text(json.dumps({"mode": "splunk-oncall", "actions": []}), encoding="utf-8")
    with pytest.raises(mod.ApiError, match="--api-id"):
        mod.apply_plan(plan_dir, api_id="", api_key_file=None, dry_run=False)


def test_safe_plan_path_rejects_traversal(tmp_path, mod) -> None:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    with pytest.raises(mod.ApiError, match="escapes plan directory"):
        mod.safe_plan_path(plan_dir, "../../etc/passwd")
