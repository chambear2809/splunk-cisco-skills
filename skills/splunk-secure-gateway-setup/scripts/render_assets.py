#!/usr/bin/env python3
"""Render Splunk Secure Gateway / Spacebridge assets (egress preflight, MDM config, runbooks)."""

from __future__ import annotations

import argparse
import json
import re
import stat
from pathlib import Path

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "instance-id-config.json",
    "egress-preflight.sh",
    "deployment-settings-runbook.md",
    "registration-runbook.md",
}

SPACEBRIDGE_HOST = "prod.spacebridge.spl.mobi"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Secure Gateway assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--app-name", default="splunk_secure_gateway")
    parser.add_argument("--action", choices=("configure", "enable", "disable"), default="configure")
    parser.add_argument("--deployment-name", default="")
    parser.add_argument("--visible-apps", default="")
    parser.add_argument("--private-spacebridge", choices=("true", "false"), default="false")
    parser.add_argument("--custom-endpoint-id", default="")
    parser.add_argument("--custom-endpoint-hostname", default="")
    parser.add_argument("--custom-endpoint-grpc-hostname", default="")
    parser.add_argument("--client-cert-required", choices=("true", "false"), default="true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


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


def validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    for value, option in (
        (args.deployment_name, "--deployment-name"),
        (args.custom_endpoint_id, "--custom-endpoint-id"),
        (args.custom_endpoint_hostname, "--custom-endpoint-hostname"),
        (args.custom_endpoint_grpc_hostname, "--custom-endpoint-grpc-hostname"),
    ):
        no_newline(value, option)
    for app in csv_list(args.visible_apps):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", app):
            die(f"Visible app {app!r} must be a valid app name.")
    for value, option in (
        (args.custom_endpoint_hostname, "--custom-endpoint-hostname"),
        (args.custom_endpoint_grpc_hostname, "--custom-endpoint-grpc-hostname"),
    ):
        if value and not re.fullmatch(r"[A-Za-z0-9.-]+", value):
            die(f"{option} must be a hostname.")
    if args.private_spacebridge == "true" and not (
        args.custom_endpoint_id and args.custom_endpoint_hostname and args.custom_endpoint_grpc_hostname
    ):
        die(
            "--private-spacebridge true requires --custom-endpoint-id, "
            "--custom-endpoint-hostname, and --custom-endpoint-grpc-hostname."
        )


def render_instance_id(args: argparse.Namespace) -> str:
    server_directory: dict = {
        "sign_public_key": "<populate_from_Generate_an_Instance_ID_File>",
        "encrypt_public_key": "<populate_from_Generate_an_Instance_ID_File>",
    }
    if args.deployment_name:
        server_directory["label"] = args.deployment_name
    config: dict = {"server_directory": [server_directory]}
    if args.private_spacebridge == "true":
        config["endpoint_config"] = [
            {
                "custom_endpoint_id": args.custom_endpoint_id,
                "custom_endpoint_hostname": args.custom_endpoint_hostname,
                "custom_endpoint_grpc_hostname": args.custom_endpoint_grpc_hostname,
                "client_cert_required": args.client_cert_required == "true",
            }
        ]
    return json.dumps(config, indent=2, sort_keys=True) + "\n"


def render_egress_preflight(args: argparse.Namespace) -> str:
    host = SPACEBRIDGE_HOST
    if args.private_spacebridge == "true" and args.custom_endpoint_hostname:
        host = args.custom_endpoint_hostname
    return (
        "#!/usr/bin/env bash\nset -euo pipefail\n\n"
        f'host="{host}"\n'
        "echo \"Checking outbound 443 (WebSocket) to ${host} ...\"\n"
        'if command -v nc >/dev/null 2>&1; then\n'
        '  nc -z -w 5 "${host}" 443 || { echo "FAIL: ${host}:443 not reachable" >&2; exit 1; }\n'
        '  echo "OK: ${host}:443 reachable"\n'
        'else\n'
        '  curl -fsS --max-time 5 -o /dev/null "https://${host}" || { echo "FAIL: ${host} not reachable" >&2; exit 1; }\n'
        '  echo "OK: ${host} reachable"\n'
        'fi\n'
        'echo "Splunk Secure Gateway requires outbound 443 to the Spacebridge host. No inbound ports are opened."\n'
    )


def render_deployment_runbook(args: argparse.Namespace) -> str:
    apps = csv_list(args.visible_apps)
    apps_line = ", ".join(apps) if apps else "(choose the apps to expose to mobile)"
    return f"""# Secure Gateway Deployment Settings Runbook

Configure in Splunk Web: Administration > Deployment configuration > Advanced
settings (admin role required).

1. Deployment name: `{args.deployment_name or '(set a friendly deployment name)'}`.
2. App visibility: choose which apps show dashboards in the mobile apps:
   {apps_line}.
3. Spacebridge location/region: select the Spacebridge region for your data
   residency requirements.
4. Mobile notifications and device management: review under the Secure Gateway
   app's Administration pages.

These settings are managed through Splunk Web; this skill enables/disables the
app and validates Spacebridge egress.
"""


def render_registration_runbook(args: argparse.Namespace) -> str:
    return """# Secure Gateway Registration Runbook

Device registration is interactive (auth code or QR) and cannot be scripted.

In-app registration (single instance):

1. In the Connected Experiences mobile app, start registration.
2. Enter the authentication code shown, or scan the QR code from Secure Gateway.
3. The device exchanges keys with Spacebridge and registers.

MDM / in-app registration at scale:

1. Add the Connected Experiences app to your MDM provider.
2. In Secure Gateway, Generate an Instance ID File (combine multiple instances
   with the concatenation feature if needed).
3. Add the instance ID file contents (see `instance-id-config.json`) as a custom
   app configuration in your MDM provider.
4. Users select the deployment and log in with their Splunk credentials.
"""


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk Secure Gateway Rendered Assets

App: `{args.app_name}`
Action: `{args.action}`
Private Spacebridge: `{args.private_spacebridge}`

Files:

- `instance-id-config.json` - MDM custom app configuration skeleton
- `egress-preflight.sh` - outbound 443 check to the Spacebridge host
- `deployment-settings-runbook.md` - Splunk Web deployment settings steps
- `registration-runbook.md` - device registration (auth code / QR / MDM)

Splunk Secure Gateway connects mobile devices through Spacebridge over outbound
443 to `{SPACEBRIDGE_HOST}` (no inbound ports). Enabling the app opens that
egress and requires `--accept-spacebridge-egress`. Deployment settings and
device registration are Splunk Web / MDM operations.
"""


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "secure-gateway"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "app_name": args.app_name,
                    "action": args.action,
                    "deployment_name": args.deployment_name,
                    "visible_apps": csv_list(args.visible_apps),
                    "private_spacebridge": args.private_spacebridge,
                    "spacebridge_host": SPACEBRIDGE_HOST,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "instance-id-config.json": render_instance_id(args),
            "egress-preflight.sh": render_egress_preflight(args),
            "deployment-settings-runbook.md": render_deployment_runbook(args),
            "registration-runbook.md": render_registration_runbook(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "secure-gateway",
        "app_name": args.app_name,
        "action": args.action,
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
        print(f"Would render Secure Gateway assets under {payload['render_dir']}")
    else:
        print(f"Rendered Secure Gateway assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
