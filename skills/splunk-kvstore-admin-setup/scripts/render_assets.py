#!/usr/bin/env python3
"""Render Splunk KV Store administration assets (backup/restore/migrate/upgrade/collections)."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from render_bundle_ownership import ensure_canonical_bundle_compatible  # noqa: E402

BUNDLE_OWNER = "splunk-kvstore-admin-setup"

_SKILLS_ROOT = Path(__file__).resolve().parents[2]
_PLATFORM_VERSION_HELPERS = _SKILLS_ROOT / "shared" / "lib" / "platform_version_helpers.sh"
_SPV_VERSIONS_JSON = _SKILLS_ROOT / "shared" / "references" / "splunk_platform_versions.json"
_SPV_VERSIONS_PY = _SKILLS_ROOT / "shared" / "lib" / "platform_versions.py"
_SPV_BUNDLE_DIR = ".spv-bundle"
GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "server.conf",
    "collections.conf",
    "transforms.conf",
    "platform_version_helpers.sh",
    "preflight.sh",
    "backup.sh",
    "restore.sh",
    "clean.sh",
    "migrate.sh",
    "upgrade.sh",
    "status.sh",
}

FIELD_TYPES = {"number", "string", "bool", "time", "cidr"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk KV Store administration assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--platform", choices=("auto", "cloud", "enterprise"), default="auto")
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--topology", choices=("standalone", "shc"), default="standalone")
    parser.add_argument("--app-name", default="ZZZ_cisco_skills_kvstore")
    parser.add_argument("--point-in-time", choices=("", "true", "false"), default="")
    parser.add_argument("--backup-mode", choices=("auto", "parallel", "point-in-time", "legacy"), default="auto")
    parser.add_argument("--backup-archive-name", default="")
    parser.add_argument("--storage-engine", choices=("wiredTiger", "mmapv1"), default="wiredTiger")
    parser.add_argument("--migrate-dry-run", choices=("true", "false"), default="true")
    parser.add_argument("--target-kvstore-version", default="")
    parser.add_argument("--enterprise-version", default="", help="Expected installed Enterprise version for live checks (default: shared 10.6.0.5 for offline render metadata).")
    parser.add_argument("--disable-startup-upgrade", choices=("true", "false"), default="false")
    parser.add_argument("--defer-postgres-migration", choices=("true", "false"), default="false")
    parser.add_argument("--collection-name", default="")
    parser.add_argument("--collection-fields", default="")
    parser.add_argument("--collection-replicate", choices=("true", "false"), default="false")
    parser.add_argument("--lookup-definition-name", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def shared_enterprise_version() -> str:
    try:
        payload = json.loads(_SPV_VERSIONS_JSON.read_text(encoding="utf-8"))
        value = str((payload.get("defaults") or {}).get("enterprise_version") or "").strip()
    except (OSError, ValueError, TypeError):
        value = ""
    if not value:
        die("shared Enterprise version default is missing")
    return value


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


def bool_value(value: str) -> bool:
    return value.lower() == "true"


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str, *, platform: str, expected_enterprise_version: str = "", disable_startup_upgrade: bool = False) -> str:
    first, separator, remainder = body.lstrip().partition("\n")
    if not separator:
        die("internal renderer error: local script body has no runtime assignment")
    rendered_platform = shell_quote(platform)
    gate = f"""rendered_platform={rendered_platform}
runtime_platform="${{SPLUNK_PLATFORM:-${{rendered_platform}}}}"
if [[ "${{runtime_platform}}" == "cloud" ]]; then
  echo "ERROR: Managed Splunk Cloud owns KV Store host lifecycle operations; this rendered host script will not run." >&2
  echo "HANDOFF: Use Splunk Support for backup, restore, clean, migrate, upgrade, maintenance, or host status work." >&2
  exit 2
fi
[[ "${{runtime_platform}}" == "auto" || "${{runtime_platform}}" == "enterprise" ]] || {{ echo "ERROR: invalid SPLUNK_PLATFORM=${{runtime_platform}}" >&2; exit 1; }}
_script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
export SPV_SKILLS_ROOT="${{_script_dir}}/{_SPV_BUNDLE_DIR}"
_platform_helpers_default="${{_script_dir}}/platform_version_helpers.sh"
platform_helpers="${{SPLUNK_PLATFORM_VERSION_HELPERS:-${{_platform_helpers_default}}}}"
[[ -r "${{platform_helpers}}" ]] || {{ echo "ERROR: platform version helper is missing: ${{platform_helpers}}" >&2; exit 1; }}
# shellcheck disable=SC1090
source "${{platform_helpers}}"
runtime_home="${{splunk_home:-}}"
[[ -n "${{runtime_home}}" ]] || {{ echo "ERROR: rendered script did not set splunk_home." >&2; exit 1; }}
installed_version="$(spv_require_supported_splunk_home "${{runtime_home}}")"
echo "PASS: supported Splunk Enterprise runtime ${{installed_version}}."
expected_enterprise_version={shell_quote(expected_enterprise_version)}
if [[ -n "${{expected_enterprise_version}}" && "${{installed_version}}" != "${{expected_enterprise_version}}" ]]; then
  echo "ERROR: installed Splunk Enterprise version ${{installed_version}} does not match expected ${{expected_enterprise_version}}." >&2
  exit 1
