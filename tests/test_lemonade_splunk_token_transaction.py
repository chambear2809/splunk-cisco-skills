#!/usr/bin/env python3
"""Fail-closed tests for the Splunk token cutover wrapper."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills/lemonade-splunk-otel/scripts/transactional_splunk_token.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "lemonade_splunk_token_transaction", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cutover() -> ModuleType:
    return load_module()


def environment(token: str, *, other: str = "unchanged") -> bytes:
    return (
        f"SPLUNK_REALM=us0\nSPLUNK_ACCESS_TOKEN={token}\nUNCHANGED={other}\n"
    ).encode()


def test_payload_preflight_accepts_exact_token_only_change(cutover: ModuleType) -> None:
    cutover.validate_cutover_payloads(
        environment("NEW_OFFLINE_TOKEN_1234567890"),
        environment("OLD_OFFLINE_TOKEN_1234567890"),
    )


@pytest.mark.parametrize(
    ("staged", "live", "message"),
    [
        (
            environment("NEW_OFFLINE_TOKEN_1234567890", other="changed"),
            environment("OLD_OFFLINE_TOKEN_1234567890"),
            "may change only",
        ),
        (
            environment("SAME_OFFLINE_TOKEN_123456789"),
            environment("SAME_OFFLINE_TOKEN_123456789"),
            "must differ",
        ),
        (
            environment("NEW_OFFLINE_TOKEN_1234567890")
            + b"SPLUNK_ACCESS_TOKEN=SECOND_OFFLINE_TOKEN_123456\n",
            environment("OLD_OFFLINE_TOKEN_1234567890"),
            "exactly once",
        ),
        (
            environment("NEW TOKEN WITH WHITESPACE"),
            environment("OLD_OFFLINE_TOKEN_1234567890"),
            "printable ASCII",
        ),
        (
            b'SPLUNK_REALM=us0\nSPLUNK_ACCESS_TOKEN="NEW_OFFLINE_TOKEN_123456"\nUNCHANGED=unchanged\n',
            environment("OLD_OFFLINE_TOKEN_1234567890"),
            "may change only",
        ),
    ],
)
def test_payload_preflight_rejects_nontransactional_changes(
    cutover: ModuleType, staged: bytes, live: bytes, message: str
) -> None:
    with pytest.raises(cutover.CutoverError, match=message):
        cutover.validate_cutover_payloads(staged, live)


def test_transaction_argv_contains_only_paths_hashes_and_fixed_flags(
    cutover: ModuleType,
) -> None:
    args = argparse.Namespace(
        staged="/root/stage/splunk.env",
        live="/etc/otel/collector/splunk-otel-collector.conf",
        service="splunk-otel-collector.service",
        health_url="http://127.0.0.1:13133/",
        expected_sha256="1" * 64,
        collector_binary="/usr/bin/otelcol",
        collector_binary_sha256="2" * 64,
        state_root="/var/lib/splunk-token-transactions",
        health_timeout=15.0,
    )
    argv = cutover.transaction_apply_argv(args, live_sha256="3" * 64)
    joined = " ".join(argv)
    assert "--private-artifact" in argv
    assert "--expected-live-sha256" in argv
    assert "SPLUNK_ACCESS_TOKEN=" not in joined
    assert "OFFLINE_TOKEN" not in joined


def test_argument_errors_do_not_echo_an_accidental_secret(
    cutover: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    accidental = "OFFLINE_SECRET_MUST_NOT_BE_ECHOED"
    assert cutover.main(["apply", "--token", accidental]) == 1
    captured = capsys.readouterr()
    assert accidental not in captured.out + captured.err
    assert "command arguments are invalid" in captured.err
