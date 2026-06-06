#!/usr/bin/env python3
"""Render Splunk KV Store administration assets (backup/restore/migrate/resync)."""

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
    "status.sh",
    "backup.sh",
    "restore.sh",
    "migrate.sh",
    "resync.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk KV Store admin assets.")
    parser.add_argument("--deployment", choices=("standalone", "shc"), default="standalone")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--archive-name", default="kvstore_backup")
    parser.add_argument("--restore-archive-name", default="")
    parser.add_argument("--storage-engine", choices=("unset", "wiredTiger"), default="unset")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


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


def validate_archive_name(value: str, option: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value or ""):
        die(f"{option} must contain only letters, numbers, dot, underscore, and hyphen.")


def validate(args: argparse.Namespace) -> None:
    validate_archive_name(args.archive_name, "--archive-name")
    if args.restore_archive_name:
        validate_archive_name(args.restore_archive_name, "--restore-archive-name")
    if "\n" in (args.splunk_home or "") or "\r" in (args.splunk_home or ""):
        die("--splunk-home must not contain newlines.")


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk KV Store Admin Rendered Assets

Deployment: `{args.deployment}`
Splunk home: `{args.splunk_home}`
Backup archive name: `{args.archive_name}`
Storage engine target: `{args.storage_engine}`

Files:

- `status.sh` — read-only KV Store status and replication
- `backup.sh` — create a KV Store backup archive
- `restore.sh` — restore from a KV Store backup archive (review first)
- `migrate.sh` — migrate the KV Store storage engine (one-way)
- `resync.sh` — resync a stale SHC KV Store member (gated)
- `server.conf` — optional `[kvstore]` overrides

Order of operations:

1. `./status.sh` to capture current state.
2. `./backup.sh` to take a fresh backup.
3. Only then run restore, migrate, or resync, one member at a time on an SHC.

All verbs authenticate against splunkd. Authenticate interactively or pass
`-auth user:<password-from-file>` from a file you control. Never paste the
password into chat or argv.
"""


def render_status(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    return make_script(
        f"""splunk={splunk}
echo "== kvstore-status =="
"${{splunk}}" show kvstore-status --verbose
echo "== server.conf [kvstore] (btool) =="
"${{splunk}}" btool server list kvstore --debug 2>/dev/null || true
"""
    )


def render_backup(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    archive = shell_quote(args.archive_name)
    return make_script(
        f"""splunk={splunk}
archive_name={archive}
# Add -auth user:"$(cat /path/to/secret)" if not authenticating interactively.
"${{splunk}}" backup kvstore --archiveName "${{archive_name}}"
echo "Backup archive '${{archive_name}}' created under \\$SPLUNK_HOME/var/lib/splunk/kvstorebackup/."
"""
    )


def render_restore(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    restore_name = args.restore_archive_name or args.archive_name
    restore = shell_quote(restore_name)
    return make_script(
        f"""splunk={splunk}
splunk_home={shell_quote(args.splunk_home)}
archive_name={restore}
echo "Available KV Store backup archives:"
ls -1 "${{splunk_home}}/var/lib/splunk/kvstorebackup/" 2>/dev/null || echo "(none found under ${{splunk_home}}/var/lib/splunk/kvstorebackup/)"
echo
echo "About to restore KV Store from archive: ${{archive_name}}"
echo "This OVERWRITES current KV Store collection data. A fresh backup is strongly advised."
read -r -p "Type RESTORE to continue: " confirm
[[ "${{confirm}}" == "RESTORE" ]] || {{ echo "Aborted."; exit 1; }}
# Add -auth user:"$(cat /path/to/secret)" if not authenticating interactively.
"${{splunk}}" restore kvstore --archiveName "${{archive_name}}"
echo "Restore requested. Re-run status.sh to confirm collections and replication."
"""
    )


def render_migrate(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    return make_script(
        f"""splunk={splunk}
echo "Current KV Store engine:"
"${{splunk}}" show kvstore-status --verbose | grep -i -E 'storageEngine|serverVersion' || true
echo
echo "Migrating the KV Store storage engine to WiredTiger is ONE-WAY and requires a"
echo "maintenance window. Take a fresh backup first (./backup.sh)."
read -r -p "Type MIGRATE to continue: " confirm
[[ "${{confirm}}" == "MIGRATE" ]] || {{ echo "Aborted."; exit 1; }}
"${{splunk}}" migrate migrate-kvstore
echo "Migration requested. Re-run status.sh to confirm storageEngine = wiredTiger."
"""
    )


def render_resync(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    standalone_note = (
        ""
        if args.deployment == "shc"
        else 'echo "NOTE: resync is for search head cluster members; this host is rendered as standalone."\n'
    )
    return make_script(
        f"""splunk={splunk}
{standalone_note}echo "Resync rebuilds this member's KV Store from the SHC captain."
echo "Run this on ONE stale member at a time, never on the captain, and only after a backup."
read -r -p "Type RESYNC to continue: " confirm
[[ "${{confirm}}" == "RESYNC" ]] || {{ echo "Aborted."; exit 1; }}
"${{splunk}}" stop
"${{splunk}}" clean kvstore --local
"${{splunk}}" start
echo "Member cleaned and restarted; it will re-replicate from the captain."
echo "If the cluster requires it, run: splunk resync kvstore -auth ... on this member."
"""
    )


def render_server(args: argparse.Namespace) -> str:
    lines = ["# Rendered by splunk-kvstore-admin. Review before applying."]
    if args.storage_engine != "unset":
        lines.extend(
            [
                "[kvstore]",
                f"storageEngine = {args.storage_engine}",
                "# storageEngine changes require splunk migrate migrate-kvstore; see migrate.sh.",
                "",
            ]
        )
    else:
        lines.append("# No [kvstore] overrides requested. Defaults are recommended for most deployments.")
    return "\n".join(lines).rstrip() + "\n"


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "kvstore"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "deployment": args.deployment,
                    "splunk_home": args.splunk_home,
                    "archive_name": args.archive_name,
                    "restore_archive_name": args.restore_archive_name,
                    "storage_engine": args.storage_engine,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "server.conf": render_server(args),
            "status.sh": render_status(args),
            "backup.sh": render_backup(args),
            "restore.sh": render_restore(args),
            "migrate.sh": render_migrate(args),
            "resync.sh": render_resync(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "kvstore",
        "deployment": args.deployment,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "status": [["./status.sh"]],
            "backup": [["./backup.sh"]],
            "restore": [["./restore.sh"]],
            "migrate": [["./migrate.sh"]],
            "resync": [["./resync.sh"]],
        },
    }


def main() -> int:
    args = parse_args()
    validate(args)
    payload = render(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render KV Store admin assets under {payload['render_dir']}")
    else:
        print(f"Rendered KV Store admin assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
