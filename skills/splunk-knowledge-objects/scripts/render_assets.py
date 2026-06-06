#!/usr/bin/env python3
"""Render Splunk knowledge-object governance assets (inventory, audit, metadata)."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path

OBJECT_TYPES = {
    "savedsearches",
    "macros",
    "lookups",
    "lookuptablefiles",
    "eventtypes",
    "tags",
    "fieldextractions",
}

REST_ENDPOINTS = {
    "savedsearches": "/servicesNS/-/-/saved/searches",
    "macros": "/servicesNS/-/-/admin/macros",
    "lookups": "/servicesNS/-/-/data/transforms/lookups",
    "lookuptablefiles": "/servicesNS/-/-/data/lookup-table-files",
    "eventtypes": "/servicesNS/-/-/saved/eventtypes",
    "tags": "/servicesNS/-/-/configs/conf-tags",
    "fieldextractions": "/servicesNS/-/-/data/props/extractions",
}

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "local.meta",
    "savedsearches.conf",
    "macros.conf",
    "transforms.conf",
    "inventory.sh",
    "audit.sh",
    "apply.sh",
    "reassign.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk knowledge-object governance assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--app-name", default="ZZZ_cisco_skills_governance")
    parser.add_argument("--app-context", default="search")
    parser.add_argument(
        "--object-types",
        default="savedsearches,macros,lookups,eventtypes,tags,fieldextractions",
    )
    parser.add_argument("--reassign-owner", default="admin")
    parser.add_argument("--share-level", choices=("app", "global"), default="app")
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


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def object_type_list(args: argparse.Namespace) -> list[str]:
    if args.object_types.strip().lower() == "all":
        return [t for t in REST_ENDPOINTS if t != "lookuptablefiles"] + ["lookuptablefiles"]
    types = csv_list(args.object_types)
    if not types:
        die("--object-types must contain at least one type or 'all'.")
    unknown = [t for t in types if t not in OBJECT_TYPES]
    if unknown:
        die(
            "Unknown object type(s): "
            + ", ".join(sorted(unknown))
            + ". Valid: "
            + ", ".join(sorted(OBJECT_TYPES))
            + ", or 'all'."
        )
    seen: list[str] = []
    for t in types:
        if t not in seen:
            seen.append(t)
    return seen


def validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_context or ""):
        die("--app-context must be a valid app namespace.")
    if not re.fullmatch(r"[A-Za-z0-9._@-]+", args.reassign_owner or ""):
        die("--reassign-owner must be a valid Splunk username.")
    if "\n" in (args.splunk_home or "") or "\r" in (args.splunk_home or ""):
        die("--splunk-home must not contain newlines.")
    object_type_list(args)


def render_inventory(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    types = object_type_list(args)
    blocks = [f"splunk={splunk}\n"]
    for t in types:
        endpoint = REST_ENDPOINTS[t]
        spl = (
            f"| rest splunk_server=local count=0 {endpoint} "
            "| eval object_type=\"" + t + "\" "
            "| rename eai:acl.app as app, eai:acl.owner as owner, eai:acl.sharing as sharing "
            "| fields object_type title app owner sharing disabled "
            "| sort app title"
        )
        blocks.append(
            f'echo "== inventory: {t} ({endpoint}) =="\n'
            f'"${{splunk}}" search {shell_quote(spl)} -maxout 0 || echo "query failed for {t}"\n'
            "echo\n"
        )
    return make_script("\n".join(blocks))


def render_audit(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    orphan_spl = (
        "| rest splunk_server=local count=0 /servicesNS/-/-/saved/searches "
        '| search eai:acl.sharing=user '
        "| rename eai:acl.owner as owner, eai:acl.app as app "
        "| join type=left owner [ | rest splunk_server=local count=0 /services/authentication/users "
        '| rename title as owner | eval exists="yes" | fields owner exists ] '
        '| where isnull(exists) | eval finding="orphaned_owner" '
        "| table finding title app owner is_scheduled"
    )
    private_sched_spl = (
        "| rest splunk_server=local count=0 /servicesNS/-/-/saved/searches "
        '| search is_scheduled=1 eai:acl.sharing=user disabled=0 '
        "| rename eai:acl.owner as owner, eai:acl.app as app "
        '| eval finding="private_scheduled_search" '
        "| table finding title app owner cron_schedule"
    )
    lookup_def_spl = (
        "| rest splunk_server=local count=0 /servicesNS/-/-/data/lookup-table-files "
        "| rename title as filename, eai:acl.app as app | fields filename app "
        "| join type=left filename [ | rest splunk_server=local count=0 /servicesNS/-/-/data/transforms/lookups "
        '| rename filename as filename | eval has_def="yes" | fields filename has_def ] '
        '| where isnull(has_def) | eval finding="lookup_file_without_definition" '
        "| table finding filename app"
    )
    disabled_spl = (
        "| rest splunk_server=local count=0 /servicesNS/-/-/saved/searches "
        "| search disabled=1 "
        "| rename eai:acl.owner as owner, eai:acl.app as app "
        '| eval finding="disabled_saved_search" | table finding title app owner'
    )
    return make_script(
        f"""splunk={splunk}
