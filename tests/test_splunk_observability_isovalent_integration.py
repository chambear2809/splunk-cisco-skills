"""Regressions for splunk-observability-isovalent-integration rendering."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from copy import deepcopy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_LIB = REPO_ROOT / "skills/shared/lib"
if str(SHARED_LIB) not in sys.path:
    sys.path.insert(0, str(SHARED_LIB))

from yaml_compat import dump_yaml, load_yaml_or_json  # noqa: E402

SETUP = REPO_ROOT / "skills/splunk-observability-isovalent-integration/scripts/setup.sh"
VALIDATE = (
    REPO_ROOT / "skills/splunk-observability-isovalent-integration/scripts/validate.sh"
)


def run_setup(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("SPLUNK_O11Y_TOKEN_FILE", None)
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_validate(
    output: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env.pop("SPLUNK_O11Y_TOKEN_FILE", None)
    if env:
        process_env.update(env)
    return subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(output), *args],
        cwd=REPO_ROOT,
        env=process_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_token(path: Path, value: str = "TEST_ONLY_" + "EXAMPLE_TOKEN_VALUE") -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def write_live_agent_relay(output: Path, path: Path) -> Path:
    overlay = load_yaml_or_json(
        (output / "splunk-otel-overlay/values.overlay.yaml").read_text(
            encoding="utf-8"
        ),
        source="test overlay",
    )
    relay = deepcopy(overlay["agent"]["config"])
    filelog = (
        (overlay.get("logsCollection") or {})
        .get("extraFileLogs", {})
        .get("filelog/tetragon")
    )
    if filelog is not None:
        relay.setdefault("receivers", {})["filelog/tetragon"] = deepcopy(filelog)
    path.write_text(dump_yaml(relay, sort_keys=True), encoding="utf-8")
    return path


def fake_live_tools(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "kubectl.calls"
    helm = bin_dir / "helm"
    helm.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--kube-context" ]]; then shift 2; fi
if [[ "$1" == "list" ]]; then
  if [[ -n "${FAKE_HELM_LIST_JSON:-}" ]]; then printf '%s\n' "${FAKE_HELM_LIST_JSON}"; else printf '%s\n' '[{"name":"splunk-otel-collector","namespace":"splunk-otel","chart":"splunk-otel-collector-0.148.0"}]'; fi
elif [[ "$1" == "get" && "${2:-}" == "metadata" ]]; then
  if [[ "${FAIL_HELM_METADATA:-false}" == "true" ]]; then exit 1; fi
  if [[ -n "${FAKE_HELM_METADATA_JSON:-}" ]]; then printf '%s\n' "${FAKE_HELM_METADATA_JSON}"; else printf '%s\n' '{"name":"splunk-otel-collector","namespace":"splunk-otel","chart":"splunk-otel-collector","version":"0.148.0","status":"deployed"}'; fi
elif [[ "$1" == "status" ]]; then
  printf 'legacy helm status should not be used\n' >&2
  exit 3
else
  exit 1
fi
""",
        encoding="utf-8",
    )
    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${KUBECTL_CALL_LOG:?}"
if [[ "$*" == *" get daemonset "* ]]; then
  if [[ -n "${FAKE_DAEMONSET_JSON:-}" ]]; then printf '%s\n' "${FAKE_DAEMONSET_JSON}"; else printf '%s\n' '{"status":{"desiredNumberScheduled":3,"numberReady":3}}'; fi
elif [[ "$*" == *" get configmap "*"-otel-agent "* ]]; then
  cat "${FAKE_AGENT_RELAY_FILE:?}"
elif [[ "$*" == *" get pods "* ]]; then
  if [[ -n "${FAKE_PODS_JSON:-}" ]]; then printf '%s\n' "${FAKE_PODS_JSON}"; else printf '%s\n' '{"items":[{"metadata":{"name":"ready-pod"},"status":{"phase":"Running","conditions":[{"type":"Ready","status":"True"}]}}]}'; fi
elif [[ "$*" == *"get --raw "* ]]; then
  if [[ -n "${FAIL_RAW_MATCH:-}" && "$*" == *"${FAIL_RAW_MATCH}"* ]]; then exit 1; fi
  printf '%s\n' '# HELP test_metric test' 'test_metric 1'
else
  exit 1
fi
""",
        encoding="utf-8",
    )
    helm.chmod(0o755)
    kubectl.chmod(0o755)
    return bin_dir, call_log


def fake_apply_tools(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "apply-bin"
    bin_dir.mkdir()
    helm_log = tmp_path / "helm.calls"
    (bin_dir / "kubectl").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "config current-context" ]]; then
  printf '%s\n' "${FAKE_CURRENT_CONTEXT:-expected-context}"
elif [[ "$*" == *" get ns cilium"* ]]; then
  exit 0
elif [[ "$*" == *" get configmap "* || "$*" == *" get deployment/"* ]]; then
  exit 1
elif [[ "$*" == *" rollout status "* ]]; then
  exit 0
else
  exit 0
fi
""",
        encoding="utf-8",
    )
    (bin_dir / "helm").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--kube-context" ]]; then shift 2; fi
case "${1:-}" in
  version)
    printf '%s\n' "${FAKE_HELM_VERSION:-v4.0.0}"
    ;;
  upgrade)
    if [[ "${2:-}" == "--help" ]]; then
      printf '%s\n' -- '--force-conflicts'
      if [[ "${FAKE_HIDE_SECRET_SUPPORTED:-true}" == "true" ]]; then printf '%s\n' -- '--hide-secret'; fi
    else
      printf '%s\n' "$*" >> "${HELM_CALL_LOG:?}"
    fi
    ;;
  list)
    if [[ -n "${FAKE_HELM_LIST_JSON:-}" ]]; then printf '%s\n' "${FAKE_HELM_LIST_JSON}"; else printf '%s\n' '[]'; fi
    ;;
  status)
    printf 'legacy helm status should not be used\n' >&2
    exit 3
    ;;
  get)
    if [[ "${2:-}" == "metadata" ]]; then
      if [[ -n "${FAKE_HELM_METADATA_JSON:-}" ]]; then printf '%s\n' "${FAKE_HELM_METADATA_JSON}"; else printf '%s\n' '{"name":"splunk-otel-collector","namespace":"splunk-otel","chart":"splunk-otel-collector","version":"0.148.0","status":"deployed"}'; fi
    elif [[ -n "${FAKE_CURRENT_VALUES:-}" ]]; then
      printf '%s\n' "${FAKE_CURRENT_VALUES}"
    else
      printf '%s\n' '{}'
    fi
    ;;
  *)
    exit 1
    ;;
