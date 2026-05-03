"""Regressions for Splunk Observability OTel Collector rendering."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-otel-collector-setup/scripts/setup.sh"


def run_setup(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def rendered_text(root: Path) -> str:
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_rendered_assets_never_include_token_values(tmp_path: Path) -> None:
    o11y_secret = "O11Y_SECRET_SHOULD_NOT_RENDER"
    hec_secret = "HEC_SECRET_SHOULD_NOT_RENDER"
    o11y_file = tmp_path / "o11y.token"
    hec_file = tmp_path / "hec.token"
    output_dir = tmp_path / "rendered"
    o11y_file.write_text(o11y_secret, encoding="utf-8")
    hec_file.write_text(hec_secret, encoding="utf-8")

    result = run_setup(
        "--render-k8s",
        "--render-linux",
        "--realm",
        "us0",
        "--namespace",
        "splunk-otel",
        "--release-name",
        "splunk-otel-collector",
        "--cluster-name",
        "demo-cluster",
        "--platform-hec-url",
        "https://splunk.example.com:8088/services/collector",
        "--platform-hec-token-file",
        str(hec_file),
        "--o11y-token-file",
        str(o11y_file),
        "--linux-host",
        "otel.example.com",
        "--ssh-user",
        "ec2-user",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    text = rendered_text(output_dir)
    assert o11y_secret not in text
    assert hec_secret not in text
    assert str(o11y_file) in text
    assert str(hec_file) in text


def test_kubernetes_values_enable_expected_all_signal_options(tmp_path: Path) -> None:
    o11y_file = tmp_path / "o11y.token"
    hec_file = tmp_path / "hec.token"
    output_dir = tmp_path / "rendered"
    o11y_file.write_text("token", encoding="utf-8")
    hec_file.write_text("hec", encoding="utf-8")

    result = run_setup(
        "--render-k8s",
        "--realm",
        "us1",
        "--cluster-name",
        "demo-cluster",
        "--platform-hec-url",
        "https://splunk.example.com:8088/services/collector",
        "--platform-hec-token-file",
        str(hec_file),
        "--o11y-token-file",
        str(o11y_file),
        "--enable-prometheus-autodetect",
        "--o11y-ingest-url",
        "https://ingest.us1.observability.splunkcloud.com",
        "--o11y-api-url",
        "https://api.us1.observability.splunkcloud.com",
        "--priority-class-name",
        "splunk-otel-agent-priority",
        "--render-priority-class",
        "--enable-platform-persistent-queue",
        "--platform-persistent-queue-path",
        "/var/addon/splunk/exporter_queue",
        "--enable-platform-fsync",
        "--enable-secure-app",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert 'realm: "us1"' in values
    assert 'accessToken: ""' in values
    assert 'ingestUrl: "https://ingest.us1.observability.splunkcloud.com"' in values
    assert 'apiUrl: "https://api.us1.observability.splunkcloud.com"' in values
    assert "metricsEnabled: true" in values
    assert "tracesEnabled: true" in values
    assert "profilingEnabled: true" in values
    assert "secureAppEnabled: true" in values
    assert "sendK8sEventsToSplunkO11y: true" in values
    assert "logsEnabled: true" in values
    assert "prometheus: true" in values
    assert "create: false" in values
    assert "operatorcrds:\n  install: true" in values
    assert 'priorityClassName: "splunk-otel-agent-priority"' in values
    assert "persistentQueue:\n      enabled: true" in values
    assert "fsyncEnabled: true" in values
    assert (output_dir / "k8s/priority-class.sh").is_file()

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["kubernetes"]["platform_logs_enabled"] is True
    assert metadata["kubernetes"]["operator_crds_install"] is True
    assert metadata["kubernetes"]["priority_class_name"] == "splunk-otel-agent-priority"
    assert metadata["signals"]["autoinstrumentation"] is True


def test_platform_hec_helper_renders_handoff_and_default_token_path(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"

    result = run_setup(
        "--render-k8s",
        "--render-platform-hec-helper",
        "--realm",
        "us0",
        "--cluster-name",
        "demo-cluster",
        "--platform-hec-url",
        "https://splunk.example.com:8088/services/collector",
        "--hec-platform",
        "cloud",
        "--hec-token-name",
        "splunk_otel_k8s_logs",
        "--hec-default-index",
        "k8s_logs",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    default_token_path = output_dir / "platform-hec/.splunk_platform_hec_token"
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    create_secret = (output_dir / "k8s/create-secret.sh").read_text(encoding="utf-8")
    render_helper = (output_dir / "platform-hec/render-hec-service.sh").read_text(encoding="utf-8")
    apply_helper = (output_dir / "platform-hec/apply-hec-service.sh").read_text(encoding="utf-8")
    readme = (output_dir / "platform-hec/README.md").read_text(encoding="utf-8")

    assert "logsEnabled: true" in values
    assert str(default_token_path) in create_secret
    assert "splunk-hec-service-setup/scripts/setup.sh" in render_helper
    assert "--platform\n    cloud" in apply_helper
    assert "--write-token-file" in apply_helper
    assert str(default_token_path) in apply_helper
    assert "--token-name\n    splunk_otel_k8s_logs" in apply_helper
    assert "--default-index\n    k8s_logs" in apply_helper
    assert "apply-hec-service.sh" in readme

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["kubernetes"]["platform_logs_enabled"] is True
    assert metadata["platform_hec"]["helper_rendered"] is True
    assert metadata["platform_hec"]["token_file"] == str(default_token_path)


def test_platform_hec_helper_default_token_path_is_absolute_for_relative_output(tmp_path: Path) -> None:
    relative_output = Path("relative-otel-rendered")
    absolute_output = REPO_ROOT / relative_output
    if absolute_output.exists():
        shutil.rmtree(absolute_output)

    try:
        result = run_setup(
            "--render-k8s",
            "--render-platform-hec-helper",
            "--realm",
            "us0",
            "--cluster-name",
            "demo-cluster",
            "--platform-hec-url",
            "https://splunk.example.com:8088/services/collector",
            "--output-dir",
            str(relative_output),
        )

        assert result.returncode == 0, result.stdout
        create_secret = (absolute_output / "k8s/create-secret.sh").read_text(encoding="utf-8")
        apply_helper = (absolute_output / "platform-hec/apply-hec-service.sh").read_text(encoding="utf-8")
        expected = absolute_output / "platform-hec/.splunk_platform_hec_token"
        assert str(expected) in create_secret
        assert str(expected) in apply_helper
    finally:
        shutil.rmtree(absolute_output, ignore_errors=True)


def test_platform_hec_helper_supports_enterprise_token_file_handoff(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    token_file = tmp_path / "platform-hec.token"

    result = run_setup(
        "--render-platform-hec-helper",
        "--realm",
        "us0",
        "--platform-hec-token-file",
        str(token_file),
        "--hec-platform",
        "enterprise",
        "--hec-token-name",
        "otel_enterprise_logs",
        "--hec-default-index",
        "kube_logs",
        "--hec-allowed-indexes",
        "kube_logs,main",
        "--hec-port",
        "9997",
        "--hec-enable-ssl",
        "false",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    apply_helper = (output_dir / "platform-hec/apply-hec-service.sh").read_text(encoding="utf-8")
    assert "--platform\n    enterprise" in apply_helper
    assert "--token-file" in apply_helper
    assert "--write-token-file" not in apply_helper
    assert str(token_file) in apply_helper
    assert "--allowed-indexes\n    kube_logs,main" in apply_helper
    assert "--port\n    9997" in apply_helper
    assert "--enable-ssl\n    false" in apply_helper


def test_kubernetes_values_cover_windows_and_fargate_modes(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"

    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--distribution",
        "eks/fargate",
        "--cluster-name",
        "demo-cluster",
        "--windows-nodes",
        "--disable-cluster-receiver",
        "--disable-agent-host-network",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert 'distribution: "eks/fargate"' in values
    assert "isWindows: true" in values
    assert 'repository: "quay.io/signalfx/splunk-otel-collector-windows"' in values
    assert "clusterReceiver:\n  enabled: false" in values
    assert "agent:\n  hostNetwork: false" in values
    assert "gateway:\n  enabled: true" in values
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["kubernetes"]["gateway_enabled"] is True
    assert metadata["kubernetes"]["windows_nodes"] is True


def test_render_can_use_observability_realm_from_credentials(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    credentials_file = tmp_path / "credentials"
    credentials_file.write_text('SPLUNK_O11Y_REALM="eu0"\n', encoding="utf-8")

    result = run_setup(
        "--render-k8s",
        "--cluster-name",
        "demo-cluster",
        "--output-dir",
        str(output_dir),
        env={"SPLUNK_CREDENTIALS_FILE": str(credentials_file)},
    )

    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert 'realm: "eu0"' in values


def test_linux_install_wrappers_keep_tokens_off_argv(tmp_path: Path) -> None:
    secret = "LINUX_SECRET_SHOULD_NOT_RENDER"
    token_file = tmp_path / "o11y.token"
    output_dir = tmp_path / "rendered"
    token_file.write_text(secret, encoding="utf-8")

    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--o11y-token-file",
        str(token_file),
        "--execution",
        "ssh",
        "--linux-host",
        "otel.example.com",
        "--ssh-user",
        "ec2-user",
        "--api-url",
        "https://api.us0.observability.splunkcloud.com",
        "--ingest-url",
        "https://ingest.us0.observability.splunkcloud.com",
        "--trace-url",
        "https://ingest.us0.observability.splunkcloud.com/v2/trace",
        "--hec-url",
        "https://ingest.us0.observability.splunkcloud.com/v1/log",
        "--collector-config",
        "/etc/otel/custom.yaml",
        "--service-user",
        "otel",
        "--service-group",
        "otel",
        "--skip-collector-repo",
        "--repo-channel",
        "beta",
        "--npm-path",
        "/usr/local/bin/npm",
        "--otlp-endpoint",
        "127.0.0.1:4317",
        "--otlp-endpoint-protocol",
        "grpc",
        "--metrics-exporter",
        "otlp,prometheus",
        "--logs-exporter",
        "otlp",
        "--instrumentation-version",
        "latest",
        "--godebug",
        "fips140=on",
        "--enable-obi",
        "--obi-version",
        "v0.6.0",
        "--obi-install-dir",
        "/usr/local/bin",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    local_script = (output_dir / "linux/install-local.sh").read_text(encoding="utf-8")
    ssh_script = (output_dir / "linux/install-ssh.sh").read_text(encoding="utf-8")
    combined = local_script + "\n" + ssh_script
    assert secret not in combined
    assert "--access-token" not in combined
    assert "--o11y-token" not in combined
    assert "--hec-token" not in combined
    assert "VERIFY_ACCESS_TOKEN=false" in combined
    assert "--api-url\n    https://api.us0.observability.splunkcloud.com" in combined
    assert "--ingest-url\n    https://ingest.us0.observability.splunkcloud.com" in combined
    assert "--trace-url\n    https://ingest.us0.observability.splunkcloud.com/v2/trace" in combined
    assert "--hec-url\n    https://ingest.us0.observability.splunkcloud.com/v1/log" in combined
    assert "--collector-config\n    /etc/otel/custom.yaml" in combined
    assert "--service-user\n    otel" in combined
    assert "--service-group\n    otel" in combined
    assert "--skip-collector-repo" in combined
    assert "--beta" in combined
    assert "--otlp-endpoint\n    127.0.0.1:4317" in combined
    assert "--metrics-exporter\n    otlp,prometheus" in combined
    assert "--logs-exporter\n    otlp" in combined
    assert "--instrumentation-version\n    latest" in combined
    assert "--godebug\n    fips140=on" in combined
    assert "--with-obi" in combined
    assert "--obi-version\n    v0.6.0" in combined
    assert '< "${TOKEN_FILE}"' in local_script
    assert str(token_file) in combined


def test_direct_token_flags_are_rejected() -> None:
    # --access-token covers the legacy installer flag name some operators
    # reach for; --token, --api-token, and --sf-token cover the broader
    # alias surface so each rejection path is asserted in Python (parity
    # with the bats coverage).
    for flag, replacement in (
        ("--o11y-token", "--o11y-token-file"),
        ("--hec-token", "--o11y-token-file"),
        ("--platform-hec-token", "--platform-hec-token-file"),
        ("--access-token", "--o11y-token-file"),
        ("--token", "--o11y-token-file"),
        ("--api-token", "--o11y-token-file"),
        ("--sf-token", "--o11y-token-file"),
    ):
        result = run_setup("--render-linux", "--realm", "us0", flag, "inline")

        assert result.returncode == 1, f"flag {flag} should be rejected"
        assert replacement in result.stdout, f"flag {flag} should suggest {replacement}"
        assert "process listings" in result.stdout
