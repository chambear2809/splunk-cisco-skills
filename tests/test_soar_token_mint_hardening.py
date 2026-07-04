"""Adversarial coverage for SOAR automation-token mint journaling."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SOAR_HELPERS = REPO_ROOT / "skills/shared/lib/soar_helpers.sh"
SOAR_SETUP = REPO_ROOT / "skills/splunk-soar-setup/scripts/setup.sh"


def run_mint(
    tmp_path: Path,
    *,
    behavior: str,
    accept: bool,
    rotate: bool = False,
    token_path: Path | None = None,
    admin_path: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    token_path = token_path or tmp_path / "automation.token"
    admin_path = admin_path or tmp_path / "admin.password"
    call_log = tmp_path / "calls.log"
    observed_state = tmp_path / "observed-state"
    script = f"""
source {shlex.quote(str(SOAR_HELPERS))}
_soar_admin_basic_auth_call() {{
    local method="$3" path="$4" output_file="" write_out=""
    shift 4
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -o|--output) output_file="$2"; shift 2 ;;
            -w|--write-out) write_out="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
    printf '%s %s\n' "${{method}}" "${{path}}" >> "${{CALL_LOG}}"
    case "${{method}} ${{path}}" in
        'POST /rest/ph_user')
            printf '{{}}' > "${{output_file}}"
            [[ -n "${{write_out}}" ]] && printf '201'
            ;;
        GET\\ /rest/ph_user*)
            printf '%s' '{{"data":[{{"id":42,"username":"automation_splunk","type":"automation"}}]}}' > "${{output_file}}"
            ;;
        'POST /rest/ph_user/42/token')
            python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' \
                "${{JOURNAL_FILE}}" > "${{OBSERVED_STATE}}"
            case "${{MINT_BEHAVIOR}}" in
                success) printf '%s' '{{"key":"minted-secret-value"}}' > "${{output_file}}" ;;
                missing) printf '%s' '{{}}' > "${{output_file}}" ;;
                transport) return 1 ;;
                symlink-race)
                    ln -s "${{VICTIM_FILE}}" "${{TOKEN_DEST}}"
                    printf '%s' '{{"key":"minted-secret-value"}}' > "${{output_file}}"
                    ;;
                hardlink-race)
                    ln "${{VICTIM_FILE}}" "${{TOKEN_DEST}}"
                    printf '%s' '{{"key":"minted-secret-value"}}' > "${{output_file}}"
                    ;;
                signal) kill -TERM "${{BASHPID}}" ;;
                *) return 99 ;;
            esac
            ;;
        *) return 98 ;;
    esac
}}
export SOAR_API_ALLOW_HTTP=true
export SOAR_ACCEPT_TOKEN_MINT_OR_ROTATION={str(accept).lower()}
export SOAR_ROTATE_AUTOMATION_TOKEN={str(rotate).lower()}
set +e
soar_create_automation_user \
    http://127.0.0.1:8080 "${{ADMIN_FILE}}" automation_splunk "${{TOKEN_DEST}}"
