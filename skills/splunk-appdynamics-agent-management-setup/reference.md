# Agent Management Reference

Primary 26.4 sources reviewed:

- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/before-you-begin
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/quick-start
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/get-started/install-smart-agent
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/get-started/configure-smart-agent
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/get-started/validate-smart-agent-installation
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/get-started/synchronize-smart-agent-primary-host-with-the-remote-hosts
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/upgrade-smart-agent
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/auto-attach-java-and-nodejs-agents
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/auto-discovery-of-application-process
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/auto-deploy-agents-with-deployment-groups
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-ui
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-ui/install-agents
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-ui/upgrade-agents
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-ui/rollback-agents
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-database-agent-using-ui
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-database-agent-using-ui/install-database-agent
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-database-agent-using-ui/rollback-database-agent
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/configuration-options-for-supported-agents
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl/install-supported-agents-using-smartagentctl/supported-agent-types
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl/install-supported-agents-using-smartagentctl/supported-platforms-to-install-supported-agents-using-smartagentctl
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl/install-supported-agents-using-smartagentctl/install-supported-agent-on-a-smart-agent-host
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl/install-supported-agents-using-smartagentctl/requirements-to-install-supported-agent-on-a-remote-host
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl/install-supported-agents-using-smartagentctl/install-supported-agents-on-remote-hosts
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl/install-supported-agents-using-smartagentctl/ssh-configuration-for-remote-host
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl/upgrade-supported-agents-using-smartagentctl
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl/uninstall-supported-agents-using-smartagentctl
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl/roll-back-supported-agents-using-smartagentctl
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/smart-agent-command-line-utility
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/smart-agent-command-line-utility/automate-smart-agent-installation-on-multiple-nodes
- https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/smart-agent-command-line-utility/configure-auto-attach
- https://help.splunk.com/en/appdynamics-on-premises/get-started/26.4.0/getting-started/download-appdynamics-software
- https://help.splunk.com/en/appdynamics-saas/get-started/26.4.0/downloads/download-options
- https://help.splunk.com/en/appdynamics-saas/get-started/26.4.0/downloads/filter-and-search-options
- https://help.splunk.com/en/appdynamics-on-premises/accounts/download-splunk-appdynamics-software
- https://help.splunk.com/en/appdynamics-on-premises/extend-appdynamics/26.4.0/extend-splunk-appdynamics/splunk-appdynamics-apis/agent-installer-platform-service-api

Current managed surface:

- Apache Web Server
- .NET
- Database
- Java
- Machine
- Node.js
- PHP
- Python

`smartagentctl` agent type values currently documented for direct
`smartagentctl` lifecycle operations are:

- `.NET`: `dotnet_msi`
- Database: `db`
- Java: `java`
- Machine: `machine`
- Node.js: `node`

The broader Smart Agent and Agent Management UI support matrix also lists
Apache Web Server, PHP, and Python. Treat those as UI/deployment-group runbook
coverage unless a current `smartagentctl` page documents a direct CLI agent type.

Consumption model:

- `agent-management-decision-guide.md`: smallest decision tree for users.
- `smart-agent-readiness.yaml`: prereq, platform, support matrix, permissions,
  and resource checks.
- `smart-agent-config.ini.template`: redacted config template with proxy, TLS,
  telemetry, polling/scanning, storage, and auto-discovery knobs.
- `remote.yaml.template`: Linux SSH and Windows WinRM examples using file or
  environment-backed credentials only.
- `agent-management-ui-runbook.md`: UI install, upgrade, rollback, Database
  Agent, CSV import, custom HTTP/local directory, and rollback constraints.
- `smartagentctl-lifecycle-plan.sh`: local and remote lifecycle command plan.
- `deployment-groups-runbook.md`: create/edit/duplicate/delete/view flow and
  large-scale rollout guardrails.
- `auto-attach-and-discovery-runbook.md`: Java/Node.js auto-attach and process
  discovery handling.
- `smart-agent-cli-deprecation-runbook.md`: legacy CLI compatibility only.

Remote install, upgrade, and rollback commands are rendered to
`smart-agent-remote-command-plan.sh` and require explicit acceptance before any
automation path may execute them. Package download automation, checksums,
digital signatures, and rollback package posture are rendered for operator review.
