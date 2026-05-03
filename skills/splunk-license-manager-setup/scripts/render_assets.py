#!/usr/bin/env python3
"""Render Splunk license manager assets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path
from urllib.parse import urlparse


VALID_GROUPS = ("Enterprise", "Forwarder", "Free", "Trial", "Download-Trial")
VALID_STACK_IDS = ("enterprise", "forwarder", "download-trial", "free", "dev")
VALID_APPLY_TARGETS = ("manager", "peers", "all")
VALID_COLOCATIONS = (
    "cluster-manager",
    "monitoring-console",
    "deployment-server",
    "shc-deployer",
    "search-head",
    "indexer",
    "dedicated",
)


GENERATED_TOP_FILES = {
    "README.md",
    "metadata.json",
    "validate.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk license manager assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--license-manager-uri", required=True)
    parser.add_argument("--license-manager-host", default="")
    parser.add_argument("--license-manager-ssh-user", default="splunk")
    parser.add_argument("--license-files", default="")
    parser.add_argument("--license-group", default="Enterprise")
    parser.add_argument("--pool-specs", default="", help="Repeatable; CSV of key=value pairs per pool. Use newline or '|' between pools.")
    parser.add_argument("--peer-hosts", default="")
    parser.add_argument("--peer-ssh-user", default="splunk")
    parser.add_argument("--apply-target", choices=VALID_APPLY_TARGETS, default="all")
    parser.add_argument("--colocated-with", choices=VALID_COLOCATIONS, default="dedicated")
    parser.add_argument("--restart-splunk", choices=("true", "false"), default="true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


def parse_uri(uri: str) -> tuple[str, int]:
    parsed = urlparse(uri)
    if parsed.scheme not in ("http", "https"):
        die(f"--license-manager-uri must be http(s)://host:port: {uri!r}")
    if not parsed.hostname:
        die(f"--license-manager-uri must include a host: {uri!r}")
    port = parsed.port or 8089
    return parsed.hostname, port


def parse_pool_specs(value: str) -> list[dict]:
    if not value.strip():
        return []
    # Pools are separated by '|' or newline; key=value pairs within a pool by ','.
    raw_pools = [chunk for chunk in re.split(r"[|\n]", value) if chunk.strip()]
    pools: list[dict] = []
    for chunk in raw_pools:
        spec: dict = {}
        for kv in csv_list(chunk):
            if "=" not in kv:
                die(f"--pool-specs entry has no '=': {kv!r}")
            key, raw = kv.split("=", 1)
            key = key.strip()
            raw = raw.strip()
            spec[key] = raw
        if "name" not in spec or "stack_id" not in spec or "quota" not in spec:
            die(f"--pool-specs entry missing required key (name/stack_id/quota): {spec!r}")
        if spec["stack_id"] not in VALID_STACK_IDS:
            die(f"--pool-specs stack_id must be one of {VALID_STACK_IDS}: {spec!r}")
        quota = spec["quota"]
        if quota.upper() != "MAX" and not re.fullmatch(r"[0-9]+", quota):
            die(f"--pool-specs quota must be MAX or a byte count: {quota!r}")
        if "slaves" not in spec or not spec["slaves"]:
            spec["slaves"] = "*"
        pools.append(spec)
    return pools


def validate_args(args: argparse.Namespace) -> dict:
    parse_uri(args.license_manager_uri)
    if args.license_group not in VALID_GROUPS:
        die(f"--license-group must be one of {VALID_GROUPS}")
    license_files = csv_list(args.license_files)
    for path in license_files:
        if not re.fullmatch(r"[A-Za-z0-9_./~:-]+", path):
            die(f"--license-files path contains unsupported characters: {path!r}")
    peer_hosts = csv_list(args.peer_hosts)
    pool_specs = parse_pool_specs(args.pool_specs)
    return {
        "license_files": license_files,
        "peer_hosts": peer_hosts,
        "pool_specs": pool_specs,
    }


def render_metadata(args: argparse.Namespace, parsed: dict) -> str:
    return json.dumps(
        {
            "skill": "splunk-license-manager-setup",
            "license_manager_uri": args.license_manager_uri,
            "license_files_count": len(parsed["license_files"]),
            "license_group": args.license_group,
            "pool_count": len(parsed["pool_specs"]),
            "peer_count": len(parsed["peer_hosts"]),
            "colocated_with": args.colocated_with,
            "apply_target": args.apply_target,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_readme(args: argparse.Namespace, parsed: dict) -> str:
    pool_lines = "\n".join(
        f"- `{p['name']}` ({p['stack_id']}, quota={p['quota']}, slaves={p.get('slaves', '*')})"
        for p in parsed["pool_specs"]
    ) or "- (no pools)"
    return f"""# Splunk License Manager Rendered Assets

