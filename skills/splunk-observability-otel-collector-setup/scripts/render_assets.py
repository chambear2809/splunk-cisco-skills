#!/usr/bin/env python3
"""Render Splunk Observability OTel Collector deployment assets."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
from pathlib import Path


def str_bool(value: str) -> bool:
    return value == "true"


def yaml_scalar(value: str | int | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value)


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def write_text(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | 0o111)


def bash_array(name: str, values: list[str]) -> str:
    if not values:
        return f"{name}=()\n"
    body = "\n".join(f"    {shell_quote(value)}" for value in values)
    return f"{name}=(\n{body}\n)\n"


def secret_name(release_name: str) -> str:
    return f"{release_name}-splunk"


def bool_arg(parser: argparse.ArgumentParser, name: str, default: bool) -> None:
    parser.add_argument(
        f"--{name}",
        choices=("true", "false"),
        default="true" if default else "false",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--realm", required=True)
    parser.add_argument("--render-k8s", action="store_true")
    parser.add_argument("--render-linux", action="store_true")
    parser.add_argument("--render-platform-hec-helper", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")

    parser.add_argument("--namespace", default="splunk-otel")
    parser.add_argument("--release-name", default="splunk-otel-collector")
    parser.add_argument("--cluster-name", default="")
    parser.add_argument("--distribution", default="")
    parser.add_argument("--cloud-provider", default="")
    parser.add_argument("--chart-version", default="")
    parser.add_argument("--kube-context", default="")
    parser.add_argument("--o11y-ingest-url", default="")
    parser.add_argument("--o11y-api-url", default="")
    parser.add_argument("--platform-hec-url", default="")
    parser.add_argument("--platform-hec-index", default="k8s_logs")
    parser.add_argument("--hec-platform", choices=("cloud", "enterprise"), default="cloud")
    parser.add_argument("--hec-token-name", default="splunk_otel_k8s_logs")
    parser.add_argument("--hec-description", default="Managed by splunk-observability-otel-collector-setup")
    parser.add_argument("--hec-default-index", default="")
    parser.add_argument("--hec-allowed-indexes", default="")
    parser.add_argument("--hec-source", default="")
    parser.add_argument("--hec-sourcetype", default="")
    parser.add_argument("--hec-use-ack", choices=("true", "false"), default="false")
    parser.add_argument("--hec-port", default="8088")
    parser.add_argument("--hec-enable-ssl", choices=("true", "false"), default="true")
    parser.add_argument("--hec-splunk-home", default="/opt/splunk")
    parser.add_argument("--hec-app-name", default="splunk_httpinput")
    parser.add_argument("--hec-restart-splunk", choices=("true", "false"), default="true")
    parser.add_argument(
        "--hec-s2s-indexes-validation",
        choices=("disabled", "disabled_for_internal", "enabled_for_all"),
        default="disabled_for_internal",
    )
    parser.add_argument("--eks-cluster-name", default="")
    parser.add_argument("--aws-region", default="")
    parser.add_argument("--priority-class-name", default="")
    parser.add_argument("--gateway-replicas", default="1")
    bool_arg(parser, "gateway-enabled", False)
    bool_arg(parser, "render-priority-class", False)
    bool_arg(parser, "windows-nodes", False)
    bool_arg(parser, "cluster-receiver-enabled", True)
    bool_arg(parser, "agent-host-network", True)
    bool_arg(parser, "platform-persistent-queue-enabled", False)
    parser.add_argument("--platform-persistent-queue-path", default="/var/addon/splunk/exporter_queue")
    bool_arg(parser, "platform-fsync-enabled", False)

    parser.add_argument("--o11y-token-file", default="")
    parser.add_argument("--platform-hec-token-file", default="")

    parser.add_argument("--execution", choices=("local", "ssh"), default="local")
    parser.add_argument("--linux-host", default="")
    parser.add_argument("--ssh-user", default="")
    parser.add_argument("--ssh-port", default="22")
    parser.add_argument("--ssh-key-file", default="")
    parser.add_argument("--linux-mode", choices=("agent", "gateway"), default="agent")
    parser.add_argument("--memory-mib", default="512")
    parser.add_argument("--listen-interface", default="0.0.0.0")
    parser.add_argument("--linux-api-url", default="")
    parser.add_argument("--linux-ingest-url", default="")
    parser.add_argument("--linux-trace-url", default="")
    parser.add_argument("--linux-hec-url", default="")
    parser.add_argument("--collector-config", default="")
    parser.add_argument("--service-user", default="")
    parser.add_argument("--service-group", default="")
    bool_arg(parser, "skip-collector-repo", False)
    parser.add_argument("--repo-channel", choices=("primary", "beta", "test"), default="primary")
    parser.add_argument("--deployment-environment", default="")
    parser.add_argument("--service-name", default="")
    parser.add_argument(
        "--instrumentation-mode",
        choices=("none", "preload", "systemd"),
        default="systemd",
    )
    parser.add_argument("--instrumentation-sdks", default="")
    parser.add_argument("--npm-path", default="")
    parser.add_argument("--otlp-endpoint", default="")
    parser.add_argument("--otlp-endpoint-protocol", default="")
    parser.add_argument("--metrics-exporter", default="")
    parser.add_argument("--logs-exporter", default="")
    parser.add_argument("--instrumentation-version", default="")
    parser.add_argument("--collector-version", default="")
    parser.add_argument("--godebug", default="")
    parser.add_argument("--obi-version", default="")
    parser.add_argument("--obi-install-dir", default="")
    parser.add_argument(
        "--installer-url",
        default="https://dl.observability.splunkcloud.com/splunk-otel-collector.sh",
    )

    bool_arg(parser, "enable-metrics", True)
    bool_arg(parser, "enable-traces", True)
    bool_arg(parser, "enable-logs", True)
    bool_arg(parser, "enable-profiling", True)
    bool_arg(parser, "enable-events", True)
    bool_arg(parser, "enable-discovery", True)
    bool_arg(parser, "enable-autoinstrumentation", True)
    bool_arg(parser, "enable-prometheus-autodetect", False)
    bool_arg(parser, "enable-istio-autodetect", False)
    bool_arg(parser, "enable-obi", False)
    bool_arg(parser, "enable-operator-crds", True)
    bool_arg(parser, "enable-certmanager", False)
    bool_arg(parser, "enable-secure-app", False)
    return parser.parse_args()


def rendered_plan(args: argparse.Namespace) -> dict[str, object]:
    output_dir = Path(args.output_dir)
    commands: list[str] = []
    preparation_commands: list[str] = []
    if args.render_platform_hec_helper:
        preparation_commands.extend(
            [
                f"bash {output_dir / 'platform-hec' / 'render-hec-service.sh'}",
                f"bash {output_dir / 'platform-hec' / 'apply-hec-service.sh'}",
            ]
        )
    if args.render_k8s:
        if args.eks_cluster_name and args.aws_region:
            commands.append(f"bash {output_dir / 'k8s' / 'eks-update-kubeconfig.sh'}")
        if str_bool(args.render_priority_class) and args.priority_class_name:
            commands.append(f"bash {output_dir / 'k8s' / 'priority-class.sh'}")
        commands.extend(
            [
                f"bash {output_dir / 'k8s' / 'create-secret.sh'}",
                f"bash {output_dir / 'k8s' / 'helm-install.sh'}",
            ]
        )
    if args.render_linux:
        linux_script = "install-ssh.sh" if args.execution == "ssh" else "install-local.sh"
        commands.append(f"bash {output_dir / 'linux' / linux_script}")
    return {
        "output_dir": str(output_dir),
        "render_k8s": args.render_k8s,
        "render_linux": args.render_linux,
        "render_platform_hec_helper": args.render_platform_hec_helper,
        "preparation_commands": preparation_commands,
        "apply_commands": commands,
        "warnings": warnings(args),
    }


def platform_hec_token_configured(args: argparse.Namespace) -> bool:
    return bool(args.platform_hec_token_file) or bool(args.render_platform_hec_helper)


def platform_hec_token_path(args: argparse.Namespace, output_dir: Path) -> str:
    if args.platform_hec_token_file:
        return args.platform_hec_token_file
    return str(output_dir / "platform-hec" / ".splunk_platform_hec_token")


def platform_logs_enabled(args: argparse.Namespace) -> bool:
    return (
        str_bool(args.enable_logs)
        and bool(args.platform_hec_url)
        and platform_hec_token_configured(args)
    )


def warnings(args: argparse.Namespace) -> list[str]:
    result: list[str] = []
    logs_enabled = platform_logs_enabled(args)
    if str_bool(args.enable_logs) and args.render_k8s and not logs_enabled:
        result.append(
            "Kubernetes container logs require --platform-hec-url and --platform-hec-token-file; rendered chart values leave Splunk Platform logs disabled."
        )
    if args.render_platform_hec_helper and args.render_k8s and args.platform_hec_url:
        result.append(
            "Run platform-hec/apply-hec-service.sh before k8s/create-secret.sh if the Splunk Platform HEC token file does not already exist."
        )
    if args.render_platform_hec_helper and args.render_k8s and not args.platform_hec_url:
        result.append(
            "The Splunk Platform HEC helper is rendered, but Kubernetes container logs remain disabled until --platform-hec-url is supplied."
        )
    if args.platform_hec_token_file and args.render_linux:
        result.append(
            "The Linux installer path uses the Observability access token; platform HEC token handling is Kubernetes-only in this workflow."
        )
    if args.distribution == "eks/fargate" and args.render_k8s and not str_bool(args.gateway_enabled):
        result.append(
            "EKS Fargate does not support the agent DaemonSet; gateway.enabled is rendered true so applications have a collector endpoint."
        )
    if str_bool(args.windows_nodes) and args.render_k8s:
        result.append(
            "Windows node support normally needs a separate Helm release; disable one cluster receiver if you also install a Linux release."
        )
    if str_bool(args.enable_autoinstrumentation) and args.render_k8s and not str_bool(args.enable_operator_crds):
        result.append(
            "Auto-instrumentation is enabled but operator CRD installation is disabled; install OpenTelemetry Operator CRDs before applying."
        )
    if str_bool(args.enable_certmanager):
        result.append(
            "certmanager.enabled is deprecated in the chart; prefer operator admission webhook auto-generated certificates unless your cluster requires cert-manager."
        )
    if str_bool(args.enable_obi):
        result.append(
            "OBI is enabled; confirm cluster or host privilege requirements before applying."
        )
    return result


def k8s_values(args: argparse.Namespace) -> str:
    logs_enabled = platform_logs_enabled(args)
    gateway_enabled = str_bool(args.gateway_enabled) or args.distribution == "eks/fargate"
    lines = [
        "# Generated by splunk-observability-otel-collector-setup.",
        "# Token values are intentionally omitted; use k8s/create-secret.sh.",
        f"clusterName: {yaml_scalar(args.cluster_name)}",
        f"cloudProvider: {yaml_scalar(args.cloud_provider)}",
        f"distribution: {yaml_scalar(args.distribution)}",
        f"environment: {yaml_scalar(args.deployment_environment)}",
        f"isWindows: {yaml_scalar(str_bool(args.windows_nodes))}",
        f"priorityClassName: {yaml_scalar(args.priority_class_name)}",
        "",
        "secret:",
        "  create: false",
        f"  name: {yaml_scalar(secret_name(args.release_name))}",
        "",
        "splunkObservability:",
        f"  realm: {yaml_scalar(args.realm)}",
        '  accessToken: ""',
        f"  ingestUrl: {yaml_scalar(args.o11y_ingest_url)}",
        f"  apiUrl: {yaml_scalar(args.o11y_api_url)}",
        f"  metricsEnabled: {yaml_scalar(str_bool(args.enable_metrics))}",
        f"  tracesEnabled: {yaml_scalar(str_bool(args.enable_traces))}",
        f"  profilingEnabled: {yaml_scalar(str_bool(args.enable_profiling))}",
        f"  secureAppEnabled: {yaml_scalar(str_bool(args.enable_secure_app))}",
        "",
        "splunkPlatform:",
        f"  endpoint: {yaml_scalar(args.platform_hec_url if logs_enabled else '')}",
        '  token: ""',
        f"  index: {yaml_scalar(args.platform_hec_index if logs_enabled else '')}",
        f"  logsEnabled: {yaml_scalar(logs_enabled)}",
        "  metricsEnabled: false",
        "  tracesEnabled: false",
        "  insecureSkipVerify: false",
        "  sendingQueue:",
        "    persistentQueue:",
        f"      enabled: {yaml_scalar(str_bool(args.platform_persistent_queue_enabled))}",
        f"      storagePath: {yaml_scalar(args.platform_persistent_queue_path)}",
        f"  fsyncEnabled: {yaml_scalar(str_bool(args.platform_fsync_enabled))}",
        "",
        "clusterReceiver:",
        f"  enabled: {yaml_scalar(str_bool(args.cluster_receiver_enabled))}",
        f"  eventsEnabled: {yaml_scalar(str_bool(args.enable_events))}",
        f"  priorityClassName: {yaml_scalar(args.priority_class_name)}",
        "",
        "featureGates:",
        f"  sendK8sEventsToSplunkO11y: {yaml_scalar(str_bool(args.enable_events))}",
        "",
        "logsCollection:",
        "  containers:",
        f"    enabled: {yaml_scalar(logs_enabled)}",
        "  journald:",
        "    enabled: false",
        "",
        "agent:",
        f"  hostNetwork: {yaml_scalar(str_bool(args.agent_host_network))}",
        "  discovery:",
        f"    enabled: {yaml_scalar(str_bool(args.enable_discovery))}",
        "",
        "autodetect:",
        f"  prometheus: {yaml_scalar(str_bool(args.enable_prometheus_autodetect))}",
        f"  istio: {yaml_scalar(str_bool(args.enable_istio_autodetect))}",
        "",
        "operator:",
        f"  enabled: {yaml_scalar(str_bool(args.enable_autoinstrumentation))}",
        "",
        "operatorcrds:",
        f"  install: {yaml_scalar(str_bool(args.enable_operator_crds) and str_bool(args.enable_autoinstrumentation))}",
        "",
        "certmanager:",
        f"  enabled: {yaml_scalar(str_bool(args.enable_certmanager))}",
        "",
        "instrumentation:",
        f"  enabled: {yaml_scalar(str_bool(args.enable_autoinstrumentation))}",
        "",
        "obi:",
        f"  enabled: {yaml_scalar(str_bool(args.enable_obi))}",
        "",
        "gateway:",
        f"  enabled: {yaml_scalar(gateway_enabled)}",
        f"  replicaCount: {yaml_scalar(int(args.gateway_replicas))}",
        f"  priorityClassName: {yaml_scalar(args.priority_class_name)}",
        "",
    ]
    if str_bool(args.windows_nodes):
        lines.extend(
            [
                "image:",
                "  otelcol:",
                '    repository: "quay.io/signalfx/splunk-otel-collector-windows"',
                "readinessProbe:",
                "  initialDelaySeconds: 60",
                "livenessProbe:",
                "  initialDelaySeconds: 60",
                "",
            ]
        )
    return "\n".join(lines)


def render_k8s(args: argparse.Namespace, output_dir: Path) -> None:
    k8s_dir = output_dir / "k8s"
    if k8s_dir.exists():
        shutil.rmtree(k8s_dir)
    k8s_dir.mkdir(parents=True, exist_ok=True)

    values_path = k8s_dir / "values.yaml"
    write_text(values_path, k8s_values(args))

    logs_enabled = platform_logs_enabled(args)
    kube_prefix = ""
    if args.kube_context:
        kube_prefix = f"--context {shell_quote(args.kube_context)} "
    token_file = args.o11y_token_file or "/path/to/splunk_o11y_access_token"
    platform_file = platform_hec_token_path(args, output_dir) if logs_enabled else "/path/to/splunk_platform_hec_token"

    if str_bool(args.render_priority_class) and args.priority_class_name:
        write_text(
            k8s_dir / "priority-class.sh",
            f"""#!/usr/bin/env bash
