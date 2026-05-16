# Coverage

This child owns AppDynamics platform rows in the parent taxonomy:

- `appd_onprem_controller`
- `appd_onprem_overview`
- `appd_onprem_release_notes_references`
- `appd_onprem_deployment_planning`
- `appd_platform_installation_quickstart`
- `appd_virtual_appliance`
- `appd_enterprise_console`
- `appd_events_service_deployment`
- `appd_eum_server_deployment`
- `appd_synthetic_server_deployment`
- `appd_platform_ha`
- `appd_platform_upgrade`
- `appd_platform_security`

Run `bash skills/splunk-appdynamics-platform-setup/scripts/setup.sh --render`
to generate `coverage-report.json` with current status and apply boundaries.

The 26.4-backed rows include On-Premises overview and release references,
deployment planning, platform quickstart, Controller CLI install, Enterprise
Console command line, HA prerequisites, and HA Controller upgrade. Component
deployment rows track the current Events Service, EUM Server, and Synthetic
Server landing pages where the docs do not expose 26.4 URL pathing.

Deployment-method coverage is broader than the taxonomy row count:

- Classic On-Premises software: Enterprise Console Express GUI, Custom GUI,
  CLI, Discover/Upgrade GUI, Discover/Upgrade CLI, and AWS Aurora Controller
  upgrade/move.
- Component installers: Linux Events Service GUI/CLI, Windows Events Service
  manual deployment, EUM Server GUI/console/silent installer modes, and
  Synthetic Server dependency sequencing.
- Virtual Appliance infrastructure: VMware vSphere OVA, VMware ESXi OVA,
  Microsoft Azure VHD, AWS AMI, KVM QCOW2, and ROSA/OpenShift Virtualization
  QCOW2.
- Virtual Appliance services: Standard and Hybrid `appdcli` deployment paths.
- VMware OVA handoff: redacted vSphere/ESXi inventory, OVF Tool dry-run import
  commands, govc import-option workflow, password-file handling, pod CIDR
  overlap warnings, and live govc/SSH validation hooks.

The renderer emits `deployment-method-selector.yaml` and
`deployment-method-matrix.md` so users can start with a small set of decisions
instead of needing to know the underlying AppDynamics deployment taxonomy.