echo "== finding: orphaned owners (private objects owned by removed users) =="
"${{splunk}}" search {shell_quote(orphan_spl)} -maxout 0 || echo "orphan query failed"
echo
echo "== finding: private scheduled searches (run as a removed/individual user) =="
"${{splunk}}" search {shell_quote(private_sched_spl)} -maxout 0 || echo "private-scheduled query failed"
echo
echo "== finding: lookup table files without a lookup definition =="
"${{splunk}}" search {shell_quote(lookup_def_spl)} -maxout 0 || echo "lookup-definition query failed"
echo
echo "== finding: disabled saved searches =="
"${{splunk}}" search {shell_quote(disabled_spl)} -maxout 0 || echo "disabled query failed"
echo
echo "Reassign orphaned/private objects with reassign.sh and share with local.meta + apply.sh."
"""
    )


def render_local_meta(args: argparse.Namespace) -> str:
    share = "global" if args.share_level == "global" else "app"
    lines = [
        "# Rendered by splunk-knowledge-objects. Stage as etc/apps/<app>/metadata/local.meta.",
        "# Defines sharing/ownership for governed knowledge objects. Review before applying.",
        "",
        "[]",
        "access = read : [ * ], write : [ admin, power ]",
        f"export = {'system' if share == 'global' else 'none'}",
        f"owner = {args.reassign_owner}",
        "",
        "# Per-object overrides, for example a specific saved search:",
        "# [savedsearches/My Governed Report]",
        "# access = read : [ * ], write : [ admin ]",
        f"# export = {'system' if share == 'global' else 'none'}",
        f"# owner = {args.reassign_owner}",
        "",
    ]
    return "\n".join(lines)


def render_savedsearches(args: argparse.Namespace) -> str:
    return (
        "# Rendered by splunk-knowledge-objects. Governed saved-search template.\n"
        "# Stage into etc/apps/<app>/local/savedsearches.conf and share via local.meta.\n"
        "\n"
        "[Example Governed Report]\n"
        "search = index=main | stats count by sourcetype\n"
        "dispatch.earliest_time = -24h@h\n"
        "dispatch.latest_time = now\n"
        "cron_schedule = 0 6 * * *\n"
        "enableSched = 0\n"
        "# Set enableSched = 1 only after reviewing schedule load and ownership.\n"
        "request.ui_dispatch_app = " + args.app_context + "\n"
    )


def render_macros() -> str:
    return (
        "# Rendered by splunk-knowledge-objects. Governed macro template.\n"
        "\n"
        "[governed_index_filter]\n"
        "definition = index=main OR index=summary\n"
        "iseval = 0\n"
    )


def render_transforms() -> str:
    return (
        "# Rendered by splunk-knowledge-objects. Lookup definition template.\n"
        "# Pair with a CSV under etc/apps/<app>/lookups/ and an automatic lookup in props.conf.\n"
        "\n"
        "[governed_lookup]\n"
        "filename = governed_lookup.csv\n"
        "# For external/scripted lookups, use external_cmd and fields_list instead of filename.\n"
    )


def render_apply(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    app_name = shell_quote(args.app_name)
    return make_script(
        f"""splunk={splunk}