esac
""",
        encoding="utf-8",
    )
    (bin_dir / "yq").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
args="$*"
if [[ "$args" == *'.splunkPlatform.logsEnabled == true'* ]]; then
  [[ "${FAKE_LOGS_ENABLED:-true}" == "true" ]]
elif [[ "$args" == *'com.splunk.index'* ]]; then
  printf '%s\n' "${FAKE_OVERLAY_INDEX:-cisco_isovalent}"
elif [[ "$args" == *'com.splunk.sourcetype'* ]]; then
  printf '%s\n' "${FAKE_OVERLAY_SOURCETYPE:-cisco:isovalent}"
elif [[ "$args" == *'.splunkPlatform.token'* ]]; then
  [[ "${FAKE_INHERITED_HEC_TOKEN:-false}" == "true" ]]
elif [[ "$args" == *'.splunkPlatform.endpoint'* ]]; then
  last="${!#}"
  if [[ "$last" == *'current-values.yaml' ]]; then
    printf '%s\n' "${FAKE_INHERITED_HEC_URL:-}"
  else
    printf '%s\n' "${FAKE_OVERLAY_HEC_URL:-}"
  fi
elif [[ "${1:-}" == "eval-all" ]]; then
  printf '%s\n' '{}'
else
  exit 0
fi
""",
        encoding="utf-8",
    )
    for name in ("kubectl", "helm", "yq"):
        (bin_dir / name).chmod(0o755)
    return bin_dir, helm_log


