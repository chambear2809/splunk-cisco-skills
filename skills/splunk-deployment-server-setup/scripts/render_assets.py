#!/usr/bin/env python3
"""Render Splunk Deployment Server assets.

Reads CLI args (from setup.sh) and emits the DS rendered tree under
``--output-dir/ds/``:
- bootstrap/enable-deploy-server.sh
- bootstrap/deployment-apps-layout.md
- reload/reload-deploy-server.sh
- ha/{haproxy.cfg,dns-record-template.txt,sync-deployment-apps.sh}
- inspect/{inspect-fleet.sh,client-drift-report.py}
- migrate/{retarget-clients.sh,staged-rollout.sh}
- runbook-failure-modes.md
- validate.sh
- preflight-report.md
- handoffs/{agent-management.txt,monitoring-console.txt}
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_NAME = "splunk-deployment-server-setup"

# phoneHome scaling recommendations
PHONE_HOME_SCALE = [
    (0,    500,  60,  "default — acceptable at this scale"),
    (500,  2000, 120, "double the default to reduce DS load"),
    (2000, 5000, 300, "5 min — recommended for mid-size fleets"),
    (5000, 10000, 600, "10 min — required for large fleets"),
    (10000, None, 900, "15 min — consider HA DS pair at this scale"),
]


def _phone_home_recommendation(fleet_size: int) -> tuple[int, str]:
    for lo, hi, interval, note in PHONE_HOME_SCALE:
        if hi is None or fleet_size < hi:
            return interval, note
    return 900, "15 min — HA DS pair recommended"


def render(args: argparse.Namespace) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    out = Path(args.output_dir)
    ds = out / "ds"

    ds_host = args.ds_host or "ds01.example.com"
    ds_uri = args.ds_uri or f"https://{ds_host}:8089"
    fleet_size = int(args.fleet_size)
    phone_home, phone_home_note = _phone_home_recommendation(fleet_size)
    ha_enabled = args.ha_enabled
    ds_host2 = args.ds_host2 or "ds02.example.com"
    ds_vip = args.ds_vip or "ds-vip.example.com"

    for subdir in [
        ds / "bootstrap",
        ds / "reload",
        ds / "ha",
        ds / "inspect",
        ds / "migrate",
        ds / "handoffs",
    ]:
        subdir.mkdir(parents=True, exist_ok=True)

    # bootstrap/enable-deploy-server.sh
    (ds / "bootstrap" / "enable-deploy-server.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Enable the Splunk Deployment Server on this host.\n"
        "# Run as the splunk OS user (or via sudo -u splunk).\n\n"
        "SPLUNK_HOME=\"${SPLUNK_HOME:-/opt/splunk}\"\n"
        "ADMIN_PASS_FILE=\"${ADMIN_PASS_FILE:-/tmp/splunk_admin_password}\"\n\n"
        "# Step 1: Enable the deploy-server feature\n"
        "sudo -u splunk \"${SPLUNK_HOME}/bin/splunk\" enable deploy-server \\\n"
        "  -auth admin:\"$(cat \"${ADMIN_PASS_FILE}\")\"\n\n"
        "# Step 2: Restart to activate\n"
        "sudo systemctl restart SplunkForwarder 2>/dev/null || \\\n"
        "  sudo -u splunk \"${SPLUNK_HOME}/bin/splunk\" restart\n\n"
        "# Step 3: Verify\n"
        f"curl -s -k -u admin:\"$(cat \"${{ADMIN_PASS_FILE}}\")\" \\\n"
        f"  '{ds_uri}/services/deployment/server/clients?count=1&output_mode=json' | \\\n"
        "  python3 -m json.tool | head -5\n"
        "echo 'Deployment server enabled. Add apps to ${SPLUNK_HOME}/etc/deployment-apps/'\n",
        encoding="utf-8",
    )

    # bootstrap/deployment-apps-layout.md
    (ds / "bootstrap" / "deployment-apps-layout.md").write_text(
        "# Deployment Apps Layout\n\n"
        "```\n"
        "${SPLUNK_HOME}/etc/deployment-apps/\n"
        "  <app-name>/\n"
        "    default/\n"
        "      inputs.conf\n"
        "      outputs.conf\n"
        "      props.conf\n"
        "    metadata/\n"
        "      default.meta\n"
        "```\n\n"
        "## Key Rules\n\n"
        "- Apps here are pushed to UFs and HFs — NOT to search heads or indexers.\n"
        "- Do NOT use `etc/apps/` for deployment server apps.\n"
        "- The DS reads `serverclass.conf` from `${SPLUNK_HOME}/etc/system/local/` "
        "or from a deployment app in `etc/deployment-apps/`.\n"
        "- After adding or editing apps, run `reload/reload-deploy-server.sh`.\n"
        "- `filterType` must be `whitelist` or `blacklist` — never rely on the default "
        "(changed in Splunk 9.4.3+).\n\n"
        "## Common App Structure\n\n"
        "| App | Purpose |\n|-----|---------||\n"
        "| `TA-outputs` | Global `outputs.conf` pointing to indexers |\n"
        "| `TA-inputs-linux-os` | Linux OS inputs (syslog, proc, etc.) |\n"
        "| `TA-inputs-windows` | Windows inputs (WinEventLog, etc.) |\n"
        "| `TA-cisco-<product>` | Cisco product inputs |\n"
        "| `TA-base-forwarder` | Base forwarder config (limits, server.conf tuning) |\n",
        encoding="utf-8",
    )

    # reload/reload-deploy-server.sh
    (ds / "reload" / "reload-deploy-server.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Reload the deployment server configuration without a full restart.\n"
        "# Triggers re-read of serverclass.conf and pushes updated app assignments.\n\n"
        "ADMIN_PASS_FILE=\"${ADMIN_PASS_FILE:-/tmp/splunk_admin_password}\"\n\n"
        f"curl -s -k -u admin:\"$(cat \"${{ADMIN_PASS_FILE}}\")\" \\\n"
        f"  -X POST '{ds_uri}/services/deployment/server/_reload' \\\n"
        "  -d '' | python3 -m json.tool\n"
        "echo 'Deployment server reloaded.'\n",
        encoding="utf-8",
    )

    # inspect/inspect-fleet.sh
    (ds / "inspect" / "inspect-fleet.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Inspect the deployment server fleet: clients, check-in lag, app versions.\n\n"
        "ADMIN_PASS_FILE=\"${ADMIN_PASS_FILE:-/tmp/splunk_admin_password}\"\n"
        f"DS_URI=\"${{{ds_uri}}}\"\n"
        "DS_URI=\"${DS_URI:-" + ds_uri + "}\"\n\n"
        "echo '=== Deployment Server Clients (first 20) ==='\n"
        "curl -s -k -u admin:\"$(cat \"${ADMIN_PASS_FILE}\")\" \\\n"
        "  \"${DS_URI}/services/deployment/server/clients?count=20&output_mode=json\" | \\\n"
        "  python3 -m json.tool\n\n"
        "echo '=== Server Classes ==='\n"
        "curl -s -k -u admin:\"$(cat \"${ADMIN_PASS_FILE}\")\" \\\n"
        "  \"${DS_URI}/services/deployment/server/serverclasses?output_mode=json\" | \\\n"
        "  python3 -m json.tool\n\n"
        "echo '=== Deployment Applications ==='\n"
        "curl -s -k -u admin:\"$(cat \"${ADMIN_PASS_FILE}\")\" \\\n"
        "  \"${DS_URI}/services/deployment/server/applications/local?output_mode=json\" | \\\n"
        "  python3 -m json.tool\n",
        encoding="utf-8",
    )

    # inspect/client-drift-report.py
    (ds / "inspect" / "client-drift-report.py").write_text(
        "#!/usr/bin/env python3\n"
        '"""Report clients with stale check-in (lag > threshold)."""\n\n'
        "import json\nimport sys\nimport urllib.request\nimport urllib.error\n"
        "from datetime import datetime, timezone\n\n"
        "DS_URI = sys.argv[1] if len(sys.argv) > 1 else '" + ds_uri + "'\n"
        "LAG_WARN = int(sys.argv[2]) if len(sys.argv) > 2 else 300  # seconds\n"
        "CREDS = sys.argv[3] if len(sys.argv) > 3 else 'admin:changeme'\n\n"
        "import base64, ssl\n"
        "ctx = ssl.create_default_context()\nctx.check_hostname = False\n"
        "ctx.verify_mode = ssl.CERT_NONE\n"
        "req = urllib.request.Request(\n"
        "    f'{DS_URI}/services/deployment/server/clients?count=0&output_mode=json',\n"
        "    headers={'Authorization': 'Basic ' + base64.b64encode(CREDS.encode()).decode()}\n"
        ")\n"
        "resp = urllib.request.urlopen(req, context=ctx)\n"
        "data = json.loads(resp.read())\n"
        "now = datetime.now(timezone.utc).timestamp()\n"
        "stale = []\n"
        "for e in data.get('entry', []):\n"
        "    last = e.get('content', {}).get('lastPhoneHomeTime', 0)\n"
        "    lag = now - last\n"
        "    if lag > LAG_WARN:\n"
        "        stale.append({'client': e['name'], 'lag_s': int(lag)})\n"
        "if stale:\n"
        "    print(f'STALE CLIENTS (lag > {LAG_WARN}s):')\n"
        "    for c in sorted(stale, key=lambda x: -x['lag_s']):\n"
        "        print(f\"  {c['client']}: {c['lag_s']}s\")\n"
        "    sys.exit(1)\n"
        "else:\n"
        "    print(f'All clients checked in within {LAG_WARN}s')\n",
        encoding="utf-8",
    )

    # ha/haproxy.cfg
    (ds / "ha" / "haproxy.cfg").write_text(
        "# HAProxy config for Splunk Deployment Server HA pair.\n"
        "# Both DS instances share the same etc/deployment-apps/ via rsync or Git.\n"
        "# Health check: GET /services/server/info returns 200 when DS is up.\n\n"
        "global\n    log /dev/log local0\n    maxconn 4096\n\n"
        "defaults\n    mode http\n    timeout connect 5s\n"
        "    timeout client  60s\n    timeout server  60s\n\n"
        "frontend splunk_ds\n    bind *:8089\n    default_backend splunk_ds_backend\n\n"
        "backend splunk_ds_backend\n    balance roundrobin\n"
        "    option httpchk GET /services/server/info\n"
        f"    server ds1 {ds_host}:8089 check ssl verify none inter 10s rise 2 fall 3\n"
        f"    server ds2 {ds_host2}:8089 check ssl verify none inter 10s rise 2 fall 3 backup\n",
        encoding="utf-8",
    )

    # ha/dns-record-template.txt
    (ds / "ha" / "dns-record-template.txt").write_text(
        f"# DNS record for DS VIP (used in deploymentclient.conf targetUri)\n"
        f"# Replace with your actual DNS zone and IP addresses.\n\n"
        f"{ds_vip}.    300    IN    A    <DS1_IP>\n"
        f"{ds_vip}.    300    IN    A    <DS2_IP>\n\n"
        f"# Or use a CNAME to your load balancer:\n"
        f"# {ds_vip}.    300    IN    CNAME    <haproxy_or_elb_hostname>.\n\n"
        f"# UF deploymentclient.conf targetUri:\n"
        f"# targetUri = {ds_vip}:8089\n",
        encoding="utf-8",
    )

    # ha/sync-deployment-apps.sh
    (ds / "ha" / "sync-deployment-apps.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Sync deployment-apps from primary DS to secondary DS.\n"
        "# Run on the primary DS after any app change, before reload.\n"
        "# For production, consider Git-based sync (pull on both DS nodes from a shared repo).\n\n"
        f"PRIMARY=\"{ds_host}\"\n"
        f"SECONDARY=\"{ds_host2}\"\n"
        "SPLUNK_HOME=\"${SPLUNK_HOME:-/opt/splunk}\"\n\n"
        "rsync -avz --delete \\\n"
        "  \"${SPLUNK_HOME}/etc/deployment-apps/\" \\\n"
        "  \"splunk@${SECONDARY}:${SPLUNK_HOME}/etc/deployment-apps/\"\n\n"
        "# Then reload on both nodes\n"
        f"ADMIN_PASS_FILE=\"${{ADMIN_PASS_FILE:-/tmp/splunk_admin_password}}\"\n"
        f"for uri in 'https://{ds_host}:8089' 'https://{ds_host2}:8089'; do\n"
        '  curl -s -k -u admin:"$(cat "${ADMIN_PASS_FILE}")" \\\n'
        '    -X POST "${uri}/services/deployment/server/_reload" -d "" > /dev/null\n'
        "done\n"
        "echo 'Sync and reload complete.'\n",
        encoding="utf-8",
    )

    # migrate/retarget-clients.sh
    (ds / "migrate" / "retarget-clients.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Mass re-target UF clients to a new DS URI.\n"
        "# This renders the commands; review before running on your UF fleet.\n"
        "# Requires Ansible, Fabric, or a parallel SSH tool.\n\n"
        "NEW_DS_URI=\"${NEW_DS_URI:-" + ds_uri + "}\"\n\n"
        "cat <<'INSTRUCTIONS'\n"
        "Steps to re-target clients:\n"
        "  1. Deploy a new deployment-app containing deploymentclient.conf:\n"
        "       [deployment-client]\n"
        "       targetUri = ${NEW_DS_URI}\n"
        "  2. Or push via existing DS to a server class covering all UFs.\n"
        "  3. Verify check-in on new DS with inspect/inspect-fleet.sh.\n"
        "  4. After all clients have re-targeted, decommission the old DS.\n"
        "INSTRUCTIONS\n",
        encoding="utf-8",
    )

    # migrate/staged-rollout.sh
    (ds / "migrate" / "staged-rollout.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Staged app rollout: push a new app to a canary server class first,\n"
        "# then expand to full fleet.\n\n"
        "APP_NAME=\"${APP_NAME:-}\"\n"
        "CANARY_CLASS=\"${CANARY_CLASS:-canary_uf_class}\"\n"
        "ADMIN_PASS_FILE=\"${ADMIN_PASS_FILE:-/tmp/splunk_admin_password}\"\n"
        f"DS_URI=\"${{{ds_uri}}}\"\n"
        "DS_URI=\"${DS_URI:-" + ds_uri + "}\"\n\n"
        "if [[ -z \"${APP_NAME}\" ]]; then echo 'Set APP_NAME'; exit 1; fi\n\n"
        "echo \"Step 1: Apply ${APP_NAME} to canary class ${CANARY_CLASS}\"\n"
        "curl -s -k -u admin:\"$(cat \"${ADMIN_PASS_FILE}\")\" \\\n"
        "  -X POST \"${DS_URI}/services/deployment/server/_reload\" -d '' > /dev/null\n\n"
        "echo 'Step 2: Monitor canary for 30 minutes before proceeding'\n"
        "echo 'Step 3: Expand server class to full fleet and reload again'\n",
        encoding="utf-8",
    )

    # runbook-failure-modes.md
    (ds / "runbook-failure-modes.md").write_text(
        "# DS Failure Mode Runbooks\n\n"
        "## Clients Not Checking In\n\n"
        "Check `phoneHomeIntervalInSecs` — for large fleets (5000+ UFs), "
        "the default 60s causes DS overload. Increase to 300–600s.\n"
        "Verify `deploymentclient.conf` `targetUri` points to the correct DS.\n"
        "Run `inspect/inspect-fleet.sh` to check check-in lag distribution.\n\n"
        "## App Not Pushed After Reload\n\n"
        "Verify `filterType` is explicitly `whitelist` or `blacklist` in `serverclass.conf`. "
        "The default changed in Splunk 9.4.3+ and implicit behavior is gone.\n"
        "Check `etc/deployment-apps/<app>/` exists and is readable.\n"
        "Run `reload/reload-deploy-server.sh` again; check `splunkd.log` for errors.\n\n"
        "## DS Overload (503 Errors)\n\n"
        "Symptoms: `rest_call_http.log` shows 503 responses from DS REST API.\n"
        "Immediate: increase `phoneHomeIntervalInSecs` across all UFs.\n"
        "Long-term: add a second DS in HA pair behind a load balancer.\n"
        "See `ha/haproxy.cfg` for the HA pair config.\n\n"
        "## Duplicate DS Enrollment\n\n"
        "A UF enrolled in two DSes will receive apps from both, causing conflicts.\n"
        "Resolve by ensuring `deploymentclient.conf` has only one `targetUri`.\n"
        "Use `inspect/inspect-fleet.sh` to identify dual-enrolled clients.\n\n"
        "## Cascading DS (DS-to-DS) Misbehavior\n\n"
        "Splunk does not support cascading DS (a DS pushing to another DS).\n"
        "If encountered: remove the DS-as-client enrollment, then rebuild the "
        "app push chain through direct UF enrollment.\n",
        encoding="utf-8",
    )

    # validate.sh (in rendered tree, for quick operator use)
    (ds / "validate.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "ADMIN_PASS_FILE=\"${ADMIN_PASS_FILE:-/tmp/splunk_admin_password}\"\n"
        f"DS_URI=\"${{{ds_uri}}}\"\n"
        "DS_URI=\"${DS_URI:-" + ds_uri + "}\"\n"
        "echo '=== DS Server Info ==='\n"
        "curl -s -k -u admin:\"$(cat \"${ADMIN_PASS_FILE}\")\" \\\n"
        "  \"${DS_URI}/services/server/info?output_mode=json\" | python3 -m json.tool | head -20\n"
        "echo '=== DS Clients Count ==='\n"
        "curl -s -k -u admin:\"$(cat \"${ADMIN_PASS_FILE}\")\" \\\n"
        "  \"${DS_URI}/services/deployment/server/clients?count=1&output_mode=json\" | \\\n"
        "  python3 -c \"import json,sys; d=json.load(sys.stdin); print('Total clients:', d.get('paging', {}).get('total', 'unknown'))\"\n",
        encoding="utf-8",
    )

    # preflight-report.md
    phone_home_rec, phone_home_rec_note = _phone_home_recommendation(fleet_size)
    ha_rec = "YES — fleet size requires HA DS pair" if fleet_size >= 5000 else "optional (recommended at 5000+ UFs)"
    (ds / "preflight-report.md").write_text(
        f"# DS Preflight Report\n\n"
        f"Generated: {now}\n\n"
        f"| Check | Value | Status |\n|-------|-------|--------|\n"
        f"| DS host | `{ds_host}` | OK |\n"
        f"| Fleet size | {fleet_size} UFs | OK |\n"
        f"| phoneHomeIntervalInSecs | {phone_home_rec} | {phone_home_rec_note} |\n"
        f"| HA pair recommended | {ha_rec} | {'WARN' if fleet_size >= 5000 and not ha_enabled else 'OK'} |\n"
        f"| filterType explicit | required | Rendered with explicit value |\n",
        encoding="utf-8",
    )

    # handoffs/agent-management.txt
    (ds / "handoffs" / "agent-management.txt").write_text(
        f"# Agent Management handoff\n"
        f"# Pass to: bash skills/splunk-agent-management-setup/scripts/setup.sh\n"
        f"DS_URI={ds_uri}\n"
        f"DS_HOST={ds_host}\n"
        f"# Note: splunk-agent-management-setup owns serverclass.conf authoring.\n"
        f"# splunk-deployment-server-setup owns DS runtime (bootstrap, reload, fleet ops).\n",
        encoding="utf-8",
    )

    # handoffs/monitoring-console.txt
    (ds / "handoffs" / "monitoring-console.txt").write_text(
        f"# Monitoring Console handoff\n"
        f"# Pass to: bash skills/splunk-monitoring-console-setup/scripts/setup.sh\n"
        f"DS_URI={ds_uri}\n"
        f"DS_HOST={ds_host}\n",
        encoding="utf-8",
    )

    for path in ds.rglob("*.sh"):
        path.chmod(0o755)
    for path in ds.rglob("*.py"):
        path.chmod(0o755)

    result = {
        "output_dir": str(out.resolve()),
        "ds_host": ds_host,
        "fleet_size": fleet_size,
        "phone_home_interval": phone_home_rec,
        "ha_enabled": ha_enabled,
        "rendered_files": [str(p.relative_to(out)) for p in sorted(out.rglob("*")) if p.is_file()],
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{SKILL_NAME} renderer")
    parser.add_argument("--phase", default="render")
    parser.add_argument("--output-dir",
                        default=str(PROJECT_ROOT / "splunk-deployment-server-rendered"))
    parser.add_argument("--ds-host", default="")
    parser.add_argument("--ds-uri", default="")
    parser.add_argument("--fleet-size", default="100")
    parser.add_argument("--phone-home-interval", default="")
    parser.add_argument("--handshake-retry-interval", default="60")
    parser.add_argument("--max-client-apps", default="100")
    parser.add_argument("--ha-enabled", action="store_true")
    parser.add_argument("--ds-host2", default="")
    parser.add_argument("--ds-vip", default="")
    parser.add_argument("--accept-cascading-ds-workaround", action="store_true")
    parser.add_argument("--admin-password-file", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = render(args)
    if args.json:
        import json as _json
        print(_json.dumps(result, indent=2))
    else:
        print(f"Rendered to: {result['output_dir']}")
        print(f"DS host:     {result['ds_host']}")
        print(f"Fleet size:  {result['fleet_size']} UFs")
        print(f"phoneHome:   {result['phone_home_interval']}s")
        print(f"Files:       {len(result.get('rendered_files', []))}")


if __name__ == "__main__":
    main()
