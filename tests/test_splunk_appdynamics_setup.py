from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

APPD_SKILLS = [
    "splunk-appdynamics-setup",
    "splunk-appdynamics-platform-setup",
    "splunk-appdynamics-controller-admin-setup",
    "splunk-appdynamics-agent-management-setup",
    "splunk-appdynamics-apm-setup",
    "splunk-appdynamics-k8s-cluster-agent-setup",
    "splunk-appdynamics-infrastructure-visibility-setup",
    "splunk-appdynamics-database-visibility-setup",
    "splunk-appdynamics-analytics-setup",
    "splunk-appdynamics-eum-setup",
    "splunk-appdynamics-synthetic-monitoring-setup",
    "splunk-appdynamics-log-observer-connect-setup",
    "splunk-appdynamics-alerting-content-setup",
    "splunk-appdynamics-dashboards-reports-setup",
    "splunk-appdynamics-tags-extensions-setup",
    "splunk-appdynamics-security-ai-setup",
    "splunk-appdynamics-sap-agent-setup",
]

ALLOWED_STATUSES = {
    "api_apply",
    "cli_apply",
    "k8s_apply",
    "delegated_apply",
    "render_runbook",
    "validate_only",
    "not_applicable",
}


def run_script(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def render_skill(skill: str, output_dir: Path) -> Path:
    result = run_script(
        SKILLS_DIR / skill / "scripts/setup.sh",
        "--render",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return output_dir


def test_required_public_interface_files_exist() -> None:
    required = [
        "SKILL.md",
        "template.example",
        "reference.md",
        "references/coverage.md",
        "scripts/setup.sh",
        "scripts/validate.sh",
        "agents/openai.yaml",
    ]
    for skill in APPD_SKILLS:
        for rel in required:
            assert (SKILLS_DIR / skill / rel).is_file(), f"{skill}/{rel}"


def test_taxonomy_completeness_and_status_validity(tmp_path: Path) -> None:
    check = subprocess.run(
        ["python3", "skills/splunk-appdynamics-setup/scripts/check_coverage.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert check.returncode == 0, check.stderr + check.stdout

    rendered = render_skill("splunk-appdynamics-setup", tmp_path / "parent")
    report = json.loads((rendered / "coverage-report.json").read_text(encoding="utf-8"))
    assert report["coverage_rows"] >= 80
    for row in report["features"]:
        assert row["owner"]
        assert row["source_url"].startswith("https://help.splunk.com/")
        assert row["status"] in ALLOWED_STATUSES
        assert row["validation_method"]
        assert row["apply_boundary"]


def test_direct_secret_flags_are_rejected() -> None:
    result = run_script(
        SKILLS_DIR / "splunk-appdynamics-analytics-setup/scripts/setup.sh",
        "--render",
        "--token",
        "literal-token",
    )
    assert result.returncode == 2
    assert "Refusing direct-secret" in result.stderr


def test_appd_tls_helper_env_contract(tmp_path: Path) -> None:
    ca_file = tmp_path / "lab-ca.pem"
    ca_file.write_text("test-ca\n", encoding="utf-8")
    helper = shlex.quote(str(SKILLS_DIR / "shared/lib/appdynamics_helpers.sh"))
    ca_path = shlex.quote(str(ca_file))
    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                f"source {helper}; "
                "APPD_VERIFY_SSL=false; appd_prepare_curl_tls_args; "
                "printf '<%s>\\n' \"${APPD_CURL_TLS_ARGS[@]}\"; "
                f"APPD_CA_CERT={ca_path}; APPD_VERIFY_SSL=false; appd_prepare_curl_tls_args; "
                "printf '<%s>\\n' \"${APPD_CURL_TLS_ARGS[@]}\""
            ),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "<-k>" in result.stdout
    assert "<--cacert>" in result.stdout
    assert f"<{ca_file}>" in result.stdout
    assert "APPD_VERIFY_SSL=false" in result.stderr


def test_rendered_appd_probe_scripts_support_lab_tls(tmp_path: Path) -> None:
    platform = render_skill("splunk-appdynamics-platform-setup", tmp_path / "platform-tls")
    platform_probe = (platform / "platform-validation-probes.sh").read_text(encoding="utf-8")
    assert "APPD_CA_CERT" in platform_probe
    assert "APPD_VERIFY_SSL" in platform_probe
    assert "appd_curl --fail --silent --show-error --max-time 10" in platform_probe
    assert '\ncurl --fail --silent --show-error --max-time 10 "${CONTROLLER_URL}/"' not in platform_probe

    controller = render_skill("splunk-appdynamics-controller-admin-setup", tmp_path / "controller-tls")
    controller_plan = (controller / "controller-admin-api-plan.sh").read_text(encoding="utf-8")
    assert "APPD_CA_CERT" in controller_plan
    assert "APPD_VERIFY_SSL" in controller_plan
    assert "appd_curl --fail --silent --show-error -H" in controller_plan

    agent = render_skill("splunk-appdynamics-agent-management-setup", tmp_path / "agent-tls")
    agent_probe = (agent / "smart-agent-validation-probes.sh").read_text(encoding="utf-8")
    assert "APPD_CA_CERT" in agent_probe
    assert "APPD_VERIFY_SSL" in agent_probe
    assert "appd_curl --fail --silent --show-error --max-time 10" in agent_probe


def test_cli_help_for_all_appdynamics_skills() -> None:
    for skill in APPD_SKILLS:
        setup = run_script(SKILLS_DIR / skill / "scripts/setup.sh", "--help")
        assert setup.returncode == 0, skill
        assert "--render" in setup.stdout
        validate = run_script(SKILLS_DIR / skill / "scripts/validate.sh", "--help")
        assert validate.returncode == 0, skill
        assert "--output-dir" in validate.stdout


def test_render_smoke_and_validate_for_all_appdynamics_skills(tmp_path: Path) -> None:
    for skill in APPD_SKILLS:
        out = render_skill(skill, tmp_path / skill)
        assert (out / "coverage-report.json").is_file()
        assert (out / "01-overview.md").is_file()
        validate = run_script(
            SKILLS_DIR / skill / "scripts/validate.sh",
            "--output-dir",
            str(out),
        )
        assert validate.returncode == 0, validate.stderr + validate.stdout


def test_specific_artifacts_render_for_all_appdynamics_children(tmp_path: Path) -> None:
    expected = {
        "splunk-appdynamics-controller-admin-setup": [
            "api-client-oauth-payload.redacted.json",
            "controller-admin-api-plan.sh",
            "rbac-access-plan.json",
            "saml-ldap-runbook.md",
            "sensitive-data-controls-runbook.md",
            "licensing-validation-plan.sh",
        ],
        "splunk-appdynamics-agent-management-setup": [
            "agent-management-decision-guide.md",
            "smart-agent-readiness.yaml",
            "smart-agent-config.ini.template",
            "smart-agent-inventory.yaml",
            "remote.yaml.template",
            "smart-agent-remote-command-plan.sh",
            "smartagentctl-lifecycle-plan.sh",
            "agent-management-ui-runbook.md",
            "deployment-groups-runbook.md",
            "auto-attach-and-discovery-runbook.md",
            "smart-agent-cli-deprecation-runbook.md",
            "appdynamics-download-verification-runbook.md",
            "smart-agent-validation-probes.sh",
        ],
        "splunk-appdynamics-apm-setup": [
            "apm-application-model.json",
            "apm-controller-api-plan.sh",
            "app-server-agent-snippets.md",
            "serverless-development-monitoring-runbook.md",
            "opentelemetry-apm-runbook.md",
            "apm-validation-probes.sh",
        ],
        "splunk-appdynamics-infrastructure-visibility-setup": [
            "machine-agent-command-plan.sh",
            "infrastructure-health-rules.json",
            "server-tags-payload.json",
            "network-visibility-runbook.md",
            "gpu-monitoring-runbook.md",
            "prometheus-extension-runbook.md",
            "infrastructure-validation-probes.sh",
        ],
        "splunk-appdynamics-alerting-content-setup": [
            "alerting-content-payloads.json",
            "alerting-export-rollback-plan.sh",
            "anomaly-detection-rca-runbook.md",
            "aiml-baseline-diagnostics-runbook.md",
            "alerting-validation-probes.sh",
        ],
        "splunk-appdynamics-dashboards-reports-setup": [
            "dashboard-payloads.json",
            "dashboard-report-runbook.md",
            "dashboard-validation-probes.sh",
            "thousandeyes-dashboard-integration-runbook.md",
            "war-room-runbook.md",
        ],
        "splunk-appdynamics-tags-extensions-setup": [
            "custom-tags-payload.json",
            "extensions-runbook.md",
            "custom-metrics-example.sh",
            "integrations-handoff.md",
        ],
        "splunk-appdynamics-security-ai-setup": [
            "security-ai-readiness.yaml",
            "secure-application-validation.sh",
            "secure-application-policy-runbook.md",
            "otel-secure-application-snippet.md",
            "observability-ai-handoffs.md",
        ],
        "splunk-appdynamics-analytics-setup": [
            "analytics-events-headers.redacted.json",
            "analytics-publish-plan.sh",
            "analytics-schema-plan.json",
            "business-journeys-xlm-runbook.md",
            "analytics-adql-validation.sh",
        ],
    }
    for skill, filenames in expected.items():
        out = render_skill(skill, tmp_path / skill)
        for filename in filenames:
            assert (out / filename).is_file(), f"{skill}/{filename}"


def test_platform_onprem_26_4_artifacts_render_and_gate(tmp_path: Path) -> None:
    out = render_skill("splunk-appdynamics-platform-setup", tmp_path / "platform")
    expected = [
        "platform-topology-inventory.yaml",
        "deployment-method-selector.yaml",
        "deployment-method-matrix.md",
        "enterprise-console-hosts.txt",
        "enterprise-console-command-plan.sh",
        "classic-onprem-deployment-runbook.md",
        "controller-install-upgrade-runbook.md",
        "component-deployment-runbook.md",
        "virtual-appliance-deployment-runbook.md",
        "platform-ha-backup-runbook.md",
        "platform-security-checklist.md",
        "platform-validation-probes.sh",
    ]
    for name in expected:
        assert (out / name).is_file(), name

    topology = (out / "platform-topology-inventory.yaml").read_text(encoding="utf-8")
    assert "doc_version: 26.4.0" in topology
    assert "controller-1.example.com" in topology
    assert "events-1.example.com" in topology

    command_plan = (out / "enterprise-console-command-plan.sh").read_text(encoding="utf-8")
    assert "show-platform-admin-version" in command_plan
    assert "create-platform" in command_plan
    assert "add-credential" in command_plan
    assert "add-hosts --host-file" in command_plan
    assert "list-job-parameters --service controller --job install" in command_plan
    assert "controllerAdminPassword=" not in command_plan
    assert "mysqlRootPassword=" not in command_plan

    runbook = (out / "controller-install-upgrade-runbook.md").read_text(encoding="utf-8")
    assert "AppDynamics On-Premises 26.4.0" in runbook
    assert "Back up the Controller" in runbook

    component = (out / "component-deployment-runbook.md").read_text(encoding="utf-8")
    assert "Events Service" in component
    assert "EUM Server" in component
    assert "Synthetic Server" in component

    selector = (out / "deployment-method-selector.yaml").read_text(encoding="utf-8")
    assert "recommended_methods:" in selector
    assert "- classic_cli_custom" in selector
    assert "id: va_aws_ami" in selector
    assert "id: va_rosa_qcow2" in selector
    assert "id: eum_installer_gui_console_silent" in selector

    deployment_matrix = (out / "deployment-method-matrix.md").read_text(encoding="utf-8")
    assert "classic_gui_express" in deployment_matrix
    assert "va_services_hybrid" in deployment_matrix

    va_runbook = (out / "virtual-appliance-deployment-runbook.md").read_text(encoding="utf-8")
    assert "VMware vSphere" in va_runbook
    assert "ROSA" in va_runbook

    live_validate = run_script(
        SKILLS_DIR / "splunk-appdynamics-platform-setup/scripts/validate.sh",
        "--output-dir",
        str(out),
        "--live",
    )
    assert live_validate.returncode == 0, live_validate.stderr + live_validate.stdout
    assert "APPD_PLATFORM_LIVE=1" in live_validate.stdout

    apply = run_script(
        SKILLS_DIR / "splunk-appdynamics-platform-setup/scripts/setup.sh",
        "--apply",
        "--output-dir",
        str(tmp_path / "apply-denied"),
    )
    assert apply.returncode == 2
    assert "--accept-enterprise-console-mutation" in apply.stderr

    accepted = run_script(
        SKILLS_DIR / "splunk-appdynamics-platform-setup/scripts/setup.sh",
        "--apply",
        "--accept-enterprise-console-mutation",
        "--output-dir",
        str(tmp_path / "apply-accepted"),
    )
    assert accepted.returncode == 0, accepted.stderr + accepted.stdout
    accepted_plan = (tmp_path / "apply-accepted" / "apply-plan.sh").read_text(encoding="utf-8")
    assert "enterprise-console-command-plan.sh" in accepted_plan


def test_platform_virtual_appliance_route_selects_infra_and_service_paths(tmp_path: Path) -> None:
    spec = tmp_path / "va.yaml"
    spec.write_text(
        """
deployment_model: virtual_appliance
deployment:
  model: virtual_appliance
virtual_appliance:
  infrastructure_platform: aws
  service_deployment: hybrid
  profile: medium
  node_count: 3
platform:
  name: va-platform
  controller_profile: medium
enterprise_console:
  host: ec.example.com
controller:
  primary_host: controller.example.com
events_service:
  enabled: false
eum_server:
  enabled: false
synthetic_server:
  enabled: false
""",
        encoding="utf-8",
    )
    out = tmp_path / "va-rendered"
    result = run_script(
        SKILLS_DIR / "splunk-appdynamics-platform-setup/scripts/setup.sh",
        "--render",
        "--spec",
        str(spec),
        "--output-dir",
        str(out),
    )
    assert result.returncode == 0, result.stderr + result.stdout

    selector = (out / "deployment-method-selector.yaml").read_text(encoding="utf-8")
    assert "deployment_model: virtual_appliance" in selector
    assert "- va_aws_ami" in selector
    assert "- va_services_hybrid" in selector

    runbook = (out / "virtual-appliance-deployment-runbook.md").read_text(encoding="utf-8")
    assert "Infrastructure platform: `aws`" in runbook
    assert "`va_aws_ami`" in runbook
    assert "`va_services_hybrid`" in runbook


def test_database_collector_payload_redacts_password(tmp_path: Path) -> None:
    out = render_skill("splunk-appdynamics-database-visibility-setup", tmp_path / "db")
    payload = json.loads((out / "database-collector-payloads.redacted.json").read_text(encoding="utf-8"))
    collector = payload["collectors"][0]
    assert collector["password"] == "<redacted:file-backed>"
    assert collector["password_file"] == "/secure/appd/db_password"


def test_analytics_events_headers_are_redacted(tmp_path: Path) -> None:
    out = render_skill("splunk-appdynamics-analytics-setup", tmp_path / "analytics")
    headers = json.loads((out / "analytics-events-headers.redacted.json").read_text(encoding="utf-8"))
    assert headers["X-Events-API-Key"] == "<redacted:events_api_key_file>"
    assert headers["Content-Type"].startswith("application/vnd.appd.events+json")
    xlm = (out / "business-journeys-xlm-runbook.md").read_text(encoding="utf-8")
    assert "Experience Level Management" in xlm
    assert "Business Journey" in xlm


def test_apm_and_alerting_deep_coverage_artifacts_render(tmp_path: Path) -> None:
    apm = render_skill("splunk-appdynamics-apm-setup", tmp_path / "apm")
    serverless = (apm / "serverless-development-monitoring-runbook.md").read_text(encoding="utf-8")
    assert "Serverless APM" in serverless
    assert "Development Level Monitoring" in serverless
    otel = (apm / "opentelemetry-apm-runbook.md").read_text(encoding="utf-8")
    assert "OpenTelemetry" in otel
    assert "access key" in otel

    alerting = render_skill("splunk-appdynamics-alerting-content-setup", tmp_path / "alerting")
    anomaly = (alerting / "anomaly-detection-rca-runbook.md").read_text(encoding="utf-8")
    assert "Anomaly Detection" in anomaly
    assert "Root Cause Analysis" in anomaly
    aiml = (alerting / "aiml-baseline-diagnostics-runbook.md").read_text(encoding="utf-8")
    assert "Dynamic Baseline" in aiml
    assert "Automated Transaction Diagnostics" in aiml
    payload = json.loads((alerting / "alerting-content-payloads.json").read_text(encoding="utf-8"))
    assert "email_digests" in payload
    assert "anomaly_detection" in payload


def test_current_26_4_gap_artifacts_render(tmp_path: Path) -> None:
    controller = render_skill("splunk-appdynamics-controller-admin-setup", tmp_path / "controller")
    sensitive = (controller / "sensitive-data-controls-runbook.md").read_text(encoding="utf-8")
    assert "Sensitive Data" in sensitive
    assert "Log Analytics masking" in sensitive

    agent = render_skill("splunk-appdynamics-agent-management-setup", tmp_path / "agent-download")
    download = (agent / "appdynamics-download-verification-runbook.md").read_text(encoding="utf-8")
    assert "checksum" in download
    assert "digital signatures" in download

    infra = render_skill("splunk-appdynamics-infrastructure-visibility-setup", tmp_path / "infra")
    gpu = (infra / "gpu-monitoring-runbook.md").read_text(encoding="utf-8")
    assert "GPU Monitoring" in gpu
    assert "DCGM" in gpu
    prometheus = (infra / "prometheus-extension-runbook.md").read_text(encoding="utf-8")
    assert "Prometheus" in prometheus

    dashboards = render_skill("splunk-appdynamics-dashboards-reports-setup", tmp_path / "dash")
    thousandeyes = (dashboards / "thousandeyes-dashboard-integration-runbook.md").read_text(encoding="utf-8")
    assert "ThousandEyes" in thousandeyes
    assert "Dash Studio" in thousandeyes

    security = render_skill("splunk-appdynamics-security-ai-setup", tmp_path / "security")
    policy = (security / "secure-application-policy-runbook.md").read_text(encoding="utf-8")
    assert "runtime policy" in policy
    assert "Secure Application APIs" in policy
    assert "policyConfigs" in policy

    eum = render_skill("splunk-appdynamics-eum-setup", tmp_path / "eum")
    mobile_replay = (eum / "mobile-session-replay-runbook.md").read_text(encoding="utf-8")
    assert "Mobile Session Replay" in mobile_replay
    assert "session.replay.enabled" in mobile_replay
    mobile_snippets = (eum / "mobile-sdk-snippets.md").read_text(encoding="utf-8")
    assert ".withSessionReplayEnabled(true)" in mobile_snippets

    analytics = render_skill("splunk-appdynamics-analytics-setup", tmp_path / "analytics")
    adql = (analytics / "analytics-adql-validation.sh").read_text(encoding="utf-8")
    assert "Connected Device Data" in adql

    sap = render_skill("splunk-appdynamics-sap-agent-setup", tmp_path / "sap")
    sap_runbook = (sap / "sap-agent-runbook.md").read_text(encoding="utf-8")
    assert "gateway/proxy" in sap_runbook
    assert "BiQ business-process data" in sap_runbook


def test_second_pass_official_doc_family_rows_render(tmp_path: Path) -> None:
    out = render_skill("splunk-appdynamics-setup", tmp_path / "parent-doc-families")
    report = json.loads((out / "coverage-report.json").read_text(encoding="utf-8"))
    ids = {row["id"] for row in report["features"]}
    expected = {
        "appd_saas_release_notes_references",
        "appd_product_announcements_alerts",
        "appd_onprem_overview",
        "appd_onprem_release_notes_references",
        "appd_onprem_deployment_planning",
        "appd_platform_installation_quickstart",
        "appd_events_service_deployment",
        "appd_eum_server_deployment",
        "appd_synthetic_server_deployment",
        "appd_sap_release_notes",
    }
    assert expected <= ids


def test_smart_agent_remote_command_rendering_and_gate(tmp_path: Path) -> None:
    out = render_skill("splunk-appdynamics-agent-management-setup", tmp_path / "agent")
    expected = [
        "agent-management-decision-guide.md",
        "smart-agent-readiness.yaml",
        "smart-agent-config.ini.template",
        "remote.yaml.template",
        "smartagentctl-lifecycle-plan.sh",
        "agent-management-ui-runbook.md",
        "deployment-groups-runbook.md",
        "auto-attach-and-discovery-runbook.md",
        "smart-agent-cli-deprecation-runbook.md",
    ]
    for name in expected:
        assert (out / name).is_file(), name

    readiness = (out / "smart-agent-readiness.yaml").read_text(encoding="utf-8")
    assert "Apache Web Server" in readiness
    assert "Python Agent" in readiness
    assert "minimum_version: 24.7.0" in readiness

    remote_yaml = (out / "remote.yaml.template").read_text(encoding="utf-8")
    assert "password_env_var: SSH_PASSWORD" in remote_yaml
    assert "type: winrm" in remote_yaml
    assert "socks5" in remote_yaml

    lifecycle = (out / "smartagentctl-lifecycle-plan.sh").read_text(encoding="utf-8")
    assert "dotnet_msi" in lifecycle
    assert "java" in lifecycle
    assert "rollback" in lifecycle

    ui = (out / "agent-management-ui-runbook.md").read_text(encoding="utf-8")
    assert "Database Agent high availability is not supported" in ui
    assert "UI at least once" in ui

    deprecation = (out / "smart-agent-cli-deprecation-runbook.md").read_text(encoding="utf-8")
    assert "February 2, 2026" in deprecation
    assert "does not support Database Agent" in deprecation

    plan = (out / "smart-agent-remote-command-plan.sh").read_text(encoding="utf-8")
    assert "--accept-remote-execution" in plan
    assert "smartagentctl start" in plan

    report = json.loads((out / "coverage-report.json").read_text(encoding="utf-8"))
    ids = {row["id"] for row in report["features"]}
    assert {
        "appd_smart_agent_readiness",
        "appd_agent_management_deployment_groups",
        "appd_agent_management_auto_attach",
        "appd_agent_management_auto_discovery",
        "appd_smartagentctl_remote_yaml_security",
        "appd_smart_agent_cli_deprecated",
        "appd_managed_apache_agent",
        "appd_managed_php_agent",
        "appd_managed_python_agent",
    } <= ids

    apply = run_script(SKILLS_DIR / "splunk-appdynamics-agent-management-setup/scripts/setup.sh", "--apply")
    assert apply.returncode == 2
    assert "--accept-remote-execution" in apply.stderr


def test_cluster_agent_values_rendering(tmp_path: Path) -> None:
    out = render_skill("splunk-appdynamics-k8s-cluster-agent-setup", tmp_path / "k8s")
    values = (out / "cluster-agent-values.yaml").read_text(encoding="utf-8")
    assert "installSplunkOtelCollector: true" in values
    assert "clusterAgent:" in values
    assert "splunkOtelCollector:" in values
    assert "splunk-otel-collector:" in values
    assert "${SPLUNK_O11Y_ACCESS_TOKEN}" in values
    assert "dotnet-core-linux" in values
    otel_values = (out / "splunk-otel-collector-values.yaml").read_text(encoding="utf-8")
    assert "splunkObservability:" in otel_values
    assert "secret:" in otel_values
    secret = (out / "splunk-otel-secret-template.yaml").read_text(encoding="utf-8")
    assert "splunk_observability_access_token" in secret
    patches = (out / "workload-instrumentation-patches.yaml").read_text(encoding="utf-8")
    assert "appdynamics.com/instrumentation" in patches
    assert "AGENT_DEPLOYMENT_MODE" in patches
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in patches
    dual_env = (out / "dual-signal-workload-env.yaml").read_text(encoding="utf-8")
    assert "AGENT_DEPLOYMENT_MODE" in dual_env
    assert "DOTNET_STARTUP_HOOKS" in dual_env
    rollout = (out / "cluster-agent-rollout-plan.sh").read_text(encoding="utf-8")
    assert "--set-file splunk-otel-collector.splunkObservability.accessToken" in rollout
    assert "K8S_APPLY=1" in rollout
    o11y = (out / "o11y-export-validation.sh").read_text(encoding="utf-8")
    assert "X-SF-Token" in o11y
    runbook = (out / "combined-agent-o11y-runbook.md").read_text(encoding="utf-8")
    assert "dual" in runbook
    assert "Splunk Observability Cloud" in runbook
    rbac = (out / "cluster-agent-rbac-review.md").read_text(encoding="utf-8")
    assert "26.4" in rbac
    report = json.loads((out / "coverage-report.json").read_text(encoding="utf-8"))
    ids = {row["id"] for row in report["features"]}
    assert {
        "appd_cluster_agent",
        "appd_k8s_auto_instrumentation",
        "appd_cluster_agent_otel_collector",
        "appd_k8s_combined_agent_dual_signal",
        "appd_k8s_splunk_o11y_export",
    } <= ids


def test_eum_synthetic_and_sap_artifacts_render(tmp_path: Path) -> None:
    eum = render_skill("splunk-appdynamics-eum-setup", tmp_path / "eum")
    snippet = (eum / "browser-rum-snippet.html").read_text(encoding="utf-8")
    assert "APPD_BROWSER_APP_KEY" in snippet
    assert "adrum-latest.js" in snippet
    replay = (eum / "session-replay-config.js").read_text(encoding="utf-8")
    assert "sessionReplay" in replay
    upload = (eum / "source-map-upload-plan.sh").read_text(encoding="utf-8")
    assert "APPD_EUM_TOKEN_FILE" in upload

    synthetic = render_skill("splunk-appdynamics-synthetic-monitoring-setup", tmp_path / "synthetic")
    values = (synthetic / "private-synthetic-agent-values.yaml").read_text(encoding="utf-8")
    assert "privateSyntheticAgent:" in values
    assert "shepherdUrl:" in values
    browser_jobs = json.loads((synthetic / "browser-synthetic-jobs.json").read_text(encoding="utf-8"))
    assert browser_jobs["jobs"][0]["name"] == "checkout-homepage"

    sap = render_skill("splunk-appdynamics-sap-agent-setup", tmp_path / "sap")
    runbook = (sap / "sap-agent-runbook.md").read_text(encoding="utf-8")
    assert "NetWeaver transport" in runbook
    assert "SAP authorizations" in runbook
    checklist = (sap / "sap-authorization-checklist.md").read_text(encoding="utf-8")
    assert "ABAP" in checklist
