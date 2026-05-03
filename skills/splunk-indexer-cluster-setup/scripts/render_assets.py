#!/usr/bin/env python3
"""Render Splunk indexer cluster assets for single-site, multisite, and ops phases."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path
from urllib.parse import urlparse


VALID_CLUSTER_MODES = ("single-site", "multisite")
VALID_SWITCHOVER = ("auto", "manual", "disabled")
VALID_ROLLING_DEFAULTS = ("searchable_force", "searchable", "shutdown", "restart")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render Splunk indexer cluster assets.")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--cluster-mode", choices=VALID_CLUSTER_MODES, default="single-site")
    p.add_argument("--cluster-label", default="prod")
    p.add_argument("--cluster-manager-uri", required=True)
    p.add_argument("--manager-hosts", default="")
    p.add_argument("--manager-ssh-user", default="splunk")
    p.add_argument("--manager-redundancy", choices=("true", "false"), default="false")
    p.add_argument("--manager-switchover-mode", choices=VALID_SWITCHOVER, default="disabled")
    p.add_argument("--manager-lb-uri", default="")
    p.add_argument("--manager-dns-name", default="")
    p.add_argument("--replication-factor", default="3")
    p.add_argument("--search-factor", default="2")
    p.add_argument("--available-sites", default="")
    p.add_argument("--site-replication-factor", default="origin:2,total:3")
    p.add_argument("--site-search-factor", default="origin:1,total:2")
    p.add_argument("--site-mappings", default="")
    p.add_argument("--peer-hosts", default="")
    p.add_argument("--sh-hosts", default="")
    p.add_argument("--forwarder-hosts", default="")
    p.add_argument("--peer-ssh-user", default="splunk")
    p.add_argument("--sh-ssh-user", default="splunk")
    p.add_argument("--replication-port", default="9887")
    p.add_argument("--percent-peers-to-restart", default="10")
    p.add_argument("--rolling-restart-default", choices=VALID_ROLLING_DEFAULTS, default="searchable")
    p.add_argument("--indexer-discovery-tag", default="idxc_main")
    p.add_argument("--migrate-keep-legacy-factors", choices=("true", "false"), default="true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


# Hostnames are interpolated into rendered file PATHS like
# `cluster/peer-{host}/server.conf`. Without validation, a value like
# `../../etc/passwd` could redirect a write outside the operator's chosen
# output directory. We accept only DNS-style labels plus dot, underscore,
# hyphen, and digits — the same character class real Splunk peer hosts
# use. Anything else is rejected up front.
_HOST_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_host_token(host: str, kind: str) -> str:
    if not host or not _HOST_RE.fullmatch(host):
        die(
            f"--{kind} value {host!r} is not a valid hostname/IP token "
            "(allowed characters: letters, digits, '.', '_', '-')."
        )
    return host


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


def parse_host_site_pairs(value: str, kind: str, multisite: bool) -> list[dict]:
    items = []
    for entry in csv_list(value):
        if "=" in entry:
            host, site = entry.split("=", 1)
            host = validate_host_token(host.strip(), kind)
            site = site.strip()
            if not site or not re.fullmatch(r"site[0-9]+", site):
                die(f"--{kind} site value must be siteN: {entry!r}")
            items.append({"host": host, "site": site})
        else:
            if multisite:
                die(f"--{kind} multisite entries require host=siteN: {entry!r}")
            items.append({"host": validate_host_token(entry, kind), "site": None})
    return items


def parse_uri(uri: str, option: str) -> tuple[str, int]:
    parsed = urlparse(uri)
    if parsed.scheme not in ("http", "https"):
        die(f"{option} must be http(s)://host:port: {uri!r}")
    if not parsed.hostname:
        die(f"{option} must include a host: {uri!r}")
    return parsed.hostname, parsed.port or 8089


def helper_path() -> Path:
    """Path to credential_helpers.sh used by the bootstrap script.

    Most of the rendered scripts now use `_CLUSTER_LIB_DIR_BLOCK` to
    discover skills/shared/lib at runtime, but the bootstrap script still
    sources credential_helpers.sh by absolute path through this function
    because it is generated with a known render-tree layout.
    """
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "skills/shared/lib/credential_helpers.sh"


def render_manager_server_conf(args: argparse.Namespace, host: str, multisite: bool, sites: list[str], peer_count_per_site: dict, manager_index: int = 0, manager_uris: list[str] | None = None) -> str:
    lines = [
        "# Rendered by splunk-indexer-cluster-setup. Review before applying.",
        "[general]",
    ]
    if multisite:
        # Place the manager on the first site by default.
        primary_site = sites[0] if sites else "site1"
        lines.append(f"site = {primary_site}")
    lines.append("")
    lines.append("[clustering]")
    lines.append("mode = manager")
    lines.append(f"cluster_label = {args.cluster_label}")
    lines.append("pass4SymmKey = $IDXC_SECRET")
    lines.append(f"rolling_restart = {args.rolling_restart_default}")
    lines.append(f"percent_peers_to_restart = {args.percent_peers_to_restart}")
    if multisite:
        lines.append("multisite = true")
        lines.append(f"available_sites = {','.join(sites)}")
        lines.append(f"site_replication_factor = {args.site_replication_factor}")
        lines.append(f"site_search_factor = {args.site_search_factor}")
        # Per Splunk doc: the legacy single-site factors must remain valid for
        # legacy buckets — set them to the smallest per-site peer count if the
        # operator isn't migrating, or pass-through their --replication-factor
        # / --search-factor.
        lines.append(f"replication_factor = {args.replication_factor}")
        lines.append(f"search_factor = {args.search_factor}")
        if args.site_mappings:
            lines.append(f"site_mappings = {args.site_mappings}")
    else:
        lines.append(f"replication_factor = {args.replication_factor}")
        lines.append(f"search_factor = {args.search_factor}")

    if args.manager_redundancy == "true" and manager_uris and len(manager_uris) > 1:
        lines.append(f"manager_switchover_mode = {args.manager_switchover_mode}")
        lines.append("manager_uri = " + ",".join(f"clustermanager:cm{i+1}" for i in range(len(manager_uris))))
        lines.append("")
        for idx, uri in enumerate(manager_uris):
            lines.append(f"[clustermanager:cm{idx+1}]")
            lines.append(f"manager_uri = {uri}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _peer_facing_manager_uri(args: argparse.Namespace) -> str:
    """When manager redundancy is enabled, peers and SHs must reference the
    LB or DNS endpoint, not a single manager hostname. Falls back to the
    cluster-manager URI when redundancy is off.
    """
    if args.manager_redundancy == "true":
        if args.manager_lb_uri:
            return args.manager_lb_uri
        if args.manager_dns_name:
            return f"https://{args.manager_dns_name}:8089"
    return args.cluster_manager_uri


def render_peer_server_conf(args: argparse.Namespace, peer: dict, multisite: bool, manager_endpoint: str) -> str:
    lines = ["# Rendered by splunk-indexer-cluster-setup. Review before applying.", "[general]"]
    if multisite and peer.get("site"):
        lines.append(f"site = {peer['site']}")
    lines.append("")
    lines.append(f"[replication_port://{args.replication_port}]")
    lines.append("")
    lines.append("[clustering]")
    lines.append(f"manager_uri = {manager_endpoint}")
    lines.append("mode = peer")
    lines.append("pass4SymmKey = $IDXC_SECRET")
    return "\n".join(lines) + "\n"


def render_sh_server_conf(args: argparse.Namespace, sh: dict, multisite: bool, manager_endpoint: str) -> str:
    lines = ["# Rendered by splunk-indexer-cluster-setup. Review before applying.", "[general]"]
    if multisite:
        site = sh.get("site") or "site0"  # site0 disables affinity if unspecified
        lines.append(f"site = {site}")
    lines.append("")
    lines.append("[clustering]")
    if multisite:
        lines.append("multisite = true")
    lines.append(f"manager_uri = {manager_endpoint}")
    lines.append("mode = searchhead")
    lines.append("pass4SymmKey = $IDXC_SECRET")
    return "\n".join(lines) + "\n"


def render_bootstrap(args: argparse.Namespace, manager_hosts: list[str], peer_entries: list[dict], sh_entries: list[dict], multisite: bool) -> str:
    helper = shell_quote(helper_path())
    expected_peers = len(peer_entries)
    cluster_uri = shell_quote(args.cluster_manager_uri)
    # Prefer the documented REST endpoint over `splunk list cluster-peers`
    # output parsing — the former returns structured JSON, the latter is a
    # CLI table whose format can drift between releases.
    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
# Locate skills/shared/lib for the post-bootstrap REST probe (peer-count
# wait loop uses splunk_curl + a session key minted via the password file,
# never a curl -u "admin:pw" with the password on argv).
_BOOTSTRAP_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
LIB_DIR_FOR_BOOTSTRAP="${{SKILLS_SHARED_LIB_DIR:-}}"
if [[ -z "${{LIB_DIR_FOR_BOOTSTRAP}}" ]]; then
  for candidate in \\
    "${{_BOOTSTRAP_DIR}}/../../../../skills/shared/lib" \\
    "${{_BOOTSTRAP_DIR}}/../../../skills/shared/lib" \\
    "${{_BOOTSTRAP_DIR}}/../../skills/shared/lib"; do
    if [[ -d "${{candidate}}" ]]; then
      LIB_DIR_FOR_BOOTSTRAP="$(cd "${{candidate}}" && pwd)"
      break
    fi
  done
fi
if [[ -z "${{LIB_DIR_FOR_BOOTSTRAP}}" || ! -d "${{LIB_DIR_FOR_BOOTSTRAP}}" ]]; then
  echo "ERROR: Could not locate skills/shared/lib. Set SKILLS_SHARED_LIB_DIR=/path/to/skills/shared/lib." >&2
  exit 1
fi
RENDER_DIR="$(dirname "$0")/.."
SECRET_FILE="${{IDXC_SECRET_FILE:-/tmp/splunk_idxc_secret}}"
ADMIN_PW_FILE="${{SPLUNK_ADMIN_PASSWORD_FILE:-/tmp/splunk_admin_password}}"
SSH_USER_PEER={shell_quote(args.peer_ssh_user)}
SSH_USER_SH={shell_quote(args.sh_ssh_user)}
SSH_USER_MGR={shell_quote(args.manager_ssh_user)}
MANAGER_URI={cluster_uri}

require() {{
  for path in "$@"; do
    if [[ ! -s "${{path}}" ]]; then
      log "ERROR: required file missing or empty: ${{path}}"
      exit 1
    fi
  done
}}
require "${{SECRET_FILE}}" "${{ADMIN_PW_FILE}}"

# Push secret + admin password to the remote host as files (chmod 600) and
# reference them from the inner script. This avoids putting the cluster
# pass4SymmKey or admin password in the SSH command line, where they would
# be visible in `ps` and SSH server logs.
push_conf() {{
  local user="$1" host="$2" rel="$3"
  local local_path="${{RENDER_DIR}}/${{rel}}"
  if [[ ! -s "${{local_path}}" ]]; then
    log "ERROR: rendered config missing: ${{local_path}}"
    exit 1
  fi
  scp -o StrictHostKeyChecking=accept-new -p \\
    "${{local_path}}" "${{SECRET_FILE}}" "${{ADMIN_PW_FILE}}" \\
    "${{user}}@${{host}}:/tmp/"
  local secret_basename pw_basename conf_basename
  secret_basename="$(basename "${{SECRET_FILE}}")"
  pw_basename="$(basename "${{ADMIN_PW_FILE}}")"
  conf_basename="$(basename "${{local_path}}")"
  # We DO want client-side expansion of secret_basename/pw_basename/conf_basename
  # so the remote bash sees the actual filenames. shellcheck disable=SC2087.
  # NB on splunk restart auth: bootstrap is the ONE step that legitimately
  # has to talk to the local splunkd via CLI, because the indexer is not
  # yet a cluster member with the manager. We start (rather than restart)
  # so admin auth is not required: a fresh `splunk start` does not prompt
  # for credentials, and on a system that is already running we use
  # `splunk stop && splunk start`. This keeps the admin password out of
  # `splunk` argv on the remote host. The password file is still shred'd
  # at the end as defense-in-depth in case operators repurpose this block.
  # shellcheck disable=SC2087
  ssh -o StrictHostKeyChecking=accept-new "${{user}}@${{host}}" bash -s <<REMOTE_EOF
set -euo pipefail
secret=\\$(cat /tmp/${{secret_basename}})
sudo cp /tmp/${{conf_basename}} /opt/splunk/etc/system/local/server.conf
sudo sed -i "s/\\\\\\$IDXC_SECRET/\\${{secret}}/g" /opt/splunk/etc/system/local/server.conf
if sudo /opt/splunk/bin/splunk status >/dev/null 2>&1; then
  sudo /opt/splunk/bin/splunk stop || true
fi
sudo /opt/splunk/bin/splunk start --answer-yes --no-prompt --accept-license || true
shred -u /tmp/${{secret_basename}} /tmp/${{pw_basename}} 2>/dev/null || rm -f /tmp/${{secret_basename}} /tmp/${{pw_basename}}
REMOTE_EOF
}}

# 1. Configure manager(s) and restart.
for mgr in {' '.join(shell_quote(h) for h in manager_hosts)}; do
  push_conf "${{SSH_USER_MGR}}" "${{mgr}}" "manager/${{mgr}}/server.conf"
done

# 2. Configure peers and wait for the manager to register them via REST.
for peer_entry in {' '.join(shell_quote(p['host']) for p in peer_entries)}; do
  push_conf "${{SSH_USER_PEER}}" "${{peer_entry}}" "peer-${{peer_entry}}/server.conf"
done

EXPECTED={expected_peers}
log "Waiting for cluster manager to register ${{EXPECTED}} peer(s) via /services/cluster/manager/peers..."
ATTEMPTS=60
# Mint a session key once via REST. The admin password is read from the
# file by curl itself (--data-urlencode @file) and never lands on argv.
# All subsequent peer-count probes go through splunk_curl with the session
# key fed via -K <(...).
# shellcheck disable=SC1091
source "${{LIB_DIR_FOR_BOOTSTRAP}}/credential_helpers.sh"
SK="$(get_session_key_from_password_file "${{MANAGER_URI}}" "${{ADMIN_PW_FILE}}" "${{SPLUNK_AUTH_USER:-admin}}")"
while (( ATTEMPTS > 0 )); do
  count=$(splunk_curl "${{SK}}" \\
    "${{MANAGER_URI}}/services/cluster/manager/peers?output_mode=json&count=0" 2>/dev/null \\
    | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(len(data.get('entry', []) if isinstance(data, dict) else []))
except Exception:
    print(0)
" 2>/dev/null || echo 0)
  if [[ "${{count}}" -ge "${{EXPECTED}}" ]]; then
    log "Manager has registered ${{count}} peer(s); proceeding."
    break
  fi
  log "  Manager sees ${{count}}/${{EXPECTED}} peers, retrying in 10s..."
  sleep 10
  ATTEMPTS=$((ATTEMPTS - 1))
done
unset SK
if (( ATTEMPTS == 0 )); then
  log "ERROR: Timed out waiting for peer registration. Inspect manager logs."
  exit 1
fi

# 3. Configure search heads.
# shellcheck disable=SC2043
for sh_host in {' '.join(shell_quote(s['host']) for s in sh_entries)}; do
  push_conf "${{SSH_USER_SH}}" "${{sh_host}}" "sh-${{sh_host}}/server.conf"
done

log "OK: Cluster bootstrap sequence complete."
"""
    )


