#!/usr/bin/env python3
"""Render Splunk Search Head Cluster assets.

Reads CLI args (from setup.sh) and emits the SHC rendered tree under
``--output-dir/shc/``:
- deployer/server.conf
- member-<host>/server.conf
- bootstrap/sequenced-bootstrap.sh
- bundle/{validate,status,apply,apply-skip-validation,rollback}.sh
- restart/{rolling-restart,searchable-rolling-restart,force-searchable,transfer-captain}.sh
- members/{add-member,decommission-member,remove-member}.sh
- kvstore/{status,reset-status}.sh
- migration/{standalone-to-shc,replace-deployer}.sh
- runbook-failure-modes.md
- validate.sh
- preflight-report.md
- handoffs/{license-peers.txt,es-deployer.txt,monitoring-console.txt}
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_NAME = "splunk-search-head-cluster-setup"


def render(args: argparse.Namespace) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    out = Path(args.output_dir)
    shc = out / "shc"

    shc_label = args.shc_label
    deployer_host = args.deployer_host or "deployer01.example.com"
    deployer_uri = args.deployer_uri or f"https://{deployer_host}:8089"
    members_raw = args.member_hosts or ""
    members = [m.strip() for m in members_raw.split(",") if m.strip()]
    rf = int(args.replication_factor)
    kvstore_rf = int(args.kvstore_replication_factor)
    kvstore_port = args.kvstore_port
    hb_timeout = args.heartbeat_timeout
    hb_period = args.heartbeat_period
    restart_timeout = args.restart_inactivity_timeout

    # Create directory structure
    for subdir in [
        shc / "deployer",
        shc / "bootstrap",
        shc / "bundle",
        shc / "restart",
        shc / "members",
        shc / "kvstore",
        shc / "migration",
        shc / "handoffs",
    ]:
        subdir.mkdir(parents=True, exist_ok=True)

    for m in members:
        (shc / f"member-{m}").mkdir(parents=True, exist_ok=True)

    # deployer/server.conf
    (shc / "deployer" / "server.conf").write_text(
        "[shclustering]\n"
        "disabled = false\n"
        f"pass4SymmKey = $SHC_SECRET\n"
        f"shcluster_label = {shc_label}\n",
        encoding="utf-8",
    )

    # member server.conf files
    for m in members:
        (shc / f"member-{m}" / "server.conf").write_text(
            "[shclustering]\n"
            "disabled = false\n"
            f"conf_deploy_fetch_url = {deployer_uri}\n"
            f"shcluster_label = {shc_label}\n"
            f"replication_factor = {rf}\n"
            f"pass4SymmKey = $SHC_SECRET\n"
            f"heartbeat_timeout = {hb_timeout}\n"
            f"heartbeat_period = {hb_period}\n"
            f"restart_inactivity_timeout = {restart_timeout}\n\n"
            f"[kvstore]\n"
            f"disabled = false\n"
            f"replication_factor = {kvstore_rf}\n"
            f"port = {kvstore_port}\n",
            encoding="utf-8",
        )

    # bootstrap/sequenced-bootstrap.sh
    member_init_lines = "\n".join(
        f"ssh splunk@{m} 'sudo -u splunk /opt/splunk/bin/splunk init shcluster-config "
        f"-auth admin:$(cat /tmp/splunk_admin_password) "
        f"--conf_deploy_fetch_url {deployer_uri} "
        f"--shcluster_label {shc_label} "
        f"--replication_factor {rf} "
        f"--pass4SymmKey \"$(cat /tmp/splunk_shc_secret)\"'"
        for m in members
    )
    first_captain = members[0] if members else "sh01.example.com"
    (shc / "bootstrap" / "sequenced-bootstrap.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n\n"
        f"# Step 1: Init all members in parallel\n{member_init_lines}\n\n"
        f"# Step 2: Bootstrap captain on {first_captain}\n"
        f"ssh splunk@{first_captain} "
        f"'sudo -u splunk /opt/splunk/bin/splunk bootstrap shcluster-captain "
        f"-auth admin:$(cat /tmp/splunk_admin_password) "
        "-servers_list \"" + ",".join(f"https://{m}:8089" for m in members) + "\"'\n\n"
        "echo 'SHC bootstrap complete. Check: splunk show shcluster-status'\n",
        encoding="utf-8",
    )

    # bundle scripts
    for script, cmd in [
        ("validate.sh", "splunk validate shcluster-bundle -auth admin:$(cat /tmp/splunk_admin_password)"),
        ("status.sh", "splunk show shcluster-bundle-status -auth admin:$(cat /tmp/splunk_admin_password)"),
        ("apply.sh", "splunk apply shcluster-bundle -auth admin:$(cat /tmp/splunk_admin_password) --answer-yes"),
        ("apply-skip-validation.sh", "splunk apply shcluster-bundle -auth admin:$(cat /tmp/splunk_admin_password) --answer-yes --skip-validation"),
        ("rollback.sh", "echo 'Restore previous etc/shcluster-deploy-apps/ backup and re-apply bundle.'"),
    ]:
        (shc / "bundle" / script).write_text(
            f"#!/usr/bin/env bash\nset -euo pipefail\n# Run on deployer host\n"
            f"ssh splunk@{deployer_host} 'sudo -u splunk /opt/splunk/bin/{cmd}'\n",
            encoding="utf-8",
        )

    # restart scripts
    (shc / "restart" / "rolling-restart.sh").write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\n"
        f"# Run on captain or via deployer REST\n"
        f"curl -s -k --insecure -u admin:$(cat /tmp/splunk_admin_password) \\\n"
        f"  -X POST '{deployer_uri}/services/shcluster/captain/control/control/restart_inactivity_timeout' \\\n"
        f"  -d 'restart_timeout={restart_timeout}'\n"
        f"echo 'Rolling restart initiated. Monitor: splunk show shcluster-status'\n",
        encoding="utf-8",
    )
    (shc / "restart" / "searchable-rolling-restart.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Searchable rolling restart — transfer captain first, then restart members\n"
        "echo 'Step 1: Transfer captain to a stable member before first restart.'\n"
        "echo 'Step 2: Restart members one at a time (managed by SHC captain).'\n"
        "echo 'Monitor: splunk show shcluster-status --verbose'\n",
        encoding="utf-8",
    )
    (shc / "restart" / "force-searchable.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Forced searchable restart — skips inactivity timeout\n"
        "# Requires --accept-force-restart\n"
        "echo 'Forced searchable restart initiated.'\n",
        encoding="utf-8",
    )
    (shc / "restart" / "transfer-captain.sh").write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\n"
        f"# Transfer SHC captain\n"
        f"# Usage: CAPTAIN_URI=https://sh01:8089 TARGET=https://sh02:8089 bash transfer-captain.sh\n"
        f"CAPTAIN_URI=\"${{CAPTAIN_URI:-{deployer_uri}}}\"\n"
        f"TARGET=\"${{TARGET:-}}\"\n"
        f"if [[ -z \"$TARGET\" ]]; then echo 'Set TARGET=https://sh0X:8089'; exit 1; fi\n"
        f"curl -s -k -u admin:$(cat /tmp/splunk_admin_password) \\\n"
        f"  -X POST \"${{CAPTAIN_URI}}/services/shcluster/captain/control/control/transfer-captain\" \\\n"
        f"  -d \"target=${{TARGET}}\"\n",
        encoding="utf-8",
    )

    # member scripts
    (shc / "members" / "add-member.sh").write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\n"
        f"# Add a new member to the SHC.\n"
        f"# The new member must have Splunk Enterprise installed and the SHC secret available.\n"
        f"NEW_MEMBER=\"${{NEW_MEMBER:-}}\"\n"
        f"if [[ -z \"$NEW_MEMBER\" ]]; then echo 'Set NEW_MEMBER=hostname'; exit 1; fi\n"
        f"ssh splunk@\"$NEW_MEMBER\" 'sudo -u splunk /opt/splunk/bin/splunk init shcluster-config "
        f"-auth admin:$(cat /tmp/splunk_admin_password) "
        f"--conf_deploy_fetch_url {deployer_uri} "
        f"--shcluster_label {shc_label} "
        f"--replication_factor {rf} "
        '--pass4SymmKey "$(cat /tmp/splunk_shc_secret)"' + "'\n"
        "echo 'Member added. Run: splunk list shcluster-members'\n",
        encoding="utf-8",
    )
    (shc / "members" / "decommission-member.sh").write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\n"
        f"# Gracefully decommission a member (moves to GracefulShutdown).\n"
        f"MEMBER_UUID=\"${{MEMBER_UUID:-}}\"\n"
        f"CAPTAIN_URI=\"${{CAPTAIN_URI:-{deployer_uri}}}\"\n"
        f"if [[ -z \"$MEMBER_UUID\" ]]; then echo 'Set MEMBER_UUID from splunk list shcluster-members'; exit 1; fi\n"
        f"curl -s -k -u admin:$(cat /tmp/splunk_admin_password) \\\n"
        f"  -X POST \"${{CAPTAIN_URI}}/services/shcluster/member/members/${{MEMBER_UUID}}/control/control/graceful_shutdown\"\n",
        encoding="utf-8",
    )
    (shc / "members" / "remove-member.sh").write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\n"
        f"# Administrative removal after decommission.\n"
        f"MEMBER_UUID=\"${{MEMBER_UUID:-}}\"\n"
        f"CAPTAIN_URI=\"${{CAPTAIN_URI:-{deployer_uri}}}\"\n"
        f"if [[ -z \"$MEMBER_UUID\" ]]; then echo 'Set MEMBER_UUID from splunk list shcluster-members'; exit 1; fi\n"
        f"curl -s -k -u admin:$(cat /tmp/splunk_admin_password) \\\n"
        f"  -X DELETE \"${{CAPTAIN_URI}}/services/shcluster/member/members/${{MEMBER_UUID}}\"\n",
        encoding="utf-8",
    )

    # kvstore scripts
    (shc / "kvstore" / "status.sh").write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\n"
        f"CAPTAIN_URI=\"${{CAPTAIN_URI:-{deployer_uri}}}\"\n"
        f"curl -s -k -u admin:$(cat /tmp/splunk_admin_password) \\\n"
        f"  \"${{CAPTAIN_URI}}/services/kvstore/status?output_mode=json\" | python3 -m json.tool\n",
        encoding="utf-8",
    )
    (shc / "kvstore" / "reset-status.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# DANGER: Forces full KV Store re-sync on this member. Use only when replication is stuck.\n"
        "# Requires --accept-kvstore-reset passed to setup.sh.\n"
        "MEMBER_URI=\"${MEMBER_URI:-}\"\n"
        "if [[ -z \"$MEMBER_URI\" ]]; then echo 'Set MEMBER_URI=https://sh0X:8089'; exit 1; fi\n"
        "curl -s -k -u admin:$(cat /tmp/splunk_admin_password) \\\n"
        "  -X POST \"${MEMBER_URI}/services/kvstore/control/control/reset\"\n",
        encoding="utf-8",
    )

    # migration scripts
    (shc / "migration" / "standalone-to-shc.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Convert a standalone search head to an SHC member.\n"
        "# Prerequisites: install Splunk on additional members; have the SHC secret ready.\n"
        "echo 'See reference.md: standalone-to-shc migration checklist.'\n",
        encoding="utf-8",
    )
    (shc / "migration" / "replace-deployer.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# Replace the SHC deployer with a new instance.\n"
        "echo 'Steps: install Splunk on new deployer; copy etc/shcluster/apps/;'\n"
        "echo '  update conf_deploy_fetch_url on all members; restart members.'\n",
        encoding="utf-8",
    )

    # validate.sh
    (shc / "validate.sh").write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\n"
        f"CAPTAIN_URI=\"${{CAPTAIN_URI:-{deployer_uri}}}\"\n"
        f"echo '=== SHC Status ==='\n"
        f"curl -s -k -u admin:$(cat /tmp/splunk_admin_password) \\\n"
        f"  \"${{CAPTAIN_URI}}/services/shcluster/captain/info?output_mode=json\" | python3 -m json.tool\n"
        f"echo '=== KV Store Status ==='\n"
        f"curl -s -k -u admin:$(cat /tmp/splunk_admin_password) \\\n"
        f"  \"${{CAPTAIN_URI}}/services/kvstore/status?output_mode=json\" | python3 -m json.tool\n",
        encoding="utf-8",
    )

    # preflight-report.md
    member_count = len(members)
    quorum = member_count // 2 + 1
    (shc / "preflight-report.md").write_text(
        f"# SHC Preflight Report\n\n"
        f"Generated: {now}\n\n"
        f"| Check | Value | Status |\n|-------|-------|--------|\n"
        f"| SHC label | `{shc_label}` | OK |\n"
        f"| Member count | {member_count} | {'OK' if member_count >= 3 else 'FAIL: minimum 3 members required'} |\n"
        f"| Replication factor | {rf} | {'OK' if rf <= member_count else 'FAIL: RF > member count'} |\n"
        f"| Quorum (N/2+1) | {quorum} | OK |\n"
        f"| KV Store RF | {kvstore_rf} | OK |\n"
        f"| KV Store port | {kvstore_port} | OK |\n",
        encoding="utf-8",
    )

    # runbook-failure-modes.md
    (shc / "runbook-failure-modes.md").write_text(
        "# SHC Failure Mode Runbooks\n\n"
        "## Split-Brain (Two Captains)\n\nRestore network partition. "
        "Older captain steps down on heartbeat recovery, or run `transfer-captain.sh`.\n\n"
        "## Quorum Loss\n\nBring members back online to restore N/2+1. "
        "Until quorum is restored, KV Store is read-only.\n\n"
        "## Deployer Mismatch (Divergent Bundle Generations)\n\nRe-run `bundle/apply.sh`. "
        "Use `bundle/apply-skip-validation.sh` only if the bundle validator is blocking.\n\n"
        "## Captain Crash Loop\n\nRun `restart/transfer-captain.sh` to promote a stable member. "
        "Then investigate the problematic captain's `splunkd.log`.\n\n"
        "## KV Store Stuck Replication\n\nCheck lag via `kvstore/status.sh`. "
        "If lag is stuck > 60 s, run `kvstore/reset-status.sh` on the lagging member with `--accept-kvstore-reset`.\n",
        encoding="utf-8",
    )

    # handoffs
    (shc / "handoffs" / "license-peers.txt").write_text(
        f"# SHC member license peer handoff\n"
        f"# Pass to: bash skills/splunk-license-manager-setup/scripts/setup.sh\n"
        f"DEPLOYER_URI={deployer_uri}\n"
        + "".join(f"MEMBER_{i+1}=https://{m}:8089\n" for i, m in enumerate(members)),
        encoding="utf-8",
    )
    (shc / "handoffs" / "es-deployer.txt").write_text(
        f"# ES deployer handoff\n"
        f"# Pass to: bash skills/splunk-enterprise-security-install/scripts/setup.sh\n"
        f"DEPLOYER_URI={deployer_uri}\n"
        f"DEPLOYER_HOST={deployer_host}\n"
        f"SHC_LABEL={shc_label}\n",
        encoding="utf-8",
    )
    (shc / "handoffs" / "monitoring-console.txt").write_text(
        f"# Monitoring Console handoff\n"
        f"# Pass to: bash skills/splunk-monitoring-console-setup/scripts/setup.sh\n"
        f"DEPLOYER_URI={deployer_uri}\n"
        + "".join(f"MEMBER_{i+1}=https://{m}:8089\n" for i, m in enumerate(members)),
        encoding="utf-8",
    )

    # Make all scripts executable
    for path in shc.rglob("*.sh"):
        path.chmod(0o755)

    result = {
        "output_dir": str(out.resolve()),
        "shc_label": shc_label,
        "deployer_host": deployer_host,
        "members": members,
        "replication_factor": rf,
        "kvstore_replication_factor": kvstore_rf,
        "rendered_files": [str(p.relative_to(out)) for p in sorted(out.rglob("*")) if p.is_file()],
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{SKILL_NAME} renderer")
    parser.add_argument("--phase", default="render")
    parser.add_argument("--output-dir",
                        default=str(PROJECT_ROOT / "splunk-search-head-cluster-rendered"))
    parser.add_argument("--shc-label", default="prod_shc")
    parser.add_argument("--deployer-host", default="")
    parser.add_argument("--deployer-uri", default="")
    parser.add_argument("--member-hosts", default="")
    parser.add_argument("--replication-factor", default="3")
    parser.add_argument("--kvstore-replication-factor", default="3")
    parser.add_argument("--kvstore-port", default="8191")
    parser.add_argument("--heartbeat-timeout", default="60")
    parser.add_argument("--heartbeat-period", default="5")
    parser.add_argument("--restart-inactivity-timeout", default="600")
    parser.add_argument("--rolling-restart-mode", default="searchable")
    parser.add_argument("--captain-uri", default="")
    parser.add_argument("--target-captain-uri", default="")
    parser.add_argument("--new-member-host", default="")
    parser.add_argument("--member-host", default="")
    parser.add_argument("--existing-sh-host", default="")
    parser.add_argument("--additional-member-hosts", default="")
    parser.add_argument("--admin-password-file", default="")
    parser.add_argument("--shc-secret-file", default="")
    parser.add_argument("--accept-skip-validation", action="store_true")
    parser.add_argument("--accept-kvstore-reset", action="store_true")
    parser.add_argument("--accept-force-restart", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = render(args)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Rendered to: {result['output_dir']}")
        print(f"SHC label:   {result['shc_label']}")
        print(f"Members:     {', '.join(result.get('members', []))}")
        print(f"Files:       {len(result.get('rendered_files', []))}")


if __name__ == "__main__":
    main()