def run_apply_helper(
    output: Path,
    token_file: Path,
    bin_dir: Path,
    helm_log: Path,
    *,
    bash_options: tuple[str, ...] = (),
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "EXPECTED_KUBE_CONTEXT": "expected-context",
            "O11Y_TOKEN_FILE": str(token_file),
            "HELM_CALL_LOG": str(helm_log),
            "FAKE_HELM_LIST_JSON": json.dumps(
                [
                    {
                        "name": "splunk-otel-collector",
                        "namespace": "splunk-otel",
                        "chart": "splunk-otel-collector-0.148.0",
                    }
                ]
            ),
        }
    )
    env.update(overrides)
    return subprocess.run(
        ["bash", *bash_options, str(output / "scripts/apply-isovalent-overlay.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


@contextmanager
def mock_http_api(
    status: int, body: bytes, content_type: str
) -> Iterator[tuple[str, list[dict[str, object]]]]:
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
            length = int(self.headers.get("Content-Length", "0"))
            requests.append(
                {
                    "path": self.path,
                    "headers": dict(self.headers.items()),
                    "body": self.rfile.read(length),
                }
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def rendered_text(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def write_spec(path: Path, **overrides: object) -> Path:
    spec: dict[str, object] = {
        "api_version": "splunk-observability-isovalent-integration/v1",
        "realm": "us0",
        "cluster_name": "lab-cluster",
        "distribution": "kubernetes",
        "collector": {
            "release": "splunk-otel-collector",
            "namespace": "splunk-otel",
            "chart_ref": "splunk-otel-collector-chart/splunk-otel-collector",
            "chart_version": "0.148.0",
        },
        "splunk_platform": {
            "enabled": True,
            "index": "cisco_isovalent",
            "sourcetype": "cisco:isovalent",
        },
        "tetragon_export": {
            "mode": "file",
            "host_path": "/var/run/cilium/tetragon",
            "filename_pattern": "*.log",
        },
        "scrape": {
            "cilium_agent_9962": True,
            "hubble_metrics_9965": True,
            "cilium_envoy_9964": True,
            "cilium_operator_9963": True,
            "tetragon_2112": True,
            "tetragon_operator_2113": True,
        },
        "dashboards": {"enabled": True},
        "detectors": {"enabled": True, "thresholds": {}},
        "handoffs": {
            "base_collector": True,
            "hec_service": True,
            "cisco_security_cloud": True,
            "dashboard_builder": True,
            "native_ops": True,
        },
    }
    spec.update(overrides)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return path


def test_render_produces_overlay_and_handoffs(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render", "--validate", "--spec", str(spec), "--output-dir", str(output)
    )
    assert result.returncode == 0, combined_output(result)
    for f in (
        "splunk-otel-overlay/values.overlay.yaml",
        "scripts/handoff-base-collector.sh",
        "scripts/handoff-hec-token.sh",
        "scripts/handoff-cisco-security-cloud.sh",
        "scripts/handoff-dashboards.sh",
        "scripts/handoff-detectors.sh",
        "scripts/scrub-tokens.py",
        "metadata.json",
    ):
        assert (output / f).is_file(), f"Missing rendered file: {f}"
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(
        encoding="utf-8"
    )
    assert "prometheus/isovalent_cilium" in overlay
    assert "prometheus/isovalent_hubble" in overlay
    assert "prometheus/isovalent_tetragon" in overlay
    assert "${__meta_kubernetes_pod_ip}" not in overlay
    assert "replacement: $1:" in overlay
    assert "filter/includemetrics" in overlay
    assert "\ngateway:" not in f"\n{overlay}"
    assert "\noperator:" not in f"\n{overlay}"


def test_validate_only_never_rerenders_existing_packet(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        cluster_name="validate-only-cluster",
        realm="us1",
    )
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    metadata_path = output / "metadata.json"
    before = metadata_path.read_bytes()

    validated = run_setup("--validate", "--output-dir", str(output))
    assert validated.returncode == 0, combined_output(validated)
    assert metadata_path.read_bytes() == before
    metadata = json.loads(before)
    assert metadata["cluster_name"] == "validate-only-cluster"
    assert metadata["realm"] == "us1"


def test_validate_dry_run_is_rejected_for_missing_or_tampered_packets(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    missing_result = run_setup("--validate", "--dry-run", "--output-dir", str(missing))
    assert missing_result.returncode != 0
    assert "--validate cannot be combined with --dry-run" in combined_output(missing_result)
    assert not missing.exists()

    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    metadata_path = output / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["skill"] = "tampered-skill"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    tampered = run_setup("--validate", "--dry-run", "--output-dir", str(output))
    assert tampered.returncode != 0
    assert "--validate cannot be combined with --dry-run" in combined_output(tampered)


def test_default_file_path_renders_extra_file_logs_aligned_with_hostpath(
    tmp_path: Path,
) -> None:
    """The hostPath mount and extraFileLogs include glob must reference the same directory."""
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render", "--validate", "--spec", str(spec), "--output-dir", str(output)
    )
    assert result.returncode == 0, combined_output(result)
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(
        encoding="utf-8"
    )
    assert "extraVolumes" in overlay
    assert "/var/run/cilium/tetragon" in overlay
    assert "filelog/tetragon" in overlay
    assert "receivers:" in overlay
    assert "com.splunk.sourcetype: cisco:isovalent" in overlay
    assert "com.splunk.index: cisco_isovalent" in overlay
    assert "k8s.cluster.name: lab-cluster" in overlay
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["collector"] == {
        "release": "splunk-otel-collector",
        "namespace": "splunk-otel",
        "chart_ref": "splunk-otel-collector-chart/splunk-otel-collector",
        "chart_name": "splunk-otel-collector",
        "chart_version": "0.148.0",
    }


def test_legacy_fluentd_warns(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render",
        "--legacy-fluentd-hec",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    warnings = " ".join(metadata.get("warnings", []))
    assert "DEPRECATED" in warnings


def test_handoff_to_hec_uses_correct_token_name_flag(tmp_path: Path) -> None:
    """Regression: splunk-hec-service-setup uses --token-name, not --hec-token-name.

    The Isovalent integration emits handoff-hec-token.sh that the operator runs to
    provision a Splunk Platform HEC token for cisco_isovalent-index events. If this
    handoff scripts the wrong flag, the operator's hand-off command fails.
    """
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    handoff = (output / "scripts/handoff-hec-token.sh").read_text(encoding="utf-8")
    assert "--token-name " in handoff
    assert "--platform " in handoff
    assert "--default-index " in handoff
    assert "--allowed-indexes " in handoff
    assert "--hec-token-name" not in handoff


def test_handoff_to_dashboards_uses_spec_flag(tmp_path: Path) -> None:
    """Regression: splunk-observability-dashboard-builder uses --spec, not --import-json.

    Earlier the Isovalent handoff emitted --import-json which is not a flag of
    splunk-observability-dashboard-builder/scripts/setup.sh. Operator running
    the handoff verbatim got "Unknown option: --import-json".
    """
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    handoff = (output / "scripts/handoff-dashboards.sh").read_text(encoding="utf-8")
    assert "--spec " in handoff
    assert "--token-file " in handoff
    assert "--realm " in handoff
    assert "--import-json" not in handoff


def test_handoff_to_cisco_security_cloud(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    handoff = (output / "scripts/handoff-cisco-security-cloud.sh").read_text(
        encoding="utf-8"
    )
    # cisco-security-cloud-setup uses two scripts: setup.sh --install for the app,
    # then configure_input.sh --input-type sbg_isovalent_input for the Isovalent
    # input. There is no --product flag.
    assert "cisco-security-cloud-setup/scripts/setup.sh --install" in handoff
    assert "cisco-security-cloud-setup/scripts/configure_input.sh" in handoff
    assert "--input-type sbg_isovalent_input" in handoff
    # The default index for Isovalent Runtime Security must align with the
    # Cisco Security Cloud App Splunk Threat Research Team detection scope.
    assert "cisco_isovalent" in handoff
    # Negative: confirm we do NOT emit the legacy/wrong --product flag that was
    # never a valid cisco-security-cloud-setup CLI argument.
    assert "--product isovalent" not in handoff


def test_apply_helper_auto_discovers_collector_namespace_and_uses_set_file(
    tmp_path: Path,
) -> None:
    """The apply helper must work with non-default collector namespaces.

    Live EKS clusters commonly install the Splunk OTel Collector outside the
    chart's example `splunk-otel` namespace. The helper should discover the
    release namespace when the spec does not pin one, and it must not expand
    the O11y token into the Helm process argv.
    """
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    helper = (output / "scripts/apply-isovalent-overlay.sh").read_text(encoding="utf-8")
    assert (
        '"${HELM[@]}" list --all-namespaces --filter "^${RELEASE}$" -o json' in helper
    )
    assert "head -1" not in helper
    assert "matches = [row for row in rows" in helper
    assert "len(matches) != 1" in helper
    assert 'get metadata "${RELEASE}"' in helper
    assert 'data.get("chart") == chart' in helper
    assert '"${VERSION_FLAG[@]}"' in helper
    assert 'NAMESPACE="splunk-otel"' in helper
    assert 'get configmap "${RELEASE}-obi"' in helper
    assert ".obi.config.data = load(strenv(OBI_CONFIG_FILE))" in helper
    assert 'get configmap "${RELEASE}-otel-collector"' in helper
    assert ".gateway.config = load(strenv(GATEWAY_CONFIG_FILE))" in helper
    assert "claim_configmap_for_helm" not in helper
    assert "field-manager=helm" not in helper
    assert 'getattr(os, "O_NOFOLLOW", 0)' in helper
    assert "info.st_nlink != 1" in helper
    assert "changed while it was read" in helper
    assert 'NORMALIZE_OTLPHTTP="auto"' in helper
    assert 'sub("^otlphttp"; "otlp_http")' in helper
    assert "--force-conflicts" in helper
    assert "EXPECTED_KUBE_CONTEXT" in helper
    assert "--hide-secret" in helper
    assert 'upgrade "${RELEASE}" "${CHART_REF}"' in helper
    assert "upgrade --install" not in helper
    assert (
        'HELM_SECRET_FLAGS=(--set-file "splunkObservability.accessToken=${O11Y_TOKEN_COPY}")'
        in helper
    )
    assert "deployment/${RELEASE}-k8s-cluster-receiver" in helper
    assert "deployment/${RELEASE}-cluster-receiver" not in helper
    assert (
        '--set "splunkObservability.accessToken=$(cat "${O11Y_TOKEN_FILE}")"'
        not in helper
    )
    assert (
        '--set-file "splunkObservability.accessToken=${O11Y_TOKEN_FILE}"' not in helper
    )


def test_apply_helper_honors_explicit_collector_namespace(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        collector={
            "release": "custom-collector",
            "namespace": "otel-splunk",
            "chart_version": "0.148.0",
        },
    )
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    helper = (output / "scripts/apply-isovalent-overlay.sh").read_text(encoding="utf-8")
    assert 'RELEASE="custom-collector"' in helper
    assert 'NAMESPACE="otel-splunk"' in helper
    assert 'CHART_VERSION="0.148.0"' in helper


def test_apply_helper_requires_explicit_matching_context(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, helm_log = fake_apply_tools(tmp_path)
    token = write_token(tmp_path / "o11y.token")
    missing = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        EXPECTED_KUBE_CONTEXT="",
    )
    assert missing.returncode == 1
    assert "EXPECTED_KUBE_CONTEXT is required" in combined_output(missing)
    mismatch = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        FAKE_CURRENT_CONTEXT="different-context",
    )
    assert mismatch.returncode == 1
    assert "does not match EXPECTED_KUBE_CONTEXT" in combined_output(mismatch)


def test_apply_helper_requires_helm4_and_dry_run_secret_hiding(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, helm_log = fake_apply_tools(tmp_path)
    token = write_token(tmp_path / "o11y.token")
    helm3 = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        FAKE_HELM_VERSION="v3.18.0",
    )
    assert helm3.returncode == 1
    assert "requires Helm 4" in combined_output(helm3)
    no_hide = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        K8S_APPLY_DRY_RUN="true",
        FAKE_HIDE_SECRET_SUPPORTED="false",
    )
    assert no_hide.returncode == 1
    assert "cannot --hide-secret" in combined_output(no_hide)


def test_apply_helper_streams_private_helm_status_and_refuses_xtrace(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        splunk_platform={
            "enabled": False,
            "index": "cisco_isovalent",
            "sourcetype": "cisco:isovalent",
        },
    )
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    helper_path = output / "scripts/apply-isovalent-overlay.sh"
    helper = helper_path.read_text(encoding="utf-8")
    assert "HELM_STATUS=" not in helper
    assert "HELM_METADATA=" not in helper
    assert "shell xtrace is enabled; refusing" in helper

    bin_dir, helm_log = fake_apply_tools(tmp_path)
    token = write_token(tmp_path / "o11y.token")
    private_marker = "HELM_PRIVATE_STATUS_MARKER"
    status_payload = json.dumps(
        {
            "name": "splunk-otel-collector",
            "namespace": "splunk-otel",
            "chart": "splunk-otel-collector",
            "version": "0.148.0",
            "status": "deployed",
            "notes": private_marker,
        }
    )
    normal = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        K8S_APPLY_DRY_RUN="true",
        FAKE_HELM_METADATA_JSON=status_payload,
    )
    assert normal.returncode == 0, combined_output(normal)
    assert private_marker not in combined_output(normal)

    traced = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        bash_options=("-x",),
        K8S_APPLY_DRY_RUN="true",
        FAKE_HELM_METADATA_JSON=status_payload,
    )
    assert traced.returncode != 0
    assert "shell xtrace is enabled; refusing" in combined_output(traced)
    assert private_marker not in combined_output(traced)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("name", "wrong-release"),
        ("namespace", "wrong-namespace"),
        ("chart", "wrong-chart"),
        ("version", "0.0.0"),
        ("status", "failed"),
    ),
)
def test_apply_helper_rejects_fresh_helm_metadata_drift(
    tmp_path: Path, field: str, value: str
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        splunk_platform={
            "enabled": False,
            "index": "cisco_isovalent",
            "sourcetype": "cisco:isovalent",
        },
    )
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, helm_log = fake_apply_tools(tmp_path)
    token = write_token(tmp_path / "o11y.token")
    metadata = {
        "name": "splunk-otel-collector",
        "namespace": "splunk-otel",
        "chart": "splunk-otel-collector",
        "version": "0.148.0",
        "status": "deployed",
    }
    metadata[field] = value

    result = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        K8S_APPLY_DRY_RUN="true",
        FAKE_HELM_METADATA_JSON=json.dumps(metadata),
    )

    assert result.returncode != 0
    assert "unavailable or not deployed; command output suppressed" in combined_output(result)


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([], "does not exist"),
        (
            [
                {
                    "name": "splunk-otel-collector",
                    "namespace": "one",
                    "chart": "splunk-otel-collector-0.148.0",
                },
                {
                    "name": "splunk-otel-collector",
                    "namespace": "two",
                    "chart": "splunk-otel-collector-0.148.0",
                },
            ],
            "ambiguous",
        ),
    ],
)
def test_apply_helper_rejects_missing_or_ambiguous_release(
    rows: list[dict[str, str]], expected: str, tmp_path: Path
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, helm_log = fake_apply_tools(tmp_path)
    token = write_token(tmp_path / "o11y.token")
    result = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        FAKE_HELM_LIST_JSON=json.dumps(rows),
    )
    assert result.returncode == 1
    assert expected in combined_output(result)


