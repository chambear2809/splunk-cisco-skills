#!/usr/bin/env python3
"""Render Splunk Ingest Actions assets (RFS destinations, ruleset spec, preview)."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path

RULE_TYPES = ("filter", "mask", "setindex", "route")

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "outputs.conf",
    "ruleset.json",
    "props_transforms_preview.conf",
    "apply.sh",
    "status.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Ingest Actions assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--app-name", default="splunk_ingest_actions")
    parser.add_argument("--platform", choices=("cloud", "enterprise"), default="enterprise")
    parser.add_argument("--sourcetype", default="")
    parser.add_argument("--ruleset-name", default="")
    parser.add_argument("--rules", default="")
    parser.add_argument("--filter-regex", default="")
    parser.add_argument("--mask-regex", default="")
    parser.add_argument("--mask-replacement", default="")
    parser.add_argument("--target-index", default="")
    # Destination (RFS).
    parser.add_argument("--destination-type", choices=("none", "s3", "filesystem"), default="none")
    parser.add_argument("--destination-name", default="")
    parser.add_argument("--s3-path", default="")
    parser.add_argument("--fs-path", default="")
    parser.add_argument("--s3-endpoint", default="")
    parser.add_argument("--s3-auth-region", default="")
    parser.add_argument("--s3-encryption", choices=("unset", "none", "sse-s3", "sse-kms"), default="unset")
    parser.add_argument("--s3-kms-key-id", default="")
    parser.add_argument("--s3-access-key-file", default="")
    parser.add_argument("--s3-secret-key-file", default="")
    parser.add_argument("--partition-by", default="")
    parser.add_argument("--format", choices=("raw", "json"), default="json")
    parser.add_argument("--compression", choices=("none", "gzip", "zstd"), default="gzip")
    parser.add_argument("--batch-size-kb", default="")
    parser.add_argument("--drop-events-on-upload-error", choices=("true", "false"), default="false")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


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


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def no_newline(value: str, option: str) -> None:
    if "\n" in (value or "") or "\r" in (value or ""):
        die(f"{option} must not contain newlines.")


def rule_list(args: argparse.Namespace) -> list[str]:
    if not args.rules.strip():
        return []
    rules = csv_list(args.rules)
    unknown = [r for r in rules if r not in RULE_TYPES]
    if unknown:
        die("Unknown rule(s): " + ", ".join(sorted(unknown)) + ". Valid: " + ", ".join(RULE_TYPES))
    seen: list[str] = []
    for r in rules:
        if r not in seen:
            seen.append(r)
    return seen


def validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    for value, option in (
        (args.s3_path, "--s3-path"),
        (args.fs_path, "--fs-path"),
        (args.s3_endpoint, "--s3-endpoint"),
        (args.s3_auth_region, "--s3-auth-region"),
        (args.s3_kms_key_id, "--s3-kms-key-id"),
        (args.s3_access_key_file, "--s3-access-key-file"),
        (args.s3_secret_key_file, "--s3-secret-key-file"),
        (args.sourcetype, "--sourcetype"),
        (args.filter_regex, "--filter-regex"),
        (args.mask_regex, "--mask-regex"),
        (args.mask_replacement, "--mask-replacement"),
        (args.target_index, "--target-index"),
        (args.partition_by, "--partition-by"),
        (args.splunk_home, "--splunk-home"),
    ):
        no_newline(value, option)
    if args.batch_size_kb and not re.fullmatch(r"[0-9]+", args.batch_size_kb):
        die("--batch-size-kb must be a nonnegative integer.")
    rules = rule_list(args)
    if rules and not args.sourcetype:
        die("--sourcetype is required when --rules are provided.")
    if "filter" in rules and not args.filter_regex:
        die("--filter-regex is required for the 'filter' rule.")
    if "mask" in rules and (not args.mask_regex or not args.mask_replacement):
        die("--mask-regex and --mask-replacement are required for the 'mask' rule.")
    if "setindex" in rules and not args.target_index:
        die("--target-index is required for the 'setindex' rule.")
    if "route" in rules and args.destination_type == "none":
        die("--destination-type s3|filesystem is required for the 'route' rule.")
    if args.destination_type != "none" and not args.destination_name:
        die("--destination-name is required when a destination type is set.")
    if args.destination_type == "s3" and not args.s3_path:
        die("--s3-path is required for an s3 destination.")
    if args.destination_type == "filesystem" and not args.fs_path:
        die("--fs-path is required for a filesystem destination.")
    if args.destination_type == "s3":
        scheme = args.s3_path.split(":", 1)[0]
        if scheme != "s3":
            die("--s3-path must start with s3://")
    if args.s3_encryption == "sse-kms" and not args.s3_kms_key_id:
        die("--s3-kms-key-id is required when --s3-encryption is sse-kms.")
    if (args.s3_access_key_file and not args.s3_secret_key_file) or (
        args.s3_secret_key_file and not args.s3_access_key_file
    ):
        die("--s3-access-key-file and --s3-secret-key-file must be supplied together.")
    if args.destination_type != "s3" and (
        args.s3_path
        or args.s3_endpoint
        or args.s3_auth_region
        or args.s3_kms_key_id
        or args.s3_access_key_file
        or args.s3_secret_key_file
        or args.s3_encryption != "unset"
    ):
        die("S3 settings can only be used with --destination-type s3.")


def ruleset_name(args: argparse.Namespace) -> str:
    if args.ruleset_name:
        return args.ruleset_name
    if args.sourcetype:
        return f"ruleset_{re.sub(r'[^A-Za-z0-9]+', '_', args.sourcetype)}"
    return "ruleset"


def render_outputs(args: argparse.Namespace) -> str:
    if args.destination_type == "none":
        return (
            "# Rendered by splunk-ingest-actions. No RFS destination requested.\n"
            "# Set --destination-type s3|filesystem to render an [rfs:<name>] stanza.\n"
        )
    name = args.destination_name
    lines = [
        "# Rendered by splunk-ingest-actions. Review before applying.",
        "# RFS (Remote File System) destination for Ingest Actions routing.",
        f"[rfs:{name}]",
    ]
    if args.destination_type == "s3":
        lines.append(f"path = {args.s3_path}")
        lines.append("remote.s3.bucket_name = __SET_FROM_PATH__")
        if args.s3_endpoint:
            lines.append(f"remote.s3.endpoint = {args.s3_endpoint}")
        if args.s3_auth_region:
            lines.append(f"remote.s3.auth_region = {args.s3_auth_region}")
        if args.s3_encryption != "unset":
            lines.append(f"remote.s3.encryption = {args.s3_encryption}")
        if args.s3_kms_key_id:
            lines.append(f"remote.s3.kms.key_id = {args.s3_kms_key_id}")
        if args.s3_access_key_file:
            lines.append("remote.s3.access_key = __INGEST_ACTIONS_S3_ACCESS_KEY_FROM_FILE__")
            lines.append("remote.s3.secret_key = __INGEST_ACTIONS_S3_SECRET_KEY_FROM_FILE__")
    else:
        lines.append(f"path = {args.fs_path}")
    lines.append(f"format = {args.format}")
    lines.append(f"compression = {args.compression}")
    if args.partition_by:
        lines.append(f"partitionBy = {args.partition_by}")
    if args.batch_size_kb:
        lines.append(f"batchSizeThresholdKB = {args.batch_size_kb}")
    lines.append(f"dropEventsOnUploadError = {args.drop_events_on_upload_error}")
    lines.append("")
    lines.append("# remote.s3.bucket_name: replace __SET_FROM_PATH__ or remove if path includes the bucket.")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_ruleset_spec(args: argparse.Namespace) -> str:
    rules = rule_list(args)
    rule_specs: list[dict] = []
    for rule in rules:
        if rule == "filter":
            rule_specs.append(
                {"type": "filter", "condition": "regex", "field": "_raw", "regex": args.filter_regex,
                 "action": "drop_matching_events"}
            )
        elif rule == "mask":
            rule_specs.append(
                {"type": "mask", "field": "_raw", "regex": args.mask_regex, "replacement": args.mask_replacement}
            )
        elif rule == "setindex":
            rule_specs.append({"type": "set_index", "index": args.target_index})
        elif rule == "route":
            rule_specs.append(
                {
                    "type": "route_to_destination",
                    "destination": args.destination_name,
                    "destination_type": args.destination_type,
                    "condition": "none",
                }
            )
    spec = {
        "ruleset": ruleset_name(args),
        "sourcetype": args.sourcetype,
        "platform": args.platform,
        "rules": rule_specs,
        "rest_endpoint": "/services/data/ingest/rulesets",
        "ui_path": "Settings > Ingest Actions",
        "note": (
            "Create/modify the ruleset through the Ingest Actions UI or the REST "
            "endpoint above. Do not hand-edit the ruleset into transforms.conf."
        ),
    }
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def render_preview(args: argparse.Namespace) -> str:
    rules = rule_list(args)
    if not rules or not args.sourcetype:
        return (
            "# Rendered by splunk-ingest-actions. No manual preview (no rules/sourcetype set).\n"
        )
    transforms: list[str] = []
    transform_names: list[str] = []
    if "filter" in rules:
        transform_names.append("ia_preview_filter")
        transforms.extend(
            [
                "[ia_preview_filter]",
                f"REGEX = {args.filter_regex}",
                "DEST_KEY = queue",
                "FORMAT = nullQueue",
                "",
            ]
        )
    if "mask" in rules:
        transform_names.append("ia_preview_mask")
        transforms.extend(
            [
                "[ia_preview_mask]",
                "SOURCE_KEY = _raw",
                f"REGEX = {args.mask_regex}",
                f"FORMAT = {args.mask_replacement}",
                "DEST_KEY = _raw",
                "",
            ]
        )
    if "setindex" in rules:
        transform_names.append("ia_preview_setindex")
        transforms.extend(
            [
                "[ia_preview_setindex]",
                "REGEX = .",
                "DEST_KEY = _MetaData:Index",
                f"FORMAT = {args.target_index}",
                "",
            ]
        )
    header = [
        "# Rendered by splunk-ingest-actions. MANUAL heavy-forwarder preview ONLY.",
        "# This is the classic pre-index path (props.conf + transforms.conf), NOT an",
        "# Ingest Actions ruleset. For rulesets, use the UI or /services/data/ingest/rulesets.",
        "# Place on the first full Splunk instance in the pipeline (HF or indexer).",
        "",
        "# ---- props.conf ----",
        f"[{args.sourcetype}]",
        f"TRANSFORMS-ia_preview = {', '.join(transform_names)}",
        "",
        "# ---- transforms.conf ----",
    ]
    return "\n".join(header + transforms).rstrip() + "\n"


def render_apply(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    app_name = shell_quote(args.app_name)
    has_dest = "true" if args.destination_type != "none" else "false"
    access_key_file = (
        shell_quote(str(Path(args.s3_access_key_file).expanduser())) if args.s3_access_key_file else "''"
    )
    secret_key_file = (
        shell_quote(str(Path(args.s3_secret_key_file).expanduser())) if args.s3_secret_key_file else "''"
    )
    return make_script(
        f"""splunk={splunk}
