from __future__ import annotations

import importlib.util
import json
import shlex
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
HOST_APPLY_HELPER = SKILLS_DIR / "splunk-appdynamics-setup/scripts/appdynamics_host_apply.py"

APPD_SKILLS = [
    "splunk-appdynamics-setup",
    "splunk-appdynamics-platform-setup",
    "splunk-appdynamics-controller-admin-setup",
    "splunk-appdynamics-agent-management-setup",
    "splunk-appdynamics-dual-agent-setup",
    "splunk-appdynamics-apm-setup",
    "splunk-appdynamics-k8s-cluster-agent-setup",
    "splunk-appdynamics-infrastructure-visibility-setup",
    "splunk-appdynamics-machine-agent-otel-collector-setup",
    "splunk-appdynamics-database-visibility-setup",
    "splunk-appdynamics-analytics-setup",
    "splunk-appdynamics-eum-setup",
    "splunk-appdynamics-synthetic-monitoring-setup",
    "splunk-appdynamics-log-observer-connect-setup",
    "splunk-appdynamics-alerting-content-setup",
    "splunk-appdynamics-dashboards-reports-setup",
    "splunk-appdynamics-thousandeyes-integration-setup",
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

ALLOWED_SOURCE_PREFIXES = (
    "https://help.splunk.com/",
    "https://docs.thousandeyes.com/",
    "https://developer.cisco.com/docs/thousandeyes/",
)


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


def write_local_dual_agent_spec(tmp_path: Path) -> Path:
    machine = tmp_path / "machine"
    collector_dir = machine / "otel-collector"
    systemd_dir = tmp_path / "systemd"
    secrets = tmp_path / "secrets"
    for path in (collector_dir, systemd_dir, secrets):
        path.mkdir(parents=True, exist_ok=True)
    (secrets / "o11y").write_text("splunk-secret-value", encoding="utf-8")
    (secrets / "appd").write_text("appd-secret-value", encoding="utf-8")
    (secrets / "o11y").chmod(0o600)
    (secrets / "appd").chmod(0o600)
    spec = tmp_path / "dual-agent.yaml"
    spec.write_text(
        f"""
restart_strategy: canary
environment: prod
targets:
  - name: local-test
    host: localhost
    execution: local
    os_family: linux
    runtime: systemd
    sudo: false
    service_name: checkout-api
    application_name: Checkout
    tier_name: api
    node_name: local-test
    startup_config_path: {systemd_dir / "appd-dual-agent.conf"}
    systemd_daemon_reload_command: "true"
    restart_command: "true"
    healthcheck_command: "true"
    machine_agent_home: {machine}
    install_type: zip
    collector_config_path: {collector_dir / "config.yaml"}
    collector_service_name: appdynamics-machine-agent
    collector_restart_command: "true"
    collector_credentials_ready_command: "true"
    collector_healthcheck_command: "true"
    receiver_bind: 127.0.0.1
    grpc_port: 4317
    http_port: 4318
destinations:
  splunk_o11y:
    realm: us1
    token_file: {secrets / "o11y"}
  appd_otel:
    endpoint: https://otel.example.saas.appdynamics.com
    api_key_file: {secrets / "appd"}
""",
        encoding="utf-8",
    )
    return spec


def load_host_apply_helper():
    spec = importlib.util.spec_from_file_location("appdynamics_host_apply_test", HOST_APPLY_HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
        assert row["source_url"].startswith(ALLOWED_SOURCE_PREFIXES)
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


def test_appd_host_apply_helper_atomic_write_rollback_and_ssh_command(tmp_path: Path) -> None:
    helper = load_host_apply_helper()
    target = {"name": "local", "execution": "local", "sudo": False}
    executor = helper.HostExecutor(target, tmp_path)
    backup_dir = tmp_path / "backups"
    config = tmp_path / "config.yaml"

    first = executor.atomic_write(str(config), "first\n", backup_dir=backup_dir, label="config")
    assert first["changed"] is True
    assert first["backup_path"] is None
    assert first["after_sha256"] == helper.sha256_file(config)

    noop = executor.atomic_write(str(config), "first\n", backup_dir=backup_dir, label="config")
    assert noop["changed"] is False
    assert noop["action"] == "noop"
    noop_restore = helper.restore_entry(noop, target, tmp_path)
    assert noop_restore is None
    assert config.read_text(encoding="utf-8") == "first\n"

    second = executor.atomic_write(str(config), "second\n", backup_dir=backup_dir, label="config")
    assert second["changed"] is True
    assert second["backup_path"]
    assert Path(second["backup_path"]).is_file()
    assert config.read_text(encoding="utf-8") == "second\n"

    restored = helper.restore_entry(second, target, tmp_path)
    assert restored.exit_code == 0
    assert config.read_text(encoding="utf-8") == "first\n"

    sudo_config = tmp_path / "sudo-owned.conf"
    sudo_config.write_text("sudo\n", encoding="utf-8")
    sudo_target = {"name": "sudo-local", "execution": "local", "sudo": True}
    sudo_executor = helper.HostExecutor(sudo_target, tmp_path)
    sudo_calls = []

    def fake_sudo_run(command, *, sudo=None, label=""):
        sudo_calls.append({"command": command, "sudo": sudo, "label": label})
        return helper.CommandResult(
            target="sudo-local",
            command=["fake-sudo-probe"],
            exit_code=0,
            stdout=f"{helper.sha256_file(sudo_config)}\n",
            stderr="",
            started_at=helper.utc_now(),
            finished_at=helper.utc_now(),
            label=label,
        )

    sudo_executor.run = fake_sudo_run
    sudo_noop = sudo_executor.atomic_write(str(sudo_config), "sudo\n", backup_dir=backup_dir, sudo=True, label="sudo config")
    assert sudo_noop["changed"] is False
    assert sudo_calls[0]["sudo"] is True
    assert "sha256sum" in sudo_calls[0]["command"]

    ssh_target = {
        "host": "app01.example.com",
        "execution": "ssh",
        "ssh_user": "appdynamics",
        "ssh_key_file": "/secure/id_rsa",
        "ssh_known_hosts_file": "/secure/known_hosts",
    }
    command = helper.build_ssh_command(ssh_target, "systemctl restart appdynamics-machine-agent", sudo=True)
    joined = " ".join(shlex.quote(part) for part in command)
    assert "ssh" in command[0]
    assert "-i /secure/id_rsa" in joined
    assert "UserKnownHostsFile=/secure/known_hosts" in joined
    assert "StrictHostKeyChecking=yes" in joined
    assert "appdynamics@app01.example.com" in command
    assert "sudo -n bash -lc" in joined


def test_appd_thousandeyes_apply_requires_gate() -> None:
    result = run_script(
        SKILLS_DIR / "splunk-appdynamics-thousandeyes-integration-setup/scripts/setup.sh",
        "--apply", "assets",
        "--spec",
        str(SKILLS_DIR / "splunk-appdynamics-thousandeyes-integration-setup/template.example"),
    )
    assert result.returncode == 2
    assert "--accept-appd-te-mutation" in result.stderr


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
    assert 'appd_curl --fail --silent --show-error --config "${CURL_CONFIG}"' in controller_plan
    assert '-H "Authorization: Bearer' not in controller_plan

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
            "license-usage-report.sh",
            "license-usage-report-readme.md",
            "controller-26-4-release-runbook.md",
            "licensing-storage-metrics-plan.sh",
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
            "agent-management-26-4-release-runbook.md",
            "agent-upgrade-api-plan.sh",
            "smart-agent-validation-probes.sh",
        ],
        "splunk-appdynamics-dual-agent-setup": [
            "dual-agent-targets.yaml",
            "java-dual-agent-env.sh",
            "java-systemd-dropin.conf",
            "java-container-env.env",
            "dual-agent-collector-first-runbook.md",
            "dual-agent-apply-plan.sh",
            "java-dual-agent-validation-probes.sh",
            "apply-contract.md",
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
        "splunk-appdynamics-machine-agent-otel-collector-setup": [
            "collector-targets.yaml",
            "collector-config.yaml",
            "collector-service-plan.sh",
            "collector-validation-probes.sh",
            "machine-agent-discovery.sh",
            "machine-agent-collector-runbook.md",
            "apply-contract.md",
        ],
        "splunk-appdynamics-alerting-content-setup": [
            "alerting-content-payloads.json",
            "alerting-export-rollback-plan.sh",
            "anomaly-detection-rca-runbook.md",
            "aiml-baseline-diagnostics-runbook.md",
            "alert-template-variables-runbook.md",
            "alerting-validation-probes.sh",
        ],
        "splunk-appdynamics-dashboards-reports-setup": [
            "dashboard-payloads.json",
            "dashboard-report-runbook.md",
            "dashboard-validation-probes.sh",
            "thousandeyes-dashboard-integration-runbook.md",
            "war-room-runbook.md",
            "dash-studio-26-4-runbook.md",
            "reports-26-4-runbook.md",
            "log-tail-deprecation-runbook.md",
        ],
        "splunk-appdynamics-thousandeyes-integration-setup": [
            "appd-te-readiness.yaml",
            "thousandeyes-token-runbook.md",
            "dash-studio-query-runbook.md",
            "eum-network-metrics-runbook.md",
            "te-assets-spec.yaml",
            "handoff-thousandeyes-assets.sh",
            "te-native-appd-integration-runbook.md",
            "te-appd-webhook-payloads/connector.json",
            "te-appd-webhook-payloads/operation.json",
            "te-alert-notification-fragments.json",
            "te-api-apply-plan.sh",
            "appd-events-api-probe.sh",
            "te-appd-admin-checklist.md",
            "metadata.json",
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
            "cisco-ai-pod-monitoring-runbook.md",
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
        "virtual-appliance-vmware-inventory.yaml",
        "virtual-appliance-ovftool-plan.sh",
        "virtual-appliance-govc-plan.sh",
        "virtual-appliance-vmware-validation.sh",
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
    assert "virtual-appliance-ovftool-plan.sh" in va_runbook

    vmware_inventory = (out / "virtual-appliance-vmware-inventory.yaml").read_text(encoding="utf-8")
    assert "vcenter_password_file: /secure/vmware/vcenter-password" in vmware_inventory
    assert "prod-platform-va-1" in vmware_inventory
    assert "10.0.10.11/24" in vmware_inventory

    ovftool_plan = (out / "virtual-appliance-ovftool-plan.sh").read_text(encoding="utf-8")
    assert "VMWARE_APPLY" in ovftool_plan
    assert "--probe" in ovftool_plan
    assert "VMWARE_PASSWORD_FILE" in ovftool_plan
    assert "GOVC_PASSWORD" not in ovftool_plan
    assert 'VMWARE_NETWORK="${VMWARE_NETWORK:-VM Network}"' in ovftool_plan
    assert ":-''" not in ovftool_plan

    govc_plan = (out / "virtual-appliance-govc-plan.sh").read_text(encoding="utf-8")
    assert "govc" in govc_plan
    assert "import.spec" in govc_plan
    assert "import.ova" in govc_plan
    assert "VMWARE_APPLY" in govc_plan
    assert ":-''" not in govc_plan

    vmware_validate = (out / "virtual-appliance-vmware-validation.sh").read_text(encoding="utf-8")
    assert "VMWARE_VALIDATE_LIVE" in vmware_validate
    assert "appdctl show boot" in vmware_validate

    live_validate = run_script(
        SKILLS_DIR / "splunk-appdynamics-platform-setup/scripts/validate.sh",
        "--output-dir",
        str(out),
        "--live",
    )
    assert live_validate.returncode != 0
    assert "FAIL: live validation platform failed" in live_validate.stderr

    apply = run_script(
        SKILLS_DIR / "splunk-appdynamics-platform-setup/scripts/setup.sh",
        "--apply", "enterprise_console",
        "--spec",
        str(SKILLS_DIR / "splunk-appdynamics-platform-setup/template.example"),
        "--output-dir",
        str(tmp_path / "apply-denied"),
    )
    assert apply.returncode == 2
    assert "--accept-enterprise-console-mutation" in apply.stderr


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


def test_platform_virtual_appliance_vmware_esxi_packet(tmp_path: Path) -> None:
    spec = tmp_path / "va-esxi.yaml"
    spec.write_text(
        """
deployment:
  model: virtual_appliance
virtual_appliance:
  infrastructure_platform: vmware_esxi
  service_deployment: standard
  image_file: /secure/appdynamics/appd-va.ova
  dns_domain: va.example.com
  subnet_prefix: "24"
  node_ips:
    - 10.0.20.11
    - 10.0.20.12
    - 10.0.20.13
  gateway_ip: 10.0.20.1
  dns_server_ip: 10.0.20.53
  vmware:
    esxi:
      esxi_host: esxi-1.example.com
      esxi_username_file: /secure/vmware/esxi-username
      esxi_password_file: /secure/vmware/esxi-password
      datastore: local-ds
      network: AppD-PortGroup
platform:
  name: appd-va
controller:
  primary_host: controller.example.com
""",
        encoding="utf-8",
    )
    out = tmp_path / "va-esxi-rendered"
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
    assert "- va_vmware_esxi_ova" in selector

    topology = (out / "platform-topology-inventory.yaml").read_text(encoding="utf-8")
    assert "deployment_model: virtual_appliance" in topology

    inventory = (out / "virtual-appliance-vmware-inventory.yaml").read_text(encoding="utf-8")
    assert "esxi_host: esxi-1.example.com" in inventory
    assert "esxi_password_file: /secure/vmware/esxi-password" in inventory
    assert "10.0.20.11/24" in inventory

    ovftool = (out / "virtual-appliance-ovftool-plan.sh").read_text(encoding="utf-8")
    assert "vi://%s@%s/" in ovftool
    assert "AppD-PortGroup" in ovftool

    runbook = (out / "virtual-appliance-deployment-runbook.md").read_text(encoding="utf-8")
    assert "sudo appdctl host init" in runbook


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
    variables = (alerting / "alert-template-variables-runbook.md").read_text(encoding="utf-8")
    assert "latestEvent.eventProperties.hostname" in variables
    assert "Core Web Vitals" in variables
    payload = json.loads((alerting / "alerting-content-payloads.json").read_text(encoding="utf-8"))
    assert "email_digests" in payload
    assert "anomaly_detection" in payload


def test_current_26_4_gap_artifacts_render(tmp_path: Path) -> None:
    controller = render_skill("splunk-appdynamics-controller-admin-setup", tmp_path / "controller")
    sensitive = (controller / "sensitive-data-controls-runbook.md").read_text(encoding="utf-8")
    assert "Sensitive Data" in sensitive
    assert "Log Analytics masking" in sensitive
    controller_release = (controller / "controller-26-4-release-runbook.md").read_text(encoding="utf-8")
    assert "Edit Applications Name" in controller_release
    assert "tag-based RBAC" in controller_release
    storage_metrics = (controller / "licensing-storage-metrics-plan.sh").read_text(encoding="utf-8")
    assert "Usage(Bytes)" in storage_metrics
    license_report = (controller / "license-usage-report.sh").read_text(encoding="utf-8")
    assert "APPD_ACCOUNT_ID" in license_report
    assert "APPD_OAUTH_CLIENT_SECRET_FILE" in license_report
    assert "--deep" in license_report
    license_readme = (controller / "license-usage-report-readme.md").read_text(encoding="utf-8")
    assert "license-usage-report.md" in license_readme

    agent = render_skill("splunk-appdynamics-agent-management-setup", tmp_path / "agent-download")
    download = (agent / "appdynamics-download-verification-runbook.md").read_text(encoding="utf-8")
    assert "checksum" in download
    assert "digital signatures" in download
    agent_release = (agent / "agent-management-26-4-release-runbook.md").read_text(encoding="utf-8")
    assert "Agent Upgrade API" in agent_release
    assert "Python 3.14" in agent_release
    upgrade_api = (agent / "agent-upgrade-api-plan.sh").read_text(encoding="utf-8")
    assert "APPD_OAUTH_TOKEN_FILE" in upgrade_api

    infra = render_skill("splunk-appdynamics-infrastructure-visibility-setup", tmp_path / "infra")
    gpu = (infra / "gpu-monitoring-runbook.md").read_text(encoding="utf-8")
    assert "GPU Monitoring" in gpu
    assert "DCGM" in gpu
    prometheus = (infra / "prometheus-extension-runbook.md").read_text(encoding="utf-8")
    assert "Prometheus" in prometheus

    dashboards = render_skill("splunk-appdynamics-dashboards-reports-setup", tmp_path / "dash")
    thousandeyes = (dashboards / "thousandeyes-dashboard-integration-runbook.md").read_text(encoding="utf-8")
    assert "ThousandEyes" in thousandeyes
    assert "splunk-appdynamics-thousandeyes-integration-setup" in thousandeyes
    dash_studio = (dashboards / "dash-studio-26-4-runbook.md").read_text(encoding="utf-8")
    assert "standard-deviation" in dash_studio
    reports = (dashboards / "reports-26-4-runbook.md").read_text(encoding="utf-8")
    assert "TLS certificate" in reports
    log_tail = (dashboards / "log-tail-deprecation-runbook.md").read_text(encoding="utf-8")
    assert "Log Tail" in log_tail

    security = render_skill("splunk-appdynamics-security-ai-setup", tmp_path / "security")
    policy = (security / "secure-application-policy-runbook.md").read_text(encoding="utf-8")
    assert "runtime policy" in policy
    assert "Secure Application APIs" in policy
    assert "policyConfigs" in policy
    ai_pod = (security / "cisco-ai-pod-monitoring-runbook.md").read_text(encoding="utf-8")
    assert "Cisco AI POD" in ai_pod
    assert "NVIDIA GPU" in ai_pod

    eum = render_skill("splunk-appdynamics-eum-setup", tmp_path / "eum")
    mobile_replay = (eum / "mobile-session-replay-runbook.md").read_text(encoding="utf-8")
    assert "Mobile Session Replay" in mobile_replay
    assert "session.replay.enabled" in mobile_replay
    mobile_snippets = (eum / "mobile-sdk-snippets.md").read_text(encoding="utf-8")
    assert ".withSessionReplayEnabled(true)" in mobile_snippets
    core_vitals = (eum / "core-web-vitals-runbook.md").read_text(encoding="utf-8")
    assert "Interaction to Next Paint" in core_vitals
    assert "First Input Delay" in core_vitals

    db = render_skill("splunk-appdynamics-database-visibility-setup", tmp_path / "db-release")
    db_release = (db / "database-26-4-release-readiness.yaml").read_text(encoding="utf-8")
    assert "hashicorp_vault" in db_release
    assert "blocking_sessions" in db_release
    assert "query_executor_metrics" in db_release

    synthetic = render_skill("splunk-appdynamics-synthetic-monitoring-setup", tmp_path / "synthetic-release")
    psa = (synthetic / "private-synthetic-agent-26-4-runbook.md").read_text(encoding="utf-8")
    assert "Podman" in psa
    assert "Chrome 147" in psa

    analytics = render_skill("splunk-appdynamics-analytics-setup", tmp_path / "analytics")
    adql = (analytics / "analytics-adql-validation.sh").read_text(encoding="utf-8")
    assert "Connected Device Data" in adql

    sap = render_skill("splunk-appdynamics-sap-agent-setup", tmp_path / "sap")
    sap_runbook = (sap / "sap-agent-runbook.md").read_text(encoding="utf-8")
    assert "gateway/proxy" in sap_runbook
    assert "BiQ business-process data" in sap_runbook


def test_appd_thousandeyes_integration_artifacts_are_gated_and_secret_safe(tmp_path: Path) -> None:
    out = render_skill("splunk-appdynamics-thousandeyes-integration-setup", tmp_path / "appd-te")

    readiness = (out / "appd-te-readiness.yaml").read_text(encoding="utf-8")
    assert "deployment_model: saas" in readiness
    assert "- virtual_appliance" in readiness
    assert "Government" in readiness

    assets = (out / "te-assets-spec.yaml").read_text(encoding="utf-8")
    assert "api_version: splunk-observability-thousandeyes-integration/v1" in assets
    assert "type: http-server" in assets
    assert "name: appdynamics" in assets
    assert "expression: ((responseTime > 500 ms))" in assets
    assert "severity: major" in assets

    handoff = (out / "handoff-thousandeyes-assets.sh").read_text(encoding="utf-8")
    assert "--i-accept-te-mutations" in handoff
    assert "--apply tests,alert_rules,labels,tags,te_dashboards,templates" in handoff

    connector = json.loads((out / "te-appd-webhook-payloads/connector.json").read_text(encoding="utf-8"))
    assert connector["type"] == "generic"
    assert connector["authentication"]["oauthClientSecret"] == "${APPD_OAUTH_CLIENT_SECRET}"

    operation = json.loads((out / "te-appd-webhook-payloads/operation.json").read_text(encoding="utf-8"))
    assert operation["type"] == "webhook"
    assert operation["category"] == "alerts"
    assert "eventtype" in operation["queryParams"]
    assert "CUSTOM" in operation["queryParams"]

    apply_plan = (out / "te-api-apply-plan.sh").read_text(encoding="utf-8")
    assert "APPD_TE_APPLY=1" in apply_plan
    assert "/v7/connectors/generic" in apply_plan
    assert "/v7/operations/webhooks" in apply_plan
    assert "/operations/webhooks/${OPERATION_ID}/connectors" in apply_plan

    native = (out / "te-native-appd-integration-runbook.md").read_text(encoding="utf-8")
    assert "Manage > Integrations" in native
    assert "cSaaS" in native
    assert "No public ThousandEyes API endpoint" in native

    probe = (out / "appd-events-api-probe.sh").read_text(encoding="utf-8")
    assert "APPD_TE_EVENT_PROBE=1" in probe
    assert "eventtype=CUSTOM" in probe
    assert "--data-urlencode" in probe
    assert "APPD_AUTH_CONFIG" in probe
    assert '-H "Authorization: Bearer ${ACCESS_TOKEN}"' not in probe


def test_appd_thousandeyes_custom_webhook_operation_id_is_bound(tmp_path: Path) -> None:
    spec = tmp_path / "appd-te.json"
    spec.write_text(
        json.dumps(
            {
                "controller_url": "https://controller.example.com",
                "account_name": "customer1",
                "appdynamics_target": {"application": "Checkout"},
                "monitored_endpoints": [
                    {"name": "Checkout health", "url": "https://checkout.example.com/health"}
                ],
                "thousandeyes": {
                    "account_group_id": "1234",
                    "custom_webhook_operation_id": "te-webhook-op-123",
                },
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "appd-te-custom-webhook"
    result = run_script(
        SKILLS_DIR / "splunk-appdynamics-thousandeyes-integration-setup/scripts/setup.sh",
        "--render",
        "--spec",
        str(spec),
        "--output-dir",
        str(out),
    )
    assert result.returncode == 0, result.stderr + result.stdout

    assets = (out / "te-assets-spec.yaml").read_text(encoding="utf-8")
    assert "integrationId: te-webhook-op-123" in assets
    assert "integrationType: custom-webhook" in assets


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
        "appd_controller_local_credential_reauth",
        "appd_edit_application_name_permission",
        "appd_controller_license_usage_report",
        "appd_licensing_storage_usage_metrics",
        "appd_machine_agent_tag_rbac",
        "appd_agent_upgrade_api",
        "appd_agent_license_release_reacquire",
        "appd_cluster_agent_k8s_event_visibility",
        "appd_dbmon_vault_access_keys",
        "appd_dbmon_postgres_blocking_sessions",
        "appd_dbmon_mongodb_query_executor_metrics",
        "appd_dbmon_sqlserver_db2_support",
        "appd_core_web_vitals_inp",
        "appd_private_synthetic_agent_26_4_runtime",
        "appd_alert_template_db_hostname",
        "appd_core_web_vitals_alerting",
        "appd_dash_studio_26_4_widgets",
        "appd_reports_tls_direct_download",
        "appd_log_tail_widget_deprecation",
        "appd_cisco_ai_pod_monitoring",
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

    apply = run_script(
        SKILLS_DIR / "splunk-appdynamics-agent-management-setup/scripts/setup.sh",
        "--apply",
        "--spec",
        str(SKILLS_DIR / "splunk-appdynamics-agent-management-setup/template.example"),
    )
    assert apply.returncode == 2
    assert "no executable apply implementation" in apply.stderr


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
    cluster_release = (out / "cluster-agent-26-4-release-runbook.md").read_text(encoding="utf-8")
    assert "enhanced visibility" in cluster_release
    assert "Kubernetes alerting" in cluster_release
    report = json.loads((out / "coverage-report.json").read_text(encoding="utf-8"))
    ids = {row["id"] for row in report["features"]}
    assert {
        "appd_cluster_agent",
        "appd_k8s_auto_instrumentation",
        "appd_cluster_agent_otel_collector",
        "appd_k8s_combined_agent_dual_signal",
        "appd_k8s_splunk_o11y_export",
        "appd_cluster_agent_k8s_event_visibility",
    } <= ids


def test_cluster_agent_availability_probe_defaults_to_server_visibility_path() -> None:
    script = SKILLS_DIR / "splunk-appdynamics-k8s-cluster-agent-setup/scripts/poll_cluster_agent_availability.sh"
    text = script.read_text(encoding="utf-8")
    default_path = "Application Infrastructure Performance|Root|Individual Nodes|*|Cluster Agent|Availability"
    assert f"METRIC_PATH=\"${{APPD_CLUSTER_AGENT_AVAILABILITY_METRIC_PATH:-{default_path}}}\"" in text

    help_result = run_script(script, "--help")
    assert help_result.returncode == 0
    assert default_path in help_result.stdout


def test_dual_agent_and_machine_collector_render_contracts(tmp_path: Path) -> None:
    dual = render_skill("splunk-appdynamics-dual-agent-setup", tmp_path / "dual")
    env = (dual / "java-dual-agent-env.sh").read_text(encoding="utf-8")
    assert 'AGENT_DEPLOYMENT_MODE="dual"' in env
    assert 'OTEL_TRACES_EXPORTER="otlp"' in env
    assert 'OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4318"' in env
    assert 'OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"' in env
    assert "service.name=api" in env
    assert "service.namespace=Checkout" in env
    assert "deployment.environment=prod" in env
    assert "TOKEN" not in env
    systemd = (dual / "java-systemd-dropin.conf").read_text(encoding="utf-8")
    assert "-Dagent.deployment.mode=dual" in systemd
    assert "${JAVA_TOOL_OPTIONS" not in systemd
    runbook = (dual / "dual-agent-collector-first-runbook.md").read_text(encoding="utf-8")
    assert "collector" in runbook.lower()
    assert "Java" in runbook
    report = json.loads((dual / "coverage-report.json").read_text(encoding="utf-8"))
    dual_ids = {row["id"] for row in report["features"]}
    assert {
        "appd_java_dual_signal_mode",
        "appd_java_dual_signal_host_apply",
        "appd_dual_agent_apply_sequence",
    } <= dual_ids

    collector = render_skill("splunk-appdynamics-machine-agent-otel-collector-setup", tmp_path / "collector")
    config = (collector / "collector-config.yaml").read_text(encoding="utf-8")
    assert "127.0.0.1:4317" in config
    assert "127.0.0.1:4318" in config
    assert "signalfx:" in config
    assert "otlphttp/appdynamics:" in config
    assert "x-api-key: ${APPD_OTEL_API_KEY}" in config
    assert "access_token: ${SPLUNK_O11Y_ACCESS_TOKEN}" in config
    assert "\n  logs:" not in config
    collector_report = json.loads((collector / "coverage-report.json").read_text(encoding="utf-8"))
    collector_ids = {row["id"] for row in collector_report["features"]}
    assert {
        "appd_machine_agent_bundled_otel_collector",
        "appd_machine_agent_collector_host_apply",
        "appd_machine_agent_collector_runtime_matrix",
    } <= collector_ids


def test_dual_agent_gates_local_apply_and_rollback(tmp_path: Path) -> None:
    spec = write_local_dual_agent_spec(tmp_path)
    denied = run_script(
        SKILLS_DIR / "splunk-appdynamics-dual-agent-setup/scripts/setup.sh",
        "--apply",
        "all",
        "--spec",
        str(spec),
        "--output-dir",
        str(tmp_path / "denied"),
    )
    assert denied.returncode == 2
    assert "--accept-host-mutation" in denied.stderr
    assert "--accept-app-restart" in denied.stderr

    applied_dir = tmp_path / "applied"
    applied = run_script(
        SKILLS_DIR / "splunk-appdynamics-dual-agent-setup/scripts/setup.sh",
        "--apply",
        "all",
        "--spec",
        str(spec),
        "--output-dir",
        str(applied_dir),
        "--accept-host-mutation",
        "--accept-app-restart",
    )
    assert applied.returncode == 0, applied.stderr + applied.stdout
    report = json.loads((applied_dir / "apply-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "applied"
    assert report["phase"] == "all"
    assert any(file["label"] == "collector config" for file in report["files"])
    assert any(file["label"] == "java dual signal startup config" for file in report["files"])
    report_text = json.dumps(report)
    assert "splunk-secret-value" not in report_text
    assert "appd-secret-value" not in report_text
    command_labels = [command["label"] for command in report["commands"]]
    assert "reload systemd" in command_labels
    assert command_labels.index("reload systemd") < command_labels.index("restart java app")
    startup_entry = next(file for file in report["files"] if file["label"] == "java dual signal startup config")
    startup_config = Path(startup_entry["path"]).read_text(encoding="utf-8")
    assert "${JAVA_TOOL_OPTIONS" not in startup_config
    manifest = json.loads((applied_dir / "backup-manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]
    assert (applied_dir / "rollback-plan.sh").is_file()

    rollback = run_script(
        SKILLS_DIR / "splunk-appdynamics-dual-agent-setup/scripts/setup.sh",
        "--rollback",
        "all",
        "--spec",
        str(spec),
        "--output-dir",
        str(applied_dir),
        "--accept-host-mutation",
        "--accept-app-restart",
    )
    assert rollback.returncode == 0, rollback.stderr + rollback.stdout
    rollback_report = json.loads((applied_dir / "rollback-report.json").read_text(encoding="utf-8"))
    assert rollback_report["status"] == "rolled_back"


def test_machine_agent_collector_local_apply_and_ssh_gate(tmp_path: Path) -> None:
    spec = write_local_dual_agent_spec(tmp_path)
    applied_dir = tmp_path / "collector-applied"
    applied = run_script(
        SKILLS_DIR / "splunk-appdynamics-machine-agent-otel-collector-setup/scripts/setup.sh",
        "--apply",
        "collector",
        "--spec",
        str(spec),
        "--output-dir",
        str(applied_dir),
        "--accept-host-mutation",
    )
    assert applied.returncode == 0, applied.stderr + applied.stdout
    report = json.loads((applied_dir / "apply-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "applied"
    assert report["phase"] == "collector"
    assert any(file["path"].endswith("config.yaml") for file in report["files"])

    ssh_spec = tmp_path / "ssh.yaml"
    ssh_spec.write_text(
        f"""
targets:
  - name: ssh-target
    host: app01.example.com
    execution: ssh
    ssh_user: appdynamics
    ssh_key_file: {tmp_path / "id_rsa"}
    ssh_known_hosts_file: {tmp_path / "known_hosts"}
    machine_agent_home: {tmp_path / "machine"}
    collector_config_path: {tmp_path / "machine/otel-collector/config.yaml"}
    collector_service_name: appdynamics-machine-agent
destinations:
  splunk_o11y:
    token_file: {tmp_path / "secrets/o11y"}
  appd_otel:
    api_key_file: {tmp_path / "secrets/appd"}
""",
        encoding="utf-8",
    )
    denied = run_script(
        SKILLS_DIR / "splunk-appdynamics-machine-agent-otel-collector-setup/scripts/setup.sh",
        "--apply",
        "preflight",
        "--spec",
        str(ssh_spec),
        "--output-dir",
        str(tmp_path / "ssh-denied"),
    )
    assert denied.returncode == 2
    assert "--accept-remote-execution" in denied.stderr


def test_eum_synthetic_and_sap_artifacts_render(tmp_path: Path) -> None:
    eum = render_skill("splunk-appdynamics-eum-setup", tmp_path / "eum")
    snippet = (eum / "browser-rum-snippet.html").read_text(encoding="utf-8")
    assert "APPD_BROWSER_APP_KEY" in snippet
    assert "adrum-latest.js" in snippet
    replay = (eum / "session-replay-config.js").read_text(encoding="utf-8")
    assert "sessionReplay" in replay
    upload = (eum / "source-map-upload-plan.sh").read_text(encoding="utf-8")
    assert "PLAN ONLY" in upload
    assert "product- and release-specific endpoint" in upload
    assert "exit 2" in upload

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
