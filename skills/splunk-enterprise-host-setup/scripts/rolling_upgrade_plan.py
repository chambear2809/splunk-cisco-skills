#!/usr/bin/env python3
"""Render a rolling upgrade plan for clustered Splunk Enterprise hosts."""

from __future__ import annotations

import argparse
import json
import shlex
from typing import Any


SETUP_SCRIPT = "skills/splunk-enterprise-host-setup/scripts/setup.sh"
VALIDATE_SCRIPT = "skills/splunk-enterprise-host-setup/scripts/validate.sh"

CLUSTERED_ROLES = {"indexer-peer", "shc-member"}
VALID_ROLES = {
    "standalone-search-tier",
    "standalone-indexer",
    "heavy-forwarder",
    "cluster-manager",
    "indexer-peer",
    "shc-deployer",
    "shc-member",
}


def split_hosts(raw_hosts: str) -> list[str]:
    hosts = [host.strip() for host in raw_hosts.split(",") if host.strip()]
    if not hosts:
        raise argparse.ArgumentTypeError("--hosts must contain at least one host")
    for host in hosts:
        if any(ch.isspace() for ch in host):
            raise argparse.ArgumentTypeError(f"host names must not contain whitespace: {host!r}")
    return hosts


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def with_ssh_host(host: str, command: list[str], execution: str) -> str:
    rendered = shell_join(command)
    if execution != "ssh":
        return rendered
    return f"SPLUNK_SSH_HOST={shlex.quote(host)} {rendered}"


def optional_arg(command: list[str], flag: str, value: str | None) -> None:
    if value:
        command.extend([flag, value])


def unique_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def setup_command(args: argparse.Namespace, host: str) -> str:
    command = [
        "bash",
        SETUP_SCRIPT,
        "--phase",
        args.phase,
        "--execution",
        args.execution,
        "--deployment-mode",
        "clustered",
        "--host-bootstrap-role",
        args.role,
    ]
    optional_arg(command, "--source", args.source)
    optional_arg(command, "--url", args.url)
    optional_arg(command, "--file", args.file)
    optional_arg(command, "--package-type", args.package_type)
    optional_arg(command, "--splunk-home", args.splunk_home)
    optional_arg(command, "--service-user", args.service_user)
    optional_arg(command, "--admin-password-file", args.admin_password_file)
    optional_arg(command, "--cluster-manager-uri", args.cluster_manager_uri)
    optional_arg(command, "--deployer-uri", args.deployer_uri)
    optional_arg(command, "--discovery-secret-file", args.discovery_secret_file)
    optional_arg(command, "--idxc-secret-file", args.idxc_secret_file)
    optional_arg(command, "--shc-secret-file", args.shc_secret_file)
    command.extend(args.setup_arg or [])
    return with_ssh_host(host, command, args.execution)


def validate_command(args: argparse.Namespace, host: str, role: str | None = None) -> str:
    command = [
        "bash",
        VALIDATE_SCRIPT,
        "--execution",
        args.execution,
        "--host-bootstrap-role",
        role or args.role,
    ]
    optional_arg(command, "--splunk-home", args.splunk_home)
    optional_arg(command, "--admin-password-file", args.admin_password_file)
    optional_arg(command, "--cluster-manager-uri", args.cluster_manager_uri)
    optional_arg(command, "--deployer-uri", args.deployer_uri)
    return with_ssh_host(host, command, args.execution)


