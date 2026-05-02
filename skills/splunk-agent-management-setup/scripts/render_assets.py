#!/usr/bin/env python3
"""Render Splunk agent management assets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import stat
from pathlib import Path


GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "serverclass.conf",
    "deploymentclient.conf",
    "preflight.sh",
    "apply-agent-manager.sh",
    "apply-deployment-client.sh",
    "status.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk agent management assets.")
    parser.add_argument("--mode", choices=("agent-manager", "deployment-client", "both"), default="both")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--serverclass-name", default="all_linux_forwarders")
    parser.add_argument("--deployment-app-name", default="ZZZ_cisco_skills_forwarder_base")
    parser.add_argument("--app-source-dir", default="")
    parser.add_argument("--whitelist", default="*")
    parser.add_argument("--blacklist", default="")
    parser.add_argument("--filter-type", choices=("whitelist", "blacklist"), default="whitelist")
    parser.add_argument("--machine-types-filter", default="")
    parser.add_argument("--restart-splunkd", choices=("true", "false"), default="false")
    parser.add_argument("--state-on-client", choices=("enabled", "disabled", "noop"), default="enabled")
    parser.add_argument("--agent-manager-uri", default="")
    parser.add_argument("--client-name", default="")
    parser.add_argument("--phone-home-interval", default="60")
    parser.add_argument("--repository-location", default="$SPLUNK_HOME/etc/apps")
    parser.add_argument("--repository-location-policy", choices=("acceptSplunkHome", "acceptAlways", "rejectAlways"), default="rejectAlways")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def wants_agent_manager(args: argparse.Namespace) -> bool:
    return args.mode in {"agent-manager", "both"}


def wants_deployment_client(args: argparse.Namespace) -> bool:
    return args.mode in {"deployment-client", "both"}


def valid_conf_name(value: str, option: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", value or ""):
        die(f"{option} must contain only letters, numbers, underscore, dot, colon, or hyphen.")


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


def positive_int(value: str, option: str) -> int:
    if not re.fullmatch(r"[0-9]+", value or "") or int(value) < 1:
        die(f"{option} must be a positive integer.")
    return int(value)


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
    deployment_apps = render_dir / "deployment-apps"
    if deployment_apps.is_dir():
        shutil.rmtree(deployment_apps)


def validate(args: argparse.Namespace) -> None:
    valid_conf_name(args.serverclass_name, "--serverclass-name")
    valid_conf_name(args.deployment_app_name, "--deployment-app-name")
    positive_int(args.phone_home_interval, "--phone-home-interval")
    if wants_deployment_client(args) and not args.agent_manager_uri:
        die("--agent-manager-uri is required for deployment-client or both mode.")
    if args.app_source_dir and not Path(args.app_source_dir).expanduser().exists():
        die(f"--app-source-dir not found: {args.app_source_dir}")
    if not split_csv(args.whitelist) and args.filter_type == "whitelist":
        die("--whitelist must contain at least one value when --filter-type whitelist is used.")
    for value, option in (
        (args.whitelist, "--whitelist"),
        (args.blacklist, "--blacklist"),
        (args.machine_types_filter, "--machine-types-filter"),
        (args.agent_manager_uri, "--agent-manager-uri"),
        (args.client_name, "--client-name"),
        (args.repository_location, "--repository-location"),
    ):
        no_newline(value, option)


def render_serverclass(args: argparse.Namespace) -> str:
    lines = [
        "# Rendered by splunk-agent-management-setup. Review before applying.",
        "# Splunk 9.4.3+ changed app-level implicit filterType behavior; this file sets it explicitly.",
        "[global]",
        "restartSplunkd = false",
        "",
        f"[serverClass:{args.serverclass_name}]",
        f"filterType = {args.filter_type}",
    ]
    for index, value in enumerate(split_csv(args.whitelist)):
        lines.append(f"whitelist.{index} = {value}")
    for index, value in enumerate(split_csv(args.blacklist)):
        lines.append(f"blacklist.{index} = {value}")
    if args.machine_types_filter:
        lines.append(f"machineTypesFilter = {args.machine_types_filter}")
    lines.extend(
        [
            "",
            f"[serverClass:{args.serverclass_name}:app:{args.deployment_app_name}]",
            f"filterType = {args.filter_type}",
            f"stateOnClient = {args.state_on_client}",
            f"restartSplunkd = {args.restart_splunkd}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_deploymentclient(args: argparse.Namespace) -> str:
    lines = [
        "# Rendered by splunk-agent-management-setup. Review before applying.",
        "[deployment-client]",
        f"phoneHomeIntervalInSecs = {positive_int(args.phone_home_interval, '--phone-home-interval')}",
        f"repositoryLocation = {args.repository_location}",
        f"serverRepositoryLocationPolicy = {args.repository_location_policy}",
    ]
    if args.client_name:
        lines.append(f"clientName = {args.client_name}")
    lines.extend(
        [
            "",
            "[target-broker:deploymentServer]",
            f"targetUri = {args.agent_manager_uri}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_app_conf(args: argparse.Namespace) -> str:
    return "\n".join(
        [
            "# Rendered placeholder deployment app.",
            "[install]",
            "state = enabled",
            "",
            "[ui]",
            "is_visible = false",
            "label = Cisco Skills Agent Management App",
            "",
        ]
    )


def render_readme(args: argparse.Namespace) -> str:
    files = ["`preflight.sh`", "`status.sh`"]
    if wants_agent_manager(args):
        files.extend(
            [
                "`serverclass.conf`",
                f"`deployment-apps/{args.deployment_app_name}/local/app.conf`",
                "`apply-agent-manager.sh`",
            ]
        )
    if wants_deployment_client(args):
        files.extend(["`deploymentclient.conf`", "`apply-deployment-client.sh`"])
    file_list = "\n".join(f"- {item}" for item in files)
    return f"""# Splunk Agent Management Rendered Assets

