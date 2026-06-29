#!/usr/bin/env python3
"""Render Splunk Cloud DDAA (Dynamic Data Active Archive) lifecycle assets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path

MAX_ARCHIVE_RETENTION_DAYS = 3650

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "create-payload.json",
    "patch-payload.json",
    "enable-ddaa.sh",
    "status.sh",
    "restore.sh",
    "audit.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Cloud DDAA lifecycle assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--stack", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--datatype", choices=("event", "metric"), default="event")
    parser.add_argument("--searchable-days", required=True)
    parser.add_argument("--archival-retention-days", required=True)
    parser.add_argument("--max-data-size-mb", default="")
    parser.add_argument("--operation", choices=("enable", "update", "create", "plan"), default="enable")
    parser.add_argument("--token-file", default="/tmp/acs_token")
    parser.add_argument("--acs-base", default="https://admin.splunk.com")
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


def int_arg(value: str, option: str) -> int:
    if not re.fullmatch(r"[0-9]+", value or ""):
        die(f"{option} must be a positive integer.")
    return int(value)


def validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.stack or ""):
        die("--stack must be a valid Splunk Cloud stack name.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", args.index or ""):
        die("--index must be a valid Splunk index name (lowercase letters, numbers, underscore, hyphen).")
    if "kvstore" in args.index:
        die("--index must not contain 'kvstore'.")
    searchable = int_arg(args.searchable_days, "--searchable-days")
    archival = int_arg(args.archival_retention_days, "--archival-retention-days")
    if args.max_data_size_mb:
        int_arg(args.max_data_size_mb, "--max-data-size-mb")
    if archival <= searchable:
        die(
            "--archival-retention-days must be GREATER than --searchable-days "
            "(it is the total retention including searchable days)."
        )
    if archival > MAX_ARCHIVE_RETENTION_DAYS:
        die(f"--archival-retention-days must be <= {MAX_ARCHIVE_RETENTION_DAYS} (10 years).")
    if "\n" in (args.token_file or "") or "\r" in (args.token_file or ""):
        die("--token-file must not contain newlines.")
    if not args.acs_base.startswith("https://"):
        die("--acs-base must be an https URL.")


def create_payload(args: argparse.Namespace) -> dict:
    payload = {
        "name": args.index,
        "datatype": args.datatype,
        "searchableDays": int(args.searchable_days),
        "splunkArchivalRetentionDays": int(args.archival_retention_days),
    }
    if args.max_data_size_mb:
        payload["maxDataSizeMB"] = int(args.max_data_size_mb)
    return payload


def patch_payload(args: argparse.Namespace) -> dict:
    return {"splunkArchivalRetentionDays": int(args.archival_retention_days)}


def render_enable(args: argparse.Namespace) -> str:
    token_file = shell_quote(str(Path(args.token_file).expanduser()))
    base = shell_quote(args.acs_base.rstrip("/"))
    stack = shell_quote(args.stack)
    operation = args.operation
    method = "POST" if operation == "create" else "PATCH"
    payload_file = "create-payload.json" if operation == "create" else "patch-payload.json"
    url_suffix = "" if operation == "create" else f"/{args.index}"
    return make_script(
        f"""token_file={token_file}
acs_base={base}
stack={stack}
operation={shell_quote(operation)}
[[ -s "${{token_file}}" ]] || {{ echo "ERROR: ACS token file missing or empty: ${{token_file}}" >&2; exit 1; }}

if [[ "${{operation}}" == "plan" ]]; then
  echo "Plan only: review {payload_file} and run with --operation enable|update|create to apply."
  exit 0
fi

url="${{acs_base}}/${{stack}}/adminconfig/v2/indexes{url_suffix}"
echo "Applying DDAA via {method} ${{url}}"
echo "Payload:"; cat {payload_file}
echo
echo "DDAA archive retention changes are calculated from the index creation date and"
echo "cannot be disabled via the API. Confirm to continue."
read -r -p "Type APPLY to continue: " confirm
[[ "${{confirm}}" == "APPLY" ]] || {{ echo "Aborted."; exit 1; }}

http_code=$(curl -sS -o /tmp/ddaa_acs_response.json -w '%{{http_code}}' \\
  -X {method} "${{url}}" \\
  -H "Authorization: Bearer $(cat "${{token_file}}")" \\
  -H "Content-Type: application/json" \\
  --data @{payload_file}) || {{ echo "ERROR: ACS request failed." >&2; exit 1; }}
echo "HTTP ${{http_code}}"
cat /tmp/ddaa_acs_response.json 2>/dev/null || true
echo
if [[ "${{http_code}}" =~ ^2 ]]; then
  echo "DDAA request accepted. Run status.sh to confirm splunkArchivalRetentionDays."
else
  echo "ACS returned a non-2xx status; review the response above." >&2
  exit 1
fi
"""
    )


def render_status(args: argparse.Namespace) -> str:
    token_file = shell_quote(str(Path(args.token_file).expanduser()))
    base = shell_quote(args.acs_base.rstrip("/"))
    stack = shell_quote(args.stack)
    index = shell_quote(args.index)
    return make_script(
        f"""token_file={token_file}