def test_apply_helper_uses_fresh_metadata_over_stale_inventory_chart(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        splunk_platform={
            "enabled": False,
            "index": "cisco_isovalent",
            "sourcetype": "cisco:isovalent",
        },
    )
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, helm_log = fake_apply_tools(tmp_path)
    token = write_token(tmp_path / "o11y.token")

    result = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        K8S_APPLY_DRY_RUN="true",
        FAKE_HELM_LIST_JSON=json.dumps(
            [
                {
                    "name": "splunk-otel-collector",
                    "namespace": "splunk-otel",
                    "chart": "stale-chart-0.0.0",
                    "status": "failed",
                }
            ]
        ),
    )

    assert result.returncode == 0, combined_output(result)


def test_apply_helper_derives_only_sanitized_version_from_fresh_metadata(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        collector={
            "release": "splunk-otel-collector",
            "namespace": "splunk-otel",
            "chart_ref": "splunk-otel-collector-chart/splunk-otel-collector",
            "chart_version": "",
        },
        splunk_platform={
            "enabled": False,
            "index": "cisco_isovalent",
            "sourcetype": "cisco:isovalent",
        },
    )
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, helm_log = fake_apply_tools(tmp_path)
    token = write_token(tmp_path / "o11y.token")

    accepted = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        K8S_APPLY_DRY_RUN="true",
        FAKE_HELM_METADATA_JSON=json.dumps(
            {
                "name": "splunk-otel-collector",
                "namespace": "splunk-otel",
                "chart": "splunk-otel-collector",
                "version": "0.148.0",
                "status": "deployed",
            }
        ),
    )
    assert accepted.returncode == 0, combined_output(accepted)
    assert "--version 0.148.0" in helm_log.read_text(encoding="utf-8")

    rejected_marker = "INVALID_VERSION_MUST_NOT_APPEAR"
    rejected = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        K8S_APPLY_DRY_RUN="true",
        FAKE_HELM_METADATA_JSON=json.dumps(
            {
                "name": "splunk-otel-collector",
                "namespace": "splunk-otel",
                "chart": "splunk-otel-collector",
                "version": f"0.148.0 {rejected_marker}",
                "status": "deployed",
            }
        ),
    )
    assert rejected.returncode != 0
    assert rejected_marker not in combined_output(rejected)


@pytest.mark.parametrize(
    ("inherited_url", "inherited_token", "rendered_url", "expected"),
    [
        (
            "https://splunk.example.test:8088",
            "false",
            "",
            "complete inherited release pair",
        ),
        ("", "true", "", "complete inherited release pair"),
        ("http://splunk.example.test:8088", "true", "", "not a safe HTTPS URL"),
        (
            "https://wrong.example.test:8088",
            "true",
            "https://expected.example.test:8088",
            "endpoints differ",
        ),
    ],
)
def test_apply_helper_rejects_partial_or_wrong_inherited_hec(
    inherited_url: str,
    inherited_token: str,
    rendered_url: str,
    expected: str,
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, helm_log = fake_apply_tools(tmp_path)
    token = write_token(tmp_path / "o11y.token", "TEST_ONLY_" + "EXAMPLE_O11Y_TOKEN")
    result = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        K8S_APPLY_DRY_RUN="true",
        FAKE_INHERITED_HEC_URL=inherited_url,
        FAKE_INHERITED_HEC_TOKEN=inherited_token,
        FAKE_OVERLAY_HEC_URL=rendered_url,
    )
    assert result.returncode == 1
    assert expected in combined_output(result)
    assert "EXAMPLE_O11Y_TOKEN" not in combined_output(result)