fi
if [[ "{str(disable_startup_upgrade).lower()}" == "true" ]]; then
  if ! python3 - "${{installed_version}}" <<'PY'
import sys
parts = tuple(int(part) for part in sys.argv[1].split(".")[:2])
raise SystemExit(0 if parts < (10, 3) else 1)
PY
  then
    echo "ERROR: --disable-startup-upgrade true is removed and unsupported for Splunk Enterprise 10.3 and newer." >&2
    exit 1
  fi
fi
"""
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + first + "\n" + gate + remainder


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def parse_fields(value: str) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for item in (part.strip() for part in value.split(",") if part.strip()):
        if ":" not in item:
            die(f"--collection-fields entry {item!r} must be name:type (type one of {sorted(FIELD_TYPES)}).")
        name, ftype = (segment.strip() for segment in item.split(":", 1))
        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            die(f"Field name {name!r} must contain only letters, numbers, and underscores.")
        if ftype not in FIELD_TYPES:
            die(f"Field type {ftype!r} must be one of {sorted(FIELD_TYPES)}.")
        fields.append((name, ftype))
    return fields


def validate(args: argparse.Namespace) -> list[tuple[str, str]]:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    no_newline(args.backup_archive_name, "--backup-archive-name")
    if args.point_in_time and args.backup_mode != "auto":
        die("--point-in-time cannot be combined with an explicit --backup-mode.")
    if args.backup_archive_name and not re.fullmatch(r"[A-Za-z0-9._-]+", args.backup_archive_name):
        die("--backup-archive-name must contain only letters, numbers, dot, underscore, and hyphen.")
    if args.target_kvstore_version and not re.fullmatch(r"(?:7|8)\.0(?:\.[0-9]+)?", args.target_kvstore_version):
        die("--target-kvstore-version must be a supported 7.0 or 8.0.x KV Store server version.")
    if args.enterprise_version and not re.fullmatch(r"\d+\.\d+(?:\.\d+){0,2}", args.enterprise_version):
        die("--enterprise-version must be a numeric Enterprise version (for example 10.6.0.5).")
    if args.disable_startup_upgrade == "true":
        version_for_policy = args.enterprise_version or shared_enterprise_version()
        major, minor = (int(part) for part in version_for_policy.split(".", 2)[:2])
        if (major, minor) >= (10, 3):
            die("--disable-startup-upgrade true is removed and unsupported for Splunk Enterprise 10.3 and newer.")
    fields = parse_fields(args.collection_fields)
    if args.collection_name and not re.fullmatch(r"[A-Za-z0-9_]+", args.collection_name):
        die("--collection-name must contain only letters, numbers, and underscores.")
    if args.collection_fields and not args.collection_name:
        die("--collection-fields requires --collection-name.")
    if args.lookup_definition_name:
        if not args.collection_name:
            die("--lookup-definition-name requires --collection-name.")
        if not re.fullmatch(r"[A-Za-z0-9_]+", args.lookup_definition_name):
            die("--lookup-definition-name must contain only letters, numbers, and underscores.")
    return fields


def render_server(args: argparse.Namespace) -> str:
    lines = ["# Rendered by splunk-kvstore-admin-setup. Review before applying."]
    defer_postgres = bool_value(args.defer_postgres_migration)
    disable_startup_upgrade = bool_value(args.disable_startup_upgrade)
    if defer_postgres or disable_startup_upgrade:
        lines.append("[kvstore]")
    if defer_postgres:
        lines.extend(
            [
                "# Enterprise 10.4 pre-upgrade control: defer Enterprise 10.6's",
                "# cohosted PostgreSQL migration. Review and distribute before upgrade.",
                "postgresMigrateOnStartup = false",
            ]
        )
    if disable_startup_upgrade:
        lines.extend(
            [
                "# Prevent the automatic KV Store server-version upgrade on startup so you can",
                "# upgrade manually after backing up. Set on every SHC member before the binary upgrade.",
                "kvstoreUpgradeOnStartupEnabled = false",
            ]
        )
    if not defer_postgres and not disable_startup_upgrade:
        lines.append("# No server.conf [kvstore] overrides requested.")
    return "\n".join(lines).rstrip() + "\n"


def render_collections(args: argparse.Namespace, fields: list[tuple[str, str]]) -> str:
    lines = ["# Rendered by splunk-kvstore-admin-setup. Review before applying."]
    if not args.collection_name:
        lines.append("# No KV Store collection requested.")
        return "\n".join(lines) + "\n"
    lines.append(f"[{args.collection_name}]")
    lines.append(f"replicate = {args.collection_replicate}")
    for name, ftype in fields:
        lines.append(f"field.{name} = {ftype}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_transforms(args: argparse.Namespace, fields: list[tuple[str, str]]) -> str:
    lines = ["# Rendered by splunk-kvstore-admin-setup. Review before applying."]
    if not args.lookup_definition_name:
        lines.append("# No KV Store lookup definition requested.")
        return "\n".join(lines) + "\n"
    field_names = ["_key", *[name for name, _ in fields]]
    lines.extend(
        [
            f"[{args.lookup_definition_name}]",
            "external_type = kvstore",
            f"collection = {args.collection_name}",
            f"fields_list = {', '.join(field_names)}",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_preflight(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    return make_script(
        f"""splunk_home={splunk_home}