_CLUSTER_LIB_DIR_BLOCK = (
    '_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
    'LIB_DIR="${SKILLS_SHARED_LIB_DIR:-}"\n'
    'if [[ -z "${LIB_DIR}" ]]; then\n'
    '  for candidate in \\\n'
    '    "${_SCRIPT_DIR}/../../../../skills/shared/lib" \\\n'
    '    "${_SCRIPT_DIR}/../../../skills/shared/lib" \\\n'
    '    "${_SCRIPT_DIR}/../../skills/shared/lib"; do\n'
    '    if [[ -d "${candidate}" ]]; then\n'
    '      LIB_DIR="$(cd "${candidate}" && pwd)"\n'
    '      break\n'
    '    fi\n'
    '  done\n'
    'fi\n'
    'if [[ -z "${LIB_DIR}" || ! -d "${LIB_DIR}" ]]; then\n'
    '  echo "ERROR: Could not locate skills/shared/lib. Set SKILLS_SHARED_LIB_DIR=/path/to/skills/shared/lib." >&2\n'
    '  exit 1\n'
    'fi\n'
)

# Helper sourcing block for scripts that need a manager-side session key.
# Uses get_session_key_from_password_file, which feeds the password to curl
# via --data-urlencode @file (never on argv) and returns a session key that
# splunk_curl then carries via -K <(...) (also never on argv).
_CLUSTER_MGR_SK_BLOCK = (
    "# shellcheck disable=SC1091\n"
    'source "${LIB_DIR}/credential_helpers.sh"\n'
    "# shellcheck disable=SC1091\n"
    'source "${LIB_DIR}/cluster_helpers.sh"\n'
    "\n"
    'AUTH_USER="${SPLUNK_AUTH_USER:-admin}"\n'
    'ADMIN_PW_FILE="${SPLUNK_ADMIN_PASSWORD_FILE:-/tmp/splunk_admin_password}"\n'
    'if [[ ! -s "${ADMIN_PW_FILE}" ]]; then\n'
    '  echo "ERROR: admin password file is empty: ${ADMIN_PW_FILE}" >&2\n'
    "  exit 1\n"
    "fi\n"
    'SK="$(get_session_key_from_password_file "${MANAGER_URI}" "${ADMIN_PW_FILE}" "${AUTH_USER}")"\n'
)