set -euo pipefail

cat <<'YAML' | kubectl {kube_prefix}apply -f -
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: {yaml_scalar(args.priority_class_name)}
value: 1000000
globalDefault: false
description: "Higher priority class for the Splunk Distribution of OpenTelemetry Collector pods."
YAML
""",
            executable=True,
        )

    write_text(
        k8s_dir / "create-secret.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

namespace={shell_quote(args.namespace)}
secret_name={shell_quote(secret_name(args.release_name))}
o11y_token_file={shell_quote(token_file)}
platform_hec_token_file={shell_quote(platform_file)}
platform_logs_enabled={shell_quote('true' if logs_enabled else 'false')}

if [[ ! -r "${{o11y_token_file}}" ]]; then
    echo "ERROR: Observability token file is not readable: ${{o11y_token_file}}" >&2
    exit 1
fi
if [[ "${{platform_logs_enabled}}" == "true" && ! -r "${{platform_hec_token_file}}" ]]; then
    echo "ERROR: Platform HEC token file is not readable: ${{platform_hec_token_file}}" >&2
    exit 1
fi

kubectl {kube_prefix}create namespace "${{namespace}}" --dry-run=client -o yaml | kubectl {kube_prefix}apply -f -

secret_args=(
    create secret generic "${{secret_name}}"
    --namespace "${{namespace}}"
    "--from-file=splunk_observability_access_token=${{o11y_token_file}}"
)
if [[ "${{platform_logs_enabled}}" == "true" ]]; then
    secret_args+=("--from-file=splunk_platform_hec_token=${{platform_hec_token_file}}")
fi

kubectl {kube_prefix}"${{secret_args[@]}}" --dry-run=client -o yaml | kubectl {kube_prefix}apply -f -
""",
        executable=True,
    )

    chart_version_line = ""
    if args.chart_version:
        chart_version_line = f"    --version {shell_quote(args.chart_version)} \\\n"
    helm_context_line = ""
    if args.kube_context:
        helm_context_line = f"    --kube-context {shell_quote(args.kube_context)} \\\n"

    write_text(
        k8s_dir / "helm-install.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
namespace={shell_quote(args.namespace)}
release_name={shell_quote(args.release_name)}

helm repo add splunk-otel-collector-chart https://signalfx.github.io/splunk-otel-collector-chart --force-update
helm repo update splunk-otel-collector-chart
helm upgrade --install "${{release_name}}" splunk-otel-collector-chart/splunk-otel-collector \\
    --namespace "${{namespace}}" \\
    --create-namespace \\
{helm_context_line}{chart_version_line}    -f "${{script_dir}}/values.yaml"
""",
        executable=True,
    )

    status_context = f"--context {shell_quote(args.kube_context)} " if args.kube_context else ""
    # `helm status` honors --kube-context with the same flag name as install.
    # Without this propagation, status.sh would query the user's current
    # kubectl context even when install was pinned to a different cluster.
    helm_status_context = f" --kube-context {shell_quote(args.kube_context)}" if args.kube_context else ""
    gateway_enabled = str_bool(args.gateway_enabled) or args.distribution == "eks/fargate"
    agent_rollout = f"""kubectl {status_context}-n "${{namespace}}" rollout status daemonset/"${{release_name}}-agent" --timeout=180s \\
    || kubectl {status_context}-n "${{namespace}}" rollout status daemonset/"${{release_name}}-splunk-otel-collector-agent" --timeout=180s"""
    if gateway_enabled:
        agent_rollout = f"""kubectl {status_context}-n "${{namespace}}" rollout status deployment/"${{release_name}}-gateway" --timeout=180s \\
    || kubectl {status_context}-n "${{namespace}}" rollout status deployment/"${{release_name}}-splunk-otel-collector" --timeout=180s"""
    write_text(
        k8s_dir / "status.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

namespace={shell_quote(args.namespace)}
release_name={shell_quote(args.release_name)}

helm status "${{release_name}}" --namespace "${{namespace}}"{helm_status_context}
kubectl {status_context}-n "${{namespace}}" get pods -l app.kubernetes.io/instance="${{release_name}}"
{agent_rollout}
""",
        executable=True,
    )

    if args.eks_cluster_name and args.aws_region:
        write_text(
            k8s_dir / "eks-update-kubeconfig.sh",
            f"""#!/usr/bin/env bash
set -euo pipefail

aws eks update-kubeconfig --name {shell_quote(args.eks_cluster_name)} --region {shell_quote(args.aws_region)}
""",
            executable=True,
        )

    write_text(
        k8s_dir / "README.md",
        f"""# Splunk Observability Kubernetes OTel Collector

Review `values.yaml`, then run:

```bash
bash create-secret.sh
bash helm-install.sh
```

Rendered namespace: `{args.namespace}`
Rendered release: `{args.release_name}`
Secret name: `{secret_name(args.release_name)}`
""",
    )


