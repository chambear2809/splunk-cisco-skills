#!/usr/bin/env python3
"""Render Splunk workload management assets."""

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
    "workload_pools.conf",
    "workload_rules.conf",
    "workload_policy.conf",
    "preflight.sh",
    "apply.sh",
    "status.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk workload management assets.")
    parser.add_argument("--profile", choices=("balanced", "search-priority", "ingest-protect", "custom"), default="balanced")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--app-name", default="ZZZ_cisco_skills_workload_management")
    parser.add_argument("--enable-workload-management", action="store_true")
    parser.add_argument("--enable-admission-rules", action="store_true")
    parser.add_argument("--search-cpu", default="")
    parser.add_argument("--ingest-cpu", default="")
    parser.add_argument("--misc-cpu", default="")
    parser.add_argument("--default-search-pool", default="search_standard")
    parser.add_argument("--critical-search-pool", default="search_critical")
    parser.add_argument("--ingest-pool", default="ingest_default")
    parser.add_argument("--misc-pool", default="misc_default")
    parser.add_argument("--critical-role", default="admin")
    parser.add_argument("--long-running-runtime", default="10m")
    parser.add_argument("--long-running-action", choices=("none", "alert", "abort", "move"), default="abort")
    parser.add_argument("--admission-alltime-action", choices=("disabled", "filter"), default="filter")
    parser.add_argument("--admission-exempt-role", default="admin")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def positive_int(value: str, option: str) -> int:
    if not re.fullmatch(r"[0-9]+", value or "") or int(value) < 1:
        die(f"{option} must be a positive integer.")
    return int(value)


def conf_name(value: str, option: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value or ""):
        die(f"{option} must contain only letters, numbers, and underscore.")


def runtime_value(value: str, option: str) -> None:
    if not re.fullmatch(r"[0-9]+(s|second|seconds|m|minute|minutes|h|hour|hours)", value or ""):
        die(f"{option} must be a runtime value such as 30s, 10m, or 1h.")


def predicate_value(value: str, option: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.*:-]+", value or ""):
        die(f"{option} must contain only letters, numbers, underscore, dot, star, colon, or hyphen.")


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


def default_weights(profile: str) -> tuple[int, int, int]:
    if profile == "search-priority":
        return 80, 15, 5
    if profile == "ingest-protect":
        return 55, 35, 10
    return 70, 20, 10


def weights(args: argparse.Namespace) -> tuple[int, int, int]:
    default_search, default_ingest, default_misc = default_weights(args.profile)
    search = positive_int(args.search_cpu or str(default_search), "--search-cpu")
    ingest = positive_int(args.ingest_cpu or str(default_ingest), "--ingest-cpu")
    misc = positive_int(args.misc_cpu or str(default_misc), "--misc-cpu")
    if search + ingest + misc != 100:
        die("--search-cpu, --ingest-cpu, and --misc-cpu must add up to 100.")
    return search, ingest, misc


def validate(args: argparse.Namespace) -> None:
    for value, option in (
        (args.app_name, "--app-name"),
        (args.default_search_pool, "--default-search-pool"),
        (args.critical_search_pool, "--critical-search-pool"),
        (args.ingest_pool, "--ingest-pool"),
        (args.misc_pool, "--misc-pool"),
    ):
        conf_name(value, option)
    runtime_value(args.long_running_runtime, "--long-running-runtime")
    predicate_value(args.critical_role, "--critical-role")
    predicate_value(args.admission_exempt_role, "--admission-exempt-role")
    weights(args)


def render_workload_pools(args: argparse.Namespace) -> str:
    search_cpu, ingest_cpu, misc_cpu = weights(args)
    return f"""# Rendered by splunk-workload-management-setup. Review before applying.
[general]
default_pool = {args.default_search_pool}
ingest_pool = {args.ingest_pool}
enabled = {"true" if args.enable_workload_management else "false"}
workload_pool_base_dir_name = splunk

[workload_category:search]
cpu_weight = {search_cpu}
mem_weight = {search_cpu}

[workload_category:ingest]
cpu_weight = {ingest_cpu}
mem_weight = {ingest_cpu}

[workload_category:misc]
cpu_weight = {misc_cpu}
mem_weight = {misc_cpu}

[workload_pool:{args.default_search_pool}]
category = search
cpu_weight = 70
mem_weight = 100
default_category_pool = 1

[workload_pool:{args.critical_search_pool}]
category = search
cpu_weight = 30
mem_weight = 100
default_category_pool = 0

[workload_pool:{args.ingest_pool}]
category = ingest
cpu_weight = 100
mem_weight = 100
default_category_pool = 1

[workload_pool:{args.misc_pool}]
category = misc
cpu_weight = 100
mem_weight = 100
default_category_pool = 1
"""


