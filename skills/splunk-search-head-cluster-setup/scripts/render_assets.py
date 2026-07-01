#!/usr/bin/env python3
"""Render Splunk Search Head Cluster assets.

Reads CLI args (from setup.sh) and emits the SHC rendered tree under
``--output-dir/shc/``:
- deployer/server.conf
- member-<host>/server.conf
- bootstrap/sequenced-bootstrap.sh
- bundle/{validate,status,apply,apply-skip-validation,rollback}.sh
- restart/{rolling-restart,searchable-rolling-restart,force-searchable,transfer-captain}.sh
- members/{add-member,decommission-member,remove-member}.sh
- kvstore/{status,reset-status}.sh
- migration/{standalone-to-shc,replace-deployer}.sh
- runbook-failure-modes.md
- validate.sh
- preflight-report.md
- handoffs/{license-peers.txt,es-deployer.txt,monitoring-console.txt}
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_NAME = "splunk-search-head-cluster-setup"
_HOST_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_./~+-]+$")


def _validate_host(value: str, option: str) -> str:
    if not _HOST_RE.fullmatch(value or ""):
        raise SystemExit(f"ERROR: {option} must be a hostname/IP token.")
    return value


def _validate_uri(value: str, option: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SystemExit(f"ERROR: {option} must be an http(s) management URI.")
    _validate_host(parsed.hostname, option)
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        raise SystemExit(f"ERROR: {option} must contain only scheme, host, and optional port.")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise SystemExit(f"ERROR: {option} has an invalid port: {exc}") from exc
    return value.rstrip("/")


def _positive_int(value: str, option: str) -> int:
    if not re.fullmatch(r"[0-9]+", value or "") or int(value) < 1:
        raise SystemExit(f"ERROR: {option} must be a positive integer.")
    return int(value)


def _lib_dir_block() -> str:
    """Locate skills/shared/lib at runtime so rendered scripts can mint a
    Splunk session key from the admin password file instead of putting the
    password on argv. Mirrors the splunk-license-manager-setup pattern."""
    return (
        '_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'LIB_DIR="${SKILLS_SHARED_LIB_DIR:-}"\n'
        'if [[ -z "${LIB_DIR}" ]]; then\n'
        '  for candidate in \\\n'
        '    "${_SCRIPT_DIR}/../../../../skills/shared/lib" \\\n'
        '    "${_SCRIPT_DIR}/../../../skills/shared/lib" \\\n'
        '    "${_SCRIPT_DIR}/../../skills/shared/lib"; do\n'
        '    if [[ -d "${candidate}" ]]; then\n'
        '      LIB_DIR="$(cd "${candidate}" && pwd)"\n'
        "      break\n"
        "    fi\n"
        "  done\n"
        "fi\n"
        'if [[ -z "${LIB_DIR}" || ! -d "${LIB_DIR}" ]]; then\n'
        '  echo "ERROR: Could not locate skills/shared/lib. Set SKILLS_SHARED_LIB_DIR=/path/to/skills/shared/lib." >&2\n'
        "  exit 1\n"
        "fi\n"
    )


def _rest_script_head(pw_file: str) -> str:
    """Shebang + lib sourcing + admin-password-file resolution. The password is
    handed to get_session_key_from_password_file / splunk_curl, which keep it
    off argv (no `-u admin:pw` and no password in `ps`)."""
    return (
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        + _lib_dir_block()
        + "# shellcheck disable=SC1091\n"
        'source "${LIB_DIR}/credential_helpers.sh"\n'
        'AUTH_USER="${SPLUNK_AUTH_USER:-admin}"\n'
        f'AUTH_PW_FILE="${{SPLUNK_ADMIN_PASSWORD_FILE:-{pw_file}}}"\n'
        'if [[ ! -s "${AUTH_PW_FILE}" ]]; then\n'
        '  echo "ERROR: Splunk admin password file is empty or missing: ${AUTH_PW_FILE}" >&2\n'
        "  exit 1\n"
        "fi\n"
    )


def _rolling_restart_script(pw_file: str, captain_uri: str, mode: str,
                            label: str, extra_guard: str = "") -> str:
    """Render a rolling-restart script that targets the REAL trigger.

    Sets the documented ``rolling_restart`` mode via ``shcluster/config/config``
    (restart | searchable | searchable_force), then POSTs the captain control
    ``restart`` endpoint — NOT ``restart_inactivity_timeout`` (which only sets a
    timeout and never restarts). Success is reported only on HTTP 200.
    """
    return (
        _rest_script_head(pw_file)
        + 'CAPTAIN_URI="${CAPTAIN_URI:-' + captain_uri + '}"\n'
        + 'if [[ -z "${CAPTAIN_URI}" ]]; then echo "ERROR: set CAPTAIN_URI to the current SHC captain management URI." >&2; exit 1; fi\n'
        + extra_guard
        + 'SK="$(get_session_key_from_password_file "${CAPTAIN_URI}" "${AUTH_PW_FILE}" "${AUTH_USER}")"\n'
        + "# Set the documented rolling_restart mode, then trigger the real\n"
        + "# rolling restart via the captain control endpoint.\n"
        + 'mode_code="$(splunk_curl_post "${SK}" "rolling_restart=' + mode + '" \\\n'
        + "  -o /dev/null -w '%{http_code}' \\\n"
        + '  "${CAPTAIN_URI}/services/shcluster/config/config")"\n'
        + 'if [[ ! "${mode_code}" =~ ^2[0-9][0-9]$ ]]; then\n'
        + '  echo "ERROR: failed to set rolling_restart=' + mode + ' (HTTP ${mode_code})." >&2\n'
        + "  exit 1\n"
        + "fi\n"
        + 'rr_code="$(splunk_curl_post "${SK}" "" \\\n'
        + "  -o /dev/null -w '%{http_code}' \\\n"
        + '  "${CAPTAIN_URI}/services/shcluster/captain/control/control/restart")"\n'
        + 'if [[ ! "${rr_code}" =~ ^2[0-9][0-9]$ ]]; then\n'
        + '  echo "ERROR: ' + label + ' request failed (HTTP ${rr_code})." >&2\n'
        + "  exit 1\n"
        + "fi\n"
        + 'echo "' + label + ' initiated (HTTP ${rr_code}). Monitor cluster status before further changes."\n'
    )


def render(args: argparse.Namespace) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    out = Path(args.output_dir)
    shc = out / "shc"

    if not _IDENTIFIER_RE.fullmatch(args.shc_label or ""):
        raise SystemExit("ERROR: --shc-label contains unsupported characters.")
    shc_label = args.shc_label
    deployer_host = _validate_host(
        args.deployer_host or "deployer01.example.com", "--deployer-host"
    )
    deployer_uri = _validate_uri(
        args.deployer_uri or f"https://{deployer_host}:8089", "--deployer-uri"
    )
    members_raw = args.member_hosts or ""
    members = [
        _validate_host(m.strip(), "--member-hosts")
        for m in members_raw.split(",")
        if m.strip()
    ]
    if len(members) != len(set(members)):
        raise SystemExit("ERROR: --member-hosts contains duplicates.")
    rf = _positive_int(args.replication_factor, "--replication-factor")
    kvstore_rf = _positive_int(
        args.kvstore_replication_factor, "--kvstore-replication-factor"
    )
    kvstore_port = str(_positive_int(args.kvstore_port, "--kvstore-port"))
    if int(kvstore_port) > 65535:
        raise SystemExit("ERROR: --kvstore-port cannot exceed 65535.")
    hb_timeout = str(_positive_int(args.heartbeat_timeout, "--heartbeat-timeout"))
    hb_period = str(_positive_int(args.heartbeat_period, "--heartbeat-period"))
    restart_timeout = str(
        _positive_int(args.restart_inactivity_timeout, "--restart-inactivity-timeout")
    )
    if rf < 3 or kvstore_rf < 3:
        raise SystemExit(
            "ERROR: SHC and KV Store replication factors must both be at least 3."
        )
    if members and (
        len(members) < 3 or rf > len(members) or kvstore_rf > len(members)
    ):
        raise SystemExit(
            "ERROR: a rendered member inventory needs at least three unique members "
            "and cannot be smaller than either replication factor."
        )
    if int(hb_period) >= int(hb_timeout):
        raise SystemExit("ERROR: --heartbeat-period must be less than --heartbeat-timeout.")
    for value, option in (
        (args.new_member_host, "--new-member-host"),
        (args.existing_sh_host, "--existing-sh-host"),
    ):
        if value:
            _validate_host(value, option)
    for value in (item.strip() for item in args.additional_member_hosts.split(",")):
        if value:
            _validate_host(value, "--additional-member-hosts")
    if args.member_host and not _IDENTIFIER_RE.fullmatch(args.member_host):
        raise SystemExit("ERROR: --member-guid contains unsupported characters.")
    for value, option in (
        (args.captain_uri, "--captain-uri"),
        (args.target_captain_uri, "--target-captain-uri"),
        (args.member_uri, "--member-uri"),
    ):
        if value:
            _validate_uri(value, option)
    for value, option in (
        (args.admin_password_file, "--admin-password-file"),
        (args.shc_secret_file, "--shc-secret-file"),
    ):
        if value and not _SAFE_PATH_RE.fullmatch(value):
            raise SystemExit(f"ERROR: {option} contains unsupported characters.")
    # Admin password file baked as the default for rendered REST scripts
    # (still overridable at runtime via SPLUNK_ADMIN_PASSWORD_FILE).
    pw_file = args.admin_password_file or "/tmp/splunk_admin_password"
    # The deployer is not an SHC member, and the first listed member is not
    # necessarily the current captain. Captain-scoped actions therefore require
    # an explicit URI instead of guessing from inventory order.
    captain_uri = args.captain_uri or ""
    target_captain_uri = args.target_captain_uri or ""

    # Create directory structure
    for subdir in [
        shc / "deployer",
        shc / "bootstrap",
        shc / "bundle",
        shc / "restart",
        shc / "members",
        shc / "kvstore",
        shc / "migration",
        shc / "handoffs",
    ]:
        subdir.mkdir(parents=True, exist_ok=True)

    for m in members:
        (shc / f"member-{m}").mkdir(parents=True, exist_ok=True)

    # deployer/server.conf
    (shc / "deployer" / "server.conf").write_text(
        "[shclustering]\n"
        "disabled = false\n"
        f"pass4SymmKey = $SHC_SECRET\n"
        f"shcluster_label = {shc_label}\n",
        encoding="utf-8",
    )

    # member server.conf files
    for m in members:
        (shc / f"member-{m}" / "server.conf").write_text(
            "[shclustering]\n"
            "disabled = false\n"
            f"conf_deploy_fetch_url = {deployer_uri}\n"
            f"shcluster_label = {shc_label}\n"
            f"replication_factor = {rf}\n"
            f"pass4SymmKey = $SHC_SECRET\n"
            f"heartbeat_timeout = {hb_timeout}\n"
            f"heartbeat_period = {hb_period}\n"
            f"restart_inactivity_timeout = {restart_timeout}\n\n"
            f"[kvstore]\n"
            f"disabled = false\n"
            f"replication_factor = {kvstore_rf}\n"
            f"port = {kvstore_port}\n",
            encoding="utf-8",
        )

    # bootstrap/sequenced-bootstrap.sh
    first_captain = members[0] if members else "sh01.example.com"
    (shc / "bootstrap" / "sequenced-bootstrap.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n\n"
        "cat >&2 <<'HANDOFF'\n"
        "HANDOFF: SHC bootstrap is CLI-only and requires both admin authentication\n"
        "and pass4SymmKey. This helper refuses to expand either secret into CLI/SSH\n"
        "arguments. Establish an interactive local `splunk login` as the Splunk OS\n"
        "user on every member, then run `splunk init shcluster-config` interactively\n"
        "with the reviewed values from member-*/server.conf. Finally run\n"
        f"`splunk bootstrap shcluster-captain` interactively on {first_captain}.\n"
        "HANDOFF\n"
        "exit 2\n",
        encoding="utf-8",
    )

    # bundle scripts
    for script, cmd in [
        ("validate.sh", "splunk validate shcluster-bundle"),
        ("status.sh", "splunk show shcluster-bundle-status"),
        ("apply.sh", "splunk apply shcluster-bundle --answer-yes"),
        ("apply-skip-validation.sh", "splunk apply shcluster-bundle --answer-yes --skip-validation"),
    ]:
        (shc / "bundle" / script).write_text(
            f"#!/usr/bin/env bash\nset -euo pipefail\n# Run on deployer host\n"
            "# Requires an existing local Splunk CLI login for the splunk OS user;\n"
            "# no password is accepted on argv.\n"
            f"ssh splunk@{deployer_host} 'sudo -u splunk /opt/splunk/bin/{cmd}'\n",
            encoding="utf-8",
        )
    (shc / "bundle" / "rollback.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "echo 'HANDOFF: restore a reviewed etc/shcluster/apps backup, validate it, then run bundle/apply.sh.' >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )

    # restart scripts (REST against the SHC captain; auth via session key so
    # the admin password never lands on argv / `ps`).
    (shc / "restart" / "rolling-restart.sh").write_text(
        _rolling_restart_script(pw_file, captain_uri, "restart", "Rolling restart"),
        encoding="utf-8",
    )
    (shc / "restart" / "searchable-rolling-restart.sh").write_text(
        _rolling_restart_script(pw_file, captain_uri, "searchable",
                                "Searchable rolling restart"),
        encoding="utf-8",
    )
    force_guard = (
        '# Forced searchable restart overrides cluster health checks. Require\n'
        '# explicit confirmation so this never runs by accident.\n'
        'if [[ "${ACCEPT_FORCE_RESTART:-false}" != "true" ]]; then\n'
        '  echo "ERROR: forced restart overrides health checks. Re-run with ACCEPT_FORCE_RESTART=true to proceed." >&2\n'
        "  exit 1\n"
        "fi\n"
    )
    (shc / "restart" / "force-searchable.sh").write_text(
        _rolling_restart_script(pw_file, captain_uri, "searchable_force",
                                "Forced searchable rolling restart",
                                extra_guard=force_guard),
        encoding="utf-8",
    )
    # Captain transfer is CLI-only. Rely on a pre-existing local CLI session;
    # never expand the password file into -auth.
    (shc / "restart" / "transfer-captain.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Transfer the SHC captain to TARGET via the documented CLI\n"
        "# (splunk transfer shcluster-captain -mgmt_uri <TARGET>). Run on a member.\n"
        'SPLUNK_BIN="${SPLUNK_BIN:-/opt/splunk/bin/splunk}"\n'
        'TARGET="${TARGET:-' + target_captain_uri + '}"\n'
        'if [[ -z "${TARGET}" ]]; then echo "Set TARGET=https://sh0X:8089 (or pass --target-captain-uri at render time)." >&2; exit 1; fi\n'
        'if ! "${SPLUNK_BIN}" transfer shcluster-captain -mgmt_uri "${TARGET}"; then\n'
        '  echo "ERROR: captain transfer failed. Run splunk login interactively as the local Splunk OS user, then retry." >&2\n'
        '  exit 2\n'
        'fi\n'
        'echo "Captain transfer to ${TARGET} requested. Verify: splunk show shcluster-status"\n',
        encoding="utf-8",
    )

    # member scripts
    (shc / "members" / "add-member.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"NEW_MEMBER=\"${{NEW_MEMBER:-{args.new_member_host}}}\"\n"
        "if [[ -z \"${NEW_MEMBER}\" ]]; then echo 'ERROR: set NEW_MEMBER to the prepared host.' >&2; exit 1; fi\n"
        "cat >&2 <<'HANDOFF'\n"
        "HANDOFF: adding a member requires CLI-only init with an admin login and\n"
        "pass4SymmKey. Establish an interactive local Splunk CLI session on the new\n"
        "member and run `splunk init shcluster-config` using the reviewed server.conf\n"
        "values. This helper will not put either secret in argv or an SSH command.\n"
        "HANDOFF\n"
        "exit 2\n",
        encoding="utf-8",
    )
    (shc / "members" / "decommission-member.sh").write_text(
        _rest_script_head(pw_file)
        + "# Gracefully decommission a member (moves to GracefulShutdown).\n"
        + 'CAPTAIN_URI="${CAPTAIN_URI:-' + captain_uri + '}"\n'
        + 'MEMBER_UUID="${MEMBER_UUID:-' + args.member_host + '}"\n'
        + 'if [[ -z "${CAPTAIN_URI}" ]]; then echo "Set CAPTAIN_URI to the current captain." >&2; exit 1; fi\n'
        + 'if [[ -z "${MEMBER_UUID}" ]]; then echo "Set MEMBER_UUID from splunk list shcluster-members" >&2; exit 1; fi\n'
        + 'SK="$(get_session_key_from_password_file "${CAPTAIN_URI}" "${AUTH_PW_FILE}" "${AUTH_USER}")"\n'
        + 'splunk_curl_post "${SK}" "" --fail-with-body --show-error \\\n'
        + '  "${CAPTAIN_URI}/services/shcluster/member/members/${MEMBER_UUID}/control/control/graceful_shutdown"\n',
        encoding="utf-8",
    )
    (shc / "members" / "remove-member.sh").write_text(
        _rest_script_head(pw_file)
        + "# Administrative removal after decommission.\n"
        + 'CAPTAIN_URI="${CAPTAIN_URI:-' + captain_uri + '}"\n'
        + 'MEMBER_UUID="${MEMBER_UUID:-' + args.member_host + '}"\n'
        + 'if [[ -z "${CAPTAIN_URI}" ]]; then echo "Set CAPTAIN_URI to the current captain." >&2; exit 1; fi\n'
        + 'if [[ -z "${MEMBER_UUID}" ]]; then echo "Set MEMBER_UUID from splunk list shcluster-members" >&2; exit 1; fi\n'
        + 'SK="$(get_session_key_from_password_file "${CAPTAIN_URI}" "${AUTH_PW_FILE}" "${AUTH_USER}")"\n'
        + 'splunk_curl "${SK}" --fail-with-body --show-error -X DELETE \\\n'
        + '  "${CAPTAIN_URI}/services/shcluster/member/members/${MEMBER_UUID}"\n',
        encoding="utf-8",
    )

    # kvstore scripts
    (shc / "kvstore" / "status.sh").write_text(
        _rest_script_head(pw_file)
        + 'CAPTAIN_URI="${CAPTAIN_URI:-' + captain_uri + '}"\n'
        + 'if [[ -z "${CAPTAIN_URI}" ]]; then echo "Set CAPTAIN_URI to the current captain." >&2; exit 1; fi\n'
        + 'SK="$(get_session_key_from_password_file "${CAPTAIN_URI}" "${AUTH_PW_FILE}" "${AUTH_USER}")"\n'
        + 'splunk_curl "${SK}" --fail-with-body --show-error \\\n'
        + '  "${CAPTAIN_URI}/services/kvstore/status?output_mode=json" | python3 -m json.tool\n',
        encoding="utf-8",
    )
    (shc / "kvstore" / "reset-status.sh").write_text(
        _rest_script_head(pw_file)
        + "# DANGER: Forces full KV Store re-sync on this member. Use only when replication is stuck.\n"
        + "# Requires --accept-kvstore-reset passed to setup.sh.\n"
        + 'MEMBER_URI="${MEMBER_URI:-' + args.member_uri + '}"\n'
        + 'if [[ -z "${MEMBER_URI}" ]]; then echo "Set MEMBER_URI=https://sh0X:8089" >&2; exit 1; fi\n'
        + 'SK="$(get_session_key_from_password_file "${MEMBER_URI}" "${AUTH_PW_FILE}" "${AUTH_USER}")"\n'
        + 'splunk_curl_post "${SK}" "" --fail-with-body --show-error \\\n'
        + '  "${MEMBER_URI}/services/kvstore/control/control/reset"\n',
        encoding="utf-8",
    )

    # migration scripts
    (shc / "migration" / "standalone-to-shc.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Convert a standalone search head to an SHC member.\n"
        "# Prerequisites: install Splunk on additional members; have the SHC secret ready.\n"
        "echo 'HANDOFF: see reference.md for the standalone-to-SHC migration checklist; no hosts were changed.' >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )
    (shc / "migration" / "replace-deployer.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Replace the SHC deployer with a new instance.\n"
        "echo 'Steps: install Splunk on new deployer; copy etc/shcluster/apps/;'\n"
        "echo '  update conf_deploy_fetch_url on all members; restart members.' >&2\n"
        "echo 'HANDOFF: deployer replacement requires reviewed host and bundle transfer details; no changes were made.' >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )

    # validate.sh
    (shc / "validate.sh").write_text(
        _rest_script_head(pw_file)
        + 'CAPTAIN_URI="${CAPTAIN_URI:-' + captain_uri + '}"\n'
        + 'if [[ -z "${CAPTAIN_URI}" ]]; then echo "Set CAPTAIN_URI to the current captain." >&2; exit 1; fi\n'
        + 'SK="$(get_session_key_from_password_file "${CAPTAIN_URI}" "${AUTH_PW_FILE}" "${AUTH_USER}")"\n'
        + 'echo "=== SHC Captain Info ==="\n'
        + 'splunk_curl "${SK}" --fail-with-body --show-error \\\n'
        + '  "${CAPTAIN_URI}/services/shcluster/captain/info?output_mode=json" | python3 -m json.tool\n'
        + 'echo "=== KV Store Status ==="\n'
        + 'splunk_curl "${SK}" --fail-with-body --show-error \\\n'
        + '  "${CAPTAIN_URI}/services/kvstore/status?output_mode=json" | python3 -m json.tool\n',
        encoding="utf-8",
    )

    # preflight-report.md
    member_count = len(members)
    quorum = member_count // 2 + 1
    (shc / "preflight-report.md").write_text(
        f"# SHC Preflight Report\n\n"
        f"Generated: {now}\n\n"
        f"| Check | Value | Status |\n|-------|-------|--------|\n"
        f"| SHC label | `{shc_label}` | OK |\n"
        f"| Member count | {member_count} | {'OK' if member_count >= 3 else 'FAIL: minimum 3 members required'} |\n"
        f"| Replication factor | {rf} | {'OK' if rf <= member_count else 'FAIL: RF > member count'} |\n"
        f"| Quorum (N/2+1) | {quorum} | OK |\n"
        f"| KV Store RF | {kvstore_rf} | OK |\n"
        f"| KV Store port | {kvstore_port} | OK |\n",
        encoding="utf-8",
    )

    # runbook-failure-modes.md
    (shc / "runbook-failure-modes.md").write_text(
        "# SHC Failure Mode Runbooks\n\n"
        "## Split-Brain (Two Captains)\n\nRestore network partition. "
        "Older captain steps down on heartbeat recovery, or run `transfer-captain.sh`.\n\n"
        "## Quorum Loss\n\nBring members back online to restore N/2+1. "
        "Until quorum is restored, KV Store is read-only.\n\n"
        "## Deployer Mismatch (Divergent Bundle Generations)\n\nRe-run `bundle/apply.sh`. "
        "Use `bundle/apply-skip-validation.sh` only if the bundle validator is blocking.\n\n"
        "## Captain Crash Loop\n\nRun `restart/transfer-captain.sh` to promote a stable member. "
        "Then investigate the problematic captain's `splunkd.log`.\n\n"
        "## KV Store Stuck Replication\n\nCheck lag via `kvstore/status.sh`. "
        "If lag is stuck > 60 s, run `kvstore/reset-status.sh` on the lagging member with `--accept-kvstore-reset`.\n",
        encoding="utf-8",
    )

    # handoffs
    (shc / "handoffs" / "license-peers.txt").write_text(
        f"# SHC member license peer handoff\n"
        f"# Pass to: bash skills/splunk-license-manager-setup/scripts/setup.sh\n"
        f"DEPLOYER_URI={deployer_uri}\n"
        + "".join(f"MEMBER_{i+1}=https://{m}:8089\n" for i, m in enumerate(members)),
        encoding="utf-8",
    )
    (shc / "handoffs" / "es-deployer.txt").write_text(
        f"# ES deployer handoff\n"
        f"# Pass to: bash skills/splunk-enterprise-security-install/scripts/setup.sh\n"
        f"DEPLOYER_URI={deployer_uri}\n"
        f"DEPLOYER_HOST={deployer_host}\n"
        f"SHC_LABEL={shc_label}\n",
        encoding="utf-8",
    )
    (shc / "handoffs" / "monitoring-console.txt").write_text(
        f"# Monitoring Console handoff\n"
        f"# Pass to: bash skills/splunk-monitoring-console-setup/scripts/setup.sh\n"
        f"DEPLOYER_URI={deployer_uri}\n"
        + "".join(f"MEMBER_{i+1}=https://{m}:8089\n" for i, m in enumerate(members)),
        encoding="utf-8",
    )

    # Make all scripts executable
    for path in shc.rglob("*.sh"):
        path.chmod(0o755)

    result = {
        "output_dir": str(out.resolve()),
        "shc_label": shc_label,
        "deployer_host": deployer_host,
        "members": members,
        "replication_factor": rf,
        "kvstore_replication_factor": kvstore_rf,
        "rendered_files": [str(p.relative_to(out)) for p in sorted(out.rglob("*")) if p.is_file()],
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{SKILL_NAME} renderer")
    parser.add_argument("--phase", default="render")
    parser.add_argument("--output-dir",
                        default=str(PROJECT_ROOT / "splunk-search-head-cluster-rendered"))
    parser.add_argument("--shc-label", default="prod_shc")
    parser.add_argument("--deployer-host", default="")
    parser.add_argument("--deployer-uri", default="")
    parser.add_argument("--member-hosts", default="")
    parser.add_argument("--replication-factor", default="3")
    parser.add_argument("--kvstore-replication-factor", default="3")
    parser.add_argument("--kvstore-port", default="8191")
    parser.add_argument("--heartbeat-timeout", default="60")
    parser.add_argument("--heartbeat-period", default="5")
    parser.add_argument("--restart-inactivity-timeout", default="600")
    parser.add_argument("--rolling-restart-mode", default="searchable")
    parser.add_argument("--captain-uri", default="")
    parser.add_argument("--target-captain-uri", default="")
    parser.add_argument("--new-member-host", default="")
    parser.add_argument("--member-host", default="")
    parser.add_argument("--member-uri", default="")
    parser.add_argument("--existing-sh-host", default="")
    parser.add_argument("--additional-member-hosts", default="")
    parser.add_argument("--admin-password-file", default="")
    parser.add_argument("--shc-secret-file", default="")
    parser.add_argument("--accept-skip-validation", action="store_true")
    parser.add_argument("--accept-kvstore-reset", action="store_true")
    parser.add_argument("--accept-force-restart", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = render(args)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Rendered to: {result['output_dir']}")
        print(f"SHC label:   {result['shc_label']}")
        print(f"Members:     {', '.join(result.get('members', []))}")
        print(f"Files:       {len(result.get('rendered_files', []))}")


if __name__ == "__main__":
    main()