# Authenticate first with: "${{splunk_home}}/bin/splunk" login
test -x "${{splunk_home}}/bin/splunk"
"${{splunk_home}}/bin/splunk" show kvstore-status
df -h "${{splunk_home}}/var/lib/splunk" 2>/dev/null || true
echo "Preflight complete. Take a backup before any restore, migrate, or upgrade."
""",
        platform=args.platform,
        expected_enterprise_version=args.enterprise_version,
        disable_startup_upgrade=bool_value(args.disable_startup_upgrade),
    )


def kvstore_status_helpers() -> str:
    return r'''status_file=""
cleanup_status_file() { [[ -z "${status_file}" ]] || rm -f "${status_file}"; }
trap cleanup_status_file EXIT
read_kvstore_status() {
  [[ -n "${status_file}" ]] || status_file="$(mktemp)"
  : >"${status_file}"
  if ! "${splunk_home}/bin/splunk" show kvstore-status >"${status_file}"; then
    echo "ERROR: authenticated kvstore-status query failed; refusing to select a backup mode." >&2
    return 1
  fi
}
status_summary() {
  # Handles the CLI's nested "Service Info" type:Pdl section as well as JSON.
  python3 - "${status_file}" <<'PY'
import json, sys
from pathlib import Path
raw = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
start = raw.find("{")
try:
    payload = json.loads(raw[start:]) if start >= 0 else {}
except Exception:
    payload = {}
if not payload:
    import re
    lower = raw.lower()
    marker = lower.find("cohosted kvstore information")
    member_text = raw[:marker] if marker >= 0 else raw
    cohosted_text = raw[marker:] if marker >= 0 else ""
    def value(text, key):
        match = re.search(r"(?im)^\s*" + re.escape(key) + r"\s*:\s*([^\s]+)", text)
        return match.group(1).lower() if match else "unknown"
    ctype = "pdl" if re.search(r"(?i)\btype\s*:\s*pdl\b", cohosted_text) else "unknown"
    mode = "cohosted" if ctype == "pdl" else ("legacy" if marker < 0 else "unknown")
    print("\t".join((mode, value(member_text, "status"), value(cohosted_text, "status"), value(raw, "backupRestoreStatus"), value(member_text, "storageEngine"), value(member_text, "version"))))
    raise SystemExit(0)
def find_content(value):
    if isinstance(value, dict):
        if isinstance(value.get("content"), dict): return value["content"]
        for child in value.values():
            found = find_content(child)
            if found is not None: return found
    elif isinstance(value, list):
        for child in value:
            found = find_content(child)
            if found is not None: return found
    return None
content = find_content(payload) or payload
current = content.get("current", content) if isinstance(content, dict) else {}
if not isinstance(current, dict): current = {}
cohosted = {}
if isinstance(content, dict):
    for key in ("cohosted", "cohostedKVStore", "cohostedKVStoreInformation"):
        if isinstance(content.get(key), dict): cohosted = content[key]; break
if not cohosted and isinstance(current.get("cohosted"), dict): cohosted = current["cohosted"]
def find_type(value):
    if isinstance(value, dict):
        if "type" in value: return value["type"]
        for child in value.values():
            found = find_type(child)
            if found is not None: return found
    elif isinstance(value, list):
        for child in value:
            found = find_type(child)
            if found is not None: return found
    return None
ctype = str(find_type(cohosted) or "unknown")
cstatus = str(cohosted.get("status", "unknown")).lower()
mstatus = str(current.get("status", "unknown")).lower()
backup = "unknown"
def walk(value):
    global backup
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() == "backuprestorestatus":
                if isinstance(child, dict): child = child.get("status", child.get("state", "unknown"))
                backup = str(child).lower()
            walk(child)
    elif isinstance(value, list):
        for child in value: walk(child)
walk(payload)
engine = str(current.get("storageEngine", "unknown")).lower()
version = str(current.get("version", "unknown")).lower()
mode = "cohosted" if ctype.lower() == "pdl" else ("legacy" if not cohosted else "unknown")
print("\t".join((mode, mstatus, cstatus, backup, engine, version)))
PY
}
select_backup_mode() {
  local mode member_status cohosted_status backup_status
  IFS=$'\t' read -r mode member_status cohosted_status backup_status storage_engine kv_version <<<"$(status_summary)"
  [[ "${member_status}" == "ready" ]] || { echo "ERROR: KV Store member status is ${member_status}; refusing backup/restore." >&2; return 1; }
  if [[ "${mode}" == "cohosted" && "${cohosted_status}" != "ready" ]]; then
    echo "ERROR: cohosted KV Store type Pdl is ${cohosted_status}; refusing backup/restore." >&2
    return 1
  fi
  case "${requested_backup_mode}" in
    auto) case "${mode}" in cohosted) selected_backup_mode="parallel" ;; legacy) selected_backup_mode="point-in-time" ;; *) echo "ERROR: KV Store status did not identify a legacy or cohosted store." >&2; return 1 ;; esac ;;
    parallel) [[ "${mode}" == "cohosted" || "${mode}" == "legacy" ]] || { echo "ERROR: parallel backup/restore requires a positively identified KV Store type." >&2; return 1; }; selected_backup_mode="parallel" ;;
    point-in-time|legacy) [[ "${mode}" == "legacy" ]] || { echo "ERROR: explicit point-in-time/legacy mode is unsupported for cohosted or unidentified KV Store status; use --backup-mode parallel for type Pdl." >&2; return 1; }; selected_backup_mode="${requested_backup_mode}" ;;
    *) echo "ERROR: invalid backup mode ${requested_backup_mode}." >&2; return 1 ;;
  esac
  echo "Selected KV Store backup mode: ${selected_backup_mode} (member=${member_status}, cohosted=${cohosted_status})."
}
require_legacy_migration_state() {
  local requested_engine="$1"
  local mode member_status cohosted_status backup_status storage_engine kv_version
  IFS=$'\t' read -r mode member_status cohosted_status backup_status storage_engine kv_version <<<"$(status_summary)"
  [[ "${member_status}" == "ready" ]] || { echo "ERROR: KV Store member status is ${member_status}; refusing migration." >&2; return 1; }
  [[ "${mode}" == "legacy" && "${cohosted_status}" == "unknown" ]] || { echo "ERROR: storage-engine migration requires a positively identified legacy KV Store; cohosted Pdl is already migrated." >&2; return 1; }
  [[ "${requested_engine}" == "wiredTiger" ]] || { echo "ERROR: only migration to wiredTiger is supported." >&2; return 1; }
  case "${storage_engine}" in
    mmapv1|mmap_v1) ;;
    wiredtiger) echo "ERROR: KV Store is already using WiredTiger; refusing migration." >&2; return 1 ;;
    *) echo "ERROR: KV Store storage engine is unknown; refusing migration." >&2; return 1 ;;
  esac
}
require_legacy_upgrade_state() {
  local requested_version="$1"
  local mode member_status cohosted_status backup_status storage_engine kv_version
  IFS=$'\t' read -r mode member_status cohosted_status backup_status storage_engine kv_version <<<"$(status_summary)"
  [[ "${member_status}" == "ready" ]] || { echo "ERROR: KV Store member status is ${member_status}; refusing server-version upgrade." >&2; return 1; }
  [[ "${mode}" == "legacy" && "${cohosted_status}" == "unknown" ]] || { echo "ERROR: server-version upgrade requires a positively identified legacy KV Store; cohosted Pdl is upgraded automatically by Enterprise 10.6." >&2; return 1; }
  [[ "${storage_engine}" == "wiredtiger" ]] || { echo "ERROR: server-version upgrade requires a verified WiredTiger KV Store engine; storage engine is ${storage_engine}." >&2; return 1; }
  local current_major
  if [[ "${kv_version}" =~ ^4\.2([.][0-9]+)?$ ]]; then
    current_major="4.2"
  elif [[ "${kv_version}" =~ ^(7|8)\.0([.][0-9]+)?$ ]]; then
    current_major="${BASH_REMATCH[1]}"
  else
    echo "ERROR: KV Store server version is unknown or unsupported; refusing upgrade." >&2
    return 1
  fi
  [[ "${requested_version}" =~ ^(7|8)\.0([.][0-9]+)?$ ]] || { echo "ERROR: requested KV Store server version is unsupported." >&2; return 1; }
  local requested_major="${BASH_REMATCH[1]}"
  local enterprise_major="${installed_version%%.*}"
  local enterprise_minor="${installed_version#*.}"
  enterprise_minor="${enterprise_minor%%.*}"
  if (( enterprise_major < 9 || (enterprise_major == 9 && enterprise_minor < 4) )); then
    echo "ERROR: KV Store server-version upgrade is unsupported on Enterprise ${installed_version}." >&2
    return 1
  fi
  if [[ "${requested_major}" == "8" ]] && (( enterprise_major < 10 || (enterprise_major == 10 && enterprise_minor < 2) )); then
    echo "ERROR: KV Store server version 8.0 requires Enterprise 10.2 or newer." >&2
    return 1
  fi
  # Splunk 10.2 documents both 4.2->8.0 directly and 7.0->8.0; 4.2->7.0
  # remains the supported path for older Enterprise releases.
  if [[ "${current_major}" == 4.2 && ( "${requested_major}" == 7 || "${requested_major}" == 8 ) ]] || [[ "${current_major}" == 7 && "${requested_major}" == 8 ]]; then
    :
  else
    echo "ERROR: only the supported KV Store server-version transitions 4.2 to 7.0, 4.2 to 8.0, or 7.0 to 8.0 are allowed." >&2
    return 1
  fi
}
wait_for_backup_restore() {
  validate_polling_env
  local deadline=$((SECONDS + KVSTORE_BACKUP_STATUS_TIMEOUT_SECONDS))
  local mode member_status cohosted_status backup_status
  while (( SECONDS < deadline )); do
    read_kvstore_status || return 1
    IFS=$'\t' read -r mode member_status cohosted_status backup_status storage_engine kv_version <<<"$(status_summary)"
    case "${backup_status}" in
      ready) [[ "${member_status}" == "ready" && ( "${mode}" != "cohosted" || "${cohosted_status}" == "ready" ) ]] || { echo "ERROR: KV Store ${backup_restore_operation} reports Ready but readiness is incomplete (member=${member_status}, cohosted=${cohosted_status})." >&2; return 1; }; echo "PASS: KV Store ${backup_restore_operation} completed (backupRestoreStatus=Ready)."; return 0 ;;
      failed|failure|error) echo "ERROR: KV Store ${backup_restore_operation} failed (backupRestoreStatus=${backup_status})." >&2; return 1 ;;
    esac
    sleep "${KVSTORE_BACKUP_STATUS_POLL_SECONDS}"
  done
  echo "ERROR: KV Store ${backup_restore_operation} did not reach a completed backupRestoreStatus within the bounded timeout." >&2
  return 1
}
validate_polling_env() {
  local timeout="${KVSTORE_BACKUP_STATUS_TIMEOUT_SECONDS:-60}"
  local interval="${KVSTORE_BACKUP_STATUS_POLL_SECONDS:-2}"
  [[ "${timeout}" =~ ^[0-9]+$ && "${timeout}" -ge 1 && "${timeout}" -le 3600 ]] || { echo "ERROR: KVSTORE_BACKUP_STATUS_TIMEOUT_SECONDS must be an integer from 1 to 3600." >&2; return 1; }
  [[ "${interval}" =~ ^[0-9]+$ && "${interval}" -ge 1 && "${interval}" -le 60 ]] || { echo "ERROR: KVSTORE_BACKUP_STATUS_POLL_SECONDS must be an integer from 1 to 60." >&2; return 1; }
  KVSTORE_BACKUP_STATUS_TIMEOUT_SECONDS="${timeout}"
  KVSTORE_BACKUP_STATUS_POLL_SECONDS="${interval}"
}
'''


def render_backup(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    requested_mode = args.backup_mode
    if args.point_in_time:
        requested_mode = "point-in-time" if bool_value(args.point_in_time) else "legacy"
    archive = shell_quote(args.backup_archive_name) if args.backup_archive_name else "''"
    return make_script(
        f"""splunk_home={splunk_home}