def render_bundle_scripts(cluster_manager_uri: str) -> dict[str, str]:
    manager_uri = shell_quote(cluster_manager_uri)
    common_header = (
        _CLUSTER_LIB_DIR_BLOCK
        + f"MANAGER_URI={manager_uri}\n"
        + _CLUSTER_MGR_SK_BLOCK
    )
    return {
        "validate.sh": make_script(common_header + 'cluster_bundle_validate "${MANAGER_URI}" "${SK}"\n'),
        "status.sh": make_script(common_header + 'cluster_bundle_status "${MANAGER_URI}" "${SK}"\n'),
        "apply.sh": make_script(common_header + 'cluster_bundle_apply "${MANAGER_URI}" "${SK}"\n'),
        "apply-skip-validation.sh": make_script(common_header + 'cluster_bundle_apply "${MANAGER_URI}" "${SK}" --skip-validation\n'),
        "rollback.sh": make_script(common_header + 'cluster_bundle_rollback "${MANAGER_URI}" "${SK}"\n'),
    }


def render_restart_scripts(cluster_manager_uri: str) -> dict[str, str]:
    manager_uri = shell_quote(cluster_manager_uri)
    base = (
        _CLUSTER_LIB_DIR_BLOCK
        + f"MANAGER_URI={manager_uri}\n"
        + _CLUSTER_MGR_SK_BLOCK
    )
    return {
        "rolling-restart.sh": make_script(base + 'cluster_rolling_restart "${MANAGER_URI}" "${SK}" default\n'),
        "searchable-rolling-restart.sh": make_script(
            base
            + 'cluster_show_status_verbose "${MANAGER_URI}" "${SK}"\n'
            + 'cluster_rolling_restart "${MANAGER_URI}" "${SK}" searchable\n'
        ),
        "force-searchable.sh": make_script(
            base
            + 'export RESTART_INACTIVITY_TIMEOUT="${RESTART_INACTIVITY_TIMEOUT:-600}"\n'
            + 'export DECOMMISSION_FORCE_TIMEOUT="${DECOMMISSION_FORCE_TIMEOUT:-180}"\n'
            + 'cluster_rolling_restart "${MANAGER_URI}" "${SK}" searchable-force\n'
        ),
    }


