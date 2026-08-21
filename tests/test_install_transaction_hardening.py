#!/usr/bin/env python3
"""Focused regressions for exact-version and transactional app installation."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

from tests.regression_helpers import REPO_ROOT, write_executable


BATCH_INSTALL = REPO_ROOT / "skills/shared/scripts/cloud_batch_install.sh"
GENERIC_INSTALL = REPO_ROOT / "skills/splunk-app-install/scripts/install_app.sh"


def build_batch_env(tmp_path: Path, mode: str) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    acs_log = tmp_path / "acs.log"
    state_file = tmp_path / "state.json"
    credentials = tmp_path / "credentials"
    state_file.write_text("{}\n", encoding="utf-8")

    write_executable(
        bin_dir / "acs",
        """\
        #!/usr/bin/env python3
        import json
        import os
        import sys
        from pathlib import Path

        args = sys.argv[1:]
        cmd = " ".join(args)
        log_path = Path(os.environ["ACS_LOG"])
        state_path = Path(os.environ["ACS_STATE"])
        mode = os.environ["ACS_MODE"]
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(cmd + "\\n")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        apps = {
            "7538": ("TA_cisco_catalyst", "3.2.44"),
            "7539": ("cisco-catalyst-app", "3.2.20"),
        }

        if "config current-stack" in cmd:
            print("Current Search Head: sh-i-transaction")
            raise SystemExit(0)

        if "apps list" in cmd:
            records = [
                {
                    "name": name,
                    "splunkbaseID": app_id,
                    "version": item["version"],
                    "status": item["status"],
                }
                for app_id, item in state.items()
                for name, _ in [apps[app_id]]
            ]
            print(json.dumps({"apps": records}))
            raise SystemExit(0)

        if "apps describe " in cmd:
            name = cmd.split("apps describe ", 1)[1].strip()
            app_id = next(key for key, value in apps.items() if value[0] == name)
            item = state.get(app_id)
            if item is None:
                raise SystemExit(1)
            print(json.dumps({"name": name, "version": item["version"], "status": item["status"]}))
            raise SystemExit(0)

        if "apps install splunkbase --splunkbase-id " in cmd:
            app_id = cmd.split("apps install splunkbase --splunkbase-id ", 1)[1].split()[0]
            expected = cmd.split(" --version ", 1)[1].split()[0]
            name, _ = apps[app_id]
            if mode == "compensate" and app_id == "7539":
                print(json.dumps({"statusCode": 500}), file=sys.stderr)
                raise SystemExit(2)
            if mode == "conflict-wrong":
                state[app_id] = {"version": "9.9.9", "status": "installed"}
            else:
                state[app_id] = {"version": expected, "status": "installed"}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            if mode.startswith("conflict"):
                print(json.dumps({"statusCode": 409}), file=sys.stderr)
                raise SystemExit(2)
            print(json.dumps({"name": name, "version": expected, "status": "installed"}))
            raise SystemExit(0)

        if "apps uninstall " in cmd:
            name = cmd.split("apps uninstall ", 1)[1].split()[0]
            app_id = next(key for key, value in apps.items() if value[0] == name)
            state.pop(app_id, None)
            state_path.write_text(json.dumps(state), encoding="utf-8")
            print(json.dumps({"name": name, "status": "deleted"}))
            raise SystemExit(0)

        if "restart current-stack" in cmd or "status current-stack" in cmd:
            raise SystemExit(97)
        raise SystemExit(0)
        """,
    )
    credentials.write_text(
        textwrap.dedent(
            """\
            SPLUNK_PLATFORM="cloud"
            SPLUNK_CLOUD_STACK="example-stack"
            SPLUNK_CLOUD_SEARCH_HEAD="sh-i-transaction"
            ACS_SERVER="https://staging.admin.splunk.com"
            STACK_TOKEN="token"
            """
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "ACS_LOG": str(acs_log),
            "ACS_STATE": str(state_file),
            "ACS_MODE": mode,
            "SPLUNK_CREDENTIALS_FILE": str(credentials),
            "SPLUNK_BATCH_RECOVERY_DIR": str(tmp_path),
            "SPLUNK_ACS_APP_VERIFY_ATTEMPTS": "1",
            "SPLUNK_ACS_APP_VERIFY_INTERVAL": "0",
        }
    )
    return env, acs_log, state_file


def run_batch(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(BATCH_INSTALL), "--no-restart", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_409_is_accepted_only_after_exact_terminal_version_is_proven(tmp_path: Path) -> None:
    env, acs_log, _ = build_batch_env(tmp_path, "conflict-exact")
    result = run_batch(env, "7538")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "409 accepted" in output
    assert "--splunkbase-id 7538 --version 3.2.44" in acs_log.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("splunk-cloud-batch-recovery.*"))


def test_409_wrong_version_fails_closed_with_recovery_evidence(tmp_path: Path) -> None:
    env, acs_log, _ = build_batch_env(tmp_path, "conflict-wrong")
    result = run_batch(env, "7538")
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "version 9.9.9, expected 3.2.44" in output
    assert "apps uninstall" not in acs_log.read_text(encoding="utf-8")
    evidence = list(tmp_path.glob("splunk-cloud-batch-recovery.*"))
    assert len(evidence) == 1
    assert stat.S_IMODE(evidence[0].stat().st_mode) == 0o600


def test_batch_stops_and_reverse_compensates_without_restart(tmp_path: Path) -> None:
    env, acs_log, state_file = build_batch_env(tmp_path, "compensate")
    result = run_batch(env, "7539")
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "Rollback verified for TA_cisco_catalyst" in output
    assert json.loads(state_file.read_text(encoding="utf-8")) == {}
    commands = acs_log.read_text(encoding="utf-8")
    assert commands.index("--splunkbase-id 7538") < commands.index("--splunkbase-id 7539")
    assert "apps uninstall TA_cisco_catalyst" in commands
    assert "restart current-stack" not in commands
    evidence = list(tmp_path.glob("splunk-cloud-batch-recovery.*"))
    assert len(evidence) == 1
    journal = [json.loads(line) for line in evidence[0].read_text(encoding="utf-8").splitlines()]
    assert any(item["event"] == "rollback-verified" for item in journal)
    assert any(item["event"] == "batch-failed-compensated" for item in journal)


def test_id_version_and_remote_transport_contracts_are_explicit() -> None:
    batch = BATCH_INSTALL.read_text(encoding="utf-8")
    installer = GENERIC_INSTALL.read_text(encoding="utf-8")

    assert "must be a positive numeric ID" in batch
    assert "requires an explicit --version" in batch
    assert "requires an explicit --app-version" in installer
    assert "curl -q -sS --location --max-redirs 3" in installer
    assert "--proto '=https' --proto-redir '=https'" in installer
    assert 'credential_curl_validate_url "${effective_url}" false' in installer
    assert "Ignoring unverified cached package and redownloading exact Splunkbase release" in installer