acs_base={base}
stack={stack}
index={index}
[[ -s "${{token_file}}" ]] || {{ echo "ERROR: ACS token file missing or empty: ${{token_file}}" >&2; exit 1; }}
url="${{acs_base}}/${{stack}}/adminconfig/v2/indexes/${{index}}"
echo "GET ${{url}}"
curl -sS "${{url}}" \\
  -H "Authorization: Bearer $(cat "${{token_file}}")" \\
  | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print("(no JSON response)"); raise SystemExit(0)
keys=["name","datatype","searchableDays","splunkArchivalRetentionDays","maxDataSizeMB","selfStorageBucketPath"]
for k in keys:
    if k in d:
        print(f"{{k}} = {{d[k]}}")
sd=d.get("searchableDays"); ar=d.get("splunkArchivalRetentionDays")
if isinstance(sd,int) and isinstance(ar,int):
    print(f"archive_retention_days (derived) = {{ar - sd}}")
'
"""
    )


def render_restore(args: argparse.Namespace) -> str:
    index = shell_quote(args.index)
    return make_script(
        f"""index={index}
cat <<EOF
DDAA restore is performed in Splunk Web (there is no public ACS restore endpoint):

1. In Splunk Cloud, go to Settings > Indexes.
2. Find index "${{index}}" and open its Archive / Restore actions.
3. Choose the time range of archived data to restore.
   - You can restore up to ~10% of your DDAS entitlement at a time.
4. Submit the restore. Restored data lands in DDAS (searchable) for 30 days,
   then auto-expires. Clear it earlier via the Restore Archive window if desired.

After the restore completes, inspect the restored buckets:
EOF
echo
echo "Run this search to see restored buckets for the index:"
echo "  | dbinspect index=${{index}} | search state=* | stats count by state, bucketId | head 50"
echo
echo "Restoring does NOT remove data from the archive; the copy is temporary."
"""
    )


def render_audit(args: argparse.Namespace) -> str:
    index = shell_quote(args.index)
    return make_script(
        f"""index={index}
cat <<EOF
DDAA storage consumption (archived + restored) is shown in Splunk Web:
  Settings > Indexes (archive/restore columns), and in the Cloud Monitoring
  Console storage views. There is no single ACS metric endpoint for archive GB.
EOF
echo
echo "Searchable footprint of this index (current DDAS usage):"
echo "  | dbinspect index=${{index}} | stats sum(sizeOnDiskMB) as ddas_size_mb, count as buckets"
echo
echo "Restored (temporary) buckets currently in DDAS:"
echo "  | dbinspect index=${{index}} | search state=* | stats count by state"
"""
    )


def render_readme(args: argparse.Namespace) -> str:
    searchable = int(args.searchable_days)
    archival = int(args.archival_retention_days)
    return f"""# Splunk Cloud DDAA Rendered Assets

Stack: `{args.stack}`
Index: `{args.index}` (`{args.datatype}`)
Searchable retention (DDAS): `{searchable}` days
Total retention (`splunkArchivalRetentionDays`): `{archival}` days
Archive retention (DDAA, derived): `{archival - searchable}` days
Operation: `{args.operation}`

Files:

- `create-payload.json` — ACS POST body to create the index with DDAA
- `patch-payload.json` — ACS PATCH body to enable/update DDAA retention
- `enable-ddaa.sh` — apply the create/PATCH via ACS using a token file (gated)
- `status.sh` — read back searchableDays / splunkArchivalRetentionDays
- `restore.sh` — guided UI restore handoff and bucket inspection
- `audit.sh` — DDAS/restore footprint hints

DDAA cannot be disabled or switched to/from DDSS via the API; use Splunk Web for
those changes. Restore is UI-only and restored data is temporary (30 days).
"""


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "ddaa"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "stack": args.stack,
                    "index": args.index,
                    "datatype": args.datatype,
                    "searchableDays": int(args.searchable_days),
                    "splunkArchivalRetentionDays": int(args.archival_retention_days),
                    "operation": args.operation,
                    "token_file": args.token_file,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "create-payload.json": json.dumps(create_payload(args), indent=2, sort_keys=True) + "\n",
            "patch-payload.json": json.dumps(patch_payload(args), indent=2, sort_keys=True) + "\n",
            "enable-ddaa.sh": render_enable(args),
            "status.sh": render_status(args),
            "restore.sh": render_restore(args),
            "audit.sh": render_audit(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "ddaa",
        "stack": args.stack,
        "index": args.index,
        "operation": args.operation,
        "searchableDays": int(args.searchable_days),
        "splunkArchivalRetentionDays": int(args.archival_retention_days),
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "apply": [["./enable-ddaa.sh"]],
            "status": [["./status.sh"]],
            "restore": [["./restore.sh"]],
            "audit": [["./audit.sh"]],
        },
    }


def main() -> int:
    args = parse_args()
    validate(args)
    payload = render(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render DDAA assets under {payload['render_dir']}")
    else:
        print(f"Rendered DDAA assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
