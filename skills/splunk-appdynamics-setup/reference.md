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
| Dashboards, reports, War Rooms, and ThousandEyes dashboards | `splunk-appdynamics-dashboards-reports-setup` |
| Tags, extensions, and integration modules | `splunk-appdynamics-tags-extensions-setup` |
| Application Security Monitoring, Secure Application, and Observability for AI | `splunk-appdynamics-security-ai-setup` |
| SAP Agent and SAP release notes | `splunk-appdynamics-sap-agent-setup` |
| Splunk Platform TA | `cisco-appdynamics-setup` |

## AppDynamics API TLS For Lab Controllers

Rendered AppDynamics Controller, platform, and Smart Agent probe scripts verify
TLS by default. For self-signed lab controllers, set `APPD_CA_CERT` to a
trusted PEM bundle. As a lab-only escape hatch, set `APPD_VERIFY_SSL=false` to
pass `curl -k` through the rendered `appd_curl` wrapper. `APPD_CA_CERT` takes
precedence when both variables are set.

Run `python3 skills/splunk-appdynamics-setup/scripts/check_coverage.py` before
changing ownership or status values.