# Run as the splunk user after "${{splunk_home}}/bin/splunk" login.
requested_backup_mode={shell_quote(requested_mode)}
backup_archive_name={archive}
{kvstore_status_helpers()}
read_kvstore_status
select_backup_mode
if [[ "${{selected_backup_mode}}" == "parallel" && -z "${{backup_archive_name}}" ]]; then
  echo "ERROR: parallel backup requires --backup-archive-name NAME (without .tar.gz)." >&2
  exit 1
fi
backup_archive_args=()
if [[ -n "${{backup_archive_name}}" ]]; then
  backup_archive_args=(-archiveName "${{backup_archive_name%.tar.gz}}")
fi
case "${{selected_backup_mode}}" in
  parallel) "${{splunk_home}}/bin/splunk" backup kvstore -backupParallelJobs true "${{backup_archive_args[@]}}" ;;
  point-in-time) "${{splunk_home}}/bin/splunk" backup kvstore -pointInTime true "${{backup_archive_args[@]}}" ;;
  legacy) "${{splunk_home}}/bin/splunk" backup kvstore "${{backup_archive_args[@]}}" ;;
esac
backup_restore_operation=backup
wait_for_backup_restore
"${{splunk_home}}/bin/splunk" show kvstore-status
""",
        platform=args.platform,
        expected_enterprise_version=args.enterprise_version,
        disable_startup_upgrade=bool_value(args.disable_startup_upgrade),
    )


def render_restore(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    archive = shell_quote(args.backup_archive_name) if args.backup_archive_name else "''"
    requested_mode = args.backup_mode
    if args.point_in_time:
        requested_mode = "point-in-time" if bool_value(args.point_in_time) else "legacy"
    maint = ""
    maint_after = ""
    if args.topology == "shc":
        maint = (
            'maintenance_enabled=false\n'
            'if [[ "${selected_backup_mode}" == "point-in-time" ]]; then\n'
            '  "${splunk_home}/bin/splunk" enable kvstore-maintenance-mode\n'
            '  echo "Maintenance mode enabled on this SHC member for point-in-time restore."\n'
            '  maintenance_enabled=true\n'
            'fi\n'
        )
        maint_after = (
            'if [[ "${maintenance_enabled}" == "true" ]]; then\n'
            '  "${splunk_home}/bin/splunk" disable kvstore-maintenance-mode\n'
            '  echo "Maintenance mode disabled after successful point-in-time restore."\n'
            'fi\n'
        )
    return make_script(
        f"""splunk_home={splunk_home}