def render_maintenance_scripts(cluster_manager_uri: str) -> dict[str, str]:
    manager_uri = shell_quote(cluster_manager_uri)
    base = (
        _CLUSTER_LIB_DIR_BLOCK
        + f"MANAGER_URI={manager_uri}\n"
        + _CLUSTER_MGR_SK_BLOCK
    )
    return {
        "enable.sh": make_script(
            base
            + 'cluster_maintenance_enable "${MANAGER_URI}" "${SK}"\n'
            + 'log "OK: Maintenance mode enabled. Bucket fixup is suppressed until you run disable.sh."\n'
        ),
        "disable.sh": make_script(
            base
            + 'cluster_maintenance_disable "${MANAGER_URI}" "${SK}"\n'
            + 'log "OK: Maintenance mode disabled."\n'
        ),
    }


def render_peer_ops(cluster_manager_uri: str) -> dict[str, str]:
    manager_uri = shell_quote(cluster_manager_uri)
    # Per-peer offline operations target the *peer*'s management URI
    # (https://${PEER_HOST}:${PEER_PORT}, port 8089 by default), not the
    # manager's. Operators can override the URL via PEER_MANAGEMENT_URL.
    peer_sk_block = (
        _CLUSTER_LIB_DIR_BLOCK
        + 'PEER_HOST="${PEER_HOST:?set PEER_HOST=hostname}"\n'
        + 'PEER_PORT="${PEER_MANAGEMENT_PORT:-8089}"\n'
        + 'PEER_URI="${PEER_MANAGEMENT_URL:-https://${PEER_HOST}:${PEER_PORT}}"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/credential_helpers.sh"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/cluster_helpers.sh"\n'
        + "\n"
        + 'AUTH_USER="${SPLUNK_AUTH_USER:-admin}"\n'
        + 'ADMIN_PW_FILE="${SPLUNK_ADMIN_PASSWORD_FILE:-/tmp/splunk_admin_password}"\n'
        + 'if [[ ! -s "${ADMIN_PW_FILE}" ]]; then\n'
        + '  echo "ERROR: admin password file is empty: ${ADMIN_PW_FILE}" >&2\n'
        + '  exit 1\n'
        + 'fi\n'
        + 'SK="$(get_session_key_from_password_file "${PEER_URI}" "${ADMIN_PW_FILE}" "${AUTH_USER}")"\n'
    )
    mgr_sk_block = (
        _CLUSTER_LIB_DIR_BLOCK
        + f"MANAGER_URI={manager_uri}\n"
        + _CLUSTER_MGR_SK_BLOCK
    )
    return {
        "offline-fast.sh": make_script(
            peer_sk_block
            + 'TIMEOUT="${DECOMMISSION_TIMEOUT:-300}"\n'
            + 'cluster_peer_offline_fast "${PEER_URI}" "${SK}" "${TIMEOUT}"\n'
            + 'log "OK: Fast offline issued on ${PEER_HOST}."\n'
        ),
        "offline-enforce-counts.sh": make_script(
            peer_sk_block
            + 'cluster_peer_offline_enforce_counts "${PEER_URI}" "${SK}"\n'
            + 'log "OK: Decommission (enforce-counts) issued on ${PEER_HOST}. Cluster will rebuild missing copies before peer shuts down."\n'
        ),
        "remove-peer.sh": make_script(
            mgr_sk_block
            + 'PEER_GUID="${PEER_GUID:?set PEER_GUID=<guid>}"\n'
            + 'cluster_remove_peer "${MANAGER_URI}" "${SK}" "${PEER_GUID}"\n'
            + 'log "OK: Removed ${PEER_GUID} from manager peer list."\n'
        ),
        "extend-restart-timeout.sh": make_script(
            mgr_sk_block
            + 'SECONDS_VAL="${RESTART_TIMEOUT_SECONDS:-900}"\n'
            + 'splunk_curl_post "${SK}" "restart_timeout=${SECONDS_VAL}" \\\n'
            + '  "${MANAGER_URI}/services/cluster/config?output_mode=json" >/dev/null\n'
            + 'log "OK: Manager restart_timeout set to ${SECONDS_VAL} seconds."\n'
        ),
    }


