#!/usr/bin/env python3
"""Render Splunk Ingest Actions assets (ruleset props/transforms + RFS S3 destination)."""

from __future__ import annotations

import argparse
import json
import re
import stat
from pathlib import Path

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "props.conf",
    "transforms.conf",
    "outputs.conf",
    "status-rulesets.sh",
}

RULE_TYPES = ("eval", "mask", "drop", "route-s3")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Ingest Actions assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--app-name", default="ZZZ_cisco_skills_ingest_actions")
    parser.add_argument("--ruleset-sourcetype", required=True)
    parser.add_argument("--ruleset-name", required=True)
    parser.add_argument("--rule-type", choices=RULE_TYPES, required=True)
    parser.add_argument("--eval-expression", default="")
    parser.add_argument("--mask-regex", default="")
    parser.add_argument("--mask-replacement", default="########")
    parser.add_argument("--drop-regex", default="")
    parser.add_argument("--s3-destination-name", default="")
    parser.add_argument("--s3-path", default="")
    parser.add_argument("--s3-auth-region", default="")
    parser.add_argument("--s3-encryption", choices=("unset", "none", "sse-s3", "sse-kms"), default="unset")
    parser.add_argument("--s3-kms-key-id", default="")
    parser.add_argument("--s3-access-key-file", default="")
    parser.add_argument("--s3-secret-key-file", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


def spl_escape(value: str) -> str:
    """Escape a value for embedding inside a double-quoted SPL string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


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


def transform_stanza(args: argparse.Namespace) -> str:
    return f"{args.ruleset_name}_{args.rule_type.replace('-', '_')}"


def validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    if not re.fullmatch(r"[A-Za-z0-9_]+", args.ruleset_name or ""):
        die("--ruleset-name must contain only letters, numbers, and underscores.")
    no_newline(args.ruleset_sourcetype, "--ruleset-sourcetype")
    for value, option in (
        (args.eval_expression, "--eval-expression"),
        (args.mask_regex, "--mask-regex"),
        (args.mask_replacement, "--mask-replacement"),
        (args.drop_regex, "--drop-regex"),
        (args.s3_path, "--s3-path"),
    ):
        no_newline(value, option)
    if args.rule_type == "eval" and not args.eval_expression:
        die("--eval-expression is required for rule-type eval.")
    if args.rule_type == "mask" and not args.mask_regex:
        die("--mask-regex is required for rule-type mask.")
    if args.rule_type == "drop" and not args.drop_regex:
        die("--drop-regex is required for rule-type drop.")
    if args.rule_type == "route-s3":
        if not (args.s3_destination_name and args.s3_path):
            die("--s3-destination-name and --s3-path are required for rule-type route-s3.")
    if args.s3_destination_name:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.s3_destination_name):
            die("--s3-destination-name must contain only letters, numbers, underscore, and hyphen.")
        if args.s3_path and not args.s3_path.startswith("s3://"):
            die("--s3-path must start with s3://.")
    if (args.s3_access_key_file and not args.s3_secret_key_file) or (
        args.s3_secret_key_file and not args.s3_access_key_file
    ):
        die("--s3-access-key-file and --s3-secret-key-file must be supplied together.")
    if args.s3_encryption == "sse-kms" and not args.s3_kms_key_id:
        die("--s3-kms-key-id is required when --s3-encryption is sse-kms.")


def render_transforms(args: argparse.Namespace) -> str:
    stanza = transform_stanza(args)
    lines = [
        "# Rendered by splunk-ingest-actions-setup. Review before applying.",
        "# Ingest Actions rulesets are normally authored in Splunk Web; this is the",
        "# equivalent INGEST_EVAL representation for config-management workflows.",
        f"[{stanza}]",
    ]
    if args.rule_type == "route-s3":
        return (
            "# Rendered by splunk-ingest-actions-setup. Review before applying.\n"
            f"# Route-to-destination rule for source type {args.ruleset_sourcetype}.\n"
            "# The RFS S3 destination is configured in outputs.conf ([rfs:"
            f"{args.s3_destination_name}]). Author the matching \"Route to\n"
            "# Destination\" rule in Splunk Web (Settings > Data > Ingest Actions)\n"
            "# or via the /services/data/ingest/rulesets REST endpoint, selecting\n"
            f"# destination {args.s3_destination_name}. The internal routing transform is\n"
            "# generated by Ingest Actions and is intentionally not hand-authored here.\n"
        )
    if args.rule_type == "eval":
        lines.append(f"INGEST_EVAL = {args.eval_expression}")
    elif args.rule_type == "mask":
        regex = spl_escape(args.mask_regex)
        replacement = spl_escape(args.mask_replacement)
        lines.append(f'INGEST_EVAL = _raw=replace(_raw, "{regex}", "{replacement}")')
    elif args.rule_type == "drop":
        drop_regex = spl_escape(args.drop_regex)
        lines.append(f'INGEST_EVAL = queue=if(match(_raw, "{drop_regex}"), "nullQueue", queue)')
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_props(args: argparse.Namespace) -> str:
    stanza = transform_stanza(args)
    if args.rule_type == "route-s3":
        return (
            "# Rendered by splunk-ingest-actions-setup. Review before applying.\n"
            f"# No RULESET binding is hand-authored for route-s3 on {args.ruleset_sourcetype}.\n"
            "# Create the \"Route to Destination\" rule in the Ingest Actions UI / rulesets\n"
            f"# endpoint selecting destination {args.s3_destination_name}.\n"
        )
    return (
        "# Rendered by splunk-ingest-actions-setup. Review before applying.\n"
        f"[{args.ruleset_sourcetype}]\n"
        f"RULESET-{args.ruleset_name} = {stanza}\n"
    )


def render_outputs(args: argparse.Namespace) -> str:
    lines = ["# Rendered by splunk-ingest-actions-setup. Review before applying."]
    if args.rule_type != "route-s3" and not args.s3_destination_name:
        lines.append("# No RFS S3 destination requested.")
        return "\n".join(lines) + "\n"
    lines.append(f"[rfs:{args.s3_destination_name}]")
    lines.append(f"path = {args.s3_path}")
    # The S3 bucket is taken from `path`; RFS S3 stanzas do not use remote.s3.bucket_name.
    if args.s3_auth_region:
        lines.append(f"remote.s3.auth_region = {args.s3_auth_region}")
    if args.s3_encryption != "unset":
        lines.append(f"remote.s3.encryption = {args.s3_encryption}")
    if args.s3_kms_key_id:
        lines.append(f"remote.s3.kms.key_id = {args.s3_kms_key_id}")
    if args.s3_access_key_file:
        lines.append("remote.s3.access_key = __INGEST_ACTIONS_S3_ACCESS_KEY_FROM_FILE__")
        lines.append("remote.s3.secret_key = __INGEST_ACTIONS_S3_SECRET_KEY_FROM_FILE__")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_status(args: argparse.Namespace) -> str:
    splunk = '"${SPLUNK_HOME:-/opt/splunk}/bin/splunk"'
    return (
        "#!/usr/bin/env bash\nset -euo pipefail\n\n"
        "# List Ingest Actions rulesets via the supported REST endpoint.\n"
        "# Authenticate first with: splunk login\n"
        f'exec {splunk} _internal call /services/data/ingest/rulesets\n'
    )


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk Ingest Actions Rendered Assets

Source type: `{args.ruleset_sourcetype}`
Ruleset: `{args.ruleset_name}`
Rule type: `{args.rule_type}`
App: `{args.app_name}`

Files:

- `props.conf` - `RULESET-{args.ruleset_name}` binding on the source type
- `transforms.conf` - the rule (INGEST_EVAL) or route-to-destination definition
- `outputs.conf` - `[rfs:<name>]` S3 destination (when routing to S3)
- `status-rulesets.sh` - lists rulesets via `/services/data/ingest/rulesets`

Ingest Actions rulesets are normally authored in Splunk Web (Settings > Data >
Ingest Actions) or through the `/services/data/ingest/rulesets` REST endpoint.
This skill renders the equivalent props/transforms for review and
config-management distribution, and can write them and the RFS destination via
REST. Transformations are applied before indexing and cannot be reverted for
already-indexed data; apply requires `--accept-irreversible-ingest`. Only one
ruleset is supported per source type, and a Splunk deployment supports a maximum
of 8 S3 destinations.
"""


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "ingest-actions"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "ruleset_sourcetype": args.ruleset_sourcetype,
                    "ruleset_name": args.ruleset_name,
                    "rule_type": args.rule_type,
                    "app_name": args.app_name,
                    "s3_destination_name": args.s3_destination_name,
                    "s3_path": args.s3_path,
                    "s3_access_key_file": args.s3_access_key_file,
                    "s3_secret_key_file": args.s3_secret_key_file,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "props.conf": render_props(args),
            "transforms.conf": render_transforms(args),
            "outputs.conf": render_outputs(args),
            "status-rulesets.sh": render_status(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "ingest-actions",
        "ruleset_name": args.ruleset_name,
        "rule_type": args.rule_type,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
    }


def main() -> int:
    args = parse_args()
    validate(args)
    payload = render(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render Ingest Actions assets under {payload['render_dir']}")
    else:
        print(f"Rendered Ingest Actions assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
