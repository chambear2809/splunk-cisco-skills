---
name: splunk-appdynamics-agent-management-setup
description: >-
  Render, validate, and gate Splunk AppDynamics Smart Agent and Agent Management
  workflows, including prerequisites, platform and permission checks, Smart
  Agent config, local and remote install, upgrade, uninstall, synchronization,
  deployment groups, auto-attach, auto-discovery, UI paths, smartagentctl
  lifecycle commands, deprecated Smart Agent CLI guidance, and supported managed
  agent types for Apache, .NET MSI, Database, Java, Machine, Node.js, PHP, and
  Python agents, plus software downloads, checksum validation, digital
  signatures, and release posture. Use when the user asks for AppDynamics Smart
  Agent, Agent Management, remote agent installation, deployment groups,
  managed agent upgrade, rollback, auto-attach, auto-discovery, managed Apache,
  .NET, Database, Java, Machine, Node.js, PHP, or Python agents, package
  download automation, checksum validation, signature validation, or release
  compatibility.
---

# Splunk AppDynamics Agent Management Setup

Owns the Smart Agent and Agent Management lifecycle. The safe path is render
first: it creates reviewed plans, templates, and runbooks without touching
hosts. Remote host execution is gated by `--accept-remote-execution`; render
mode only writes reviewed commands.

```bash
bash skills/splunk-appdynamics-agent-management-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-agent-management-setup/scripts/validate.sh
```

## What This Skill Covers

- Smart Agent readiness: Controller version, licenses, permissions, supported
  platforms, memory, disk, service user/group, and service-vs-process decision.
- Smart Agent setup: `config.ini`, file-backed access-key handling, proxy/TLS
  settings, environment overrides, local install, remote install, validate,
  upgrade, uninstall, and primary-host to remote-host synchronization.
- Agent Management UI: inventory, Smart Agents tab, app-server and Machine
  Agent install/upgrade/rollback, Database Agent install/upgrade/rollback, CSV
  host import, custom package locations, local directory, and custom HTTP source
  review.
- `smartagentctl`: local and remote install, upgrade, uninstall, rollback,
  `remote.yaml`, Linux SSH, Windows WinRM, SSH password environment variables,
  HTTP/SOCKS5 SSH proxies, local-directory downloads, and source-specific flags.
- Large-scale operations: deployment groups, per-host assignment, Java and
  Node.js auto-attach, application process auto-discovery, and generated
  `ld_preload.json` planning.
- Deprecated standalone Smart Agent CLI: retained only as a compatibility
  runbook because the 26.4 docs mark it deprecated with a documented end of
  support date of February 2, 2026.
- Software supply chain: download portal/cURL plan, binary transfer warning,
  checksums, PGP or code-signing validation where published, release-note link,
  package inventory, and rollback package confirmation.

## Consume It

Start with `smart-agent-readiness.yaml` and `agent-management-decision-guide.md`.
They keep the intake small: deployment mode, host OS, target agents, local vs
remote, UI vs `smartagentctl`, package source, and whether deployment groups or
auto-attach are in scope.

Only after that should an operator review `smart-agent-remote-command-plan.sh`,
`smartagentctl-lifecycle-plan.sh`, `remote.yaml.template`, and the UI runbooks.
No generated file contains secret values.