def linux_installer_args(args: argparse.Namespace) -> list[str]:
    installer_args = [
        "--realm",
        args.realm,
        "--memory",
        args.memory_mib,
        "--mode",
        args.linux_mode,
        "--listen-interface",
        args.listen_interface,
    ]
    if args.linux_api_url:
        installer_args.extend(["--api-url", args.linux_api_url])
    if args.linux_ingest_url:
        installer_args.extend(["--ingest-url", args.linux_ingest_url])
    if args.linux_trace_url:
        installer_args.extend(["--trace-url", args.linux_trace_url])
    if args.linux_hec_url:
        installer_args.extend(["--hec-url", args.linux_hec_url])
    if args.collector_config:
        installer_args.extend(["--collector-config", args.collector_config])
    if args.service_user:
        installer_args.extend(["--service-user", args.service_user])
    if args.service_group:
        installer_args.extend(["--service-group", args.service_group])
    if str_bool(args.skip_collector_repo):
        installer_args.append("--skip-collector-repo")
    if args.repo_channel == "beta":
        installer_args.append("--beta")
    elif args.repo_channel == "test":
        installer_args.append("--test")
    if args.godebug:
        installer_args.extend(["--godebug", args.godebug])
    if args.deployment_environment:
        installer_args.extend(["--deployment-environment", args.deployment_environment])
    if args.service_name:
        installer_args.extend(["--service-name", args.service_name])
    if args.collector_version:
        installer_args.extend(["--collector-version", args.collector_version])
    if str_bool(args.enable_metrics):
        installer_args.append("--enable-metrics")
    else:
        installer_args.append("--disable-metrics")
    if args.metrics_exporter:
        installer_args.extend(["--metrics-exporter", args.metrics_exporter])
    if args.logs_exporter:
        installer_args.extend(["--logs-exporter", args.logs_exporter])
    elif str_bool(args.enable_logs):
        installer_args.extend(["--logs-exporter", "otlp"])
    else:
        installer_args.extend(["--logs-exporter", "none"])
    if str_bool(args.enable_profiling):
        installer_args.extend(["--enable-profiler", "--enable-profiler-memory"])
    else:
        installer_args.extend(["--disable-profiler", "--disable-profiler-memory"])
    if str_bool(args.enable_discovery):
        installer_args.append("--discovery")
    if str_bool(args.enable_autoinstrumentation):
        if args.instrumentation_mode == "systemd":
            installer_args.append("--with-systemd-instrumentation")
        elif args.instrumentation_mode == "preload":
            installer_args.append("--with-instrumentation")
        if args.instrumentation_sdks:
            installer_args.extend(["--with-instrumentation-sdk", args.instrumentation_sdks])
        if args.npm_path:
            installer_args.extend(["--npm-path", args.npm_path])
        if args.otlp_endpoint:
            installer_args.extend(["--otlp-endpoint", args.otlp_endpoint])
        if args.otlp_endpoint_protocol:
            installer_args.extend(["--otlp-endpoint-protocol", args.otlp_endpoint_protocol])
        if args.instrumentation_version:
            installer_args.extend(["--instrumentation-version", args.instrumentation_version])
    else:
        installer_args.extend(["--without-instrumentation", "--without-systemd-instrumentation"])
    if str_bool(args.enable_obi):
        installer_args.append("--with-obi")
        if args.obi_version:
            installer_args.extend(["--obi-version", args.obi_version])
        if args.obi_install_dir:
            installer_args.extend(["--obi-install-dir", args.obi_install_dir])
    else:
        installer_args.append("--without-obi")
    return installer_args