archive_name={archive}
if [[ -z "${{archive_name}}" ]]; then
  echo "ERROR: backup archive name is required for restore (include the .tar.gz extension)." >&2
  exit 1
fi
if [[ "${{KVSTORE_ACCEPT_RESTORE:-false}}" != "true" ]]; then
  echo "ERROR: restore requires KVSTORE_ACCEPT_RESTORE=true (normally set by --accept-kvstore-restore)." >&2
  exit 1
fi
# DESTRUCTIVE: overwrites current KV Store data. Ensure collections.conf and
# transforms.conf definitions are distributed and effective before restoring;
# restore does not create missing collection definitions. On a search head
# cluster, run this from the captain; only one restore can run at a time.
requested_backup_mode={shell_quote(requested_mode)}
{kvstore_status_helpers()}
read_kvstore_status
select_backup_mode
restore_archive_name="${{archive_name}}"
if [[ "${{restore_archive_name}}" != *.tar.gz ]]; then
  restore_archive_name="${{restore_archive_name}}.tar.gz"
fi
{maint}case "${{selected_backup_mode}}" in
  parallel) "${{splunk_home}}/bin/splunk" restore kvstore -restoreParallelJobs true -archiveName "${{restore_archive_name}}" ;;
  point-in-time) "${{splunk_home}}/bin/splunk" restore kvstore -pointInTime true -archiveName "${{restore_archive_name}}" ;;
  legacy) "${{splunk_home}}/bin/splunk" restore kvstore -archiveName "${{restore_archive_name}}" ;;