def render_redundancy(args: argparse.Namespace, manager_hosts: list[str]) -> dict[str, str]:
    if args.manager_redundancy != "true":
        return {}
    out = {}
    # The HAProxy template defaults to TLS verification (`ssl verify required
    # ca-file <path>`). Operators on a private CA must point ca-file at their
    # CA bundle (placeholder shown in the comment). The legacy `ssl verify
    # none` posture is left as a commented-out line so anyone who needs lab
    # behavior must consciously opt in.
    out["lb-haproxy.cfg"] = (
        "# Sample HAProxy config snippet. Adjust frontend/backend per your env.\n"
        "# Health check uses /services/cluster/manager/ha_active_status: 200=active, 503=standby.\n"
        "# Replace `ca-file /etc/ssl/certs/splunk-cluster-ca.pem` with the path to your\n"
        "# Splunk management-port CA bundle. Do NOT change `verify required` to `verify none`\n"
        "# in production: that disables TLS hostname/cert validation between HAProxy and the\n"
        "# cluster managers.\n"
        "backend cluster_managers\n"
        "  mode http\n"
        "  option httpchk GET /services/cluster/manager/ha_active_status\n"
        "  http-check expect status 200\n"
    ) + "\n".join(
        f"  server cm{i+1} {h}:8089 check ssl verify required ca-file /etc/ssl/certs/splunk-cluster-ca.pem inter 5s rise 2 fall 3"
        for i, h in enumerate(manager_hosts)
    ) + "\n"

    out["dns-record-template.txt"] = f"""# Sample DNS record planning for cluster manager redundancy.
# Use a CNAME or A record (e.g. cm.example.com) and update on failover.
{', '.join(manager_hosts)}
"""
    # ha-health-check.sh: TLS verification is enabled by default (no `-k`).
    # Operators on a private CA can set CLUSTER_HA_CA_BUNDLE=/path/to/ca.pem
    # to point curl at the right trust store, OR set CLUSTER_HA_INSECURE=true
    # for lab use. We emit a stderr warning whenever the insecure path runs
    # so it cannot quietly become the default in production.
    out["ha-health-check.sh"] = make_script(f"""# Health-check probe used by external monitoring or LB sanity checks.
ca_args=()
if [[ -n "${{CLUSTER_HA_CA_BUNDLE:-}}" ]]; then
  if [[ ! -s "${{CLUSTER_HA_CA_BUNDLE}}" ]]; then
    echo "ERROR: CLUSTER_HA_CA_BUNDLE not found or empty: ${{CLUSTER_HA_CA_BUNDLE}}" >&2
    exit 1
  fi
  ca_args=(--cacert "${{CLUSTER_HA_CA_BUNDLE}}")
elif [[ "${{CLUSTER_HA_INSECURE:-false}}" == "true" ]]; then
  echo "WARNING: TLS verification disabled for cluster HA health checks (CLUSTER_HA_INSECURE=true). Use CLUSTER_HA_CA_BUNDLE=/path/to/ca.pem in production." >&2
  ca_args=(-k)
fi
for mgr in {' '.join(shell_quote(h) for h in manager_hosts)}; do
  status=$(curl "${{ca_args[@]}}" -s -o /dev/null -w "%{{http_code}}" "https://${{mgr}}:8089/services/cluster/manager/ha_active_status" || echo "000")
  echo "${{mgr}}: HTTP ${{status}} ($([[ "${{status}}" == "200" ]] && echo ACTIVE || echo STANDBY/DOWN))"
done
""")
    return out


