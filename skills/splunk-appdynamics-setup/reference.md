# Splunk AppDynamics Suite Reference

The parent skill owns coverage and routing. Child skills own rendered assets and
validation for their feature families.

| Family | Owner |
| --- | --- |
| Release notes, references, product announcements, and alerts | `splunk-appdynamics-setup` |
| Platform / On-Premises / planning / quickstart / Virtual Appliance | `splunk-appdynamics-platform-setup` |
| Events Service / EUM Server / Synthetic Server deployment | `splunk-appdynamics-platform-setup` |
| Controller admin / API clients / licensing / sensitive data controls | `splunk-appdynamics-controller-admin-setup` |
| Smart Agent / Agent Management / package download validation | `splunk-appdynamics-agent-management-setup` |
| APM model / app-server snippets / serverless / OpenTelemetry | `splunk-appdynamics-apm-setup` |
| Cluster Agent and Kubernetes auto-instrumentation | `splunk-appdynamics-k8s-cluster-agent-setup` |
| Infrastructure Visibility / GPU Monitoring / Prometheus extension | `splunk-appdynamics-infrastructure-visibility-setup` |
| Database Visibility | `splunk-appdynamics-database-visibility-setup` |
| Analytics and Events API | `splunk-appdynamics-analytics-setup` |
| EUM / Browser RUM / Mobile RUM / IoT RUM | `splunk-appdynamics-eum-setup` |
| Synthetic Monitoring and Private Synthetic Agents | `splunk-appdynamics-synthetic-monitoring-setup` |
| Log Observer Connect | `splunk-appdynamics-log-observer-connect-setup` |
| Alerting content / AIML baselines and diagnostics | `splunk-appdynamics-alerting-content-setup` |
| Dashboards, reports, and War Rooms | `splunk-appdynamics-dashboards-reports-setup` |
| ThousandEyes token, Dash Studio widgets, EUM metrics, TE native integration, and TE API assets | `splunk-appdynamics-thousandeyes-integration-setup` |
| Tags, extensions, and integration modules | `splunk-appdynamics-tags-extensions-setup` |
| Application Security Monitoring, Secure Application, and Observability for AI | `splunk-appdynamics-security-ai-setup` |
| SAP Agent and SAP release notes | `splunk-appdynamics-sap-agent-setup` |
| Splunk Platform TA | `cisco-appdynamics-setup` |

## Documentation Version Pinning

Cited `help.splunk.com` paths carry the version the owning manual actually
publishes, which is not one number across the suite:

- `26.8.0` for every SaaS and On-Premises manual (agent management, controller
  deployment, enterprise console, extend, get started, APM, analytics,
  application security, EUM, infrastructure visibility, licensing,
  observability for AI, tag management, unified observability).
- `26.1.0` for `appdynamics-on-premises/virtual-appliance-self-hosted`, which
  runs on its own release cadence.
- No version segment for manuals the vendor publishes unversioned, including the
  Controller release notes. The Controller release notes have no `26.8.0`
  edition: the unversioned path resolves to `26.4.0`, which is why the
  `*-26-4-release-runbook` artifacts keep that label.

Do not normalize these to a single number. A version substituted into a path
that the vendor does not publish either 404s or silently resolves to the wrong
page. Confirm the manual's current version by requesting its root and reading
where the redirect lands.

## AppDynamics API TLS For Lab Controllers

Rendered AppDynamics Controller, platform, and Smart Agent probe scripts verify
TLS by default. For self-signed lab controllers, set `APPD_CA_CERT` to a
trusted PEM bundle. As a lab-only escape hatch, set `APPD_VERIFY_SSL=false` to
pass `curl -k` through the rendered `appd_curl` wrapper. `APPD_CA_CERT` takes
precedence when both variables are set.

Run `python3 skills/splunk-appdynamics-setup/scripts/check_coverage.py` before
changing ownership or status values.
