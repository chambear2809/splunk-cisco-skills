---
name: splunk-appdynamics-platform-setup
description: >-
  Render, validate, and gate Splunk AppDynamics On-Premises and Virtual
  Appliance platform workflows, including Enterprise Console, Controller,
  Events Service, EUM Server, Synthetic Server, planning, platform quickstart,
  release notes, compatibility, HA, backup, restore, upgrades, and secure
  platform hardening. Use when the user asks for AppDynamics
  On-Premises, Virtual Appliance, Enterprise Console, Controller host setup,
  Events Service, EUM Server, Synthetic Server, HA, upgrade, or secure platform
  runbooks.
---

# Splunk AppDynamics Platform Setup

Render-first owner for AppDynamics self-managed platform workflows. Platform
mutations are high-blast-radius and require reviewed runbooks; Enterprise
Console changes are additionally gated by `--accept-enterprise-console-mutation`.
The skill tracks the current AppDynamics On-Premises 26.4 Enterprise Console
and Controller documentation for CLI-capable platform work.

```bash
bash skills/splunk-appdynamics-platform-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-platform-setup/scripts/validate.sh
```

The renderer emits:

- `platform-topology-inventory.yaml` with the reviewed component and host map.
- `deployment-method-selector.yaml` and `deployment-method-matrix.md` to route
  users across classic On-Premises, Virtual Appliance, GUI, CLI, and
  discover/upgrade paths without making them know the product taxonomy first.
- `enterprise-console-command-plan.sh` with session-safe Enterprise Console CLI
  commands for platform, credential, host, version, diagnosis, and job discovery.
- `classic-onprem-deployment-runbook.md`,
  `controller-install-upgrade-runbook.md`, `component-deployment-runbook.md`,
  `virtual-appliance-deployment-runbook.md`, `platform-ha-backup-runbook.md`,
  and `platform-security-checklist.md` for support-gated or outage-prone work.
- `platform-validation-probes.sh` for local static checks and optional live
  reachability probes.

First-class deployment coverage:

- Classic On-Premises Enterprise Console Express GUI, Custom GUI, CLI, and
  Discover/Upgrade GUI/CLI flows.
- Classic component installers for Linux Events Service, Windows Events Service
  manual deployment, EUM Server GUI/console/silent installer modes, and
  Synthetic Server dependency sequencing.
- Virtual Appliance infrastructure targets for VMware vSphere, VMware ESXi,
  Microsoft Azure, AWS, KVM, and ROSA.
- Virtual Appliance Standard and Hybrid service deployment with `appdcli`
  validation handoffs.