def render_migration(args: argparse.Namespace) -> dict[str, str]:
    """Migration scripts. All cluster-config edits go through REST so
    neither the admin password nor the IDXC `pass4SymmKey` (`-secret`) are
    ever expanded into local or remote `ssh` argv. The pass4SymmKey is
    handed to curl via `--data-urlencode "secret@${IDXC_SECRET_FILE}"`."""
    manager_uri = shell_quote(args.cluster_manager_uri)
    available_sites = shell_quote(args.available_sites)
    site_rf = shell_quote(args.site_replication_factor)
    site_sf = shell_quote(args.site_search_factor)
    repl_port = shell_quote(str(args.replication_port))

    mgr_sk_block = (
        _CLUSTER_LIB_DIR_BLOCK
        + f"MANAGER_URI={manager_uri}\n"
        + _CLUSTER_MGR_SK_BLOCK
    )
    return {
        "single-to-multisite.sh": make_script(
            mgr_sk_block
            + 'SECRET_FILE="${IDXC_SECRET_FILE:-/tmp/splunk_idxc_secret}"\n'
            + 'if [[ ! -s "${SECRET_FILE}" ]]; then\n'
            + '  echo "ERROR: idxc secret file empty: ${SECRET_FILE}" >&2; exit 1\n'
            + 'fi\n'
            + f'AVAILABLE_SITES={available_sites}\n'
            + f'SITE_RF={site_rf}\n'
            + f'SITE_SF={site_sf}\n'
            + "# Per Splunk doc: keep legacy replication_factor / search_factor for old\n"
            + "# buckets; add multisite settings for new buckets. The pass4SymmKey is\n"
            + "# fed to curl via --data-urlencode @file so it never lands on argv.\n"
            + 'splunk_curl "${SK}" -X POST \\\n'
            + '  --data-urlencode "mode=manager" \\\n'
            + '  --data-urlencode "multisite=true" \\\n'
            + '  --data-urlencode "available_sites=${AVAILABLE_SITES}" \\\n'
            + '  --data-urlencode "site_replication_factor=${SITE_RF}" \\\n'
            + '  --data-urlencode "site_search_factor=${SITE_SF}" \\\n'
            + '  --data-urlencode "secret@${SECRET_FILE}" \\\n'
            + '  "${MANAGER_URI}/services/cluster/config?output_mode=json" >/dev/null\n'
            + 'splunk_curl "${SK}" -X POST "${MANAGER_URI}/services/server/control/restart?output_mode=json" >/dev/null\n'
            + 'log "Manager configured for multisite. Now run move-peer-to-site.sh per peer to assign sites."\n'
        ),
        "replace-manager.sh": make_script(
            _CLUSTER_LIB_DIR_BLOCK
            + 'NEW_MANAGER_URI="${NEW_MANAGER_URI:?set NEW_MANAGER_URI=https://newcm:8089}"\n'
            + 'MANAGER_URI="${NEW_MANAGER_URI}"\n'
            + _CLUSTER_MGR_SK_BLOCK
            + 'SECRET_FILE="${IDXC_SECRET_FILE:-/tmp/splunk_idxc_secret}"\n'
            + 'if [[ ! -s "${SECRET_FILE}" ]]; then\n'
            + '  echo "ERROR: idxc secret file empty: ${SECRET_FILE}" >&2; exit 1\n'
            + 'fi\n'
            + 'splunk_curl "${SK}" -X POST \\\n'
            + '  --data-urlencode "mode=manager" \\\n'
            + '  --data-urlencode "secret@${SECRET_FILE}" \\\n'
            + '  "${MANAGER_URI}/services/cluster/config?output_mode=json" >/dev/null\n'
            + 'splunk_curl "${SK}" -X POST "${MANAGER_URI}/services/server/control/restart?output_mode=json" >/dev/null\n'
            + 'log "OK: New manager configured at ${MANAGER_URI}. Update peer/SH manager_uri to point here next."\n'
        ),
        "decommission-site.sh": make_script(
            mgr_sk_block
            + 'SITE="${SITE:?set SITE=siteN}"\n'
            + "# Read available_sites from the cluster-config REST endpoint, drop the\n"
            + "# decommissioning site, and PUT the trimmed list back. No CLI parsing.\n"
            + 'config_json="$(splunk_curl "${SK}" \\\n'
            + '  "${MANAGER_URI}/services/cluster/config?output_mode=json")"\n'
            + 'remaining=$(SITE="${SITE}" python3 - "${config_json}" <<\'PY\'\n'
            + 'import json, os, sys\n'
            + 'site = os.environ["SITE"]\n'
            + 'data = json.loads(sys.argv[1]) if sys.argv[1].strip() else {}\n'
            + 'entry = (data.get("entry") or [{}])[0]\n'
            + 'content = entry.get("content", {}) if isinstance(entry, dict) else {}\n'
            + 'avail = content.get("available_sites", "")\n'
            + 'sites = [s.strip() for s in avail.split(",") if s.strip() and s.strip() != site]\n'
            + 'print(",".join(sites))\n'
            + 'PY\n'
            + ')\n'
            + 'if [[ -z "${remaining}" ]]; then\n'
            + '  echo "ERROR: Cannot decommission ${SITE}: no remaining sites would exist." >&2\n'
            + '  exit 1\n'
            + 'fi\n'
            + 'splunk_curl "${SK}" -X POST \\\n'
            + '  --data-urlencode "available_sites=${remaining}" \\\n'
            + '  "${MANAGER_URI}/services/cluster/config?output_mode=json" >/dev/null\n'
            + 'splunk_curl "${SK}" -X POST "${MANAGER_URI}/services/server/control/restart?output_mode=json" >/dev/null\n'
            + 'log "OK: Decommissioned ${SITE}; available_sites is now ${remaining}."\n'
        ),
        "move-peer-to-site.sh": make_script(
            _CLUSTER_LIB_DIR_BLOCK
            + 'PEER_HOST="${PEER_HOST:?set PEER_HOST=hostname}"\n'
            + 'NEW_SITE="${NEW_SITE:?set NEW_SITE=siteN}"\n'
            + 'PEER_PORT="${PEER_MANAGEMENT_PORT:-8089}"\n'
            + 'PEER_URI="${PEER_MANAGEMENT_URL:-https://${PEER_HOST}:${PEER_PORT}}"\n'
            + 'MANAGER_URI="${PEER_URI}"\n'
            + _CLUSTER_MGR_SK_BLOCK
            + 'splunk_curl "${SK}" -X POST \\\n'
            + '  --data-urlencode "site=${NEW_SITE}" \\\n'
            + '  "${PEER_URI}/services/cluster/config?output_mode=json" >/dev/null\n'
            + 'splunk_curl "${SK}" -X POST "${PEER_URI}/services/server/control/restart?output_mode=json" >/dev/null\n'
            + 'log "OK: Peer ${PEER_HOST} now reports site=${NEW_SITE}."\n'
        ),
        "migrate-non-clustered.sh": make_script(
            _CLUSTER_LIB_DIR_BLOCK
            + 'INDEXER_HOST="${INDEXER_HOST:?set INDEXER_HOST=hostname}"\n'
            + 'PEER_PORT="${PEER_MANAGEMENT_PORT:-8089}"\n'
            + 'PEER_URI="${PEER_MANAGEMENT_URL:-https://${INDEXER_HOST}:${PEER_PORT}}"\n'
            + 'MANAGER_URI="${PEER_URI}"\n'
            + _CLUSTER_MGR_SK_BLOCK
            + f"REMOTE_MANAGER_URI={manager_uri}\n"
            + f"REPLICATION_PORT={repl_port}\n"
            + 'SECRET_FILE="${IDXC_SECRET_FILE:-/tmp/splunk_idxc_secret}"\n'
            + 'if [[ ! -s "${SECRET_FILE}" ]]; then\n'
            + '  echo "ERROR: idxc secret file empty: ${SECRET_FILE}" >&2; exit 1\n'
            + 'fi\n'
            + 'cat <<\'EOM\'\n'
            + 'WARNING: Migrating a non-clustered indexer carries forward its standalone\n'
            + 'buckets. Splunk\'s "splunk offline --enforce-counts" command does NOT handle\n'
            + 'those standalone buckets; if you ever decommission this peer permanently you\n'
            + 'must back up or move that data separately.\n'
            + 'EOM\n'
            + 'splunk_curl "${SK}" -X POST \\\n'
            + '  --data-urlencode "mode=peer" \\\n'
            + '  --data-urlencode "manager_uri=${REMOTE_MANAGER_URI}" \\\n'
            + '  --data-urlencode "replication_port=${REPLICATION_PORT}" \\\n'
            + '  --data-urlencode "secret@${SECRET_FILE}" \\\n'
            + '  "${PEER_URI}/services/cluster/config?output_mode=json" >/dev/null\n'
            + 'splunk_curl "${SK}" -X POST "${PEER_URI}/services/server/control/restart?output_mode=json" >/dev/null\n'
            + 'log "OK: ${INDEXER_HOST} joined the cluster as a peer."\n'
        ),
    }


