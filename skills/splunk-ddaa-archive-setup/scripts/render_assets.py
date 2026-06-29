#!/usr/bin/env python3
"""Render Splunk Cloud Dynamic Data Active Archive (DDAA) assets."""

from __future__ import annotations

import argparse
import json
import re
import stat
from pathlib import Path

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "acs-payload.json",
    "restore-runbook.md",
    "disable-runbook.md",
    "status.sh",
}

MAX_ARCHIVE_DAYS = 3650


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Cloud DDAA archive assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--searchable-days", required=True)
    parser.add_argument("--archival-retention-days", required=True)
    parser.add_argument("--index-type", choices=("event", "metric"), default="event")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def validate(args: argparse.Namespace) -> tuple[int, int]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", args.index or ""):
        die("--index must be a valid Splunk index name (lowercase letters, numbers, underscore, hyphen).")
    if not re.fullmatch(r"[0-9]+", args.searchable_days or ""):
        die("--searchable-days must be a nonnegative integer.")
    if not re.fullmatch(r"[0-9]+", args.archival_retention_days or ""):
        die("--archival-retention-days must be a nonnegative integer.")
    searchable = int(args.searchable_days)
    archival = int(args.archival_retention_days)
    if archival <= searchable:
        die(
            "--archival-retention-days must be greater than --searchable-days "
            "(archival retention is the total retention including the searchable period)."
        )
    if archival > MAX_ARCHIVE_DAYS:
        die(f"--archival-retention-days must be <= {MAX_ARCHIVE_DAYS} (10 years).")
    return searchable, archival


def render_payload(args: argparse.Namespace, searchable: int, archival: int) -> str:
    return json.dumps(
        {
            "name": args.index,
            "datatype": args.index_type,
            "searchableDays": searchable,
            "splunkArchivalRetentionDays": archival,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_status(args: argparse.Namespace) -> str:
    return (
        "#!/usr/bin/env bash\nset -euo pipefail\n\n"
        "# Describe the index and its DDAA archival retention via ACS.\n"
        f'acs indexes describe "{args.index}" || '
        f'echo "Run: acs indexes describe {args.index}"\n'
    )


def render_restore_runbook(args: argparse.Namespace) -> str:
    return f"""# DDAA Restore Runbook ({args.index})

Restoring archived data is a Splunk Web operation; there is no ACS/API restore.

1. In Splunk Web, go to Settings > Indexes.
2. Find `{args.index}` and open the Restore action in the Actions column.
3. Choose the time range of archived data to restore.
4. Confirm. Restored data is copied into Dynamic Data Active Searchable (DDAS)
   and becomes searchable like any other data.

Notes:

- Restored data is searchable for 30 days, then Splunk removes it automatically.
  The archive copy is not deleted.
- You can restore up to 10% of your DDAS entitlement at any one time.
- To remove a restore early, use Clear in the Restore Archive window.
"""


def render_disable_runbook(args: argparse.Namespace) -> str:
    return f"""# DDAA Disable Runbook ({args.index})

You cannot disable DDAA, or switch between DDAA and DDSS, with the ACS API/CLI.

1. In Splunk Web, go to Settings > Indexes.
2. Edit `{args.index}`.
3. Change the Dynamic Data Storage setting away from Splunk Archive (DDAA).
4. Save.

Use this skill's ACS apply only to enable DDAA or change the archival retention
period (`splunkArchivalRetentionDays`) for an index.
"""


def render_readme(args: argparse.Namespace, searchable: int, archival: int) -> str:
    return f"""# Splunk Cloud DDAA Archive Rendered Assets

Index: `{args.index}`
Searchable days (DDAS): `{searchable}`
Archival retention days (total, DDAA): `{archival}`
Index type: `{args.index_type}`

Files:

- `acs-payload.json` - ACS create body (POST a NEW index): `name`, `datatype`,
  `searchableDays`, `splunkArchivalRetentionDays`. To enable/update DDAA on an
  EXISTING index, PATCH `/<stack>/adminconfig/v2/indexes/<name>` with only
  `splunkArchivalRetentionDays` (do not resend `searchableDays`).
- `restore-runbook.md` - UI-only restore steps (30-day searchable copy)
- `disable-runbook.md` - UI-only disable steps
- `status.sh` - `acs indexes describe {args.index}`

`splunkArchivalRetentionDays` is the TOTAL retention including the searchable
period, counted from index creation (not a rolling window). It must exceed
searchable days and be <= 3650 (10 years). Apply requires
`--accept-archive-retention`. Generic index lifecycle is handled by
`splunk-cloud-acs-admin-setup`; DDSS self-storage also lives there.
"""


def render(args: argparse.Namespace, searchable: int, archival: int) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "ddaa"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args, searchable, archival),
            "metadata.json": json.dumps(
                {
                    "index": args.index,
                    "index_type": args.index_type,
                    "searchable_days": searchable,
                    "archival_retention_days": archival,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "acs-payload.json": render_payload(args, searchable, archival),
            "restore-runbook.md": render_restore_runbook(args),
            "disable-runbook.md": render_disable_runbook(args),
            "status.sh": render_status(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "ddaa",
        "index": args.index,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
    }


def main() -> int:
    args = parse_args()
    searchable, archival = validate(args)
    payload = render(args, searchable, archival)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render DDAA archive assets under {payload['render_dir']}")
    else:
        print(f"Rendered DDAA archive assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