esac
backup_restore_operation=restore
wait_for_backup_restore
{maint_after}
"${{splunk_home}}/bin/splunk" show kvstore-status
""",
        platform=args.platform,
        expected_enterprise_version=args.enterprise_version,
        disable_startup_upgrade=bool_value(args.disable_startup_upgrade),
    )


def render_clean(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    scope = "--cluster" if args.topology == "shc" else "--local"
    return make_script(
        f"""splunk_home={splunk_home}
# DESTRUCTIVE: permanently deletes KV Store data. Take a backup first.
if [[ "${{KVSTORE_ACCEPT_CLEAN:-false}}" != "true" ]]; then
  echo "ERROR: clean requires KVSTORE_ACCEPT_CLEAN=true (normally set by --accept-kvstore-clean)." >&2
  exit 1
fi
"${{splunk_home}}/bin/splunk" clean kvstore {scope}
"${{splunk_home}}/bin/splunk" show kvstore-status
""",
        platform=args.platform,
        expected_enterprise_version=args.enterprise_version,
        disable_startup_upgrade=bool_value(args.disable_startup_upgrade),
    )


def render_migrate(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    if args.topology == "shc":
        dry = "-isDryRun true" if bool_value(args.migrate_dry_run) else ""
        acceptance_gate = ""
        if not bool_value(args.migrate_dry_run):
            acceptance_gate = """if [[ "${KVSTORE_ACCEPT_MIGRATION:-false}" != "true" ]]; then
  echo "ERROR: migration requires KVSTORE_ACCEPT_MIGRATION=true (normally set by --accept-kvstore-migrate)." >&2
  exit 1