def render_workload_rules(args: argparse.Namespace) -> str:
    rule_names = ["critical_role_to_" + args.critical_search_pool]
    if args.long_running_action != "none":
        rule_names.append("long_running_search_guardrail")
    lines = [
        "# Rendered by splunk-workload-management-setup. Review predicates before applying.",
        "[workload_rules_order]",
        f"rules = {','.join(rule_names)}",
        "",
        f"[workload_rule:critical_role_to_{args.critical_search_pool}]",
        f"predicate = role={args.critical_role}",
        f"workload_pool = {args.critical_search_pool}",
        "disabled = 0",
        "",
    ]
    if args.long_running_action != "none":
        lines.extend(
            [
                "[workload_rule:long_running_search_guardrail]",
                f"predicate = (role!={args.admission_exempt_role} AND search_time_range=alltime) AND runtime>{args.long_running_runtime}",
                f"action = {args.long_running_action}",
            ]
        )
        if args.long_running_action == "move":
            lines.append(f"workload_pool = {args.default_search_pool}")
        lines.extend(
            [
                "user_message = Long-running all-time search matched workload guardrail.",
                "disabled = 0",
                "",
            ]
        )
    if args.admission_alltime_action != "disabled":
        lines.extend(
            [
                "[search_filter_rule:block_alltime_searches]",
                f"predicate = search_time_range=alltime AND (NOT role={args.admission_exempt_role})",
                f"action = {args.admission_alltime_action}",
                "user_message = All-time searches are restricted by admission control.",
                "disabled = 0",
                "",
            ]
        )
    return "\n".join(lines)


def render_workload_policy(args: argparse.Namespace) -> str:
    enabled = "1" if args.enable_admission_rules else "0"
    return f"""# Rendered by splunk-workload-management-setup. Review before applying.
[search_admission_control]
admission_rules_enabled = {enabled}
"""


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk Workload Management Rendered Assets

Profile: `{args.profile}`

Files:

- `workload_pools.conf`
- `workload_rules.conf`
- `workload_policy.conf`
- `preflight.sh`
- `apply.sh`
- `status.sh`

Workload management remains disabled unless rendered with
`--enable-workload-management`. Admission rules remain globally disabled unless
rendered with `--enable-admission-rules`.
"""


def render_scripts(args: argparse.Namespace) -> dict[str, str]:
    splunk_home = shell_quote(args.splunk_home)
    app_name = shell_quote(args.app_name)
    return {
        "preflight.sh": make_script(
            f"""splunk_home={splunk_home}
test -x "${{splunk_home}}/bin/splunk"
if command -v systemctl >/dev/null 2>&1; then systemctl status Splunkd >/dev/null 2>&1 || true; fi
"${{splunk_home}}/bin/splunk" show workload-management-status --verbose || true
"""
        ),
        "apply.sh": make_script(
            f"""splunk_home={splunk_home}
app_name={app_name}
enable_workload_management={"true" if args.enable_workload_management else "false"}
app_dir="${{splunk_home}}/etc/apps/${{app_name}}/local"
mkdir -p "${{app_dir}}"
cp workload_pools.conf workload_rules.conf workload_policy.conf "${{app_dir}}/"
"${{splunk_home}}/bin/splunk" btool workload_pools list --debug >/dev/null
"${{splunk_home}}/bin/splunk" btool workload_rules list --debug >/dev/null
"${{splunk_home}}/bin/splunk" _internal call /services/workloads/pools/_reload >/dev/null 2>&1 || true
"${{splunk_home}}/bin/splunk" _internal call "/servicesNS/nobody/${{app_name}}/workloads/rules/_reload" >/dev/null 2>&1 || true
if [[ "${{enable_workload_management}}" == "true" ]]; then
  "${{splunk_home}}/bin/splunk" enable workload-management
fi
"""
        ),
        "status.sh": make_script(
            f"""splunk_home={splunk_home}
"${{splunk_home}}/bin/splunk" show workload-management-status --verbose || true
"${{splunk_home}}/bin/splunk" list workload-pool || true
"${{splunk_home}}/bin/splunk" list workload-rule || true
"${{splunk_home}}/bin/splunk" list workload-rule -workload_rule_type search_filter || true
"""
        ),
    }


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "workload-management"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "profile": args.profile,
                    "app_name": args.app_name,
                    "enable_workload_management": args.enable_workload_management,
                    "enable_admission_rules": args.enable_admission_rules,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "workload_pools.conf": render_workload_pools(args),
            "workload_rules.conf": render_workload_rules(args),
            "workload_policy.conf": render_workload_policy(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content)
            assets.append(rel)
        for rel, content in render_scripts(args).items():
            write_file(render_dir / rel, content, executable=True)
            assets.append(rel)
    return {
        "target": "workload-management",
        "profile": args.profile,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "preflight": [["./preflight.sh"]],
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
        print(f"Would render workload management assets under {payload['render_dir']}")
    else:
        print(f"Rendered workload management assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