exit $?
"""
    env = {
        **os.environ,
        "ADMIN_FILE": str(admin_path),
        "CALL_LOG": str(call_log),
        "JOURNAL_FILE": f"{token_path}.mint-state.json",
        "MINT_BEHAVIOR": behavior,
        "OBSERVED_STATE": str(observed_state),
        "TOKEN_DEST": str(token_path),
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )


def private_file(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def calls(tmp_path: Path) -> list[str]:
    path = tmp_path / "calls.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_existing_private_token_is_idempotent_without_admin_or_gate(tmp_path: Path) -> None:
    token = private_file(tmp_path / "automation.token", "existing-secret")
    missing_admin = tmp_path / "missing-admin"

    result = run_mint(
        tmp_path,
        behavior="success",
        accept=False,
        token_path=token,
        admin_path=missing_admin,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert token.read_text(encoding="utf-8") == "existing-secret"
    assert calls(tmp_path) == []
    assert "no user or token POST was sent" in result.stdout


def test_mint_requires_explicit_acceptance_before_mutation(tmp_path: Path) -> None:
    admin = private_file(tmp_path / "admin.password", "admin-secret")
    result = run_mint(tmp_path, behavior="success", accept=False, admin_path=admin)

    assert result.returncode != 0
    assert "SOAR_ACCEPT_TOKEN_MINT_OR_ROTATION=true" in result.stdout + result.stderr
    assert calls(tmp_path) == []
    assert not (tmp_path / "automation.token").exists()

    existing = private_file(tmp_path / "automation.token", "existing-secret")
    rotation = run_mint(
        tmp_path,
        behavior="success",
        accept=False,
        rotate=True,
        admin_path=admin,
        token_path=existing,
    )
    assert rotation.returncode != 0
    assert existing.read_text(encoding="utf-8") == "existing-secret"
    assert calls(tmp_path) == []


def test_success_journals_before_post_and_rerun_does_not_remint(tmp_path: Path) -> None:
    admin = private_file(tmp_path / "admin.password", "admin-secret")
    token = tmp_path / "automation.token"
    first = run_mint(tmp_path, behavior="success", accept=True, admin_path=admin, token_path=token)

    assert first.returncode == 0, first.stdout + first.stderr
    assert token.read_text(encoding="utf-8") == "minted-secret-value"
    assert token.stat().st_mode & 0o777 == 0o600
    journal = Path(f"{token}.mint-state.json")
    state = json.loads(journal.read_text(encoding="utf-8"))
    assert state["status"] == "complete"
    assert state["manual_reconcile"] is False
    assert journal.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "observed-state").read_text(encoding="utf-8").strip() == "in_progress"
    assert calls(tmp_path).count("POST /rest/ph_user/42/token") == 1
    assert not list(tmp_path.glob(".soar-mint-work.*"))
    assert not Path(f"{journal}.lock").exists()

    second = run_mint(tmp_path, behavior="success", accept=False, admin_path=admin, token_path=token)
    assert second.returncode == 0, second.stdout + second.stderr
    assert calls(tmp_path).count("POST /rest/ph_user/42/token") == 1


@pytest.mark.parametrize("behavior", ["missing", "transport", "signal"])
def test_uncertain_mint_marks_ambiguous_and_blocks_retry(
    behavior: str, tmp_path: Path
) -> None:
    admin = private_file(tmp_path / "admin.password", "admin-secret")
    token = tmp_path / "automation.token"
    first = run_mint(tmp_path, behavior=behavior, accept=True, admin_path=admin, token_path=token)

    assert first.returncode != 0
    journal = Path(f"{token}.mint-state.json")
    state = json.loads(journal.read_text(encoding="utf-8"))
    assert state["status"] == "ambiguous"
    assert state["manual_reconcile"] is True
    assert not token.exists()
    assert not list(tmp_path.glob(".soar-mint-work.*"))
    posts = calls(tmp_path).count("POST /rest/ph_user/42/token")
    assert posts == 1

    retry = run_mint(tmp_path, behavior="success", accept=True, admin_path=admin, token_path=token)
    assert retry.returncode != 0
    assert "automatic retry is blocked" in retry.stdout + retry.stderr
    assert calls(tmp_path).count("POST /rest/ph_user/42/token") == posts


@pytest.mark.parametrize("behavior", ["symlink-race", "hardlink-race"])
def test_destination_link_race_never_overwrites_victim_and_becomes_ambiguous(
    behavior: str, tmp_path: Path
) -> None:
    admin = private_file(tmp_path / "admin.password", "admin-secret")
    token = tmp_path / "automation.token"
    victim = private_file(tmp_path / "victim", "preserve-me")
    result = run_mint(
        tmp_path,
        behavior=behavior,
        accept=True,
        admin_path=admin,
        token_path=token,
        extra_env={"VICTIM_FILE": str(victim)},
    )

    assert result.returncode != 0
    assert victim.read_text(encoding="utf-8") == "preserve-me"
    assert json.loads(Path(f"{token}.mint-state.json").read_text(encoding="utf-8"))[
        "status"
    ] == "ambiguous"


def test_rendered_automation_user_exposes_gate_rotation_and_journal_contract(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    result = subprocess.run(
        [
            "bash",
            str(SOAR_SETUP),
            "--phase",
            "render",
            "--soar-platform",
            "cloud",
            "--soar-tenant-url",
            "https://customer.splunkcloudgc.com/soar",
            "--output-dir",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    script = (output / "cloud/automation-user.sh").read_text(encoding="utf-8")
    assert "SOAR_ACCEPT_TOKEN_MINT_OR_ROTATION" in script
    assert "SOAR_ROTATE_AUTOMATION_TOKEN" in script
    assert "durable pre-POST journal" in script
    assert "descriptor-bound" in script
    syntax = subprocess.run(
        ["bash", "-n", str(output / "cloud/automation-user.sh")],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr
