#!/usr/bin/env python3
"""Render Splunk Secure Gateway / Connected Experiences readiness assets."""

from __future__ import annotations

import argparse
import json
import shlex
import stat
from pathlib import Path

PRIMARY_SPACEBRIDGE = "prod.spacebridge.spl.mobi"

# Regional health-check hosts (https://<host>/health_check).
REGIONAL_HEALTH_HOSTS = {
    "default": PRIMARY_SPACEBRIDGE,
    "us-east-1": "http.us-east-1.spacebridge.splunkcx.com",
    "eu-central-1": "http.eu-central-1.spacebridge.splunkcx.com",
    "eu-west-1": "http.eu-west-1.spacebridge.splunkcx.com",
    "eu-west-2": "http.eu-west-2.spacebridge.splunkcx.com",
    "ap-southeast-2": "http.ap-southeast-2.spacebridge.splunkcx.com",
}

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "connectivity-preflight.sh",
    "enable.sh",
    "register.sh",
    "mdm-appconfig.xml",
    "status.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Secure Gateway readiness assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--platform", choices=("cloud", "enterprise"), default="enterprise")
    parser.add_argument("--region", choices=tuple(REGIONAL_HEALTH_HOSTS), default="default")
    parser.add_argument("--deployment-name", default="Splunk Secure Gateway")
    parser.add_argument("--mdm", choices=("true", "false"), default="false")
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


def validate(args: argparse.Namespace) -> None:
    if "\n" in (args.splunk_home or "") or "\r" in (args.splunk_home or ""):
        die("--splunk-home must not contain newlines.")
    if "\n" in (args.deployment_name or "") or "\r" in (args.deployment_name or ""):
        die("--deployment-name must not contain newlines.")


def render_connectivity(args: argparse.Namespace) -> str:
    primary = shell_quote(PRIMARY_SPACEBRIDGE)
    regional_host = REGIONAL_HEALTH_HOSTS[args.region]
    regional = shell_quote(regional_host)
    return make_script(
        f"""primary={primary}
regional={regional}
echo "== Spacebridge HTTPS health check (primary) =="
curl -sS -m 15 "https://${{primary}}/health_check" && echo || echo "FAILED: https://${{primary}}/health_check"
echo
if [[ "${{regional}}" != "${{primary}}" ]]; then
  echo "== Spacebridge regional health check =="
  curl -sS -m 15 "https://${{regional}}/health_check" && echo || echo "FAILED: https://${{regional}}/health_check"
  echo
fi
echo "== WebSocket upgrade test (outbound 443) =="
curl -sS -m 15 -i -N \\
  -H "Connection: Upgrade" \\
  -H "Upgrade: websocket" \\
  -H "Host: ${{primary}}" \\
  -H "Origin: https://${{primary}}" \\
  "https://${{primary}}/mobile" | head -1 \\
  || echo "FAILED: WebSocket upgrade to https://${{primary}}/mobile"
echo
echo "Required: outbound 443 to ${{primary}} (no inbound ports)."
echo "If a proxy does SSL decryption, it must support WebSockets or exempt ${{primary}}."
"""
    )


def render_enable(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    cloud_note = (
        'echo "Splunk Cloud: Secure Gateway is managed by Splunk; app enablement is not operator-controlled."\n'
        if args.platform == "cloud"
        else ""
    )
    enable_block = (
        ""
        if args.platform == "cloud"
        else (
            'echo "== enable splunk_secure_gateway =="\n'
            '"${splunk}" display app splunk_secure_gateway 2>/dev/null || true\n'
            '"${splunk}" enable app splunk_secure_gateway 2>/dev/null '
            '|| echo "Could not enable via CLI; enable in Settings > Apps if needed."\n'
        )
    )
    return make_script(
        f"""splunk={splunk}
{cloud_note}{enable_block}echo
echo "== token (JWT) authentication readiness =="
"${{splunk}}" search '| rest splunk_server=local /services/admin/token-auth/tokens_auth | table title disabled' -maxout 0 2>/dev/null \\
  || echo "Could not read token-auth state; verify Settings > Tokens is enabled."
echo
echo "Token authentication MUST be enabled for Connected Experiences/registration."
echo "Enable it in Settings > Tokens (or via authorize.conf / REST) before registering devices."
"""
    )


def render_register(args: argparse.Namespace) -> str:
    name = shell_quote(args.deployment_name)
    return make_script(
        f"""deployment_name={name}
cat <<EOF
Register a mobile device with Splunk Secure Gateway:

Prerequisites:
  - Outbound 443 to {PRIMARY_SPACEBRIDGE} is open (run connectivity-preflight.sh).
  - Token (JWT) authentication is enabled (Settings > Tokens).
  - The user has a role permitted to use Connected Experiences.

In-app registration:
  1. Install the Connected Experiences app (Splunk Mobile / Splunk TV / Splunk AR).
  2. In Splunk Web, go to: Apps > Splunk Secure Gateway > Register a device.
  3. The mobile app displays an authentication code; enter it in Splunk Web,
     or scan the QR code shown in Splunk Web from the mobile app.
  4. Confirm the device appears under Splunk Secure Gateway > Registered devices.

Deployment name shown to users: "${{deployment_name}}"

Note: changing a user's Splunk credentials unregisters their device; they must
re-register. For fleet rollout, use MDM (see mdm-appconfig.xml).
EOF
"""
    )


def render_mdm(args: argparse.Namespace) -> str:
    enabled = bool_value(args.mdm)
    if not enabled:
        return (
            "<!-- Rendered by splunk-secure-gateway. MDM not requested (--mdm false). -->\n"
            "<!-- Set --mdm true to render a Managed App Configuration template. -->\n"
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  Rendered by splunk-secure-gateway. Managed App Configuration (AppConfig) TEMPLATE
  for Splunk Mobile MDM rollout. This is a starting point: confirm the exact keys
  your MDM/Splunk Mobile version expects against the Splunk "Set up MDM and in-app
  registration" documentation before deploying. Fill placeholder values per your
  MDM provider (Intune, Jamf, Workspace ONE, etc.).
-->
<managedAppConfiguration>
  <version>1</version>
  <bundleId>com.splunk.mobile</bundleId>
  <dict>
    <!-- Friendly deployment name shown in the app. -->
    <string keyName="deploymentName">
      <defaultValue><value>{args.deployment_name}</value></defaultValue>
    </string>
    <!-- Spacebridge region (leave blank for default global relay). -->
    <string keyName="spacebridgeRegion">
      <defaultValue><value>{args.region if args.region != "default" else ""}</value></defaultValue>
    </string>
    <!-- Restrict login to MDM-configured devices (see docs). -->
    <boolean keyName="mdmOnlyLogin">
      <defaultValue><value>false</value></defaultValue>
    </boolean>
  </dict>
</managedAppConfiguration>
"""


def render_status(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    primary = shell_quote(PRIMARY_SPACEBRIDGE)
    return make_script(
        f"""splunk={splunk}
primary={primary}
echo "== splunk_secure_gateway app state =="
"${{splunk}}" search '| rest splunk_server=local /services/apps/local/splunk_secure_gateway | table title disabled version' -maxout 0 2>/dev/null \\
  || echo "Could not read app state."
echo
echo "== token-auth state =="
"${{splunk}}" search '| rest splunk_server=local /services/admin/token-auth/tokens_auth | table title disabled' -maxout 0 2>/dev/null \\
  || echo "Could not read token-auth state."
echo
echo "== Spacebridge connectivity =="
curl -sS -m 15 "https://${{primary}}/health_check" && echo || echo "FAILED: https://${{primary}}/health_check"
"""
    )


def render_readme(args: argparse.Namespace) -> str:
    regional_host = REGIONAL_HEALTH_HOSTS[args.region]
    return f"""# Splunk Secure Gateway / Mobile Rendered Assets

Platform: `{args.platform}`
Region: `{args.region}` (health host: `{regional_host}`)
Deployment name: `{args.deployment_name}`
MDM template: `{args.mdm}`

Files:

- `connectivity-preflight.sh` — Spacebridge health + WebSocket tests
- `enable.sh` — enable the app and check token-auth readiness
- `register.sh` — device registration handoff
- `mdm-appconfig.xml` — Managed App Configuration template (when --mdm true)
- `status.sh` — app/token-auth/connectivity status

Required: outbound 443 to `{PRIMARY_SPACEBRIDGE}` (no inbound). Token (JWT)
authentication must be enabled before devices can register.
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
                    "platform": args.platform,
                    "region": args.region,
                    "spacebridge_primary": PRIMARY_SPACEBRIDGE,
                    "spacebridge_health_host": REGIONAL_HEALTH_HOSTS[args.region],
                    "deployment_name": args.deployment_name,
                    "mdm": args.mdm,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "connectivity-preflight.sh": render_connectivity(args),
            "enable.sh": render_enable(args),
            "register.sh": render_register(args),
            "mdm-appconfig.xml": render_mdm(args),
            "status.sh": render_status(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "secure-gateway",
        "platform": args.platform,
        "region": args.region,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "preflight": [["./connectivity-preflight.sh"]],
            "enable": [["./enable.sh"]],
            "register": [["./register.sh"]],
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
        print(f"Would render Secure Gateway assets under {payload['render_dir']}")
    else:
        print(f"Rendered Secure Gateway assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