app_name={app_name}
splunk_home={shell_quote(args.splunk_home)}
app_root="${{splunk_home}}/etc/apps/${{app_name}}"
mkdir -p "${{app_root}}/local" "${{app_root}}/metadata"
cp savedsearches.conf "${{app_root}}/local/savedsearches.conf"
cp macros.conf "${{app_root}}/local/macros.conf"
cp transforms.conf "${{app_root}}/local/transforms.conf"
cp local.meta "${{app_root}}/metadata/local.meta"
echo "Staged governed conf and metadata into ${{app_root}}."
echo "Reload to apply (or restart on an SHC deployer push):"
"${{splunk}}" _internal call /services/configs/conf-savedsearches/_reload >/dev/null 2>&1 || true
"${{splunk}}" _internal call /services/admin/conf-times/_reload >/dev/null 2>&1 || true
echo "Review effective sharing in Settings > All configurations after reload."
"""
    )


def render_reassign(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    owner = shell_quote(args.reassign_owner)
    share = shell_quote(args.share_level)
    return make_script(
        f"""splunk={splunk}
new_owner={owner}
share_level={share}
# Reassign a single knowledge object's owner/sharing via its ACL endpoint.
# Usage: ./reassign.sh <acl-endpoint>
# Example endpoint: servicesNS/nobody/search/saved/searches/My%20Report/acl
acl_endpoint="${{1:-}}"
if [[ -z "${{acl_endpoint}}" ]]; then
  echo "Usage: ./reassign.sh <acl-endpoint>" >&2
  echo "Find endpoints with inventory.sh; append /acl to the object's REST path." >&2
  exit 2
fi
echo "About to set owner=${{new_owner}} sharing=${{share_level}} on:"
echo "  ${{acl_endpoint}}"
read -r -p "Type REASSIGN to continue: " confirm
[[ "${{confirm}}" == "REASSIGN" ]] || {{ echo "Aborted."; exit 1; }}
# Authenticate interactively or add -auth user:"$(cat /path/to/secret)".
"${{splunk}}" _internal call "/${{acl_endpoint#/}}" -method POST \\
  -post:owner "${{new_owner}}" -post:sharing "${{share_level}}" \\
  || {{ echo "Reassign failed; verify the endpoint and your capabilities (admin_all_objects)." >&2; exit 1; }}
echo "Reassigned. Re-run inventory.sh to confirm."
"""
    )


def render_readme(args: argparse.Namespace) -> str:
    types = object_type_list(args)
    return f"""# Splunk Knowledge-Object Governance Rendered Assets

Governance app: `{args.app_name}`
App context: `{args.app_context}`
Share level: `{args.share_level}`
Reassign owner: `{args.reassign_owner}`
Audited object types: {", ".join(f"`{t}`" for t in types)}

Files:

- `inventory.sh` — full KO inventory (app, owner, sharing, disabled)
- `audit.sh` — governance findings (orphans, private scheduled searches, lookups
  without definitions, disabled objects)
- `local.meta` — sharing/ownership metadata template
- `savedsearches.conf`, `macros.conf`, `transforms.conf` — governed templates
- `apply.sh` — stage conf + metadata into `etc/apps/{args.app_name}`
- `reassign.sh` — reassign a single object's owner/sharing via ACL (gated)

Run `inventory.sh` and `audit.sh` first (read-only). Apply governed metadata and
conf with `apply.sh`, and reassign orphaned/private objects with `reassign.sh`.
On a search head cluster, stage through the deployer.
"""


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "knowledge-objects"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "app_name": args.app_name,
                    "app_context": args.app_context,
                    "share_level": args.share_level,
                    "reassign_owner": args.reassign_owner,
                    "object_types": object_type_list(args),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "local.meta": render_local_meta(args),
            "savedsearches.conf": render_savedsearches(args),
            "macros.conf": render_macros(),
            "transforms.conf": render_transforms(),
            "inventory.sh": render_inventory(args),
            "audit.sh": render_audit(args),
            "apply.sh": render_apply(args),
            "reassign.sh": render_reassign(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "knowledge-objects",
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "object_types": object_type_list(args),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "inventory": [["./inventory.sh"]],
            "audit": [["./audit.sh"]],
            "apply": [["./apply.sh"]],
            "reassign": [["./reassign.sh", "<acl-endpoint>"]],
        },
    }


def main() -> int:
    args = parse_args()
    validate(args)
    payload = render(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render knowledge-object governance assets under {payload['render_dir']}")
    else:
        print(f"Rendered knowledge-object governance assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
