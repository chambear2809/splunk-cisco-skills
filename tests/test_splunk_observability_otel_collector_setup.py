"""Regressions for Splunk Observability OTel Collector rendering."""

from __future__ import annotations

import json
import ast
import hashlib
import os
import re
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-otel-collector-setup/scripts/setup.sh"
VALIDATE = REPO_ROOT / "skills/splunk-observability-otel-collector-setup/scripts/validate.sh"
RENDERER = REPO_ROOT / "skills/splunk-observability-otel-collector-setup/scripts/render_assets.py"


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


def test_renderer_refuses_root_metadata_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "rendered"
    output_dir.mkdir()
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("do-not-overwrite\n", encoding="utf-8")
    (output_dir / "metadata.json").symlink_to(sentinel)

    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode != 0
    assert "refusing to replace generated-file symlink" in result.stdout
    assert sentinel.read_text(encoding="utf-8") == "do-not-overwrite\n"
    assert (output_dir / "metadata.json").is_symlink()


def run_validate(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(VALIDATE), *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def patch_linux_preflight_host(
    script: Path,
    tmp_path: Path,
    *,
    os_release: str = 'ID="ubuntu"\nVERSION_ID="22.04"\nVERSION_CODENAME="jammy"\n',
) -> None:
    """Point an immutable rendered host probe at test-owned Linux facts."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    os_release_file = tmp_path / "os-release"
    os_release_file.write_text(os_release, encoding="utf-8")
    systemd_runtime = tmp_path / "systemd-runtime"
    systemd_runtime.mkdir(exist_ok=True)
    text = script.read_text(encoding="utf-8")
    text = re.sub(
        r"^OS_RELEASE_FILE=.*$",
        f"OS_RELEASE_FILE={json.dumps(str(os_release_file))}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^SYSTEMD_RUNTIME_DIR=.*$",
        f"SYSTEMD_RUNTIME_DIR={json.dumps(str(systemd_runtime))}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    script.write_text(text, encoding="utf-8")


def make_linux_diagnostic_test_bin(
    root: Path,
    *,
    package_installed: bool = True,
    service_load_state: str = "loaded",
    service_active_state: str = "active",
    service_sub_state: str = "running",
    service_status: int = 0,
    health_status: int = 0,
    listener_status: int = 0,
    journal_status: int = 0,
    journal_line: str = "No recent Collector errors.",
    config_exists: bool = True,
    config_probe_status: int = 0,
    sudo_status: int = 0,
) -> Path:
    """Build deterministic Linux diagnostic command shims."""

    root.mkdir()
    sudo = root / "sudo"
    if sudo_status:
        sudo_body = f"exit {sudo_status}\n"
    else:
        config_status = 0 if config_exists else 1
        if config_probe_status:
            config_probe_action = f"exit {config_probe_status}"
        else:
            config_probe_action = (
                "printf present" if config_exists else "printf missing"
            )
        sudo_body = (
            '[ "${1:-}" != -n ] || shift\n'
            'case "${1:-}" in\n'
            '  env) [ "${2:-}" = true ] && exit 0 ;;\n'
            f"  test) exit {config_status} ;;\n"
            f"  /bin/sh) {config_probe_action}; exit $? ;;\n"
            "  ls) printf '%s\\n' '-rw------- 1 root root 1 mock-config'; exit 0 ;;\n"
            "  sha256sum) printf '%064d  %s\\n' 0 \"${2:-config}\"; exit 0 ;;\n"
            "esac\n"
            'exec "$@"\n'
        )
    sudo.write_text(f"#!/bin/sh\n{sudo_body}", encoding="utf-8")
    sudo.chmod(0o755)

    package_body = (
        "printf '%s\\n' 'splunk-otel-collector-0.154.2'; exit 0\n"
        if package_installed
        else "printf '%s\\n' 'package splunk-otel-collector is not installed'; exit 1\n"
    )
    command_bodies = {
        "id": "printf '%s\\n' 1000\n",
        "rpm": package_body,
        "systemctl": (
            '[ "${1:-}" = show ] || exit 64\n'
            f"printf '%s\\n' 'LoadState={service_load_state}' "
            f"'ActiveState={service_active_state}' 'SubState={service_sub_state}'\n"
            f"exit {service_status}\n"
        ),
        "curl": f"exit {health_status}\n",
        "ss": (
            "printf '%s\\n' 'LISTEN 0 128 127.0.0.1:4317'; "
            f"exit {listener_status}\n"
        ),
        "journalctl": f"printf '%s\\n' {json.dumps(journal_line)}; exit {journal_status}\n",
        "sha256sum": "printf '%064d  %s\\n' 0 \"${1:-config}\"\n",
    }
    for command, body in command_bodies.items():
        shim = root / command
        shim.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        shim.chmod(0o755)
    return root


def make_ta_package(
    tmp_path: Path,
    *,
    root: str = "Splunk_TA_otel",
    version: str = "0.154.2",
    token_style: str = "current",
    token_default: str = "",
    linux: bool = True,
    windows: bool = True,
    default_stanza: str = "Splunk_TA_otel",
    spec_stanza: str = "Splunk_TA_otel://<name>",
    collector_env_default: str = "",
    collector_cmd_default: str = "",
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
            f"splunk_collector_env_vars = {collector_env_default}\n"
            f"splunk_collector_cmd_args = {collector_cmd_default}\n"
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
        "https://splunk.example.com:8088/services/collector/event",
        "--enable-logs",
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
        "https://splunk.example.com:8088/services/collector/event",
        "--all-signals",
        "--deployment-environment",
        "production",
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
    status = (output_dir / "k8s/status.sh").read_text(encoding="utf-8")
    assert "operator_name=splunk-otel-collector-operator" in status
    assert '"deployment/${operator_name}"' in status
    assert '${instrumentation_name}-inst-hook' in status
    assert 'get instrumentation \\' in status
    assert '"${instrumentation_name}" >/dev/null' in status
    assert '-l release="${release_name}"' in status
    assert '-l app.kubernetes.io/instance="${release_name}"' in status
    assert 'LC_ALL=C sort -u "${release_pods}" "${instance_pods}" > "${pod_list}"' in status
    assert "failed to inventory primary Collector pods" in status
    assert "failed to inventory auxiliary Collector pods" in status
    assert "--field-selector=" not in status
    assert "--verify-runtime-pod-json" in status
    assert 'pod_membership=primary' in status
    assert '<"${pod_json}" >/dev/null 2>&1' in status
    assert 'logs "${pod}"' in status
    assert 'pod_log="$(mktemp)"' in status
    assert '>"${pod_log}" 2>&1' in status
    assert 'cat "${pod_log}" >> "${log_file}"' in status
    assert "command output suppressed" in status
    assert "live Kubernetes workload image verification failed" in status
    assert "verifier output suppressed" in status
    assert '--verify-object-json' in status
    assert 'redact-stream.py" < "${log_file}"' not in status
    assert "dropping datapoint.*number of dimensions is larger than 36" in status
    assert "fatal_count=" in status
    assert "drop_count=" in status
    assert "matched content suppressed" in status
    assert "metric data-loss" in status
    assert "outside the supported +/-1 minor skew" in status
    assert "failed to retrieve collector release logs" in status
    assert "expected_opamp" not in status
    assert "OpAMP registration" not in status
    assert "opamp_registration_enabled" not in metadata["kubernetes"]
    assert "built-in OpAMP registration" not in result.stdout


def _render_collector_status_for_behavior(tmp_path: Path) -> tuple[Path, str]:
    output_dir = tmp_path / "status-behavior"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us1",
        "--cluster-name",
        "behavioral-gate",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    status_path = output_dir / "k8s/status.sh"
    return status_path.parent, status_path.read_text(encoding="utf-8")


def _write_status_kubectl_fixture(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "status-bin"
    fake_bin.mkdir()
    kubectl = fake_bin / "kubectl"
    kubectl.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
if "version" in args:
    print(os.environ["VERSION_JSON"])
    raise SystemExit(0)
if "get" in args and "pods" in args and "-o" in args:
    output = args[args.index("-o") + 1]
    if output == "name":
        selector = args[args.index("-l") + 1]
        if os.environ.get("FAIL_SELECTOR") and os.environ["FAIL_SELECTOR"] in selector:
            print("SELECTOR_PRIVATE_MARKER", file=sys.stderr)
            raise SystemExit(1)
        if selector.startswith("release="):
            print("pod/a-primary")
            print("pod/m-shared")
        else:
            print("pod/m-shared")
            print("pod/z-failing")
            if os.environ.get("ADD_COMPLETED_JOB") == "true":
                print("pod/completed-hook")
        raise SystemExit(0)
    if output == "json":
        print(json.dumps({"items": []}))
        raise SystemExit(0)
if "get" in args and "pod" in args and "-o" in args:
    name = args[args.index("pod") + 1]
    image = "registry.example.test/fixture@sha256:" + "a" * 64
    container_name = "fixture"
    if name in {"a-primary", "m-shared"}:
        container_name = "otel-collector"
        image = (
            "quay.io/signalfx/splunk-otel-collector@sha256:"
            "b37160d858a5ad3344301424fba8cdb4d7cc12430383616e0ebc5fb39ad33410"
        )
    if os.environ.get("BAD_IMAGE_POD") == name:
        image = "registry.example.test/fixture:latest"
    if os.environ.get("PRIVATE_BAD_IMAGE_POD") == name:
        image = "registry.example.test/private-image-marker:latest"
    phase = "Running"
    ready = "True"
    owner_references = []
    if name in {"a-primary", "m-shared"}:
        owner_references = [{
            "apiVersion": "apps/v1",
            "kind": "DaemonSet",
            "name": "splunk-otel-collector-agent",
            "controller": True,
        }]
    if os.environ.get("UNREADY_POD") == name:
        ready = "False"
    if os.environ.get("FAILED_POD") == name:
        phase = "Failed"
        ready = "False"
    if name == "completed-hook":
        phase = "Succeeded"
        ready = "False"
        owner_references = [{
            "apiVersion": "batch/v1",
            "kind": "Job",
            "name": "completed-hook-job",
            "controller": True,
        }]
    print(json.dumps({
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": "splunk-otel",
            "ownerReferences": owner_references,
        },
        "spec": {"containers": [{"name": container_name, "image": image}]},
        "status": {
            "phase": phase,
            "conditions": [{"type": "Ready", "status": ready}],
        },
    }))
    raise SystemExit(0)
if "logs" in args:
    pod = args[args.index("logs") + 1]
    with open(os.environ["CALL_LOG"], "a", encoding="utf-8") as handle:
        handle.write(pod + "\\n")
    if pod == "pod/z-failing" and os.environ.get("FAIL_LOG") == "true":
        print("FAILURE_PRIVATE_MARKER", file=sys.stderr)
        raise SystemExit(1)
    if pod == "pod/a-primary" and os.environ.get("DATA_LOSS") == "true":
        print(
            "dropping datapoint CUSTOMER_DIMENSION_MARKER because the number of dimensions is larger than 36"
        )
    elif pod == "pod/a-primary":
        print("PRIOR_PRIVATE_MARKER")
    else:
        print("collector info")
    raise SystemExit(0)
print("unexpected kubectl fixture command", file=sys.stderr)
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    return fake_bin


def _status_log_harness(tmp_path: Path, script_dir: Path, status: str) -> Path:
    start = status.index('log_file="$(mktemp)"')
    harness = tmp_path / "status-log-harness.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'namespace="splunk-otel"\n'
        'release_name="splunk-otel-collector"\n'
        f"script_dir={json.dumps(str(script_dir))}\n"
        + status[start:],
        encoding="utf-8",
    )
    harness.chmod(0o755)
    return harness


def test_status_log_gate_deduplicates_and_suppresses_arbitrary_log_content(
    tmp_path: Path,
) -> None:
    script_dir, status = _render_collector_status_for_behavior(tmp_path)
    fake_bin = _write_status_kubectl_fixture(tmp_path)
    harness = _status_log_harness(tmp_path, script_dir, status)
    call_log = tmp_path / "kubectl-log-calls"
    base_env = os.environ.copy()
    base_env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{base_env['PATH']}",
            "CALL_LOG": str(call_log),
            "VERSION_JSON": json.dumps(
                {
                    "clientVersion": {"major": "1", "minor": "35"},
                    "serverVersion": {"major": "1", "minor": "34"},
                }
            ),
        }
    )

    failed_log_env = base_env | {"FAIL_LOG": "true"}
    failed_log = subprocess.run(
        ["bash", str(harness)],
        cwd=REPO_ROOT,
        env=failed_log_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert failed_log.returncode != 0
    assert "command output suppressed" in failed_log.stdout
    for private_marker in ("PRIOR_PRIVATE_MARKER", "FAILURE_PRIVATE_MARKER"):
        assert private_marker not in failed_log.stdout
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert calls.count("pod/m-shared") == 1

    call_log.unlink()
    selector_failure = subprocess.run(
        ["bash", str(harness)],
        cwd=REPO_ROOT,
        env=base_env | {"FAIL_SELECTOR": "release="},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert selector_failure.returncode != 0
    assert "failed to inventory primary Collector pods" in selector_failure.stdout
    assert "SELECTOR_PRIVATE_MARKER" not in selector_failure.stdout

    data_loss = subprocess.run(
        ["bash", str(harness)],
        cwd=REPO_ROOT,
        env=base_env | {"DATA_LOSS": "true"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert data_loss.returncode != 0
    assert "metric data-loss match(es)" in data_loss.stdout
    assert "CUSTOMER_DIMENSION_MARKER" not in data_loss.stdout
    assert "matched content suppressed" in data_loss.stdout

    release_only_bad_image = subprocess.run(
        ["bash", str(harness)],
        cwd=REPO_ROOT,
        env=base_env | {"BAD_IMAGE_POD": "a-primary"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert release_only_bad_image.returncode != 0
    assert "readiness or image verification failed for pod/a-primary" in (
        release_only_bad_image.stdout
    )

    private_image = subprocess.run(
        ["bash", str(harness)],
        cwd=REPO_ROOT,
        env=base_env | {"PRIVATE_BAD_IMAGE_POD": "z-failing"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert private_image.returncode != 0
    assert "verifier output suppressed" in private_image.stdout
    assert "private-image-marker" not in private_image.stdout

    for state_env in ({"UNREADY_POD": "z-failing"}, {"FAILED_POD": "z-failing"}):
        unhealthy = subprocess.run(
            ["bash", str(harness)],
            cwd=REPO_ROOT,
            env=base_env | state_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert unhealthy.returncode != 0
        assert "readiness or image verification failed for pod/z-failing" in (
            unhealthy.stdout
        )

    if call_log.exists():
        call_log.unlink()
    completed_job = subprocess.run(
        ["bash", str(harness)],
        cwd=REPO_ROOT,
        env=base_env | {"ADD_COMPLETED_JOB": "true"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed_job.returncode == 0, completed_job.stdout
    assert "1 completed Job pod(s)" in completed_job.stdout
    assert "pod/completed-hook" not in call_log.read_text(encoding="utf-8").splitlines()


def test_status_version_skew_gate_executes_fail_closed(tmp_path: Path) -> None:
    _, status = _render_collector_status_for_behavior(tmp_path)
    marker = status.index("outside the supported +/-1 minor skew")
    start = status.rfind("command -v python3", 0, marker)
    end = status.index("\n\nstatus_release_record=", marker)
    harness = tmp_path / "status-version-harness.sh"
    harness.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n" + status[start:end] + "\n",
        encoding="utf-8",
    )
    harness.chmod(0o755)
    fake_bin = _write_status_kubectl_fixture(tmp_path)
    base_env = os.environ.copy()
    base_env["PATH"] = f"{fake_bin}{os.pathsep}{base_env['PATH']}"
    base_env["CALL_LOG"] = str(tmp_path / "unused-call-log")

    supported = subprocess.run(
        ["bash", str(harness)],
        env=base_env
        | {
            "VERSION_JSON": json.dumps(
                {
                    "clientVersion": {"major": "1", "minor": "35+"},
                    "serverVersion": {"major": "1", "minor": "34"},
                }
            )
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert supported.returncode == 0, supported.stdout

    unsupported = subprocess.run(
        ["bash", str(harness)],
        env=base_env
        | {
            "VERSION_JSON": json.dumps(
                {
                    "clientVersion": {"major": "1", "minor": "36"},
                    "serverVersion": {"major": "1", "minor": "34"},
                }
            )
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert unsupported.returncode != 0
    assert "outside the supported +/-1 minor skew" in unsupported.stdout

    malformed = subprocess.run(
        ["bash", str(harness)],
        env=base_env
        | {
            "VERSION_JSON": json.dumps(
                {
                    "clientVersion": {"major": "1", "minor": "not-a-version"},
                    "serverVersion": {"major": "1", "minor": "34"},
                }
            )
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert malformed.returncode != 0
    assert "minor version is invalid" in malformed.stdout


def test_status_helm_gate_streams_private_notes_and_fails_closed(tmp_path: Path) -> None:
    _, status = _render_collector_status_for_behavior(tmp_path)
    assert "helm_status_json" not in status
    start = status.index("# Never retain the full Helm status document")
    deployed_echo = 'echo "Helm status: deployed"'
    end = status.index(deployed_echo, start) + len(deployed_echo)
    harness = tmp_path / "status-helm-harness.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'namespace="splunk-otel"\n'
        'release_name="splunk-otel-collector"\n'
        + status[start:end]
        + "\n",
        encoding="utf-8",
    )
    harness.chmod(0o755)

    fake_bin = tmp_path / "helm-status-bin"
    fake_bin.mkdir()
    helm = fake_bin / "helm"
    helm.write_text(
        "#!/usr/bin/env python3\n"
        "import os,sys\n"
        "sys.stdout.write(os.environ['HELM_STATUS_PAYLOAD'])\n",
        encoding="utf-8",
    )
    helm.chmod(0o755)
    base_env = os.environ.copy()
    base_env["PATH"] = f"{fake_bin}{os.pathsep}{base_env['PATH']}"
    sentinel = "HELM_PRIVATE_NOTES_MARKER"

    cases = (
        (json.dumps({"info": {"status": "deployed", "notes": sentinel}}), 0),
        (json.dumps({"info": {"status": "failed", "notes": sentinel}}), 1),
        (f'{{"info": {sentinel}', 1),
    )
    for payload, expected_failure in cases:
        result = subprocess.run(
            ["bash", "-x", str(harness)],
            env=base_env | {"HELM_STATUS_PAYLOAD": payload},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert (result.returncode != 0) == bool(expected_failure), result.stdout
        assert sentinel not in result.stdout
        if expected_failure:
            assert "command output suppressed" in result.stdout
        else:
            assert "Helm status: deployed" in result.stdout


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
    assert 'environment: ""' in values
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
        "https://splunk.example.com:8088/services/collector/event",
        "--enable-logs",
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
    default_token_path = output_dir / ".secrets/splunk_platform_hec_token"
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
            "https://splunk.example.com:8088/services/collector/event",
            "--enable-logs",
            "--output-dir",
            str(relative_output),
        )

        assert result.returncode == 0, result.stdout
        create_secret = (absolute_output / "k8s/create-secret.sh").read_text(encoding="utf-8")
        apply_helper = (absolute_output / "platform-hec/apply-hec-service.sh").read_text(encoding="utf-8")
        expected = absolute_output / ".secrets/splunk_platform_hec_token"
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
    assert "--allowed-indexes\n    'kube_logs,main'" in apply_helper
    assert "--port\n    9997" in apply_helper
    assert "--enable-ssl\n    false" in apply_helper


def test_kubernetes_values_cover_windows_and_fargate_modes(tmp_path: Path) -> None:
    windows_dir = tmp_path / "windows"
    windows = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "demo-cluster",
        "--windows-nodes",
        "--disable-cluster-receiver",
        "--output-dir",
        str(windows_dir),
    )
    assert windows.returncode == 0, windows.stdout
    values = (windows_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert "isWindows: true" in values
    assert 'repository: "quay.io/signalfx/splunk-otel-collector-windows"' in values
    assert "clusterReceiver:\n  enabled: false" in values
    assert "agent:\n  enabled: true\n  hostNetwork: false" in values
    metadata = json.loads((windows_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["kubernetes"]["windows_nodes"] is True
    assert metadata["kubernetes"]["agent_host_network_requested"] is True
    assert metadata["kubernetes"]["agent_host_network"] is False

    fargate_dir = tmp_path / "fargate"
    fargate = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--distribution",
        "eks/fargate",
        "--cluster-name",
        "demo-cluster",
        "--disable-cluster-receiver",
        "--output-dir",
        str(fargate_dir),
    )
    assert fargate.returncode == 0, fargate.stdout
    values = (fargate_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert 'distribution: "eks/fargate"' in values
    assert "isWindows: false" in values
    assert "agent:\n  enabled: false\n  hostNetwork: false" in values
    assert "gateway:\n  enabled: true" in values
    metadata = json.loads((fargate_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["kubernetes"]["gateway_enabled"] is True
    assert metadata["kubernetes"]["windows_nodes"] is False
    assert metadata["kubernetes"]["agent_host_network_requested"] is True
    assert metadata["kubernetes"]["agent_host_network"] is False

    autopilot_dir = tmp_path / "autopilot"
    autopilot = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--distribution",
        "gke/autopilot",
        "--cloud-provider",
        "gcp",
        "--output-dir",
        str(autopilot_dir),
    )
    assert autopilot.returncode == 0, autopilot.stdout
    values = (autopilot_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert 'distribution: "gke/autopilot"' in values
    assert "agent:\n  enabled: true\n  hostNetwork: true" in values
    metadata = json.loads((autopilot_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["kubernetes"]["agent_host_network_requested"] is True
    assert metadata["kubernetes"]["agent_host_network"] is True
    assert "forces the effective agent.hostNetwork" not in autopilot.stdout

    autopilot_windows = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--distribution",
        "gke/autopilot",
        "--windows-nodes",
        "--output-dir",
        str(tmp_path / "autopilot-windows"),
    )
    assert autopilot_windows.returncode != 0
    assert "GKE Autopilot" in autopilot_windows.stdout


def test_kubernetes_uninstall_requires_confirmation_before_cluster_access(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "uninstall-guard",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    for name in ("helm", "kubectl"):
        command = fake_bin / name
        command.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$0 $*\" >> \"${COMMAND_LOG}\"\n",
            encoding="utf-8",
        )
        command.chmod(0o755)
    run_env = os.environ.copy()
    run_env["PATH"] = f"{fake_bin}{os.pathsep}{run_env['PATH']}"
    run_env["COMMAND_LOG"] = str(command_log)
    refused = subprocess.run(
        ["bash", str(output_dir / "k8s/uninstall.sh")],
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert refused.returncode != 0
    assert "SPLUNK_OTEL_CONFIRM_K8S_UNINSTALL=yes" in refused.stdout
    assert not command_log.exists()


def test_kubernetes_effective_topology_matches_chart_workload_gates(tmp_path: Path) -> None:
    traces_dir = tmp_path / "traces-only"
    traces = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "traces-only",
        "--disable-metrics",
        "--output-dir",
        str(traces_dir),
    )
    assert traces.returncode == 0, traces.stdout
    values = (traces_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    status = (traces_dir / "k8s/status.sh").read_text(encoding="utf-8")
    metadata = json.loads((traces_dir / "metadata.json").read_text(encoding="utf-8"))
    assert "clusterReceiver:\n  enabled: false" in values
    assert "expected_cluster_receiver=false" in status
    assert metadata["kubernetes"]["cluster_receiver_requested"] is True
    assert metadata["kubernetes"]["cluster_receiver_enabled"] is False

    gateway_dir = tmp_path / "gateway-instrumentation"
    gateway = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "gateway-instrumentation",
        "--agent-enabled",
        "false",
        "--gateway",
        "--enable-autoinstrumentation",
        "--deployment-environment",
        "production",
        "--output-dir",
        str(gateway_dir),
    )
    assert gateway.returncode == 0, gateway.stdout
    gateway_values = (gateway_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert "agent:\n  enabled: false" in gateway_values
    assert "  service:\n    enabled: false" in gateway_values
    assert "gateway:\n  enabled: true" in gateway_values


def test_kubernetes_supply_chain_uses_verified_chart_and_digest_image_policy(tmp_path: Path) -> None:
    output_dir = tmp_path / "supply-chain"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "supply-chain",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout

    k8s = output_dir / "k8s"
    renderer = k8s / "k8s-image-post-renderer.py"
    fetch_chart = (k8s / "fetch-chart.sh").read_text(encoding="utf-8")
    preflight = (k8s / "preflight.sh").read_text(encoding="utf-8")
    install = (k8s / "helm-install.sh").read_text(encoding="utf-8")
    status = (k8s / "status.sh").read_text(encoding="utf-8")
    plugin = (k8s / "helm-plugins/splunk-audited-image-pin/plugin.yaml").read_text(
        encoding="utf-8"
    )
    renderer_text = renderer.read_text(encoding="utf-8")

    assert "613f788d786bf741be770512c7c297c4b70d3ab5426ac337b0416209e66bc7b0" in fetch_chart
    assert "splunk-otel-collector-0.154.0.tgz" in fetch_chart
    assert "curl -q --proto '=https' --tlsv1.2" in fetch_chart
    assert "helm repo add" not in preflight + install
    assert 'chart_archive="$(bash "${script_dir}/fetch-chart.sh")"' in preflight
    assert 'chart_archive="$(bash "${script_dir}/fetch-chart.sh")"' in install
    assert "    --version " not in preflight + install
    assert "type: postrenderer/v1" in plugin
    assert "--post-renderer splunk-audited-image-pin" in preflight
    assert '--post-renderer "${script_dir}/k8s-image-post-renderer.py"' in preflight
    assert "Python 3.8 or newer" in preflight
    assert "the pinned chart requires Helm 3.9+ or Helm 4" in preflight
    assert "--verify-runtime-pod-json" in status
    assert "targets_for_primary_pod" in renderer_text
    assert "verify_known_pod_container_names" not in renderer_text
    assert 'verifier="${script_dir}/verify-supply-chain.sh"' in status
    assert 'verifier="${script_dir}/verify-supply-chain.sh"' in (
        k8s / "create-secret.sh"
    ).read_text(encoding="utf-8")
    ast.parse(renderer_text, feature_version=(3, 8))

    standard_source = "quay.io/signalfx/splunk-otel-collector:0.154.0"
    standard_pin = (
        "quay.io/signalfx/splunk-otel-collector@"
        "sha256:b37160d858a5ad3344301424fba8cdb4d7cc12430383616e0ebc5fb39ad33410"
    )
    ubi_source = "registry.access.redhat.com/ubi9/ubi"
    ubi_pin = (
        "registry.access.redhat.com/ubi9/ubi@"
        "sha256:8bf0e8f20737e9c8a68c8a498299e9504ab397b1b1f2837acb2fef12ec698f0e"
    )
    manifest = f"""---
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: splunk-otel-collector-agent
spec:
  template:
    spec:
      containers:
      - name: otel-collector
        image: {standard_source}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: splunk-otel-collector-k8s-cluster-receiver
spec:
  template:
    spec:
      containers:
      - name: otel-collector
        image: {standard_source}
---
apiVersion: v1
kind: Pod
metadata:
  name: validate-secret
spec:
  containers:
  - name: validate-secret
    image: {ubi_source}
"""
    rendered = subprocess.run(
        ["python3", str(renderer)],
        input=manifest,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stdout
    assert standard_source not in rendered.stdout
    assert ubi_source + "\n" not in rendered.stdout
    assert rendered.stdout.count(standard_pin) == 2
    assert ubi_pin in rendered.stdout
    rendered_manifest = tmp_path / "post-rendered.yaml"
    rendered_manifest.write_text(rendered.stdout, encoding="utf-8")
    verified = subprocess.run(
        ["python3", str(renderer), "--verify", str(rendered_manifest)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert verified.returncode == 0, verified.stdout

    for unsafe_image in ("nginx:latest", "quay.io/signalfx/splunk-otel-collector:0.155.0"):
        unsafe = manifest.replace(standard_source, unsafe_image, 1)
        rejected = subprocess.run(
            ["python3", str(renderer)],
            input=unsafe,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert rejected.returncode != 0
        assert "image pin verification failed" in rejected.stdout

    moved_core_pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "collector-agent-review",
            "namespace": "splunk-otel",
            "ownerReferences": [
                {
                    "apiVersion": "apps/v1",
                    "kind": "DaemonSet",
                    "name": "splunk-otel-collector-agent",
                    "controller": True,
                }
            ],
        },
        "spec": {
            "containers": [
                {
                    "name": "otel-collector",
                    "image": "admission.invalid/replaced-core@sha256:" + "c" * 64,
                },
                {
                    "name": "reviewed-auxiliary",
                    "image": "registry.example.test/auxiliary@sha256:" + "d" * 64,
                },
            ]
        },
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
        },
    }
    rejected = subprocess.run(
        [
            "python3",
            str(renderer),
            "--verify-runtime-pod-json",
            "collector-agent-review",
            "primary",
        ],
        input=json.dumps(moved_core_pod),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert rejected.returncode != 0
    assert "does not have exactly one" in rejected.stdout

    accepted_pod = json.loads(json.dumps(moved_core_pod))
    accepted_pod["spec"]["containers"][0]["image"] = standard_pin
    accepted = subprocess.run(
        [
            "python3",
            str(renderer),
            "--verify-runtime-pod-json",
            "collector-agent-review",
            "primary",
        ],
        input=json.dumps(accepted_pod),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stdout

    prefix_collision_auxiliary = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "collector-operator-review",
            "namespace": "splunk-otel",
            "ownerReferences": [
                {
                    "apiVersion": "apps/v1",
                    "kind": "ReplicaSet",
                    "name": "splunk-otel-collector-operator-reviewhash",
                    "controller": True,
                }
            ],
        },
        "spec": {
            "containers": [
                {
                    "name": "otel-collector",
                    "image": "registry.example.test/operator@sha256:" + "e" * 64,
                }
            ]
        },
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
        },
    }
    auxiliary = subprocess.run(
        [
            "python3",
            str(renderer),
            "--verify-runtime-pod-json",
            "collector-operator-review",
            "auxiliary",
        ],
        input=json.dumps(prefix_collision_auxiliary),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert auxiliary.returncode == 0, auxiliary.stdout
    misclassified_primary = subprocess.run(
        [
            "python3",
            str(renderer),
            "--verify-runtime-pod-json",
            "collector-operator-review",
            "primary",
        ],
        input=json.dumps(prefix_collision_auxiliary),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert misclassified_primary.returncode != 0
    assert "exact rendered core controller" in misclassified_primary.stdout

    renamed_deployment_core = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "collector-receiver-review",
            "namespace": "splunk-otel",
            "labels": {"pod-template-hash": "reviewhash"},
            "ownerReferences": [
                {
                    "apiVersion": "apps/v1",
                    "kind": "ReplicaSet",
                    "name": "splunk-otel-collector-k8s-cluster-receiver-reviewhash",
                    "controller": True,
                }
            ],
        },
        "spec": {
            "containers": [
                {
                    "name": "renamed-core",
                    "image": "registry.example.test/replaced@sha256:" + "f" * 64,
                }
            ]
        },
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
        },
    }
    renamed = subprocess.run(
        [
            "python3",
            str(renderer),
            "--verify-runtime-pod-json",
            "collector-receiver-review",
            "primary",
        ],
        input=json.dumps(renamed_deployment_core),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert renamed.returncode != 0
    assert "does not have exactly one" in renamed.stdout

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    supply = metadata["kubernetes"]["image_supply_chain"]
    assert supply["collector_pins"][standard_source] == standard_pin
    assert metadata["kubernetes"]["chart_archive"]["sha256"] == (
        "613f788d786bf741be770512c7c297c4b70d3ab5426ac337b0416209e66bc7b0"
    )
    for relative, expected in supply["support_asset_sha256"].items():
        assert hashlib.sha256((k8s / relative).read_bytes()).hexdigest() == expected
    assert {
        "redact-stream.py",
        "verify-overlay.py",
        "verify-secret-revision.py",
        "helm-release-guard.py",
        "k8s-object-preconditions.py",
        "add-secret-ownership.py",
        "verify-overlays.sh",
        "validate-secrets.sh",
    }.issubset(supply["support_asset_sha256"])

    supply_verifier = k8s / "verify-supply-chain.sh"
    pristine = renderer.read_text(encoding="utf-8")
    renderer.write_text(pristine + "\n# tampered\n", encoding="utf-8")
    tampered = subprocess.run(
        ["bash", str(supply_verifier)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert tampered.returncode != 0
    assert "changed after rendering" in tampered.stdout


def test_helm_release_guard_rejects_foreign_chart_status_and_revision(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "release-guard"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "release-guard",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout

    k8s = output_dir / "k8s"
    guard = k8s / "helm-release-guard.py"
    ast.parse(guard.read_text(encoding="utf-8"), feature_version=(3, 8))
    preflight = (k8s / "preflight.sh").read_text(encoding="utf-8")
    install = (k8s / "helm-install.sh").read_text(encoding="utf-8")
    uninstall = (k8s / "uninstall.sh").read_text(encoding="utf-8")
    combined = preflight + install + uninstall
    assert "--deployed --failed --pending --uninstalled --superseded --uninstalling" in combined
    assert "--all " not in combined
    assert 'get all "${release_name}"' in combined
    assert '--revision "${revision}"' not in combined
    assert install.index("query_helm_release allow-absent any deployed >/dev/null") < install.index(
        "upgrade --install"
    )
    assert uninstall.index("uninstall_release_record=") < uninstall.index(
        'uninstall "${release_name}"'
    )

    owned = {
        "name": "splunk-otel-collector",
        "namespace": "splunk-otel",
        "revision": "4",
        "status": "deployed",
        "chart": "splunk-otel-collector-0.153.0",
        "app_version": "0.153.0",
    }

    def inspect(payload: list[dict[str, str]], *options: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(guard), *options],
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    accepted = inspect([owned], "--allowed-status", "deployed", "--expected-revision", "4")
    assert accepted.returncode == 0, accepted.stdout
    assert accepted.stdout.startswith("4\tdeployed\tsplunk-otel-collector-")

    def inspect_metadata(chart_name: str) -> subprocess.CompletedProcess[str]:
        fields = (
            "splunk-otel-collector",
            "splunk-otel",
            "4",
            "deployed",
            chart_name,
            "1.0.0",
        )
        return subprocess.run(
            [
                "python3",
                str(guard),
                "--metadata",
                "--allowed-status",
                "deployed",
                "--expected-revision",
                "4",
            ],
            input="\t".join(fields),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    exact_metadata = inspect_metadata("splunk-otel-collector")
    assert exact_metadata.returncode == 0, exact_metadata.stdout
    prefix_collision = inspect_metadata("splunk-otel-collector-2evil")
    assert prefix_collision.returncode != 0
    assert "foreign chart" in prefix_collision.stdout

    absent = inspect([], "--allow-absent", "--allowed-status", "deployed")
    assert absent.returncode == 0, absent.stdout
    assert absent.stdout.strip() == "absent"

    unsafe_records = []
    for field, value in (
        ("namespace", "other"),
        ("status", "pending-upgrade"),
        ("revision", "5"),
    ):
        record = dict(owned)
        record[field] = value
        unsafe_records.append((field, record))
    for field, record in unsafe_records:
        options = ["--allowed-status", "deployed"]
        if field == "revision":
            options.extend(("--expected-revision", "4"))
        refused = inspect([record], *options)
        assert refused.returncode != 0
        assert "Helm release ownership guard failed" in refused.stdout


def test_kubernetes_rejects_unaudited_chart_and_kubectl_versions(tmp_path: Path) -> None:
    cases = (
        ("--chart-version", "0.155.0", "audited only for chart"),
        ("--instrumentation-kubectl-image-tag", "v1.34.0", "digest-audited only"),
    )
    for index, (option, value, expected) in enumerate(cases):
        result = run_setup(
            "--render-k8s",
            "--realm",
            "us0",
            "--cluster-name",
            "pins",
            option,
            value,
            "--output-dir",
            str(tmp_path / f"pin-{index}"),
        )
        assert result.returncode != 0
        assert expected in result.stdout


def test_job_owned_instrumentation_has_ownership_snapshot_and_atomic_restore(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "instrumentation-lifecycle"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "ownership",
        "--enable-autoinstrumentation",
        "--deployment-environment",
        "production",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    assert "server minors 1.34 through 1.36" in result.stdout

    k8s = output_dir / "k8s"
    helper = k8s / "instrumentation-lifecycle.py"
    helper_text = helper.read_text(encoding="utf-8")
    ast.parse(helper_text, feature_version=(3, 8))
    preflight = (k8s / "preflight.sh").read_text(encoding="utf-8")
    install = (k8s / "helm-install.sh").read_text(encoding="utf-8")
    uninstall = (k8s / "uninstall.sh").read_text(encoding="utf-8")
    status = (k8s / "status.sh").read_text(encoding="utf-8")
    assert "--verify-owned" in preflight
    assert "capture_instrumentation_prestate" in install
    assert "rollback_instrumentation" in install
    assert "--sanitize-snapshot" in install
    assert "--prepare-replace" in install
    assert "helm_mutation_committed=true" in install
    assert "query_helm_release" in install
    assert "rollback_helm_mutation" in install
    commit_offset = install.index("helm_command_succeeded=true")
    assert commit_offset < install.index(
        'query_helm_release require-present "${helm_expected_revision}" deployed',
        commit_offset,
    )
    assert 'rollback "${release_name}" "${helm_prior_revision}"' in install
    assert 'uninstall "${release_name}"' in install
    assert "--verify-owned" in status
    assert uninstall.index("--verify-owned") < uninstall.index(
        "--delete-options Instrumentation"
    )
    assert "--verify-helm-object" in uninstall
    assert "--delete-options Job" in uninstall
    helm_uninstall_offset = uninstall.index(
        '"${helm_command[@]}" uninstall "${release_name}"'
    )
    assert uninstall.index("--verify-owned") < helm_uninstall_offset
    assert helm_uninstall_offset < uninstall.index("--delete-options Instrumentation")
    assert helm_uninstall_offset < uninstall.index("--delete-options Job")

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    namespace = metadata["kubernetes"]["namespace"]
    release = metadata["kubernetes"]["release_name"]
    name = release if "splunk-otel-collector" in release else f"{release}-splunk-otel-collector"
    owned = {
        "apiVersion": "opentelemetry.io/v1alpha1",
        "kind": "Instrumentation",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "resourceVersion": "7",
            "uid": "server-owned",
            "labels": {
                "app.kubernetes.io/managed-by": "Helm",
                "app.kubernetes.io/instance": release,
            },
            "annotations": {
                "meta.helm.sh/release-name": release,
                "meta.helm.sh/release-namespace": namespace,
            },
        },
        "spec": {"exporter": {"endpoint": "http://collector:4317"}},
        "status": {"healthy": True},
    }
    verified = subprocess.run(
        ["python3", str(helper), "--verify-owned"],
        input=json.dumps(owned),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert verified.returncode == 0, verified.stdout

    sanitized = subprocess.run(
        ["python3", str(helper), "--sanitize-snapshot"],
        input=json.dumps(owned),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert sanitized.returncode == 0, sanitized.stdout
    snapshot = json.loads(sanitized.stdout)
    assert "status" not in snapshot
    assert "uid" not in snapshot["metadata"]
    assert "resourceVersion" not in snapshot["metadata"]
    snapshot_path = tmp_path / "instrumentation-prestate.json"
    snapshot_path.write_text(sanitized.stdout, encoding="utf-8")
    current = json.loads(json.dumps(owned))
    current["metadata"]["resourceVersion"] = "99"
    restored = subprocess.run(
        ["python3", str(helper), "--prepare-replace", str(snapshot_path)],
        input=json.dumps(current),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert restored.returncode == 0, restored.stdout
    restored_metadata = json.loads(restored.stdout)["metadata"]
    assert restored_metadata["resourceVersion"] == "99"
    assert restored_metadata["uid"] == "server-owned"

    delete_options = subprocess.run(
        ["python3", str(helper), "--delete-options", "Instrumentation", name],
        input=json.dumps(current),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert delete_options.returncode == 0, delete_options.stdout
    assert json.loads(delete_options.stdout)["preconditions"] == {
        "uid": "server-owned",
        "resourceVersion": "99",
    }

    foreign = json.loads(json.dumps(owned))
    foreign["metadata"]["annotations"]["meta.helm.sh/release-name"] = "foreign"
    rejected = subprocess.run(
        ["python3", str(helper), "--verify-owned"],
        input=json.dumps(foreign),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert rejected.returncode != 0
    assert "another Helm release" in rejected.stdout
    assert "instrumentation-lifecycle.py" in metadata["kubernetes"]["image_supply_chain"][
        "support_asset_sha256"
    ]


def test_instrumentation_resource_mode_documents_range_and_rejects_helm4_first_install(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "instrumentation-resource-mode"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "resource-mode",
        "--enable-autoinstrumentation",
        "--deployment-environment",
        "production",
        "--instrumentation-installation-job",
        "false",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    assert "installation Job is disabled" in result.stdout
    assert "installation Job path is enabled" not in result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert "  installationJob:\n    enabled: false" in values
    preflight = (output_dir / "k8s/preflight.sh").read_text(encoding="utf-8")
    assert "Helm 4 cannot safely first-install the Instrumentation CR" in preflight
    assert '[[ "${release_preflight}" == "absent" ]]' in preflight


def test_job_owned_postcondition_failure_restores_helm_prestate(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "helm-rollback"
    rendered = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "rollback",
        "--enable-autoinstrumentation",
        "--deployment-environment",
        "production",
        "--output-dir",
        str(output_dir),
    )
    assert rendered.returncode == 0, rendered.stdout

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_bash = fake_bin / "bash"
    fake_bash.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  */fetch-chart.sh) printf '%s\\n' \"$DUMMY_CHART\" ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_helm = fake_bin / "helm"
    fake_helm.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$HELM_LOG\"\n"
        "case \"$1\" in\n"
        "  version) printf '%s\\n' v3.14.0 ;;\n"
        "  list)\n"
        "    if [ -s \"$HELM_STATE\" ]; then\n"
        "      revision=$(cat \"$HELM_STATE\")\n"
        "      printf '[{\"name\":\"splunk-otel-collector\",\"namespace\":\"splunk-otel\",\"revision\":\"%s\",\"status\":\"deployed\",\"chart\":\"splunk-otel-collector-0.153.0\"}]\\n' \"$revision\"\n"
        "    else\n"
        "      printf '[]\\n'\n"
        "    fi\n"
        "    ;;\n"
        "  get)\n"
        "    if [ \"${2:-}\" = all ]; then\n"
        "      if [ \"${*#*Release.Info.Description}\" != \"$*\" ]; then\n"
        "        printf 'Rollback to %s\\n' \"$HELM_PRIOR_REVISION\"\n"
        "      else\n"
        "        revision=$(cat \"$HELM_STATE\")\n"
        "        if [ \"${HELM_CONCURRENT:-no}\" = yes ] && [ -e \"$HELM_MUTATED\" ] && [ ! -e \"$HELM_CONCURRENT_APPLIED\" ]; then\n"
        "          revision=$((revision + 1))\n"
        "          printf '%s\\n' \"$revision\" > \"$HELM_STATE\"\n"
        "          : > \"$HELM_CONCURRENT_APPLIED\"\n"
        "        fi\n"
        "        printf 'splunk-otel-collector\\tsplunk-otel\\t%s\\tdeployed\\tsplunk-otel-collector\\t0.153.0\\n' \"$revision\"\n"
        "      fi\n"
        "    elif [ \"${2:-}\" = manifest ]; then\n"
        "      if [ \"${HELM_MANIFEST_MATCH:-no}\" = yes ]; then\n"
        "        printf '%s\\n' stable-prior-manifest\n"
        "      else\n"
        "        printf 'manifest-%s-%s\\n' \"$(cat \"$HELM_STATE\")\" \"$*\"\n"
        "      fi\n"
        "    else\n"
        "      exit 9\n"
        "    fi\n"
        "    ;;\n"
        "  upgrade)\n"
        "    if [ \"${HELM_UPGRADE_FAIL_MODE:-none}\" = restored ]; then\n"
        "      revision=$((HELM_PRIOR_REVISION + 2))\n"
        "    elif [ -s \"$HELM_STATE\" ]; then\n"
        "      revision=$(cat \"$HELM_STATE\")\n"
        "      revision=$((revision + 1))\n"
        "    else\n"
        "      revision=1\n"
        "    fi\n"
        "    printf '%s\\n' \"$revision\" > \"$HELM_STATE\"\n"
        "    : > \"$HELM_MUTATED\"\n"
        "    if [ \"${HELM_UPGRADE_FAIL_MODE:-none}\" != none ]; then\n"
        "      exit 7\n"
        "    fi\n"
        "    ;;\n"
        "  uninstall) rm -f -- \"$HELM_STATE\" ;;\n"
        "  rollback) printf '%s\\n' \"$3\" > \"$HELM_ROLLED_TO\" ;;\n"
        "  *) exit 9 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_kubectl = fake_bin / "kubectl"
    fake_kubectl.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *api-resources*)\n"
        "    if [ ! -e \"$HELM_MUTATED\" ]; then\n"
        "      printf '%s\\n' instrumentations.opentelemetry.io\n"
        "    fi\n"
        "    ;;\n"
        "  *'auth can-i'*) printf '%s\\n' yes ;;\n"
        "  *'get instrumentation'*) : ;;\n"
        "  *) exit 10 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    for shim in (fake_bash, fake_helm, fake_kubectl):
        shim.chmod(0o755)

    for scenario, prior_revision, concurrent, upgrade_fail_mode in (
        ("new", "", False, "none"),
        ("upgrade", "7", False, "none"),
        ("concurrent", "7", True, "none"),
        ("failed-new-partial", "", False, "partial"),
        ("failed-upgrade-restored", "7", False, "restored"),
    ):
        state = tmp_path / f"{scenario}.state"
        if prior_revision:
            state.write_text(prior_revision + "\n", encoding="utf-8")
        log = tmp_path / f"{scenario}.log"
        mutated = tmp_path / f"{scenario}.mutated"
        concurrent_applied = tmp_path / f"{scenario}.concurrent-applied"
        rolled_to = tmp_path / f"{scenario}.rolled-to"
        dummy_chart = tmp_path / f"{scenario}.tgz"
        dummy_chart.write_bytes(b"not-read-by-fake-helm")
        env = os.environ.copy()
        env.update(
            {
                "PATH": str(fake_bin) + os.pathsep + env["PATH"],
                "DUMMY_CHART": str(dummy_chart),
                "HELM_STATE": str(state),
                "HELM_LOG": str(log),
                "HELM_MUTATED": str(mutated),
                "HELM_CONCURRENT": "yes" if concurrent else "no",
                "HELM_CONCURRENT_APPLIED": str(concurrent_applied),
                "HELM_ROLLED_TO": str(rolled_to),
                "HELM_PRIOR_REVISION": prior_revision or "0",
                "HELM_UPGRADE_FAIL_MODE": upgrade_fail_mode,
                "HELM_MANIFEST_MATCH": "yes" if upgrade_fail_mode == "restored" else "no",
            }
        )
        result = subprocess.run(
            ["/bin/bash", str(output_dir / "k8s/helm-install.sh")],
            cwd=output_dir / "k8s",
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        assert result.returncode != 0
        helm_log = log.read_text(encoding="utf-8")
        assert "upgrade --install splunk-otel-collector" in helm_log
        if upgrade_fail_mode == "partial":
            assert "failed new-release mutation left a Helm release record" in result.stdout
            assert "did not prove restoration of the prior release state" in result.stdout
            assert "rollback splunk-otel-collector" not in helm_log
            assert "uninstall splunk-otel-collector" not in helm_log
            assert state.read_text(encoding="utf-8").strip() == "1"
            snapshot_match = re.search(
                r"recovery snapshot at ([^\s]+/prestate\.json)", result.stdout
            )
            assert snapshot_match, result.stdout
            snapshot = Path(snapshot_match.group(1).rstrip("."))
            assert snapshot.is_file()
            shutil.rmtree(snapshot.parent)
        elif upgrade_fail_mode == "restored":
            assert "did not prove restoration" not in result.stdout
            assert "rollback splunk-otel-collector" not in helm_log
            assert "uninstall splunk-otel-collector" not in helm_log
            assert "get manifest splunk-otel-collector" in helm_log
            assert "--revision 7" in helm_log
            assert state.read_text(encoding="utf-8").strip() == "9"
            assert "recovery snapshot at" not in result.stdout
        elif concurrent:
            assert "rollback splunk-otel-collector" not in helm_log
            assert "uninstall splunk-otel-collector" not in helm_log
            assert state.read_text(encoding="utf-8").strip() == "9"
            assert "release revision changed concurrently" in result.stdout
            snapshot_match = re.search(
                r"recovery snapshot at ([^\s]+/prestate\.json)", result.stdout
            )
            assert snapshot_match, result.stdout
            snapshot = Path(snapshot_match.group(1).rstrip("."))
            assert snapshot.is_file()
            assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
            shutil.rmtree(snapshot.parent)
        elif prior_revision:
            assert "Instrumentation API is unavailable after Helm reported success" in result.stdout
            assert "rollback splunk-otel-collector 7" in helm_log
            assert rolled_to.read_text(encoding="utf-8").strip() == "7"
            assert state.read_text(encoding="utf-8").strip() == "8"
        else:
            assert "Instrumentation API is unavailable after Helm reported success" in result.stdout
            assert "uninstall splunk-otel-collector" in helm_log
            assert not state.exists()


def test_fargate_rejects_windows_obi_and_agent_discovery(tmp_path: Path) -> None:
    for option in ("--windows-nodes", "--enable-obi", "--enable-discovery"):
        result = run_setup(
            "--render-k8s",
            "--realm",
            "us0",
            "--distribution",
            "eks/fargate",
            "--cluster-name",
            "demo-cluster",
            option,
            "--output-dir",
            str(tmp_path / option.removeprefix("--")),
        )
        assert result.returncode != 0


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
        "--enable-logs",
        "--enable-profiling",
        "--enable-discovery",
        "--enable-autoinstrumentation",
        "--instrumentation-mode",
        "systemd",
        "--collector-config",
        "/etc/otel/custom.yaml",
        "--linux-health-endpoint",
        "http://127.0.0.1:13134/health",
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
        "0.154.2",
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
    remote_script = (output_dir / "linux/remote-install.sh").read_text(encoding="utf-8")
    status_script = (output_dir / "linux/status-local.sh").read_text(encoding="utf-8")
    doctor_script = (output_dir / "linux/doctor-local.sh").read_text(encoding="utf-8")
    combined = local_script + "\n" + ssh_script + "\n" + remote_script + "\n" + status_script
    assert secret not in combined
    assert "--access-token" not in combined
    assert "--o11y-token" not in combined
    assert "--hec-token" not in combined
    assert "--config -" in local_script
    assert "--config -" in remote_script
    assert "--write-out '%{http_code}'" in local_script
    assert "--write-out '%{http_code}'" in remote_script
    assert "expected 200" in local_script
    assert "expected 200" in remote_script
    assert "curl -q --proto '=https'" in local_script
    assert "curl -q --proto '=https'" in remote_script
    assert "--header @-" not in combined
    assert "header_file=" not in combined
    bypass_lines = [
        line for line in combined.splitlines() if "VERIFY_ACCESS_TOKEN=false" in line
    ]
    assert len(bypass_lines) == 4
    assert all("env VERIFY_ACCESS_TOKEN=false sh" in line for line in bypass_lines)
    assert all("sudo -n env VERIFY_ACCESS_TOKEN=false sh" in line for line in bypass_lines if "sudo" in line)
    assert "INSTALLER_SHA256=" in combined
    assert "--api-url\n    https://api.us0.observability.splunkcloud.com" in combined
    assert "--ingest-url\n    https://ingest.us0.observability.splunkcloud.com" in combined
    assert "--trace-url" not in combined
    assert "--hec-url" not in combined
    assert "--collector-config\n    /etc/otel/custom.yaml" in combined
    assert (
        "diagnostic_config_paths=(\n"
        "    /etc/otel/collector/splunk-otel-collector.conf\n"
        "    /etc/otel/collector/agent_config.yaml\n"
        "    /etc/otel/collector/gateway_config.yaml\n"
        "    /etc/otel/custom.yaml\n"
        ")"
    ) in doctor_script
    assert "--service-user\n    otel" in combined
    assert "--service-group\n    otel" in combined
    assert "--skip-collector-repo" in combined
    assert "--beta" in combined
    assert "--otlp-endpoint\n    127.0.0.1:4317" in combined
    assert "--metrics-exporter\n    'otlp,prometheus'" in combined
    assert "--logs-exporter\n    otlp" in combined
    assert "--instrumentation-version\n    0.154.2" in combined
    assert 'health_endpoint=http://127.0.0.1:13134/health' in combined
    assert "--godebug\n    fips140=on" in combined
    assert "--with-obi" in combined
    assert "--obi-version\n    v0.6.0" in combined
    assert 'printf \'%s\\n\' "${ACCESS_TOKEN}"' in local_script
    assert 'cat "${TOKEN_FILE}"' not in local_script
    assert "os.O_NOFOLLOW" in local_script
    assert "16384 bytes" in local_script
    assert '| ssh "${ssh_args[@]}"' in ssh_script
    assert '"${script_dir}/remote-install.sh"' in ssh_script
    assert "remote_args" not in ssh_script
    assert "printf -v quoted '%q'" not in ssh_script
    assert "set -eu" in remote_script
    assert "sudo -n env VERIFY_ACCESS_TOKEN=false sh" in remote_script
    assert 'access_token=""' in remote_script
    assert str(token_file) in combined


def test_linux_token_snapshot_rejects_oversize_before_network(tmp_path: Path) -> None:
    token_file = tmp_path / "oversize.token"
    token_file.write_bytes(b"A" * (16 * 1024 + 1))
    token_file.chmod(0o600)
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--execution",
        "ssh",
        "--linux-host",
        "otel.example.com",
        "--ssh-user",
        "ec2-user",
        "--o11y-token-file",
        str(token_file),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout

    network_marker = tmp_path / "network-called"
    fake_bin = tmp_path / "network-bin"
    fake_bin.mkdir()
    for command in ("curl", "ssh", "scp"):
        shim = fake_bin / command
        shim.write_text(
            f"#!/bin/sh\n: > {network_marker}\nexit 99\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
    run_env = os.environ.copy()
    run_env["PATH"] = f"{fake_bin}{os.pathsep}{run_env['PATH']}"
    rejected = subprocess.run(
        ["bash", str(output_dir / "linux/install-ssh.sh")],
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert rejected.returncode != 0
    assert "1 through 16384 bytes" in rejected.stdout
    assert not network_marker.exists()
    remote = (output_dir / "linux/remote-install.sh").read_text(encoding="utf-8")
    assert "access token input exceeds the 16384-byte safety limit" in remote


def test_documented_base64_token_alphabet_is_accepted_without_config_injection(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "o11y.token"
    token_file.write_bytes(b"AbCd0123+/==")
    token_file.chmod(0o600)
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "base64-token",
        "--o11y-token-file",
        str(token_file),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    valid = subprocess.run(
        ["bash", str(output_dir / "k8s/validate-secrets.sh")],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert valid.returncode == 0, valid.stdout

    token_file.write_bytes(b'bad"token')
    invalid = subprocess.run(
        ["bash", str(output_dir / "k8s/validate-secrets.sh")],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert invalid.returncode != 0


def test_linux_target_preflight_rejects_existing_install_before_network(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_otelcol = fake_bin / "otelcol"
    fake_otelcol.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_otelcol.chmod(0o755)
    run_env = os.environ.copy()
    run_env["PATH"] = f"{fake_bin}{os.pathsep}{run_env['PATH']}"
    preflight = subprocess.run(
        ["bash", str(output_dir / "linux/preflight-local.sh")],
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert preflight.returncode != 0
    assert "existing Splunk OTel Collector" in preflight.stdout


def test_linux_custom_config_preflight_checks_parent_traversal(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-config"
    private_dir.mkdir(mode=0o700)
    config = private_dir / "collector.yaml"
    config.write_text("receivers: {}\n", encoding="utf-8")
    config.chmod(0o644)
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--collector-config",
        str(config),
        "--linux-health-endpoint",
        "http://127.0.0.1:13133/",
        "--service-user",
        "otelunseen",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    preflight_script = output_dir / "linux/preflight-local.sh"
    patch_linux_preflight_host(preflight_script, tmp_path)
    fake_bin = tmp_path / "preflight-bin"
    fake_bin.mkdir()
    sudo_log = tmp_path / "sudo.log"
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {sudo_log}\n"
        "[ \"${1:-}\" != -n ] || shift\n"
        "case \"${1:-}\" in\n"
        "  test) exit 0 ;;\n"
        "  ls) printf '%s\\n' '-rw------- 1 root root 1 mock-config'; exit 0 ;;\n"
        "  sha256sum) printf '%064d  %s\\n' 0 \"${2:-config}\"; exit 0 ;;\n"
        "esac\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    for command in (
        "systemctl",
        "systemd-tmpfiles",
        "getent",
        "groupadd",
        "useradd",
        "userdel",
        "nologin",
        "apt-get",
    ):
        shim = fake_bin / command
        shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        shim.chmod(0o755)
    run_env = os.environ.copy()
    run_env["PATH"] = f"{fake_bin}{os.pathsep}{run_env['PATH']}"
    preflight = subprocess.run(
        ["bash", str(preflight_script)],
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert preflight.returncode != 0
    assert "cannot traverse external config parent" in preflight.stdout
    sudo_calls = sudo_log.read_text(encoding="utf-8")
    assert "-n env true" in sudo_calls
    assert f"-n python3 - {config} otelunseen" in sudo_calls


def test_linux_obi_preflight_requires_sha256sum_and_gzip_before_mutation(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--enable-obi",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout

    preflight_script = output_dir / "linux/preflight-local.sh"
    for case_name, provided, expected in (
        ("sha256sum", {"shasum"}, "sha256sum is required before OBI installation"),
        ("gzip", {"shasum", "sha256sum"}, "gzip is required before OBI installation"),
    ):
        fake_bin = tmp_path / f"{case_name}-bin"
        fake_bin.mkdir()
        for command in {"bash", "curl", "python3", "tar", *provided}:
            shim = fake_bin / command
            shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            shim.chmod(0o755)
        run_env = os.environ.copy()
        run_env["PATH"] = str(fake_bin)
        preflight = subprocess.run(
            ["/bin/bash", str(preflight_script)],
            env=run_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert preflight.returncode != 0
        assert expected in preflight.stdout


def test_linux_target_preflight_rejects_unsupported_hosts_and_missing_tools(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    preflight_script = output_dir / "linux/preflight-local.sh"

    patch_linux_preflight_host(
        preflight_script,
        tmp_path / "unsupported-os",
        os_release='ID="alpine"\nVERSION_ID="3.20"\n',
    )
    unsupported_os = subprocess.run(
        ["/bin/bash", str(preflight_script)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert unsupported_os.returncode != 0
    assert "unsupported Linux distribution: alpine" in unsupported_os.stdout

    # Restore supported host facts, then force an unsupported architecture.
    patch_linux_preflight_host(preflight_script, tmp_path / "unsupported-arch")
    arch_bin = tmp_path / "arch-bin"
    arch_bin.mkdir()
    uname = arch_bin / "uname"
    uname.write_text("#!/bin/sh\nprintf '%s\\n' riscv64\n", encoding="utf-8")
    uname.chmod(0o755)
    arch_env = os.environ.copy()
    arch_env["PATH"] = f"{arch_bin}{os.pathsep}{arch_env['PATH']}"
    unsupported_arch = subprocess.run(
        ["/bin/bash", str(preflight_script)],
        env=arch_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert unsupported_arch.returncode != 0
    assert "unsupported Linux architecture: riscv64" in unsupported_arch.stdout

    python_path = shutil.which("python3")
    assert python_path is not None
    for case_name, omitted, expected in (
        ("systemctl", "systemctl", "systemctl is required by the pinned Linux installer"),
        ("apt", "apt-get", "apt-get is required on ubuntu targets"),
    ):
        fake_bin = tmp_path / f"{case_name}-bin"
        fake_bin.mkdir()
        (fake_bin / "python3").symlink_to(python_path)
        commands = {
            "bash",
            "curl",
            "tar",
            "sha256sum",
            "uname",
            "id",
            "systemctl",
            "systemd-tmpfiles",
            "getent",
            "groupadd",
            "useradd",
            "nologin",
            "apt-get",
        }
        commands.remove(omitted)
        for command in commands:
            shim = fake_bin / command
            if command == "uname":
                body = "#!/bin/sh\nprintf '%s\\n' x86_64\n"
            elif command == "id":
                body = "#!/bin/sh\nprintf '%s\\n' 0\n"
            else:
                body = "#!/bin/sh\nexit 0\n"
            shim.write_text(body, encoding="utf-8")
            shim.chmod(0o755)
        run_env = os.environ.copy()
        run_env["PATH"] = str(fake_bin)
        missing_tool = subprocess.run(
            ["/bin/bash", str(preflight_script)],
            env=run_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert missing_tool.returncode != 0
        assert expected in missing_tool.stdout


def test_linux_support_bundle_rejects_unsafe_outputs_and_tampered_redactor(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--execution",
        "ssh",
        "--linux-host",
        "otel.example.com",
        "--ssh-user",
        "ec2-user",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout

    sentinel = tmp_path / "sentinel"
    sentinel.write_text("do-not-replace", encoding="utf-8")
    for script_name in ("support-bundle-local.sh", "support-bundle-ssh.sh"):
        unsafe_output = tmp_path / f"{script_name}.tgz"
        unsafe_output.symlink_to(sentinel)
        rejected = subprocess.run(
            ["bash", str(output_dir / "linux" / script_name), str(unsafe_output)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert rejected.returncode != 0
        assert "refusing to replace an existing or symlink" in rejected.stdout
        assert sentinel.read_text(encoding="utf-8") == "do-not-replace"

    redactor = output_dir / "linux/redact-stream.py"
    redactor.write_text("#!/usr/bin/env python3\nraise SystemExit(7)\n", encoding="utf-8")
    unpublished = tmp_path / "tampered.tgz"
    rejected_redactor = subprocess.run(
        ["bash", str(output_dir / "linux/support-bundle-local.sh"), str(unpublished)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert rejected_redactor.returncode != 0
    assert "redactor failed its rendered SHA-256 check" in rejected_redactor.stdout
    assert not unpublished.exists()


def test_linux_support_bundle_is_privileged_redacted_and_atomically_published(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout

    fake_bin = tmp_path / "diag-bin"
    fake_bin.mkdir()
    redactor_text = (output_dir / "linux/redact-stream.py").read_text(encoding="utf-8")
    assert "from __future__ import annotations" not in redactor_text
    sudo_log = tmp_path / "sudo.log"
    sudo = fake_bin / "sudo"
    sudo.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {sudo_log}\n"
        "[ \"${1:-}\" != -n ] || shift\n"
        "case \"${1:-}\" in\n"
        "  test) exit 0 ;;\n"
        "  /bin/sh) printf present; exit 0 ;;\n"
        "  ls) printf '%s\\n' '-rw------- 1 root root 1 mock-config'; exit 0 ;;\n"
        "  sha256sum) printf '%064d  %s\\n' 0 \"${2:-config}\"; exit 0 ;;\n"
        "esac\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    command_bodies = {
        "id": "printf '%s\\n' 1000\n",
        "systemctl": (
            "[ \"${1:-}\" = show ] || exit 64\n"
            "printf '%s\\n' 'LoadState=loaded' 'ActiveState=active' 'SubState=running' "
            "'SPLUNK_ACCESS_TOKEN=SERVICESECRET'\n"
        ),
        "journalctl": (
            "printf '%s\\n' 'Authorization: Bearer JOURNALSECRET' "
            "'hec_token=HECSECRET'\n"
        ),
        "curl": "exit 0\n",
        "ss": "printf '%s\\n' 'LISTEN 0 128 127.0.0.1:4317'\n",
        "rpm": "printf '%s\\n' 'splunk-otel-collector-0.154.2'\n",
    }
    for command, body in command_bodies.items():
        shim = fake_bin / command
        shim.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        shim.chmod(0o755)

    run_env = os.environ.copy()
    run_env["PATH"] = f"{fake_bin}{os.pathsep}{run_env['PATH']}"
    bundle = tmp_path / "diagnostics.tgz"
    created = subprocess.run(
        ["bash", str(output_dir / "linux/support-bundle-local.sh"), str(bundle)],
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert created.returncode == 0, created.stdout
    assert bundle.is_file() and not bundle.is_symlink()
    assert bundle.stat().st_mode & 0o777 == 0o600
    with tarfile.open(bundle, "r:gz") as archive:
        archive_files: dict[str, bytes] = {}
        for member in archive.getmembers():
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            assert extracted is not None
            archive_files[Path(member.name).name] = extracted.read()
    content = b"\n".join(archive_files.values()).decode("utf-8")
    for secret in ("SERVICESECRET", "JOURNALSECRET", "HECSECRET"):
        assert secret not in content
    assert "__REDACTED__" in content
    assert archive_files["doctor.txt"].decode("utf-8").rstrip().endswith(
        "SPLUNK_OTEL_DIAGNOSTIC_RESULT=complete_healthy"
    )
    assert archive_files["diagnostic-state.txt"].decode("utf-8") == (
        "schema_version=1\n"
        "diagnostics_complete=true\n"
        "collector_health=healthy\n"
        "doctor_exit_code=0\n"
    )
    sudo_calls = sudo_log.read_text(encoding="utf-8")
    assert "-n systemctl show" in sudo_calls
    assert "-n journalctl -u splunk-otel-collector" in sudo_calls

    original_digest = bundle.read_bytes()
    repeated = subprocess.run(
        ["bash", str(output_dir / "linux/support-bundle-local.sh"), str(bundle)],
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert repeated.returncode != 0
    assert "refusing to replace an existing or symlink" in repeated.stdout
    assert bundle.read_bytes() == original_digest


def test_linux_doctor_complete_unhealthy_contract_and_bundle_publication(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout

    missing_bin = make_linux_diagnostic_test_bin(
        tmp_path / "missing-bin",
        package_installed=False,
        service_load_state="not-found",
        service_active_state="inactive",
        service_sub_state="dead",
        health_status=7,
        journal_line="Authorization: Bearer STOPPEDSECRET",
        config_exists=False,
    )
    missing_env = os.environ.copy()
    missing_env["PATH"] = f"{missing_bin}{os.pathsep}{missing_env['PATH']}"
    doctor = subprocess.run(
        ["bash", str(output_dir / "linux/doctor-local.sh")],
        env=missing_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert doctor.returncode == 1, doctor.stdout
    assert "diagnostic_complete=true" in doctor.stdout
    assert "collector_health=unhealthy" in doctor.stdout
    assert doctor.stdout.rstrip().endswith(
        "SPLUNK_OTEL_DIAGNOSTIC_RESULT=complete_unhealthy"
    )

    bundle = tmp_path / "stopped-collector.tgz"
    bundled = subprocess.run(
        ["bash", str(output_dir / "linux/support-bundle-local.sh"), str(bundle)],
        env=missing_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert bundled.returncode == 0, bundled.stdout
    assert "diagnostics were complete" in bundled.stdout
    assert bundle.stat().st_mode & 0o777 == 0o600
    with tarfile.open(bundle, "r:gz") as archive:
        files: dict[str, str] = {}
        for member in archive.getmembers():
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            assert extracted is not None
            files[Path(member.name).name] = extracted.read().decode("utf-8")
    assert files["diagnostic-state.txt"] == (
        "schema_version=1\n"
        "diagnostics_complete=true\n"
        "collector_health=unhealthy\n"
        "doctor_exit_code=1\n"
    )
    assert files["doctor.txt"].rstrip().endswith(
        "SPLUNK_OTEL_DIAGNOSTIC_RESULT=complete_unhealthy"
    )
    assert "STOPPEDSECRET" not in "\n".join(files.values())
    assert "__REDACTED__" in files["journal-redacted.txt"]

    fatal_bin = make_linux_diagnostic_test_bin(
        tmp_path / "fatal-bin",
        journal_line="exporting failed: Authorization: Bearer FATALLOGSECRET",
    )
    fatal_env = os.environ.copy()
    fatal_env["PATH"] = f"{fatal_bin}{os.pathsep}{fatal_env['PATH']}"
    fatal_only = subprocess.run(
        ["bash", str(output_dir / "linux/doctor-local.sh")],
        env=fatal_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert fatal_only.returncode == 1, fatal_only.stdout
    assert "exporting failed" in fatal_only.stdout
    assert "FATALLOGSECRET" not in fatal_only.stdout
    assert fatal_only.stdout.rstrip().endswith(
        "SPLUNK_OTEL_DIAGNOSTIC_RESULT=complete_unhealthy"
    )


def test_linux_support_bundle_refuses_incomplete_diagnostics(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout

    failure_cases = (
        (
            "listener-tool",
            {"listener_status": 69},
            "ss listener collection failed",
        ),
        (
            "journal-collection",
            {"journal_status": 70, "journal_line": "journal unavailable"},
            "journal collection failed",
        ),
        (
            "config-probe-sudo",
            {"config_probe_status": 72},
            "config existence probe failed",
        ),
        (
            "sudo",
            {"sudo_status": 71},
            "noninteractive sudo failed",
        ),
    )
    for name, options, expected_error in failure_cases:
        fake_bin = make_linux_diagnostic_test_bin(tmp_path / f"{name}-bin", **options)
        run_env = os.environ.copy()
        run_env["PATH"] = f"{fake_bin}{os.pathsep}{run_env['PATH']}"
        doctor = subprocess.run(
            ["bash", str(output_dir / "linux/doctor-local.sh")],
            env=run_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert doctor.returncode == 2, doctor.stdout
        assert expected_error in doctor.stdout
        assert "SPLUNK_OTEL_DIAGNOSTIC_RESULT=complete_" not in doctor.stdout
        if name != "sudo":
            assert "diagnostic_complete=false" in doctor.stdout
            assert "collector_health=unknown" in doctor.stdout

        bundle = tmp_path / f"{name}.tgz"
        rejected = subprocess.run(
            ["bash", str(output_dir / "linux/support-bundle-local.sh"), str(bundle)],
            env=run_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert rejected.returncode != 0
        if name == "sudo":
            assert "refusing to create an incomplete support bundle" in rejected.stdout
        else:
            assert "no support bundle was published" in rejected.stdout
        assert not bundle.exists()

    redactor_bin = make_linux_diagnostic_test_bin(tmp_path / "redactor-bin")
    real_python = shutil.which("python3")
    assert real_python is not None
    python_shim = redactor_bin / "python3"
    python_shim.write_text(
        "#!/bin/sh\n"
        f'[ "${{1:-}}" != - ] || exec {json.dumps(real_python)} "$@"\n'
        "exit 73\n",
        encoding="utf-8",
    )
    python_shim.chmod(0o755)
    redactor_env = os.environ.copy()
    redactor_env["PATH"] = f"{redactor_bin}{os.pathsep}{redactor_env['PATH']}"
    redactor_doctor = subprocess.run(
        ["bash", str(output_dir / "linux/doctor-local.sh")],
        env=redactor_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert redactor_doctor.returncode == 2, redactor_doctor.stdout
    assert "diagnostic redaction failed (exit 73)" in redactor_doctor.stdout
    assert "SPLUNK_OTEL_DIAGNOSTIC_RESULT=complete_" not in redactor_doctor.stdout
    redactor_bundle = tmp_path / "redactor-runtime.tgz"
    rejected_redactor = subprocess.run(
        [
            "bash",
            str(output_dir / "linux/support-bundle-local.sh"),
            str(redactor_bundle),
        ],
        env=redactor_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert rejected_redactor.returncode != 0
    assert "no support bundle was published" in rejected_redactor.stdout
    assert not redactor_bundle.exists()


def test_linux_uninstall_guards_auto_instrumentation_and_cleans_runtime_secrets(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--execution",
        "ssh",
        "--linux-host",
        "otel.example.com",
        "--ssh-user",
        "ec2-user",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout

    local_uninstall = output_dir / "linux/uninstall-local.sh"
    ssh_uninstall = output_dir / "linux/uninstall-ssh.sh"
    local_text = local_uninstall.read_text(encoding="utf-8")
    ssh_text = ssh_uninstall.read_text(encoding="utf-8")
    assert "SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION" in local_text
    assert "sudo -n sh" in local_text
    assert "sudo -n bash -c" in local_text
    assert "sudo sh" not in local_text
    assert "sudo bash -c" not in local_text
    assert "/etc/otel/collector/splunk-otel-collector.conf" in local_text
    assert "/etc/otel/collector/splunk_env" in local_text
    assert "Refusing to remove symlink" in local_text
    assert "Token-bearing runtime environment file remains" in local_text
    assert (
        "SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION=yes bash -s" in ssh_text
    )
    assert "SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION=no bash -s" in ssh_text

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_dpkg = fake_bin / "dpkg-query"
    fake_dpkg.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'install ok installed'\n",
        encoding="utf-8",
    )
    fake_dpkg.chmod(0o755)
    curl_sentinel = tmp_path / "curl-called"
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/bin/sh\n: > \"${CURL_SENTINEL}\"\nexit 99\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    guard_env = os.environ.copy()
    guard_env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{guard_env['PATH']}",
            "CURL_SENTINEL": str(curl_sentinel),
            "SPLUNK_OTEL_CONFIRM_UNINSTALL": "yes",
        }
    )
    guarded = subprocess.run(
        ["bash", str(local_uninstall)],
        cwd=output_dir / "linux",
        env=guard_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert guarded.returncode != 0
    assert "upstream uninstaller will also remove" in guarded.stdout
    assert "SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION=yes" in guarded.stdout
    assert not curl_sentinel.exists(), "blast-radius guard must run before download/mutation"

    ssh_capture = tmp_path / "ssh-args"
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" > \"${SSH_CAPTURE}\"\ncat >/dev/null\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    ssh_env = os.environ.copy()
    ssh_env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{ssh_env['PATH']}",
            "SSH_CAPTURE": str(ssh_capture),
            "SPLUNK_OTEL_CONFIRM_UNINSTALL": "yes",
            "SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION": "yes",
        }
    )
    propagated = subprocess.run(
        ["bash", str(ssh_uninstall)],
        cwd=output_dir / "linux",
        env=ssh_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert propagated.returncode == 0, propagated.stdout
    assert (
        "SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION=yes bash -s"
        in ssh_capture.read_text(encoding="utf-8")
    )


def test_linux_default_pipeline_disables_require_custom_config(tmp_path: Path) -> None:
    for flag, pipeline in (
        ("--disable-metrics", "metrics"),
        ("--disable-traces", "trace"),
    ):
        rejected = run_setup(
            "--render-linux",
            "--realm",
            "us0",
            flag,
            "--output-dir",
            str(tmp_path / f"rejected-{pipeline}"),
        )
        assert rejected.returncode != 0
        assert "--collector-config" in rejected.stdout

        output_dir = tmp_path / f"custom-{pipeline}"
        accepted = run_setup(
            "--render-linux",
            "--realm",
            "us0",
            flag,
            "--collector-config",
            "/etc/otel/reviewed.yaml",
            "--linux-health-endpoint",
            "http://127.0.0.1:13133/",
            "--output-dir",
            str(output_dir),
        )
        assert accepted.returncode == 0, accepted.stdout
        metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["linux"]["pipeline_contract"] == "operator-supplied-unverified"
        assert metadata["linux"]["default_config_pipelines"] == "operator-defined"


def test_linux_cpu_and_memory_profiling_are_independently_controlled(tmp_path: Path) -> None:
    cases = (
        ("cpu", ("--enable-profiling",), "--enable-profiler", "--disable-profiler-memory"),
        (
            "memory",
            ("--enable-memory-profiling",),
            "--disable-profiler",
            "--enable-profiler-memory",
        ),
        (
            "both",
            ("--enable-profiling", "--enable-memory-profiling"),
            "--enable-profiler",
            "--enable-profiler-memory",
        ),
    )
    for name, flags, cpu_flag, memory_flag in cases:
        output_dir = tmp_path / name
        result = run_setup(
            "--render-linux",
            "--realm",
            "us0",
            "--enable-autoinstrumentation",
            "--instrumentation-mode",
            "systemd",
            *flags,
            "--output-dir",
            str(output_dir),
        )
        assert result.returncode == 0, result.stdout
        install = (output_dir / "linux/install-local.sh").read_text(encoding="utf-8")
        metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
        assert f"    {cpu_flag}\n" in install
        assert f"    {memory_flag}\n" in install
        assert metadata["linux"]["profiling_enabled"] is (name in {"cpu", "both"})
        assert metadata["linux"]["memory_profiling_enabled"] is (
            name in {"memory", "both"}
        )


def test_linux_rejects_kubernetes_only_fips_selector(tmp_path: Path) -> None:
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--fips-enabled",
        "true",
        "--output-dir",
        str(tmp_path / "rendered"),
    )

    assert result.returncode != 0
    assert "require --render-k8s" in result.stdout


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

    inline_secret = "DO_NOT_ECHO_THIS_SECRET"
    for flag in ("--token", "--access-token", "--platform-hec-token", "--ta-access-token"):
        result = run_setup("--render-linux", "--realm", "us0", f"{flag}={inline_secret}")
        assert result.returncode == 1
        assert inline_secret not in result.stdout


def test_renderer_rejects_direct_secret_arguments_without_echoing_values(
    tmp_path: Path,
) -> None:
    inline_secret = "RENDERER_MUST_NOT_ECHO_THIS_SECRET"
    for argument in (
        f"--token={inline_secret}",
        "--platform-hec-token",
        f"--my-token={inline_secret}",
        "--password",
    ):
        command = [
            "python3",
            str(RENDERER),
            "--output-dir",
            str(tmp_path / "rendered"),
            "--render-linux",
            "--realm",
            "us0",
            argument,
        ]
        if "=" not in argument:
            command.append(inline_secret)
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert result.returncode != 0
        assert inline_secret not in result.stdout
        assert "file" in result.stdout


def test_public_setup_rejects_symlinked_secret_input_paths(tmp_path: Path) -> None:
    token = tmp_path / "token.real"
    token.write_text("SAFE_TOKEN", encoding="utf-8")
    token.chmod(0o600)
    link = tmp_path / "token.link"
    link.symlink_to(token)

    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--o11y-token-file",
        str(link),
        "--output-dir",
        str(tmp_path / "rendered"),
    )
    assert result.returncode != 0
    assert "must not be a symlink" in result.stdout

    tmp_token = Path("/tmp") / f"splunk-otel-token-{os.getpid()}-{tmp_path.name}"
    try:
        tmp_token.write_text("SAFE_TOKEN", encoding="utf-8")
        tmp_token.chmod(0o600)
        accepted = run_setup(
            "--render-linux",
            "--realm",
            "us0",
            "--o11y-token-file",
            str(tmp_token),
            "--output-dir",
            str(tmp_path / "tmp-ancestor-rendered"),
        )
        assert accepted.returncode == 0, accepted.stdout
    finally:
        tmp_token.unlink(missing_ok=True)


def test_json_output_requires_dry_run(tmp_path: Path) -> None:
    setup_result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--json",
        "--output-dir",
        str(tmp_path / "setup"),
    )
    assert setup_result.returncode != 0
    assert "--json requires --dry-run" in setup_result.stdout

    renderer_result = subprocess.run(
        [
            "python3",
            str(RENDERER),
            "--render-linux",
            "--realm",
            "us0",
            "--json",
            "--output-dir",
            str(tmp_path / "renderer"),
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert renderer_result.returncode != 0
    assert "--json requires --dry-run" in renderer_result.stdout


def test_extra_values_cannot_override_file_backed_secret_contract(tmp_path: Path) -> None:
    for payload in (
        "splunkObservability: {accessToken: INLINE_SECRET}\n",
        "secret: {create: true}\n",
        'splunkPlatform:\n  "token": INLINE_SECRET\n',
    ):
        overlay = tmp_path / "override.yaml"
        overlay.write_text(payload, encoding="utf-8")
        result = run_setup(
            "--render-k8s",
            "--realm",
            "us0",
            "--cluster-name",
            "demo",
            "--extra-values-file",
            str(overlay),
            "--output-dir",
            str(tmp_path / "rendered"),
        )
        assert result.returncode != 0
        assert "INLINE_SECRET" not in result.stdout


def test_extra_values_reject_credentials_hidden_in_arbitrary_scalars(
    tmp_path: Path,
) -> None:
    sentinel = "SCALAR_SECRET_MUST_NOT_RENDER"
    unsafe_scalars = (
        f"https://alice:{sentinel}@example.invalid:4317",
        f"Server=db;User=alice;Password={sentinel}",
        f"https://example.invalid/export?api_key={sentinel}",
        f"Authorization=Bearer-{sentinel}",
        f"jdbc:postgresql://alice:{sentinel}@example.invalid/db",
        f"DefaultEndpointsProtocol=https;AccountName=example;AccountKey={sentinel}",
        f"aws_secret_access_key={sentinel}",
        f"Endpoint=sb://example/;SharedAccessKeyName=writer;SharedAccessKey={sentinel}",
        f"-----BEGIN PRIVATE KEY-----\n{sentinel}\n-----END PRIVATE KEY-----",
        f"-----BEGIN ENCRYPTED PRIVATE KEY-----\n{sentinel}\n-----END ENCRYPTED PRIVATE KEY-----",
        f"-----BEGIN RSA PRIVATE KEY-----\n{sentinel}\n-----END RSA PRIVATE KEY-----",
        f"-----BEGIN EC PRIVATE KEY-----\n{sentinel}\n-----END EC PRIVATE KEY-----",
        f"-----BEGIN DSA PRIVATE KEY-----\n{sentinel}\n-----END DSA PRIVATE KEY-----",
        f"-----BEGIN OPENSSH PRIVATE KEY-----\n{sentinel}\n-----END OPENSSH PRIVATE KEY-----",
    )
    for index, scalar in enumerate(unsafe_scalars):
        overlay = tmp_path / f"unsafe-scalar-{index}.yaml"
        overlay.write_text(
            "agent:\n  config:\n    receivers:\n      custom:\n"
            f"        endpoint: {json.dumps(scalar)}\n",
            encoding="utf-8",
        )
        result = run_setup(
            "--render-k8s",
            "--realm",
            "us0",
            "--cluster-name",
            "scalar-secret",
            "--extra-values-file",
            str(overlay),
            "--output-dir",
            str(tmp_path / f"unsafe-scalar-render-{index}"),
        )
        assert result.returncode != 0
        assert sentinel not in result.stdout

    safe = tmp_path / "secret-env-reference.yaml"
    safe.write_text(
        "agent:\n"
        "  extraEnvs:\n"
        "    - name: DB_PASSWORD\n"
        "      valueFrom:\n"
        "        secretKeyRef:\n"
        "          name: db-credentials\n"
        "          key: password\n"
        "  config:\n"
        "    receivers:\n"
        "      custom:\n"
        '        datasource: "Server=db;Password=${env:DB_PASSWORD}"\n',
        encoding="utf-8",
    )
    accepted = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "scalar-secret",
        "--extra-values-file",
        str(safe),
        "--output-dir",
        str(tmp_path / "safe-scalar-render"),
    )
    assert accepted.returncode == 0, accepted.stdout


def test_extra_values_allow_safe_platform_tuning_but_protect_owned_destination_fields(
    tmp_path: Path,
) -> None:
    safe_overlay = tmp_path / "safe-platform-tuning.yaml"
    safe_overlay.write_text(
        "splunkPlatform:\n"
        "  source: kubernetes-audit\n"
        "  sourcetype: kube:audit\n"
        "  metricsSourcetype: otel:metrics\n"
        "  maxConnections: 80\n"
        "  disableCompression: false\n"
        "  timeout: 20s\n"
        "  idleConnTimeout: 15s\n"
        "  fieldNameConvention:\n"
        "    renameFieldsSck: true\n"
        "    keepOtelConvention: true\n"
        "  retryOnFailure:\n"
        "    enabled: true\n"
        "    initialInterval: 2s\n"
        "    maxInterval: 20s\n"
        "    maxElapsedTime: 180s\n"
        "  sendingQueue:\n"
        "    enabled: true\n"
        "    numConsumers: 4\n"
        "    queueSize: 500\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "safe-platform-tuning"
    accepted = run_setup(
        "--render-k8s",
        "--cluster-name",
        "safe-platform-tuning",
        "--disable-metrics",
        "--disable-traces",
        "--platform-logs-enabled",
        "true",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-hec-token-file",
        str(tmp_path / "platform.token"),
        "--extra-values-file",
        str(safe_overlay),
        "--output-dir",
        str(output_dir),
    )
    assert accepted.returncode == 0, accepted.stdout
    assert (output_dir / "k8s/extra-values-1.yaml").read_text(
        encoding="utf-8"
    ) == safe_overlay.read_text(encoding="utf-8")

    protected = (
        ("endpoint", "splunkPlatform:\n  endpoint: https://other.example:8088/services/collector/event\n"),
        ("token", "splunkPlatform:\n  token: INLINE_SECRET\n"),
        ("signal", "splunkPlatform:\n  logsEnabled: false\n"),
        (
            "persistent-queue",
            "splunkPlatform:\n  sendingQueue:\n    persistentQueue:\n      enabled: true\n",
        ),
        (
            "legacy-events",
            "splunkObservability:\n  infrastructureMonitoringEventsEnabled: true\n",
        ),
    )
    for index, (name, payload) in enumerate(protected):
        overlay = tmp_path / f"protected-{index}.yaml"
        overlay.write_text(payload, encoding="utf-8")
        refused = run_setup(
            "--render-k8s",
            "--cluster-name",
            "protected",
            "--disable-metrics",
            "--disable-traces",
            "--platform-logs-enabled",
            "true",
            "--platform-hec-url",
            "https://splunk.example:8088/services/collector/event",
            "--platform-hec-token-file",
            str(tmp_path / "platform.token"),
            "--extra-values-file",
            str(overlay),
            "--output-dir",
            str(tmp_path / f"protected-{name}"),
        )
        assert refused.returncode != 0
        assert "lifecycle-owned value" in refused.stdout or name == "token"
        assert "INLINE_SECRET" not in refused.stdout


def test_ta_free_form_values_reject_multiline_conf_injection(tmp_path: Path) -> None:
    sentinel = "INJECTED_STANZA_SHOULD_NOT_RENDER"
    for flag, value in (
        ("--ta-collector-env", f"SAFE_KEY=ok\ndisabled = false # {sentinel}"),
        ("--ta-collector-cmd-arg", f"--safe\n[{sentinel}]"),
    ):
        output_dir = tmp_path / flag.removeprefix("--")
        result = run_setup(
            "--render-ta",
            "--realm",
            "us0",
            flag,
            value,
            "--output-dir",
            str(output_dir),
        )
        assert result.returncode != 0
        assert sentinel not in result.stdout
        assert not output_dir.exists()


def test_ta_signal_intent_rejects_disables_the_packaged_config_cannot_honor(
    tmp_path: Path,
) -> None:
    for index, flag in enumerate(("--disable-metrics", "--disable-traces", "--disable-logs")):
        result = run_setup(
            "--render-ta",
            "--realm",
            "us0",
            flag,
            "--output-dir",
            str(tmp_path / f"disabled-{index}"),
        )
        assert result.returncode != 0
        assert "all-signal Collector config" in result.stdout

    output_dir = tmp_path / "enabled"
    enabled = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--enable-metrics",
        "--enable-traces",
        "--enable-logs",
        "--output-dir",
        str(output_dir),
    )
    assert enabled.returncode == 0, enabled.stdout
    metadata = json.loads((output_dir / "ta/metadata.json").read_text(encoding="utf-8"))
    assert metadata["packaged_config_signals"] == {
        "metrics": True,
        "traces": True,
        "logs": True,
    }
    assert metadata["signal_intent"]["control_supported"] is False
    assert all(
        metadata["signal_intent"][signal]["explicit"]
        for signal in ("metrics", "traces", "logs")
    )


def test_ta_current_package_render_inspects_package_and_modular_stanza(tmp_path: Path) -> None:
    package = make_ta_package(tmp_path, root="Splunk_TA_otel", linux=True, windows=True)
    output_dir = tmp_path / "rendered"

    result = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--accept-unaudited-ta-package",
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
        "10.3",
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
    assert "Latest audited release: `0.154.2`" in audit
    assert "Published" not in audit
    assert "Package flavor: `multi-os`" in audit
    assert "Token field style: `current`" in audit
    assert "Packaged default stanza: `Splunk_TA_otel`" in audit
    assert "Rendered stanza: `Splunk_TA_otel://Splunk_TA_otel`" in audit
    assert "Stanza mismatch: `true`" in audit

    metadata = json.loads((output_dir / "ta/metadata.json").read_text(encoding="utf-8"))
    assert metadata["splunkbase"]["splunkbase_app_id"] == "7125"
    assert metadata["splunkbase"]["latest_version"] == "0.154.2"
    assert metadata["splunkbase"]["fips_compatible"] is False
    assert metadata["splunkbase"]["fedramp_status"] == "not_documented"
    assert metadata["packages"][0]["dashboard_evidence"]["ships_prebuilt_dashboards"] is False
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
    assert "secret-like ta collector env" in env_rejected.stdout.lower()

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
    assert "secret-like ta collector command args" in cmd_rejected.stdout.lower()

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
    assert "secret-like ta collector command args" in flag_rejected.stdout.lower()

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
        "--accept-unaudited-ta-package",
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
    assert 'endpoint: "otel-gateway.internal:4317"' in generated_config
    assert "insecure: false" in generated_config
    assert "memory_limiter:" in generated_config
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

    placeholder_apply = run_setup(
        "--apply-ta",
        "--accept-unaudited-ta-package",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--output-dir",
        str(output_dir),
    )
    assert placeholder_apply.returncode == 1
    assert "placeholder" in placeholder_apply.stdout.lower()

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
        "--accept-unaudited-ta-package",
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
        "--accept-unaudited-ta-package",
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
    assert "changed after render" in preflight.stdout


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
        "--accept-unaudited-ta-package",
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


def test_ta_stage_preserves_only_regular_local_tree_and_creates_private_backup(
    tmp_path: Path,
) -> None:
    package = make_ta_package(tmp_path)
    output_dir = tmp_path / "rendered"
    deployment_apps = tmp_path / "deployment-apps"
    existing_app = deployment_apps / "Splunk_TA_otel"
    custom = existing_app / "local/nested/custom.conf"
    custom.parent.mkdir(parents=True)
    custom.write_text("[custom]\nenabled = true\n", encoding="utf-8")
    custom.chmod(0o640)
    old_marker = existing_app / "default/old-marker.conf"
    old_marker.parent.mkdir(parents=True)
    old_marker.write_text("old package\n", encoding="utf-8")

    rendered = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--accept-unaudited-ta-package",
        "--ta-secret-mode",
        "environment",
        "--output-dir",
        str(output_dir),
    )
    assert rendered.returncode == 0, rendered.stdout
    stage_script = output_dir / "ta/stage-ta-package.sh"
    stage_text = stage_script.read_text(encoding="utf-8")
    assert "O_NOFOLLOW" in stage_text
    assert "src_dir_fd=target_fd" in stage_text
    assert "shutil.copytree(final" not in stage_text
    assert "os.walk(final" not in stage_text

    env = os.environ.copy()
    env.update(
        {
            "SPLUNK_DEPLOYMENT_APPS": str(deployment_apps),
            "SPLUNK_ACCESS_TOKEN": "RUNTIME_ONLY_TOKEN",
        }
    )
    staged = subprocess.run(
        ["bash", str(stage_script)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert staged.returncode == 0, staged.stdout
    preserved = deployment_apps / "Splunk_TA_otel/local/nested/custom.conf"
    assert preserved.read_text(encoding="utf-8") == "[custom]\nenabled = true\n"
    assert preserved.stat().st_mode & 0o777 == 0o640
    assert (deployment_apps / "Splunk_TA_otel/configs/agent_config.yaml").is_file()

    backup_root = tmp_path / ".splunk-otel-backups"
    assert backup_root.is_dir() and not backup_root.is_symlink()
    assert backup_root.stat().st_mode & 0o777 == 0o700
    backups = list(backup_root.glob("Splunk_TA_otel.backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "default/old-marker.conf").read_text(encoding="utf-8") == "old package\n"
    assert (backups[0] / "local/nested/custom.conf").is_file()


def test_ta_stage_rejects_symlink_in_existing_local_without_exposing_target(
    tmp_path: Path,
) -> None:
    package = make_ta_package(tmp_path)
    output_dir = tmp_path / "rendered"
    deployment_apps = tmp_path / "deployment-apps"
    existing_app = deployment_apps / "Splunk_TA_otel"
    local_dir = existing_app / "local"
    local_dir.mkdir(parents=True)
    marker = existing_app / "existing-marker"
    marker.write_text("must remain\n", encoding="utf-8")
    outside = tmp_path / "outside-secret"
    outside.write_text("do not copy or change\n", encoding="utf-8")
    outside_mode = outside.stat().st_mode
    (local_dir / "escape").symlink_to(outside)

    rendered = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--accept-unaudited-ta-package",
        "--ta-secret-mode",
        "environment",
        "--output-dir",
        str(output_dir),
    )
    assert rendered.returncode == 0, rendered.stdout
    env = os.environ.copy()
    env.update(
        {
            "SPLUNK_DEPLOYMENT_APPS": str(deployment_apps),
            "SPLUNK_ACCESS_TOKEN": "RUNTIME_ONLY_TOKEN",
        }
    )
    staged = subprocess.run(
        ["bash", str(output_dir / "ta/stage-ta-package.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert staged.returncode != 0
    assert "refusing symlink in existing TA local tree" in staged.stdout
    assert outside.read_text(encoding="utf-8") == "do not copy or change\n"
    assert outside.stat().st_mode == outside_mode
    assert marker.read_text(encoding="utf-8") == "must remain\n"
    assert not (tmp_path / ".splunk-otel-backups").exists()


def test_ta_stage_rejects_unsafe_backup_root_without_moving_existing_app(
    tmp_path: Path,
) -> None:
    package = make_ta_package(tmp_path)
    output_dir = tmp_path / "rendered"
    rendered = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--accept-unaudited-ta-package",
        "--ta-secret-mode",
        "environment",
        "--output-dir",
        str(output_dir),
    )
    assert rendered.returncode == 0, rendered.stdout
    stage_script = output_dir / "ta/stage-ta-package.sh"

    for unsafe_kind in ("symlink", "file"):
        case_root = tmp_path / unsafe_kind
        deployment_apps = case_root / "deployment-apps"
        existing_app = deployment_apps / "Splunk_TA_otel"
        marker = existing_app / "local/existing.conf"
        marker.parent.mkdir(parents=True)
        marker.write_text("must remain\n", encoding="utf-8")
        backup_root = case_root / ".splunk-otel-backups"
        if unsafe_kind == "symlink":
            redirected = case_root / "redirected-backups"
            redirected.mkdir()
            backup_root.symlink_to(redirected, target_is_directory=True)
        else:
            backup_root.write_text("not a directory\n", encoding="utf-8")

        env = os.environ.copy()
        env.update(
            {
                "SPLUNK_DEPLOYMENT_APPS": str(deployment_apps),
                "SPLUNK_ACCESS_TOKEN": "RUNTIME_ONLY_TOKEN",
            }
        )
        staged = subprocess.run(
            ["bash", str(stage_script)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert staged.returncode != 0
        assert "TA backup root must be a real non-symlink directory" in staged.stdout
        assert marker.read_text(encoding="utf-8") == "must remain\n"
        if unsafe_kind == "symlink":
            assert list((case_root / "redirected-backups").iterdir()) == []


def test_ta_backup_inventory_and_confirmation_gated_retention(tmp_path: Path) -> None:
    package = make_ta_package(tmp_path)
    output_dir = tmp_path / "rendered"
    deployment_apps = tmp_path / "deployment-apps"
    existing_inputs = deployment_apps / "Splunk_TA_otel/local/inputs.conf"
    existing_inputs.parent.mkdir(parents=True)
    existing_inputs.write_text(
        "[Splunk_TA_otel://Splunk_TA_otel]\nsplunk_access_token = OLD_TOKEN\n",
        encoding="utf-8",
    )
    rendered = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--accept-unaudited-ta-package",
        "--ta-secret-mode",
        "environment",
        "--output-dir",
        str(output_dir),
    )
    assert rendered.returncode == 0, rendered.stdout
    env = os.environ.copy()
    env.update(
        {
            "SPLUNK_DEPLOYMENT_APPS": str(deployment_apps),
            "SPLUNK_ACCESS_TOKEN": "RUNTIME_ONLY_TOKEN",
        }
    )
    for _ in range(4):
        staged = subprocess.run(
            ["bash", str(output_dir / "ta/stage-ta-package.sh")],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert staged.returncode == 0, staged.stdout

    backup_root = tmp_path / ".splunk-otel-backups"
    assert len(list(backup_root.glob("Splunk_TA_otel.backup-*"))) == 4
    inventory = subprocess.run(
        ["bash", str(output_dir / "ta/inventory-backups.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert inventory.returncode == 0, inventory.stdout
    assert inventory.stdout.count("BACKUP\tSplunk_TA_otel.backup-") == 4
    assert "secret_candidates=1" in inventory.stdout

    refused = subprocess.run(
        ["bash", str(output_dir / "ta/prune-backups.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert refused.returncode != 0
    assert "SPLUNK_OTEL_CONFIRM_BACKUP_PRUNE=yes" in refused.stdout
    assert len(list(backup_root.glob("Splunk_TA_otel.backup-*"))) == 4

    prune_env = env | {
        "SPLUNK_OTEL_CONFIRM_BACKUP_PRUNE": "yes",
        "SPLUNK_OTEL_TA_BACKUP_RETAIN": "1",
    }
    pruned = subprocess.run(
        ["bash", str(output_dir / "ta/prune-backups.sh")],
        cwd=REPO_ROOT,
        env=prune_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert pruned.returncode == 0, pruned.stdout
    assert pruned.stdout.count("PRUNED\tSplunk_TA_otel.backup-") == 3
    assert len(list(backup_root.glob("Splunk_TA_otel.backup-*"))) == 1


def test_ta_overlay_templates_are_nofollow_and_integrity_bound(tmp_path: Path) -> None:
    package = make_ta_package(tmp_path)
    token_file = tmp_path / "o11y.token"
    token_file.write_text("APPLY_TOKEN", encoding="utf-8")
    token_file.chmod(0o600)
    output_dir = tmp_path / "rendered"
    deployment_apps = tmp_path / "deployment-apps"
    rendered = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--accept-unaudited-ta-package",
        "--ta-secret-mode",
        "inputs-conf",
        "--accept-ta-token-in-conf",
        "--o11y-token-file",
        str(token_file),
        "--output-dir",
        str(output_dir),
    )
    assert rendered.returncode == 0, rendered.stdout
    env = os.environ.copy()
    env["SPLUNK_DEPLOYMENT_APPS"] = str(deployment_apps)
    staged = subprocess.run(
        ["bash", str(output_dir / "ta/stage-ta-package.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert staged.returncode == 0, staged.stdout

    template = output_dir / "ta/local/Splunk_TA_otel/inputs.conf.template"
    original = template.read_bytes()
    outside = tmp_path / "outside-template"
    outside.write_text("DO_NOT_COPY\n", encoding="utf-8")
    template.unlink()
    template.symlink_to(outside)
    symlinked = subprocess.run(
        ["bash", str(output_dir / "ta/apply-deployment-server.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert symlinked.returncode != 0
    assert "inputs template is missing, non-regular, or a symlink" in symlinked.stdout
    assert not (deployment_apps / "Splunk_TA_otel/local/inputs.conf").exists()

    template.unlink()
    template.write_bytes(original + b"# tampered\n")
    tampered = subprocess.run(
        ["bash", str(output_dir / "ta/apply-deployment-server.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert tampered.returncode != 0
    assert "digest differs from the rendered review packet" in tampered.stdout
    assert "DO_NOT_COPY" not in rendered_text(deployment_apps)


def test_ta_package_is_single_open_and_root_directory_member_is_not_extracted(
    tmp_path: Path,
) -> None:
    package = make_ta_package(tmp_path)
    replacement = tmp_path / "root-member.tgz"
    with tarfile.open(package, "r:gz") as source, tarfile.open(replacement, "w:gz") as target:
        root_member = tarfile.TarInfo("./")
        root_member.type = tarfile.DIRTYPE
        root_member.mode = 0o777
        target.addfile(root_member)
        for member in source.getmembers():
            if member.isfile():
                extracted = source.extractfile(member)
                assert extracted is not None
                with extracted:
                    target.addfile(member, extracted)
            else:
                target.addfile(member)
    package.unlink()
    replacement.rename(package)
    output_dir = tmp_path / "rendered"
    rendered = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--accept-unaudited-ta-package",
        "--ta-secret-mode",
        "environment",
        "--output-dir",
        str(output_dir),
    )
    assert rendered.returncode == 0, rendered.stdout
    preflight = (output_dir / "ta/preflight-ta.sh").read_text(encoding="utf-8")
    stage = (output_dir / "ta/stage-ta-package.sh").read_text(encoding="utf-8")
    backups = (output_dir / "ta/manage-backups.py").read_text(encoding="utf-8")
    assert "sys.version_info < (3, 6)" in preflight
    assert '"O_NOFOLLOW", "O_DIRECTORY"' in preflight
    assert "sys.version_info < (3, 6)" in backups
    assert "requires O_NOFOLLOW and O_DIRECTORY support" in backups
    assert "tarfile.open(fileobj=archive_handle" in preflight
    assert "tarfile.open(fileobj=archive_handle" in stage
    assert "tarfile.open(package" not in stage
    assert 'if not name or name == "."' in stage

    hardlink = tmp_path / "hardlinked-package.tgz"
    os.link(package, hardlink)
    hardlinked = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--output-dir",
        str(tmp_path / "hardlinked-render"),
    )
    assert hardlinked.returncode != 0
    assert "single-link regular file" in hardlinked.stdout


def test_ta_universal_forwarder_target_and_metadata_rejections(tmp_path: Path) -> None:
    package = make_ta_package(
        tmp_path,
        root="Splunk_TA_otel_windows_x86_64",
        linux=False,
        windows=True,
    )
    output_dir = tmp_path / "rendered"
    apps_dir = tmp_path / "uf-apps"
    splunk_home = tmp_path / "splunkforwarder"
    splunk_cli = splunk_home / "bin/splunk"
    splunk_cli.parent.mkdir(parents=True)
    splunk_cli.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"btool\" ]]; then\n"
            "  echo \"/opt/splunkforwarder/etc/apps/Splunk_TA_otel_linux_x86_64/local/inputs.conf [Splunk_TA_otel://Splunk_TA_otel]\"\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    splunk_cli.chmod(0o755)
    token_file = tmp_path / "o11y.token"
    token_file.write_text("UF_APPLY_TOKEN", encoding="utf-8")
    token_file.chmod(0o600)

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
    assert "not in the TA family's audited compatibility trains" in version_rejected.stdout

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

    version_104_accepted = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--splunk-version",
        "10.4.0",
        "--output-dir",
        str(output_dir),
    )
    assert version_104_accepted.returncode == 0, version_104_accepted.stdout

    version_105_rejected = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--splunk-version",
        "10.5.0",
        "--output-dir",
        str(output_dir),
    )
    assert version_105_rejected.returncode != 0
    assert "not in the TA family's audited compatibility trains" in version_105_rejected.stdout

    version_post_ceiling = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--splunk-version",
        "11.0",
        "--output-dir",
        str(output_dir),
    )
    assert version_post_ceiling.returncode != 0
    assert "not in the TA family's audited compatibility trains" in version_post_ceiling.stdout

    windows_local_rejected = run_setup(
        "--render-ta",
        "--realm",
        "us0",
        "--ta-package-path",
        str(package),
        "--ta-target",
        "universal-forwarder",
        "--output-dir",
        str(output_dir),
    )
    assert windows_local_rejected.returncode != 0
    assert "requires a Linux-capable package" in windows_local_rejected.stdout

    linux_package = make_ta_package(
        tmp_path,
        root="Splunk_TA_otel_linux_x86_64",
        linux=True,
        windows=False,
    )
    applied = run_setup(
        "--apply-ta",
        "--accept-unaudited-ta-package",
        "--realm",
        "us0",
        "--ta-package-path",
        str(linux_package),
        "--ta-target",
        "universal-forwarder",
        "--ta-secret-mode",
        "inputs-conf",
        "--accept-ta-token-in-conf",
        "--o11y-token-file",
        str(token_file),
        "--output-dir",
        str(output_dir),
        env={"SPLUNK_APPS_DIR": str(apps_dir), "SPLUNK_HOME": str(splunk_home)},
    )
    assert applied.returncode == 0, applied.stdout
    assert (apps_dir / "Splunk_TA_otel_linux_x86_64/local/inputs.conf").is_file()


def test_platform_only_otlp_renders_without_realm_or_observability_token(tmp_path: Path) -> None:
    output_dir = tmp_path / "platform-only"
    result = run_setup(
        "--render-k8s",
        "--cluster-name",
        "platform-only",
        "--disable-metrics",
        "--disable-traces",
        "--platform-logs-enabled",
        "true",
        "--platform-otlp-endpoint",
        "splunk-otlp.example:4317",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    create_secret = (output_dir / "k8s/create-secret.sh").read_text(encoding="utf-8")
    assert "splunkObservability:" not in values
    assert "splunkPlatform:" in values
    assert "No external Collector secret is required" in create_secret
    assert "--from-file=splunk_observability_access_token" not in create_secret
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["kubernetes"]["platform_only"] is True
    validation = run_validate("--check-k8s", "--output-dir", str(output_dir))
    assert validation.returncode == 0, validation.stdout


def test_combined_hec_and_otlp_mtls_values_validate(tmp_path: Path) -> None:
    files: dict[str, Path] = {}
    for name in ("o11y", "hec", "hec-ca", "hec-cert", "hec-key", "otlp-ca", "otlp-cert", "otlp-key"):
        path = tmp_path / name
        path.write_text(f"{name}-value", encoding="utf-8")
        path.chmod(0o600)
        files[name] = path
    output_dir = tmp_path / "mtls"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "mtls",
        "--enable-logs",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-hec-token-file",
        str(files["hec"]),
        "--platform-metrics-enabled",
        "true",
        "--platform-metrics-index",
        "metrics",
        "--platform-hec-ca-file",
        str(files["hec-ca"]),
        "--platform-hec-client-cert-file",
        str(files["hec-cert"]),
        "--platform-hec-client-key-file",
        str(files["hec-key"]),
        "--platform-otlp-endpoint",
        "otlp.example:4317",
        "--platform-otlp-ca-file",
        str(files["otlp-ca"]),
        "--platform-otlp-client-cert-file",
        str(files["otlp-cert"]),
        "--platform-otlp-client-key-file",
        str(files["otlp-key"]),
        "--o11y-token-file",
        str(files["o11y"]),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    validation = run_validate("--check-k8s", "--output-dir", str(output_dir))
    assert validation.returncode == 0, validation.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert '    clientCert: "__FILE_BACKED__"' in values
    assert '  clientCert: "__FILE_BACKED__"' in values


def test_diagnostic_redactor_removes_prefixed_json_and_authorization_secrets(tmp_path: Path) -> None:
    output_dir = tmp_path / "redactor"
    result = run_setup("--render-linux", "--realm", "us0", "--output-dir", str(output_dir))
    assert result.returncode == 0, result.stdout
    payload = "\n".join(
        (
            "SPLUNK_ACCESS_TOKEN=LEAK1",
            "client_secret=LEAK2",
            "splunk_hec_token: LEAK3",
            "Authorization: Bearer LEAK4",
            "Proxy-Authorization: Basic LEAK5",
            '{"access_token":"LEAK6"}',
        )
    )
    redacted = subprocess.run(
        ["python3", str(output_dir / "linux/redact-stream.py")],
        input=payload,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert redacted.returncode == 0, redacted.stdout
    assert "LEAK" not in redacted.stdout
    assert "__REDACTED__" in redacted.stdout


def test_extra_values_secret_indirection_fails_without_retaining_snapshot(tmp_path: Path) -> None:
    overlay = tmp_path / "unsafe.yaml"
    sentinel = "INLINE_SECRET_VALUE"
    overlay.write_text(
        "agent:\n"
        "  extraEnvs:\n"
        "    - name: FOO\n"
        f"      value: {sentinel}\n"
        "  config:\n"
        "    exporters:\n"
        "      otlphttp/custom:\n"
        "        headers:\n"
        "          Authorization: ${env:FOO}\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "unsafe-render"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "unsafe",
        "--extra-values-file",
        str(overlay),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode != 0
    assert sentinel not in result.stdout
    assert not (output_dir / "k8s").exists()


def test_hec_explicit_allowlist_must_cover_every_effective_index(tmp_path: Path) -> None:
    result = run_setup(
        "--render-k8s",
        "--render-platform-hec-helper",
        "--realm",
        "us0",
        "--cluster-name",
        "indexes",
        "--enable-logs",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-metrics-enabled",
        "true",
        "--platform-metrics-index",
        "metrics",
        "--hec-allowed-indexes",
        "k8s_logs",
        "--output-dir",
        str(tmp_path / "indexes"),
    )
    assert result.returncode != 0
    assert "every effective destination index" in result.stdout
    assert "metrics" in result.stdout


def test_legacy_managed_hec_token_is_migrated_before_target_cleanup(tmp_path: Path) -> None:
    output_dir = tmp_path / "legacy"
    legacy = output_dir / "platform-hec/.splunk_platform_hec_token"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("ONE_TIME_TOKEN", encoding="utf-8")
    legacy.chmod(0o600)

    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    migrated = output_dir / ".secrets/splunk_platform_hec_token"
    assert migrated.read_text(encoding="utf-8") == "ONE_TIME_TOKEN"
    assert migrated.stat().st_mode & 0o777 == 0o600
    assert migrated.parent.stat().st_mode & 0o777 == 0o700
    assert not legacy.exists()


def test_kubernetes_secondary_features_require_chart_supported_destination(tmp_path: Path) -> None:
    cases = (
        (("--enable-events",), "events/entities require"),
        (("--k8s-entities-enabled", "true"), "Kubernetes entities require"),
    )
    for index, (flags, expected) in enumerate(cases):
        output_dir = tmp_path / f"secondary-{index}"
        result = run_setup(
            "--render-k8s",
            "--realm",
            "us0",
            "--cluster-name",
            "secondary",
            "--disable-metrics",
            "--disable-traces",
            *flags,
            "--output-dir",
            str(output_dir),
        )
        assert result.returncode != 0
        assert expected in result.stdout
        assert not (output_dir / "k8s").exists()


def test_kubernetes_invalid_names_fail_before_render(tmp_path: Path) -> None:

    invalid_name = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "bad-name",
        "--release-name",
        "Bad_Name",
        "--output-dir",
        str(tmp_path / "bad-name"),
    )
    assert invalid_name.returncode != 0
    assert "lowercase DNS label" in invalid_name.stdout


def test_status_covers_optional_subcharts_and_windows_fips_is_renderable(tmp_path: Path) -> None:
    output_dir = tmp_path / "optional"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "optional",
        "--windows-nodes",
        "--fips-enabled",
        "true",
        "--target-allocator-enabled",
        "true",
        "--o11y-token-file",
        str(tmp_path / "unused.token"),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    status = (output_dir / "k8s/status.sh").read_text(encoding="utf-8")
    assert 'repository: "quay.io/signalfx/splunk-otel-collector-fips"' in values
    assert "targetallocator-ta" in status
    assert 'app.kubernetes.io/instance="${release_name}"' in status


def test_release_versions_must_be_exact_pins(tmp_path: Path) -> None:
    cases = (
        ("--render-k8s", "--chart-version", ""),
        ("--render-k8s", "--chart-version", "latest"),
        ("--render-k8s", "--chart-version", ">=0.154.0"),
        ("--render-linux", "--collector-version", ""),
        ("--render-linux", "--collector-version", "latest"),
        ("--render-linux", "--collector-version", "0.154.x"),
    )
    for index, (target, option, value) in enumerate(cases):
        result = run_setup(
            target,
            "--realm",
            "us0",
            option,
            value,
            "--cluster-name",
            "pinned" if target == "--render-k8s" else "",
            "--output-dir",
            str(tmp_path / f"pin-{index}"),
        )
        assert result.returncode != 0
        if option == "--collector-version":
            assert "exact numeric X.Y.Z" in result.stdout
        else:
            assert "exact semantic version" in result.stdout

    instrumentation = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--enable-autoinstrumentation",
        "--instrumentation-mode",
        "systemd",
        "--instrumentation-version",
        "latest",
        "--output-dir",
        str(tmp_path / "instrumentation-pin"),
    )
    assert instrumentation.returncode != 0
    assert "exact semantic" in instrumentation.stdout


def test_linux_executable_packets_reject_exact_but_unaudited_versions(
    tmp_path: Path,
) -> None:
    cases = (
        (
            "collector",
            ("--collector-version", "0.155.0"),
            "--collector-version 0.154.2",
        ),
        (
            "instrumentation",
            (
                "--enable-autoinstrumentation",
                "--instrumentation-mode",
                "systemd",
                "--instrumentation-version",
                "0.155.0",
            ),
            "--instrumentation-version 0.154.2",
        ),
        (
            "obi",
            ("--enable-obi", "--obi-version", "v0.7.0"),
            "--obi-version v0.6.0",
        ),
    )
    for name, flags, expected_pin in cases:
        result = run_setup(
            "--render-linux",
            "--realm",
            "us0",
            *flags,
            "--output-dir",
            str(tmp_path / name),
        )
        assert result.returncode != 0
        assert "executable Linux packets are restricted" in result.stdout
        assert expected_pin in result.stdout

    accepted = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--enable-autoinstrumentation",
        "--instrumentation-mode",
        "systemd",
        "--instrumentation-version",
        "0.154.2",
        "--collector-version",
        "0.154.2",
        "--enable-obi",
        "--obi-version",
        "0.6.0",
        "--output-dir",
        str(tmp_path / "audited"),
    )
    assert accepted.returncode == 0, accepted.stdout


def test_linux_installer_mirror_must_retain_audited_digest(tmp_path: Path) -> None:
    rejected = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--installer-url",
        "https://mirror.example.test/install.sh",
        "--installer-sha256",
        "0" * 64,
        "--output-dir",
        str(tmp_path / "rejected"),
    )
    assert rejected.returncode != 0
    assert "executable Linux packets require the audited installer SHA-256" in rejected.stdout

    accepted_dir = tmp_path / "accepted"
    accepted = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--installer-url",
        "https://mirror.example.test/install.sh",
        "--installer-sha256",
        "16f2c34ad1a91bf0817f5675eca3d705af5385377e87fda23537808efd5f7e29",
        "--output-dir",
        str(accepted_dir),
    )
    assert accepted.returncode == 0, accepted.stdout
    install = (accepted_dir / "linux/install-local.sh").read_text(encoding="utf-8")
    assert "INSTALLER_URL=https://mirror.example.test/install.sh" in install
    assert (
        "INSTALLER_SHA256=16f2c34ad1a91bf0817f5675eca3d705af5385377e87fda23537808efd5f7e29"
        in install
    )


def test_setup_reports_orchestration_python_minimum_before_render(
    tmp_path: Path,
) -> None:
    old_python = tmp_path / "python3.8"
    old_python.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = --version ]; then printf '%s\\n' 'Python 3.8.18'; fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    old_python.chmod(0o755)
    rejected = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--output-dir",
        str(tmp_path / "rendered"),
        env={"PYTHON": str(old_python)},
    )
    assert rejected.returncode != 0
    assert "setup/render orchestration requires Python 3.9 or newer" in rejected.stdout
    assert "generated Linux target helpers require only Python 3.6+" in rejected.stdout
    assert "Python 3.8.18" in rejected.stdout

    help_result = run_setup("--help", env={"PYTHON": str(old_python)})
    assert help_result.returncode == 0, help_result.stdout
    assert "Splunk Observability OTel Collector setup" in help_result.stdout


def test_root_rerender_removes_stale_derived_hec_packet(tmp_path: Path) -> None:
    output_dir = tmp_path / "stale-hec"
    first = run_setup(
        "--render-platform-hec-helper",
        "--realm",
        "us0",
        "--output-dir",
        str(output_dir),
    )
    assert first.returncode == 0, first.stdout
    stale = output_dir / "platform-hec-service-rendered/hec-service/actionable.conf"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")

    second = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--output-dir",
        str(output_dir),
    )
    assert second.returncode == 0, second.stdout
    assert not (output_dir / "platform-hec-service-rendered").exists()


def test_persistent_queue_path_and_linux_accounts_are_shell_safe(tmp_path: Path) -> None:
    for index, path in enumerate(("relative/path", "/", "/var/../tmp/queue", "/var//queue", "/var/queue path")):
        result = run_setup(
            "--render-k8s",
            "--realm",
            "us0",
            "--cluster-name",
            "queue-path",
            "--enable-logs",
            "--platform-hec-url",
            "https://splunk.example:8088/services/collector/event",
            "--platform-hec-token-file",
            str(tmp_path / "missing-hec-token"),
            "--platform-persistent-queue-enabled",
            "true",
            "--platform-persistent-queue-path",
            path,
            "--output-dir",
            str(tmp_path / f"queue-{index}"),
        )
        assert result.returncode != 0
        assert "normalized absolute Linux path" in result.stdout

    gateway_queue = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "gateway-queue",
        "--enable-logs",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-hec-token-file",
        str(tmp_path / "missing-hec-token"),
        "--enable-platform-persistent-queue",
        "--gateway",
        "--output-dir",
        str(tmp_path / "gateway-queue"),
    )
    assert gateway_queue.returncode != 0
    assert "gateway disabled" in gateway_queue.stdout

    fargate_queue = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--distribution",
        "eks/fargate",
        "--cluster-name",
        "fargate-queue",
        "--enable-logs",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-hec-token-file",
        str(tmp_path / "missing-hec-token"),
        "--enable-platform-persistent-queue",
        "--output-dir",
        str(tmp_path / "fargate-queue"),
    )
    assert fargate_queue.returncode != 0
    assert "gateway disabled" in fargate_queue.stdout

    for index, option_and_value in enumerate(
        (("--service-user", "1bad"), ("--service-user", "otel user"), ("--service-group", "BadGroup"))
    ):
        option, value = option_and_value
        result = run_setup(
            "--render-linux",
            "--realm",
            "us0",
            option,
            value,
            "--output-dir",
            str(tmp_path / f"account-{index}"),
        )
        assert result.returncode != 0
        assert "lowercase Linux account name" in result.stdout

    for index, memory in enumerate(("0", "-1", "512 MiB", "not-a-number")):
        result = run_setup(
            "--render-linux",
            "--realm",
            "us0",
            "--memory-mib",
            memory,
            "--output-dir",
            str(tmp_path / f"memory-{index}"),
        )
        assert result.returncode != 0
        assert "positive integer" in result.stdout


def test_https_otlp_rejects_plaintext_insecure_mode(tmp_path: Path) -> None:
    result = run_setup(
        "--render-k8s",
        "--cluster-name",
        "otlp-tls",
        "--disable-metrics",
        "--disable-traces",
        "--enable-logs",
        "--platform-otlp-endpoint",
        "https://otlp.example:4318",
        "--platform-otlp-protocol",
        "http",
        "--platform-otlp-insecure",
        "true",
        "--output-dir",
        str(tmp_path / "otlp-tls"),
    )
    assert result.returncode != 0
    assert "HTTPS OTLP cannot be combined" in result.stdout


def test_linux_health_follows_bind_and_obi_is_exactly_pinned(tmp_path: Path) -> None:
    for index, (listen, expected_health) in enumerate(
        (
            ("10.0.0.5", "http://10.0.0.5:13133/"),
            ("0.0.0.0", "http://127.0.0.1:13133/"),
            ("::", "http://[::1]:13133/"),
            ("2001:db8::5", "http://[2001:db8::5]:13133/"),
        )
    ):
        output_dir = tmp_path / f"health-{index}"
        result = run_setup(
            "--render-linux",
            "--realm",
            "us0",
            "--listen-interface",
            listen,
            "--enable-obi",
            "--output-dir",
            str(output_dir),
        )
        assert result.returncode == 0, result.stdout
        status = (output_dir / "linux/status-local.sh").read_text(encoding="utf-8")
        doctor = (output_dir / "linux/doctor-local.sh").read_text(encoding="utf-8")
        install = (output_dir / "linux/install-local.sh").read_text(encoding="utf-8")
        assert expected_health in status
        assert expected_health in doctor
        assert "--obi-version\n    v0.6.0" in install

    moving_obi = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--enable-obi",
        "--obi-version",
        "latest",
        "--output-dir",
        str(tmp_path / "moving-obi"),
    )
    assert moving_obi.returncode != 0
    assert "exact semantic --obi-version" in moving_obi.stdout


def test_linux_obi_binary_uses_audited_architecture_digests(tmp_path: Path) -> None:
    obi_dir = tmp_path / "obi-bin"
    obi_dir.mkdir()
    obi = obi_dir / "obi"
    obi.write_text("#!/bin/sh\nprintf '%s\\n' 'obi 0.6.0'\n", encoding="utf-8")
    obi.chmod(0o755)
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--enable-obi",
        "--obi-install-dir",
        str(obi_dir),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    local_install = (output_dir / "linux/install-local.sh").read_text(encoding="utf-8")
    remote_install = (output_dir / "linux/remote-install.sh").read_text(encoding="utf-8")
    status = (output_dir / "linux/status-local.sh").read_text(encoding="utf-8")
    for digest in (
        "3667f3a040b9125eeac88c8a8f2fab67e45f48ade259461d30a09dc9f4ea839e",
        "72903f7dda88d9ad70263d7c749064ede26aaa8040490807c518c62dc581aa6b",
    ):
        assert digest in local_install
        assert digest in remote_install
        assert digest in status
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["linux"]["obi_binary_sha256_by_arch"]["amd64"] == (
        "3667f3a040b9125eeac88c8a8f2fab67e45f48ade259461d30a09dc9f4ea839e"
    )
    assert metadata["audited_versions"]["linux_obi_archive_sha256"]["arm64"] == (
        "4b31902024f3e98dd93f3a28efd45a07c189f1943bb36d75a2c34dc1e0aff249"
    )

    fake_bin = tmp_path / "status-bin"
    fake_bin.mkdir()
    for command in ("systemctl", "journalctl", "curl"):
        shim = fake_bin / command
        shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        shim.chmod(0o755)
    id_shim = fake_bin / "id"
    id_shim.write_text("#!/bin/sh\nprintf '%s\\n' 0\n", encoding="utf-8")
    id_shim.chmod(0o755)
    run_env = os.environ.copy()
    run_env["PATH"] = f"{fake_bin}{os.pathsep}{run_env['PATH']}"
    mismatch = subprocess.run(
        ["bash", str(output_dir / "linux/status-local.sh")],
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert mismatch.returncode != 0
    assert "failed the audited architecture-specific SHA-256 check" in mismatch.stdout


def test_linux_persisted_installer_values_reject_directive_injection(tmp_path: Path) -> None:
    unsafe_cases = (
        ("--metrics-exporter", 'otlp\nDefaultEnvironment="INJECTED=1"'),
        ("--logs-exporter", 'otlp" "INJECTED=1'),
        ("--deployment-environment", 'prod"\nDefaultEnvironment="INJECTED=1'),
        ("--service-name", "bad service"),
        ("--instrumentation-sdks", "java,node,evil"),
        ("--godebug", "fips140=on\nINJECTED=1"),
        ("--npm-path", "relative/npm"),
        ("--obi-install-dir", "/usr/local/../tmp"),
    )
    for index, (option, value) in enumerate(unsafe_cases):
        result = run_setup(
            "--render-linux",
            "--realm",
            "us0",
            "--enable-autoinstrumentation",
            "--instrumentation-mode",
            "systemd",
            "--enable-obi",
            option,
            value,
            "--output-dir",
            str(tmp_path / f"unsafe-persisted-{index}"),
        )
        assert result.returncode != 0

    relative_config = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--collector-config",
        "relative.yaml",
        "--linux-health-endpoint",
        "http://127.0.0.1:13133/",
        "--output-dir",
        str(tmp_path / "relative-config"),
    )
    assert relative_config.returncode != 0
    assert "normalized absolute target-host Linux path" in relative_config.stdout

    for index, value in enumerate(
        (
            'https://ingest.example/evil path',
            'https://ingest.example/"quoted',
            "https://ingest.example/\\escaped",
        )
    ):
        unsafe_url = run_setup(
            "--render-linux",
            "--realm",
            "us0",
            "--ingest-url",
            value,
            "--output-dir",
            str(tmp_path / f"unsafe-url-{index}"),
        )
        assert unsafe_url.returncode != 0
        assert "without whitespace, quotes, backslashes" in unsafe_url.stdout

    normalized_dir = tmp_path / "normalized-url"
    normalized = run_setup(
        "--render-linux",
        "--realm",
        "us0",
        "--api-url",
        "https://api.example/",
        "--ingest-url",
        "https://ingest.example/",
        "--output-dir",
        str(normalized_dir),
    )
    assert normalized.returncode == 0, normalized.stdout
    install = (normalized_dir / "linux/install-local.sh").read_text(encoding="utf-8")
    remote = (normalized_dir / "linux/remote-install.sh").read_text(encoding="utf-8")
    assert "https://api.example/\n" not in install
    assert "https://ingest.example//v2/event" not in install + remote
    assert "INGEST_URL=https://ingest.example" in install


def test_platform_only_kubernetes_events_route_without_o11y_event_export(tmp_path: Path) -> None:
    output_dir = tmp_path / "platform-events"
    result = run_setup(
        "--render-k8s",
        "--cluster-name",
        "platform-events",
        "--disable-metrics",
        "--disable-traces",
        "--disable-agent",
        "--platform-logs-enabled",
        "true",
        "--enable-events",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-hec-token-file",
        str(tmp_path / "platform.token"),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert "  eventsEnabled: true" in values
    assert "  sendK8sEventsToSplunkO11y: false" in values
    assert "logsCollection:\n  containers:\n    enabled: false" in values
    assert "agent:\n  enabled: false" in values
    assert "clusterReceiver:\n  enabled: true" in values
    assert "  logsEnabled: true" in values
    assert metadata["kubernetes"]["events_to_platform"] is True
    assert metadata["kubernetes"]["events_to_observability"] is False
    assert metadata["kubernetes"]["platform_logs_pipeline_explicit"] is True
    assert metadata["kubernetes"]["container_logs_enabled"] is False


def test_platform_logs_pipeline_supports_extra_file_logs_without_container_collection(
    tmp_path: Path,
) -> None:
    overlay = tmp_path / "extra-file-logs.yaml"
    overlay.write_text(
        "logsCollection:\n"
        "  extraFileLogs:\n"
        "    filelog/audit:\n"
        "      include:\n"
        "        - /var/log/audit/*.log\n"
        "      start_at: end\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "extra-file-logs"
    result = run_setup(
        "--render-k8s",
        "--cluster-name",
        "extra-file-logs",
        "--disable-metrics",
        "--disable-traces",
        "--platform-logs-enabled",
        "true",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-hec-token-file",
        str(tmp_path / "platform.token"),
        "--extra-values-file",
        str(overlay),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    copied = (output_dir / "k8s/extra-values-1.yaml").read_text(encoding="utf-8")
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert "  logsEnabled: true" in values
    assert "logsCollection:\n  containers:\n    enabled: false" in values
    assert "  journald:\n    enabled: false" in values
    assert "extraFileLogs" in copied
    assert metadata["kubernetes"]["platform_logs_pipeline_explicit"] is True
    assert metadata["kubernetes"]["container_logs_enabled"] is False
    assert metadata["kubernetes"]["journald_enabled"] is False
    assert "without a typed built-in log source" in result.stdout


def test_platform_only_target_allocator_uses_platform_metrics(tmp_path: Path) -> None:
    output_dir = tmp_path / "platform-target-allocator"
    result = run_setup(
        "--render-k8s",
        "--cluster-name",
        "platform-target-allocator",
        "--disable-metrics",
        "--disable-traces",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-hec-token-file",
        str(tmp_path / "platform.token"),
        "--platform-metrics-enabled",
        "true",
        "--platform-metrics-index",
        "metrics",
        "--target-allocator-enabled",
        "true",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert "targetallocator:" in values
    assert "  enabled: true" in values
    assert "  metricsEnabled: true" in values


def test_k8s_object_collection_is_explicit_typed_and_rbac_guarded(tmp_path: Path) -> None:
    output_dir = tmp_path / "objects"
    object_file = tmp_path / "objects.yaml"
    object_file.write_text(
        "- name: pods\n"
        "  mode: pull\n"
        "  namespaces:\n"
        "    - default\n"
        "  interval: 6h\n"
        "- name: deployments\n"
        "  group: apps\n"
        "  mode: watch\n",
        encoding="utf-8",
    )
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "objects",
        "--k8s-objects-file",
        str(object_file),
        "--accept-cluster-wide-object-rbac",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert "  k8sObjects:" in values
    assert '      name: "pods"' in values
    assert '      name: "deployments"' in values
    assert '        - "apps"' in values
    assert "  sendK8sEventsToSplunkO11y: true" in values
    assert metadata["kubernetes"]["objects_to_observability"] is True
    assert metadata["kubernetes"]["cluster_wide_object_rbac_accepted"] is True

    platform_dir = tmp_path / "objects-platform"
    platform_result = run_setup(
        "--render-k8s",
        "--cluster-name",
        "objects-platform",
        "--disable-metrics",
        "--disable-traces",
        "--disable-agent",
        "--platform-logs-enabled",
        "true",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-hec-token-file",
        str(tmp_path / "platform.token"),
        "--k8s-objects-file",
        str(object_file),
        "--accept-cluster-wide-object-rbac",
        "--output-dir",
        str(platform_dir),
    )
    assert platform_result.returncode == 0, platform_result.stdout
    platform_values = (platform_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    platform_metadata = json.loads(
        (platform_dir / "metadata.json").read_text(encoding="utf-8")
    )
    assert "splunkObservability:" not in platform_values
    assert "  sendK8sEventsToSplunkO11y: false" in platform_values
    assert "logsCollection:\n  containers:\n    enabled: false" in platform_values
    assert "agent:\n  enabled: false" in platform_values
    assert platform_metadata["kubernetes"]["objects_to_platform"] is True
    assert platform_metadata["kubernetes"]["objects_to_observability"] is False

    default_dir = tmp_path / "objects-default"
    default_result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "objects-default",
        "--output-dir",
        str(default_dir),
    )
    assert default_result.returncode == 0, default_result.stdout
    default_values = (default_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert "  k8sObjects: []" in default_values
    assert "  customRules: []" in default_values

    missing_acceptance = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "objects-refused",
        "--k8s-objects-file",
        str(object_file),
        "--output-dir",
        str(tmp_path / "objects-refused"),
    )
    assert missing_acceptance.returncode != 0
    assert "accept-cluster-wide-object-rbac" in missing_acceptance.stdout

    sensitive = tmp_path / "sensitive-objects.yaml"
    sensitive.write_text("- name: secrets\n  mode: watch\n", encoding="utf-8")
    sensitive_result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "sensitive",
        "--k8s-objects-file",
        str(sensitive),
        "--accept-cluster-wide-object-rbac",
        "--output-dir",
        str(tmp_path / "sensitive"),
    )
    assert sensitive_result.returncode != 0
    assert "may contain credentials" in sensitive_result.stdout


def test_metrics_features_and_k8s_obi_require_matching_destinations(tmp_path: Path) -> None:
    metrics_features = ("--enable-discovery", "--enable-prometheus-autodetect", "--enable-istio-autodetect")
    for index, option in enumerate(metrics_features):
        result = run_setup(
            "--render-k8s",
            "--cluster-name",
            "no-metrics",
            "--disable-metrics",
            "--disable-traces",
            "--enable-logs",
            "--platform-otlp-endpoint",
            "https://otlp.example:4318",
            "--platform-otlp-protocol",
            "http",
            option,
            "--output-dir",
            str(tmp_path / f"no-metrics-{index}"),
        )
        assert result.returncode != 0
        assert "metrics pipeline" in result.stdout

    obi = run_setup(
        "--render-k8s",
        "--cluster-name",
        "no-traces",
        "--disable-metrics",
        "--disable-traces",
        "--enable-logs",
        "--platform-otlp-endpoint",
        "https://otlp.example:4318",
        "--platform-otlp-protocol",
        "http",
        "--enable-obi",
        "--output-dir",
        str(tmp_path / "no-traces"),
    )
    assert obi.returncode != 0
    assert "effective trace destination" in obi.stdout


def test_kubernetes_journald_is_typed_and_topology_guarded(tmp_path: Path) -> None:
    token = tmp_path / "hec.token"
    token.write_text("base64Safe+/=_~-", encoding="utf-8")
    token.chmod(0o600)
    output_dir = tmp_path / "journald"
    result = run_setup(
        "--render-k8s",
        "--cluster-name",
        "journald-cluster",
        "--disable-metrics",
        "--disable-traces",
        "--enable-journald",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-hec-token-file",
        str(token),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert "logsCollection:\n  containers:\n    enabled: false\n  journald:\n    enabled: true" in values
    assert metadata["kubernetes"]["container_logs_enabled"] is False
    assert metadata["kubernetes"]["journald_enabled"] is True
    assert metadata["signals"]["journald"] is True

    common = (
        "--render-k8s",
        "--cluster-name",
        "journald-refused",
        "--disable-metrics",
        "--disable-traces",
        "--enable-journald",
        "--platform-otlp-endpoint",
        "otlp.example:4317",
    )
    invalid_topologies = (
        ("--distribution", "eks/fargate"),
        ("--distribution", "gke/autopilot"),
        ("--windows-nodes",),
        ("--agent-enabled", "false"),
    )
    for index, topology in enumerate(invalid_topologies):
        refused = run_setup(
            *common,
            *topology,
            "--output-dir",
            str(tmp_path / f"journald-refused-{index}"),
        )
        assert refused.returncode != 0
        assert "journald" in refused.stdout.lower()


def test_kubernetes_values_and_secret_revision_integrity_are_fail_closed(tmp_path: Path) -> None:
    output_dir = tmp_path / "integrity"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "integrity-cluster",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    verify = output_dir / "k8s/verify-overlays.sh"
    create_secret = (output_dir / "k8s/create-secret.sh").read_text(encoding="utf-8")
    assert 'mktemp "${script_dir}/.secret-revision-values.XXXXXX"' in create_secret
    assert ".secret-revision-values.yaml.tmp" not in create_secret
    assert subprocess.run(["bash", str(verify)], check=False).returncode == 0

    values = output_dir / "k8s/values.yaml"
    values.write_text(values.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    changed = subprocess.run(
        ["bash", str(verify)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert changed.returncode != 0
    assert "changed after policy validation" in changed.stdout

    rerender = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "integrity-cluster",
        "--output-dir",
        str(output_dir),
    )
    assert rerender.returncode == 0, rerender.stdout
    values = output_dir / "k8s/values.yaml"
    copied_values = tmp_path / "copied-values.yaml"
    copied_values.write_bytes(values.read_bytes())
    values.unlink()
    values.symlink_to(copied_values)
    symlinked = subprocess.run(
        ["bash", str(verify)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert symlinked.returncode != 0
    assert "symlink" in symlinked.stdout

    rerender = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "integrity-cluster",
        "--output-dir",
        str(output_dir),
    )
    assert rerender.returncode == 0, rerender.stdout
    revision = output_dir / "k8s/secret-revision-values.yaml"
    payload = json.loads(revision.read_text(encoding="utf-8"))
    payload["agent"]["unexpected"] = True
    revision.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    changed_revision = subprocess.run(
        ["bash", str(verify)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert changed_revision.returncode != 0
    assert "unexpected component schema" in changed_revision.stdout

    payload["agent"].pop("unexpected")
    revision.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    noncanonical_revision = subprocess.run(
        ["bash", str(verify)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert noncanonical_revision.returncode != 0
    assert "exact canonical JSON encoding" in noncanonical_revision.stdout


def test_kubernetes_token_validation_rejects_nul_newline_and_oversize(tmp_path: Path) -> None:
    token = tmp_path / "hec.token"
    token.write_bytes(b"base64Safe+/=_~-")
    token.chmod(0o600)
    output_dir = tmp_path / "token-validation"
    result = run_setup(
        "--render-k8s",
        "--cluster-name",
        "token-cluster",
        "--disable-metrics",
        "--disable-traces",
        "--enable-logs",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-hec-token-file",
        str(token),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    validator = output_dir / "k8s/validate-secrets.sh"
    valid = subprocess.run(
        ["bash", str(validator)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert valid.returncode == 0, valid.stdout

    for value in (b"bad\x00token", b"bad\ntoken", b"x" * 16385):
        token.write_bytes(value)
        token.chmod(0o600)
        invalid = subprocess.run(
            ["bash", str(validator)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert invalid.returncode != 0
        assert "NUL or newline" in invalid.stdout or "16384" in invalid.stdout


def test_kubernetes_tls_validates_every_ca_and_client_key_match(tmp_path: Path) -> None:
    if shutil.which("openssl") is None:
        return
    cert_a = tmp_path / "cert-a.pem"
    cert_b = tmp_path / "cert-b.pem"
    key_a = tmp_path / "key-a.pem"
    key_b = tmp_path / "key-b.pem"
    for name, cert, key in (("a", cert_a, key_a), ("b", cert_b, key_b)):
        generated = subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-nodes",
                "-subj",
                f"/CN={name}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        assert generated.returncode == 0
        key.chmod(0o600)
    ca_bundle = tmp_path / "ca.pem"
    ca_bundle.write_bytes(cert_a.read_bytes() + cert_b.read_bytes())
    token = tmp_path / "hec.token"
    token.write_text("hec-token", encoding="utf-8")
    token.chmod(0o600)
    output_dir = tmp_path / "tls-validation"
    result = run_setup(
        "--render-k8s",
        "--cluster-name",
        "tls-cluster",
        "--disable-metrics",
        "--disable-traces",
        "--enable-logs",
        "--platform-hec-url",
        "https://splunk.example:8088/services/collector/event",
        "--platform-hec-token-file",
        str(token),
        "--platform-hec-ca-file",
        str(ca_bundle),
        "--platform-hec-client-cert-file",
        str(cert_a),
        "--platform-hec-client-key-file",
        str(key_a),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    validator = output_dir / "k8s/validate-secrets.sh"
    valid = subprocess.run(
        ["bash", str(validator)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert valid.returncode == 0, valid.stdout
    assert "certificate 1 expires within 30 days" in valid.stdout
    assert "certificate 2 expires within 30 days" in valid.stdout

    key_a.write_bytes(key_b.read_bytes())
    key_a.chmod(0o600)
    mismatch = subprocess.run(
        ["bash", str(validator)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert mismatch.returncode != 0
    assert "certificate and private key do not match" in mismatch.stdout

    key_a.write_text(
        "-----BEGIN ENCRYPTED PRIVATE KEY-----\nZmFrZQ==\n-----END ENCRYPTED PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    key_a.chmod(0o600)
    encrypted = subprocess.run(
        ["bash", str(validator)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert encrypted.returncode != 0
    assert "client key is encrypted" in encrypted.stdout


def test_kubernetes_owned_object_cleanup_is_confirmation_and_ownership_gated(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "ownership"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "ownership-cluster",
        "--render-priority-class",
        "--priority-class-name",
        "splunk-otel-priority",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    k8s = output_dir / "k8s"
    for name in (
        "create-secret.sh",
        "cleanup-secret.sh",
        "priority-class.sh",
        "cleanup-priority-class.sh",
    ):
        text = (k8s / name).read_text(encoding="utf-8")
        assert "splunk.com/owner-skill" in text
        assert "splunk.com/release-name" in text
        assert "splunk.com/release-namespace" in text
        assert "--ignore-not-found" in text
    assert "SPLUNK_OTEL_CONFIRM_SECRET_DELETE" in (k8s / "cleanup-secret.sh").read_text(
        encoding="utf-8"
    )
    assert "SPLUNK_OTEL_CONFIRM_PRIORITY_CLASS_DELETE" in (
        k8s / "cleanup-priority-class.sh"
    ).read_text(encoding="utf-8")
    assert "k8s-object-preconditions.py" in (k8s / "create-secret.sh").read_text(
        encoding="utf-8"
    )
    assert "kubectl replace -f -" in (k8s / "create-secret.sh").read_text(
        encoding="utf-8"
    )
    assert "apply --server-side" not in (k8s / "create-secret.sh").read_text(
        encoding="utf-8"
    )

    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "splunk-otel-collector-splunk", "namespace": "splunk-otel"},
        "data": {"mock": "bW9jaw=="},
    }
    ownership_filter = k8s / "add-secret-ownership.py"
    owned_manifest = subprocess.run(
        [
            "python3",
            str(ownership_filter),
            "splunk-observability-otel-collector-setup",
            "splunk-otel-collector",
            "splunk-otel",
            "splunk-otel-collector-splunk",
        ],
        input=json.dumps(manifest),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert owned_manifest.returncode == 0, owned_manifest.stdout
    assert json.loads(owned_manifest.stdout)["metadata"]["annotations"][
        "splunk.com/owner-skill"
    ] == "splunk-observability-otel-collector-setup"
    manifest["metadata"]["namespace"] = "other"
    wrong_namespace = subprocess.run(
        [
            "python3",
            str(ownership_filter),
            "splunk-observability-otel-collector-setup",
            "splunk-otel-collector",
            "splunk-otel",
            "splunk-otel-collector-splunk",
        ],
        input=json.dumps(manifest),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert wrong_namespace.returncode != 0

    no_confirmation = subprocess.run(
        ["bash", str(k8s / "cleanup-secret.sh")],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert no_confirmation.returncode != 0
    assert "SPLUNK_OTEL_CONFIRM_SECRET_DELETE=yes" in no_confirmation.stdout

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    delete_marker = tmp_path / "deleted"
    delete_body = tmp_path / "delete-options.json"
    kubectl = fake_bin / "kubectl"
    kubectl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "case \"$*\" in\n"
        "  *'config current-context'*) echo audit-context ;;\n"
        "  *'auth can-i'*) echo yes ;;\n"
        "  *'get secret'*'go-template'*) printf '%s\\n' \"${MOCK_OWNERSHIP}\" ;;\n"
        "  *'get secret'*) exit 0 ;;\n"
        "  *'delete --raw=/api/v1/namespaces/'*'/secrets/'*) cat > \"${MOCK_DELETE_BODY}\"; : > \"${MOCK_DELETE_MARKER}\" ;;\n"
        "  *'delete secret'*) : > \"${MOCK_DELETE_MARKER}\" ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "SPLUNK_OTEL_CONFIRM_SECRET_DELETE": "yes",
            "MOCK_DELETE_MARKER": str(delete_marker),
            "MOCK_DELETE_BODY": str(delete_body),
            "MOCK_OWNERSHIP": "foreign\tsplunk-otel-collector\tsplunk-otel\tuid-foreign\t41",
        }
    )
    unowned = subprocess.run(
        ["bash", str(k8s / "cleanup-secret.sh")],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert unowned.returncode != 0
    assert "refusing to delete an unowned Collector Secret" in unowned.stdout
    assert not delete_marker.exists()

    env["MOCK_OWNERSHIP"] = (
        "splunk-observability-otel-collector-setup"
        "\tsplunk-otel-collector\tsplunk-otel\tuid-owned\t42"
    )
    owned = subprocess.run(
        ["bash", str(k8s / "cleanup-secret.sh")],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert owned.returncode == 0, owned.stdout
    assert delete_marker.is_file()
    delete_options = json.loads(delete_body.read_text(encoding="utf-8"))
    assert delete_options["preconditions"] == {
        "uid": "uid-owned",
        "resourceVersion": "42",
    }


def test_kubernetes_destructive_helpers_display_the_explicit_target_context(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "explicit-context"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "context-cluster",
        "--kube-context",
        "reviewed-context",
        "--render-priority-class",
        "--priority-class-name",
        "splunk-otel-priority",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    for name in ("cleanup-secret.sh", "cleanup-priority-class.sh", "uninstall.sh"):
        text = (output_dir / "k8s" / name).read_text(encoding="utf-8")
        assert "Kubernetes context: reviewed-context" in text
        assert "--context reviewed-context config current-context" not in text


def test_eks_auto_mode_records_pod_identity_boundaries(tmp_path: Path) -> None:
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--distribution",
        "eks/auto-mode",
        "--gateway-enabled",
        "true",
        "--dry-run",
        "--json",
        "--output-dir",
        str(tmp_path / "eks-auto"),
    )
    assert result.returncode == 0, result.stdout
    warnings = "\n".join(json.loads(result.stdout)["warnings"])
    assert "gateway deployment requires configured EKS Pod Identity" in warnings
    assert "host networking" in warnings


def test_network_explorer_profile_enforces_one_gateway_and_renders_handoff(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "network-explorer"
    result = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "network-cluster",
        "--enable-network-explorer",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 0, result.stdout
    values = (output_dir / "k8s/values.yaml").read_text(encoding="utf-8")
    assert "gateway:\n  enabled: true\n  replicaCount: 1" in values
    handoff = output_dir / "k8s/network-explorer-handoff.md"
    assert handoff.is_file()
    handoff_text = handoff.read_text(encoding="utf-8")
    assert "outside Splunk support" in handoff_text
    assert "Kubernetes `1.24+`" in handoff_text
    assert "Kernel headers" in handoff_text
    assert "`tcp.*`" in handoff_text
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["kubernetes"]["network_explorer_enabled"] is True
    assert metadata["kubernetes"]["gateway_replicas"] == 1

    invalid_replicas = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "network-cluster",
        "--enable-network-explorer",
        "--gateway-replicas",
        "2",
        "--output-dir",
        str(tmp_path / "network-explorer-invalid"),
    )
    assert invalid_replicas.returncode != 0
    assert "requires --gateway-replicas 1" in invalid_replicas.stdout

    openshift = run_setup(
        "--render-k8s",
        "--realm",
        "us0",
        "--cluster-name",
        "network-cluster",
        "--distribution",
        "openshift",
        "--enable-network-explorer",
        "--output-dir",
        str(tmp_path / "network-explorer-openshift"),
    )
    assert openshift.returncode != 0
    assert "SELinux SPC policy" in openshift.stdout