def render_forwarder_outputs(args: argparse.Namespace, forwarder_hosts: list[str]) -> dict[str, str]:
    if not forwarder_hosts:
        return {}
    snippet = f"""# Rendered by splunk-indexer-cluster-setup. Merge into outputs.conf on the forwarder.
[indexer_discovery:{args.indexer_discovery_tag}]
manager_uri = {args.cluster_manager_uri}
pass4SymmKey = $IDXC_SECRET

[tcpout:idxc_main]
indexerDiscovery = {args.indexer_discovery_tag}

[tcpout]
defaultGroup = idxc_main
"""
    return {f"{host}/outputs.conf": snippet for host in forwarder_hosts}


def render_validate(cluster_manager_uri: str) -> str:
    manager_uri = shell_quote(cluster_manager_uri)
    body = (
        _CLUSTER_LIB_DIR_BLOCK
        + f"MANAGER_URI={manager_uri}\n"
        + _CLUSTER_MGR_SK_BLOCK
        + 'TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)\n'
        + 'AUDIT_DIR="$(dirname "$0")/audit/${TIMESTAMP}"\n'
        + "# cluster_audit_snapshot creates the dir 0700 and writes each\n"
        + "# JSON payload with umask 077.\n"
        + 'cluster_audit_snapshot "${MANAGER_URI}" "${SK}" "${AUDIT_DIR}"\n'
        + "\n"
        + "# Use the structured /info payload to gate on pre-flight readiness.\n"
        + 'preflight_failed=$(python3 - "${AUDIT_DIR}/manager-info.json" <<\'PY\'\n'
        + 'import json, sys\n'
        + 'try:\n'
        + '    data = json.load(open(sys.argv[1]))\n'
        + 'except Exception:\n'
        + '    print("unknown")\n'
        + '    sys.exit(0)\n'
        + 'entry = (data.get("entry") or [{}])[0]\n'
        + 'content = entry.get("content", {}) if isinstance(entry, dict) else {}\n'
        + 'pf = content.get("preflight_check_completed", "true")\n'
        + 'pf_pass = content.get("preflight_check_passed", "true")\n'
        + 'if str(pf).lower() == "true" and str(pf_pass).lower() == "false":\n'
        + '    print("yes")\n'
        + 'else:\n'
        + '    print("no")\n'
        + 'PY\n'
        + ')\n'
        + 'if [[ "${preflight_failed}" == "yes" ]]; then\n'
        + '  echo "FAIL: Cluster pre-flight check failed. See ${AUDIT_DIR}/manager-info.json" >&2\n'
        + '  exit 1\n'
        + 'fi\n'
        + '\n'
        + 'echo "PASS: Cluster validate complete. Snapshot: ${AUDIT_DIR}"\n'
    )
    return make_script(body)