def render_linux(args: argparse.Namespace, output_dir: Path) -> None:
    linux_dir = output_dir / "linux"
    if linux_dir.exists():
        shutil.rmtree(linux_dir)
    linux_dir.mkdir(parents=True, exist_ok=True)

    token_file = args.o11y_token_file or "/path/to/splunk_o11y_access_token"
    installer_args = linux_installer_args(args)
    installer_array = bash_array("installer_args", installer_args)

    write_text(
        linux_dir / "install-local.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

TOKEN_FILE="${{SPLUNK_O11Y_TOKEN_FILE:-}}"
if [[ -z "${{TOKEN_FILE}}" ]]; then
    TOKEN_FILE={shell_quote(token_file)}
fi
INSTALLER_URL="${{SPLUNK_OTEL_INSTALLER_URL:-{args.installer_url}}}"

if [[ ! -r "${{TOKEN_FILE}}" ]]; then
    echo "ERROR: Observability token file is not readable: ${{TOKEN_FILE}}" >&2
    exit 1
fi

installer_path="$(mktemp)"
trap 'rm -f "${{installer_path}}"' EXIT
curl -fsSL "${{INSTALLER_URL}}" -o "${{installer_path}}"
chmod 700 "${{installer_path}}"

{installer_array}

if command -v sudo >/dev/null 2>&1 && [[ "$(id -u)" -ne 0 ]]; then
    sudo env VERIFY_ACCESS_TOKEN=false sh "${{installer_path}}" "${{installer_args[@]}}" < "${{TOKEN_FILE}}"
else
    env VERIFY_ACCESS_TOKEN=false sh "${{installer_path}}" "${{installer_args[@]}}" < "${{TOKEN_FILE}}"
fi
""",
        executable=True,
    )

    ssh_host = args.linux_host or "linux-host.example.com"
    ssh_user = args.ssh_user or "ec2-user"
    ssh_key = args.ssh_key_file
    ssh_key_block = ""
    if ssh_key:
        ssh_key_block = f'    ssh_args+=(-i {shell_quote(ssh_key)})\n    scp_args+=(-i {shell_quote(ssh_key)})\n'

    write_text(
        linux_dir / "install-ssh.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

TOKEN_FILE="${{SPLUNK_O11Y_TOKEN_FILE:-}}"
if [[ -z "${{TOKEN_FILE}}" ]]; then
    TOKEN_FILE={shell_quote(token_file)}
fi
LINUX_HOST="${{SPLUNK_OTEL_LINUX_HOST:-{ssh_host}}}"
SSH_USER="${{SPLUNK_OTEL_SSH_USER:-{ssh_user}}}"
SSH_PORT="${{SPLUNK_OTEL_SSH_PORT:-{args.ssh_port}}}"
INSTALLER_URL="${{SPLUNK_OTEL_INSTALLER_URL:-{args.installer_url}}}"

if [[ ! -r "${{TOKEN_FILE}}" ]]; then
    echo "ERROR: Observability token file is not readable: ${{TOKEN_FILE}}" >&2
    exit 1
fi
if [[ -z "${{LINUX_HOST}}" || -z "${{SSH_USER}}" ]]; then
    echo "ERROR: LINUX_HOST and SSH_USER are required for SSH install." >&2
    exit 1
fi

ssh_target="${{SSH_USER}}@${{LINUX_HOST}}"
remote_token="/tmp/splunk-o11y-access-token-$RANDOM-$$"

ssh_args=(-p "${{SSH_PORT}}")
scp_args=(-P "${{SSH_PORT}}")
{ssh_key_block}

{installer_array}
remote_args=""
for arg in "${{installer_args[@]}}"; do
    printf -v quoted '%q' "${{arg}}"
    remote_args+=" ${{quoted}}"
done

scp "${{scp_args[@]}}" "${{TOKEN_FILE}}" "${{ssh_target}}:${{remote_token}}"
remote_command=$(cat <<REMOTE
set -euo pipefail
chmod 600 "${{remote_token}}"
remote_installer=\\$(mktemp /tmp/splunk-otel-installer.XXXXXX)
trap 'rm -f "${{remote_token}}" "\\${{remote_installer}}"' EXIT
curl -fsSL "${{INSTALLER_URL}}" -o "\\${{remote_installer}}"
chmod 700 "\\${{remote_installer}}"
if command -v sudo >/dev/null 2>&1 && [ "\\$(id -u)" -ne 0 ]; then
    sudo env VERIFY_ACCESS_TOKEN=false sh "\\${{remote_installer}}"${{remote_args}} < "${{remote_token}}"
else
    env VERIFY_ACCESS_TOKEN=false sh "\\${{remote_installer}}"${{remote_args}} < "${{remote_token}}"
fi
REMOTE
)
ssh "${{ssh_args[@]}}" "${{ssh_target}}" "bash -s" <<< "${{remote_command}}"
""",
        executable=True,
    )

    write_text(
        linux_dir / "status-local.sh",
        """#!/usr/bin/env bash
set -euo pipefail

if command -v systemctl >/dev/null 2>&1; then
    systemctl is-active splunk-otel-collector
    systemctl status --no-pager splunk-otel-collector
else
    service splunk-otel-collector status
fi
""",
        executable=True,
    )

    ssh_key_status_block = ""
    if ssh_key:
        ssh_key_status_block = f'    ssh_args+=(-i {shell_quote(ssh_key)})\n'
    write_text(
        linux_dir / "status-ssh.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

LINUX_HOST="${{SPLUNK_OTEL_LINUX_HOST:-{ssh_host}}}"
SSH_USER="${{SPLUNK_OTEL_SSH_USER:-{ssh_user}}}"
SSH_PORT="${{SPLUNK_OTEL_SSH_PORT:-{args.ssh_port}}}"
ssh_args=(-p "${{SSH_PORT}}")
{ssh_key_status_block}
ssh "${{ssh_args[@]}}" "${{SSH_USER}}@${{LINUX_HOST}}" 'systemctl is-active splunk-otel-collector && systemctl status --no-pager splunk-otel-collector'
""",
        executable=True,
    )

    write_text(
        linux_dir / "README.md",
        f"""# Splunk Observability Linux OTel Collector

Review the installer wrapper before applying.

Local apply:

```bash
bash install-local.sh
```

SSH apply:

```bash
bash install-ssh.sh
```

Rendered execution mode: `{args.execution}`
Rendered Linux collector mode: `{args.linux_mode}`
""",
    )


def hec_default_index(args: argparse.Namespace) -> str:
    return args.hec_default_index or args.platform_hec_index or "k8s_logs"


def hec_allowed_indexes(args: argparse.Namespace) -> str:
    return args.hec_allowed_indexes or hec_default_index(args)


def hec_setup_script() -> Path:
    return Path(__file__).resolve().parents[3] / "skills/splunk-hec-service-setup/scripts/setup.sh"


def hec_setup_args(args: argparse.Namespace, output_dir: Path, phase: str) -> list[str]:
    token_file = platform_hec_token_path(args, output_dir)
    setup_args = [
        "--platform",
        args.hec_platform,
        "--phase",
        phase,
        "--output-dir",
        str(output_dir / "platform-hec-service-rendered"),
        "--splunk-home",
        args.hec_splunk_home,
        "--app-name",
        args.hec_app_name,
        "--token-name",
        args.hec_token_name,
        "--description",
        args.hec_description,
        "--default-index",
        hec_default_index(args),
        "--allowed-indexes",
        hec_allowed_indexes(args),
        "--source",
        args.hec_source,
        "--sourcetype",
        args.hec_sourcetype,
        "--port",
        args.hec_port,
        "--enable-ssl",
        args.hec_enable_ssl,
        "--use-ack",
        args.hec_use_ack,
        "--s2s-indexes-validation",
        args.hec_s2s_indexes_validation,
        "--restart-splunk",
        args.hec_restart_splunk,
    ]
    if args.hec_platform == "cloud":
        setup_args.extend(["--write-token-file", token_file])
    else:
        setup_args.extend(["--token-file", token_file])
    return setup_args


def render_hec_helper_script(path: Path, setup_args: list[str], title: str) -> None:
    setup_path = str(hec_setup_script())
    args_array = bash_array("hec_args", setup_args)
    write_text(
        path,
        f"""#!/usr/bin/env bash
set -euo pipefail

# {title}
hec_setup={shell_quote(setup_path)}

{args_array}

bash "${{hec_setup}}" "${{hec_args[@]}}"
""",
        executable=True,
    )


def render_platform_hec_helper(args: argparse.Namespace, output_dir: Path) -> None:
    hec_dir = output_dir / "platform-hec"
    if hec_dir.exists():
        shutil.rmtree(hec_dir)
    hec_dir.mkdir(parents=True, exist_ok=True)

    token_file = platform_hec_token_path(args, output_dir)
    hec_render_dir = output_dir / "platform-hec-service-rendered" / "hec-service"

    render_hec_helper_script(
        hec_dir / "render-hec-service.sh",
        hec_setup_args(args, output_dir, "render"),
        "Render reusable Splunk Platform HEC service assets.",
    )
    render_hec_helper_script(
        hec_dir / "apply-hec-service.sh",
        hec_setup_args(args, output_dir, "apply"),
        "Create or update the Splunk Platform HEC token and write/read the token file.",
    )
    render_hec_helper_script(
        hec_dir / "status-hec-service.sh",
        hec_setup_args(args, output_dir, "status"),
        "Check the rendered Splunk Platform HEC service state.",
    )

    write_text(
        hec_dir / "README.md",
        f"""# Splunk Platform HEC Helper

This folder bridges the OTel Collector Kubernetes log path to the reusable
`splunk-hec-service-setup` skill.

Run this first to render the HEC service assets:

```bash
bash render-hec-service.sh
```

Review the HEC assets under:

`{hec_render_dir}`

Then create or update the token:

```bash
bash apply-hec-service.sh
```

Token file for the OTel Collector Kubernetes Secret:

`{token_file}`

Use that same path with `--platform-hec-token-file` when rendering or applying
the OTel Collector. For Splunk Cloud, ACS creates the token and writes it to the
file. For Splunk Enterprise, the HEC service helper reads or creates the local
token file before writing `inputs.conf`.

Rendered HEC platform: `{args.hec_platform}`
Rendered HEC token name: `{args.hec_token_name}`
Rendered HEC default index: `{hec_default_index(args)}`
Rendered HEC allowed indexes: `{hec_allowed_indexes(args)}`
""",
    )


def metadata(args: argparse.Namespace, output_dir: Path) -> dict[str, object]:
    return {
        "skill": "splunk-observability-otel-collector-setup",
        "realm": args.realm,
        "kubernetes": {
            "rendered": args.render_k8s,
            "namespace": args.namespace,
            "release_name": args.release_name,
            "cluster_name": args.cluster_name,
            "distribution": args.distribution,
            "windows_nodes": str_bool(args.windows_nodes),
            "cluster_receiver_enabled": str_bool(args.cluster_receiver_enabled),
            "operator_crds_install": str_bool(args.enable_operator_crds)
            and str_bool(args.enable_autoinstrumentation),
            "priority_class_name": args.priority_class_name,
            "gateway_enabled": str_bool(args.gateway_enabled) or args.distribution == "eks/fargate",
            "platform_logs_enabled": platform_logs_enabled(args),
            "secret_name": secret_name(args.release_name),
        },
        "platform_hec": {
            "helper_rendered": args.render_platform_hec_helper,
            "platform": args.hec_platform,
            "token_name": args.hec_token_name,
            "default_index": hec_default_index(args),
            "allowed_indexes": hec_allowed_indexes(args),
            "token_file": platform_hec_token_path(args, output_dir)
            if platform_hec_token_configured(args)
            else "",
        },
        "linux": {
            "rendered": args.render_linux,
            "execution": args.execution,
            "linux_mode": args.linux_mode,
            "instrumentation_mode": args.instrumentation_mode,
            "repo_channel": args.repo_channel,
            "skip_collector_repo": str_bool(args.skip_collector_repo),
        },
        "signals": {
            "metrics": str_bool(args.enable_metrics),
            "traces": str_bool(args.enable_traces),
            "logs": str_bool(args.enable_logs),
            "profiling": str_bool(args.enable_profiling),
            "events": str_bool(args.enable_events),
            "discovery": str_bool(args.enable_discovery),
            "autoinstrumentation": str_bool(args.enable_autoinstrumentation),
            "obi": str_bool(args.enable_obi),
        },
        "warnings": warnings(args),
    }


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)

    if args.dry_run:
        plan = rendered_plan(args)
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("Splunk Observability OTel Collector render plan")
            print(f"Output directory: {plan['output_dir']}")
            for warning in plan["warnings"]:
                print(f"Warning: {warning}")
            for command in plan["preparation_commands"]:
                print(f"Preparation command: {command}")
            for command in plan["apply_commands"]:
                print(f"Apply command: {command}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    if args.render_platform_hec_helper:
        render_platform_hec_helper(args, output_dir)
    if args.render_k8s:
        render_k8s(args, output_dir)
    if args.render_linux:
        render_linux(args, output_dir)
    write_text(output_dir / "metadata.json", json.dumps(metadata(args, output_dir), indent=2, sort_keys=True) + "\n")
    print(f"Rendered Splunk Observability OTel Collector assets to {output_dir}")
    for warning in warnings(args):
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