app_name={app_name}
splunk_home={shell_quote(args.splunk_home)}
has_dest={has_dest}
access_key_file={access_key_file}
secret_key_file={secret_key_file}

if [[ "${{has_dest}}" == "true" ]]; then
  target_dir="${{splunk_home}}/etc/apps/${{app_name}}/local"
  mkdir -p "${{target_dir}}"
  out="${{target_dir}}/outputs.conf"
  if grep -q "__INGEST_ACTIONS_S3_ACCESS_KEY_FROM_FILE__" outputs.conf; then
    [[ -s "${{access_key_file}}" ]] || {{ echo "ERROR: S3 access key file missing/empty: ${{access_key_file}}" >&2; exit 1; }}
    [[ -s "${{secret_key_file}}" ]] || {{ echo "ERROR: S3 secret key file missing/empty: ${{secret_key_file}}" >&2; exit 1; }}
    python3 - "${{out}}" outputs.conf "${{access_key_file}}" "${{secret_key_file}}" <<'PY'
from pathlib import Path
import sys
target, template, akf, skf = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
text = Path(template).read_text(encoding="utf-8")
ak = Path(akf).read_text(encoding="utf-8").strip()
sk = Path(skf).read_text(encoding="utf-8").strip()
if not ak or not sk:
    raise SystemExit("ERROR: S3 credential files must not be empty.")