def gate_commands(args: argparse.Namespace) -> list[str]:
    gates: list[str] = []
    if args.role == "indexer-peer":
        manager_host = args.cluster_manager_host or "<cluster-manager-host>"
        gates.append(
            with_ssh_host(manager_host, [
                "bash",
                VALIDATE_SCRIPT,
                "--execution",
                args.execution,
                "--host-bootstrap-role",
                "cluster-manager",
                *(
                    ["--splunk-home", args.splunk_home]
                    if args.splunk_home else []
                ),
                *(
                    ["--admin-password-file", args.admin_password_file]
                    if args.admin_password_file else []
                ),
            ], args.execution)
        )
        gates.append(
            "Run `splunk show cluster-status --verbose` on the cluster manager "
            "and continue only when replication and search factors are met."
        )
    elif args.role == "shc-member":
        captain_host = args.shc_captain_host or "<existing-shc-member-or-captain-host>"
        gates.append(validate_command(args, captain_host, "shc-member"))
        gates.append(
            "Run `splunk show shcluster-status` on an existing SHC member and "
            "continue only when all members are up, searchable, and in sync."
        )
    else:
        gates.append(
            "Run the role-specific validate.sh command before and after the change window."
        )
    return gates


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    hosts = args.hosts
    clustered = args.role in CLUSTERED_ROLES
    waves = []
    for index, host_group in enumerate(([host] for host in hosts) if clustered else [hosts], start=1):
        host_list = list(host_group)
        precheck = gate_commands(args)
        postcheck = unique_items(
            [validate_command(args, host) for host in host_list] + gate_commands(args)
        )
        waves.append(
            {
                "wave": index,
                "hosts": host_list,
                "precheck": precheck,
                "upgrade": [setup_command(args, host) for host in host_list],
                "postcheck": postcheck,
            }
        )

    notes = [
        "Render-only plan: this script does not SSH, restart Splunk, or modify hosts.",
        "Keep one clustered host in flight at a time and wait for health gates before moving on.",
        "Secret values stay in local files referenced by --admin-password-file, --idxc-secret-file, --discovery-secret-file, or --shc-secret-file.",
    ]
    if clustered and len(hosts) < 2:
        notes.append("Only one host was supplied; rolling order is still shown as a single wave.")
    if args.role == "indexer-peer" and not args.cluster_manager_uri:
        notes.append("Add --cluster-manager-uri so per-host validation can verify indexer clustering context.")
    if args.role == "shc-member" and not args.deployer_uri:
        notes.append("Add --deployer-uri when the rolling window also needs SHC app bundle coordination.")

    return {
        "workflow": "splunk-enterprise-host-rolling-upgrade",
        "mode": "plan-only",
        "role": args.role,
        "phase": args.phase,
        "execution": args.execution,
        "hosts": hosts,
        "waves": waves,
        "notes": notes,
    }


def render_text(plan: dict[str, Any]) -> str:
    lines = [
        f"Workflow: {plan['workflow']}",
        f"Role: {plan['role']}",
        f"Phase: {plan['phase']}",
        f"Execution: {plan['execution']}",
        "",
        "Notes:",
    ]
    for note in plan["notes"]:
        lines.append(f"- {note}")
    for wave in plan["waves"]:
        lines.extend(["", f"Wave {wave['wave']}: {', '.join(wave['hosts'])}", "Precheck:"])
        lines.extend(f"  {item}" for item in wave["precheck"])
        lines.append("Upgrade:")
        lines.extend(f"  {item}" for item in wave["upgrade"])
        lines.append("Postcheck:")
        lines.extend(f"  {item}" for item in wave["postcheck"])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a safe rolling upgrade plan for Splunk Enterprise clustered hosts."
    )
    parser.add_argument("--role", required=True, choices=sorted(VALID_ROLES))
    parser.add_argument("--hosts", required=True, type=split_hosts, help="Comma-separated target host list")
    parser.add_argument("--phase", default="install", choices=["download", "install", "configure", "cluster", "all"])
    parser.add_argument("--execution", default="ssh", choices=["ssh", "local"])
    parser.add_argument("--source", choices=["auto", "splunk-auth", "remote", "local"])
    parser.add_argument("--url")
    parser.add_argument("--file")
    parser.add_argument("--package-type", choices=["auto", "tgz", "rpm", "deb"])
    parser.add_argument("--splunk-home")
    parser.add_argument("--service-user")
    parser.add_argument("--admin-password-file")
    parser.add_argument("--cluster-manager-uri")
    parser.add_argument("--cluster-manager-host")
    parser.add_argument("--deployer-uri")
    parser.add_argument("--shc-captain-host")
    parser.add_argument("--discovery-secret-file")
    parser.add_argument("--idxc-secret-file")
    parser.add_argument("--shc-secret-file")
    parser.add_argument(
        "--setup-arg",
        action="append",
        default=[],
        help="Additional setup.sh argument token; repeat for flags and values.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = build_plan(args)
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        print(render_text(plan), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
