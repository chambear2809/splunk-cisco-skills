#!/usr/bin/env python3
"""Render Splunk CIM data-model management assets (acceleration + audit)."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path

# Canonical Splunk Common Information Model data models (Splunk_SA_CIM).
CIM_MODELS = {
    "Alerts",
    "Authentication",
    "Certificates",
    "Change",
    "Compute_Inventory",
    "Data_Access",
    "Databases",
    "DLP",
    "Email",
    "Endpoint",
    "Event_Signatures",
    "Interprocess_Messaging",
    "Intrusion_Detection",
    "Inventory",
    "JVM",
    "Malware",
    "Network_Resolution",
    "Network_Sessions",
    "Network_Traffic",
    "Performance",
    "Splunk_Audit",
    "Ticket_Management",
    "Updates",
    "Vulnerabilities",
    "Web",
}

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "datamodels.conf",
    "apply.sh",
    "rebuild.sh",
    "status.sh",
    "audit.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk CIM data-model assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--app-name", default="ZZZ_cisco_skills_cim_accel")
    parser.add_argument("--models", default="Authentication,Network_Traffic,Web,Endpoint")
    parser.add_argument("--acceleration", choices=("true", "false"), default="true")
    parser.add_argument("--earliest-time", default="-7d@d")
    parser.add_argument("--backfill-time", default="")
    parser.add_argument("--max-concurrent", default="")
    parser.add_argument("--summary-range", default="-24h")
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


def validate_time_token(value: str, option: str) -> None:
    if value and not re.fullmatch(r"[A-Za-z0-9@:+_.\-]+", value):
        die(f"{option} must be a valid Splunk relative time token (for example -7d@d).")


def model_list(args: argparse.Namespace) -> list[str]:
    if args.models.strip().lower() == "all":
        return sorted(CIM_MODELS)
    models = csv_list(args.models)
    if not models:
        die("--models must contain at least one CIM model or 'all'.")
    unknown = [m for m in models if m not in CIM_MODELS]
    if unknown:
        die(
            "Unknown CIM model(s): "
            + ", ".join(sorted(unknown))
            + ". Use canonical names (for example Network_Traffic) or 'all'."
        )
    # Preserve input order, drop duplicates.
    seen: list[str] = []
    for m in models:
        if m not in seen:
            seen.append(m)
    return seen


def validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    validate_time_token(args.earliest_time, "--earliest-time")
    validate_time_token(args.backfill_time, "--backfill-time")
    validate_time_token(args.summary_range, "--summary-range")
    no_newline(args.splunk_home, "--splunk-home")
    if args.max_concurrent and not re.fullmatch(r"[0-9]+", args.max_concurrent):
        die("--max-concurrent must be a nonnegative integer.")
    model_list(args)


def render_datamodels(args: argparse.Namespace) -> str:
    models = model_list(args)
    enabled = bool_value(args.acceleration)
    lines = [
        "# Rendered by splunk-cim-data-model. Review before applying.",
        "# Stage into a dedicated app local/ directory; never edit Splunk_SA_CIM/default.",
        "",
    ]
    for model in models:
        lines.append(f"[{model}]")
        lines.append(f"acceleration = {1 if enabled else 0}")
        if enabled:
            lines.append(f"acceleration.earliest_time = {args.earliest_time}")
            if args.backfill_time:
                lines.append(f"acceleration.backfill_time = {args.backfill_time}")
            if args.max_concurrent:
                lines.append(f"acceleration.max_concurrent = {args.max_concurrent}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_apply(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    app_name = shell_quote(args.app_name)
    return make_script(
        f"""splunk={splunk}
app_name={app_name}
splunk_home={shell_quote(args.splunk_home)}
target_dir="${{splunk_home}}/etc/apps/${{app_name}}/local"
mkdir -p "${{target_dir}}"
cp datamodels.conf "${{target_dir}}/datamodels.conf"
echo "Staged datamodels.conf into ${{target_dir}}."
# Reload data model config without a full restart where supported.
"${{splunk}}" _internal call /services/data/models/_reload >/dev/null 2>&1 \\
  || echo "Reload endpoint not available; restart Splunk or reload datamodels to apply."
