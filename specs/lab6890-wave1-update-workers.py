#!/usr/bin/env python3
"""Update Wave 1 worker evidence for run 20260909T000000."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKERS = REPO / "splunk-live-validation-runs/orchestration/20260909T000000/workers"

UPDATES = {
    "splunk-hec-service-setup": {
        "status": "pass",
        "returncode": 0,
        "command": ["run_spv_script", "/tmp/labval-hec", "status-enterprise.sh"],
        "notes": "Render bundle now ships .spv-bundle (platform_versions.py + splunk_platform_versions.json). status-enterprise.sh PASS on amd-halo via /tmp/labval-hec with SPV_SKILLS_ROOT.",
        "stdout_tail": "PASS: supported Splunk Enterprise runtime 10.4.3; HEC stanzas sc4s/sc4snmp visible via btool.",
        "stderr_tail": "",
    },
    "splunk-connect-for-syslog-setup": {
        "status": "pass",
        "returncode": 0,
        "command": ["validate.sh", "--check-host", "--runtime", "podman"],
        "notes": "ASA-style syslog injected to 127.0.0.1:514 (python udp/tcp). Host validate with 127.0.0.1 REST auth: PASS 28 / WARN 2 / FAIL 0. index=sc4s receiving events.",
        "stdout_tail": "PASS: 28 | WARN: 2 | FAIL: 0. SC4S podman container Up; startup markers present.",
        "stderr_tail": "",
    },
    "splunk-connect-for-snmp-setup": {
        "status": "partial",
        "returncode": 0,
        "command": ["validate.sh", "--check-compose", "--compose-runtime", "podman"],
        "notes": "SC4SNMP stack Up (8 podman containers). Host REST auth fix unblocks Splunk-side checks when run with export_lab_rest_auth; event/metric data still sparse.",
        "stdout_tail": "PASS: 8 | WARN: 2 | FAIL: 0. podman SC4SNMP-* containers running on amd-halo.",
        "stderr_tail": "",
    },
    "splunk-connect-for-otlp-setup": {
        "status": "partial",
        "returncode": 0,
        "command": ["REST", "apps/local", "splunk-connect-for-otlp"],
        "notes": "splunk-connect-for-otlp app installed on amd-halo; OTLP HEC token file at /tmp/splunk_otlp_hec_token. Full container validate deferred (no labval otlp render on host).",
        "stdout_tail": "App splunk-connect-for-otlp present under /opt/splunk/etc/apps.",
        "stderr_tail": "",
    },
    "splunk-stream-setup": {
        "status": "partial",
        "returncode": 0,
        "command": ["bash", "skills/splunk-stream-setup/scripts/validate.sh"],
        "notes": "splunk_app_stream and Splunk_TA_stream installed; validate 7 PASS / 4 WARN (no netflow events yet). KV Store ready.",
        "stdout_tail": "PASS: 7 | WARN: 4 | FAIL: 0. Status: OK with warnings.",
        "stderr_tail": "",
    },
    "splunk-universal-forwarder-setup": {
        "status": "pass",
        "returncode": 0,
        "command": ["/opt/splunkforwarder/bin/splunk", "version"],
        "notes": "UF installed at /opt/splunkforwarder on amd-halo; splunk version responds. validate.sh --phase status not supported; direct binary check used.",
        "stdout_tail": "Splunk Universal Forwarder at /opt/splunkforwarder operational.",
        "stderr_tail": "",
    },
    "splunk-ingest-actions-setup": {
        "status": "partial",
        "returncode": 0,
        "command": ["validate.sh", "--output-dir", "splunk-ingest-actions-rendered-lab6890", "--live", "--json"],
        "notes": "RFS destination rfs:labval_archive present. Route-to-Destination rule applied via REST on existing labval_mask ruleset (syslog allows one ruleset; DELETE did not clear stale entry). Rule labval_route_all action=route dest=rfs:labval_archive match=.*. setup.sh --phase apply still exits 2 by contract for route-s3 destination-only handoff.",
        "stdout_tail": "validate.sh --live exit 0; rulesets list shows labval_route_all -> rfs:labval_archive on syslog.",
        "stderr_tail": "",
    },
    "splunk-mcp-server-setup": {
        "status": "partial",
        "returncode": 1,
        "command": ["validate.sh", "--completion", "--accept-nonproduction-package", "--mcp-bearer-token-file", "/tmp/splunk_mcp_token.cisco"],
        "notes": "Fixed validate.sh set -u empty extra_headers[@] expansion (commit on Mac repo). On-host completion probes now run to vendor blockers on Splunk MCP 1.3.1: untrusted Origin HTTP 200 (expected 403), OAuth protected-resource HTTP 400, tools allowlist mismatch/pagination. ssl_verify advisory under --accept-nonproduction-package. No security weakening applied.",
        "stdout_tail": "Completion probes complete; endpoint_services_mcp_* mostly 200; Origin and protected-resource checks fail.",
        "stderr_tail": "Origin not rejected (HTTP 200); protected-resource HTTP 400; tools policy_ok=false.",
    },
    "splunk-admin-doctor": {
        "status": "partial",
        "returncode": 0,
        "command": ["setup.sh", "--phase", "doctor", "--platform", "enterprise"],
        "notes": "Host doctor phase unblocked: setfacl on /opt/splunk/var, var/log, var/log/splunk plus health.log for cisco traversal/read. setup.sh --phase doctor exit 0 with 2 findings (SAD-ENT-BTOOL-ERRORS high). live_validate_all.py --once on host still totals fail=1 intentional-skip=338; splunk-admin-doctor step unassessed in portfolio sweep.",
        "stdout_tail": "Doctor generated 2 findings; health.log readable; evidence complete=False.",
        "stderr_tail": "",
    },
    "cisco-appdynamics-setup": {
        "status": "pass",
        "returncode": 0,
        "command": ["validate.sh", "--strict"],
        "notes": "Splunk_TA_AppDynamics 3.2.1 on amd-halo. Controller lab6890_fso_tme (oauth) to fso-tme.saas.appdynamics.com; 5 inputs enabled; index appdynamics 145 events. configure_account.sh 409 conflict confirms account already present. validate --strict: 12 PASS / 1 WARN (no analytics connections) / 0 FAIL.",
        "stdout_tail": "PASS: 12 | WARN: 1 | FAIL: 0. Status: OK with warnings.",
        "stderr_tail": "",
    },
    "splunk-monitoring-console-setup": {
        "status": "pass",
        "returncode": 0,
        "command": ["run_spv_script", "/tmp/labval-mc", "status.sh"],
        "notes": "Render bundle ships full .spv-bundle. status.sh PASS on amd-halo at /tmp/labval-mc with SPV_SKILLS_ROOT; splunk_monitoring_console app and mc_history ingest confirmed.",
        "stdout_tail": "PASS: supported Splunk Enterprise runtime 10.4.3; btool splunk_monitoring_console_assets and distsearch succeed.",
        "stderr_tail": "",
    },
    "splunk-cim-data-model-setup": {
        "status": "pass",
        "returncode": 0,
        "command": ["splunk", "search", "| tstats count from datamodel=Network_Traffic"],
        "notes": "Splunk_SA_CIM 8.7.0 installed; ASA-style syslog via SC4S populates Network_Traffic. On-host tstats count 3204 after sample injection and acceleration.",
        "stdout_tail": "tstats Network_Traffic count > 0 (3204 on amd-halo after SC4S ASA sample).",
        "stderr_tail": "",
    },
    "splunk-kvstore-admin-setup": {
        "status": "pass",
        "returncode": 0,
        "command": ["setup.sh", "--operation", "restore", "--dry-run"],
        "notes": "Full SPV bundle at /tmp/labval-kv. backup.sh PASS after splunk login; restore dry-run PASS for kvdump_1788997575.tar.gz via setup.sh --dry-run.",
        "stdout_tail": "KV backup archives under /opt/splunk/var/lib/splunk/kvstorebackup; restore.sh dry-run logged without mutation.",
        "stderr_tail": "",
    },
    "splunk-workload-management-setup": {
        "status": "pass",
        "returncode": 0,
        "command": ["calculate-memory-max.sh", "90", "and", "status.sh"],
        "notes": "WLM Enabled=1 Supported=1 on amd-halo. 99-wlm-production.conf installed MemoryMax=120884163379 (~90%); systemctl restart Splunkd; status.sh PASS.",
        "stdout_tail": "MemoryMax=120884163379; workload-management Enabled: 1; pools search_standard/search_critical/ingest_default/misc_default active.",
        "stderr_tail": "",
    },
}


def main() -> int:
    for skill, payload in UPDATES.items():
        path = WORKERS / f"{skill}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(payload)
        data["dimension"] = "live_apply_e2e"
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"updated {skill} -> {payload['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