fi
"""
        return make_script(
            f"""splunk_home={splunk_home}
# Migrate the SHC KV Store storage engine. Run the dry run first, then re-run
# without -isDryRun to perform the migration. Coordinate across all members.
{acceptance_gate}
{kvstore_status_helpers()}
read_kvstore_status
require_legacy_migration_state {shell_quote(args.storage_engine)}
"${{splunk_home}}/bin/splunk" start-shcluster-migration kvstore -storageEngine {args.storage_engine} {dry}
"${{splunk_home}}/bin/splunk" show kvstore-status
""",
            platform=args.platform,
            expected_enterprise_version=args.enterprise_version,
            disable_startup_upgrade=bool_value(args.disable_startup_upgrade),
        )
    return make_script(
        f"""splunk_home={splunk_home}
# Single-instance deployments migrate the storage engine automatically during the
# upgrade to Splunk Enterprise 9.0+. This script reports current status.
"${{splunk_home}}/bin/splunk" show kvstore-status
echo "Storage engine: {args.storage_engine} (single-instance migration is automatic on upgrade)."
""",
        platform=args.platform,
        expected_enterprise_version=args.enterprise_version,
        disable_startup_upgrade=bool_value(args.disable_startup_upgrade),
    )


def render_upgrade(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    version = shell_quote(args.target_kvstore_version) if args.target_kvstore_version else "''"
    if args.topology == "shc":
        return make_script(
            f"""splunk_home={splunk_home}
target_version={version}
if [[ -z "${{target_version}}" ]]; then
  echo "ERROR: --target-kvstore-version is required to upgrade an SHC KV Store (e.g. 7.0 or 8.0)." >&2
  exit 1
fi
if [[ "${{KVSTORE_ACCEPT_UPGRADE:-false}}" != "true" ]]; then
  echo "ERROR: upgrade requires KVSTORE_ACCEPT_UPGRADE=true (normally set by --accept-kvstore-upgrade)." >&2
  exit 1
fi
# Upgrade the SHC KV Store server version after all members run the same Splunk
# Enterprise version. Take a backup first.
{kvstore_status_helpers()}
read_kvstore_status
require_legacy_upgrade_state "${{target_version}}"
"${{splunk_home}}/bin/splunk" start-shcluster-upgrade kvstore -version "${{target_version}}"
"${{splunk_home}}/bin/splunk" show kvstore-status
""",
            platform=args.platform,
            expected_enterprise_version=args.enterprise_version,
            disable_startup_upgrade=bool_value(args.disable_startup_upgrade),
        )
    return make_script(
        f"""splunk_home={splunk_home}
# Single-instance deployments auto-upgrade the KV Store server version about 60
# seconds after the first start on a new Splunk Enterprise version. This reports status.
"${{splunk_home}}/bin/splunk" show kvstore-status
""",
        platform=args.platform,
        expected_enterprise_version=args.enterprise_version,
        disable_startup_upgrade=bool_value(args.disable_startup_upgrade),
    )


def render_status(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    return make_script(
        f"""splunk_home={splunk_home}
"${{splunk_home}}/bin/splunk" show kvstore-status
"${{splunk_home}}/bin/splunk" btool server list kvstore --debug 2>/dev/null || true
""",
        platform=args.platform,
        expected_enterprise_version=args.enterprise_version,
        disable_startup_upgrade=bool_value(args.disable_startup_upgrade),
    )


def render_readme(args: argparse.Namespace) -> str:
    enterprise_version = args.enterprise_version or shared_enterprise_version()
    return f"""# Splunk KV Store Admin Rendered Assets

Platform: `{args.platform}`
Topology: `{args.topology}`
Splunk home: `{args.splunk_home}`
Enterprise version expectation: `{enterprise_version}` (offline default; live scripts always verify the installed supported train)
Point-in-time backup: `{args.point_in_time}`
Backup mode: `{args.backup_mode}` (`auto` selects parallel for a ready cohosted
PostgreSQL/Pdl store and point-in-time for a legacy store)

