#!/usr/bin/env python3
"""Render Splunk KV Store administration assets (backup/restore/migrate/upgrade/collections)."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "server.conf",
    "collections.conf",
    "transforms.conf",
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
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--topology", choices=("standalone", "shc"), default="standalone")
    parser.add_argument("--app-name", default="ZZZ_cisco_skills_kvstore")
    parser.add_argument("--point-in-time", choices=("true", "false"), default="true")
    parser.add_argument("--backup-archive-name", default="")
    parser.add_argument("--storage-engine", choices=("wiredTiger", "mmapv1"), default="wiredTiger")
    parser.add_argument("--migrate-dry-run", choices=("true", "false"), default="true")
    parser.add_argument("--target-kvstore-version", default="")
    parser.add_argument("--disable-startup-upgrade", choices=("true", "false"), default="false")
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


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


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
    if args.backup_archive_name and not re.fullmatch(r"[A-Za-z0-9._-]+", args.backup_archive_name):
        die("--backup-archive-name must contain only letters, numbers, dot, underscore, and hyphen.")
    if args.target_kvstore_version and not re.fullmatch(r"[0-9]+(\.[0-9]+){0,2}", args.target_kvstore_version):
        die("--target-kvstore-version must look like 7.0 or 8.0.x.")
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
    if bool_value(args.disable_startup_upgrade):
        lines.extend(
            [
                "[kvstore]",
                "# Prevent the automatic KV Store server-version upgrade on startup so you can",
                "# upgrade manually after backing up. Set on every SHC member before the binary upgrade.",
                "kvstoreUpgradeOnStartupEnabled = false",
                "",
            ]
        )
    else:
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
"""
    )


def render_backup(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    pit = "-pointInTime true" if bool_value(args.point_in_time) else ""
    return make_script(
        f"""splunk_home={splunk_home}
# Run as the splunk user after "${{splunk_home}}/bin/splunk" login.
# Point-in-time backups (-pointInTime true) are consistent; archives land in
# $SPLUNK_DB/kvstorebackup. Take one before every restore, migrate, or upgrade.
"${{splunk_home}}/bin/splunk" backup kvstore {pit}
"${{splunk_home}}/bin/splunk" show kvstore-status
"""
    )


def render_restore(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    archive = shell_quote(args.backup_archive_name) if args.backup_archive_name else "''"
    pit = "-pointInTime true" if bool_value(args.point_in_time) else ""
    maint = ""
    maint_after = ""
    if args.topology == "shc":
        maint = (
            '"${splunk_home}/bin/splunk" enable kvstore-maintenance-mode\n'
            'echo "Maintenance mode enabled on this SHC member."\n'
        )
        maint_after = (
            '"${splunk_home}/bin/splunk" disable kvstore-maintenance-mode\n'
            'echo "Maintenance mode disabled after successful restore."\n'
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
# DESTRUCTIVE: overwrites current KV Store data. On a search head cluster, run
# this from the captain; only one restore can run at a time across the cluster.
{maint}"${{splunk_home}}/bin/splunk" restore kvstore {pit} -archiveName "${{archive_name}}"
{maint_after}
"${{splunk_home}}/bin/splunk" show kvstore-status
"""
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
"""
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
"${{splunk_home}}/bin/splunk" start-shcluster-migration kvstore -storageEngine {args.storage_engine} {dry}
"${{splunk_home}}/bin/splunk" show kvstore-status
"""
        )
    return make_script(
        f"""splunk_home={splunk_home}
# Single-instance deployments migrate the storage engine automatically during the
# upgrade to Splunk Enterprise 9.0+. This script reports current status.
"${{splunk_home}}/bin/splunk" show kvstore-status
echo "Storage engine: {args.storage_engine} (single-instance migration is automatic on upgrade)."
"""
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
"${{splunk_home}}/bin/splunk" start-shcluster-upgrade kvstore -version "${{target_version}}"
"${{splunk_home}}/bin/splunk" show kvstore-status
"""
        )
    return make_script(
        f"""splunk_home={splunk_home}
# Single-instance deployments auto-upgrade the KV Store server version about 60
# seconds after the first start on a new Splunk Enterprise version. This reports status.
"${{splunk_home}}/bin/splunk" show kvstore-status
"""
    )


def render_status(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    return make_script(
        f"""splunk_home={splunk_home}
"${{splunk_home}}/bin/splunk" show kvstore-status
"${{splunk_home}}/bin/splunk" btool server list kvstore --debug 2>/dev/null || true
"""
    )


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk KV Store Admin Rendered Assets

Topology: `{args.topology}`
Splunk home: `{args.splunk_home}`
Point-in-time backup: `{args.point_in_time}`

Lifecycle host scripts (run as the splunk user after `splunk login`):

- `preflight.sh` - status + disk headroom; reminds you to back up first
- `backup.sh` - `splunk backup kvstore` (point-in-time when enabled)
- `restore.sh` - `splunk restore kvstore` (DESTRUCTIVE; captain on SHC)
- `clean.sh` - `splunk clean kvstore` (DESTRUCTIVE)
- `migrate.sh` - storage-engine migration (SHC `start-shcluster-migration`)
- `upgrade.sh` - server-version upgrade (SHC `start-shcluster-upgrade`)
- `status.sh` - `splunk show kvstore-status`

Governance config (apply with `--phase apply --operation collections`, written via REST):

- `collections.conf` - KV Store collection definition
- `transforms.conf` - KV Store lookup definition
- `server.conf` - optional `[kvstore] kvstoreUpgradeOnStartupEnabled = false`

Always take a point-in-time backup before a restore, migrate, or upgrade.
"""


def render(args: argparse.Namespace, fields: list[tuple[str, str]]) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "kvstore"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "topology": args.topology,
                    "splunk_home": args.splunk_home,
                    "app_name": args.app_name,
                    "point_in_time": args.point_in_time,
                    "storage_engine": args.storage_engine,
                    "target_kvstore_version": args.target_kvstore_version,
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
    return {
        "target": "kvstore",
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