Mode: `{args.mode}`

Review `serverclass.conf` and `deploymentclient.conf` before applying. This
workflow intentionally sets app-level `filterType` because Splunk Enterprise
9.4.3 and later changed the implicit app-level default.

Files:

{file_list}
"""


def render_scripts(args: argparse.Namespace) -> dict[str, str]:
    splunk_home = shell_quote(args.splunk_home)
    app = shell_quote(args.deployment_app_name)
    source_dir = shell_quote(str(Path(args.app_source_dir).expanduser().resolve())) if args.app_source_dir else ""
    app_copy = (
        f"rm -rf \"${{deployment_apps_dir}}\"/{app}\n"
        f"cp -R {source_dir} \"${{deployment_apps_dir}}\"/{app}\n"
        if args.app_source_dir
        else f"mkdir -p \"${{deployment_apps_dir}}\"/{app}/local\ncp deployment-apps/{app}/local/app.conf \"${{deployment_apps_dir}}\"/{app}/local/app.conf\n"
    )
    return {
        "preflight.sh": make_script(
            f"""splunk_home={splunk_home}
test -x "${{splunk_home}}/bin/splunk"
if [[ -f serverclass.conf ]]; then "${{splunk_home}}/bin/splunk" btool serverclass list --debug >/dev/null || true; fi
"""
        ),
        "apply-agent-manager.sh": make_script(
            f"""splunk_home={splunk_home}
deployment_apps_dir="${{splunk_home}}/etc/deployment-apps"
system_local="${{splunk_home}}/etc/system/local"
mkdir -p "${{deployment_apps_dir}}" "${{system_local}}"
if [[ -f "${{system_local}}/serverclass.conf" ]]; then
  cp "${{system_local}}/serverclass.conf" "${{system_local}}/serverclass.conf.bak.$(date +%Y%m%d%H%M%S)"
fi
cp serverclass.conf "${{system_local}}/serverclass.conf"
{app_copy}"${{splunk_home}}/bin/splunk" reload deploy-server
"""
        ),
        "apply-deployment-client.sh": make_script(
            f"""splunk_home={splunk_home}
client_app="${{splunk_home}}/etc/apps/{args.deployment_app_name}_deploymentclient"
mkdir -p "${{client_app}}/local"
cp deploymentclient.conf "${{client_app}}/local/deploymentclient.conf"
"${{splunk_home}}/bin/splunk" restart
"""
        ),
        "status.sh": make_script(
            f"""splunk_home={splunk_home}
"${{splunk_home}}/bin/splunk" btool serverclass list --debug || true
"${{splunk_home}}/bin/splunk" list deploy-clients || true
"""
        ),
    }


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "agent-management"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        write_file(render_dir / "README.md", render_readme(args))
        assets.append("README.md")
        metadata = {
            "mode": args.mode,
            "serverclass_name": args.serverclass_name,
            "deployment_app_name": args.deployment_app_name,
            "agent_manager_uri": args.agent_manager_uri,
        }
        write_file(render_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        assets.append("metadata.json")
        if wants_agent_manager(args):
            write_file(render_dir / "serverclass.conf", render_serverclass(args))
            assets.append("serverclass.conf")
            write_file(render_dir / f"deployment-apps/{args.deployment_app_name}/local/app.conf", render_app_conf(args))
            assets.append(f"deployment-apps/{args.deployment_app_name}/local/app.conf")
        if wants_deployment_client(args):
            write_file(render_dir / "deploymentclient.conf", render_deploymentclient(args))
            assets.append("deploymentclient.conf")
        for name, content in render_scripts(args).items():
            write_file(render_dir / name, content, executable=True)
            assets.append(name)
    apply_commands = []
    if wants_agent_manager(args):
        apply_commands.append(["./apply-agent-manager.sh"])
    if wants_deployment_client(args):
        apply_commands.append(["./apply-deployment-client.sh"])
    return {
        "target": "agent-management",
        "mode": args.mode,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "preflight": [["./preflight.sh"]],
            "apply": apply_commands,
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
        print(f"Would render agent management assets under {payload['render_dir']}")
    else:
        print(f"Rendered agent management assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
