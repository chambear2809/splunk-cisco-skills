"""Unit tests for the Splunk On-Call REST endpoint sender (rest_endpoint.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills/splunk-oncall-setup/scripts/rest_endpoint.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("rest_endpoint", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rest_endpoint"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def test_normalize_alert_message_type_allowlist(mod) -> None:
    with pytest.raises(mod.RestEndpointError, match="message_type"):
        mod.normalize_alert({"message_type": "PANIC"}, default_routing_key="r")


def test_normalize_alert_renders_structured_annotations(mod) -> None:
    payload = mod.normalize_alert(
        {
            "message_type": "CRITICAL",
            "entity_id": "abc",
            "entity_display_name": "x",
            "state_message": "y",
            "annotations": [
                {"kind": "url", "title": "Runbook", "value": "https://runbook"},
                {"kind": "note", "title": "Note", "value": "Investigate."},
                {"kind": "image", "title": "Graph", "value": "https://img"},
            ],
        },
        default_routing_key="r",
    )
    assert payload["vo_annotate.u.Runbook"] == "https://runbook"
    assert payload["vo_annotate.s.Note"] == "Investigate."
    assert payload["vo_annotate.i.Graph"] == "https://img"


def test_normalize_alert_caps_annotation_value_length(mod) -> None:
    too_long = "x" * 1200
    with pytest.raises(mod.RestEndpointError, match="1124-char"):
        mod.normalize_alert(
            {
                "message_type": "INFO",
                "entity_id": "abc",
                "annotations": [{"kind": "note", "title": "x", "value": too_long}],
            },
            default_routing_key="r",
        )


def test_build_url_rejects_path_traversal_in_keys(mod) -> None:
    with pytest.raises(mod.RestEndpointError, match="integration key"):
        mod.build_url(
            "https://alert.victorops.com/integrations/generic/20131114/alert",
            integration_key="../escape",
            routing_key="r",
        )
    with pytest.raises(mod.RestEndpointError, match="routing key"):
        mod.build_url(
            "https://alert.victorops.com/integrations/generic/20131114/alert",
            integration_key="abc-1234",
            routing_key="bad/slash",
        )


def test_redact_url_strips_integration_key(mod) -> None:
    url = "https://alert.victorops.com/integrations/generic/20131114/alert/SECRETKEYSHOULDNOTLEAK/checkout"
    redacted = mod.redact_url(url)
    assert "SECRETKEYSHOULDNOTLEAK" not in redacted
    assert "[REDACTED]" in redacted
    assert "/checkout" in redacted


def test_self_test_returns_info_then_recovery_with_dedup_entity_id(mod) -> None:
    alerts = mod.self_test_alerts()
    assert len(alerts) == 2
    assert alerts[0]["message_type"] == "INFO"
    assert alerts[1]["message_type"] == "RECOVERY"
    assert alerts[0]["entity_id"] == alerts[1]["entity_id"]
    assert alerts[0]["entity_id"].startswith("splunk-oncall-setup-self-test-")


def test_send_alerts_dry_run_emits_payloads_with_redacted_url(mod) -> None:
    result = mod.send_alerts(
        mod.self_test_alerts(),
        integration_key="abc-1234",
        routing_key="checkout",
        dry_run=True,
    )
    assert result["dry_run"] is True
    for entry in result["results"]:
        assert "[REDACTED]" in entry["url_template"]
        assert "abc-1234" not in entry["url_template"]


def test_post_alert_retries_429_then_succeeds(mod) -> None:
    class FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    responses = [
        HTTPError("https://x/y", 429, "rate limit", {"Retry-After": "0"}, BytesIO(b"")),
        FakeResponse(json.dumps({"result": "success", "entity_id": "abc"}).encode("utf-8")),
    ]

    def fake_urlopen(request, timeout=30):
        item = responses.pop(0)
        if isinstance(item, HTTPError):
            raise item
        return item

    with patch.object(mod, "urlopen", side_effect=fake_urlopen):
        result = mod.post_alert("https://alert.example.com/integrations/generic/20131114/alert/key/r", {"message_type": "INFO", "entity_id": "abc"})

    assert result["result"] == "success"


def test_secret_file_rejects_world_readable(tmp_path, mod) -> None:
    path = tmp_path / "key"
    path.write_text("k", encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(mod.RestEndpointError, match="overly permissive"):
        mod.read_secret_file(path, "REST endpoint integration key")


def test_isMultiResponder_must_be_boolean(mod) -> None:
    with pytest.raises(mod.RestEndpointError, match="isMultiResponder"):
        mod.normalize_alert(
            {"message_type": "CRITICAL", "entity_id": "x", "isMultiResponder": "yes"},
            default_routing_key="r",
        )