Lifecycle host scripts (run as the splunk user after `splunk login`):

- `preflight.sh` - status + disk headroom; reminds you to back up first
- `backup.sh` - status-selected `splunk backup kvstore` (parallel cohosted or point-in-time legacy)
- `restore.sh` - `splunk restore kvstore` (DESTRUCTIVE; captain on SHC)
- `clean.sh` - `splunk clean kvstore` (DESTRUCTIVE)
- `migrate.sh` - storage-engine migration (SHC `start-shcluster-migration`)
- `upgrade.sh` - server-version upgrade (SHC `start-shcluster-upgrade`)
- `status.sh` - `splunk show kvstore-status`

Distribute `collections.conf` and `transforms.conf` definitions and verify they
are effective before restoring data; restore does not create missing collection
definitions. A restore on an SHC must run from the captain in maintenance mode.

Governance config (apply with `--phase apply --operation collections`, written via REST):

- `collections.conf` - KV Store collection definition
- `transforms.conf` - KV Store lookup definition
- `server.conf` - optional `[kvstore] kvstoreUpgradeOnStartupEnabled = false`

`auto` requires an authenticated ready status. Cohosted PostgreSQL/Pdl uses
parallel jobs and has a bounded consistency window; legacy KV Store uses the
consistent point-in-time path. Explicit point-in-time mode refuses a cohosted
store rather than silently downgrading its guarantee. Set
`KVSTORE_BACKUP_STATUS_TIMEOUT_SECONDS` and `KVSTORE_BACKUP_STATUS_POLL_SECONDS`
to tune bounded completion polling.

Managed Splunk Cloud owns every host lifecycle operation listed above. When
rendered with `--platform cloud`, those scripts exit `2` before invoking the
Splunk CLI. Only collection and lookup knowledge-object governance can use the
Cloud REST apply path from this skill.
"""


def render(args: argparse.Namespace, fields: list[tuple[str, str]]) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "kvstore"
    ensure_canonical_bundle_compatible(
        render_dir,
        canonical=BUNDLE_OWNER,
        generated_files=GENERATED_FILES,
        write=not args.dry_run,
    )
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "platform": args.platform,
                    "topology": args.topology,
                    "splunk_home": args.splunk_home,
                    "app_name": args.app_name,
                    "point_in_time": args.point_in_time,
                    "backup_mode": args.backup_mode,
                    "storage_engine": args.storage_engine,
                    "target_kvstore_version": args.target_kvstore_version,
                    "enterprise_version": args.enterprise_version or shared_enterprise_version(),
                    "defer_postgres_migration": args.defer_postgres_migration,
                    "collection_name": args.collection_name,
                    "lookup_definition_name": args.lookup_definition_name,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "server.conf": render_server(args),
            "collections.conf": render_collections(args, fields),
            "transforms.conf": render_transforms(args, fields),
            "preflight.sh": render_preflight(args),
            "backup.sh": render_backup(args),
            "restore.sh": render_restore(args),
            "clean.sh": render_clean(args),
            "migrate.sh": render_migrate(args),
            "upgrade.sh": render_upgrade(args),
            "status.sh": render_status(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
        spv_refs = render_dir / _SPV_BUNDLE_DIR / "shared" / "references"
        spv_lib = render_dir / _SPV_BUNDLE_DIR / "shared" / "lib"
        spv_refs.mkdir(parents=True, exist_ok=True)
        spv_lib.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_SPV_VERSIONS_JSON, spv_refs / "splunk_platform_versions.json")
        shutil.copy2(_SPV_VERSIONS_PY, spv_lib / "platform_versions.py")
        shutil.copy2(_PLATFORM_VERSION_HELPERS, render_dir / "platform_version_helpers.sh")
        assets.append("platform_version_helpers.sh")
        assets.append(f"{_SPV_BUNDLE_DIR}/shared/references/splunk_platform_versions.json")
        assets.append(f"{_SPV_BUNDLE_DIR}/shared/lib/platform_versions.py")
    return {
        "target": "kvstore",
        "platform": args.platform,
        "topology": args.topology,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "preflight": [["./preflight.sh"]],
            "backup": [["./backup.sh"]],
            "restore": [["./restore.sh"]],
            "clean": [["./clean.sh"]],
            "migrate": [["./migrate.sh"]],
            "upgrade": [["./upgrade.sh"]],
            "status": [["./status.sh"]],
        },
    }


def main() -> int:
    args = parse_args()
    fields = validate(args)
    payload = render(args, fields)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render KV Store admin assets under {payload['render_dir']}")
    else:
        print(f"Rendered KV Store admin assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
