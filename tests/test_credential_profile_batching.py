"""Regression coverage for batched credential-profile resolution."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_bash(
    script: str, credentials: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {"SPLUNK_CREDENTIALS_FILE": str(credentials)}
    return subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env={**os.environ, **env, **(extra_env or {})},
        text=True,
        capture_output=True,
        check=False,
    )


def test_profile_endpoint_batch_preserves_explicit_endpoint(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "\n".join(
            (
                'PROFILE_cm__SPLUNK_SEARCH_API_URI="https://cm.example.invalid:8089"',
                'PROFILE_cm__SPLUNK_URI="https://legacy.example.invalid:8089"',
                'PROFILE_cm__SPLUNK_HOST="cm.example.invalid"',
                'PROFILE_cm__SPLUNK_MGMT_PORT="8089"',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    result = _run_bash(
        """
        source skills/shared/lib/credential_helpers.sh
        load_splunk_credentials
        _profile_endpoint_uri cm
        """,
        credentials,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://cm.example.invalid:8089"


def test_unknown_profile_still_fails_closed(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text('SPLUNK_HOST="flat.example.invalid"\n', encoding="utf-8")
    result = _run_bash(
        """
        source skills/shared/lib/credential_helpers.sh
        load_splunk_credentials
        _credential_profile_value_for_profile_key missing SPLUNK_HOST
        """,
        credentials,
    )
    assert result.returncode != 0


def test_deployment_profile_batch_keeps_profile_role_and_fallbacks(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "\n".join(
            (
                'SPLUNK_USER="flat-user"',
                'SPLUNK_PASS="flat-pass"',
                'PROFILE_cm__SPLUNK_USER="cm-user"',
                'PROFILE_cm__SPLUNK_TARGET_ROLE="indexer"',
                'PROFILE_cm__SPLUNK_HEC_URL="https://cm-hec.example.invalid:8088"',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    result = _run_bash(
        """
        source skills/shared/lib/credential_helpers.sh
        source skills/shared/lib/deployment_helpers.sh
        load_splunk_credentials
        deployment_apply_profile_globals cm
        printf '%s|%s|%s|%s' "$SPLUNK_USER" "$SPLUNK_PASS" "$SPLUNK_TARGET_ROLE" "$SPLUNK_HEC_URL"
        """,
        credentials,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "cm-user|flat-pass|indexer|https://cm-hec.example.invalid:8088"


def test_profile_batch_rejects_credential_file_drift(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        'PROFILE_cm__SPLUNK_SEARCH_API_URI="https://cm.example.invalid:8089"\n',
        encoding="utf-8",
    )
    result = _run_bash(
        """
        source skills/shared/lib/credential_helpers.sh
        load_splunk_credentials
        printf '\\nPROFILE_cm__SPLUNK_HOST=drift.example.invalid\\n' >> "$SPLUNK_CREDENTIALS_FILE"
        _profile_endpoint_uri cm
        """,
        credentials,
    )
    assert result.returncode != 0
    assert "credential file changed" in result.stderr


def test_profile_endpoint_uses_one_batched_profile_parse(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        'PROFILE_cm__SPLUNK_SEARCH_API_URI="https://cm.example.invalid:8089"\n',
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    counter = tmp_path / "python.count"
    real_python = "/usr/bin/python3"
    (bin_dir / "python3").write_text(
        f"#!/usr/bin/env bash\nprintf x >> {counter!s}\nexec {real_python} \"$@\"\n",
        encoding="utf-8",
    )
    (bin_dir / "python3").chmod(0o755)
    result = _run_bash(
        """
        source skills/shared/lib/credential_helpers.sh
        load_splunk_credentials
        : > "$COUNT_FILE"
        _profile_endpoint_uri cm >/dev/null
        """,
        credentials,
        {"PATH": f"{bin_dir}:{os.environ['PATH']}", "COUNT_FILE": str(counter)},
    )
    assert result.returncode == 0, result.stderr
    assert len(counter.read_text(encoding="utf-8")) <= 3


def test_empty_profile_value_preserves_flat_fallback(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "\n".join(
            (
                'SPLUNK_USER="flat-user"',
                'PROFILE_cm__SPLUNK_USER=""',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    result = _run_bash(
        """
        source skills/shared/lib/credential_helpers.sh
        source skills/shared/lib/deployment_helpers.sh
        load_splunk_credentials
        deployment_apply_profile_globals cm
        printf '%s' "$SPLUNK_USER"
        """,
        credentials,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "flat-user"


def test_deployment_profile_batch_uses_one_profile_parse(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        'PROFILE_cm__SPLUNK_USER="cm-user"\n',
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    counter = tmp_path / "python.count"
    real_python = "/usr/bin/python3"
    (bin_dir / "python3").write_text(
        f"#!/usr/bin/env bash\nprintf x >> {counter!s}\nexec {real_python} \"$@\"\n",
        encoding="utf-8",
    )
    (bin_dir / "python3").chmod(0o755)
    result = _run_bash(
        """
        source skills/shared/lib/credential_helpers.sh
        source skills/shared/lib/deployment_helpers.sh
        load_splunk_credentials
        : > "$COUNT_FILE"
        deployment_apply_profile_globals cm
        """,
        credentials,
        {"PATH": f"{bin_dir}:{os.environ['PATH']}", "COUNT_FILE": str(counter)},
    )
    assert result.returncode == 0, result.stderr
    # Protected route and snapshot checks remain per selected key; batching
    # keeps the parser work bounded rather than one parse per key plus a
    # duplicate profile-existence parse.
    assert len(counter.read_text(encoding="utf-8")) <= 35