text = text.replace("__INGEST_ACTIONS_S3_ACCESS_KEY_FROM_FILE__", ak)
text = text.replace("__INGEST_ACTIONS_S3_SECRET_KEY_FROM_FILE__", sk)
Path(target).write_text(text, encoding="utf-8")
PY
    chmod 600 "${{out}}"
  else
    cp outputs.conf "${{out}}"
  fi
  echo "Staged RFS destination into ${{out}}."
else
  echo "No RFS destination to stage."
fi

echo
echo "Create the ruleset the supported way (do NOT hand-edit transforms.conf):"
echo "  UI:   Settings > Ingest Actions > New Ruleset (see ruleset.json for the rule plan)"
echo "  REST: POST /services/data/ingest/rulesets (see ruleset.json)"
echo
echo "On Splunk Cloud Victoria rulesets deploy automatically; on Classic and on"
echo "indexer clusters you must deploy explicitly. Validate with status.sh."
"""
    )


def render_status(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    return make_script(
        f"""splunk={splunk}
echo "== existing ingest rulesets =="
"${{splunk}}" search '| rest splunk_server=local count=0 /services/data/ingest/rulesets | table title disabled' -maxout 0 \\
  || echo "Could not list rulesets (endpoint/capability may be unavailable)."
echo
echo "== RFS / S3 upload errors (last 60m) =="
"${{splunk}}" search 'index=_internal sourcetype=splunkd (ERROR OR WARN) (RfsOutputProcessor OR S3Client) earliest=-60m | stats count by component, log_level' -maxout 0 \\
  || echo "Could not query _internal for RFS errors."