def test_apply_helper_accepts_complete_inherited_hec_and_hides_dry_run_secrets(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, helm_log = fake_apply_tools(tmp_path)
    token = write_token(
        tmp_path / "o11y.token",
        "TEST_ONLY_" + "EXAMPLE_O11Y_TOKEN\n",
    )
    result = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        K8S_APPLY_DRY_RUN="true",
        FAKE_INHERITED_HEC_URL="https://splunk.example.test:8088/services/collector",
        FAKE_INHERITED_HEC_TOKEN="true",
    )
    assert result.returncode == 0, combined_output(result)
    calls = helm_log.read_text(encoding="utf-8")
    assert "--dry-run --hide-secret" in calls
    assert "--install" not in calls
    assert "EXAMPLE_O11Y_TOKEN" not in calls


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("FAKE_OVERLAY_INDEX", "wrong_index"),
        ("FAKE_OVERLAY_SOURCETYPE", "wrong:sourcetype"),
    ],
)
def test_apply_helper_rejects_drifted_platform_event_path(
    override: str, value: str, tmp_path: Path
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, helm_log = fake_apply_tools(tmp_path)
    token = write_token(tmp_path / "o11y.token")
    result = run_apply_helper(
        output,
        token,
        bin_dir,
        helm_log,
        K8S_APPLY_DRY_RUN="true",
        **{override: value},
    )
    assert result.returncode == 1
    assert "index/sourcetype path" in combined_output(result)


def test_apply_helper_accepts_reviewed_hec_file_pair_without_exposing_tokens(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, helm_log = fake_apply_tools(tmp_path)
    o11y_value = "TEST_ONLY_" + "EXAMPLE_O11Y_TOKEN"
    hec_value = "TEST_ONLY_" + "EXAMPLE_HEC_TOKEN"
    o11y_token = write_token(tmp_path / "o11y.token", o11y_value + "\n")
    hec_token = write_token(tmp_path / "hec.token", hec_value + "\n")
    hec_url = "https://splunk.example.test:8088/services/collector"
    result = run_apply_helper(
        output,
        o11y_token,
        bin_dir,
        helm_log,
        K8S_APPLY_DRY_RUN="true",
        PLATFORM_HEC_URL=hec_url,
        PLATFORM_HEC_TOKEN_FILE=str(hec_token),
        FAKE_OVERLAY_HEC_URL="",
    )
    assert result.returncode == 0, combined_output(result)
    calls = helm_log.read_text(encoding="utf-8")
    assert "splunkPlatform.token=" in calls
    assert "splunkPlatform.endpoint=" + hec_url in calls
    assert o11y_value not in calls
    assert hec_value not in calls
    assert o11y_value not in combined_output(result)
    assert hec_value not in combined_output(result)


def test_apply_dry_run_still_renders_fresh_assets() -> None:
    setup = SETUP.read_text(encoding="utf-8")
    assert '[[ "${DRY_RUN}" == "true" && "${MODE_APPLY}" != "true" ]]' in setup
    assert "--apply requires --kube-context" in setup
    assert 'EXPECTED_KUBE_CONTEXT="${EXPECTED_KUBE_CONTEXT}"' in setup


@pytest.mark.parametrize(
    "flag",
    [
        "--access-token",
        "--token",
        "--bearer-token",
        "--api-token",
        "--o11y-token",
        "--sf-token",
        "--platform-hec-token",
        "--hec-token",
    ],
)
def test_direct_secret_flags_are_rejected(flag: str, tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), flag, "INLINE_SHOULD_NOT_LEAK")
    assert result.returncode == 1
    assert "-token-file" in combined_output(result)
    assert "INLINE_SHOULD_NOT_LEAK" not in combined_output(result)


def test_idempotent_re_render(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    args = ["--render", "--spec", str(spec), "--output-dir", str(output)]
    first = run_setup(*args)
    second = run_setup(*args)
    assert first.returncode == 0, combined_output(first)
    assert second.returncode == 0, combined_output(second)
    first_overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(
        encoding="utf-8"
    )
    assert (output / "splunk-otel-overlay/values.overlay.yaml").read_text(
        encoding="utf-8"
    ) == first_overlay


@pytest.mark.parametrize("mode", ["banana", "FILE", "", "file/stdout"])
def test_invalid_export_mode_is_rejected(mode: str, tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--export-mode", mode)
    assert result.returncode != 0
    assert "export" in combined_output(result).lower()


def test_invalid_export_mode_in_spec_is_rejected_before_write(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", tetragon_export={"mode": "invalid"})
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 1
    assert "export mode" in combined_output(result).lower()
    assert not (output / "metadata.json").exists()


def test_hec_url_and_token_file_are_wired_without_serializing_secret(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    secret = "TEST_ONLY_" + "EXAMPLE_HEC_TOKEN_VALUE"
    token_file = write_token(tmp_path / "hec.token", secret)
    hec_url = "https://splunk.example.test:8088/services/collector"
    result = run_setup(
        "--render",
        "--validate",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
        "--platform-hec-url",
        hec_url,
        "--platform-hec-token-file",
        str(token_file),
    )
    assert result.returncode == 0, combined_output(result)
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(
        encoding="utf-8"
    )
    helper = (output / "scripts/apply-isovalent-overlay.sh").read_text(encoding="utf-8")
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert hec_url in overlay
    assert (
        'HELM_SECRET_FLAGS+=(--set-file "splunkPlatform.token=${PLATFORM_HEC_TOKEN_COPY}")'
        in helper
    )
    assert (
        'PLATFORM_FLAGS+=(--set-string "splunkPlatform.endpoint=${PLATFORM_HEC_URL}")'
        in helper
    )
    assert metadata["platform_hec_token_configured"] is True
    assert metadata["splunk_platform_hec_url"] == hec_url
    assert secret not in rendered_text(output)
    assert str(token_file) not in json.dumps(metadata)


def test_hec_token_file_without_endpoint_fails_closed(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    token_file = write_token(tmp_path / "hec.token")
    result = run_setup(
        "--render",
        "--spec",
        str(spec),
        "--platform-hec-token-file",
        str(token_file),
    )
    assert result.returncode == 1
    assert "requires --platform-hec-url" in combined_output(result)


def test_render_hec_helper_flag_forces_helper_when_spec_disables_handoff(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        handoffs={
            "base_collector": False,
            "hec_service": False,
            "cisco_security_cloud": False,
            "dashboard_builder": False,
            "native_ops": False,
        },
    )
    result = run_setup(
        "--render",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
        "--render-platform-hec-helper",
    )
    assert result.returncode == 0, combined_output(result)
    assert (output / "scripts/handoff-hec-token.sh").is_file()
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["render_platform_hec_helper"] is True


@pytest.mark.parametrize(
    "flag", ["--token", "--access-token", "--hec-token", "--splunk-token"]
)
def test_direct_secret_equals_form_is_rejected_without_echo(
    flag: str, tmp_path: Path
) -> None:
    spec = write_spec(tmp_path / "spec.json")
    secret = "TEST_ONLY_" + "EXAMPLE_INLINE_SECRET"
    result = run_setup("--render", "--spec", str(spec), f"{flag}={secret}")
    assert result.returncode == 1
    assert secret not in combined_output(result)
    assert "-token-file" in combined_output(result)


def test_token_file_symlink_is_rejected_even_with_permission_override(
    tmp_path: Path,
) -> None:
    spec = write_spec(tmp_path / "spec.json")
    target = write_token(tmp_path / "target.token")
    link = tmp_path / "link.token"
    link.symlink_to(target)
    result = run_setup(
        "--render",
        "--spec",
        str(spec),
        "--o11y-token-file",
        str(link),
        "--allow-loose-token-perms",
    )
    assert result.returncode == 1
    assert "symbolic link" in combined_output(result)


def test_token_file_hard_link_is_rejected(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    token = write_token(tmp_path / "token")
    hard_link = tmp_path / "token.link"
    os.link(token, hard_link)
    result = run_setup("--render", "--spec", str(spec), "--o11y-token-file", str(token))
    assert result.returncode == 1
    assert "hard link" in combined_output(result)


def test_non_600_token_mode_is_rejected(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    token = write_token(tmp_path / "token")
    token.chmod(0o644)
    result = run_setup("--render", "--spec", str(spec), "--o11y-token-file", str(token))
    assert result.returncode == 1
    assert "mode 600" in combined_output(result)


@pytest.mark.parametrize(
    ("needle", "replacement", "message"),
    [
        ("com.splunk.index: cisco_isovalent", "com.splunk.index: wrong_index", "index"),
        (
            "com.splunk.sourcetype: cisco:isovalent",
            "com.splunk.sourcetype: wrong:type",
            "sourcetype",
        ),
    ],
)
def test_static_validation_fails_on_index_or_sourcetype_drift(
    needle: str, replacement: str, message: str, tmp_path: Path
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    overlay = output / "splunk-otel-overlay/values.overlay.yaml"
    text = overlay.read_text(encoding="utf-8")
    assert needle in text
    overlay.write_text(text.replace(needle, replacement), encoding="utf-8")
    validated = run_validate(output)
    assert validated.returncode == 1
    assert message in combined_output(validated).lower()


def test_static_token_scan_finds_leak_even_when_placeholder_also_exists(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    synthetic_secret = "TEST_ONLY_" + "EXAMPLE_ACCESS_TOKEN_VALUE"
    (output / "dashboards/leak.json").write_text(
        json.dumps(
            {
                "accessToken": "${REDACTED}",
                "nested": {"secret_file": synthetic_secret},
            }
        ),
        encoding="utf-8",
    )
    validated = run_validate(output)
    assert validated.returncode == 1
    assert "credential material" in combined_output(validated)
    assert synthetic_secret not in combined_output(validated)


def test_dashboard_placeholder_uses_portable_source_guidance(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    readme = (output / "dashboards/README.md").read_text(encoding="utf-8")
    assert "--dashboards-source" in readme
    assert "Isovalent_Splunk_o11y examples checkout" in readme
    assert "/Users/" not in readme


def test_dashboard_scrubber_redacts_generic_credential_keys_and_values(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    source = tmp_path / "dashboards-source"
    source.mkdir()
    markers = {
        "hec": "TEST_ONLY_" + "EXAMPLE_HEC_VALUE",
        "authorization": "TEST_ONLY_" + "EXAMPLE_AUTH_VALUE",
        "clientSecret": "TEST_ONLY_" + "EXAMPLE_SECRET_VALUE",
        "bearerCredential": "TEST_ONLY_" + "EXAMPLE_BEARER_VALUE",
    }
    (source / "generic.json").write_text(
        json.dumps(
            {
                **markers,
                "description": "Bearer " + "TEST_ONLY_EXAMPLE_FREEFORM_VALUE",
                "safe": "dashboard title",
            }
        ),
        encoding="utf-8",
    )
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render",
        "--validate",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
        "--dashboards-source",
        str(source),
    )
    assert result.returncode == 0, combined_output(result)
    scrubbed = json.loads(
        (output / "dashboards/generic.json").read_text(encoding="utf-8")
    )
    for key in markers:
        assert scrubbed[key] == "${REDACTED}"
    assert scrubbed["description"] == "${REDACTED}"
    assert scrubbed["safe"] == "dashboard title"
    rendered = rendered_text(output)
    assert all(value not in rendered for value in markers.values())
    assert "TEST_ONLY_EXAMPLE_FREEFORM_VALUE" not in rendered


def test_signalflow_metadata_uses_verified_representative_metrics(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["signalflow_metrics"] == {
        "cilium": "cilium_endpoint_state",
        "hubble": "hubble_flows_processed_total",
        "tetragon": "tetragon_dns_total",
    }


def test_signalflow_representatives_are_configurable_and_allowlisted(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    configured = {
        "cilium": "cilium_custom_validation",
        "hubble": "hubble_custom_validation",
        "tetragon": "tetragon_custom_validation",
    }
    spec = write_spec(
        tmp_path / "spec.json",
        validation={"signalflow_metrics": configured},
    )
    rendered = run_setup(
        "--render",
        "--validate",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert rendered.returncode == 0, combined_output(rendered)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(
        encoding="utf-8"
    )
    assert metadata["signalflow_metrics"] == configured
    assert all(metric in overlay for metric in configured.values())


def test_signalflow_and_splunk_search_require_file_backed_credentials(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    signalflow = run_validate(output, "--signalflow")
    assert signalflow.returncode == 1
    assert "--o11y-token-file" in combined_output(signalflow)
    search = run_validate(
        output, "--splunk-search", "--splunk-url", "https://splunk.example.test:8089"
    )
    assert search.returncode == 1
    assert "--splunk-search-token-file" in combined_output(search)
    production = run_validate(output, "--production")
    assert production.returncode == 1
    assert "--live, --signalflow, and --splunk-search" in combined_output(production)


def test_signalflow_api_probe_accepts_only_positive_sse_data(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    synthetic_token = "TEST_ONLY_" + "EXAMPLE_SIGNALFLOW_TOKEN"
    token = write_token(tmp_path / "o11y.token", synthetic_token + "\n")
    positive = b'event: data\ndata: {"data":[\ndata: [1712345678000,1]]}\n\n'
    with mock_http_api(200, positive, "text/event-stream") as (url, requests):
        result = run_validate(
            output,
            "--signalflow",
            "--o11y-token-file",
            str(token),
            "--api-timeout-seconds",
            "2",
            env={
                "ISOVALENT_VALIDATION_TEST_MODE": "true",
                "ISOVALENT_SIGNALFLOW_TEST_URL": url + "/signalflow",
            },
        )
    assert result.returncode == 0, combined_output(result)
    assert len(requests) == 3
    assert all(
        request["headers"].get("X-Sf-Token") == synthetic_token for request in requests
    )
    request_programs = b"\n".join(request["body"] for request in requests)
    assert b"cilium_endpoint_state" in request_programs
    assert b"hubble_flows_processed_total" in request_programs
    assert b"tetragon_dns_total" in request_programs
    assert b'filter("k8s.cluster.name", "lab-cluster")' in request_programs
    assert synthetic_token not in combined_output(result)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (
            200,
            b'event: metadata\ndata: {"properties":{"sf_metric":"cilium_endpoint_state"}}\n\n',
            "no positive data",
        ),
        (
            200,
            b'event: data\ndata: {"data":[[1712345678000,0]]}\n\n',
            "no positive data",
        ),
        (403, b"TEST_ONLY_EXAMPLE_RESPONSE_SECRET lab-cluster", "HTTP 403"),
    ],
)
def test_signalflow_api_probe_fails_closed_without_echoing_response_or_filter(
    status: int, body: bytes, expected: str, tmp_path: Path
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    synthetic_token = "TEST_ONLY_" + "EXAMPLE_SIGNALFLOW_TOKEN"
    token = write_token(tmp_path / "o11y.token", synthetic_token)
    with mock_http_api(status, body, "text/event-stream") as (url, _requests):
        result = run_validate(
            output,
            "--signalflow",
            "--o11y-token-file",
            str(token),
            "--api-timeout-seconds",
            "2",
            env={
                "ISOVALENT_VALIDATION_TEST_MODE": "true",
                "ISOVALENT_SIGNALFLOW_TEST_URL": url + "/signalflow",
            },
        )
    text = combined_output(result)
    assert result.returncode == 1
    assert expected in text
    assert synthetic_token not in text
    assert "TEST_ONLY_EXAMPLE_RESPONSE_SECRET" not in text
    assert "lab-cluster" not in text


def test_splunk_search_api_probe_accepts_export_result(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    synthetic_token = "TEST_ONLY_" + "EXAMPLE_SPLUNK_BEARER"
    token = write_token(tmp_path / "splunk.token", synthetic_token + "\r\n")
    with mock_http_api(
        200,
        b'{"result":{"k8s.cluster.name":"lab-cluster"}}\n',
        "application/json",
    ) as (
        url,
        requests,
    ):
        result = run_validate(
            output,
            "--splunk-search",
            "--splunk-url",
            url,
            "--splunk-search-token-file",
            str(token),
            "--api-timeout-seconds",
            "2",
            env={"ISOVALENT_VALIDATION_TEST_MODE": "true"},
        )
    assert result.returncode == 0, combined_output(result)
    assert len(requests) == 1
    assert requests[0]["headers"].get("Authorization") == "Bearer " + synthetic_token
    request_body = requests[0]["body"]
    assert b"cisco_isovalent" in request_body
    assert b"cisco%3Aisovalent" in request_body
    assert b"k8s.cluster.name%3D%22lab-cluster%22" in request_body
    assert synthetic_token not in combined_output(result)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, b'{"preview":false}\n', "no Isovalent events"),
        (
            200,
            b'{"result":{"k8s.cluster.name":"unrelated-cluster"}}\n',
            "no Isovalent events",
        ),
        (401, b"TEST_ONLY_EXAMPLE_RESPONSE_SECRET cisco_isovalent", "HTTP 401"),
    ],
)
def test_splunk_search_api_probe_fails_closed_without_echoing_response(
    status: int, body: bytes, expected: str, tmp_path: Path
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    synthetic_token = "TEST_ONLY_" + "EXAMPLE_SPLUNK_BEARER"
    token = write_token(tmp_path / "splunk.token", synthetic_token)
    with mock_http_api(status, body, "application/json") as (url, _requests):
        result = run_validate(
            output,
            "--splunk-search",
            "--splunk-url",
            url,
            "--splunk-search-token-file",
            str(token),
            "--api-timeout-seconds",
            "2",
            env={"ISOVALENT_VALIDATION_TEST_MODE": "true"},
        )
    text = combined_output(result)
    assert result.returncode == 1
    assert expected in text
    assert synthetic_token not in text
    assert "TEST_ONLY_EXAMPLE_RESPONSE_SECRET" not in text


def test_live_validation_fails_when_fresh_helm_metadata_fails(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
            "FAIL_HELM_METADATA": "true",
        },
    )
    assert validated.returncode == 1
    assert "not a valid deployed release; command output suppressed" in combined_output(validated)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("name", "wrong-release"),
        ("namespace", "wrong-namespace"),
        ("chart", "wrong-chart"),
        ("version", "0.0.0"),
        ("status", "failed"),
    ),
)
def test_live_validation_rejects_fresh_helm_metadata_drift(
    tmp_path: Path, field: str, value: str
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    metadata = {
        "name": "splunk-otel-collector",
        "namespace": "splunk-otel",
        "chart": "splunk-otel-collector",
        "version": "0.148.0",
        "status": "deployed",
    }
    metadata[field] = value
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
            "FAKE_HELM_METADATA_JSON": json.dumps(metadata),
        },
    )

    assert validated.returncode != 0
    assert "not a valid deployed release; command output suppressed" in combined_output(validated)


def test_live_validation_requires_context_or_explicit_acknowledgement(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    missing = run_validate(output, "--live")
    assert missing.returncode == 1
    assert "--kube-context" in combined_output(missing)
    conflict = run_validate(
        output,
        "--live",
        "--kube-context",
        "expected-context",
        "--allow-current-context",
    )
    assert conflict.returncode == 1
    assert "not both" in combined_output(conflict)


def test_live_validation_accepts_explicit_named_context(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    validated = run_validate(
        output,
        "--live",
        "--kube-context",
        "expected-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
        },
    )
    assert validated.returncode == 0, combined_output(validated)


def test_live_validation_refuses_xtrace_before_private_object_reads(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    helm_marker = "HELM_PRIVATE_NOTES_MARKER"
    object_marker = "KUBERNETES_PRIVATE_ANNOTATION_MARKER"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
            "FAKE_HELM_METADATA_JSON": json.dumps(
                {
                    "name": "splunk-otel-collector",
                    "namespace": "splunk-otel",
                    "chart": "splunk-otel-collector",
                    "version": "0.148.0",
                    "status": "deployed",
                    "notes": helm_marker,
                }
            ),
            "FAKE_DAEMONSET_JSON": json.dumps(
                {
                    "metadata": {"annotations": {"private": object_marker}},
                    "status": {"desiredNumberScheduled": 3, "numberReady": 3},
                }
            ),
        }
    )
    validated = subprocess.run(
        [
            "/bin/bash",
            "-x",
            str(VALIDATE),
            "--output-dir",
            str(output),
            "--live",
            "--allow-current-context",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert validated.returncode != 0
    assert "shell xtrace is enabled; refusing to load credential helpers" in validated.stdout
    assert helm_marker not in validated.stdout
    assert object_marker not in validated.stdout
    validator = VALIDATE.read_text(encoding="utf-8")
    assert "HELM_STATUS=" not in validator
    assert "AGENT_STATUS=" not in validator


def test_live_required_pod_probe_failure_is_nonzero(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
            "FAIL_RAW_MATCH": ":2112/proxy/metrics",
        },
    )
    assert validated.returncode == 1
    assert "tetragon:2112 has a selected pod with an unreachable" in combined_output(
        validated
    )


def test_live_validation_uses_pod_proxies_and_requires_all_rendered_jobs(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
        },
    )
    assert validated.returncode == 0, combined_output(validated)
    calls = call_log.read_text(encoding="utf-8")
    assert "/pods/ready-pod:9962/proxy/metrics" in calls
    assert "/pods/ready-pod:2112/proxy/metrics" in calls
    assert "/services/" not in calls
    assert ":9967/proxy/metrics" not in calls


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (
            [
                {
                    "name": "splunk-otel-collector",
                    "namespace": "splunk-otel",
                    "chart": "splunk-otel-collector-0.148.0",
                },
                {
                    "name": "splunk-otel-collector",
                    "namespace": "duplicate",
                    "chart": "splunk-otel-collector-0.148.0",
                },
            ],
            "exactly one collector Helm release",
        ),
        (
            [
                {
                    "name": "unrelated-release",
                    "namespace": "splunk-otel",
                    "chart": "splunk-otel-collector-0.148.0",
                }
            ],
            "unrelated release",
        ),
        (
            [
                {
                    "name": "splunk-otel-collector",
                    "namespace": "wrong-namespace",
                    "chart": "splunk-otel-collector-0.148.0",
                }
            ],
            "namespace differs",
        ),
    ],
)
def test_live_validation_rejects_nonexact_collector_helm_identity(
    rows: list[dict[str, str]], expected: str, tmp_path: Path
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
            "FAKE_HELM_LIST_JSON": json.dumps(rows),
        },
    )
    assert validated.returncode == 1
    assert expected in combined_output(validated)


def test_live_validation_uses_fresh_metadata_over_stale_inventory_chart_and_status(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
            "FAKE_HELM_LIST_JSON": json.dumps(
                [
                    {
                        "name": "splunk-otel-collector",
                        "namespace": "splunk-otel",
                        "chart": "stale-chart-0.0.0",
                        "status": "failed",
                    }
                ]
            ),
        },
    )

    assert validated.returncode == 0, combined_output(validated)


def test_live_validation_derives_custom_collector_identity_from_metadata(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(
        tmp_path / "spec.json",
        collector={
            "release": "custom-collector",
            "namespace": "otel-splunk",
            "chart_ref": "splunk-otel-collector-chart/splunk-otel-collector",
            "chart_version": "0.148.0",
        },
    )
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
            "FAKE_HELM_LIST_JSON": json.dumps(
                [
                    {
                        "name": "custom-collector",
                        "namespace": "otel-splunk",
                        "chart": "splunk-otel-collector-0.148.0",
                    }
                ]
            ),
            "FAKE_HELM_METADATA_JSON": json.dumps(
                {
                    "name": "custom-collector",
                    "namespace": "otel-splunk",
                    "chart": "splunk-otel-collector",
                    "version": "0.148.0",
                    "status": "deployed",
                }
            ),
        },
    )
    assert validated.returncode == 0, combined_output(validated)
    calls = call_log.read_text(encoding="utf-8")
    assert "-n otel-splunk get daemonset custom-collector-agent" in calls
    assert "-n otel-splunk get configmap custom-collector-otel-agent" in calls


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("--collector-release", "wrong-release"), "--collector-release"),
        (("--collector-namespace", "wrong-namespace"), "--collector-namespace"),
    ],
)
def test_live_validation_rejects_collector_cli_override_mismatch(
    args: tuple[str, str], expected: str, tmp_path: Path
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        *args,
    )
    assert validated.returncode == 1
    assert f"{expected} does not match rendered metadata" in combined_output(validated)


def test_live_validation_rejects_receiver_port_drift(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    relay = load_yaml_or_json(relay_file.read_text(encoding="utf-8"), source="relay")
    relabels = relay["receivers"]["prometheus/isovalent_cilium"]["config"][
        "scrape_configs"
    ][0]["relabel_configs"]
    replacement = next(rule for rule in relabels if "replacement" in rule)
    replacement["replacement"] = "$1:9999"
    relay_file.write_text(dump_yaml(relay, sort_keys=True), encoding="utf-8")
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
        },
    )
    assert validated.returncode == 1
    assert "receiver/relabel/port configuration drifted" in combined_output(validated)


def test_live_validation_rejects_tetragon_cluster_resource_drift(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    relay = load_yaml_or_json(relay_file.read_text(encoding="utf-8"), source="relay")
    relay["receivers"]["filelog/tetragon"]["resource"]["k8s.cluster.name"] = (
        "unrelated-cluster"
    )
    relay_file.write_text(dump_yaml(relay, sort_keys=True), encoding="utf-8")
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
        },
    )
    assert validated.returncode == 1
    assert "filelog index/sourcetype/resource configuration drifted" in combined_output(
        validated
    )


