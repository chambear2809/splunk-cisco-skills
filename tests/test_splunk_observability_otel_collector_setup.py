"""Regressions for Splunk Observability OTel Collector rendering."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-otel-collector-setup/scripts/setup.sh"
VALIDATE = REPO_ROOT / "skills/splunk-observability-otel-collector-setup/scripts/validate.sh"


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


def run_validate(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(VALIDATE), *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def make_ta_package(
    tmp_path: Path,
    *,
    root: str = "Splunk_TA_otel",
    version: str = "0.153.0",
    token_style: str = "current",
    token_default: str = "",
    linux: bool = True,
    windows: bool = True,
    default_stanza: str = "Splunk_TA_otel",
    spec_stanza: str = "Splunk_TA_otel://<name>",
) -> Path:
    package = tmp_path / f"{root}-{token_style}.tgz"
    inputs_token_lines = (
        f"splunk_access_token = {token_default}\n"
        if token_style == "current"
        else f"splunk_access_token_file = {token_default}\n"
    )
    spec_token_lines = (
        "splunk_access_token = <value>\n"
        "* Access token used to send data to Splunk Observability\n"
        if token_style == "current"
        else "splunk_access_token_file = <path>\n"
        "* File containing the access token used to send data to Splunk Observability\n"
    )
    files: dict[str, str | bytes] = {
        f"{root}/default/app.conf": (
            "[package]\n"
            f"id = {root}\n"
            "[launcher]\n"
            "author = Splunk, Inc.\n"
            "description = Splunk Add-on for OpenTelemetry Collector\n"
            f"version = {version}\n"
            "[id]\n"
            f"name = {root}\n"
            f"version = {version}\n"
        ),
        f"{root}/default/inputs.conf": (
            f"[{default_stanza}]\n"
            "disabled=false\n"
            "start_by_shell=false\n"
            "interval = 0\n"
            "index = _internal\n"
            "sourcetype = Splunk_TA_otel\n"
            f"{inputs_token_lines}"
            "splunk_realm =\n"
            f"splunk_config = $SPLUNK_HOME/etc/apps/{root}/configs/agent_config.yaml\n"
            "splunk_collector_log_level = error\n"
            "splunk_collector_env_vars =\n"
            "splunk_collector_cmd_args =\n"
        ),
        f"{root}/README/inputs.conf.spec": (
            f"[{spec_stanza}]\n\n"
            f"{spec_token_lines}"
            "splunk_realm = <value>\n"
            "splunk_config = <value>\n"
            "splunk_collector_log_level = <value>\n"
            "splunk_collector_env_vars = <value>\n"
            "splunk_collector_cmd_args = <value>\n"
        ),
        f"{root}/configs/agent_config.yaml": "receivers: {}\nservice: {}\n",
        f"{root}/configs/gateway_config.yaml": "receivers: {}\nservice: {}\n",
        f"{root}/static/appIcon.png": b"png",
    }
    if linux:
        files[f"{root}/linux_x86_64/bin/Splunk_TA_otel"] = b"linux-binary"
    if windows:
        files[f"{root}/windows_x86_64/bin/Splunk_TA_otel.exe"] = b"windows-binary"

    with tarfile.open(package, "w:gz") as tar:
        for name, content in files.items():
            data = content if isinstance(content, bytes) else content.encode("utf-8")
            source = tmp_path / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(data)
            tar.add(source, arcname=name)
    shutil.rmtree(tmp_path / root, ignore_errors=True)
    return package


def make_unsafe_ta_package(path: Path) -> Path:
    payload = path.parent / "evil.txt"
    payload.write_text("unsafe", encoding="utf-8")
    with tarfile.open(path, "w:gz") as tar:
        tar.add(payload, arcname="../evil.txt")
    return path


def add_extra_top_level_member(package: Path, tmp_path: Path) -> Path:
    replacement = tmp_path / "extra-root.tgz"
    extra = tmp_path / "other-app.txt"
    extra.write_text("unexpected", encoding="utf-8")
    with tarfile.open(package, "r:gz") as source, tarfile.open(replacement, "w:gz") as target:
        for member in source.getmembers():
            if member.isfile():
                extracted = source.extractfile(member)
                assert extracted is not None
                with extracted:
                    target.addfile(member, extracted)
            else:
                target.addfile(member)
        target.add(extra, arcname="OtherApp/default/app.conf")
    package.unlink()
    replacement.rename(package)
    return package


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


def test_kubernetes_extra_values_file_is_copied_and_used_by_helm(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    extra_values = tmp_path / "ai-agent-values.yaml"
    extra_values.write_text(
        "agent:\n"
        "  config:\n"
        "    exporters:\n"
        "      signalfx:\n"
        "        send_otlp_histograms: true\n",
        encoding="utf-8",
    )

    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "demo-cluster",
        "--extra-values-file",
        str(extra_values),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert 'environment: "default"' in values
    copied = output_dir / "k8s/extra-values-1.yaml"
    helm_install = (output_dir / "k8s/helm-install.sh").read_text(encoding="utf-8")
    assert "splunkPlatform:" not in values
    assert copied.read_text(encoding="utf-8") == extra_values.read_text(encoding="utf-8")
    assert '-f "${script_dir}/values.yaml" \\' in helm_install
    assert '-f "${script_dir}/extra-values-1.yaml"' in helm_install


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


def test_ta_current_package_render_inspects_package_and_modular_stanza(tmp_path: Path) -> None:
    package = make_ta_package(tmp_path, root="Splunk_TA_otel", linux=True, windows=True)
    output_dir = tmp_path / "rendered"

    result = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--ta-mode",
        "gateway",
        "--ta-collector-log-level",
        "debug",
        "--ta-collector-env",
        "OTEL_RESOURCE_ATTRIBUTES=deployment.environment=prod,team=platform",
        "--ta-collector-cmd-arg",
        "--set=service.telemetry.logs.level=debug",
        "--ta-collector-cmd-arg",
        "two words",
        "--ta-enable-opamp",
        "--splunk-version",
        "10.4",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    template = (output_dir / "ta/local/inputs.conf.template").read_text(encoding="utf-8")
    assert "[Splunk_TA_otel://Splunk_TA_otel]" in template
    assert "splunk_access_token =" in template
    assert "__SPLUNK_O11Y_ACCESS_TOKEN__" not in template
    assert "configs/gateway_config.yaml" in template
    assert "SPLUNK_LISTEN_INTERFACE=0.0.0.0" in template
    assert "OTEL_RESOURCE_ATTRIBUTES=deployment.environment=prod%2Cteam=platform" in template
    assert "--feature-gates=+splunk.opamp.enabled" in template
    assert "'two words'" in template

    audit = (output_dir / "ta/package-audit.md").read_text(encoding="utf-8")
    assert "Latest audited release: `0.153.0`" in audit
    assert "Published" not in audit
    assert "Package flavor: `multi-os`" in audit
    assert "Token field style: `current`" in audit
    assert "Packaged default stanza: `Splunk_TA_otel`" in audit
    assert "Rendered stanza: `Splunk_TA_otel://Splunk_TA_otel`" in audit
    assert "Stanza mismatch: `true`" in audit

    metadata = json.loads((output_dir / "ta/metadata.json").read_text(encoding="utf-8"))
    assert metadata["splunkbase"]["splunkbase_app_id"] == "7125"
    assert metadata["splunkbase"]["latest_version"] == "0.153.0"
    assert metadata["splunkbase"]["fips_compatible"] is False
    assert metadata["splunkbase"]["fedramp_validated"] is False
    assert metadata["packages"][0]["package_flavor"] == "multi-os"
    assert metadata["packages"][0]["stanza_mismatch"] is True

    validation = run_validate("--check-ta", "--output-dir", str(output_dir))
    assert validation.returncode == 0, validation.stdout
    assert "TA assets passed static validation" in validation.stdout


def test_ta_rejects_secret_like_env_and_cmd_args_and_redacts_package_fields(tmp_path: Path) -> None:
    packaged_secret = "PACKAGED_SECRET_SHOULD_NOT_RENDER"
    package = make_ta_package(tmp_path, token_default=packaged_secret)
    output_dir = tmp_path / "rendered"

    env_rejected = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--ta-collector-env",
        "SPLUNK_ACCESS_TOKEN=inline",
        "--output-dir",
        str(output_dir),
    )
    assert env_rejected.returncode != 0
    assert "secret-like TA collector env" in env_rejected.stdout

    cmd_rejected = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--ta-collector-cmd-arg",
        "--set=exporters.signalfx.access_token=inline",
        "--output-dir",
        str(output_dir),
    )
    assert cmd_rejected.returncode != 0
    assert "secret-like TA collector command args" in cmd_rejected.stdout

    flag_rejected = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--ta-collector-cmd-arg",
        "--access-token",
        "--output-dir",
        str(output_dir),
    )
    assert flag_rejected.returncode != 0
    assert "secret-like TA collector command args" in flag_rejected.stdout

    rendered = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--output-dir",
        str(output_dir),
    )
    assert rendered.returncode == 0, rendered.stdout
    text = rendered_text(output_dir / "ta")
    assert packaged_secret not in text
    metadata = json.loads((output_dir / "ta/metadata.json").read_text(encoding="utf-8"))
    assert metadata["packages"][0]["default_fields"]["splunk_access_token"] == "__REDACTED_SECRET_FIELD__"


def test_ta_preserves_non_template_spec_stanza_and_validates(tmp_path: Path) -> None:
    package = make_ta_package(
        tmp_path,
        default_stanza="Splunk_TA_otel",
        spec_stanza="Splunk_TA_otel://custom_instance",
    )
    output_dir = tmp_path / "rendered"

    result = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    template = (output_dir / "ta/local/inputs.conf.template").read_text(encoding="utf-8")
    assert "[Splunk_TA_otel://custom_instance]" in template

    validation = run_validate("--check-ta", "--output-dir", str(output_dir))
    assert validation.returncode == 0, validation.stdout


def test_ta_legacy_file_secret_and_agent_to_gateway_render(tmp_path: Path) -> None:
    package = make_ta_package(
        tmp_path,
        root="Splunk_TA_otel_linux_x86_64",
        token_style="legacy-file",
        linux=True,
        windows=False,
    )
    output_dir = tmp_path / "rendered"

    result = run_setup(
        "--render-ta",
        "--realm",
        "us1",
        "--ta-package-path",
        str(package),
        "--ta-secret-mode",
        "legacy-file",
        "--ta-mode",
        "agent-to-gateway",
        "--ta-gateway-url",
        "otel-gateway.internal:4317",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    template = (output_dir / "ta/local/inputs.conf.template").read_text(encoding="utf-8")
    generated_config = (output_dir / "ta/local/agent_to_gateway_config.yaml").read_text(encoding="utf-8")
    assert "splunk_access_token_file = $SPLUNK_HOME/etc/apps/Splunk_TA_otel_linux_x86_64/local/access_token" in template
    assert "local/agent_to_gateway_config.yaml" in template
    assert "SPLUNK_GATEWAY_URL=otel-gateway.internal:4317" in template
    assert "endpoint: otel-gateway.internal:4317" in generated_config
    metadata = json.loads((output_dir / "ta/metadata.json").read_text(encoding="utf-8"))
    assert metadata["packages"][0]["package_flavor"] == "linux-x86-64"
    assert metadata["packages"][0]["token_field_style"] == "legacy-file"


def test_ta_multiple_platform_packages_render_and_validate(tmp_path: Path) -> None:
    linux_package = make_ta_package(
        tmp_path,
        root="Splunk_TA_otel_linux_x86_64",
        linux=True,
        windows=False,
    )
    windows_package = make_ta_package(
        tmp_path,
        root="Splunk_TA_otel_windows_x86_64",
        linux=False,
        windows=True,
    )
    output_dir = tmp_path / "rendered"

    result = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(linux_package),
        "--ta-package-path",
        str(windows_package),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    metadata = json.loads((output_dir / "ta/metadata.json").read_text(encoding="utf-8"))
    assert [package["package_flavor"] for package in metadata["packages"]] == [
        "linux-x86-64",
        "windows-x86-64",
    ]
    assert (output_dir / "ta/local/Splunk_TA_otel_linux_x86_64/inputs.conf.template").is_file()
    assert (output_dir / "ta/local/Splunk_TA_otel_windows_x86_64/inputs.conf.template").is_file()
    stage = (output_dir / "ta/stage-ta-package.sh").read_text(encoding="utf-8")
    assert str(linux_package) in stage
    assert str(windows_package) in stage
    validation = run_validate("--check-ta", "--output-dir", str(output_dir))
    assert validation.returncode == 0, validation.stdout


def test_ta_secret_flags_inputs_conf_acceptance_and_regulated_guards(tmp_path: Path) -> None:
    package = make_ta_package(tmp_path)
    token_file = tmp_path / "o11y.token"
    token_file.write_text("SPLUNK_SECRET_SHOULD_NOT_RENDER", encoding="utf-8")
    token_file.chmod(0o600)
    output_dir = tmp_path / "rendered"

    rejected = run_setup("--render-ta", "--realm", "us0", "--ta-access-token", "inline")
    assert rejected.returncode == 1
    assert "--o11y-token-file" in rejected.stdout

    regulated = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--ta-fedramp-required",
        "--output-dir",
        str(output_dir),
    )
    assert regulated.returncode == 1
    assert "FedRAMP" in regulated.stdout

    apply_without_accept = run_setup(
        "--apply-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--ta-secret-mode",
        "inputs-conf",
        "--o11y-token-file",
        str(token_file),
        "--output-dir",
        str(output_dir),
    )
    assert apply_without_accept.returncode == 1
    assert "--accept-ta-token-in-conf" in apply_without_accept.stdout

    render_inputs_conf = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--ta-secret-mode",
        "inputs-conf",
        "--accept-ta-token-in-conf",
        "--o11y-token-file",
        str(token_file),
        "--ta-fips-required",
        "--accept-ta-regulated-override",
        "--output-dir",
        str(output_dir),
    )
    assert render_inputs_conf.returncode == 0, render_inputs_conf.stdout
    text = rendered_text(output_dir / "ta")
    assert "SPLUNK_SECRET_SHOULD_NOT_RENDER" not in text
    assert "__SPLUNK_O11Y_ACCESS_TOKEN__" in text
    assert (output_dir / "ta/regulated-environment-warning.md").is_file()


def test_ta_dry_run_does_not_require_local_package_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"

    result = run_setup(
        "--render-ta",
        "--dry-run",
        "--json",
        "--realm",
        "us0",
        "--ta-package-path",
        str(tmp_path / "not-downloaded-yet.tgz"),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    plan = json.loads(result.stdout)
    assert plan["render_ta"] is True
    assert "preflight-ta.sh" in "\n".join(plan["apply_commands"])
    assert not output_dir.exists()


def test_ta_rejects_unsafe_archives_at_render_and_stage_time(tmp_path: Path) -> None:
    unsafe = make_unsafe_ta_package(tmp_path / "unsafe.tgz")
    output_dir = tmp_path / "rendered"

    rejected = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(unsafe),
        "--output-dir",
        str(output_dir),
    )
    assert rejected.returncode != 0
    assert "unsafe TA package member path" in rejected.stdout

    extra_root = add_extra_top_level_member(make_ta_package(tmp_path), tmp_path)
    extra_rejected = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(extra_root),
        "--output-dir",
        str(output_dir),
    )
    assert extra_rejected.returncode != 0
    assert "unsupported top-level TA package member" in extra_rejected.stdout

    package = make_ta_package(tmp_path)
    rendered = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--output-dir",
        str(output_dir),
    )
    assert rendered.returncode == 0, rendered.stdout
    make_unsafe_ta_package(package)

    preflight = subprocess.run(
        ["bash", str(output_dir / "ta/preflight-ta.sh")],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert preflight.returncode != 0
    assert "unsafe TA package member path" in preflight.stdout


def test_ta_apply_inputs_conf_writes_token_only_to_target_app(tmp_path: Path) -> None:
    package = make_ta_package(tmp_path)
    token_file = tmp_path / "o11y.token"
    token = "REAL_TOKEN_FOR_APPLY_ONLY"
    token_file.write_text(token, encoding="utf-8")
    token_file.chmod(0o600)
    output_dir = tmp_path / "rendered"
    deployment_apps = tmp_path / "deployment-apps"

    result = run_setup(
        "--apply-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--ta-secret-mode",
        "inputs-conf",
        "--accept-ta-token-in-conf",
        "--o11y-token-file",
        str(token_file),
        "--output-dir",
        str(output_dir),
        env={"SPLUNK_DEPLOYMENT_APPS": str(deployment_apps)},
    )

    assert result.returncode == 0, result.stdout
    rendered = rendered_text(output_dir)
    assert token not in rendered
    inputs_conf = deployment_apps / "Splunk_TA_otel/local/inputs.conf"
    assert inputs_conf.is_file()
    assert token in inputs_conf.read_text(encoding="utf-8")
    assert (deployment_apps / "Splunk_TA_otel/configs/agent_config.yaml").is_file()


def test_ta_universal_forwarder_target_and_metadata_rejections(tmp_path: Path) -> None:
    package = make_ta_package(
        tmp_path,
        root="Splunk_TA_otel_windows_x86_64",
        linux=False,
        windows=True,
    )
    output_dir = tmp_path / "rendered"
    apps_dir = tmp_path / "uf-apps"

    mismatch = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--ta-package-flavor",
        "linux-x86-64",
        "--output-dir",
        str(output_dir),
    )
    assert mismatch.returncode != 0
    assert "not requested --ta-package-flavor linux-x86-64" in mismatch.stdout

    version_rejected = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--splunk-version",
        "7.3",
        "--output-dir",
        str(output_dir),
    )
    assert version_rejected.returncode != 0
    assert "outside app 7125 compatibility range" in version_rejected.stdout

    version_patch_accepted = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--splunk-version",
        "10.3.1",
        "--output-dir",
        str(output_dir),
    )
    assert version_patch_accepted.returncode == 0, version_patch_accepted.stdout

    applied = run_setup(
        "--apply-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--ta-target",
        "universal-forwarder",
        "--output-dir",
        str(output_dir),
        env={"SPLUNK_APPS_DIR": str(apps_dir)},
    )
    assert applied.returncode == 0, applied.stdout
    assert (apps_dir / "Splunk_TA_otel_windows_x86_64/default/inputs.conf").is_file()
    assert (apps_dir / "Splunk_TA_otel_windows_x86_64/local/inputs.conf").is_file()