echo
echo "== effective rfs destinations (btool) =="
"${{splunk}}" btool outputs list --debug 2>/dev/null | grep -i -E '\\[rfs:|path = ' | grep -v -i -E 'access_key|secret_key' || true
"""
    )


def render_readme(args: argparse.Namespace) -> str:
    rules = rule_list(args)
    return f"""# Splunk Ingest Actions Rendered Assets

Platform: `{args.platform}`
Source type: `{args.sourcetype or "(none)"}`
Ruleset: `{ruleset_name(args)}`
Rules: {", ".join(f"`{r}`" for r in rules) or "(none)"}
Destination: `{args.destination_type}` {("`" + args.destination_name + "`") if args.destination_name else ""}

Files:

- `outputs.conf` — `[rfs:<name>]` destination (editable; stage into app local/)
- `ruleset.json` — ruleset plan for the Ingest Actions UI / REST
- `props_transforms_preview.conf` — manual heavy-forwarder preview only
- `apply.sh` — stage the RFS destination and print the ruleset handoff
- `status.sh` — list rulesets and surface RFS upload errors

Create destinations BEFORE rulesets that route to them: routing to a missing or
invalid destination blocks queues and pipelines (it does not drop data).
Create rulesets only via the Ingest Actions UI or the
`/services/data/ingest/rulesets` REST endpoint.
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
                    "platform": args.platform,
                    "sourcetype": args.sourcetype,
                    "ruleset": ruleset_name(args),
                    "rules": rule_list(args),
                    "destination_type": args.destination_type,
                    "destination_name": args.destination_name,
                    "s3_access_key_file": args.s3_access_key_file,
                    "s3_secret_key_file": args.s3_secret_key_file,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "outputs.conf": render_outputs(args),
            "ruleset.json": render_ruleset_spec(args),
            "props_transforms_preview.conf": render_preview(args),
            "apply.sh": render_apply(args),
            "status.sh": render_status(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "ingest-actions",
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "ruleset": ruleset_name(args),
        "rules": rule_list(args),
        "destination_type": args.destination_type,
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "apply": [["./apply.sh"]],
            "status": [["./status.sh"]],
        },
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
