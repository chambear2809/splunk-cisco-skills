---
name: splunk-stream-windows-setup
description: "Use when the user asks to investigate, install, upgrade, configure, validate, troubleshoot, or roll back Splunk Stream Forwarder on a Windows host. Provides action-capable local PowerShell, Windows OpenSSH, WinRM, and AWS Systems Manager paths; enforces a drift-bound investigation and plan before installing the Windows x64 Splunk_TA_stream payload and bundled Npcap driver."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  parent_skill: "splunk-stream-setup"
  splunk_stream_version: "8.1.6"
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Splunk Stream Windows Setup

This is the Windows capture-host child of `splunk-stream-setup`. The parent owns
the complete Stream topology, search/index-tier packages, indexes, stream
definitions, data searches, and dashboards. This child owns Windows discovery,
transport, Npcap, `Splunk_TA_stream`, host configuration, host evidence, and
transactional rollback.

Read the parent [Windows research](../splunk-stream-setup/references/windows.md)
before changing compatibility or transport policy. It records the official
sources and the reviewed 8.1.6 package evidence.

## When to Activate

Activate this child when Splunk Stream packet capture or the Stream Forwarder
must run on a Windows x64 capture host. Use the parent skill for the Stream
search tier, indexes, stream definitions, dashboards, and end-to-end data
checks; use the Universal Forwarder skill when the Windows runtime is absent.

## Prerequisites

- A supported x64 Windows Server host with elevated Administrator access.
- A reviewed `Splunk_TA_stream` 8.1.6 archive and Npcap approval.
- One supported transport: local PowerShell, pinned-host-key SSH, WinRM, or
  AWS Systems Manager with private temporary S3 staging.
- A reachable Stream app endpoint and the required Splunk topology details.
- Credentials kept in protected local files or an existing authenticated AWS
  session; never place secret values in plans, arguments, or chat.

## Workflow Overview

```text
┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
│ Investigate │ → │ Plan/review  │ → │ Apply exact  │ → │ Validate evidence │
└─────────────┘   └──────────────┘   └──────────────┘   └──────────────────┘
        ↑                                                    │
        └────────────── prerequisite or drift rerun ────────┘
```

1. Investigate the host and endpoint without mutation.
2. Resolve missing Universal Forwarder or network prerequisites, then
   investigate again.
3. Render and review a package-verified, inventory-bound plan.
4. Apply only the unchanged plan with explicit mutation confirmation.
5. Validate host health and complete the parent Stream data/dashboard gate.
6. Roll back only the reviewed transaction if the apply requires recovery.

## Non-negotiable safety and compatibility rules

- Never ask for or place a password, token, private key, or secret value in
  chat, command-line arguments, rendered output, a plan, or a transaction
  journal.
- Use key-based SSH, the caller's Kerberos/Negotiate identity, a chmod-600
  WinRM password file, or the caller's existing AWS CLI session.
- Require an x64 Windows Server capture host and an elevated execution identity.
- The Splunk service must run as LocalSystem or an account this workflow can
  verify as a direct local Administrator, matching Splunk Stream's Windows
  deployment requirements.
- Block Stream capture inside Splunk Enterprise 10.4 or newer on Windows. Its
  required least-privilege service change conflicts with Stream's documented
  Windows service-account requirement. Prefer a Windows x64 Universal Forwarder
  running as LocalSystem, with the full Enterprise search/index tier elsewhere.
- Do not install an Independent Stream Forwarder on Windows; that package is
  Linux-only.
- Use only the original reviewed archive in `splunk-ta/`. The controller checks
  its fixed SHA-256 and safely creates a PowerShell-compatible ZIP.
- Treat Npcap as a potentially shared driver. Default to
  `install-if-missing`; never remove it automatically during rollback.
- Never claim completion from package installation alone.

## Required parent/child routing

Run this child only for the Windows capture host. Delegate other roles as
follows:

| Need found by investigation | Required skill |
| --- | --- |
| No Windows Splunk runtime | `splunk-universal-forwarder-setup` with `--target-os windows --target-arch x64`; execute its reviewed MSI handoff, then investigate again |
| Search-tier Stream app, wire-data TA, indexes, streams, or end-to-end data/dashboard evidence | parent `splunk-stream-setup` |
| Deployment Server runtime missing or unhealthy | `splunk-deployment-server-setup` |
| Deployment apps/server classes for fleet rollout | `splunk-agent-management-setup` |
| Coordinated restart across distributed Splunk roles | `splunk-platform-restart-orchestrator` |

Do not make this child install a full Windows Splunk Enterprise instance as a
shortcut. If both Universal Forwarder and Enterprise are present, stop and
resolve the intended service and `SPLUNK_HOME` explicitly.

## Mandatory workflow

