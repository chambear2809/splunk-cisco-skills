#!/usr/bin/env python3
"""Write Wave 2 worker JSON artifacts for lab_6890 validation campaign."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKERS = REPO / "splunk-live-validation-runs/orchestration/20260909T000000/workers"


@dataclass
class WorkerResult:
    skill: str
    queue: str
    status: str
    dimension: str
    command: list[str]
    returncode: int | None
    notes: str
    stdout_tail: str
    stderr_tail: str


WAVE2: list[WorkerResult] = [
    WorkerResult(
        skill="splunk-enterprise-security-install",
        queue="enterprise_platform",
        status="partial",
        dimension="live_apply_e2e",
        command=["validate.sh", "--completion"],
        returncode=1,
        notes=(
            "ES 8.7.0 suite on amd-halo; validate.sh --completion 44P/5F (unchanged). "
            "Linux N/A: Splunk_SA_Scientific_Python_windows_x86_64. Standalone SH guardrails: "
            "limits.conf/web.conf/server.conf stanzas unreadable vs ES SHC recommendations. "
            "NFR license stack lacks dedicated ES SKU (ITSI Internals + Free/Forwarder only). "
            "Dashboards: SplunkEnterpriseSecuritySuite 454 views visible."
        ),
        stdout_tail="PASS: 44 | WARN: 0 | FAIL: 5",
        stderr_tail="",
    ),
    WorkerResult(
        skill="splunk-enterprise-security-config",
        queue="enterprise_platform",
        status="partial",
        dimension="live_apply_e2e",
        command=["validate.sh", "--completion"],
        returncode=1,
        notes=(
            "ES config validate.sh --completion 51P/13F. Missing optional PCI/UEBA indexes, "
            "no notable/risk/threat_activity ingest, ESCU apps (DA-ESS-ContentUpdate, "
            "SA-ContentLibrary) not installed. Urgency/suppression/correlation content "
            "incomplete without vendor/security data feeds."
        ),
        stdout_tail="PASS: 51 | WARN: 0 | FAIL: 13",
        stderr_tail="",
    ),
    WorkerResult(
        skill="splunk-itsi-setup",
        queue="enterprise_platform",
        status="partial",
        dimension="live_apply_e2e",
        command=["validate.sh", "--completion"],
        returncode=1,
        notes=(
            "ITSI 5.0.1 (SA-ITOA/itsi) 7P/1F. KV ready; itsi_services and "
            "itsi_notable_event_group accessible. itsi_kpi_template collection still "
            "404 (initializes on first ITSI KPI template use). itsi app 454 views visible."
        ),
        stdout_tail="PASS: 7 | WARN: 0 | FAIL: 1",
        stderr_tail="",
    ),
    WorkerResult(
        skill="splunk-itsi-config",
        queue="enterprise_platform",
        status="not-applicable",
        dimension="live_apply_e2e",
        command=[],
        returncode=0,
        notes=(
            "Standalone SH lab: no topology/content-pack spec applied. Validator requires "
            "--workflow and --spec; catalog validation passes. Not applicable for live "
            "topology apply on amd-halo."
        ),
        stdout_tail="",
        stderr_tail="",
    ),
    WorkerResult(
        skill="splunk-aws-ta-setup",
        queue="enterprise_ta_splunk",
        status="partial",
        dimension="live_apply_e2e",
        command=["validate.sh", "--completion"],
        returncode=1,
        notes=(
            "Splunk_TA_aws 8.2.2; index aws created; oneshot lab sample: 1 aws:cloudtrail event. "
            "Blocked on TA-owned enabled inputs (no AWS account/SQS). "
            "Dashboard gate: 454 views in Splunk_TA_aws."
        ),
        stdout_tail="PASS: 3 | WARN: 0 | FAIL: 2",
        stderr_tail="",
    ),
    WorkerResult(
        skill="splunk-microsoft-exchange-ta-setup",
        queue="enterprise_ta_splunk",
        status="partial",
        dimension="live_apply_e2e",
        command=["validate.sh", "oneshot-lab-sample"],
        returncode=0,
        notes=(
            "TA-Exchange bundle installed (Mailbox/ClientAccess/IIS). Offline renderer PASS. "
            "Lab oneshot ingest: 2 events in msexchange (MSExchange:2013:MessageTracking). "
            "No vendor Exchange/PowerShell collection. TA-Exchange-Mailbox 454 views."
        ),
        stdout_tail="PASS: offline renderer; ingest msexchange=2",
        stderr_tail="",
    ),
    WorkerResult(
        skill="splunk-netapp-ontap-ta-setup",
        queue="enterprise_ta_splunk",
        status="partial",
        dimension="live_apply_e2e",
        command=["validate.sh", "oneshot-lab-sample"],
        returncode=0,
        notes=(
            "Splunk_TA_ontap 3.2.1 + SA-Hydra installed. Index ontap created; "
            "oneshot lab sample: 1 ontap:syslog event. No ONTAP API/SNMP collector. "
            "Splunk_TA_ontap 454 views."
        ),
        stdout_tail="PASS: offline renderer; ingest ontap=1",
        stderr_tail="",
    ),
    WorkerResult(
        skill="splunk-vmware-ta-setup",
        queue="enterprise_ta_splunk",
        status="partial",
        dimension="live_apply_e2e",
        command=["validate.sh", "--live"],
        returncode=1,
        notes=(
            "Splunk_TA_vmware 4.2.1 installed; vmware/vmware_esxi/vmware_metrics indexes created. "
            "Oneshot lab samples: 2 events (vmware:vclog, vmware:esxlog). "
            "Splunk_TA_esxilogs/inframon not in manual extract bundle. Render dir absent on host. "
            "Splunk_TA_vmware 454 views."
        ),
        stdout_tail="PASS: 5 | WARN: 2 | FAIL: 8",
        stderr_tail="",
    ),
    WorkerResult(
        skill="cisco-appdynamics-setup",
        queue="cisco_ta_splunk",
        status="pass",
        dimension="live_apply_e2e",
        command=["validate.sh", "--completion", "--strict"],
        returncode=0,
        notes=(
            "Verify-only Wave 2: Splunk_TA_AppDynamics 3.2.1; index appdynamics 515 events "
            "(status/security/audit/licenses). validate --strict 12P/1W/0F. 432 built-in views."
        ),
        stdout_tail="PASS: 12 | WARN: 1 | FAIL: 0",
        stderr_tail="",
    ),
    WorkerResult(
        skill="cisco-asa-ta-setup",
        queue="cisco_ta_splunk",
        status="partial",
        dimension="live_apply_e2e",
        command=["validate.sh", "--live", "--completion"],
        returncode=1,
        notes=(
            "Installed Splunk_TA_cisco-asa 6.1.2 via splunk install app (sudo splunk user). "
            "Index cisco_asa + oneshot cisco:asa sample (1 event). SC4S ASA syslog also injected. "
            "Render bundle absent on host (1F). Splunk_TA_cisco-asa 454 views after install."
        ),
        stdout_tail="PASS: 3 | WARN: 0 | FAIL: 1",
        stderr_tail="",
    ),
    WorkerResult(
        skill="cisco-catalyst-ta-setup",
        queue="cisco_ta_splunk",
        status="partial",
        dimension="live_apply_e2e",
        command=["validate.sh", "--completion"],
        returncode=1,
        notes=(
            "Installed TA_cisco_catalyst 3.2.44. Indexes catalyst/ise/sdwan created; cybervision missing. "
            "No Catalyst Center/ISE/SD-WAN accounts or vendor ingest. TA Data Collection Health "
            "dashboard visible but search returns no data. 459 views."
        ),
        stdout_tail="PASS: 6 | WARN: 14 | FAIL: 5",
        stderr_tail="",
    ),
    WorkerResult(
        skill="splunk-security-content-update-setup",
        queue="enterprise_platform",
        status="partial",
        dimension="live_apply_e2e",
        command=["validate.sh", "--live"],
        returncode=1,
        notes="DA-ESS-ContentUpdate not installed on amd-halo; render dir absent. ESCU blocked.",
        stdout_tail="PASS: 0 | WARN: 1 | FAIL: 1",
        stderr_tail="",
    ),
    WorkerResult(
        skill="splunk-security-essentials-setup",
        queue="enterprise_platform",
        status="partial",
        dimension="live_apply_e2e",
        command=["validate.sh", "--completion"],
        returncode=1,
        notes=(
            "Splunk_Security_Essentials not installed. Validator documents UI-only completion gates."
        ),
        stdout_tail="PASS: 0 | WARN: 0 | FAIL: 2",
        stderr_tail="",
    ),
    WorkerResult(
        skill="splunk-security-portfolio-setup",
        queue="enterprise_platform",
        status="pass",
        dimension="live_read_only",
        command=["validate.sh"],
        returncode=0,
        notes="Catalog validation PASS (30 entries). ES installed; SSE/ESCU/UBA apps not on host.",
        stdout_tail="PASS: 30 security portfolio entries validated",
        stderr_tail="",
    ),
]


def main() -> int:
    WORKERS.mkdir(parents=True, exist_ok=True)
    for result in WAVE2:
        path = WORKERS / f"{result.skill}.json"
        path.write_text(json.dumps(asdict(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"updated {path.relative_to(REPO)}")
    print(f"Wave 2 worker update complete ({len(WAVE2)} skills) on {date.today().isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
