#!/usr/bin/env python3
"""Render Splunk Monitoring Console setup assets."""

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
    "app.conf",
    "distsearch.conf",
    "splunk_monitoring_console_assets.conf",
    "savedsearches.conf",
    "preflight.sh",
    "apply.sh",
    "add-search-peers.sh",
    "status.sh",
}

DEFAULT_PLATFORM_ALERTS = [
    "Abnormal State of Indexer Processor",
    "Near Critical Disk Usage",
    "Saturated Event-Processing Queues",
    "Search Peer Not Responding",
    "Total License Usage Near Daily Quota",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Monitoring Console setup assets.")
    parser.add_argument("--mode", choices=("standalone", "distributed"), default="distributed")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--enable-auto-config", choices=("true", "false"), default="true")
    parser.add_argument("--enable-forwarder-monitoring", choices=("true", "false"), default="false")
    parser.add_argument("--forwarder-cron", default="*/15 * * * *")
    parser.add_argument("--enable-platform-alerts", choices=("true", "false"), default="false")
    parser.add_argument("--platform-alerts", default=",".join(DEFAULT_PLATFORM_ALERTS))
    parser.add_argument("--search-peers", default="")
    parser.add_argument("--search-peer-scheme", choices=("https", "http"), default="https")
    parser.add_argument("--search-groups", default="")
    parser.add_argument("--default-search-group", default="")
    parser.add_argument("--peer-username", default="")
    parser.add_argument("--restart-splunk", choices=("true", "false"), default="true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def bool_value(value: str) -> bool:
    return value.lower() == "true"


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_search_groups(value: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    if not value.strip():
        return groups
    for raw_group in value.split(";"):
        raw_group = raw_group.strip()
        if not raw_group:
            continue
        if "=" not in raw_group:
            die(f"Invalid --search-groups entry {raw_group!r}; expected name=peer|peer.")
        name, raw_peers = raw_group.split("=", 1)
        name = name.strip()
        peers = [peer.strip() for peer in raw_peers.split("|") if peer.strip()]
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", name):
            die(f"Invalid search group name {name!r}; use letters, numbers, underscores, and hyphens.")
        if not peers:
            die(f"Search group {name!r} must contain at least one peer.")
        groups[name] = peers
    return groups


def peer_uri(peer: str, scheme: str) -> str:
    return f"{scheme}://{peer}"


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


def validate(args: argparse.Namespace) -> None:
    peers = csv_list(args.search_peers)
    peer_set = set(peers)
    for peer in peers:
        if not re.fullmatch(r"[^:\s]+:[0-9]{1,5}", peer):
            die(f"Invalid --search-peers entry {peer!r}; expected host:management_port.")
        port = int(peer.rsplit(":", 1)[1])
        if port < 1 or port > 65535:
            die(f"Invalid --search-peers port in {peer!r}.")
    search_groups = parse_search_groups(args.search_groups)
    for group, group_peers in search_groups.items():
        for peer in group_peers:
            if peer not in peer_set:
                die(f"Search group {group!r} references {peer!r}, which is not in --search-peers.")
    if args.default_search_group and args.default_search_group not in search_groups:
        die("--default-search-group must name one of the --search-groups groups.")
    if peers and not args.peer_username:
        die("--peer-username is required when --search-peers is supplied.")
    for value, option in (
        (args.forwarder_cron, "--forwarder-cron"),
        (args.platform_alerts, "--platform-alerts"),
        (args.search_groups, "--search-groups"),
        (args.default_search_group, "--default-search-group"),
        (args.peer_username, "--peer-username"),
    ):
        no_newline(value, option)
    alerts = csv_list(args.platform_alerts)
    if bool_value(args.enable_platform_alerts) and not alerts:
        die("--platform-alerts must contain at least one saved search name when platform alerts are enabled.")
    for alert in alerts:
        if "[" in alert or "]" in alert:
            die(f"Invalid --platform-alerts entry {alert!r}; saved search names must not contain brackets.")


def render_app_conf(args: argparse.Namespace) -> str:
    return """# Rendered by splunk-monitoring-console-setup. Review before applying.
[install]
is_configured = 1

[ui]
is_visible = 1
label = Monitoring Console
"""


def render_assets_conf(args: argparse.Namespace) -> str:
    lines = ["# Rendered by splunk-monitoring-console-setup. Review before applying.", "[settings]"]
    if args.mode == "distributed" and bool_value(args.enable_auto_config):
        lines.append("mc_auto_config = enabled")
    else:
        lines.append("mc_auto_config = disabled")
    return "\n".join(lines).rstrip() + "\n"


def render_distsearch(args: argparse.Namespace) -> str:
    peers = csv_list(args.search_peers)
    groups = parse_search_groups(args.search_groups)
    lines = [
        "# Rendered by splunk-monitoring-console-setup. Review before applying.",
        "# If peers are added by editing distsearch.conf directly, distribute trusted.pem keys manually.",
    ]
    if not peers:
        lines.append("# No distributed search peers supplied.")
        return "\n".join(lines).rstrip() + "\n"
    lines.extend(
        [
            "[distributedSearch]",
            "servers = " + ",".join(peer_uri(peer, args.search_peer_scheme) for peer in peers),
            "",
        ]
    )
    for group_name, group_peers in groups.items():
        lines.extend(
            [
                f"[distributedSearch:{group_name}]",
                f"default = {'true' if group_name == args.default_search_group else 'false'}",
                "servers = " + ",".join(group_peers),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_savedsearches(args: argparse.Namespace) -> str:
    lines = ["# Rendered by splunk-monitoring-console-setup. Review before applying."]
    if bool_value(args.enable_forwarder_monitoring):
        lines.extend(
            [
                "[DMC Forwarder - Build Asset Table]",
                "disabled = 0",
                f"cron_schedule = {args.forwarder_cron}",
                "",
            ]
        )
    if bool_value(args.enable_platform_alerts):
        for alert in csv_list(args.platform_alerts):
            lines.extend([f"[{alert}]", "disabled = 0", "alert.suppress = 0", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_readme(args: argparse.Namespace) -> str:
    peer_note = (
        f"\nSearch peers to add before distributed auto-config: `{', '.join(csv_list(args.search_peers))}`.\n"
        if csv_list(args.search_peers)
        else "\nNo search peers were supplied. Add search peers before relying on distributed auto-config.\n"
    )
    return f"""# Splunk Monitoring Console Rendered Assets

Mode: `{args.mode}`
Auto-config: `{args.enable_auto_config}`
Forwarder monitoring: `{args.enable_forwarder_monitoring}`
Platform alerts: `{args.enable_platform_alerts}`

Files:

- `app.conf`
- `distsearch.conf`
- `splunk_monitoring_console_assets.conf`
- `savedsearches.conf`
- `preflight.sh`
- `apply.sh`
- `add-search-peers.sh`
- `status.sh`
{peer_note}
`add-search-peers.sh` does not pass remote passwords to Splunk CLI. Add peers
through Splunk Web or an operator-controlled secure process, then run `apply.sh`
to enable Monitoring Console local settings.

Distributed mode still requires correct search peers, unique server names and
host values, internal log forwarding, and role review in the Monitoring Console.
"""


def render_preflight(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    return make_script(
        f"""splunk_home={splunk_home}
test -x "${{splunk_home}}/bin/splunk"
test -d "${{splunk_home}}/etc/apps/splunk_monitoring_console"
"${{splunk_home}}/bin/splunk" btool app list --app=splunk_monitoring_console --debug >/dev/null || true
"${{splunk_home}}/bin/splunk" btool splunk_monitoring_console_assets list --debug >/dev/null || true
"""
    )


def render_apply(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    restart_block = (
        '"${splunk_home}/bin/splunk" restart\n'
        if bool_value(args.restart_splunk)
        else 'echo "Restart skipped. Monitoring Console auto-config normally applies within an hour or after restart."\n'
    )
    return make_script(
        f"""splunk_home={splunk_home}
target_dir="${{splunk_home}}/etc/apps/splunk_monitoring_console/local"
mkdir -p "${{target_dir}}"
cp app.conf splunk_monitoring_console_assets.conf savedsearches.conf "${{target_dir}}/"
echo "distsearch.conf is rendered for review. Add peers through Splunk Web or copy it with trusted.pem key handling."
{restart_block}"""
    )


def render_add_peers(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    peers = " ".join(shell_quote(peer) for peer in csv_list(args.search_peers))
    peer_scheme = shell_quote(args.search_peer_scheme)
    username = json.dumps(args.peer_username)
    return make_script(
        f"""splunk_home={splunk_home}
peer_scheme={peer_scheme}
peer_username={username}
peers=({peers})

if (( ${{#peers[@]}} == 0 )); then
  echo "No search peers were rendered. Re-render with --search-peers host:port,host2:port." >&2
  exit 0
fi
cat <<'EOF'
Search peer onboarding requires remote admin credentials. Splunk CLI documents
this with a password flag, which would expose a secret as a process argument.
This helper therefore prints the peer checklist only.

Use Splunk Web:
  Settings > Distributed search > Search peers > New

Or use an operator-controlled secure session that does not place secrets in
chat, rendered assets, shell history, or reusable automation.
EOF

echo
for peer in "${{peers[@]}}"; do
  echo "Peer: ${{peer_scheme}}://${{peer}}"
  if [[ -n "${{peer_username}}" ]]; then
    echo "  Remote username: ${{peer_username}}"
  fi
done
"${{splunk_home}}/bin/splunk" list search-server || true
"""
    )


def render_status(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    return make_script(
        f"""splunk_home={splunk_home}
"${{splunk_home}}/bin/splunk" list search-server || true
"${{splunk_home}}/bin/splunk" btool splunk_monitoring_console_assets list --debug 2>/dev/null || true
"${{splunk_home}}/bin/splunk" btool distsearch list --debug 2>/dev/null || true
"${{splunk_home}}/bin/splunk" btool savedsearches list "DMC Forwarder - Build Asset Table" --debug 2>/dev/null || true
"""
    )


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "monitoring-console"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "mode": args.mode,
                    "enable_auto_config": bool_value(args.enable_auto_config),
                    "enable_forwarder_monitoring": bool_value(args.enable_forwarder_monitoring),
                    "enable_platform_alerts": bool_value(args.enable_platform_alerts),
                    "search_peers": csv_list(args.search_peers),
                    "search_peer_scheme": args.search_peer_scheme,
                    "search_groups": parse_search_groups(args.search_groups),
                    "default_search_group": args.default_search_group,
                    "peer_username": args.peer_username,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "app.conf": render_app_conf(args),
            "distsearch.conf": render_distsearch(args),
            "splunk_monitoring_console_assets.conf": render_assets_conf(args),
            "savedsearches.conf": render_savedsearches(args),
            "preflight.sh": render_preflight(args),
            "apply.sh": render_apply(args),
            "add-search-peers.sh": render_add_peers(args),
            "status.sh": render_status(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "monitoring-console",
        "mode": args.mode,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "preflight": [["./preflight.sh"]],
            "apply": [["./apply.sh"], ["./add-search-peers.sh"]],
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
        print(f"Would render Monitoring Console assets under {payload['render_dir']}")
    else:
        print(f"Rendered Monitoring Console assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