def render_metadata(args: argparse.Namespace, peers: list[dict], shs: list[dict], managers: list[str]) -> str:
    return json.dumps(
        {
            "skill": "splunk-indexer-cluster-setup",
            "cluster_mode": args.cluster_mode,
            "cluster_label": args.cluster_label,
            "manager_count": len(managers),
            "manager_redundancy": args.manager_redundancy == "true",
            "peer_count": len(peers),
            "sh_count": len(shs),
            "available_sites": csv_list(args.available_sites) if args.cluster_mode == "multisite" else [],
            "site_replication_factor": args.site_replication_factor if args.cluster_mode == "multisite" else None,
            "site_search_factor": args.site_search_factor if args.cluster_mode == "multisite" else None,
            "replication_factor": args.replication_factor,
            "search_factor": args.search_factor,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_handoff_license_peers(peers: list[dict], shs: list[dict], managers: list[str]) -> str:
    lines = ["# Hand-off stub for splunk-license-manager-setup --peer-hosts.",
             "# Each line is a single host that should be configured as a license peer."]
    for h in managers:
        lines.append(h)
    for p in peers:
        lines.append(p["host"])
    for s in shs:
        lines.append(s["host"])
    return "\n".join(lines) + "\n"


def render_all(args: argparse.Namespace) -> dict:
    multisite = args.cluster_mode == "multisite"
    sites = csv_list(args.available_sites) if multisite else []
    if multisite and not sites:
        die("--available-sites is required when --cluster-mode=multisite.")

    peers = parse_host_site_pairs(args.peer_hosts, "peer-hosts", multisite)
    shs = parse_host_site_pairs(args.sh_hosts, "sh-hosts", multisite)
    managers = [validate_host_token(h, "manager-hosts") for h in csv_list(args.manager_hosts)]
    if not managers:
        managers = [parse_uri(args.cluster_manager_uri, "--cluster-manager-uri")[0]]
    forwarders = [validate_host_token(h, "forwarder-hosts") for h in csv_list(args.forwarder_hosts)]

    if args.manager_redundancy == "true" and len(managers) < 2:
        die("--manager-redundancy=true requires at least 2 entries in --manager-hosts.")

    # Per-site peer count for the legacy single-site validator.
    peer_count_per_site: dict[str, int] = {}
    for p in peers:
        if p.get("site"):
            peer_count_per_site[p["site"]] = peer_count_per_site.get(p["site"], 0) + 1

    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "cluster"
    render_dir.mkdir(parents=True, exist_ok=True)

    files = []

    write_file(render_dir / "metadata.json", render_metadata(args, peers, shs, managers))
    files.append("metadata.json")

    # Manager configs (one per manager host so ops can stage them individually).
    for idx, mgr in enumerate(managers):
        mgr_uris = [args.cluster_manager_uri] if not args.manager_redundancy == "true" else [
            f"https://{m}:{parse_uri(args.cluster_manager_uri, '--cluster-manager-uri')[1]}"
            for m in managers
        ]
        conf = render_manager_server_conf(args, mgr, multisite, sites, peer_count_per_site, idx, mgr_uris)
        write_file(render_dir / f"manager/{mgr}/server.conf", conf)
        files.append(f"manager/{mgr}/server.conf")

    # Per Splunk's manager-redundancy doc, peers and SHs MUST reference the
    # LB / DNS endpoint when redundancy is enabled. Pick that endpoint here.
    peer_facing_uri = _peer_facing_manager_uri(args)

    # Peer configs.
    for p in peers:
        conf = render_peer_server_conf(args, p, multisite, peer_facing_uri)
        write_file(render_dir / f"peer-{p['host']}/server.conf", conf)
        files.append(f"peer-{p['host']}/server.conf")

    # SH configs.
    for s in shs:
        conf = render_sh_server_conf(args, s, multisite, peer_facing_uri)
        write_file(render_dir / f"sh-{s['host']}/server.conf", conf)
        files.append(f"sh-{s['host']}/server.conf")

    # Bootstrap.
    write_file(render_dir / "bootstrap/sequenced-bootstrap.sh", render_bootstrap(args, managers, peers, shs, multisite), executable=True)
    files.append("bootstrap/sequenced-bootstrap.sh")

    # Bundle ops.
    for name, content in render_bundle_scripts(args.cluster_manager_uri).items():
        write_file(render_dir / f"bundle/{name}", content, executable=True)
        files.append(f"bundle/{name}")

    # Restart ops.
    for name, content in render_restart_scripts(args.cluster_manager_uri).items():
        write_file(render_dir / f"restart/{name}", content, executable=True)
        files.append(f"restart/{name}")

    # Maintenance.
    for name, content in render_maintenance_scripts(args.cluster_manager_uri).items():
        write_file(render_dir / f"maintenance/{name}", content, executable=True)
        files.append(f"maintenance/{name}")

    # Peer ops.
    for name, content in render_peer_ops(args.cluster_manager_uri).items():
        write_file(render_dir / f"peer-ops/{name}", content, executable=True)
        files.append(f"peer-ops/{name}")

    # Redundancy.
    for name, content in render_redundancy(args, managers).items():
        executable = name.endswith(".sh")
        write_file(render_dir / f"redundancy/{name}", content, executable=executable)
        files.append(f"redundancy/{name}")

    # Migration.
    for name, content in render_migration(args).items():
        write_file(render_dir / f"migration/{name}", content, executable=True)
        files.append(f"migration/{name}")

    # Forwarder outputs.
    for rel, content in render_forwarder_outputs(args, forwarders).items():
        write_file(render_dir / f"forwarder-outputs/{rel}", content)
        files.append(f"forwarder-outputs/{rel}")

    # Hand-off stubs.
    write_file(render_dir / "handoffs/license-peers.txt", render_handoff_license_peers(peers, shs, managers))
    files.append("handoffs/license-peers.txt")

    # Validate.
    write_file(render_dir / "validate.sh", render_validate(args.cluster_manager_uri), executable=True)
    files.append("validate.sh")

    write_file(render_dir / "README.md", render_readme(args, peers, shs, managers, multisite))
    files.append("README.md")

    return {"render_dir": str(render_dir), "files": sorted(files)}


def render_readme(args: argparse.Namespace, peers: list[dict], shs: list[dict], managers: list[str], multisite: bool) -> str:
    sites = csv_list(args.available_sites) if multisite else []
    return f"""# Splunk Indexer Cluster Rendered Assets

Cluster mode: `{args.cluster_mode}`
Cluster label: `{args.cluster_label}`
Cluster manager URI: `{args.cluster_manager_uri}`
Manager redundancy: `{args.manager_redundancy}`
Manager(s): `{', '.join(managers)}`
Peers: {len(peers)}
Search heads: {len(shs)}
{('Sites: `' + ', '.join(sites) + '`') if multisite else ''}

## Files

- `manager/<host>/server.conf` — manager configs (per host).
- `peer-<host>/server.conf` — per-peer config with site assignment.
- `sh-<host>/server.conf` — per-SH config.
- `bootstrap/sequenced-bootstrap.sh` — manager → peers (RF gate) → SHs.
- `bundle/{{validate,status,apply,apply-skip-validation,rollback}}.sh`.
- `restart/{{rolling-restart,searchable-rolling-restart,force-searchable}}.sh`.
- `maintenance/{{enable,disable}}.sh`.
- `peer-ops/{{offline-fast,offline-enforce-counts,remove-peer,extend-restart-timeout}}.sh`.
- `migration/{{single-to-multisite,replace-manager,decommission-site,move-peer-to-site,migrate-non-clustered}}.sh`.
- `redundancy/{{lb-haproxy.cfg,dns-record-template.txt,ha-health-check.sh}}` (when redundancy enabled).
- `forwarder-outputs/<host>/outputs.conf` — indexer-discovery snippets.
- `handoffs/license-peers.txt` — hand-off stub for `splunk-license-manager-setup`.
- `validate.sh` — full health snapshot (cluster-status, bundle-status, REST `/health`, `/info`, `/peers`).

## $IDXC_SECRET substitution

The rendered server.conf files contain `pass4SymmKey = $IDXC_SECRET`. The
`bootstrap/sequenced-bootstrap.sh` script reads the secret value from
`${{IDXC_SECRET_FILE:-/tmp/splunk_idxc_secret}}` and substitutes it before
copying server.conf to each host. If you stage the configs by hand, replace
`$IDXC_SECRET` yourself and delete the substituted copy after apply.

## Restart impact

- Manager configuration changes (`mode`, `multisite`, factors, `pass4SymmKey`)
  require a manager restart and a rolling restart of peers.
- Peer site changes require a peer restart.
- Bundle apply triggers a peer rolling restart only when the bundle contains
  changes that require restart (per `[triggers]` in `app.conf`).

## Next steps

1. Run `splunk-license-manager-setup` and import `handoffs/license-peers.txt`
   as `--peer-hosts`.
2. If you use SmartStore, run `splunk-index-lifecycle-smartstore-setup` to
   render `indexes.conf` for the bundle.
3. If you use Workload Management, run `splunk-workload-management-setup` to
   render workload pool / rule files for the bundle.
"""


def main() -> None:
    args = parse_args()
    if args.dry_run:
        sites = csv_list(args.available_sites)
        peers = parse_host_site_pairs(args.peer_hosts, "peer-hosts", args.cluster_mode == "multisite")
        shs = parse_host_site_pairs(args.sh_hosts, "sh-hosts", args.cluster_mode == "multisite")
        managers = csv_list(args.manager_hosts) or [parse_uri(args.cluster_manager_uri, "--cluster-manager-uri")[0]]
        payload = {"sites": sites, "peers": peers, "shs": shs, "managers": managers}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return
    result = render_all(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Rendered {len(result['files'])} cluster asset(s) to {result['render_dir']}")
        for name in result["files"]:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