def test_live_validation_probes_every_ready_pod_and_fails_on_one_broken_endpoint(
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    pods = {
        "items": [
            {
                "metadata": {"name": "ready-pod"},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
            },
            {
                "metadata": {"name": "broken-pod"},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
            },
        ]
    }
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
            "FAKE_PODS_JSON": json.dumps(pods),
            "FAIL_RAW_MATCH": "/pods/broken-pod:2112/proxy/metrics",
        },
    )
    assert validated.returncode == 1
    assert "tetragon:2112 has a selected pod with an unreachable" in combined_output(
        validated
    )
    calls = call_log.read_text(encoding="utf-8")
    assert "/pods/ready-pod:2112/proxy/metrics" in calls
    assert "/pods/broken-pod:2112/proxy/metrics" in calls


def test_live_validation_rejects_any_unready_selected_pod(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    rendered = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert rendered.returncode == 0, combined_output(rendered)
    bin_dir, call_log = fake_live_tools(tmp_path)
    relay_file = write_live_agent_relay(output, tmp_path / "agent-relay.yaml")
    pods = {
        "items": [
            {
                "metadata": {"name": "ready-pod"},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
            },
            {
                "metadata": {"name": "unready-pod"},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "False"}],
                },
            },
        ]
    }
    validated = run_validate(
        output,
        "--live",
        "--allow-current-context",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "KUBECTL_CALL_LOG": str(call_log),
            "FAKE_AGENT_RELAY_FILE": str(relay_file),
            "FAKE_PODS_JSON": json.dumps(pods),
        },
    )
    assert validated.returncode == 1
    assert "requires every selected pod to be Running and Ready" in combined_output(
        validated
    )