"${{splunk}}" btool datamodels list --debug 2>/dev/null | grep -i acceleration || true
"""
    )


def render_rebuild(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    models = model_list(args)
    model_csv = shell_quote(",".join(models))
    return make_script(
        f"""splunk={splunk}
models={model_csv}
echo "Rebuilding/backfilling accelerated data models: ${{models}}"
echo "Rebuilds re-summarize historical data and consume search/indexer resources."
read -r -p "Type REBUILD to continue: " confirm
[[ "${{confirm}}" == "REBUILD" ]] || {{ echo "Aborted."; exit 1; }}
IFS=',' read -r -a model_arr <<< "${{models}}"
for model in "${{model_arr[@]}}"; do
  echo "== rebuild ${{model}} =="
  # Trigger a rebuild via the summarization controls for this model.
  "${{splunk}}" _internal call "/services/data/models/${{model}}/acceleration/rebuild" -method POST \\
    || echo "Could not trigger rebuild for ${{model}} via REST; use Settings > Data models > ${{model}} > Rebuild."
done
"""
    )


def render_status(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    return make_script(
        f"""splunk={splunk}
echo "== data model acceleration summarization status =="
"${{splunk}}" search '| rest splunk_server=local /services/admin/summarization \\
  | rename summary.id as id, summary.access_time as access_time, summary.complete as complete, summary.size as size_bytes, summary.mod_time as mod_time \\
  | table id complete size_bytes access_time mod_time' -maxout 0 -auth "$@" 2>/dev/null \\
  || "${{splunk}}" search '| rest splunk_server=local /services/admin/summarization | table title summary.complete summary.size' -maxout 0
"""
    )


def render_audit(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    summary_range = shell_quote(args.summary_range)
    models = model_list(args)
    model_csv = shell_quote(",".join(models))
    return make_script(
        f"""splunk={splunk}
summary_range={summary_range}
models={model_csv}
IFS=',' read -r -a model_arr <<< "${{models}}"
for model in "${{model_arr[@]}}"; do
  echo "== CIM population: ${{model}} (accelerated tstats, earliest ${{summary_range}}) =="
  "${{splunk}}" search "| tstats count from datamodel=${{model}} where _time>=${{summary_range}} by index sourcetype | sort - count | head 20" -maxout 0 \\
    || echo "tstats failed for ${{model}} (model may be unaccelerated or empty)."
  echo
done
echo "Empty results usually mean the model is unaccelerated or the data is not CIM-mapped."
echo "Use splunk-data-source-readiness-doctor to diagnose CIM tagging and field compliance."
"""
    )


def render_readme(args: argparse.Namespace) -> str:
    models = model_list(args)
    return f"""# Splunk CIM Data-Model Rendered Assets

App: `{args.app_name}`
Acceleration: `{args.acceleration}`
Earliest (summary range): `{args.earliest_time}`
Backfill: `{args.backfill_time or "(default)"}`
Models: {", ".join(f"`{m}`" for m in models)}

Files:

- `datamodels.conf` — acceleration overrides (stage into the app `local/`)
- `apply.sh` — copy `datamodels.conf` into `etc/apps/{args.app_name}/local` and reload
- `rebuild.sh` — rebuild/backfill the selected accelerated models (gated)
- `status.sh` — acceleration summarization status
- `audit.sh` — per-model population checks via `tstats`

Apply on a search head (or SHC deployer for clustered search heads). On an
indexer cluster, accelerated summaries are built on the indexers; ensure
capacity before enabling many models.
"""


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "cim"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "app_name": args.app_name,
                    "acceleration": args.acceleration,
                    "earliest_time": args.earliest_time,
                    "backfill_time": args.backfill_time,
                    "max_concurrent": args.max_concurrent,
                    "models": model_list(args),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "datamodels.conf": render_datamodels(args),
            "apply.sh": render_apply(args),
            "rebuild.sh": render_rebuild(args),
            "status.sh": render_status(args),
            "audit.sh": render_audit(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "cim",
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "models": model_list(args),
        "acceleration": args.acceleration,
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "apply": [["./apply.sh"]],
            "rebuild": [["./rebuild.sh"]],
            "status": [["./status.sh"]],
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
        print(f"Would render CIM data-model assets under {payload['render_dir']}")
    else:
        print(f"Rendered CIM data-model assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