### 1. Investigate without mutation

Always run `investigate` before choosing or proposing the installation plan.
It inventories:

- Windows Server version, architecture, administrator context, machine model;
- Splunk runtime type, version, home, service state, startup mode, and account;
- current Stream TA version, process, and effective managed configuration;
- Npcap driver/version/watchdog state;
- active interfaces and addresses available for capture;
- OpenSSH, WinRM, and SSM Agent service state; and
- TCP/HTTP reachability from the host to the Stream app endpoint.

Examples:

```bash
# AWS Systems Manager (preferred on EC2 when the node is managed)
bash skills/splunk-stream-windows-setup/scripts/setup.sh investigate \
  --transport ssm --instance-id i-0123456789abcdef0 --region us-east-1 \
  --staging-s3-uri s3://reviewed-private-bucket/splunk-stream-staging \
  --stream-app-url https://splunk.example.com:8000/en-US/custom/splunk_app_stream \
  --output-dir rendered/splunk-stream-windows

# Windows OpenSSH. Pin the host key; accept-new is only for reviewed first contact.
bash skills/splunk-stream-windows-setup/scripts/setup.sh investigate \
  --transport ssh --host windows.example.com --ssh-user Administrator \
  --ssh-key-file /secure/path/windows_key \
  --known-hosts-file /secure/path/windows_known_hosts \
  --stream-app-url https://splunk.example.com:8000/en-US/custom/splunk_app_stream
```

For WinRM, use HTTPS or Kerberos/Negotiate. Never add a wildcard to
`TrustedHosts`. A password, when unavoidable, is read from a local chmod-600
file via `--winrm-password-file`; its value is never passed to the controller's
command line.

### 2. Resolve prerequisites and investigate again

If the inventory reports `runtime_type: absent`, invoke the Universal Forwarder
child. Render its Windows x64 MSI handoff with `--service-user LocalSystem`,
then the Stream child can execute that exact hash-bound handoff through the
already selected transport:

```bash
bash skills/splunk-stream-windows-setup/scripts/setup.sh bootstrap-uf \
  --inventory-file rendered/splunk-stream-windows/inventory.json \
  --uf-render-dir rendered/splunk-uf-windows/universal-forwarder \
  --uf-msi splunk-ta/splunkforwarder-<version>-windows-x64.msi \
  --transport ssm --instance-id i-0123456789abcdef0 --region us-east-1 \
  --staging-s3-uri s3://reviewed-private-bucket/splunk-stream-staging \
  --accept-forwarder-mutation
```

`bootstrap-uf` permits only metadata from `splunk-universal-forwarder-setup`
for Windows x64, LocalSystem, and an MSI whose SHA-256 still matches the child
render. It rechecks the missing-runtime inventory before mutation and writes a
fresh inventory afterward.

If the Stream app endpoint is unreachable, fix DNS/routing/firewall/TLS
or finish the parent search-tier deployment. If SSM is selected, require a
managed node, an instance role with `AmazonSSMManagedInstanceCore`, and a
private staging S3 prefix accessible to the authenticated operator.

Do not plan through unresolved blockers. Re-run investigation after every
prerequisite or service-identity change.

### 3. Generate and review a drift-bound plan

```bash
bash skills/splunk-stream-windows-setup/scripts/setup.sh plan \
  --inventory-file rendered/splunk-stream-windows/inventory.json \
  --transport ssm \
  --stream-app-url https://splunk.example.com:8000/en-US/custom/splunk_app_stream \
  --bind-ip auto --ssl-verify true \
  --output-dir rendered/splunk-stream-windows
```

Add `--netflow-ip 0.0.0.0 --netflow-port 9995 --netflow-decoder netflow`
only when this host is also the reviewed flow receiver. `plan` verifies the
vendor archive, builds a safe Windows ZIP, records blockers/warnings, and emits
`plan.json` with an inventory fingerprint and plan hash. A blocked plan exits 2.

Review the target identity, service account, transport, endpoint, bind address,
TLS policy, Npcap policy, package hashes, actions, and rollback transaction ID.

### 4. Apply the exact plan

Repeat the same transport selectors used for investigation. Apply re-runs the
inventory and refuses mutation on drift.

```bash
bash skills/splunk-stream-windows-setup/scripts/setup.sh apply \
  --plan-file rendered/splunk-stream-windows/plan.json \
  --transport ssm --instance-id i-0123456789abcdef0 --region us-east-1 \
  --staging-s3-uri s3://reviewed-private-bucket/splunk-stream-staging \
  --accept-stream-mutation
```