License manager URI: `{args.license_manager_uri}`
Active group to set: `{args.license_group}`
Co-located with: `{args.colocated_with}`

## License files

{(chr(10).join(f"- `{p}`" for p in parsed["license_files"])) or "- (none — manager will keep its existing licenses)"}

## License pools

{pool_lines}

## Peers

{(chr(10).join(f"- `{h}`" for h in parsed["peer_hosts"])) or "- (none — peers phase will be a no-op)"}

## Files

- `manager/install-licenses.sh`
- `manager/activate-group.sh`
- `manager/pools/<pool>.json`
- `manager/apply-pools.sh`
- `peers/<host>/peer-server.conf`
- `peers/<host>/configure-peer.sh`
- `validate.sh`

## Restart impact

License install and group activation usually require a Splunk restart on the
manager. Configuring a peer's localpeer requires a peer restart so the change
takes effect. Both restarts are emitted by the rendered scripts.

## Next steps

If this license manager will be co-located with a cluster manager, run
`splunk-indexer-cluster-setup` next so the cluster manager `pass4SymmKey` and
`cluster_label` line up with the manager's existing config. If you have ES or
ITSI on a separate search-head cluster, ensure the SHC deployer is also
listed in `--peer-hosts`.
"""


_SOURCE_LIB_BLOCK = (
    "# shellcheck disable=SC1091\n"
    'source "${LIB_DIR}/credential_helpers.sh"\n'
    "# shellcheck disable=SC1091\n"
    'source "${LIB_DIR}/license_helpers.sh"\n'
    "\n"
    'AUTH_USER="${SPLUNK_AUTH_USER:-admin}"\n'
    'AUTH_PW_FILE="${SPLUNK_ADMIN_PASSWORD_FILE:-/tmp/splunk_admin_password}"\n'
    'if [[ ! -s "${AUTH_PW_FILE}" ]]; then\n'
    '  echo "ERROR: Splunk admin password file is empty: ${AUTH_PW_FILE}" >&2\n'
    "  exit 1\n"
    "fi\n"
    "# Mint a session key from the password file (curl reads the file via\n"
    "# --data-urlencode @file; password never lands on argv). All subsequent\n"
    "# REST work uses splunk_curl, which feeds the session key via -K <(...)\n"
    "# and also keeps it off argv.\n"
    'SK="$(get_session_key_from_password_file "${MANAGER_URI}" "${AUTH_PW_FILE}" "${AUTH_USER}")"\n'
)


def _lib_dir_block() -> str:
    """Compute the absolute path to skills/shared/lib at runtime, so the
    rendered scripts work from any CWD without depending on relative paths."""
    return (
        '_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        '# shared/lib lives at <repo>/skills/shared/lib relative to the rendered\n'
        '# tree; we accept SKILLS_SHARED_LIB_DIR as an override for portable\n'
        "# deployments where the renderer output is moved out of the repo.\n"
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


def render_install_licenses(args: argparse.Namespace, parsed: dict) -> str:
    license_files = " ".join(shell_quote(p) for p in parsed["license_files"]) or ""
    manager_uri = shell_quote(args.license_manager_uri)
    restart_block = (
        # Restart goes through the local splunk CLI with no -auth (the
        # operator must already own the host); the password never lands in
        # the splunk argv that other users on this host could see.
        'if [[ -x "/opt/splunk/bin/splunk" ]]; then\n'
        '  /opt/splunk/bin/splunk stop || true\n'
        '  /opt/splunk/bin/splunk start\n'
        'else\n'
        '  echo "WARNING: /opt/splunk/bin/splunk not found; skipping local restart. Restart Splunk manually before continuing." >&2\n'
        'fi\n'
        if args.restart_splunk == "true"
        else 'echo "Splunk restart skipped. License changes typically require a restart on the manager."\n'
    )

    body = _lib_dir_block() + (
        f'MANAGER_URI={manager_uri}\n'
        + _SOURCE_LIB_BLOCK
    )
    if license_files:
        body += (
            '# shellcheck disable=SC2043\n'
            f'for f in {license_files}; do\n'
            '  if [[ ! -s "$f" ]]; then\n'
            '    echo "ERROR: License file missing: $f" >&2\n'
            '    exit 1\n'
            '  fi\n'
            '  license_install_files "${MANAGER_URI}" "${SK}" "$f"\n'
            'done\n'
        )
    else:
        body += 'echo "No license files specified; skipping license install."\n'
    body += restart_block
    return make_script(body)


def render_activate_group(args: argparse.Namespace) -> str:
    manager_uri = shell_quote(args.license_manager_uri)
    group = shell_quote(args.license_group)
    body = _lib_dir_block() + (
        f"MANAGER_URI={manager_uri}\n"
        f"GROUP={group}\n"
        + _SOURCE_LIB_BLOCK
        + (
            'if [[ "${GROUP}" == "Free" ]]; then\n'
            "  cat <<'EOM'\n"
            "WARNING: Activating the Free license group will disable:\n"
            "  - authentication\n"
            "  - distributed search\n"
            "  - indexer clustering\n"
            "  - scheduled searches and alerts\n"
            "  - summary indexing\n"
            "  - deployment server\n"
            "Confirm the change is intentional before proceeding.\n"
            "EOM\n"
            "fi\n"
            "\n"
            'license_activate_group "${MANAGER_URI}" "${SK}" "${GROUP}"\n'
            'echo "OK: License group ${GROUP} activated on ${MANAGER_URI}"\n'
        )
    )
    return make_script(body)


def render_pool_json(pool: dict) -> str:
    return json.dumps(
        {
            "name": pool["name"],
            "stack_id": pool["stack_id"],
            "quota": pool["quota"],
            "slaves": pool.get("slaves", "*"),
            "description": pool.get("description", ""),
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_apply_pools(args: argparse.Namespace, parsed: dict) -> str:
    manager_uri = shell_quote(args.license_manager_uri)
    body = _lib_dir_block() + (
        f"MANAGER_URI={manager_uri}\n"
        + _SOURCE_LIB_BLOCK
        + (
            'POOLS_DIR="$(dirname "$0")/pools"\n'
            "shopt -s nullglob\n"
            'for spec in "${POOLS_DIR}"/*.json; do\n'
            "  # license_pool_apply handles both create and update via REST,\n"
            "  # checks HTTP 200 vs 404 strictly, and refuses to fall back\n"
            "  # to a blind create on auth/server errors. It also normalizes\n"
            "  # `slaves` from JSON arrays to comma-separated GUID lists.\n"
            '  license_pool_apply "${MANAGER_URI}" "${SK}" "${spec}"\n'
            '  log "OK: Applied pool spec ${spec}"\n'
            "done\n"
        )
    )
    return make_script(body)


def render_peer_server_conf(args: argparse.Namespace) -> str:
    # Peer-side server.conf snippet. The skill writes manager_uri (9.x+) and
    # documents the legacy master_uri fallback in reference.md.
    return f"""# Rendered by splunk-license-manager-setup. Review before applying.