The Windows transaction verifies the staged ZIP, installs or preserves Npcap
according to policy, preserves existing `local/`, changes only the managed
stanzas, stops Splunk, replaces `Splunk_TA_stream`, restarts Splunk, and runs
host validation. Same-version/same-config healthy reruns are no-ops. Backups
and a private journal remain under
`%ProgramData%\SplunkStreamSetup\transactions\<transaction-id>`.

### 5. Validate host and product completion

```bash
bash skills/splunk-stream-windows-setup/scripts/setup.sh validate \
  --plan-file rendered/splunk-stream-windows/plan.json \
  --transport ssm --instance-id i-0123456789abcdef0 --region us-east-1 \
  --staging-s3-uri s3://reviewed-private-bucket/splunk-stream-staging

# Runs both Windows checks and the parent strict completion gate.
bash skills/splunk-stream-windows-setup/scripts/setup.sh validate \
  --plan-file rendered/splunk-stream-windows/plan.json \
  --transport ssm --instance-id i-0123456789abcdef0 --region us-east-1 \
  --staging-s3-uri s3://reviewed-private-bucket/splunk-stream-staging \
  --completion
```

Host success requires the Splunk service, allowed account, Npcap driver,
8.1.6 TA, `streamfwd` process, endpoint reachability, and effective configuration.
Completion additionally requires parent evidence for indexed `source=stream`
data, `_internal` Stream logs/stats, shipped dashboards, macros, and any enabled
NetFlow input. Keep status open until both layers pass.

### 6. Roll back only the reviewed transaction

```bash
bash skills/splunk-stream-windows-setup/scripts/setup.sh rollback \
  --plan-file rendered/splunk-stream-windows/plan.json \
  --transport ssm --instance-id i-0123456789abcdef0 --region us-east-1 \
  --staging-s3-uri s3://reviewed-private-bucket/splunk-stream-staging \
  --accept-stream-rollback
```

Rollback restores or removes only the transaction's prior TA state and restores
the prior Splunk service state. It retains the displaced app and Npcap for
recovery; inspect the journal if compensation is incomplete.

## Transport and fleet coverage

| Method | Action support | Guardrail |
| --- | --- | --- |
| Local elevated PowerShell | Investigate/apply/validate/rollback | Run on the Windows host |
| Windows OpenSSH + SCP/SFTP | Full lifecycle | Key auth, pinned host key, explicit `powershell.exe` invocation |
| WinRM / PowerShell Remoting | Full lifecycle | Kerberos/Negotiate or HTTPS; file-based password only |
| AWS Systems Manager Run Command | Full lifecycle | Managed node, reviewed region/instance, temporary presigned S3 staging; objects removed after each operation |
| Systems Manager Distributor | Fleet packaging option | Build from this exact payload and transaction contract; validate a canary before rollout |
| Splunk Deployment Server / Agent Management | Ongoing TA/config distribution | Install Npcap separately, then delegate deployment app/serverclass ownership to the named child skills |
| Manual/RDP handoff | Rendered fallback | Run the target PowerShell script elevated and retain JSON evidence |

For detailed compatibility decisions, SSH/WinRM/SSM setup, Npcap exit codes,
fleet design, dashboards, known issues, and citations, use the parent
[Windows research](../splunk-stream-setup/references/windows.md).

## Troubleshooting

| Failure | Response |
| --- | --- |
| Plan says runtime absent | Run the Windows UF prerequisite child, then reinvestigate |
| Enterprise 10.4+ service conflict | Use a separate LocalSystem UF capture host; do not override |
| Inventory drift | Reinvestigate and create a new plan; never reuse the old hash |
| Npcap exit 3010 | Record reboot required, reboot in the approved window, validate again |
| Npcap exit 350 | Reboot, reinvestigate, and retry with a new plan |
| SSH host-key mismatch | Stop and verify the host out-of-band; never disable checking |
| SSM node unavailable | Repair SSM/instance role/networking or choose an already configured SSH/WinRM path |
| NIC reconfiguration/Windows update | Reinvestigate interfaces, restart the Splunk service if approved, and prove capture resumed |
| No indexed data | Check endpoint reachability, stream enablement, outputs, receiver/listener, `_internal`, then parent data/dashboard validation |

## TA completion gate

Apply [the shared TA completion gate](../shared/ta_completion_gate.md). Evidence
must include configured and enabled ingestion, fresh data in the intended
indexes/source types, and the shipped Stream dashboards visible, macro-aligned,
and returning data. `Splunk_TA_stream_wire_data` ships no user-facing views;
record that package evidence explicitly while validating dashboards from
`splunk_app_stream`.

## Examples

Show the supported transports and execution modes before selecting a target:

```bash
bash skills/splunk-stream-windows-setup/scripts/setup.sh --help
```

The mandatory workflow above contains complete investigation, planning, apply,
validation, and rollback examples for AWS Systems Manager and Windows OpenSSH.