# This snippet should be merged into ${{SPLUNK_HOME}}/etc/system/local/server.conf
# on each license peer.

[license]
manager_uri = {args.license_manager_uri}
"""


def render_configure_peer(args: argparse.Namespace, host: str, ssh_user: str) -> str:
    """Configure a single license peer via the peer's own REST endpoint.

    The peer URI is constructed from the peer hostname plus the same
    management port the license manager exposes (8089 by default), since
    license peers are full Splunk Enterprise instances. We hit the peer's
    `/services/licenser/localpeer` over HTTPS using the operator's admin
    password file; SSH is no longer required, which removes the previous
    SSH `bash -c '${INNER}'` quoting bug AND the `splunk -auth admin:pw`
    argv leakage on both the local and remote hosts.

    For unusual deployments where the peer's management URL is not the
    obvious `https://<host>:8089`, the operator can override the URL via
    the `PEER_MANAGEMENT_URL` env var.
    """
    manager_uri = shell_quote(args.license_manager_uri)
    host_q = shell_quote(host)
    # ssh_user is retained in the script preamble for traceability but no
    # longer used for execution.
    user_q = shell_quote(ssh_user)

    parsed = urlparse(args.license_manager_uri)
    peer_default_port = parsed.port or 8089
    body = _lib_dir_block() + (
        f"HOST={host_q}\n"
        f"SSH_USER={user_q}  # informational; not used for execution\n"
        f"MANAGER_URI={manager_uri}\n"
        f'PEER_PORT="${{PEER_MANAGEMENT_PORT:-{peer_default_port}}}"\n'
        'PEER_URI="${PEER_MANAGEMENT_URL:-https://${HOST}:${PEER_PORT}}"\n'
        + _SOURCE_LIB_BLOCK.replace(
            'SK="$(get_session_key_from_password_file "${MANAGER_URI}" "${AUTH_PW_FILE}" "${AUTH_USER}")"\n',
            'SK="$(get_session_key_from_password_file "${PEER_URI}" "${AUTH_PW_FILE}" "${AUTH_USER}")"\n',
        )
        + (
            'result="$(license_localpeer_set_manager_uri "${PEER_URI}" "${SK}" "${MANAGER_URI}")"\n'
            "case \"${result}\" in\n"
            '  OK_MANAGER_URI) echo "OK: localpeer manager_uri set on ${HOST}" ;;\n'
            '  OK_MASTER_URI) echo "OK: localpeer master_uri set on ${HOST} (8.x compatibility path)" ;;\n'
            '  *) echo "ERROR: license_localpeer_set_manager_uri failed: ${result}" >&2; exit 1 ;;\n'
            "esac\n"
        )
        + (
            "# Localpeer changes only take effect after a Splunk restart on\n"
            "# the peer. Trigger it via REST so we never put credentials on\n"
            "# the splunk CLI argv on the remote host.\n"
            'splunk_curl "${SK}" -X POST "${PEER_URI}/services/server/control/restart?output_mode=json" >/dev/null\n'
            'echo "OK: requested splunkd restart on ${HOST} via REST"\n'
            if args.restart_splunk == "true"
            else 'echo "Restart skipped (--restart-splunk=false). Localpeer changes require a Splunk restart on ${HOST} to take effect."\n'
        )
    )
    return make_script(body)


def render_validate(args: argparse.Namespace) -> str:
    manager_uri = shell_quote(args.license_manager_uri)
    body = _lib_dir_block() + (
        f"MANAGER_URI={manager_uri}\n"
        + _SOURCE_LIB_BLOCK
        + (
            'TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)\n'
            'AUDIT_DIR="$(dirname "$0")/audit/${TIMESTAMP}"\n'
            "# license_usage_snapshot creates the dir 0700 and writes each\n"
            "# JSON payload with umask 077.\n"
            'license_usage_snapshot "${MANAGER_URI}" "${SK}" "${AUDIT_DIR}"\n'
            "\n"
            "# license_messages_check returns non-zero when ERROR-severity\n"
            "# messages are present and prints '<errors> <warns>' to stdout.\n"
            'set +e\n'
            'counts="$(license_messages_check "${MANAGER_URI}" "${SK}")"\n'
            'rc=$?\n'
            'set -e\n'
            'errors="$(echo "${counts}" | awk \'{print $1}\')"\n'
            'warns="$(echo "${counts}" | awk \'{print $2}\')"\n'
            "if [[ \"${rc}\" -ne 0 || \"${errors:-0}\" != \"0\" ]]; then\n"
            '  echo "FAIL: ${errors:-?} ERROR-severity license message(s). See ${AUDIT_DIR}/messages.json" >&2\n'
            "  exit 1\n"
            "fi\n"
            "if [[ \"${warns:-0}\" != \"0\" ]]; then\n"
            '  echo "WARN: ${warns} WARN-severity license message(s). See ${AUDIT_DIR}/messages.json" >&2\n'
            "fi\n"
            'echo "PASS: License manager validate complete. Snapshot: ${AUDIT_DIR}"\n'
        )
    )
    return make_script(body)


def render_all(args: argparse.Namespace) -> dict:
    parsed = validate_args(args)

    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "license"
    render_dir.mkdir(parents=True, exist_ok=True)

    # Clean previously generated top-level files.
    for rel in GENERATED_TOP_FILES:
        p = render_dir / rel
        if p.is_file() or p.is_symlink():
            p.unlink()

    files = []

    write_file(render_dir / "README.md", render_readme(args, parsed))
    files.append("README.md")
    write_file(render_dir / "metadata.json", render_metadata(args, parsed))
    files.append("metadata.json")

    manager_dir = render_dir / "manager"
    manager_dir.mkdir(parents=True, exist_ok=True)
    for stale in manager_dir.glob("*.sh"):
        stale.unlink()

    write_file(manager_dir / "install-licenses.sh", render_install_licenses(args, parsed), executable=True)
    files.append("manager/install-licenses.sh")
    write_file(manager_dir / "activate-group.sh", render_activate_group(args), executable=True)
    files.append("manager/activate-group.sh")

    pools_dir = manager_dir / "pools"
    if pools_dir.exists():
        for stale in pools_dir.glob("*.json"):
            stale.unlink()
    pools_dir.mkdir(parents=True, exist_ok=True)
    for pool in parsed["pool_specs"]:
        write_file(pools_dir / f"{pool['name']}.json", render_pool_json(pool))
        files.append(f"manager/pools/{pool['name']}.json")
    write_file(manager_dir / "apply-pools.sh", render_apply_pools(args, parsed), executable=True)
    files.append("manager/apply-pools.sh")

    peers_dir = render_dir / "peers"
    peers_dir.mkdir(parents=True, exist_ok=True)
    for host in parsed["peer_hosts"]:
        host_dir = peers_dir / host
        host_dir.mkdir(parents=True, exist_ok=True)
        write_file(host_dir / "peer-server.conf", render_peer_server_conf(args))
        files.append(f"peers/{host}/peer-server.conf")
        write_file(
            host_dir / "configure-peer.sh",
            render_configure_peer(args, host, args.peer_ssh_user),
            executable=True,
        )
        files.append(f"peers/{host}/configure-peer.sh")

    write_file(render_dir / "validate.sh", render_validate(args), executable=True)
    files.append("validate.sh")

    return {
        "render_dir": str(render_dir),
        "files": sorted(files),
        "parsed": parsed,
    }


def main() -> None:
    args = parse_args()
    if args.dry_run:
        parsed = validate_args(args)
        if args.json:
            print(json.dumps({"parsed": parsed}, indent=2, sort_keys=True))
        else:
            print(json.dumps(parsed, indent=2, sort_keys=True))
        return
    result = render_all(args)
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "parsed"}, indent=2, sort_keys=True))
    else:
        print(f"Rendered {len(result['files'])} license-manager asset(s) to {result['render_dir']}")
        for name in result["files"]:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
